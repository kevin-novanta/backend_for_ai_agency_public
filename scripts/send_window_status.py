#!/usr/bin/env python3
"""
Status-only checker for the follow-up send window.

Usage:
  python3 scripts/send_window_status.py
  python3 scripts/send_window_status.py --inbox sales@yourdomain.com
  python3 scripts/send_window_status.py --check-live --inbox sales@yourdomain.com

Notes:
- This script NEVER sends emails.
- It prints whether sending is allowed right now per followup_controls.json.
- Exit code: 0 if allowed, 1 if blocked.
- With --check-live, it increments counters if allowed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

# Ensure repo root is on path when run from anywhere
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from workflows.followup_engine.utils.send_window_status import (  # type: ignore
    check_send_window,
    CONTROLS_PATH,
    COUNTERS_PATH,
    _load_controls,
    _now_local,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Show follow-up send window status and quotas.")
    parser.add_argument("--inbox", default=None, help="Inbox identifier/email to check per-inbox limits.")
    parser.add_argument(
        "--check-live",
        action="store_true",
        help="If set, perform a live check (dry_run=False). This will increment counters if allowed.",
    )
    args = parser.parse_args()

    cfg = _load_controls()
    tz = cfg.get("timezone", "America/New_York")
    now = _now_local(tz)
    today = now.date().isoformat()

    # Perform the check (dry by default)
    allowed, reason = check_send_window(inbox=args.inbox, dry_run=not args.check_live)

    # Read counters file (do not modify here)
    if COUNTERS_PATH.exists():
        try:
            with open(COUNTERS_PATH, "r", encoding="utf-8") as f:
                counters = json.load(f)
        except Exception:
            counters = {}
    else:
        counters = {}

    total_sent = int(counters.get("total", 0))
    per_inbox = {k: int(v) for k, v in counters.get("per_inbox", {}).items()}

    daily_limit = int(cfg.get("daily_limit", 0)) if "daily_limit" in cfg else None
    per_inbox_limit = int(cfg.get("per_inbox_limit", 0)) if "per_inbox_limit" in cfg else None

    # Pretty print status
    print("=== Follow-up Send Window Status ===")
    print(f"Now:           {now.strftime('%Y-%m-%d %H:%M:%S')} ({tz})")
    print(f"Controls file: {CONTROLS_PATH}")
    print(f"Counters file: {COUNTERS_PATH}")
    print(f"Allowed now?:  {'YES' if allowed else 'NO'}  (reason: {reason})")
    print()
    print("--- Rules ---")
    print(f"Enabled:       {cfg.get('outreach_enabled', True)}")
    print(f"Days allowed:  {', '.join(cfg.get('days_allowed', []))}")
    print(f"Time window:   {cfg.get('start_time', '09:00')} - {cfg.get('end_time', '17:00')} ({tz})")
    if daily_limit:
        print(f"Daily limit:   {daily_limit}")
    if per_inbox_limit:
        print(f"Per-inbox limit: {per_inbox_limit}")
    print()
    print("--- Today ---")
    print(f"Date:          {today}")
    print(f"Total sent:    {total_sent}")
    if daily_limit is not None:
        print(f"Remaining:     {max(daily_limit - total_sent, 0)}")
    if args.inbox:
        used = per_inbox.get(args.inbox, 0)
        print(f"Inbox '{args.inbox}' sent: {used}")
        if per_inbox_limit is not None:
            print(f"Inbox remaining: {max(per_inbox_limit - used, 0)}")
    else:
        if per_inbox:
            print("Per-inbox counts:")
            for k, v in sorted(per_inbox.items()):
                print(f"  - {k}: {v}")

    if args.check_live:
        print("\nNote: --check-live increments counters if allowed.")

    # Exit code: 0 if allowed, 1 if blocked
    return 0 if allowed else 1


if __name__ == "__main__":
    raise SystemExit(main())