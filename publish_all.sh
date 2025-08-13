#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# publish_all.sh — one-button private push + public sanitized export & push
#
# What it does:
# 1) Commits & pushes your PRIVATE repo:
#      /Users/kevinnovanta/backend_for_ai_agency  ->  github.com/kevin-novanta/backend_for_ai_agency (main)
# 2) Mirrors PRIVATE -> PUBLIC working dir, sanitizes, then commits & pushes:
#      /Users/kevinnovanta/backend_public_export  ->  github.com/kevin-novanta/backend_for_ai_agency_public (main)
#
# Usage examples:
#   ./publish_all.sh --message="Sync + sanitize" --push
#   ./publish_all.sh --message="Only commit privately" --no-public-push
#
# Flags:
#   --message=MSG     Commit message (applies to both private & public commits).
#   --push            Push both repos (default true).
#   --no-push         Do not push either repo.
#   --private-only    Only commit/push private repo (skip public mirror/sanitize).
#   --public-only     Only mirror/sanitize/push public repo (skip private commit).
###############################################################################

###### CONFIG (paths/remotes/branches) ########################################
PRIVATE_DIR="/Users/kevinnovanta/backend_for_ai_agency"
PRIVATE_REMOTE="origin"
PRIVATE_URL="https://github.com/kevin-novanta/backend_for_ai_agency.git"
PRIVATE_BRANCH="main"

PUBLIC_DIR="/Users/kevinnovanta/backend_public_export"
PUBLIC_REMOTE="origin"
PUBLIC_URL="https://github.com/kevin-novanta/backend_for_ai_agency_public.git"
PUBLIC_BRANCH="main"

###### Options (defaults) #####################################################
COMMIT_MSG="Automated sync & sanitize"
DO_PUSH=1
DO_PRIVATE=1
DO_PUBLIC=1
MSG_PASSED=0

for arg in "$@"; do
  case "$arg" in
    --message=*) COMMIT_MSG="${arg#--message=}"; MSG_PASSED=1 ;;
    --push) DO_PUSH=1 ;;
    --no-push) DO_PUSH=0 ;;
    --private-only) DO_PUBLIC=0 ;;
    --public-only) DO_PRIVATE=0 ;;
  esac
done

###### Helpers ################################################################
say() { printf "%s\n" "$*"; }
err() { printf "ERROR: %s\n" "$*" >&2; }

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then err "Missing required command: $1"; exit 1; fi
}

need_cmd git
need_cmd rsync

# Prompt for commit message if none provided and we're interactive
if [ "$MSG_PASSED" -eq 0 ] && [ -t 0 ]; then
  printf "Enter Git commit message (default: '%s'): " "$COMMIT_MSG"
  read -r _input || true
  if [ -n "${_input:-}" ]; then COMMIT_MSG="$_input"; fi
fi

###############################################################################
# 1) PRIVATE REPO: commit & push
###############################################################################
if [ "$DO_PRIVATE" -eq 1 ]; then
  say "==> PRIVATE: committing & (optionally) pushing $PRIVATE_DIR to $PRIVATE_URL ($PRIVATE_BRANCH)"
  if [ ! -d "$PRIVATE_DIR/.git" ]; then
    err "No git repo at $PRIVATE_DIR. Initialize it first."; exit 1
  fi
  (
    cd "$PRIVATE_DIR"
    # Ensure remote + branch exist (and correct URL if mismatched)
    if git remote get-url "$PRIVATE_REMOTE" >/dev/null 2>&1; then
      current_priv_url="$(git remote get-url "$PRIVATE_REMOTE" || true)"
      if [ "$current_priv_url" != "$PRIVATE_URL" ]; then
        say "Private: updating remote '$PRIVATE_REMOTE' URL -> $PRIVATE_URL (was $current_priv_url)"
        git remote set-url "$PRIVATE_REMOTE" "$PRIVATE_URL"
      fi
    else
      git remote add "$PRIVATE_REMOTE" "$PRIVATE_URL"
    fi
    current_branch="$(git rev-parse --abbrev-ref HEAD)"
    if [ "$current_branch" != "$PRIVATE_BRANCH" ]; then
      # Create/switch to desired branch if needed
      if git show-ref --verify --quiet "refs/heads/$PRIVATE_BRANCH"; then
        git checkout "$PRIVATE_BRANCH"
      else
        git checkout -b "$PRIVATE_BRANCH"
      fi
    fi

    # Stage & commit if there are changes
    git add -A || true
    if git diff --cached --quiet; then
      say "No staged changes in private repo."
    else
      git commit -m "$COMMIT_MSG" || true
      say "Committed private repo with message: $COMMIT_MSG"
    fi
    if [ "$DO_PUSH" -eq 1 ]; then
      say "Pushing private repo to $PRIVATE_REMOTE/$PRIVATE_BRANCH ..."
      git push -u "$PRIVATE_REMOTE" "$PRIVATE_BRANCH"
    fi
  )
else
  say "==> PRIVATE: skipped (public-only mode)"
fi

###############################################################################
# 2) PUBLIC REPO WORKING DIR: mirror from private
###############################################################################
if [ "$DO_PUBLIC" -eq 1 ]; then
  say "==> PUBLIC: mirroring $PRIVATE_DIR -> $PUBLIC_DIR"
  mkdir -p "$PUBLIC_DIR"

  # If PUBLIC_DIR is a git worktree linked to PRIVATE_DIR, convert to standalone repo
  if [ -f "$PUBLIC_DIR/.git" ] && grep -q "gitdir: .*worktrees" "$PUBLIC_DIR/.git" 2>/dev/null; then
    say "Detected git worktree in PUBLIC_DIR; converting to standalone repo..."
    git -C "$PRIVATE_DIR" worktree remove --force "$PUBLIC_DIR" || true
    rm -rf "$PUBLIC_DIR/.git"
  fi

  # Mirror file tree (exclude .git from private); keep PUBLIC .git intact
  rsync -a --delete \
    --exclude ".git" \
    --exclude "publish_all.sh" \
    --exclude "publish_all_commands.txt" \
    --exclude ".gitignore" \
    "$PRIVATE_DIR"/ "$PUBLIC_DIR"/

  #############################################################################
  # PUBLIC: git init/remote/branch ensure
  #############################################################################
  if [ ! -d "$PUBLIC_DIR/.git" ]; then
    (
      cd "$PUBLIC_DIR"
      git init
      git checkout -b "$PUBLIC_BRANCH" 2>/dev/null || git checkout "$PUBLIC_BRANCH" || true
    )
  fi
  (
    cd "$PUBLIC_DIR"
    # Ensure remote points to public URL
    if git remote get-url "$PUBLIC_REMOTE" >/dev/null 2>&1; then
      current_url="$(git remote get-url "$PUBLIC_REMOTE" || true)"
      if [ "$current_url" != "$PUBLIC_URL" ]; then
        git remote set-url "$PUBLIC_REMOTE" "$PUBLIC_URL"
      fi
    else
      git remote add "$PUBLIC_REMOTE" "$PUBLIC_URL"
    fi
    # Ensure branch exists/checked out
    if git show-ref --verify --quiet "refs/heads/$PUBLIC_BRANCH"; then
      git checkout "$PUBLIC_BRANCH"
    else
      git checkout -b "$PUBLIC_BRANCH"
    fi
  )

  #############################################################################
  # 3) SANITIZE PUBLIC DIR (untrack sensitive files / write .gitignore / stubs)
  #############################################################################
  say ">> Running sanitizer (public snapshot)"
  (
    cd "$PUBLIC_DIR"

    # 3.1 Untrack specific private/sensitive paths (leave on disk)
    git rm -r --cached --force --ignore-unmatch \
      Creds \
      Debugging \
      Documentation_Videos \
      api \
      data \
      database \
      integrations \
      workflows/Google_Sheets \
      workflows/Logging \
      workflows/lead_scraper \
      workflows/linkedin \
      workflows/followup_engine/Utils \
      workflows/followup_engine/listeners \
      workflows/outreach_sender/Utils \
      workflows/outreach_sender/Email_Scripts/email_send_tracking.json \
      Restart_CRM_sync.sh \
      restart.commands.txt \
      restart_registry_sync.sh \
      sync_output.log \
      api/routes/__pycache__/leads.cpython-313.pyc \
      api/routes/leads.py \
      data/exports/Google_Leads/Cleaned_Google_Maps_Data/enriched_data.csv \
      data/exports/Google_Leads/Raw_Google_Maps_Data/raw_data.csv \
      data/exports/Linkedin_Leads/Raw_Linkedin_Leads/business_process_outsourcing_linkedin_leads.csv \
      data/leads/CRM_Leads/CRM_leads.csv \
      data/leads/CRM_Leads/CRM_leads_copy.csv \
      data/leads/Lead_Registry/leads_registry.csv \
      data/leads/Unfiltered_GPT_Leads/split_output_1.csv \
      data/leads/Unfiltered_GPT_Leads/split_output_2.csv \
      integrations/gmail_auth.py \
      integrations/gmail_sender.py \
      workflows/followup_engine/Utils/followup_state.sqlite3 \
      workflows/lead_scraper/google_maps/utils/csv_splitter/split_large_csv.py \
      workflows/lead_scraper/google_maps/utils/parse_and_format_leads/__pycache__/parse_and_format_leads.cpython-313.pyc \
      workflows/lead_scraper/google_maps/utils/parse_and_format_leads/parse_and_format_leads.py \
      workflows/lead_scraper/linkedin/Sessions/Cookies.json \
      workflows/lead_scraper/linkedin/logic/linkedin_phase1_raw_links.csv \
      workflows/outreach_sender/Utils/load_crm_leads.py \
      || true

    # 3.2 Untrack generic sensitive file types
    git rm --cached --force --ignore-unmatch '**/*.sqlite3' || true
    git rm -r --cached --force --ignore-unmatch '**/__pycache__/**' '**/*.pyc' || true
    git rm --cached --force --ignore-unmatch '**/*.csv' || true

    # 3.3 Automatically detect and untrack sensitive files, add them to .gitignore
    matches="$(git ls-files | grep -Ei '(token|secret|apikey|gpt_key|sheets_key|cookie|credentials|Creds|sqlite3|csv|leads|gmail)' || true)"
    if [ -n "$matches" ]; then
      echo "$matches" | while IFS= read -r file; do
        touch .gitignore
        grep -qxF "$file" .gitignore || echo "$file" >> .gitignore
        git rm --cached --force --ignore-unmatch "$file" || true
        echo "Untracked sensitive file and added to .gitignore: $file"
      done
    else
      echo "No additional sensitive files detected."
    fi

    # 3.4 Public .gitignore (keep these out going forward; keep helper script)
    cat > .gitignore <<'IGN'
# ---- OS & IDE ----
.DS_Store
.Spotlight-V100
.Trashes
.vscode/
.idea/

# ---- Python ----
__pycache__/
**/__pycache__/
*.py[cod]
*.pyc
*.pyo
*.pyd
*.egg-info/

# ---- Env / Secrets ----
*.env
creds/
Creds/

# ---- Logs ----
logs/
*.log
sync_output.log
Restart_CRM_sync.sh
restart.commands.txt
restart_registry_sync.sh

# ---- Builds ----
build/
dist/

# ---- Data exports (keep out of public snapshot) ----
*.sqlite3
*.db
*.csv

data/
Debugging/
Documentation_Videos/

# ---- Private code paths to exclude from public snapshot ----
api/
database/
integrations/
workflows/Google_Sheets/
workflows/Logging/
workflows/lead_scraper/
workflows/linkedin/
workflows/followup_engine/Utils/
workflows/followup_engine/listeners/
workflows/outreach_sender/Utils/
workflows/outreach_sender/Email_Scripts/email_send_tracking.json

# ---- Helper scripts ----
# Keep the main publisher tracked, ignore the commands helper file
!/publish_all.sh
publish_all_commands.txt
IGN

    # 3.5 Ensure demo utils + public-safe LLM stub exist (idempotent)
    mkdir -p workflows/followup_engine/demo_utils

    [[ -f workflows/followup_engine/demo_utils/__init__.py ]] || cat > workflows/followup_engine/demo_utils/__init__.py <<'PY'
from .state_store import StateStore
from . import crm
from . import logger
PY

    [[ -f workflows/followup_engine/demo_utils/logger.py ]] || cat > workflows/followup_engine/demo_utils/logger.py <<'PY'
import logging
logging.basicConfig(level=logging.INFO)
def info(msg): logging.info(msg)
def warn(msg): logging.warning(msg)
def error(msg): logging.error(msg)
PY

    [[ -f workflows/followup_engine/demo_utils/crm.py ]] || cat > workflows/followup_engine/demo_utils/crm.py <<'PY'
def lookup_lead_id_by_email(email): return email
def get_followup_eligible_leads(client):
    return [
        {"Email":"demo1@example.com","Company Name":"Acme Co","Custom 2":"B2B ops platform"},
        {"Email":"demo2@example.com","Company Name":"Globex","Custom 2":"Logistics analytics"},
    ]
def update_fields(lead_id, fields): pass
def set_responded(lead_id, val): pass
def is_automatic_reply(text): return False
PY

    [[ -f workflows/followup_engine/demo_utils/state_store.py ]] || cat > workflows/followup_engine/demo_utils/state_store.py <<'PY'
class StateStore:
    def __init__(self, client="Demo"): self.sent=set()
    def was_sent(self, lead_id, seq_id, step_id, idempotency_key): return (lead_id,seq_id,step_id,idempotency_key) in self.sent
    def mark_sent(self, lead_id, seq_id, step_id, idempotency_key): self.sent.add((lead_id,seq_id,step_id,idempotency_key))
    def is_stopped(self, lead_id): return False
    def mark_replied(self, lead_id): pass
PY

    mkdir -p workflows/followup_engine/AI_Integrations
    cat > workflows/followup_engine/AI_Integrations/llm_client.py <<'PY'
import os
def render_llm_email(template_name, lead, fallback_subject="", llm_opts=None, context=None):
    subj = fallback_subject or f"Follow-up for {lead.get('Company Name','your team')}"
    body = f"Hi there — demo follow-up for {lead.get('Company Name','your team')}."
    if os.getenv("OPENAI_API_KEY"): pass
    return {"subject": subj, "body_one_paragraph": body}
PY

    # 3.6 Fix imports from private utils -> demo_utils (macOS sed-friendly)
    if command -v rg >/dev/null 2>&1; then
      rg -l "workflows\\.followup_engine\\.(Utils|utils)" | xargs -I{} sed -i '' 's/workflows\\.followup_engine\\.Utils/workflows.followup_engine.demo_utils/g; s/workflows\\.followup_engine\\.utils/workflows.followup_engine.demo_utils/g' {} || true
    else
      grep -rl "workflows.followup_engine.Utils\|workflows.followup_engine.utils" | xargs -I{} sed -i '' 's/workflows\\.followup_engine\\.Utils/workflows.followup_engine.demo_utils/g; s/workflows\\.followup_engine\\.utils/workflows.followup_engine.demo_utils/g' {} || true
    fi

    # 3.7 Status summary
    git status --porcelain=v1 | sed -e 's/^/  /' | head -n 200 || true
  )

  #############################################################################
  # 4) PUBLIC: commit & push
  #############################################################################
  (
    cd "$PUBLIC_DIR"
    # Stage & commit if there are changes
    git add -A || true
    if git diff --cached --quiet; then
      say "No staged changes to commit (public)."
    else
      git commit -m "$COMMIT_MSG" || true
      say "Committed public snapshot with message: $COMMIT_MSG"
    fi

    if [ "$DO_PUSH" -eq 1 ]; then
      branch="$(git rev-parse --abbrev-ref --symbolic-full-name HEAD | sed 's#^refs/heads/##')"
      say "Pushing public repo to $PUBLIC_REMOTE/$branch (force) ..."
      git push --force -u "$PUBLIC_REMOTE" "$branch"
    fi
  )
else
  say "==> PUBLIC: skipped (private-only mode)"
fi

say "✅ Done."
