from __future__ import annotations
from typing import Dict, Any
import hashlib
from datetime import datetime, UTC

from workflows.followup_engine.utils import crm
from workflows.followup_engine.utils import logger


def _one_paragraph(text: str) -> str:
    return " ".join((text or "").split())


def render_template(template_name: str, lead: Dict[str, Any]) -> Dict[str, str]:
    fn = (lead.get("First Name") or lead.get("FirstName") or "there").strip()
    company = (lead.get("Company Name") or lead.get("Company") or "your team").strip()

    if template_name == "followup_1":
        body = (
            f"Hey {fn}, circling back on the workflow idea. "
            f"Want a 60-sec loom for {company}, or should I close this out?"
        )
    elif template_name == "followup_2":
        body = (
            f"{fn}, quick nudge — happy to send a 60-sec loom of the exact workflow for {company}. "
            f"If now’s not the time, I’ll close the loop."
        )
    else:
        body = (
            f"Hey {fn}, following up — would a short loom walkthrough for {company} be useful?"
        )

    return {"body": _one_paragraph(body)}


class SendEmailStep:
    def __init__(
        self,
        subject: str,
        template: str,
        step_id: str,
        mode: str = "static",
        llm_opts: dict | None = None,
    ):
        self.subject = subject
        self.template = template
        self.step_id = step_id
        self.mode = (mode or "static").lower()
        self.llm_opts = llm_opts or {}

    def run(
        self, lead: Dict[str, Any], st, sequence_id: str, dry_run: bool
    ) -> Dict[str, Any]:
        lead_id = (
            lead.get("Email") or lead.get("id") or lead.get("DM Link") or "unknown"
        )
        if not lead_id or lead_id == "unknown":
            logger.warn("send_email: missing lead identifier; skipping.")
            return {"status": "skip", "notes": "no-lead-id"}

        # Enforce allowed send window / daily limits (fail-closed in all modes)
        try:
            from workflows.followup_engine.utils.send_window_status import check_send_window
            sender_inbox = lead.get("Sender") or None  # optional inbox field
            allowed, reason = check_send_window(inbox=sender_inbox, dry_run=dry_run)
            if not allowed:
                logger.info(f"⏸️  Outside allowed send window ({reason}); skipping {lead_id}.")
                return {"status": "skip", "notes": f"send-window:{reason}"}
        except Exception as e:
            logger.error(f"send_window check error ({e}); skipping {lead_id}.")
            return {"status": "skip", "notes": "send-window:error"}

        # Choose template mode
        subject_for_send = self.subject
        if self.mode == "llm":
            try:
                from workflows.followup_engine.AI_Integrations.llm_client import (
                    render_llm_email,
                )

                tpl = render_llm_email(
                    self.template,
                    lead,
                    fallback_subject=self.subject,
                    llm_opts=self.llm_opts,
                    context={},
                )
                body = tpl.get("body_one_paragraph") or tpl.get("body") or ""
                subject_for_send = (tpl.get("subject") or self.subject).strip()
            except Exception as e:
                logger.warn(f"LLM mode failed ({e}); falling back to static template.")
                tpl = render_template(self.template, lead)
                body = tpl["body"]
        else:
            tpl = render_template(self.template, lead)
            body = tpl["body"]

        # Per-step idempotency
        idem = hashlib.sha256(
            f"{lead_id}|{self.step_id}|{body}".encode()
        ).hexdigest()
        if st.was_sent(lead_id, sequence_id, self.step_id, idem):
            logger.info(
                f"[IDEMPOTENT] Already sent {self.step_id} to {lead_id}; skipping."
            )
            return {"status": "skip", "notes": "already-sent-idempotent"}

        if dry_run:
            logger.info(f"[DRY RUN] Would send '{subject_for_send}' → {lead_id}")
        else:
            # TODO: integrate real mail client here
            logger.info(f"Sent '{subject_for_send}' → {lead_id}")
            st.mark_sent(lead_id, sequence_id, self.step_id, idem)
            # Only stamp the send time; Follow-Up Stage is set by the runner before send
            crm.update_fields(
                lead_id,
                {
                    "Last Message Sent Timestamp": datetime.now(UTC).isoformat(),
                },
            )

        return {"status": "ok", "notes": "sent-or-simulated"}