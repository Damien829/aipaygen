#!/bin/bash
# Smoke tests for AiPayGen live site
# Usage: ./smoke_tests.sh [base_url]
# Exit code 0 = all passed, 1 = failures detected

set -uo pipefail

BASE_URL="${1:-https://api.aipaygen.com}"
MCP_URL="https://mcp.aipaygen.com"
DOMAIN="api.aipaygen.com"
MAX_RESPONSE_TIME=2  # seconds — warn if slower

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

# Check HTTP status code + response time
# Usage: check_endpoint "label" "url" expected_code [method] [data] [content_type]
check_endpoint() {
  local label="$1"
  local url="$2"
  local expected="$3"
  local method="${4:-GET}"
  local data="${5:-}"
  local ctype="${6:-application/json}"

  local curl_args=(-s -o /tmp/smoke_body.txt -w "%{http_code}|%{time_total}" --max-time 10)

  if [ "$method" = "POST" ]; then
    curl_args+=(-X POST -H "Content-Type: $ctype")
    if [ -n "$data" ]; then
      curl_args+=(-d "$data")
    fi
  fi

  local result
  result=$(curl "${curl_args[@]}" "$url" 2>/dev/null) || result="000|0"

  local code="${result%%|*}"
  local time="${result##*|}"

  if [ "$code" = "$expected" ]; then
    pass "$label (HTTP $code, ${time}s)"
    # Warn on slow responses
    if (( $(echo "$time > $MAX_RESPONSE_TIME" | bc -l 2>/dev/null || echo 0) )); then
      warn "$label response time ${time}s exceeds ${MAX_RESPONSE_TIME}s threshold"
    fi
    return 0
  else
    fail "$label — expected HTTP $expected, got $code"
    return 1
  fi
}

echo -e "${BOLD}╔═══════════════════════════════════╗${NC}"
echo -e "${BOLD}║      AiPayGen Smoke Tests         ║${NC}"
echo -e "${BOLD}╚═══════════════════════════════════╝${NC}"
echo -e "  Target: $BASE_URL"
echo -e "  Time:   $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# ──────────────────────────────────────────────
# 1. Core endpoints
# ──────────────────────────────────────────────
echo -e "${CYAN}[Core Endpoints]${NC}"

check_endpoint "/health" "$BASE_URL/health" 200
# Verify health response body
if [ -f /tmp/smoke_body.txt ]; then
  HEALTH_STATUS=$(python3 -c "import json; d=json.load(open('/tmp/smoke_body.txt')); print(d.get('status',''))" 2>/dev/null || echo "")
  if [ "$HEALTH_STATUS" = "healthy" ]; then
    pass "/health body: status=healthy"
  else
    fail "/health body: expected status=healthy, got '$HEALTH_STATUS'"
  fi
fi

check_endpoint "/health/deep" "$BASE_URL/health/deep" 200
# Verify deep health checks
if [ -f /tmp/smoke_body.txt ]; then
  DEEP_OK=$(python3 -c "
import json
d = json.load(open('/tmp/smoke_body.txt'))
checks = d.get('checks', {})
failed = [k for k, v in checks.items() if v in (False, 'error', 'down')]
print('ok' if not failed else ','.join(failed))
" 2>/dev/null || echo "error")
  if [ "$DEEP_OK" = "ok" ]; then
    pass "/health/deep: all checks passed"
  else
    fail "/health/deep: failed checks: $DEEP_OK"
  fi
fi

check_endpoint "/" "$BASE_URL/" 200
check_endpoint "/pricing" "$BASE_URL/pricing" 200
check_endpoint "/discover" "$BASE_URL/discover" 200

echo ""

# ──────────────────────────────────────────────
# 2. API endpoints
# ──────────────────────────────────────────────
echo -e "${CYAN}[API Endpoints]${NC}"

check_endpoint "/api/stats" "$BASE_URL/api/stats" 200
# Verify stats is valid JSON
if [ -f /tmp/smoke_body.txt ]; then
  if python3 -c "import json; json.load(open('/tmp/smoke_body.txt'))" 2>/dev/null; then
    pass "/api/stats: valid JSON"
  else
    fail "/api/stats: invalid JSON response"
  fi
fi

check_endpoint "/openapi.json" "$BASE_URL/openapi.json" 200

echo ""

# ──────────────────────────────────────────────
# 3. Static assets
# ──────────────────────────────────────────────
echo -e "${CYAN}[Static Assets]${NC}"

check_endpoint "/og-image.png" "$BASE_URL/og-image.png" 200
# Verify content type
if [ -f /tmp/smoke_body.txt ]; then
  OG_CTYPE=$(curl -s -o /dev/null -w "%{content_type}" --max-time 10 "$BASE_URL/og-image.png" 2>/dev/null || echo "")
  if echo "$OG_CTYPE" | grep -qi "image/png"; then
    pass "/og-image.png: content-type is image/png"
  else
    warn "/og-image.png: content-type is '$OG_CTYPE' (expected image/png)"
  fi
fi

check_endpoint "/robots.txt" "$BASE_URL/robots.txt" 200
check_endpoint "/sitemap.xml" "$BASE_URL/sitemap.xml" 200

echo ""

# ──────────────────────────────────────────────
# 4. MCP service
# ──────────────────────────────────────────────
echo -e "${CYAN}[MCP Service]${NC}"

check_endpoint "MCP /health" "$MCP_URL/health" 200
if [ -f /tmp/smoke_body.txt ]; then
  MCP_TOOLS=$(python3 -c "import json; d=json.load(open('/tmp/smoke_body.txt')); print(d.get('tools', d.get('tool_count', '?')))" 2>/dev/null || echo "?")
  if [ "$MCP_TOOLS" = "244" ]; then
    pass "MCP tools: 244"
  else
    warn "MCP tools: $MCP_TOOLS (expected 244)"
  fi
fi

echo ""

# ──────────────────────────────────────────────
# 5. Free-tier demo call
# ──────────────────────────────────────────────
echo -e "${CYAN}[Free Tier Demo]${NC}"

check_endpoint "POST /sentiment" "$BASE_URL/sentiment" 200 POST '{"text":"AiPayGen is great!"}' "application/json"
if [ -f /tmp/smoke_body.txt ]; then
  SENTIMENT=$(python3 -c "import json; d=json.load(open('/tmp/smoke_body.txt')); print(d.get('sentiment', d.get('result', {}).get('sentiment', '?')))" 2>/dev/null || echo "?")
  if [ "$SENTIMENT" != "?" ] && [ -n "$SENTIMENT" ]; then
    pass "/sentiment returned: $SENTIMENT"
  else
    warn "/sentiment response format unexpected"
  fi
fi

echo ""

# ──────────────────────────────────────────────
# 6. SSL certificate
# ──────────────────────────────────────────────
echo -e "${CYAN}[SSL Certificate]${NC}"

SSL_EXPIRY=$(echo | openssl s_client -servername "$DOMAIN" -connect "$DOMAIN:443" 2>/dev/null | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)
if [ -n "$SSL_EXPIRY" ]; then
  EXPIRY_EPOCH=$(date -d "$SSL_EXPIRY" +%s 2>/dev/null || echo "0")
  NOW_EPOCH=$(date +%s)
  DAYS_LEFT=$(( (EXPIRY_EPOCH - NOW_EPOCH) / 86400 ))

  if [ "$DAYS_LEFT" -gt 30 ]; then
    pass "SSL valid for ${DAYS_LEFT} days (expires: $SSL_EXPIRY)"
  elif [ "$DAYS_LEFT" -gt 7 ]; then
    warn "SSL expires in ${DAYS_LEFT} days (expires: $SSL_EXPIRY)"
  else
    fail "SSL expires in ${DAYS_LEFT} days! (expires: $SSL_EXPIRY)"
  fi
else
  fail "Could not check SSL certificate"
fi

echo ""

# ──────────────────────────────────────────────
# Summary
# ──────────────────────────────────────────────
TOTAL=$((PASSED + FAILED))
echo -e "${BOLD}╔═══════════════════════════════════╗${NC}"
echo -e "${BOLD}║        Smoke Test Summary         ║${NC}"
echo -e "${BOLD}╚═══════════════════════════════════╝${NC}"
echo -e "  ${GREEN}Passed:${NC}   $PASSED"
echo -e "  ${RED}Failed:${NC}   $FAILED"
echo -e "  ${YELLOW}Warnings:${NC} $WARNED"
echo -e "  ${CYAN}Total:${NC}    $TOTAL"
echo ""

if [ "$FAILED" -gt 0 ]; then
  echo -e "  ${RED}${BOLD}RESULT: FAIL${NC}"
  exit 1
else
  echo -e "  ${GREEN}${BOLD}RESULT: PASS${NC}"
  exit 0
fi
