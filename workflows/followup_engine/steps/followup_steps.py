from __future__ import annotations
from typing import Dict, Any
from datetime import datetime
import hashlib

from workflows.followup_engine.utils import crm
from workflows.followup_engine.utils import logger

def _one_paragraph(text: str) -> str:
  # Collapse whitespace and newlines for CSV safety
  return " ".join((text or "").split())

def _render_template(lead: Dict[str, Any]) -> Dict[str, str]:
  """
  Minimal placeholder template. You can later swap this for a real Jinja engine.
  Returns a dict with 'subject' and 'body'.
  """
  first_name = (lead.get("First Name") or lead.get("FirstName") or "there").strip()
  company = (lead.get("Company Name") or lead.get("Company") or "your team").strip()
  subject = f"Quick follow-up for {company}"
  body = (
      f"Hey {first_name}, just circling back on the workflow idea. "
      f"If it's not a priority, no worries — should I close this out or send a short loom with a concrete example for {company}?"
  )
  return {"subject": subject, "body": _one_paragraph(body)}

def send_followup_email_step(lead: Dict[str, Any], st, sequence_id: str = "default_followups", step_id: str = "f1", dry_run: bool = True) -> Dict[str, Any]:
  """
  Sends (or simulates sending) a follow-up email to a lead and updates the CRM.
  - Applies per-step idempotency using (lead_id|step_id|body) hash
  - Writes Follow-Up Stage and Responded? to CRM after send
  - Returns a dict like {"status": "ok"|"skip", "notes": str}
  """
  lead_id = lead.get("Email") or lead.get("id") or lead.get("DM Link") or "unknown"
  if not lead_id or lead_id == "unknown":
      logger.warn("Follow-up step missing lead identifier; skipping update.")
      return {"status": "skip", "notes": "no-lead-id"}

  tpl = _render_template(lead)
  subject, body = tpl["subject"], tpl["body"]

  idem = hashlib.sha256(f"{lead_id}|{step_id}|{body}".encode()).hexdigest()
  if st.was_sent(lead_id, sequence_id, step_id, idem):
      logger.info(f"[IDEMPOTENT] Already sent step {step_id} to {lead_id}; skipping.")
      return {"status": "skip", "notes": "already-sent-idempotent"}

  if dry_run:
      logger.info(f"[DRY RUN] Would send follow-up '{subject}' → {lead_id}")
  else:
      # TODO: integrate with your real mail client. For now, just log.
      logger.info(f"Sent follow-up '{subject}' → {lead_id}")
      st.mark_sent(lead_id, sequence_id, step_id, idem)
      # Immediately reflect in CRM: stage + leave Responded? as No
      crm.update_fields(lead_id, {
          "Follow-Up Stage": "Follow Up #1 Sent",
          "Responded?": "No"
      })

  # You can schedule the next step here by returning next_action_at
  return {"status": "ok", "notes": "sent-or-simulated", "next_action_at": None}
