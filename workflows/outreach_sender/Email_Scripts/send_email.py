import smtplib
import ssl
import json
import random
import re
from pathlib import Path
from email.mime.text import MIMEText 
from datetime import datetime

def remove_brackets(text):
    """Remove [] and anything between them."""
    return re.sub(r"\[[^\]]*\]", "", text)

# Load email accounts and limits
credentials_path = "/Users/kevinnovanta/backend_for_ai_agency/Creds/email_accounts.json"
with open(credentials_path, "r") as f:
    email_accounts = json.load(f)

# Track how many emails each inbox has sent today
sent_counts = {acc["email"]: 0 for acc in email_accounts}

# Load per-inbox daily limit from controls (fallback to 40)
controls_path = "/Users/kevinnovanta/backend_for_ai_agency/workflows/outreach_sender/Utils/opener_controls.json"
try:
    with open(controls_path, "r") as cf:
        controls = json.load(cf)
    DAILY_LIMIT = int(controls.get("per_inbox_limit", 40))
except Exception:
    DAILY_LIMIT = 40

# Reset tracking if needed (new day)
today = datetime.now().strftime("%Y-%m-%d")
tracking_path = Path(__file__).parent / "email_send_tracking.json"

if tracking_path.exists():
    with open(tracking_path, "r") as f:
        tracking_data = json.load(f)
    if tracking_data.get("date") != today:
        tracking_data = {"date": today, "sent_counts": sent_counts}
else:
    tracking_data = {"date": today, "sent_counts": sent_counts}

# Update local reference
sent_counts.update(tracking_data["sent_counts"])

def get_available_sender(sender_override=None):
    """
    Pick a sender under the per-inbox daily limit.
    If sender_override is provided, try to use it (if it exists and is under limit),
    otherwise fall back to normal rotation.
    """
    # Try explicit override first
    if sender_override:
        for acc in email_accounts:
            if acc.get("email") == sender_override:
                if sent_counts.get(acc["email"], 0) >= DAILY_LIMIT:
                    print(f"⚠️ Sender {sender_override} is at its daily limit ({DAILY_LIMIT}). Falling back to rotation.")
                    break
                return acc
        print(f"⚠️ sender_override '{sender_override}' not found in config. Falling back to rotation.")

    # Normal rotation: choose among accounts under limit
    available_accounts = [
        acc for acc in email_accounts if sent_counts.get(acc["email"], 0) < DAILY_LIMIT
    ]
    if not available_accounts:
        raise Exception("All inboxes have reached the daily limit.")
    return random.choice(available_accounts)

def send_email(to_email, subject, body, sender_override=None):
    sender = get_available_sender(sender_override=sender_override)
    sender_email = sender["email"]
    sender_password = sender["app_password"]
    smtp_server = sender.get("smtp_server", "smtp.gmail.com")
    smtp_port = sender.get("smtp_port", 587)

    # Sanitize AI output to remove any bracketed content before sending
    subject = remove_brackets(subject)
    body = remove_brackets(body)
    body = body if isinstance(body, str) else str(body)

    msg = MIMEText(body, "plain", "utf-8")

    msg["Subject"] = subject
    msg["From"] = sender_email
    msg["To"] = to_email

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls(context=context)
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, to_email, msg.as_string())

        sent_counts[sender_email] += 1
        tracking_data["sent_counts"] = sent_counts
        with open(tracking_path, "w") as f:
            json.dump(tracking_data, f, indent=2)

        print(f"✅ Email sent from {sender_email} to {to_email}")
        return True, sender_email
    except smtplib.SMTPAuthenticationError as e:
        print("❌ Authentication failed when sending via Gmail SMTP.")
        print("   • Ensure 2-Step Verification is ON for the sender account")
        print("   • Use a 16-character App Password (not the normal account password)")
        print("   • SMTP host should be smtp.gmail.com and port 587 with STARTTLS")
        print("   • For Google Workspace, verify SMTP AUTH is allowed in Admin console")
        print(f"   • Sender: {sender_email} | Error: {e}")
        return False, None
    except Exception as e:
        print(f"❌ Failed to send email from {sender_email} to {to_email}: {e}")
        return False, None