from __future__ import annotations
from typing import Dict, Any

def build_opener_preview(lead: Dict[str, Any]) -> str:
  """Return a short preview string for an opener email (for logs/UI)."""
  company = (lead.get("Company Name") or lead.get("Company") or "their company").strip()
  return f"Intro about a workflow audit for {company}"
