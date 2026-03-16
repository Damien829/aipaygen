#!/bin/bash
# Pre-deploy consistency checker — catches stale numbers, broken refs, and drift
# Runs against LOCAL codebase before rsync
# Exit 0 = all pass, 1 = failures detected
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

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

# --- Current canonical values ---
CURRENT_TOOL_COUNT="250"
STALE_TOOL_COUNTS="244 169 165 162 161 155 153 156"
CURRENT_VERSION="1.9.0"
STALE_VERSIONS="1.8.3 1.8.2 1.8.1 1.8.0 1.7.1"

# Read FREE_DAILY_LIMIT from source of truth
FREE_LIMIT=$(python3 -c "
import re
with open('agent_network.py') as f:
    m = re.search(r'FREE_DAILY_LIMIT\s*=\s*(\d+)', f.read())
    print(m.group(1) if m else '?')
" 2>/dev/null || echo "?")

# Files/dirs to exclude from checks (changelogs, history, memory, git)
EXCLUDE_PATTERN="(CHANGELOG|changelog|MEMORY|session_history|SHOW_HN|REDDIT_LAUNCH|\.git/|__pycache__|\.pyc$|venv/|node_modules/|\.claude/)"

echo -e "${BOLD}╔═══════════════════════════════════════╗${NC}"
echo -e "${BOLD}║   AiPayGen Consistency Checker        ║${NC}"
echo -e "${BOLD}╚═══════════════════════════════════════╝${NC}"
echo -e "  Dir:     $SCRIPT_DIR"
echo -e "  Time:    $(date '+%Y-%m-%d %H:%M:%S')"
echo -e "  Tools:   $CURRENT_TOOL_COUNT"
echo -e "  Version: $CURRENT_VERSION"
echo -e "  Free:    $FREE_LIMIT calls/day"
echo ""

# ──────────────────────────────────────────────
# 1. Tool count consistency
# ──────────────────────────────────────────────
echo -e "${CYAN}[1/7] Tool Count Consistency${NC}"

TOOL_ISSUES=0
for stale in $STALE_TOOL_COUNTS; do
  # Search for "NNN tool" or "NNN endpoint" or "NNN api" patterns (case insensitive)
  HITS=$(grep -rn --include='*.py' --include='*.html' --include='*.json' --include='*.sh' --include='*.txt' --include='*.md' \
    -iE "(^|[^0-9])${stale}\s*(tool|endpoint|api|MCP)" \
    . 2>/dev/null | grep -vE "$EXCLUDE_PATTERN" || true)
  if [ -n "$HITS" ]; then
    fail "Stale tool count '$stale' found:"
    echo "$HITS" | head -5 | sed 's/^/         /'
    COUNT=$(echo "$HITS" | wc -l)
    if [ "$COUNT" -gt 5 ]; then
      echo -e "         ${YELLOW}... and $((COUNT - 5)) more${NC}"
    fi
    TOOL_ISSUES=1
  fi
done

if [ "$TOOL_ISSUES" -eq 0 ]; then
  pass "No stale tool counts found"
fi

# Verify current count appears somewhere
CURRENT_REFS=$(grep -rn --include='*.py' --include='*.html' --include='*.json' \
  -E "(^|[^0-9])${CURRENT_TOOL_COUNT}\s*(tool|endpoint|api|MCP)" \
  . 2>/dev/null | grep -vE "$EXCLUDE_PATTERN" | wc -l || echo "0")
if [ "$CURRENT_REFS" -gt 0 ]; then
  pass "Current tool count ($CURRENT_TOOL_COUNT) referenced in $CURRENT_REFS places"
else
  warn "Current tool count ($CURRENT_TOOL_COUNT) not found in any source file"
fi

echo ""

# ──────────────────────────────────────────────
# 2. Version consistency
# ──────────────────────────────────────────────
echo -e "${CYAN}[2/7] Version Consistency${NC}"

VERSION_ISSUES=0
for stale in $STALE_VERSIONS; do
  # Look for version strings like "v1.8.3" or "version.*1.8.3" or '"1.8.3"'
  HITS=$(grep -rn --include='*.py' --include='*.html' --include='*.json' --include='*.toml' --include='*.cfg' \
    -E "(version|__version__|\"version\").*${stale//./\\.}" \
    . 2>/dev/null | grep -vE "$EXCLUDE_PATTERN" || true)
  if [ -n "$HITS" ]; then
    fail "Stale version '$stale' found:"
    echo "$HITS" | head -5 | sed 's/^/         /'
    VERSION_ISSUES=1
  fi
done

if [ "$VERSION_ISSUES" -eq 0 ]; then
  pass "No stale versions found"
fi

# Verify current version in key files
for key_file in mcp_server.py sdk/python/pyproject.toml; do
  if [ -f "$key_file" ]; then
    if grep -q "$CURRENT_VERSION" "$key_file" 2>/dev/null; then
      pass "$key_file has version $CURRENT_VERSION"
    else
      fail "$key_file missing version $CURRENT_VERSION"
    fi
  fi
done

echo ""

# ──────────────────────────────────────────────
# 3. Free tier limit consistency
# ──────────────────────────────────────────────
echo -e "${CYAN}[3/7] Free Tier Limit Consistency${NC}"

if [ "$FREE_LIMIT" = "?" ]; then
  fail "Could not read FREE_DAILY_LIMIT from agent_network.py"
else
  pass "FREE_DAILY_LIMIT = $FREE_LIMIT (from agent_network.py)"

  # Check for hardcoded free tier numbers that don't match
  # Look for patterns like "10 free" "3 free" "5 free calls" etc.
  MISMATCHES=$(grep -rn --include='*.py' --include='*.html' \
    -iE "[0-9]+\s*(free\s*(call|request|tier|daily)|calls?\s*(per|a)\s*day)" \
    . 2>/dev/null | grep -vE "$EXCLUDE_PATTERN" | grep -vE "(${FREE_LIMIT}\s*free|${FREE_LIMIT}\s*call|FREE_DAILY_LIMIT)" || true)

  if [ -n "$MISMATCHES" ]; then
    # Filter to only lines with a different number than FREE_LIMIT
    BAD=$(echo "$MISMATCHES" | grep -vE "(^|[^0-9])${FREE_LIMIT}([^0-9]|$)" || true)
    if [ -n "$BAD" ]; then
      warn "Possible stale free tier references (expected $FREE_LIMIT):"
      echo "$BAD" | head -5 | sed 's/^/         /'
    else
      pass "All free tier references consistent ($FREE_LIMIT)"
    fi
  else
    pass "No hardcoded free tier limits found outside source of truth"
  fi
fi

echo ""

# ──────────────────────────────────────────────
# 4. OG tag check
# ──────────────────────────────────────────────
echo -e "${CYAN}[4/7] OG Tag Consistency${NC}"

OG_ISSUES=0
# Check all templates for og:image pointing to wrong domain
BAD_OG=$(grep -rn --include='*.html' \
  'og:image' templates/ 2>/dev/null | grep -v 'aipaygen.com' || true)

if [ -n "$BAD_OG" ]; then
  fail "OG images not pointing to aipaygen.com:"
  echo "$BAD_OG" | head -5 | sed 's/^/         /'
  OG_ISSUES=1
fi

# Check that key templates have og:image
for tmpl in templates/landing.html templates/index.html templates/pricing.html templates/discover.html; do
  if [ -f "$tmpl" ]; then
    if grep -q 'og:image' "$tmpl" 2>/dev/null; then
      pass "$tmpl has og:image tag"
    else
      warn "$tmpl missing og:image tag"
    fi
  fi
done

if [ "$OG_ISSUES" -eq 0 ]; then
  pass "All OG images point to aipaygen.com"
fi

echo ""

# ──────────────────────────────────────────────
# 5. Nav link consistency
# ──────────────────────────────────────────────
echo -e "${CYAN}[5/7] Nav Link Consistency${NC}"

if [ -f "templates/base.html" ]; then
  # Check required nav links exist in base template
  REQUIRED_NAV_LINKS="/try /docs /pricing /playground /get-key"
  NAV_ISSUES=0
  for link in $REQUIRED_NAV_LINKS; do
    if grep -q "href=\"${link}\"" templates/base.html 2>/dev/null; then
      pass "Nav has $link"
    else
      fail "Nav missing $link in base.html"
      NAV_ISSUES=1
    fi
  done

  # Check footer links
  REQUIRED_FOOTER_LINKS="/docs /try /blog /discover"
  for link in $REQUIRED_FOOTER_LINKS; do
    if grep -q "href=\"${link}\"" templates/base.html 2>/dev/null; then
      pass "Footer has $link"
    else
      warn "Footer missing $link in base.html"
    fi
  done
else
  fail "templates/base.html not found"
fi

echo ""

# ──────────────────────────────────────────────
# 6. Route existence check
# ──────────────────────────────────────────────
echo -e "${CYAN}[6/7] Route Existence${NC}"

# Critical routes that must exist in the codebase
CRITICAL_ROUTES="/support /get-key /referrals /examples /integrations /status /changelog /playground /dashboard"
for route in $CRITICAL_ROUTES; do
  if grep -rq "route(\"${route}\"" routes/ app.py 2>/dev/null; then
    pass "Route $route exists"
  else
    fail "Route $route not found in routes/ or app.py"
  fi
done

echo ""

# ──────────────────────────────────────────────
# 7. Import check
# ──────────────────────────────────────────────
echo -e "${CYAN}[7/7] Import Check${NC}"

IMPORT_OUTPUT=$(python3 -c "
import sys, os
os.chdir('$SCRIPT_DIR')
sys.path.insert(0, '.')
try:
    import app
    print('OK')
except Exception as e:
    print(f'FAIL: {e}')
" 2>&1)

if echo "$IMPORT_OUTPUT" | grep -q "^OK$"; then
  pass "import app succeeded"
else
  # Sometimes app needs Flask context — try just syntax check on key files
  SYNTAX_OK=true
  for pyfile in app.py mcp_server.py agent_network.py model_router.py helpers.py; do
    if [ -f "$pyfile" ]; then
      if python3 -m py_compile "$pyfile" 2>/dev/null; then
        pass "$pyfile syntax OK"
      else
        fail "$pyfile has syntax errors"
        SYNTAX_OK=false
      fi
    fi
  done

  if [ "$SYNTAX_OK" = true ]; then
    warn "import app failed (may need runtime deps): $(echo "$IMPORT_OUTPUT" | head -1)"
  fi
fi

echo ""

# ──────────────────────────────────────────────
# Summary
# ──────────────────────────────────────────────
TOTAL=$((PASSED + FAILED))
echo -e "${BOLD}╔═══════════════════════════════════════╗${NC}"
echo -e "${BOLD}║    Consistency Check Summary          ║${NC}"
echo -e "${BOLD}╚═══════════════════════════════════════╝${NC}"
echo -e "  ${GREEN}Passed:${NC}   $PASSED"
echo -e "  ${RED}Failed:${NC}   $FAILED"
echo -e "  ${YELLOW}Warnings:${NC} $WARNED"
echo -e "  ${CYAN}Total:${NC}    $TOTAL"
echo ""

if [ "$FAILED" -gt 0 ]; then
  echo -e "  ${RED}${BOLD}RESULT: FAIL${NC} — fix issues before deploying"
  exit 1
else
  echo -e "  ${GREEN}${BOLD}RESULT: PASS${NC}"
  exit 0
fi
