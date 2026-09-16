#!/usr/bin/env bash
#
# Part 3 — functional test scenarios.
#
#   ./tests/run_tests.sh            # against the deployed AgentCore Runtime
#   ./tests/run_tests.sh --local    # against main.py running locally
#
# Writes a timestamped transcript to tests/transcripts/ for the submission.
#
set -uo pipefail

MODE="deployed"
[ "${1:-}" = "--local" ] && MODE="local"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$ROOT/tests/transcripts"
mkdir -p "$OUT_DIR"
TRANSCRIPT="$OUT_DIR/$(date +%Y%m%d-%H%M%S)-$MODE.md"

export AWS_PROFILE="${AWS_PROFILE:-udacity}"
export AWS_REGION="${AWS_REGION:-us-east-1}"

# A fresh customer id per run. The memory tests only mean something against a
# customer with no stored history: re-running the suite under one fixed id makes
# the agent answer test 4a from facts it learned in an earlier run rather than
# from the message in front of it. Override with CUSTOMER_ID=... to replay a
# previous run's customer.
CUSTOMER="${CUSTOMER_ID:-CUST-$(date +%H%M%S)}"

# AgentCore extracts long-term memory records from saved events asynchronously.
# Test 4b must not run until that extraction has finished, or the agent will
# correctly report that it remembers nothing.
MEMORY_WAIT="${MEMORY_WAIT:-150}"

# name | session_id | prompt | what the rubric expects to see
TESTS=(
"1. Order Tracking (Gateway — API target)|t1|Can you track order ORD-001?|SHIPPED, tracking TRK987654321, carrier UPS, estimated delivery"
"2. Refund Processing (Gateway — Lambda target)|t2|I want to return my Kindle Paperwhite (ORD-002). Please initiate a refund.|refund ID, APPROVED status, 3-5 business days"
"3. Knowledge Base (RAG)|t3|What are the benefits of the Platinum loyalty tier?|free same-day shipping, 15% discount, priority support"
"4a. Memory — session A (store)|s-A|Hi, I am Jane. I prefer concise responses.|acknowledges the name and the preference"
"4b. Memory — session B (recall)|s-B|Do you remember my name and communication preference?|recalls Jane and concise responses"
"5. Loyalty Discount (Code Interpreter)|t5|I am a Gold member with 4250 points. Calculate my discount on a \$150 standard order.|4000 points redeemed, 10% tier discount, \$99.00 final total, 349 points remaining"
"6. Browser Tool|t6|Go to https://www.udacity.com and tell me the page title.|page title retrieved from the live Udacity.com page"
)

run_one() {
  local payload="$1"
  if [ "$MODE" = "local" ]; then
    (cd "$ROOT" && PYTHONPATH="$ROOT" uv run python tests/local_invoke.py "$payload" 2>&1)
  else
    (cd "$ROOT" && uv run agentcore invoke "$payload" 2>&1)
  fi
}

{
  echo "# Functional Test Transcript"
  echo
  echo "- Mode: \`$MODE\`"
  echo "- Date: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
  echo "- Customer ID: \`$CUSTOMER\` (fresh per run — see tests/run_tests.sh)"
  echo
} | tee "$TRANSCRIPT"

for entry in "${TESTS[@]}"; do
  IFS='|' read -r NAME SESSION PROMPT EXPECTED <<< "$entry"

  if [ "$SESSION" = "s-B" ]; then
    echo
    echo "Waiting ${MEMORY_WAIT}s for AgentCore memory extraction before the recall test..."
    sleep "$MEMORY_WAIT"
  fi

  PAYLOAD=$(python3 -c '
import json, sys
print(json.dumps({"prompt": sys.argv[1], "customer_id": sys.argv[2], "session_id": sys.argv[3]}))
' "$PROMPT" "$CUSTOMER" "$SESSION")

  {
    echo "---"
    echo
    echo "## Test $NAME"
    echo
    echo "**Expected:** $EXPECTED"
    echo
    echo '```'
    echo "\$ agentcore invoke '$PAYLOAD'"
  } | tee -a "$TRANSCRIPT"

  run_one "$PAYLOAD" | tee -a "$TRANSCRIPT"

  { echo '```'; echo; } | tee -a "$TRANSCRIPT"
done

echo
echo "Transcript written to: $TRANSCRIPT"
