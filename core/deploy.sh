#!/bin/bash
# Deploy AiPayGen from Pi to Oracle Cloud
# Usage: ./deploy.sh [--skip-tests] [--dry-run]
set -euo pipefail

# --- Config ---
REMOTE_USER="ubuntu"
REMOTE_HOST="150.136.124.81"
SSH_KEY="$HOME/.ssh/oracle_key"
SSH_CMD="ssh -i $SSH_KEY ${REMOTE_USER}@${REMOTE_HOST}"
REMOTE_DIR="/home/ubuntu/agent-service"
LOCAL_DIR="/home/damien809/agent-service"
LIVE_URL="https://api.aipaygen.com"
DEPLOY_START=$(date +%s)

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# --- Helpers ---
info()  { echo -e "${CYAN}[INFO]${NC} $*"; }
pass()  { echo -e "${GREEN}[PASS]${NC} $*"; }
fail()  { echo -e "${RED}[FAIL]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
step()  { echo -e "\n${BOLD}=== $* ===${NC}"; }

# --- Parse Args ---
SKIP_TESTS=false
DRY_RUN=false
for arg in "$@"; do
  case "$arg" in
    --skip-tests) SKIP_TESTS=true ;;
    --dry-run)    DRY_RUN=true ;;
    -h|--help)
      echo "Usage: ./deploy.sh [--skip-tests] [--dry-run]"
      echo "  --skip-tests  Skip local test suite"
      echo "  --dry-run     Rsync dry run (no actual file transfer)"
      exit 0
      ;;
    *) fail "Unknown argument: $arg"; exit 1 ;;
  esac
done

echo -e "${BOLD}╔═══════════════════════════════════╗${NC}"
echo -e "${BOLD}║     AiPayGen Deploy Pipeline      ║${NC}"
echo -e "${BOLD}╚═══════════════════════════════════╝${NC}"
echo ""
info "Started at $(date '+%Y-%m-%d %H:%M:%S')"

# ──────────────────────────────────────────────
# Step 0: Pre-deploy consistency check
# ──────────────────────────────────────────────
step "Step 0/7: Consistency Check"

if [ -f "$LOCAL_DIR/consistency_check.sh" ]; then
  if bash "$LOCAL_DIR/consistency_check.sh"; then
    pass "Consistency check passed"
  else
    fail "Consistency check FAILED — fix issues before deploying"
    exit 1
  fi
else
  warn "consistency_check.sh not found — skipping"
fi

# ──────────────────────────────────────────────
# Step 1: Run tests locally
# ──────────────────────────────────────────────
step "Step 1/7: Local Tests"

if [ "$SKIP_TESTS" = true ]; then
  warn "Skipping tests (--skip-tests)"
else
  cd "$LOCAL_DIR"
  if python -m pytest tests/ -q --tb=line -x 2>&1 | tee /tmp/deploy_test_output.txt; then
    TOTAL=$(grep -oP '\d+ passed' /tmp/deploy_test_output.txt | head -1 || echo "?")
    pass "All tests passed ($TOTAL)"
  else
    fail "Tests failed — aborting deploy"
    echo ""
    tail -20 /tmp/deploy_test_output.txt
    exit 1
  fi
fi

# ──────────────────────────────────────────────
# Step 2: Rsync to Oracle
# ──────────────────────────────────────────────
step "Step 2/7: Sync to Oracle"

RSYNC_FLAGS="-avz --checksum --delete"
if [ "$DRY_RUN" = true ]; then
  RSYNC_FLAGS="$RSYNC_FLAGS --dry-run"
  warn "Dry run mode — no files will be transferred"
fi

RSYNC_EXCLUDES=(
  --exclude='.git'
  --exclude='venv/'
  --exclude='*.db'
  --exclude='*.db-shm'
  --exclude='*.db-wal'
  --exclude='__pycache__/'
  --exclude='*.pyc'
  --exclude='dist/'
  --exclude='build/'
  --exclude='*.egg-info'
  --exclude='node_modules/'
  --exclude='.env'
  --exclude='.flask_secret'
  --exclude='*.log'
  --exclude='*.log.*'
  --exclude='.claude/'
  --exclude='payments.jsonl'
  --exclude='.pytest_cache/'
  --exclude='htmlcov/'
  --exclude='.coverage'
)

SYNC_OUTPUT=$(rsync $RSYNC_FLAGS \
  -e "ssh -i $SSH_KEY" \
  "${RSYNC_EXCLUDES[@]}" \
  "$LOCAL_DIR/" "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/" 2>&1)

FILES_CHANGED=$(echo "$SYNC_OUTPUT" | grep -cE '^[<>]|^sent' || true)
pass "Sync complete"
echo "$SYNC_OUTPUT" | grep -E '^(sending|sent|total)' | tail -3

if [ "$DRY_RUN" = true ]; then
  info "Dry run complete — exiting"
  exit 0
fi

# ──────────────────────────────────────────────
# Step 3: Install dependencies on Oracle
# ──────────────────────────────────────────────
step "Step 3/7: Dependencies"

DEP_OUTPUT=$($SSH_CMD "cd $REMOTE_DIR && source venv/bin/activate && pip install -q -r requirements.txt 2>&1 | grep -v 'already satisfied'" || true)
if [ -n "$DEP_OUTPUT" ]; then
  info "Updated packages:"
  echo "$DEP_OUTPUT" | head -10
else
  pass "All dependencies up to date"
fi

# ──────────────────────────────────────────────
# Step 4: Restart services
# ──────────────────────────────────────────────
step "Step 4/7: Restart Services"

$SSH_CMD "sudo systemctl restart aipaygent.service" 2>&1
pass "aipaygent.service restarted"

$SSH_CMD "sudo systemctl restart aipaygen-mcp.service" 2>&1
pass "aipaygen-mcp.service restarted"

# ──────────────────────────────────────────────
# Step 5: Wait for services to come up
# ──────────────────────────────────────────────
step "Step 5/7: Waiting for Services"
info "Waiting 5 seconds for services to initialize..."
sleep 5

# Quick service status check
for svc in aipaygent.service aipaygen-mcp.service; do
  STATUS=$($SSH_CMD "systemctl is-active $svc" 2>/dev/null || echo "unknown")
  if [ "$STATUS" = "active" ]; then
    pass "$svc is active"
  else
    fail "$svc status: $STATUS"
  fi
done

# ──────────────────────────────────────────────
# Step 6: Smoke tests
# ──────────────────────────────────────────────
step "Step 6/7: Smoke Tests"

if [ -f "$LOCAL_DIR/smoke_tests.sh" ]; then
  if bash "$LOCAL_DIR/smoke_tests.sh"; then
    pass "All smoke tests passed"
  else
    echo ""
    fail "Smoke tests FAILED"
    warn "Consider rolling back:"
    echo -e "  ${YELLOW}$SSH_CMD \"sudo systemctl restart aipaygent.service && sudo systemctl restart aipaygen-mcp.service\"${NC}"
    echo -e "  ${YELLOW}Or restore from backup: rsync from Oracle's last good state${NC}"
    DEPLOY_END=$(date +%s)
    DEPLOY_TIME=$((DEPLOY_END - DEPLOY_START))
    echo ""
    fail "Deploy completed with errors in ${DEPLOY_TIME}s"
    exit 1
  fi
else
  warn "smoke_tests.sh not found — skipping smoke tests"
  # Fallback: basic health check
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$LIVE_URL/health" 2>/dev/null || echo "000")
  if [ "$HTTP_CODE" = "200" ]; then
    pass "Health endpoint returned 200"
  else
    fail "Health endpoint returned $HTTP_CODE"
  fi
fi

# ──────────────────────────────────────────────
# Step 7/7: Post-deploy site audit
# ──────────────────────────────────────────────
step "Step 7/7: Site Audit"

if [ -f "$LOCAL_DIR/site_audit.sh" ]; then
  if bash "$LOCAL_DIR/site_audit.sh"; then
    pass "Site audit passed"
  else
    warn "Site audit detected issues — review above (not rolling back)"
  fi
else
  warn "site_audit.sh not found — skipping"
fi

# ──────────────────────────────────────────────
# Summary
# ──────────────────────────────────────────────
DEPLOY_END=$(date +%s)
DEPLOY_TIME=$((DEPLOY_END - DEPLOY_START))

echo ""
echo -e "${BOLD}╔═══════════════════════════════════╗${NC}"
echo -e "${BOLD}║        Deploy Summary             ║${NC}"
echo -e "${BOLD}╚═══════════════════════════════════╝${NC}"
echo -e "  ${GREEN}Status:${NC}     SUCCESS"
echo -e "  ${GREEN}Duration:${NC}   ${DEPLOY_TIME}s"
echo -e "  ${GREEN}Time:${NC}       $(date '+%Y-%m-%d %H:%M:%S')"
echo -e "  ${GREEN}Target:${NC}     ${REMOTE_HOST}"
echo -e "  ${GREEN}Live URL:${NC}   ${LIVE_URL}"
echo ""
