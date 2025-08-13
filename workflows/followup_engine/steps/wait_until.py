

from __future__ import annotations
from datetime import datetime, timedelta
from typing import Dict, Any

class WaitUntilStep:
    def __init__(self, step_id: str, days: int = 0, hours: int = 0, minutes: int = 0):
        self.step_id = step_id
        self.delta = timedelta(days=days, hours=hours, minutes=minutes)

    def run(self, lead: Dict[str, Any], st, sequence_id: str, dry_run: bool) -> Dict[str, Any]:
        next_time = datetime.utcnow() + self.delta
        # Persist the schedule for this lead/sequence
        st.advance(lead.get("Email") or lead.get("id") or "unknown", sequence_id, self.step_id, {"next_action_at": next_time})
        return {"status": "ok", "notes": "scheduled", "next_action_at": next_time}