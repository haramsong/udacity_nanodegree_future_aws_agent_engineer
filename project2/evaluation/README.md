# Evaluation Artifacts

Verification record for the project. Every rubric criterion below is backed by a
captured artifact in [`screenshots/`](screenshots/). All six functional tests were
run against the **deployed** AgentCore Runtime via `agentcore invoke`, not locally.

The same runs are also recorded as markdown transcripts under
[`../tests/transcripts/`](../tests/transcripts/) — most recently
[`20260916-130406-deployed.md`](../tests/transcripts/20260916-130406-deployed.md). The screenshots are the visual version of that.

## Required — functional tests

| # | Evidence | Rubric requirement | What it shows |
|---|----------|--------------------|---------------|
| 1 | [`01-order-tracking.png`](screenshots/01-order-tracking.png) | MCP tool integration — API Gateway target | `ORD-001` → SHIPPED, carrier UPS, tracking `TRK987654321`, delivery 18 Sep 2026 |
| 2 | [`02-refund-processing.png`](screenshots/02-refund-processing.png) | MCP tool integration — Lambda target | `ORD-002` → refund `REF-T5103IZU`, APPROVED, $139.99, credit in 3–5 business days |
| 3 | [`03-knowledge-base-rag.png`](screenshots/03-knowledge-base-rag.png) | Retrieval Augmented Generation | Platinum tier: free same-day shipping, 15% discount, priority customer support |
| 4a | [`04a-memory-session-a.png`](screenshots/04a-memory-session-a.png) | Cross-session memory — write | `CUST-901` / session `s-A` → "Hello Jane! I understand you prefer concise responses." |
| 4b | [`04b-memory-session-b.png`](screenshots/04b-memory-session-b.png) | Cross-session memory — recall | `CUST-901` / session `s-B` → recalls the name and the preference in a new session |
| 5 | [`05-loyalty-discount.png`](screenshots/05-loyalty-discount.png) | Sandboxed code interpreter | 4,000 points → $40, Gold 10% → $11, **final total $99.00**, 349 points remaining |
| 6 | [`06-browser-tool.png`](screenshots/06-browser-tool.png) | Browser tool | Live title from udacity.com: "Learn the Latest Tech Skills; Advance Your Career \| Udacity" |

Tests 1 and 2 together satisfy the rubric's "at least two distinct
Gateway-backed tools, one API-based target and one Lambda-based target" —
`get_order` comes from the API Gateway REST stage target and `initiate_refund`
from the direct Lambda target.

**Why 4a and 4b share a customer id.** Cross-session recall only means anything
when both sessions address the same actor, so the two differ in `session_id`
alone. They also use a customer with no prior history: replaying the suite under
one fixed id lets the agent answer 4a from facts it learned in an earlier run
rather than from the message in front of it, which is exactly what happened on
the first attempt. [`../tests/run_tests.sh`](../tests/run_tests.sh) now generates
a fresh `customer_id` per run.

**Why 4b needs a delay.** AgentCore extracts long-term memory records from saved
events asynchronously. Run session B a couple of minutes after session A, or the
agent will correctly report that it remembers nothing. The test runner waits
`MEMORY_WAIT` seconds (default 150) between the two.

## Required — monitoring

Both resources are created by
[`../infra/02-monitoring.yaml`](../infra/02-monitoring.yaml).

| # | Evidence | What it shows |
|---|----------|---------------|
| 7 | [`07-cloudwatch-metric-filter.png`](screenshots/07-cloudwatch-metric-filter.png) | `AgentErrorMetricFilter-uiha7UncYcpq` on the runtime log group — pattern `ERROR` → `csai/Agent / AgentErrorCount` |
| 8 | [`08-cloudwatch-alarm.png`](screenshots/08-cloudwatch-alarm.png) | `csai-agent-error-rate`: `AgentErrorCount > 5 for 1 datapoints within 5 minutes`, statistic Sum, period 5 minutes |

## Required — written reflection

[`REFLECTION.md`](REFLECTION.md) — 354 words covering the three required points:

1. **A design decision** — the Gateway's graceful-degradation path, and the
   availability-versus-observability trade-off it makes.
2. **A challenge** — the `nest_asyncio` / Python 3.14 interaction that silently
   stripped the agent's Gateway tools after the first request in a warm
   container, and how it was reproduced.
3. **A production consideration** — the Gateway's `NONE` authorizer letting any
   caller invoke `initiate_refund`, and what replacing it would involve.

## Setup verification

Not required by the rubric, but they record that the infrastructure was built and
verified before any agent code ran.

| Evidence | What it shows |
|----------|---------------|
| [`00-caller-identity.png`](screenshots/00-caller-identity.png) | `aws sts get-caller-identity` → account `079401129916`, `arn:aws:iam::079401129916:user/admin` |
| [`00-mcp-inspector.png`](screenshots/00-mcp-inspector.png) | MCP Inspector connected to the Gateway, all six tools listed with their input schemas |
| [`00-knowledge-base-test.png`](screenshots/00-knowledge-base-test.png) | `CustomerSupportKB` Test tab answering with the **15-day** electronics return window |
| [`00-agentcore-deploy.png`](screenshots/00-agentcore-deploy.png) | `agentcore status` → `DEFAULT (READY)`, agent ARN, runtime log group |

## See also

| Path | |
|------|--|
| [`../README.md`](../README.md) | architecture, deployment order, implementation notes, teardown |
| [`../main.py`](../main.py) | the agent — all eight starter TODO sections implemented |
| [`../infra/`](../infra/) | CloudFormation templates and the deploy / permissions / destroy scripts |
| [`../RUBRIC.md`](../RUBRIC.md) | the grading criteria these artifacts map onto |
