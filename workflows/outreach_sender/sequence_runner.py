import re
from workflows.followup_engine.utils.state_store import StateStore
import hashlib
from workflows.outreach_sender.AI_Intergrations.opener_ai_writer import generate_email
from workflows.outreach_sender.Email_Scripts.send_email import send_email as gmail_send_email
from workflows.outreach_sender.Utils.opener_utils import sanitize_email_fields

import csv
import json
from datetime import datetime
from pathlib import Path
import time
import random


def remove_brackets(text):
    import re
    return re.sub(r'\[.*?\]', '', text)

def strip_html_tags(text):
    import re
    # Replace <br> and <br/> with newlines
    text = re.sub(r'(?i)<br\s*/?>', '\n', text)
    # Remove all other HTML tags
    return re.sub(r'<[^>]+>', '', text)


def _norm(s: str) -> str:
    """Lowercase, trim, and collapse inner whitespace for robust comparisons."""
    return " ".join((s or "").split()).lower()

def _find_col(fieldnames, target_label: str) -> str:
    """Return the actual column name in CSV that matches target_label after normalization."""
    tgt = _norm(target_label)
    for name in fieldnames or []:
        if _norm(name) == tgt:
            return name
    return target_label  # fallback if not found


# Use actual Gmail send logic
def send_email(recipient_email, subject, body, sender_override=None):
    success, sender_email = gmail_send_email(recipient_email, subject, body, sender_override=sender_override)
    return success, sender_email

def run_opener_sequence():
    # Load config
    control_path = Path(__file__).parent / "Utils" / "opener_controls.json"
    with open(control_path, "r") as f:
        controls = json.load(f)

    allowed_days = controls["days_allowed"]
    start_hour = int(controls["start_time"].split(":")[0])
    end_hour = int(controls["end_time"].split(":")[0])
    daily_limit = controls["daily_limit"]
    per_inbox_limit = controls["per_inbox_limit"]
    send_interval_seconds = int(controls.get("send_interval_seconds", 120))  # default 2 minutes
    send_jitter_seconds = int(controls.get("send_jitter_seconds", 20))       # default +/- up to ~20s

    # Time check (use weekday abbreviations to match controls)
    now = datetime.now()
    weekday_abbr = now.strftime("%a")  # e.g., "Mon", "Tue", "Sat"
    if weekday_abbr not in allowed_days:
        print(f"⛔ Not a sending day. Today is {weekday_abbr}. Allowed: {allowed_days}")
        return
    if not (start_hour <= now.hour < end_hour):
        print(f"⛔ Outside sending window. Now: {now.strftime('%H:%M')} | Window: {start_hour:02d}:00-{end_hour:02d}:00")
        return

    # Preload CRM once, detect the actual Client Name column, and build lookup
    crm_path = Path("/Users/kevinnovanta/backend_for_ai_agency/data/leads/CRM_Leads/CRM_leads_copy.csv")
    with open(crm_path, newline="", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        fieldnames = reader.fieldnames or []
        client_col = _find_col(fieldnames, "Client Name")
        rows = list(reader)

    # Build normalized set/map of client names present
    clients_present = {}
    for r in rows:
        val = (r.get(client_col, "") or "").strip()
        if val:
            clients_present[_norm(val)] = val  # preserve original casing

    # Pitch message: explain what this sequence does and why
    print("🚀 Outreach Sequence Initiator")
    print("This tool sends personalized opener emails to selected client leads from your CRM,")
    print("updates their Messaging Status, and spaces sends to mimic human behavior.")
    print("You'll be prompted for the client name, and optionally can review/edit each email in test mode.")

    # Prompt until a valid client is entered
    while True:
        client_name_display = input("🔍 Enter the client name to run outreach for: ").strip()
        client_name_norm = _norm(client_name_display)
        if client_name_norm in clients_present:
            # preserve the exact casing from the CSV
            client_name_display = clients_present[client_name_norm]
            break
        print(f"⚠️ No leads found for client: '{client_name_display}'. Please try again.")

    # Initialize shared state store for this client (used for global stop/idempotency)
    st = StateStore(client=client_name_display)

    # Optional interactive testing mode
    interactive_mode = input("🧪 Interactive test mode? (y/N): ").strip().lower().startswith("y")
    sender_override = None
    auto_send_rest = False
    if interactive_mode:
        override_inp = input("✉️  (Optional) Force send from which sender email? Leave blank to keep rotation: ").strip()
        if override_inp:
            sender_override = override_inp

    # Load leads from preloaded rows using the resolved client column
    leads_to_send = []
    for row in rows:
        status = (row.get("Messaging Status", "") or "").strip().lower()
        row_client = _norm(row.get(client_col, ""))
        sequence_stage = (row.get("Sequence Stage", "") or "").strip().lower()
        responded = (row.get("Responded?", "") or "").strip().lower()
        if row_client != client_name_norm:
            continue
        if sequence_stage:
            continue
        if responded == "yes":
            continue
        if status not in ("", "untouched", "new"):
            continue
        leads_to_send.append(row)
        if len(leads_to_send) >= daily_limit:
            break

    if not leads_to_send:
        print(f"⚠️ No leads found for client: '{client_name_display}'")
        return

    print(f"📬 Preparing to send {len(leads_to_send)} opener emails...")

    inbox_count = max(1, daily_limit // per_inbox_limit)

    # Simulate batching by inbox
    for i, lead in enumerate(leads_to_send):
        inbox_index = i % inbox_count
        email = lead.get("Email")
        # Global stop gate: if this lead has replied or was stopped, skip all actions
        lead_id = email or lead.get("id") or "unknown"
        if st.should_stop_all(lead_id):
            print(f"⏭️  Skipping {lead_id}: globally stopped (replied/paused/done).")
            continue

        personalized = generate_email(lead)
        print("\n=== RAW AI OUTPUT ===")
        print("SUBJECT:", personalized["subject"])
        print("BODY_HTML:", personalized["body_html"])
        print("=====================\n")
        # Clean subject and body: remove brackets and strip HTML tags from body
        subject = remove_brackets(personalized["subject"])
        body = remove_brackets(personalized["body_html"])
        body = strip_html_tags(body)
        clean_subject, clean_body = sanitize_email_fields(subject, body)

        # Interactive confirmation (testing): preview and confirm
        if interactive_mode and not auto_send_rest:
            preview = clean_body
            if len(preview) > 500:
                preview = preview[:500] + "..."
            print("\n— Preview —")
            print(f"To: {email}")
            print(f"From: {sender_override or '(rotation)'}")
            print(f"Subject: {clean_subject}")
            print(f"Body (first 500 chars):\n{preview}\n")

            # Allow edits before decision
            edit_choice = input("Edit subject/body before sending? (y/N): ").strip().lower()
            if edit_choice == "y":
                new_subject = input("✏️ New subject (leave blank to keep): ").strip()
                if new_subject:
                    clean_subject = new_subject

                print("✏️ Enter new body (press Enter for new line; press Enter twice on a blank line to finish):")
                new_body_lines = []
                while True:
                    try:
                        line = input()
                    except EOFError:
                        break
                    if line == "":
                        break
                    new_body_lines.append(line)

                if new_body_lines:
                    edited_text = "\n".join(new_body_lines)
                    clean_body = edited_text

            choice = input("Send this email? [y]es / [s]kip / send [a]ll / [q]uit: ").strip().lower()
            if choice == "q":
                print("🛑 Quitting early by user request.")
                break
            if choice == "s":
                print("⏭️  Skipped.")
                continue
            if choice == "a":
                auto_send_rest = True
            # else proceed with send

        print("=== DEBUG: Email being sent ===")
        print(f"TO: {email}")
        print(f"SUBJECT: {clean_subject}")
        print("BODY HTML:\n", clean_body)
        print("=== END DEBUG ===")
        success, sender_used = send_email(email, clean_subject, clean_body, sender_override=sender_override)
        if success:
            print(f"✅ Email sent from {sender_used} to {email}")
            print(f"✅ Sent to {email}")
            lead["Messaging Status"] = "Opener Sent"
            lead["Campaign Type"] = "Opener"
            lead["Sequence Stage"] = "Sent"
            lead["Lead Stage"] = "New"
            lead["Last Contacted Date"] = datetime.now().strftime("%Y-%m-%d")
            lead["Campaign Assigned"] = "1"
            lead["Outreach Channel"] = "Email"
            lead["Owner / Assigned To"] = sender_used
            # Placeholder for bounce/failure tracking
            lead["Bounce Status"] = ""
            # Log opener email content, time, and date (save only cleaned body as a single paragraph)
            one_para_body = clean_body.replace("\n", " ")
            lead["Opener Email"] = one_para_body
            lead["Opener Time Sent"] = datetime.now().strftime("%H:%M:%S")
            lead["Opener Date Sent"] = datetime.now().strftime("%Y-%m-%d")

            # Per-step idempotency marker for opener step in sequence 'opener_outreach'
            step_id = "opener"
            sequence_id = "opener_outreach"
            idem = hashlib.sha256(f"{lead_id}|{step_id}|{one_para_body}".encode()).hexdigest()
            st.mark_sent(lead_id, sequence_id, step_id, idem)

            # Immediately update CRM CSV for this lead
            with open(crm_path, "r", newline="", encoding="utf-8") as csvfile:
                csvfile_data = list(csv.DictReader(csvfile))
            with open(crm_path, "w", newline="", encoding="utf-8") as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=csvfile_data[0].keys())
                writer.writeheader()
                for row in csvfile_data:
                    if row.get("Email") == lead.get("Email"):
                        row["Messaging Status"] = lead.get("Messaging Status", row.get("Messaging Status", ""))
                        row["Campaign Type"] = lead.get("Campaign Type", row.get("Campaign Type", ""))
                        row["Sequence Stage"] = lead.get("Sequence Stage", row.get("Sequence Stage", ""))
                        row["Lead Stage"] = lead.get("Lead Stage", row.get("Lead Stage", ""))
                        row["Last Contacted Date"] = lead.get("Last Contacted Date", row.get("Last Contacted Date", ""))
                        row["Campaign Assigned"] = lead.get("Campaign Assigned", row.get("Campaign Assigned", ""))
                        row["Outreach Channel"] = lead.get("Outreach Channel", row.get("Outreach Channel", ""))
                        row["Owner / Assigned To"] = lead.get("Owner / Assigned To", row.get("Owner / Assigned To", ""))
                        if "Bounce Status" in lead:
                            row["Bounce Status"] = lead.get("Bounce Status", row.get("Bounce Status", ""))
                        # Save only cleaned body as a single paragraph for Opener Email
                        opener_email_val = lead.get("Opener Email", row.get("Opener Email", ""))
                        if opener_email_val is not None:
                            row["Opener Email"] = opener_email_val.replace("\n", " ")
                        else:
                            row["Opener Email"] = ""
                        row["Opener Time Sent"] = lead.get("Opener Time Sent", row.get("Opener Time Sent", ""))
                        row["Opener Date Sent"] = lead.get("Opener Date Sent", row.get("Opener Date Sent", ""))
                    writer.writerow(row)

            # Pacing: wait between sends to mimic human behavior
            delay = send_interval_seconds + random.randint(-send_jitter_seconds, send_jitter_seconds)
            if delay < 0:
                delay = send_interval_seconds // 2
            print(f"⏳ Waiting {delay}s before next send...")
            time.sleep(delay)
        else:
            print(f"❌ Failed to send to {email}")
            lead["Bounce Status"] = "Failed to send"

    # Reload full CRM data and update relevant rows
    with open(crm_path, "r", newline="", encoding="utf-8") as csvfile:
        csvfile_data = list(csv.DictReader(csvfile))

    # Reopen CRM for rewriting
    with open(crm_path, "w", newline="", encoding="utf-8") as csvfile:
        fieldnames = csvfile_data[0].keys()
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        for row in csvfile_data:
            if _norm(row.get(client_col, "")) == client_name_norm and row.get("Messaging Status", "").strip().lower() in ("", "untouched", "new"):
                # Find the updated status in leads_to_send
                matching = next((lead for lead in leads_to_send if lead["Email"] == row["Email"]), None)
                if matching:
                    row["Messaging Status"] = matching.get("Messaging Status", row.get("Messaging Status", ""))
                    row["Campaign Type"] = matching.get("Campaign Type", row.get("Campaign Type", ""))
                    row["Sequence Stage"] = matching.get("Sequence Stage", row.get("Sequence Stage", ""))
                    row["Lead Stage"] = matching.get("Lead Stage", row.get("Lead Stage", ""))
                    row["Last Contacted Date"] = matching.get("Last Contacted Date", row.get("Last Contacted Date", ""))
                    row["Campaign Assigned"] = matching.get("Campaign Assigned", row.get("Campaign Assigned", ""))
                    row["Outreach Channel"] = matching.get("Outreach Channel", row.get("Outreach Channel", ""))
                    row["Owner / Assigned To"] = matching.get("Owner / Assigned To", row.get("Owner / Assigned To", ""))
                    if "Bounce Status" in matching:
                        row["Bounce Status"] = matching.get("Bounce Status", row.get("Bounce Status", ""))
                    # Update Opener Email, Time Sent, and Date Sent
                    opener_email_val = matching.get("Opener Email", row.get("Opener Email", ""))
                    if opener_email_val is not None:
                        row["Opener Email"] = opener_email_val.replace("\n", " ")
                    else:
                        row["Opener Email"] = ""
                    row["Opener Time Sent"] = matching.get("Opener Time Sent", row.get("Opener Time Sent", ""))
                    row["Opener Date Sent"] = matching.get("Opener Date Sent", row.get("Opener Date Sent", ""))
            writer.writerow(row)


if __name__ == "__main__":
    run_opener_sequence()