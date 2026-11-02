#!/usr/bin/env bash
# Bootstrap the requested private repository and implementation PR. No force pushes.
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"
command -v git >/dev/null
command -v gh >/dev/null
command -v python3 >/dev/null
gh auth status --hostname github.com >/dev/null
OWNER="${1:-$(gh api user --jq .login)}"
if [[ ! "$OWNER" =~ ^[A-Za-z0-9][A-Za-z0-9-]*$ ]]; then
  echo "Invalid GitHub owner." >&2
  exit 1
fi
REPOSITORY="$OWNER/robinhood"
FEATURE_BRANCH="feat/spending-dashboard-and-jobs"
EXPECTED_REMOTE="https://github.com/$REPOSITORY.git"

if [[ ! -e .git ]]; then
  git init --initial-branch=main
fi
if [[ "$(git rev-parse --show-toplevel)" != "$PROJECT_ROOT" ]]; then
  echo "Run this script from its own robin-hood checkout." >&2
  exit 1
fi
if ! git rev-parse --verify HEAD >/dev/null 2>&1; then
  git symbolic-ref HEAD refs/heads/main
  git commit --allow-empty -m "chore: initialize robin-hood repository"
fi
git rev-parse --verify main >/dev/null
CURRENT_BRANCH="$(git branch --show-current)"
if [[ "$CURRENT_BRANCH" != "main" && "$CURRENT_BRANCH" != "$FEATURE_BRANCH" ]]; then
  echo "Expected main or the implementation branch; leaving the existing branch unchanged." >&2
  exit 1
fi
if git remote get-url origin >/dev/null 2>&1; then
  ORIGIN="$(git remote get-url origin)"
  if [[ "$ORIGIN" != "$EXPECTED_REMOTE" && "$ORIGIN" != "git@github.com:$REPOSITORY.git" ]]; then
    echo "origin points to a different repository; stopping without changing it." >&2
    exit 1
  fi
fi
if git show-ref --verify --quiet "refs/heads/$FEATURE_BRANCH"; then
  git switch "$FEATURE_BRANCH"
else
  git switch -c "$FEATURE_BRANCH"
fi
git add -- .gitignore README.md SPEC.md docs deploy pipeline tests scripts robin-hood-server robin-hood-web site/index.html site/assets

# Inspect the actual index, including any files staged before this script.
# Report paths/pattern names only, never matching credential values.
python3 - <<'PY'
import re
import subprocess
import sys

names = subprocess.check_output(['git', 'ls-files', '-z']).decode().split('\0')
blocked = []
patterns = {
    'private key': rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
    'GitHub token': rb'\b(?:ghp_|github_pat_)[A-Za-z0-9_]{20,}',
    'OpenAI key': rb'\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{25,}',
    'AWS key': rb'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b',
    'Slack token': rb'\bxox[baprs]-[A-Za-z0-9-]{15,}',
}
for name in filter(None, names):
    parts = name.split('/')
    if (name.startswith(('data/', 'site/data/', '.artifacts/', '.playwright-mcp/'))
        or any(p in {'.venv', 'node_modules', 'dist', '__pycache__', '.pytest_cache', 'var'} for p in parts)
        or parts[-1] in {'credentials.yaml', '.sops.yaml'}
        or parts[-1].startswith('.env') and parts[-1] != '.env.example'
        or name.endswith(('.sqlite', '.sqlite3', '.db', '.pyc', '.tsbuildinfo'))):
        blocked.append((name, 'excluded data/runtime/credential file'))
        continue
    data = subprocess.check_output(['git', 'show', ':' + name])
    if len(data) > 10 * 1024 * 1024:
        blocked.append((name, 'unexpected file larger than 10 MiB'))
    for label, pattern in patterns.items():
        if re.search(pattern, data):
            blocked.append((name, label))
if blocked:
    for name, label in blocked:
        print(f'Refusing to publish {name}: {label}', file=sys.stderr)
    sys.exit(1)
print(f'Checked {len(list(filter(None, names)))} tracked files; raw datasets and credentials excluded.')
PY

if ! git diff --cached --quiet; then
  git commit -m "feat: add spending dashboard, PostgreSQL ingestion and OCR text corrections"
fi
if ! gh repo view "$REPOSITORY" --json nameWithOwner >/dev/null 2>&1; then
  gh repo create "$REPOSITORY" --private --description "나랏일보고서: public spending dashboards, source evidence and scheduled collection"
fi
if ! git remote get-url origin >/dev/null 2>&1; then
  git remote add origin "$EXPECTED_REMOTE"
fi
# Use the authenticated gh helper for these pushes without changing global Git config.
git -c credential.helper= -c 'credential.helper=!gh auth git-credential' push -u origin main
git -c credential.helper= -c 'credential.helper=!gh auth git-credential' push -u origin "$FEATURE_BRANCH"

EXISTING_PR="$(gh pr list --repo "$REPOSITORY" --base main --head "$FEATURE_BRANCH" --state open --json url --jq '.[0].url // empty')"
if [[ -n "$EXISTING_PR" ]]; then
  echo "$EXISTING_PR"
  exit 0
fi
PR_BODY="$(mktemp "${TMPDIR:-/tmp}/robin-hood-pr.XXXXXX")"
trap 'rm -f "$PR_BODY"' EXIT
cat > "$PR_BODY" <<'BODY'
Implements 나랏일보고서 as a responsive React/TypeScript dashboard and FastAPI service using the collected public-spending data.

- Add regional maps, member/party profiles, council role spending, Top 10 comparisons, place and transaction details, fiscal statistics, and source/method pages with explicit funding and period labels.
- Store service records in an isolated PostgreSQL schema with transactional COPY publication and consistent read snapshots. Retain SQLite for offline development.
- Add durable collection schedules, bounded retries, cross-host exclusion, job history, and systemd service definitions.
- Add optional Codex correction of extracted OCR table text. Preserve source/staging files, record correction evidence separately, protect numerical/attribution fields, and reuse unchanged review results.

Validation:
- Server tests: 57 passed; 3 live PostgreSQL integration tests skipped without TEST_POSTGRES_URL in the original data-bearing workspace.
- Clean source export: 54 server tests passed; 6 skipped without the external dataset and live PostgreSQL. All 36 pipeline tests pass without the dataset.
- Pipeline tests: 36 passed.
- PostgreSQL 17.5 engine checks cover 18 API paths, constraints/rollback, shared job state, and correction-audit JSONB storage.
- Frontend typecheck, production build, and formatting checks pass.
- Desktop/mobile flows were checked using captured responses from the actual API; this execution environment blocks localhost listeners.

Deployment requires a configured PostgreSQL URL. NAVER Maps and optional Codex corrections require their documented application/login settings. No production migration, persistent scheduler, or live Codex correction run has been activated.

Raw/normalized datasets, generated site data, local databases, credentials, dependencies, build output, and development artifacts are excluded from Git. Dataset-based reconciliation tests require a restored or recollected dataset.
BODY
gh pr create --repo "$REPOSITORY" --base main --head "$FEATURE_BRANCH" \
  --title "feat: add public spending dashboard and scheduled ingestion" --body-file "$PR_BODY"
