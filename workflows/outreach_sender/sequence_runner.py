import requests
import os

import re
from workflows.outreach_sender.AI_Intergrations.opener_ai_writer import generate_email as gen_opener_email
from workflows.outreach_sender.AI_Intergrations.opener_ai_writer import generate_generic_subject
from workflows.outreach_sender.AI_Intergrations.personalizer import personalize_email
from workflows.outreach_sender.AI_Intergrations.personalizer import personalize_subject
from workflows.outreach_sender.Email_Scripts.send_email import send_email as gmail_send_email
from workflows.outreach_sender.Utils.opener_utils import sanitize_email_fields
from workflows.outreach_sender.Utils.preflight import preflight_filter
from workflows.outreach_sender.Utils.parallel_dispatcher import run_parallel_dispatch

import csv
import json
from datetime import datetime
from pathlib import Path
import time
import random
import sys

from datetime import datetime

# =====================
# Logging: mirror all prints to logs/outreach.log with timestamps
# =====================
from pathlib import Path as _PathForLog
import atexit as _atexit_for_log
import datetime as _dt_for_log

_LOG_DIR = _PathForLog(__file__).replace("sequence_runner.py", "logs") if hasattr(_PathForLog(__file__), 'replace') else _PathForLog(__file__).parent / "logs"
try:
    # Fallback to normal path logic
    _LOG_DIR = _PathForLog(__file__).parent / "logs"
except Exception:
    pass
_LOG_DIR.mkdir(parents=True, exist_ok=True)
_LOG_FILE = _LOG_DIR / "outreach.log"

class _Tee:
    def __init__(self, console_stream, file_path):
        self.console = console_stream
        self.file = open(file_path, "a", encoding="utf-8", buffering=1)
        self._buffer = ""
    def write(self, data):
        # Ensure str
        s = str(data)
        # Split on lines but keep newlines
        for chunk in s.splitlines(True):
            ts = _dt_for_log.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if chunk.endswith("\n"):
                # Complete line
                line = self._buffer + chunk
                self._buffer = ""
                prefix = f"[{ts}] "
                try:
                    self.console.write(prefix + line)
                except Exception:
                    pass
                try:
                    self.file.write(prefix + line)
                except Exception:
                    pass
            else:
                # Partial line; buffer until newline
                self._buffer += chunk
    def flush(self):
        try:
            self.console.flush()
        except Exception:
            pass
        try:
            self.file.flush()
        except Exception:
            pass
    def isatty(self):
        try:
            return self.console.isatty()
        except Exception:
            return False

# Install tee for stdout and stderr
_orig_stdout = sys.stdout
_orig_stderr = sys.stderr
_tee_out = _Tee(_orig_stdout, _LOG_FILE)
_tee_err = _Tee(_orig_stderr, _LOG_FILE)
sys.stdout = _tee_out
sys.stderr = _tee_err

# Ensure files close on exit
def _close_teelog():
    try:
        _tee_out.file.close()
    except Exception:
        pass
    try:
        _tee_err.file.close()
    except Exception:
        pass

_atexit_for_log.register(_close_teelog)

print(f"🧾 Logging to {_LOG_FILE} (console + file). Session start.")


# Simple logger helper for step-wise logging
def log_step(msg):
    print(f"[STEP] {msg}")


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


# Helper to persist owner assignment to the CRM for a specific lead email, preserving headers and quoting.
def _persist_owner_assignment(crm_path: Path, lead_email: str, owner_email: str) -> None:
    """Write Owner / Assigned To to CSV for a specific lead email, preserving headers and quoting."""
    try:
        with open(crm_path, "r", newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        if not rows:
            return
        fieldnames = rows[0].keys()
        with open(crm_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
            writer.writeheader()
            for r in rows:
                if (r.get("Email") or "") == (lead_email or ""):
                    r["Owner / Assigned To"] = owner_email
                writer.writerow(r)
    except Exception as e:
        print(f"⚠️ Failed to persist owner assignment for {lead_email}: {e}")


# Use actual Gmail send logic
def send_email(recipient_email, subject, body, sender_override=None):
    success, sender_email = gmail_send_email(recipient_email, subject, body, sender_override=sender_override)
    return success, sender_email

def run_opener_sequence():
    # Load config
    control_path = Path(__file__).parent / "Utils" / "opener_controls.json"
    with open(control_path, "r") as f:
        controls = json.load(f)
        log_step("Loaded opener_controls.json with run settings.")

        # Deliverability filter controls (default: disabled)
        use_deliv_filter = bool(controls.get("use_deliverability_filter", False))
        allowed_deliv = list(controls.get("allowed_deliverability_statuses", [])) or []

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
    log_step(f"Day/time check passed. Allowed days: {allowed_days}, Window: {start_hour:02d}:00-{end_hour:02d}:00")

    # Preload CRM once, detect the actual Client Name column, and build lookup
    crm_path = Path("/Users/kevinnovanta/backend_for_ai_agency/data/leads/CRM_Leads/CRM_leads_copy.csv")
    with open(crm_path, newline="", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        fieldnames = reader.fieldnames or []
        client_col = _find_col(fieldnames, "Client Name")
        rows = list(reader)
        log_step(f"Loaded CRM leads from {crm_path}. Total rows: {len(rows)} | Client column: {client_col}")

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

    log_step(f"Selected client: {client_name_display}")

    # Optional interactive testing mode
    interactive_mode = input("🧪 Interactive test mode? (y/N): ").strip().lower().startswith("y")
    sender_override = None
    auto_send_rest = False
    if interactive_mode:
        override_inp = input("✉️  (Optional) Force send from which sender email? Leave blank to keep rotation: ").strip()
        if override_inp:
            sender_override = override_inp

    log_step("Interactive mode evaluated; proceeding to lead filtering.")

    # Use centralized preflight (verification + allow-list + basic gates)
    leads_to_send, skip_logs, settings_logs = preflight_filter(
        rows,
        controls,
        client_col_name=client_col,
        selected_client_norm=client_name_norm,
    )

    # Print settings summary and any skip reasons
    for msg in settings_logs:
        log_step(msg)
    for msg in skip_logs:
        print(msg)

    # Enforce daily limit
    if len(leads_to_send) > daily_limit:
        leads_to_send = leads_to_send[:daily_limit]

    log_step(f"Filtered to {len(leads_to_send)} eligible leads for outreach (daily_limit={daily_limit}).")

    if not leads_to_send:
        print(f"⚠️ No leads found for client: '{client_name_display}'")
        return

    print(f"📬 Preparing to send {len(leads_to_send)} opener emails...")

    # Compute inbox_count after final filtering
    inbox_count = max(1, daily_limit // per_inbox_limit)


    # Load sender pool from controls (with fallback to Creds/email_accounts.json if empty)
    sender_pool = [s.strip() for s in controls.get("sender_pool", []) if (s or "").strip()]
    # If no sender_pool provided in controls, attempt to derive it from Creds/email_accounts.json
    if not sender_pool:
        try:
            creds_path = Path("/Users/kevinnovanta/backend_for_ai_agency/Creds/email_accounts.json")
            if creds_path.exists():
                with open(creds_path, "r", encoding="utf-8") as cf:
                    creds_json = json.load(cf)

                def _extract_emails(x):
                    emails = []
                    # Recursively walk JSON and collect strings that look like emails
                    if isinstance(x, dict):
                        for k, v in x.items():
                            emails.extend(_extract_emails(v))
                    elif isinstance(x, list):
                        for it in x:
                            emails.extend(_extract_emails(it))
                    elif isinstance(x, str):
                        # very light email pattern; avoids pulling API keys etc.
                        if re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", x.strip()):
                            emails.append(x.strip())
                    return emails

                extracted = _extract_emails(creds_json)
                # De-dup while preserving order
                seen = set()
                ordered = []
                for e in extracted:
                    if e not in seen:
                        seen.add(e)
                        ordered.append(e)
                sender_pool = ordered
                if sender_pool:
                    print(f"📫 Loaded {len(sender_pool)} sender(s) from Creds/email_accounts.json")
        except Exception as e:
            print(f"⚠️ Could not load sender_pool from Creds/email_accounts.json: {e}")

    log_step(f"Sender pool resolved: {sender_pool if sender_pool else '[]'}")
    # Build a deterministic rotation list of actual sender emails for each inbox slot
    # Optional strict mode: if a pool exists but is smaller than inbox_count, warn (still repeats by default)
    if sender_pool and len(sender_pool) < inbox_count:
        print(f"⚠️ sender_pool has {len(sender_pool)} inbox(es) but inbox_count is {inbox_count}. Repeating pool to fill slots.")
    # (rest of rotation logic continues below)

    # --- Dispatch mode selection ---
    # If interactive_mode is ON, keep the existing sequential flow (you confirm each send).
    # If interactive_mode is OFF, use the parallel dispatcher to run one worker per inbox.
    #
    # Build a deterministic rotation count to help choose_inbox_cb:
    rr_index = 0

    # Helper to pick/remember an inbox for a lead, and persist that owner to the CRM immediately.
    def choose_inbox_cb(lead: dict, senders: list[str]) -> str:
        nonlocal rr_index
        # If this lead already has an explicit owner that matches a real inbox, keep it
        current_owner = (lead.get("Owner / Assigned To", "") or "").strip()
        if current_owner in senders:
            return current_owner
        # Otherwise choose round-robin
        inbox = senders[rr_index % len(senders)]
        rr_index += 1
        # Persist the owner so other processes won't double-assign
        _persist_owner_assignment(crm_path, lead.get("Email", ""), inbox)
        lead["Owner / Assigned To"] = inbox
        print(f"📌 Assigned inbox for {lead.get('Email')} → '{inbox}' (persisted to CRM)")
        return inbox

    # The core "send one opener" operation used by both modes.
    # It mirrors your previous per-lead logic, but receives the chosen inbox explicitly.
    def send_one_opener(inbox_email: str, lead: dict) -> dict:
        email = lead.get("Email")

        # === Generate a generic opener ===
        base_email = gen_opener_email(lead)  # {"subject": "...", "body_html": "..."}
        log_step("Generated generic opener email via opener_ai_writer.")

        # === Generate generic subject ===
        subj_data = generate_generic_subject()
        base_email["subject"] = subj_data.get("subject", base_email.get("subject", "Quick question"))
        log_step("Generated generic subject via subject_prompt.")

        # === Personalize body ===
        final_email = personalize_email(
            base_subject=base_email.get("subject", ""),
            base_body_html=base_email.get("body_html", ""),
            lead=lead,
            prompt_override=None
        )
        log_step("Personalized email body via personalizer.")

        # === Personalize subject ===
        subj_final = personalize_subject(final_email.get("subject", ""), lead)
        final_email["subject"] = subj_final.get("subject", final_email.get("subject", ""))
        log_step("Personalized subject via subject_personalizer.")

        print("\n=== RAW AI OUTPUT (after personalization) ===")
        print("SUBJECT:", final_email.get("subject", ""))
        print("BODY_HTML:", final_email.get("body_html", ""))
        print("============================================\n")

        subject = final_email.get("subject", "")
        body = final_email.get("body_html", "")

        if not (subject or "").strip():
            raise RuntimeError(f"Empty subject generated for {email}")

        clean_subject, clean_body = sanitize_email_fields(subject, body)
        log_step(f"Sanitized subject/body. Final subject: {clean_subject}")

        if not (clean_subject or "").strip():
            raise RuntimeError(f"Subject became empty after sanitization for {email}")

        # In interactive mode, preview and require explicit confirmation
        if interactive_mode:
            preview = clean_body if len(clean_body) <= 500 else (clean_body[:500] + "...")
            print("\n— Preview —")
            print(f"To: {email}")
            print(f"From: {inbox_email}")
            print(f"Subject: {clean_subject}")
            print(f"Body (first 500 chars):\n{preview}\n")
            choice = input("Send this email? [y]es / [s]kip / [q]uit: ").strip().lower()
            if choice == "q":
                raise KeyboardInterrupt("User aborted in interactive mode.")
            if choice != "y":
                print("⏭️  Skipped (interactive mode).")
                return {"ok": False, "skipped": True}

        print("=== DEBUG: Email being sent ===")
        print(f"TO: {email}")
        print(f"SUBJECT: {clean_subject}")
        print("BODY HTML:\n", clean_body)
        print("=== END DEBUG ===")

        log_step(f"Ready to send email to {email} from {inbox_email}.")
        success, sender_used = send_email(email, clean_subject, clean_body, sender_override=inbox_email)
        if not success:
            log_step("Email failed to send; marking bounce status.")
            return {"ok": False, "error": "send_failed"}

        _now = datetime.now()
        # Update the in-memory lead for reconciliation
        lead["Messaging Status"] = "Opener Sent"
        lead["Campaign Type"] = "Opener"
        lead["Sequence Stage"] = "Opener Sent"
        lead["Lead Stage"] = "New"
        lead["Last Contacted Date"] = _now.strftime("%Y-%m-%d")
        lead["Campaign Assigned"] = "1"
        lead["Outreach Channel"] = "Email"
        lead["Owner / Assigned To"] = sender_used
        lead["Bounce Status for Opener"] = ""
        lead["Opener Sender Used"] = sender_used
        lead["Opener Subject Sent"] = clean_subject
        lead["Opener Body Sent"] = clean_body
        lead["Opener Time Sent"] = _now.strftime("%H:%M:%S")
        lead["Opener Date Sent"] = _now.strftime("%Y-%m-%d")

        # Persist the opener fields to CSV immediately
        try:
            with open(crm_path, "r", newline="", encoding="utf-8") as f:
                csv_rows = list(csv.DictReader(f))
            required_cols = [
                "Opener Sender Used", "Opener Subject Sent", "Opener Body Sent",
                "Opener Time Sent", "Opener Date Sent", "Bounce Status for Opener"
            ]
            existing_cols = list(csv_rows[0].keys()) if csv_rows else []
            fieldnames_local = list(dict.fromkeys(existing_cols + required_cols))
            with open(crm_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames_local, quoting=csv.QUOTE_ALL)
                writer.writeheader()
                for row in csv_rows:
                    if row.get("Email") == lead.get("Email"):
                        row["Messaging Status"] = lead.get("Messaging Status", row.get("Messaging Status", ""))
                        row["Campaign Type"] = lead.get("Campaign Type", row.get("Campaign Type", ""))
                        row["Sequence Stage"] = lead.get("Sequence Stage", row.get("Sequence Stage", ""))
                        row["Lead Stage"] = lead.get("Lead Stage", row.get("Lead Stage", ""))
                        row["Last Contacted Date"] = lead.get("Last Contacted Date", row.get("Last Contacted Date", ""))
                        row["Campaign Assigned"] = lead.get("Campaign Assigned", row.get("Campaign Assigned", ""))
                        row["Outreach Channel"] = lead.get("Outreach Channel", row.get("Outreach Channel", ""))
                        row["Owner / Assigned To"] = lead.get("Owner / Assigned To", row.get("Owner / Assigned To", ""))
                        row["Bounce Status for Opener"] = lead.get("Bounce Status for Opener", row.get("Bounce Status for Opener", ""))
                        row["Opener Sender Used"] = lead.get("Opener Sender Used", row.get("Opener Sender Used", ""))
                        row["Opener Subject Sent"] = lead.get("Opener Subject Sent", row.get("Opener Subject Sent", ""))
                        row["Opener Body Sent"] = lead.get("Opener Body Sent", row.get("Opener Body Sent", ""))
                        row["Opener Time Sent"] = lead.get("Opener Time Sent", row.get("Opener Time Sent", ""))
                        row["Opener Date Sent"] = lead.get("Opener Date Sent", row.get("Opener Date Sent", ""))
                    for col in fieldnames_local:
                        if col not in row:
                            row[col] = ""
                    writer.writerow(row)
        except Exception as e:
            print(f"⚠️ Failed to persist opener fields for {email}: {e}")

        return {
            "ok": True,
            "subject": clean_subject,
            "body_html": clean_body,
            "bounce_status": "none",
            "timestamp": _now.isoformat(timespec="seconds"),
            "sender_used": sender_used,
        }

    # Result hook (already persisted above; kept for symmetry/metrics)
    def on_result_cb(lead: dict, inbox: str, result: dict) -> None:
        if result.get("ok"):
            print(f"[DISPATCH] Persisted opener for {lead.get('Email')} via {inbox}")
        else:
            print(f"[DISPATCH] Not sent for {lead.get('Email')} (skipped or failed).")

    if interactive_mode:
        # === Original sequential flow with confirmation ===
        # (Single-threaded; identical to your previous per-lead loop, but we reuse send_one_opener)
        # Compute inbox_count after final filtering
        inbox_count = max(1, daily_limit // per_inbox_limit)

        # Optional strict mode warning for small pools
        if sender_pool and len(sender_pool) < inbox_count:
            print(f"⚠️ sender_pool has {len(sender_pool)} inbox(es) but inbox_count is {inbox_count}. Repeating pool to fill slots.")

        for i, lead in enumerate(leads_to_send):
            inbox_index = i % max(1, len(sender_pool)) if sender_pool else 0
            # Choose a real inbox email if available; otherwise keep rotation label
            chosen_inbox = sender_pool[inbox_index] if sender_pool else (sender_override or f"slot:{inbox_index}")

            # Respect existing owner assignment if it points to a real inbox
            assigned_owner = (lead.get('Owner / Assigned To', '') or '').strip()
            if assigned_owner and sender_pool and assigned_owner not in sender_pool:
                # It was a 'slot:*' style or something else — allow reassignment to a real inbox
                assigned_owner = ''
            if assigned_owner and assigned_owner != chosen_inbox:
                print(f"⏭️  Skipping {lead.get('Email')}: already assigned to '{assigned_owner}', not '{chosen_inbox}'.")
                continue
            if not assigned_owner:
                _persist_owner_assignment(crm_path, lead.get("Email", ""), chosen_inbox)
                lead["Owner / Assigned To"] = chosen_inbox
                print(f"📌 Assigned inbox for {lead.get('Email')} → '{chosen_inbox}' (persisted to CRM)")
                log_step(f"Assigning inbox '{chosen_inbox}' to lead {lead.get('Email')}")

            # Send with interactive confirmation inside send_one_opener()
            res = send_one_opener(chosen_inbox, lead)
            if res.get("ok"):
                print(f"✅ Sent to {lead.get('Email')}")
            else:
                print(f"⏭️  Not sent to {lead.get('Email')} (skipped or failed).")

            # Manual pacing between interactive sends (keep your existing cadence)
            delay = send_interval_seconds + random.randint(-send_jitter_seconds, send_jitter_seconds)
            if delay < 0:
                delay = send_interval_seconds // 2
            print(f"⏳ Waiting {delay}s before next send...")
            time.sleep(delay)

    else:
        # === Parallel dispatch mode (no prompts; respects jitter and limits per inbox) ===
        min_j = max(1, send_interval_seconds - send_jitter_seconds)
        max_j = send_interval_seconds + send_jitter_seconds
        print(f"[DISPATCH] Parallel mode ON. Jitter window: {min_j}-{max_j}s | per-inbox cap: {per_inbox_limit} | global cap: {daily_limit}")

        run_parallel_dispatch(
            leads=leads_to_send,
            sender_pool=sender_pool if sender_pool else [sender_override] if sender_override else [],
            send_one_cb=send_one_opener,
            choose_inbox_cb=choose_inbox_cb,
            on_result_cb=on_result_cb,
            jitter_seconds=(min_j, max_j),
            per_inbox_daily_limit=per_inbox_limit,
            global_daily_limit=daily_limit,
            max_inboxes=None,  # or set a cap
        )

    log_step("Starting final reconciliation pass for untouched/new leads.")
    # Reload full CRM data and update relevant rows
    with open(crm_path, "r", newline="", encoding="utf-8") as csvfile:
        csvfile_data = list(csv.DictReader(csvfile))

    # Reopen CRM for rewriting
    required_cols = [
        "Opener Sender Used", "Opener Subject Sent", "Opener Body Sent",
        "Opener Time Sent", "Opener Date Sent", "Bounce Status for Opener"
    ]
    existing_cols = list(csvfile_data[0].keys()) if csvfile_data else []
    fieldnames = list(dict.fromkeys(existing_cols + required_cols))
    with open(crm_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
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
                    if "Bounce Status for Opener" in matching:
                        row["Bounce Status for Opener"] = matching.get("Bounce Status for Opener", row.get("Bounce Status for Opener", ""))
                    # Update opener NEW columns
                    row["Opener Sender Used"] = matching.get("Opener Sender Used", row.get("Opener Sender Used", ""))
                    row["Opener Subject Sent"] = matching.get("Opener Subject Sent", row.get("Opener Subject Sent", ""))
                    row["Opener Body Sent"] = matching.get("Opener Body Sent", row.get("Opener Body Sent", ""))
                    row["Opener Time Sent"] = matching.get("Opener Time Sent", row.get("Opener Time Sent", ""))
                    row["Opener Date Sent"] = matching.get("Opener Date Sent", row.get("Opener Date Sent", ""))
            # Ensure all required columns exist for DictWriter
            for col in fieldnames:
                if col not in row:
                    row[col] = ""
            writer.writerow(row)

    log_step("Final reconciliation complete. Script finished.")


if __name__ == "__main__":
    run_opener_sequence()