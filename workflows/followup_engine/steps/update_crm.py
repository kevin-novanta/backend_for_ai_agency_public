

from __future__ import annotations
from typing import Dict, Any
from workflows.followup_engine.utils import crm
from workflows.followup_engine.utils import logger

class UpdateCRMStep:
    def __init__(self, step_id: str, fields: Dict[str, str]):
        self.step_id = step_id
        self.fields = fields

    def run(self, lead: Dict[str, Any], st, sequence_id: str, dry_run: bool) -> Dict[str, Any]:
        lead_id = lead.get("Email") or lead.get("id") or lead.get("DM Link") or "unknown"
        if not lead_id or lead_id == "unknown":
            logger.warn("update_crm: missing lead identifier; skipping.")
            return {"status": "skip", "notes": "no-lead-id"}
        if dry_run:
            logger.info(f"[DRY RUN] Would update CRM for {lead_id} with {self.fields}")
        else:
            crm.update_fields(lead_id, self.fields)
        return {"status": "ok", "notes": "crm-updated"}