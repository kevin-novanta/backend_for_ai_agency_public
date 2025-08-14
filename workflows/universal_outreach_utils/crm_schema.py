

"""
CRM schema & helpers for the Outreach system.

Centralizes:
- Column names (fieldnames) for DictReader/DictWriter
- Valid enums (Deliverability, stages)
- Normalizers & validators
- Convenience setters for writing stage results back to the CSV

This module mirrors your current CSV header precisely, including the new
Deliverability column and per‑stage Bounce Status fields.

Path suggestion: workflows/universal_outreach_utils/crm_schema.py
"""
from __future__ import annotations
from datetime import datetime
from typing import Dict, List, Iterable, Optional

# =============================
# Base columns (pre-stage)
# =============================
BASE_FIELDS: List[str] = [
    "Copywriting Document Link",
    "Client Name",
    "Email",
    "First Name",
    "Last Name",
    "Company Name",
    "Phone Number",
    "Address",
    "Custom 1",
    "Custom 2",
    "Custom 3",
    "Campaign Type",
    "Sequence Stage",
    "Messaging Status",
    "Responded?",
    "Replied Timestamp",
    "Qualified?",
    "Last Message Sent Timestamp",
    "Added To Retargeting Campaign?",
    "Retargeting Stage",
    "Retargeting Status",
    "Retargeting Responded?",
    "Retargetin Replied Time Stamp",
    "Last Message Sent Time Stamp",
    "Recycled?",
    "Lead Stage",
    "Last Contacted Date",
    "Campaign Assigned",
    "Outreach Channel",
    "Owner / Assigned To",
    "Deliverability",  # Dropdown: Safe, Risky, Catch All (we also normalize additional values)
]

# =============================
# Outreach stages you support
# =============================
STAGES: List[str] = [
    "Opener",
    "Follow Up 1",
    "Follow Up 2",
    "Follow Up 3",
    "Follow Up 4",
    "Follow Up 5",
    "Follow Up 6",
]

# For each stage, these sub-fields are stored in the CSV (order matches your sheet)
STAGE_SUBFIELDS: List[str] = [
    "Sender Used",
    "Time Sent",
    "Date Sent",
    "Subject Sent",
    "Body Sent",
]

BOUNCE_SUFFIX = "Bounce Status"


def stage_fields() -> List[str]:
    fields: List[str] = []
    for stage in STAGES:
        for sub in STAGE_SUBFIELDS:
            fields.append(f"{stage} {sub}")
        fields.append(f"{BOUNCE_SUFFIX} for {stage}")
    return fields


def NOTES_FIELD() -> List[str]:
    # Your current CSV uses a simple Notes column. If your file ever contains the historical
    # header with quotes (e.g. " \"\"Notes\"\""), update here accordingly.
    return ["Notes"]


def FIELDNAMES() -> List[str]:
    """Exact, ordered fieldnames for csv.DictWriter to match the sheet."""
    return BASE_FIELDS + stage_fields() + NOTES_FIELD()

# =============================
# Enums / normalizers
# =============================
# We normalize various verifier/provider statuses into your CRM dropdown values.
DELIVERABILITY_MAP = {
    # preferred canonical values
    "safe": "Safe",
    "risky": "Risky",
    "catch all": "Catch All",
    "catch-all": "Catch All",
    "accept all": "Catch All",
    # common verifier statuses we keep (even if not in the dropdown UI)
    "valid": "Safe",
    "deliverable": "Safe",
    "ok": "Safe",
    "unknown": "Unknown",
    "undeliverable": "Undeliverable",
    "invalid": "Undeliverable",
    # passthrough
    "": "",
    None: "",
}

ALLOWED_DELIVERABILITY = {"Safe", "Risky", "Catch All", "Unknown", "Undeliverable", ""}

# Bounce statuses you may write into the per-stage columns
BOUNCE_STATUSES = {"", "delivered", "bounced", "deferred", "blocked", "spam", "unknown"}


def normalize_deliverability(value: Optional[str]) -> str:
    v = (value or "").strip().lower()
    return DELIVERABILITY_MAP.get(v, value if (value or "") in ALLOWED_DELIVERABILITY else "")


def deliverability_is_allowed(value: str, allowed: Iterable[str]) -> bool:
    """Return True if normalized deliverability is in the allowed set."""
    norm = normalize_deliverability(value)
    return norm in set(allowed)

# =============================
# Convenience: write results for a given stage
# =============================

def set_stage_send_result(
    row: Dict[str, str],
    *,
    stage: str,
    sender_used: str,
    subject: str,
    body: str,
    sent_dt: Optional[datetime] = None,
    bounce_status: str = "",
) -> None:
    """
    Mutates `row` with send details for the stage and updates generic timestamps.
    `stage` must be one of STAGES (e.g., "Opener", "Follow Up 1").
    """
    if stage not in STAGES:
        raise ValueError(f"Unknown stage: {stage}")

    sent_dt = sent_dt or datetime.utcnow()

    row[f"{stage} Sender Used"] = sender_used or ""
    row[f"{stage} Subject Sent"] = subject or ""
    row[f"{stage} Body Sent"] = body or ""
    row[f"{stage} Time Sent"] = sent_dt.strftime("%H:%M:%S")
    row[f"{stage} Date Sent"] = sent_dt.strftime("%Y-%m-%d")

    b = (bounce_status or "").strip().lower()
    row[f"{BOUNCE_SUFFIX} for {stage}"] = b if b in BOUNCE_STATUSES else (b or "")

    # Generic bookkeeping
    iso_ts = sent_dt.isoformat(timespec="seconds")
    row["Last Message Sent Timestamp"] = iso_ts
    row["Last Message Sent Time Stamp"] = iso_ts  # keep legacy column in sync
    row["Last Contacted Date"] = row[f"{stage} Date Sent"]


# =============================
# Small helpers for sequence logic
# =============================

def ensure_defaults(row: Dict[str, str]) -> None:
    """Ensure required keys exist so DictWriter doesn't fail."""
    for k in FIELDNAMES():
        row.setdefault(k, "")


def is_new_or_opener_stage(row: Dict[str, str]) -> bool:
    stg = (row.get("Sequence Stage") or "").strip().lower()
    return stg in {"", "new", "opener", "opener sent"}


def next_stage(current: Optional[str]) -> str:
    """Return the next stage label; if at the end, return current.
    Examples:
      "" -> "Opener"
      "Opener" -> "Follow Up 1"
      "Opener sent" -> "Follow Up 1"
    """
    normalized = (current or "").strip()
    if normalized == "" or normalized.lower() in {"new", "opener"}:
        return "Opener"
    if normalized.lower().endswith(" sent"):
        base = normalized[:-5].strip().title()  # remove trailing " sent"
        try:
            idx = STAGES.index(base)
            return STAGES[min(idx + 1, len(STAGES) - 1)]
        except ValueError:
            return "Opener"
    try:
        idx = STAGES.index(normalized)
        return STAGES[min(idx + 1, len(STAGES) - 1)]
    except ValueError:
        return normalized


def passes_deliverability(row: Dict[str, str], allowed: Iterable[str]) -> bool:
    return deliverability_is_allowed(row.get("Deliverability", ""), allowed)


# =============================
# Pretty-print helpers (optional)
# =============================

def describe_schema() -> str:
    """Human-friendly summary of the CRM schema."""
    lines = []
    lines.append("Lead & Client Information + Campaign Tracking + Deliverability")
    for f in BASE_FIELDS:
        lines.append(f"  - {f}")
    lines.append("")
    lines.append("Per-stage fields (for: Opener, Follow Up 1..6):")
    for sub in STAGE_SUBFIELDS:
        lines.append(f"  - <Stage> {sub}")
    lines.append(f"  - {BOUNCE_SUFFIX} for <Stage>")
    lines.append("")
    lines.append("Notes")
    lines.append("  - Notes")
    return "\n".join(lines)