#!/bin/bash
# Post-deploy site audit — verifies live site consistency
# Runs after deploy to catch runtime issues
# Exit 0 = all pass, 1 = failures detected
set -uo pipefail

BASE_URL="${1:-https://api.aipaygen.com}"
MCP_URL="${2:-https://mcp.aipaygen.com}"
DOMAIN="api.aipaygen.com"
SSH_KEY="$HOME/.ssh/oracle_key"
REMOTE="ubuntu@150.136.124.81"

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

PASSED=0
FAILED=0
WARNED=0

pass() { ((PASSED++)); echo -e "  ${GREEN}PASS${NC}  $*"; }
fail() { ((FAILED++)); echo -e "  ${RED}FAIL${NC}  $*"; }
warn() { ((WARNED++)); echo -e "  ${YELLOW}WARN${NC}  $*"; }

# Fetch page and return HTTP status code
check_page() {
  local label="$1"
  local url="$2"
  local expected="${3:-200}"
  local code
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$url" 2>/dev/null || echo "000")
  if [ "$code" = "$expected" ]; then
    pass "$label (HTTP $code)"
  else
    fail "$label — expected $expected, got $code"
  fi
}

echo -e "${BOLD}╔═══════════════════════════════════════╗${NC}"
echo -e "${BOLD}║       AiPayGen Site Audit             ║${NC}"
echo -e "${BOLD}╚═══════════════════════════════════════╝${NC}"
echo -e "  Target: $BASE_URL"
echo -e "  MCP:    $MCP_URL"
echo -e "  Time:   $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# ──────────────────────────────────────────────
# 1. Critical pages return 200
# ──────────────────────────────────────────────
echo -e "${CYAN}[1/8] Critical Pages${NC}"

PAGES="/ /try /pricing /buy-credits /docs /discover /playground /examples /integrations /status /blog /dashboard /support /get-key /sell /referrals"
for page in $PAGES; do
  check_page "$page" "$BASE_URL$page"
done

echo ""

# ──────────────────────────────────────────────
# 2. Health endpoint
# ──────────────────────────────────────────────
echo -e "${CYAN}[2/8] Health Check${NC}"

HEALTH_BODY=$(curl -s --max-time 10 "$BASE_URL/health" 2>/dev/null || echo "{}")
HEALTH_STATUS=$(echo "$HEALTH_BODY" | python3 -c "import json,sys; print(json.load(sys.stdin).get('status',''))" 2>/dev/null || echo "")

if [ "$HEALTH_STATUS" = "healthy" ]; then
  pass "/health status=healthy"
else
  fail "/health status='$HEALTH_STATUS' (expected 'healthy')"
fi

echo ""

# ──────────────────────────────────────────────
# 3. Deep health
# ──────────────────────────────────────────────
echo -e "${CYAN}[3/8] Deep Health${NC}"

DEEP_BODY=$(curl -s --max-time 15 "$BASE_URL/health/deep" 2>/dev/null || echo "{}")
DEEP_RESULT=$(echo "$DEEP_BODY" | python3 -c "
import json, sys
d = json.load(sys.stdin)
checks = d.get('checks', {})
failed = [k for k, v in checks.items() if v in (False, 'error', 'down')]
if failed:
    print('FAIL:' + ','.join(failed))
else:
    print('OK:' + str(len(checks)))
" 2>/dev/null || echo "ERROR")

if echo "$DEEP_RESULT" | grep -q "^OK:"; then
  NCHECK="${DEEP_RESULT#OK:}"
  pass "/health/deep — all $NCHECK checks passed"
elif echo "$DEEP_RESULT" | grep -q "^FAIL:"; then
  FAILURES="${DEEP_RESULT#FAIL:}"
  fail "/health/deep — failed checks: $FAILURES"
else
  warn "/health/deep — could not parse response"
fi

echo ""

# ──────────────────────────────────────────────
# 4. MCP health + tool count
# ──────────────────────────────────────────────
echo -e "${CYAN}[4/8] MCP Service${NC}"

MCP_BODY=$(curl -s --max-time 10 "$MCP_URL/health" 2>/dev/null || echo "{}")
MCP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$MCP_URL/health" 2>/dev/null || echo "000")

if [ "$MCP_CODE" = "200" ]; then
  pass "MCP /health (HTTP 200)"
else
  fail "MCP /health (HTTP $MCP_CODE)"
fi

MCP_TOOLS=$(echo "$MCP_BODY" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('tools', d.get('tool_count', '?')))" 2>/dev/null || echo "?")
EXPECTED_TOOLS="250"
if [ "$MCP_TOOLS" = "$EXPECTED_TOOLS" ]; then
  pass "MCP tool count: $MCP_TOOLS"
else
  warn "MCP tool count: $MCP_TOOLS (expected $EXPECTED_TOOLS)"
fi

echo ""

# ──────────────────────────────────────────────
# 5. Stale content check (scrape key pages)
# ──────────────────────────────────────────────
echo -e "${CYAN}[5/8] Stale Content Check${NC}"

STALE_COUNTS="244 169 165 162 161"
PAGES_TO_CHECK="/ /try /pricing /discover /docs"
STALE_FOUND=0

for page in $PAGES_TO_CHECK; do
  PAGE_BODY=$(curl -s --max-time 10 "$BASE_URL$page" 2>/dev/null || echo "")
  for stale in $STALE_COUNTS; do
    # Check for patterns like "244 tools" or "244 endpoints" or "244 APIs"
    if echo "$PAGE_BODY" | grep -qiE "(^|[^0-9])${stale}\s*(tool|endpoint|api)" 2>/dev/null; then
      fail "Page $page contains stale count '$stale'"
      STALE_FOUND=1
    fi
  done
done

if [ "$STALE_FOUND" -eq 0 ]; then
  pass "No stale tool counts on checked pages"
fi

echo ""

# ──────────────────────────────────────────────
# 6. OG image resolves
# ──────────────────────────────────────────────
echo -e "${CYAN}[6/8] OG Image${NC}"

# Extract og:image from landing page
OG_URL=$(curl -s --max-time 10 "$BASE_URL/" 2>/dev/null | grep -oP 'og:image.*?content="([^"]+)"' | grep -oP 'https?://[^"]+' | head -1 || echo "")

if [ -n "$OG_URL" ]; then
  OG_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$OG_URL" 2>/dev/null || echo "000")
  if [ "$OG_CODE" = "200" ]; then
    pass "OG image resolves ($OG_URL)"
  else
    fail "OG image returns HTTP $OG_CODE ($OG_URL)"
  fi
else
  warn "No og:image found on landing page"
fi

echo ""

# ──────────────────────────────────────────────
# 7. Free tier demo
# ──────────────────────────────────────────────
echo -e "${CYAN}[7/8] Free Tier Demo${NC}"

# Run via SSH to Oracle to bypass Cloudflare
DEMO_STATUS=$(ssh -i "$SSH_KEY" -o ConnectTimeout=5 -o StrictHostKeyChecking=no "$REMOTE" \
  "curl -s -o /dev/null -w '%{http_code}' -X POST http://localhost:5001/sentiment -H 'Content-Type: application/json' -d '{\"text\":\"audit test\"}'" 2>/dev/null || echo "")

if [ "$DEMO_STATUS" = "200" ]; then
  pass "POST /sentiment via Oracle (HTTP 200)"
elif [ "$DEMO_STATUS" = "402" ]; then
  pass "POST /sentiment via Oracle (HTTP 402 — free tier exhausted, expected)"
elif [ -z "$DEMO_STATUS" ]; then
  warn "SSH to Oracle failed — skipping demo test"
else
  fail "POST /sentiment — expected 200 or 402, got $DEMO_STATUS"
fi

echo ""

# ──────────────────────────────────────────────
# 8. SSL certificate
# ──────────────────────────────────────────────
echo -e "${CYAN}[8/8] SSL Certificate${NC}"

SSL_EXPIRY=$(echo | openssl s_client -servername "$DOMAIN" -connect "$DOMAIN:443" 2>/dev/null | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)

if [ -n "$SSL_EXPIRY" ]; then
  EXPIRY_EPOCH=$(date -d "$SSL_EXPIRY" +%s 2>/dev/null || echo "0")
  NOW_EPOCH=$(date +%s)
  DAYS_LEFT=$(( (EXPIRY_EPOCH - NOW_EPOCH) / 86400 ))

  if [ "$DAYS_LEFT" -gt 30 ]; then
    pass "SSL valid for ${DAYS_LEFT} days (expires: $SSL_EXPIRY)"
  elif [ "$DAYS_LEFT" -gt 7 ]; then
    warn "SSL expires in ${DAYS_LEFT} days — renew soon"
  else
    fail "SSL expires in ${DAYS_LEFT} days!"
  fi
else
  fail "Could not check SSL certificate"
fi

echo ""

# ──────────────────────────────────────────────
# Summary
# ──────────────────────────────────────────────
TOTAL=$((PASSED + FAILED))
echo -e "${BOLD}╔═══════════════════════════════════════╗${NC}"
echo -e "${BOLD}║       Site Audit Summary              ║${NC}"
echo -e "${BOLD}╚═══════════════════════════════════════╝${NC}"
echo -e "  ${GREEN}Passed:${NC}   $PASSED"
echo -e "  ${RED}Failed:${NC}   $FAILED"
echo -e "  ${YELLOW}Warnings:${NC} $WARNED"
echo -e "  ${CYAN}Total:${NC}    $TOTAL"
echo ""

if [ "$FAILED" -gt 0 ]; then
  echo -e "  ${RED}${BOLD}RESULT: FAIL${NC} — review issues above"
  exit 1
else
  echo -e "  ${GREEN}${BOLD}RESULT: PASS${NC}"
  exit 0
fi
