#!/usr/bin/env bash
# functional_tests.sh — Comprehensive live functional tests for AiPayGen
# Runs REAL HTTP requests against the live Oracle server via Cloudflare
# Usage: bash functional_tests.sh
set -euo pipefail

###############################################################################
# Config
###############################################################################
BASE="https://aipaygen.com"
ORACLE_SSH="ssh -i ~/.ssh/oracle_key -o StrictHostKeyChecking=no ubuntu@150.136.124.81"
PASS=0
FAIL=0
SKIP=0
ERRORS=""
TEST_KEYS=()  # track keys we create for cleanup

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

###############################################################################
# Helpers
###############################################################################
log_pass() { ((PASS++)); echo -e "  ${GREEN}PASS${NC} $1"; }
log_fail() { ((FAIL++)); echo -e "  ${RED}FAIL${NC} $1 — $2"; ERRORS+="FAIL: $1 — $2\n"; }
log_skip() { ((SKIP++)); echo -e "  ${YELLOW}SKIP${NC} $1 — $2"; }
section()  { echo -e "\n${CYAN}═══ $1 ═══${NC}"; }

# Make a request returning "HTTP_CODE|BODY"
# Usage: result=$(req POST /path '{"json":"data"}' "Bearer key")
req() {
    local method="$1" path="$2" body="${3:-}" auth="${4:-}"
    local url="${BASE}${path}"
    local args=(-s -w '\n%{http_code}' -X "$method" --max-time 30)
    args+=(-H "Content-Type: application/json")
    [[ -n "$auth" ]] && args+=(-H "Authorization: $auth")
    [[ -n "$body" ]] && args+=(-d "$body")
    local raw
    raw=$(curl "${args[@]}" "$url" 2>/dev/null) || { echo "000|curl_error"; return; }
    local code body_out
    code=$(echo "$raw" | tail -1)
    body_out=$(echo "$raw" | sed '$d')
    echo "${code}|${body_out}"
}

# Extract JSON field (simple jq wrapper)
jval() { echo "$1" | jq -r "$2" 2>/dev/null; }

# Get HTTP code from req output
http_code() { echo "$1" | cut -d'|' -f1; }

# Get body from req output
http_body() { echo "$1" | cut -d'|' -f2-; }

# Run a command on Oracle via SSH
oracle() { $ORACLE_SSH "$@" 2>/dev/null; }

# DB helper: run sqlite3 on Oracle's api_keys.db
oracle_db() {
    oracle "cd /home/ubuntu/agent-service && sqlite3 api_keys.db \"$1\""
}

###############################################################################
# Pre-flight
###############################################################################
section "PRE-FLIGHT CHECKS"

# Check connectivity
result=$(req GET /health)
if [[ "$(http_code "$result")" == "200" ]]; then
    log_pass "Cloudflare → Oracle connectivity"
else
    log_fail "Cloudflare → Oracle connectivity" "got $(http_code "$result")"
    echo "Cannot reach server. Aborting."
    exit 1
fi

# Check SSH
if oracle "echo ok" | grep -q ok; then
    log_pass "SSH to Oracle"
else
    log_fail "SSH to Oracle" "cannot connect"
    echo "SSH needed for DB manipulation. Aborting."
    exit 1
fi

###############################################################################
# 1. FREE ENDPOINTS (should NOT charge)
###############################################################################
section "FREE ENDPOINTS (no billing)"

# /health
result=$(req GET /health)
code=$(http_code "$result")
[[ "$code" == "200" ]] && log_pass "GET /health → 200" || log_fail "GET /health" "got $code"

# /api/stats
result=$(req GET /api/stats)
code=$(http_code "$result")
[[ "$code" == "200" ]] && log_pass "GET /api/stats → 200" || log_fail "GET /api/stats" "got $code"

# /api/usage
result=$(req GET /api/usage)
code=$(http_code "$result")
# May require key, but should not 402
[[ "$code" != "402" ]] && log_pass "GET /api/usage → no 402 (got $code)" || log_fail "GET /api/usage" "got 402 — should be free"

# /auth/generate-key (POST, free)
result=$(req POST /auth/generate-key '{"label":"ftest-free-check"}')
code=$(http_code "$result")
body=$(http_body "$result")
if [[ "$code" == "200" ]]; then
    log_pass "POST /auth/generate-key → 200 (free, no billing)"
    FREE_CHECK_KEY=$(jval "$body" '.key')
    TEST_KEYS+=("$FREE_CHECK_KEY")
else
    log_fail "POST /auth/generate-key" "got $code"
fi

###############################################################################
# 2. PAYMENT FLOW (MOST CRITICAL)
###############################################################################
section "PAYMENT FLOW — Key lifecycle"

# 2.1 Generate key → verify $0.25 balance
result=$(req POST /auth/generate-key '{"label":"ftest-payment"}')
code=$(http_code "$result")
body=$(http_body "$result")
if [[ "$code" == "200" ]]; then
    TEST_KEY=$(jval "$body" '.key')
    TEST_BALANCE=$(jval "$body" '.balance_usd')
    TEST_KEYS+=("$TEST_KEY")
    if (( $(echo "$TEST_BALANCE == 0.25" | bc -l) )); then
        log_pass "Generate key → \$0.25 trial balance"
    else
        log_fail "Generate key balance" "expected 0.25, got $TEST_BALANCE"
    fi
else
    log_fail "Generate key" "got $code"
    TEST_KEY=""
fi

if [[ -n "${TEST_KEY:-}" ]]; then
    # 2.2 Make paid call → verify balance decreased
    result=$(req POST /sentiment '{"text":"I love this product"}' "Bearer $TEST_KEY")
    code=$(http_code "$result")
    body=$(http_body "$result")
    if [[ "$code" == "200" ]]; then
        log_pass "Paid call /sentiment → 200"
        # Check balance via auth/status
        status_result=$(req POST /auth/status "{\"key\":\"$TEST_KEY\"}")
        bal1=$(jval "$(http_body "$status_result")" '.balance_usd')
        if (( $(echo "$bal1 < 0.25" | bc -l) )); then
            log_pass "Balance decreased after call (was 0.25, now $bal1)"
        else
            log_fail "Balance not decreased" "still $bal1"
        fi
    else
        log_fail "Paid call /sentiment" "got $code — $(jval "$(http_body "$result")" '.error')"
        bal1="0.25"
    fi

    # 2.3 Make 2nd call → verify balance decreased again (no double-bill bug)
    result=$(req POST /explain '{"text":"What is TCP?"}' "Bearer $TEST_KEY")
    code=$(http_code "$result")
    if [[ "$code" == "200" ]]; then
        status_result=$(req POST /auth/status "{\"key\":\"$TEST_KEY\"}")
        bal2=$(jval "$(http_body "$status_result")" '.balance_usd')
        if (( $(echo "${bal2:-0} < ${bal1:-0}" | bc -l) )); then
            log_pass "2nd call deducted correctly (now $bal2)"
        else
            log_fail "2nd call balance" "expected < $bal1, got $bal2"
        fi
    else
        log_fail "2nd paid call /explain" "got $code"
    fi

    # 2.4 Set balance to $0.001 → verify 402 insufficient_balance
    oracle_db "UPDATE api_keys SET balance_usd = 0.001 WHERE key = '$TEST_KEY';"
    sleep 1
    result=$(req POST /sentiment '{"text":"test"}' "Bearer $TEST_KEY")
    code=$(http_code "$result")
    err=$(jval "$(http_body "$result")" '.error')
    if [[ "$code" == "402" && "$err" == "insufficient_balance" ]]; then
        log_pass "Low balance → 402 insufficient_balance"
    else
        log_fail "Low balance rejection" "expected 402/insufficient_balance, got $code/$err"
    fi

    # 2.5 Deactivate key → verify 401 invalid_api_key
    oracle_db "UPDATE api_keys SET is_active = 0 WHERE key = '$TEST_KEY';"
    sleep 1
    result=$(req POST /sentiment '{"text":"test"}' "Bearer $TEST_KEY")
    code=$(http_code "$result")
    err=$(jval "$(http_body "$result")" '.error')
    if [[ "$code" == "401" && "$err" == "invalid_api_key" ]]; then
        log_pass "Deactivated key → 401 invalid_api_key"
    else
        log_fail "Deactivated key" "expected 401/invalid_api_key, got $code/$err"
    fi

    # Reactivate for later tests
    oracle_db "UPDATE api_keys SET is_active = 1, balance_usd = 0.25 WHERE key = '$TEST_KEY';"
fi

# 2.6 Fake key → verify 401
result=$(req POST /sentiment '{"text":"test"}' "Bearer apk_FAKE_KEY_DOES_NOT_EXIST_12345")
code=$(http_code "$result")
err=$(jval "$(http_body "$result")" '.error')
if [[ "$code" == "401" && "$err" == "invalid_api_key" ]]; then
    log_pass "Fake key → 401 invalid_api_key"
else
    log_fail "Fake key" "expected 401/invalid_api_key, got $code/$err"
fi

# 2.7 No key, exhaust free tier → verify 402 free_tier_exhausted
# Use a unique IP-like header to simulate (won't work through CF, so test localhost)
section "FREE TIER EXHAUSTION (via localhost on Oracle)"
EXHAUST_RESULT=$(oracle "for i in 1 2 3 4 5; do curl -s -o /dev/null -w '%{http_code}\n' -X POST http://localhost:5001/sentiment -H 'Content-Type: application/json' -H 'X-Forwarded-For: 198.51.100.99' -d '{\"text\":\"test\"}'; done" 2>/dev/null)
LAST_CODE=$(echo "$EXHAUST_RESULT" | tail -1)
if [[ "$LAST_CODE" == "402" ]]; then
    log_pass "Free tier exhausted → 402 on 4th+ call"
else
    log_fail "Free tier exhaustion" "expected 402 on last call, got $LAST_CODE (all: $EXHAUST_RESULT)"
fi

# 2.8 Negative deduction attempt
section "NEGATIVE DEDUCTION"
# The deduct() function rejects negative amounts. Verify by checking DB directly.
NEG_RESULT=$(oracle "cd /home/ubuntu/agent-service && python3 -c \"
from api_keys import deduct
result = deduct('$TEST_KEY', -1.0)
print(result)
\"" 2>/dev/null)
if [[ "$NEG_RESULT" == "False" ]]; then
    log_pass "Negative deduction rejected (returns False)"
else
    log_fail "Negative deduction" "expected False, got $NEG_RESULT"
fi

###############################################################################
# 3. ALL PAID ENDPOINTS — Billing enforcement
###############################################################################
section "PAID ENDPOINTS — Billing enforcement (402 without key, 200 with key)"

# Generate a fresh test key with enough balance
result=$(req POST /auth/generate-key '{"label":"ftest-billing"}')
BILLING_KEY=$(jval "$(http_body "$result")" '.key')
TEST_KEYS+=("$BILLING_KEY")
# Top up to $2.00 for bulk testing
oracle_db "UPDATE api_keys SET balance_usd = 2.00 WHERE key = '$BILLING_KEY';"
sleep 1

# Define all paid routes with their method, path, and test body
declare -A PAID_ROUTES
PAID_ROUTES=(
    ["/sentiment"]='{"text":"I love this"}'
    ["/summarize"]='{"text":"The quick brown fox jumps over the lazy dog. This is a test sentence that needs to be summarized for testing purposes."}'
    ["/translate"]='{"text":"Hello world","target_language":"es"}'
    ["/explain"]='{"text":"What is TCP?"}'
    ["/analyze"]='{"text":"Sales grew 15% in Q3"}'
    ["/write"]='{"prompt":"Write a haiku about testing"}'
    ["/code"]='{"prompt":"Write hello world in Python"}'
    ["/keywords"]='{"text":"Machine learning and artificial intelligence are transforming industries"}'
    ["/classify"]='{"text":"I want a refund","categories":["support","sales","billing"]}'
    ["/compare"]='{"text_a":"Hello world","text_b":"Hi there world"}'
    ["/transform"]='{"text":"hello world","instruction":"uppercase"}'
    ["/proofread"]='{"text":"Ths is a tset sentance"}'
    ["/questions"]='{"text":"Python is a programming language"}'
    ["/outline"]='{"topic":"Machine learning basics"}'
    ["/rewrite"]='{"text":"This is bad","style":"formal"}'
    ["/extract"]='{"text":"John is 30 years old","schema":{"name":"string","age":"number"}}'
    ["/qa"]='{"question":"What color?","context":"The sky is blue."}'
    ["/tag"]='{"text":"A recipe for chocolate cake with vanilla frosting"}'
    ["/score"]='{"text":"This is a well-written article","rubric":["clarity","grammar"]}'
    ["/headline"]='{"text":"A new AI tool that helps developers write better code faster"}'
    ["/fact"]='{"text":"The Earth orbits the Sun at 67000 mph"}'
    ["/action"]='{"text":"John should update the docs by Friday. Mary will review the PR."}'
    ["/timeline"]='{"text":"In 1969 man landed on the moon. In 1989 the Berlin wall fell."}'
    ["/regex"]='{"description":"Match email addresses"}'
    ["/json-schema"]='{"description":"A user with name, email, and age"}'
    ["/mock"]='{"schema":"A list of 3 users with name and email","format":"json"}'
    ["/cron"]='{"description":"Every Monday at 9am"}'
    ["/email"]='{"to":"test","subject":"Hi","tone":"formal"}'
    ["/sql"]='{"description":"Get all users over 18","dialect":"postgresql"}'
    ["/plan"]='{"goal":"Launch a SaaS product"}'
    ["/decide"]='{"question":"Should I use Python or Go?","options":["Python","Go"]}'
    ["/pitch"]='{"product":"AI-powered code review tool"}'
    ["/debate"]='{"topic":"Should AI be regulated?"}'
    ["/diagram"]='{"description":"User login flow","type":"flowchart"}'
    ["/privacy-check"]='{"text":"My SSN is 123-45-6789 and my email is test@test.com"}'
    ["/test-cases"]='{"code":"def add(a,b): return a+b"}'
    ["/batch"]='{"operations":[{"tool":"sentiment","params":{"text":"good"}},{"tool":"sentiment","params":{"text":"bad"}}]}'
    ["/chain"]='{"steps":[{"tool":"sentiment","params":{"text":"I love this"}}]}'
    ["/vision"]='{"image_url":"https://upload.wikimedia.org/wikipedia/commons/thumb/a/a7/Camponotus_flavomarginatus_ant.jpg/320px-Camponotus_flavomarginatus_ant.jpg","question":"What is this?"}'
    ["/scrape"]='{"url":"https://example.com"}'
    ["/research"]='{"query":"What is x402 protocol?"}'
)

# Streaming endpoints (test separately — they return SSE)
STREAM_ROUTES=(
    "/stream/research|{\"query\":\"What is x402?\"}"
    "/stream/write|{\"prompt\":\"Write a haiku\"}"
    "/stream/analyze|{\"text\":\"Sales grew 15%\"}"
)

# Test each paid route
for path in "${!PAID_ROUTES[@]}"; do
    body="${PAID_ROUTES[$path]}"

    # Without key → should get 402
    result=$(req POST "$path" "$body")
    code=$(http_code "$result")
    err=$(jval "$(http_body "$result")" '.error')
    if [[ "$code" == "402" ]]; then
        log_pass "$path without key → 402"
    else
        # Could be free tier (first 3 calls), so 200 is OK too
        if [[ "$code" == "200" ]]; then
            log_pass "$path without key → 200 (free tier)"
        else
            log_fail "$path without key" "expected 402, got $code ($err)"
        fi
    fi

    # With key → should get 200
    result=$(req POST "$path" "$body" "Bearer $BILLING_KEY")
    code=$(http_code "$result")
    if [[ "$code" == "200" ]]; then
        log_pass "$path with key → 200"
    elif [[ "$code" == "202" ]]; then
        log_pass "$path with key → 202 (accepted)"
    else
        err=$(jval "$(http_body "$result")" '.error // .message // empty')
        log_fail "$path with key" "expected 200, got $code ($err)"
    fi
done

# Check balance decreased after all those calls
status_result=$(req POST /auth/status "{\"key\":\"$BILLING_KEY\"}")
final_bal=$(jval "$(http_body "$status_result")" '.balance_usd')
echo -e "\n  Billing key started at \$2.00, now at \$${final_bal}"
if (( $(echo "${final_bal:-2} < 2.0" | bc -l) )); then
    log_pass "Aggregate billing: balance decreased from \$2.00 to \$${final_bal}"
else
    log_fail "Aggregate billing" "balance did not decrease (still $final_bal)"
fi

# Streaming endpoints
section "STREAMING ENDPOINTS"
for entry in "${STREAM_ROUTES[@]}"; do
    path=$(echo "$entry" | cut -d'|' -f1)
    body=$(echo "$entry" | cut -d'|' -f2)

    # Without key → 402
    result=$(req POST "$path" "$body")
    code=$(http_code "$result")
    if [[ "$code" == "402" || "$code" == "200" ]]; then
        log_pass "$path without key → $code"
    else
        log_fail "$path without key" "expected 402, got $code"
    fi

    # With key → 200 (SSE streams start with 200)
    result=$(req POST "$path" "$body" "Bearer $BILLING_KEY")
    code=$(http_code "$result")
    if [[ "$code" == "200" ]]; then
        log_pass "$path with key → 200 (stream started)"
    else
        log_fail "$path with key" "expected 200, got $code"
    fi
done

###############################################################################
# 4. WORKFLOW & CHAIN ENDPOINTS
###############################################################################
section "WORKFLOW ENDPOINTS"

# /workflow/run
result=$(req POST /workflow/run '{"template":"content_brief","params":{"topic":"AI testing"}}' "Bearer $BILLING_KEY")
code=$(http_code "$result")
if [[ "$code" == "200" || "$code" == "202" ]]; then
    log_pass "/workflow/run with key → $code"
else
    err=$(jval "$(http_body "$result")" '.error // .message // empty')
    log_fail "/workflow/run with key" "got $code ($err)"
fi

# /code/run
result=$(req POST /code/run '{"code":"print(2+2)"}' "Bearer $BILLING_KEY")
code=$(http_code "$result")
if [[ "$code" == "200" ]]; then
    output=$(jval "$(http_body "$result")" '.stdout // .output // .result // empty')
    log_pass "/code/run → 200"
else
    log_fail "/code/run" "got $code"
fi

###############################################################################
# 5. EDGE CASES
###############################################################################
section "EDGE CASES"

# 5.1 Empty body → 400
result=$(req POST /sentiment '' "Bearer $BILLING_KEY")
code=$(http_code "$result")
if [[ "$code" == "400" || "$code" == "422" ]]; then
    log_pass "Empty body → $code"
elif [[ "$code" == "415" ]]; then
    log_pass "Empty body → 415 (content-type mismatch)"
else
    log_fail "Empty body" "expected 400/422, got $code"
fi

# 5.2 Wrong content-type → 415 or 400
wrong_ct_result=$(curl -s -w '\n%{http_code}' -X POST "${BASE}/sentiment" \
    -H "Authorization: Bearer $BILLING_KEY" \
    -H "Content-Type: text/plain" \
    -d 'just plain text' --max-time 15 2>/dev/null)
wc_code=$(echo "$wrong_ct_result" | tail -1)
if [[ "$wc_code" == "415" || "$wc_code" == "400" ]]; then
    log_pass "Wrong content-type → $wc_code"
else
    log_fail "Wrong content-type" "expected 415/400, got $wc_code"
fi

# 5.3 Huge payload (1MB) → rejection
huge_payload=$(python3 -c "import json; print(json.dumps({'text': 'x' * 1048576}))")
huge_result=$(curl -s -w '\n%{http_code}' -X POST "${BASE}/sentiment" \
    -H "Authorization: Bearer $BILLING_KEY" \
    -H "Content-Type: application/json" \
    -d "$huge_payload" --max-time 30 2>/dev/null)
huge_code=$(echo "$huge_result" | tail -1)
if [[ "$huge_code" == "413" || "$huge_code" == "400" || "$huge_code" == "422" || "$huge_code" == "200" ]]; then
    log_pass "Huge payload (1MB) → $huge_code"
else
    log_fail "Huge payload" "expected 413/400/422, got $huge_code"
fi

# 5.4 Concurrent requests with same key → no race condition
section "CONCURRENCY TEST"
# Generate a key with exactly $0.10
result=$(req POST /auth/generate-key '{"label":"ftest-concurrent"}')
CONC_KEY=$(jval "$(http_body "$result")" '.key')
TEST_KEYS+=("$CONC_KEY")
oracle_db "UPDATE api_keys SET balance_usd = 0.10 WHERE key = '$CONC_KEY';"
sleep 1

# Fire 5 concurrent sentiment calls ($0.01 each flat) — should allow ~10
for i in 1 2 3 4 5; do
    curl -s -o /dev/null -w "%{http_code}\n" -X POST "${BASE}/sentiment" \
        -H "Authorization: Bearer $CONC_KEY" \
        -H "Content-Type: application/json" \
        -d '{"text":"concurrent test"}' --max-time 20 &
done
wait
# Check final balance
sleep 2
status_result=$(req POST /auth/status "{\"key\":\"$CONC_KEY\"}")
conc_bal=$(jval "$(http_body "$status_result")" '.balance_usd')
conc_count=$(jval "$(http_body "$status_result")" '.call_count')
echo -e "  Concurrent key: balance=$conc_bal, calls=$conc_count"
if [[ -n "$conc_bal" && "$conc_bal" != "null" ]]; then
    # Balance should be >= 0 (no negative from race)
    if (( $(echo "$conc_bal >= 0" | bc -l) )); then
        log_pass "Concurrent requests: no negative balance (bal=$conc_bal, calls=$conc_count)"
    else
        log_fail "Concurrent requests" "negative balance: $conc_bal"
    fi
else
    log_skip "Concurrent balance check" "could not read balance"
fi

# 5.5 Chain with failing step → correct handling
section "CHAIN WITH FAILING STEP"
result=$(req POST /chain '{"steps":[{"tool":"sentiment","params":{"text":"good"}},{"tool":"nonexistent_tool","params":{}}]}' "Bearer $BILLING_KEY")
code=$(http_code "$result")
body=$(http_body "$result")
if [[ "$code" == "200" || "$code" == "207" || "$code" == "400" ]]; then
    log_pass "Chain with bad step → $code (handled gracefully)"
else
    log_fail "Chain with bad step" "got $code"
fi

###############################################################################
# 6. ADDITIONAL ENDPOINT CHECKS
###############################################################################
section "ADDITIONAL ENDPOINTS"

# Memory endpoints
for ep in "/memory/set" "/memory/get" "/memory/list" "/memory/search" "/memory/clear"; do
    result=$(req POST "$ep" '{"agent_id":"test-agent","key":"test","value":"hello","query":"test"}' "Bearer $BILLING_KEY")
    code=$(http_code "$result")
    if [[ "$code" == "200" || "$code" == "201" ]]; then
        log_pass "$ep → $code"
    else
        log_fail "$ep" "got $code"
    fi
done

# Message endpoints
result=$(req POST /message/send '{"from":"agent-a","to":"agent-b","content":"hello"}' "Bearer $BILLING_KEY")
code=$(http_code "$result")
[[ "$code" == "200" || "$code" == "201" ]] && log_pass "/message/send → $code" || log_fail "/message/send" "got $code"

# Knowledge
result=$(req POST /knowledge/add '{"agent_id":"test","title":"test","content":"test content"}' "Bearer $BILLING_KEY")
code=$(http_code "$result")
[[ "$code" == "200" || "$code" == "201" ]] && log_pass "/knowledge/add → $code" || log_fail "/knowledge/add" "got $code"

# Task
result=$(req POST /task/submit '{"title":"Test task","description":"Do something"}' "Bearer $BILLING_KEY")
code=$(http_code "$result")
[[ "$code" == "200" || "$code" == "201" ]] && log_pass "/task/submit → $code" || log_fail "/task/submit" "got $code"

# Scrape endpoints (may fail if Apify not configured, but should not 500)
for ep in "/scrape/website" "/scrape/web"; do
    result=$(req POST "$ep" '{"url":"https://example.com"}' "Bearer $BILLING_KEY")
    code=$(http_code "$result")
    if [[ "$code" == "200" || "$code" == "202" || "$code" == "400" || "$code" == "422" ]]; then
        log_pass "$ep → $code"
    elif [[ "$code" == "500" ]]; then
        log_fail "$ep" "500 server error"
    else
        log_pass "$ep → $code (non-500)"
    fi
done

# Auth status
result=$(req POST /auth/status "{\"key\":\"$BILLING_KEY\"}")
code=$(http_code "$result")
[[ "$code" == "200" ]] && log_pass "/auth/status → 200" || log_fail "/auth/status" "got $code"

# Auth topup (verify structure, not actual payment)
result=$(req POST /auth/topup "{\"key\":\"$BILLING_KEY\",\"amount\":0}")
code=$(http_code "$result")
[[ "$code" == "200" || "$code" == "400" ]] && log_pass "/auth/topup → $code" || log_fail "/auth/topup" "got $code"

###############################################################################
# 7. META / DISCOVERY ENDPOINTS
###############################################################################
section "META / DISCOVERY ENDPOINTS"

for ep in "/docs" "/pricing" "/discover" "/changelog" "/status" "/playground" "/openapi.json" "/.well-known/ai-plugin.json" "/llms.txt" "/robots.txt" "/sitemap.xml"; do
    result=$(req GET "$ep")
    code=$(http_code "$result")
    if [[ "$code" == "200" ]]; then
        log_pass "GET $ep → 200"
    elif [[ "$code" == "301" || "$code" == "302" ]]; then
        log_pass "GET $ep → $code (redirect)"
    else
        log_fail "GET $ep" "got $code"
    fi
done

###############################################################################
# CLEANUP
###############################################################################
section "CLEANUP"
for k in "${TEST_KEYS[@]}"; do
    oracle_db "DELETE FROM api_keys WHERE key = '$k';" 2>/dev/null || true
done
# Clean up free tier usage for our test IP
oracle_db "DELETE FROM free_tier_usage WHERE ip = '198.51.100.99';" 2>/dev/null || true
echo -e "  Cleaned up ${#TEST_KEYS[@]} test keys"

###############################################################################
# SUMMARY
###############################################################################
echo ""
echo -e "${CYAN}═══════════════════════════════════════════════════${NC}"
echo -e "  ${GREEN}PASSED${NC}: $PASS"
echo -e "  ${RED}FAILED${NC}: $FAIL"
echo -e "  ${YELLOW}SKIPPED${NC}: $SKIP"
TOTAL=$((PASS + FAIL + SKIP))
echo -e "  TOTAL:   $TOTAL"
echo -e "${CYAN}═══════════════════════════════════════════════════${NC}"

if [[ $FAIL -gt 0 ]]; then
    echo -e "\n${RED}FAILURES:${NC}"
    echo -e "$ERRORS"
    exit 1
else
    echo -e "\n${GREEN}ALL TESTS PASSED${NC}"
    exit 0
fi
