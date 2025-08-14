from __future__ import annotations

#!/usr/bin/env python3
"""
Execute a follow‑up sequence once per run (cron‑friendly).

Usage:
  python3 -m workflows.followup_engine.sequence_runner --sequence opener_followups [--live|--dry-run] [--max 50] [--client CLIENT] [--email someone@example.com] [--bypass-time]

Notes:
- Runs at most `--max` actionable steps per invocation (default 50) so you can cron this.
- Respects per‑lead state in SQLite (stop/replied/done) and `wait_until` schedules.
- Uses send window/quotas inside the SendEmailStep itself.
"""

import argparse
import csv
from datetime import datetime, UTC
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

# Ensure project root on path so `import workflows.*` works
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from workflows.followup_engine.utils import logger
from workflows.followup_engine.utils.state_store import StateStore
from workflows.followup_engine.utils.sequence_loader import load_sequences_cfg
from workflows.followup_engine.utils import crm

from workflows.followup_engine.steps.send_email import SendEmailStep
from workflows.followup_engine.steps.wait_until import WaitUntilStep
from workflows.followup_engine.steps.update_crm import UpdateCRMStep

from workflows.followup_engine.utils.send_window_status import check_send_window


def _parse_iso(dt_str: Optional[str]) -> Optional[datetime]:
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except Exception:
        return None


def _norm(s: Optional[str]) -> str:
    return " ".join((s or "").split()).lower()


def _load_leads(client_filter: str) -> List[Dict[str, str]]:
    """Read rows from the canonical CRM CSV and filter by client name.
    We match against one of the client columns in priority order:
    'Client Name' > 'Client' > 'client'.
    No deduping is performed; all matching rows are returned as-is.
    """
    rows: List[Dict[str, str]] = []
    try:
        with open(crm.CRM_CSV, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            all_rows = list(reader)
    except FileNotFoundError:
        logger.error(f"CRM file not found: {crm.CRM_CSV}")
        return rows

    key_opts = ("Client Name", "Client", "client")
    wanted = _norm(client_filter)

    for r in all_rows:
        val = None
        for k in key_opts:
            if k in r and r[k] is not None:
                val = r.get(k)
                break
        if val is None:
            continue
        if _norm(val) == wanted:
            rows.append(r)

    # Enforce one inbox per lead: dedupe by identity and drop duplicates (keep first)
    try:
        unique_rows, dups = crm.dedupe_leads_by_identity(rows)
    except Exception as _e:
        logger.warn(f"Deduplication helper error: {_e}; proceeding without dedupe (NOT RECOMMENDED)")
        unique_rows, dups = rows, {}

    if dups:
        # Log concise summary of duplicates found
        dup_count = sum(len(info["dropped"]) for info in dups.values())
        logger.warn(f"Detected {dup_count} duplicate row(s) for the same lead identity; keeping first occurrence per lead.")
        # Optionally, log a few examples
        shown = 0
        for ident, info in dups.items():
            logger.warn(f"Lead '{ident}' had multiple rows; kept sender={info['kept_sender']}, dropped={info['dropped']}")
            shown += 1
            if shown >= 5:
                break

    logger.info(f"Loaded {len(unique_rows)} unique lead rows for client '{client_filter}' (from {len(rows)} raw)")
    return unique_rows


def _step_factory(step_cfg: Dict[str, Any]):
    typ = (step_cfg.get("type") or "").strip().lower()
    sid = step_cfg.get("id")
    if not typ or not sid:
        raise ValueError(f"Invalid step config: {step_cfg}")

    if typ == "send_email":
        return SendEmailStep(
            subject=step_cfg.get("subject", ""),
            template=step_cfg.get("template", ""),
            step_id=sid,
            mode=step_cfg.get("mode", "static"),
            llm_opts=step_cfg.get("llm") or {},
        )
    if typ == "wait_until":
        delay = step_cfg.get("delay") or {}
        return WaitUntilStep(
            step_id=sid,
            days=int(delay.get("days", 0)),
            hours=int(delay.get("hours", 0)),
            minutes=int(delay.get("minutes", 0)),
        )
    if typ == "update_crm":
        return UpdateCRMStep(step_id=sid, fields=step_cfg.get("fields") or {})

    raise ValueError(f"Unknown step type: {typ}")


def _index_steps(seq_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    steps = seq_cfg.get("steps") or []
    if not steps:
        raise ValueError("Sequence has no steps")
    return steps


def _next_step_id(steps: List[Dict[str, Any]], current_step: Optional[str]) -> Optional[str]:
    step_ids = [s.get("id") for s in steps]
    if not current_step:
        return step_ids[0]
    try:
        idx = step_ids.index(current_step)
    except ValueError:
        return step_ids[0]
    return step_ids[idx + 1] if idx + 1 < len(step_ids) else None


def _followup_label_for_step(steps_cfg: List[Dict[str, Any]], step_id: str) -> Optional[str]:
    cfg_map = {s.get("id"): s for s in steps_cfg}
    s_cfg = cfg_map.get(step_id)
    if not s_cfg:
        return None
    label = s_cfg.get("label")
    if label:
        return str(label)
    if (s_cfg.get("type") or "").strip().lower() != "send_email":
        return None
    n = 0
    for s in steps_cfg:
        if (s.get("type") or "").strip().lower() == "send_email":
            n += 1
        if s.get("id") == step_id:
            break
    if n <= 0:
        return None
    return f"Follow Up #{n}"


def run_once(*, sequence_id: str, dry_run: bool, client: str, email_filter: Optional[str], max_actions: int) -> int:
    cfg = load_sequences_cfg()
    sequences = cfg.get("sequences") or {}
    if sequence_id not in sequences:
        raise SystemExit(f"Sequence '{sequence_id}' not found in config.")

    seq_cfg = sequences[sequence_id]
    steps_cfg: List[Dict[str, Any]] = _index_steps(seq_cfg)

    id_to_cfg: Dict[str, Dict[str, Any]] = {s["id"]: s for s in steps_cfg}
    step_objs: Dict[str, Any] = {sid: _step_factory(cfg) for sid, cfg in id_to_cfg.items()}

    st = StateStore(client=client)

    leads = _load_leads(client)
    now = datetime.now(UTC)

    # --- summary counters ---
    total_loaded = len(leads)
    ok_actions = 0
    skips_time = 0
    skips_quota = 0
    skips_disabled = 0
    skips_error = 0
    skips_other = 0
    skips_waiting = 0
    skips_stopped = 0

    actions = 0
    for lead in leads:
        if actions >= max_actions:
            break
        lead_id = lead.get("Email") or lead.get("id") or lead.get("DM Link")
        if not lead_id:
            continue
        if email_filter and (email_filter.strip().lower() != str(lead_id).strip().lower()):
            continue

        if st.should_stop_all(str(lead_id)):
            skips_stopped += 1
            continue

        current_step, next_action_at, status = st.get_pointer(str(lead_id), sequence_id)
        next_dt = _parse_iso(next_action_at)
        if next_dt and next_dt > now:
            skips_waiting += 1
            continue

        next_sid = _next_step_id(steps_cfg, current_step)
        if not next_sid:
            st.set_global_status(str(lead_id), "DONE")
            continue

        step_obj = step_objs[next_sid]

        if not dry_run:
            lbl = _followup_label_for_step(steps_cfg, next_sid)
            if lbl:
                try:
                    crm.update_fields(str(lead_id), {"Follow-Up Stage": lbl})
                except Exception as _e:
                    logger.warn(f"Lead {lead_id}: could not set Follow-Up Stage='{lbl}' before sending: {_e}")

        try:
            res = step_obj.run(lead, st, sequence_id, dry_run)
            status = res.get("status")
            notes = (res.get("notes") or "")
            if status == "ok":
                ok_actions += 1
                actions += 1
            elif status == "skip":
                actions += 1  # attempted, but skipped for a reason
                # classify skip reasons coming from send_email / window checker
                if notes.startswith("send-window:"):
                    reason = notes.split(":", 1)[1]
                    if reason in ("time",):
                        skips_time += 1
                    elif reason in ("daily_limit", "per_inbox_limit"):
                        skips_quota += 1
                    elif reason in ("disabled",):
                        skips_disabled += 1
                    elif reason in ("error",):
                        skips_error += 1
                    else:
                        skips_other += 1
                else:
                    skips_other += 1
            else:
                # unknown status, count as other skip
                skips_other += 1
            logger.info(f"Lead {lead_id}: ran step {next_sid} → {status} ({notes})")
        except Exception as e:
            logger.error(f"Lead {lead_id}: step {next_sid} raised {e}")
            skips_error += 1
            continue

    logger.info("Run finished. Actions attempted: %d", actions)
    logger.info("Summary for client '%s' / sequence '%s':", client, sequence_id)
    logger.info("  Leads loaded: %d", total_loaded)
    logger.info("  OK sends: %d", ok_actions)
    logger.info("  Skipped (time window): %d", skips_time)
    logger.info("  Skipped (quota limits): %d", skips_quota)
    logger.info("  Skipped (disabled): %d", skips_disabled)
    logger.info("  Skipped (errors): %d", skips_error)
    logger.info("  Skipped (waiting for next_action_at): %d", skips_waiting)
    logger.info("  Skipped (stopped/replied): %d", skips_stopped)
    logger.info("  Skipped (other): %d", skips_other)
    return actions


def main() -> int:
    ap = argparse.ArgumentParser(description="Execute one tick of a follow‑up sequence.")
    ap.add_argument("--sequence", default="opener_followups", help="Sequence id from config/sequences.yml")
    ap.add_argument("--dry-run", action="store_true", help="Simulate only; no counters/emails/CRM writes")
    ap.add_argument("--max", dest="max_actions", type=int, default=50, help="Maximum leads/steps to process this run")
    ap.add_argument("--client", default=None, help="Client name for StateStore partitioning (prompted if omitted)")
    ap.add_argument("--email", dest="email_filter", default=None, help="Only run for this prospect email/id")
    ap.add_argument("--live", action="store_true", help="Run live (sends emails). Requires SEQ_RUNNER_LIVE=YES")
    ap.add_argument("--bypass-time", action="store_true", help="Bypass time window checks for this run")
    args = ap.parse_args()

    client = args.client
    if client is None:
        try:
            entered = input("Enter client name [default]: ").strip()
        except EOFError:
            entered = ""
        client = entered or "default"
        logger.info(f"Using client partition: {client}")

    bypass_time = bool(args.bypass_time)
    if not bypass_time:
        try:
            ans = input("Bypass time window for this run? [y/N]: ").strip().lower()
        except EOFError:
            ans = ""
        bypass_time = ans in ("y", "yes")
    import os as _os
    _os.environ["SEQ_BYPASS_TIME"] = "1" if bypass_time else "0"

    # Preflight: check global send window from followup_controls.json (no counters incremented)
    allowed, reason = check_send_window(dry_run=True, bypass_time=bypass_time)
    if not allowed:
        logger.error(f"Outside allowed window or disabled (reason={reason}). Exiting early.")
        return 0

    dry_run = not bool(args.live)
    if not dry_run:
        if _os.environ.get("SEQ_RUNNER_LIVE") != "YES":
            logger.error("Refusing to run live: set SEQ_RUNNER_LIVE=YES to arm live sends.")
            return 2

    run_once(
        sequence_id=args.sequence,
        dry_run=dry_run,
        client=client,
        email_filter=args.email_filter,
        max_actions=int(args.max_actions),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
