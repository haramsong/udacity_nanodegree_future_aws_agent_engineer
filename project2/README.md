# Customer Support AI Agent — Amazon Bedrock AgentCore

A production-shaped customer support agent for a fictional e-commerce store,
built on Amazon Bedrock AgentCore. The agent answers policy and product
questions from a knowledge base, looks up live order data and processes refunds
through the AgentCore Gateway, remembers customers across sessions, computes
loyalty discounts in a sandbox, and browses the live web.

Udacity — AWS AI Engineering Nanodegree, Course 2.

---

## What the agent can do

| Capability | How it is implemented |
|---|---|
| Product, policy and loyalty questions | RAG over a Bedrock Knowledge Base (Titan Text Embeddings V2 + OpenSearch Serverless) |
| Order and customer lookups | AgentCore Gateway → API Gateway REST target → `order-tracker` Lambda |
| Refunds and return labels | AgentCore Gateway → Lambda target → `refund-processor` Lambda |
| Memory across sessions | AgentCore Memory with a semantic strategy and a user-preference strategy |
| Exact discount arithmetic | AgentCore Code Interpreter, with a tier-only fallback |
| Live web pages | AgentCore Browser tool |

The model is Amazon Nova 2 Lite, reached through the
`global.amazon.nova-2-lite-v1:0` inference profile.

---

## Architecture

```
            agentcore invoke
                   │
                   ▼
    ┌──────────────────────────────┐
    │   AgentCore Runtime          │   main.py, @app.entrypoint
    │   (container, ARM64)         │
    └───┬───────┬───────┬──────┬───┘
        │       │       │      │
        │       │       │      └─► AgentCore Browser ──► live web
        │       │       │
        │       │       └────────► Code Interpreter (loyalty maths)
        │       │
        │       └────────────────► AgentCore Memory
        │                          cs_agent/{actorId}/facts
        │                          cs_agent/{actorId}/preferences
        │
        ├────────────────────────► Bedrock Knowledge Base
        │                          └─ OpenSearch Serverless ◄─ S3 (product_catalog.txt)
        │
        └────────────────────────► AgentCore Gateway (MCP, NONE authorizer)
                                   ├─ order-tracker    → API Gateway → Lambda
                                   └─ refund-processor → Lambda (direct)
```

The Gateway exposes six MCP tools: `get_order`, `get_customer_orders`,
`get_customer` from the REST API target, and `initiate_refund`,
`check_refund_status`, `get_return_label` from the Lambda target.

---

## Repository layout

```
main.py                            The agent — all eight TODO sections implemented
pyproject.toml                     Dependencies, plus an explicit setuptools backend
product_catalog.txt                Knowledge Base source document (uploaded to S3)
lambda/
  order_tracker.py                 Deployed as-is behind the REST API
  refund_processor.py              Deployed as-is as a direct Lambda target
  lambda_schema                    Tool schema for the refund Gateway target
infra/
  00-bootstrap.yaml                S3 bucket for Lambda zips and KB documents
  01-core.yaml                     Everything else: IAM, Lambda, REST API,
                                   OpenSearch Serverless, Knowledge Base,
                                   Memory, Gateway and both targets
  02-monitoring.yaml               ERROR metric filter and CloudWatch alarm
  deploy.sh                        Deploys the stacks, syncs the KB, writes the
                                   resource IDs into main.py
  grant-runtime-permissions.sh     Grants the runtime role access to the KB,
                                   Memory and browser
  destroy.sh                       Tears everything down
tests/
  run_tests.sh                     The six functional scenarios → a transcript
  local_invoke.py                  Runs the entrypoint locally
  transcripts/                     Generated test transcripts
evaluation/                        Screenshots and the written reflection
RUBRIC.md                          Grading criteria
```

`starter/` holds a pristine copy of the upstream starter code as a diff
baseline. It is git-ignored and is not part of the submission.

---

## Prerequisites

| Tool | Version used |
|---|---|
| Python | 3.14.7 (managed by `uv`) |
| uv | 0.12.15 |
| AWS CLI | v2 |
| Docker | 29.5.3, with `buildx` and `linux/arm64` emulation |
| Node.js | 18+ (only for MCP Inspector) |

Amazon Nova 2 Lite must be enabled under **Model access** in the Bedrock
console, in `us-east-1`.

An AWS profile named `udacity` is assumed throughout. Export it before running
anything:

```bash
export AWS_PROFILE=udacity
```

---

## Deployment

### 1. Install dependencies

```bash
uv sync
```

### 2. Create the AWS infrastructure

```bash
./infra/deploy.sh
```

This deploys both CloudFormation stacks, packages and uploads the Lambda
functions, uploads the knowledge base document, starts and waits for the
ingestion job, and finally writes `GATEWAY_URL`, `KB_ID`, `REGION` and
`MEMORY_ID` into `main.py`.

The AgentCore Runtime is deliberately **not** in CloudFormation — the agent
container is built and deployed with the starter toolkit instead.

### 3. Deploy the agent

```bash
agentcore configure --entrypoint main.py --name customer_support_agent
agentcore deploy --local-build
```

The agent name must match `^[A-Za-z][A-Za-z0-9_]{0,47}$` — hyphens are
rejected.

`--local-build` builds the ARM64 image with local Docker and pushes it to ECR.
Plain `agentcore deploy` builds in CodeBuild instead; that path is blocked in
this account by an Organizations service control policy, which stops the build
during provisioning with no build log.

Because the host is x86_64, arm64 emulation must be registered once:

```bash
docker run --privileged --rm tonistiigi/binfmt --install arm64
docker buildx create --name armbuilder --driver docker-container --use
```

### 4. Grant the runtime access to the project resources

```bash
./infra/grant-runtime-permissions.sh
```

`agentcore configure` generates an execution role scoped to what the toolkit
itself creates. It knows nothing about the Knowledge Base, Memory resource and
Gateway created by CloudFormation, and it does not grant the browser tool at
all. Without this step RAG, cross-session memory and browsing all fail on the
deployed agent while still working locally, because local runs use the
developer's own credentials.

### 5. Deploy monitoring

```bash
aws cloudformation deploy \
  --stack-name csai-monitoring \
  --template-file infra/02-monitoring.yaml \
  --parameter-overrides \
    RuntimeLogGroupName=/aws/bedrock-agentcore/runtimes/<agent-id>-DEFAULT
```

The log group only exists after the first deployment, which is why this is a
separate stack.

---

## Testing

```bash
./tests/run_tests.sh            # against the deployed runtime
./tests/run_tests.sh --local    # against main.py in-process
```

Both write a timestamped markdown transcript to `tests/transcripts/`.

Two things to know when running tests:

- **`agentcore invoke` reuses one runtime session id** stored in
  `.bedrock_agentcore.yaml`. AgentCore serialises requests within a session, so
  two concurrent invocations queue behind each other rather than running in
  parallel.
- **Memory extraction is asynchronous.** The cross-session recall test waits
  `MEMORY_WAIT` seconds (default 150) before the second session; without the
  wait the agent correctly reports that it has no memories yet.

---

## Implementation notes

**Namespace discovery.** `get_namespaces()` reads `namespaceTemplates` and falls
back to the legacy `namespaces` field, and accepts `type`,
`memoryStrategyType` or `strategyType` for the strategy type. The AgentCore API
in this account returns `namespaces`, so the fallback is load-bearing rather
than defensive.

**Graceful degradation.** If the Gateway cannot be reached, `invoke()` logs a
warning and runs with the local tools only instead of failing the request. This
keeps the agent available during a Gateway outage, at the cost of making a
Gateway problem look like a model that simply chose not to call a tool — worth
knowing when reading the logs.

**Discount arithmetic.** The business rules live in a generated Python string
executed in the Code Interpreter with `clearContext=True`: points floor to the
nearest 500, cap at 50% of the order, then the tier discount applies to the
remaining subtotal. The fallback path computes the tier discount alone and
returns the same fields with `calculation_method: "local_fallback"` so callers
can tell the two apart.

**Browser and Gateway coexistence.** `main.py` sets `asyncio._nest_patched`
before anything runs. `strands_tools.browser` calls `nest_asyncio.apply()` the
first time the browser tool executes, which replaces `asyncio.Task` with the
pure-Python implementation; on Python 3.14 that makes `asyncio.current_task()`
return `None`, anyio's cancel scope then fails, and every later MCP connection
to the Gateway raises `cannot create weak reference to 'NoneType' object`. The
patch is process-wide, so in a warm container the agent loses its Gateway tools
from the request after the browser first runs. Claiming the sentinel keeps
nest_asyncio's loop patches — which the browser wants — and skips the Task swap,
which it does not need, because Strands runs sync tools in a worker thread
rather than nesting event loops.

**Packaging.** `pyproject.toml` declares an explicit setuptools backend and
`py-modules = ["main"]`. Without it, the Dockerfile's `uv pip install .` falls
back to flat-layout auto-discovery, which treats `infra/`, `lambda/` and
`starter/` as packages and aborts the build.

---

## Verification record

Every rubric criterion is backed by a captured artifact. All six functional tests
were run against the **deployed** AgentCore Runtime, not locally.

### Functional tests

| Rubric criterion | Evidence | What it shows |
|---|---|---|
| MCP tool integration — API Gateway target | [`01-order-tracking.png`](evaluation/screenshots/01-order-tracking.png) | `ORD-001` → SHIPPED, UPS, `TRK987654321`, delivery 18 Sep 2026 |
| MCP tool integration — Lambda target | [`02-refund-processing.png`](evaluation/screenshots/02-refund-processing.png) | `ORD-002` → refund `REF-T5103IZU`, APPROVED, $139.99, 3–5 business days |
| Retrieval Augmented Generation | [`03-knowledge-base-rag.png`](evaluation/screenshots/03-knowledge-base-rag.png) | Platinum tier: free same-day shipping, 15% discount, priority support |
| Cross-session memory — write | [`04a-memory-session-a.png`](evaluation/screenshots/04a-memory-session-a.png) | `CUST-901` / `s-A` → "Hello Jane! I understand you prefer concise responses." |
| Cross-session memory — recall | [`04b-memory-session-b.png`](evaluation/screenshots/04b-memory-session-b.png) | `CUST-901` / `s-B` → recalls the name and the preference in a new session |
| Sandboxed code interpreter | [`05-loyalty-discount.png`](evaluation/screenshots/05-loyalty-discount.png) | 4,000 points → $40, Gold 10% → $11, **final $99.00**, 349 points left |
| Browser tool | [`06-browser-tool.png`](evaluation/screenshots/06-browser-tool.png) | Live title from udacity.com: "Learn the Latest Tech Skills; Advance Your Career \| Udacity" |

Tests 1 and 2 together satisfy "at least two distinct Gateway-backed tools, one
API-based target and one Lambda-based target".

Tests 4a and 4b share one `customer_id` and differ only in `session_id`, which is
what makes the recall meaningful. `tests/run_tests.sh` generates a fresh
`customer_id` per run for the same reason — replaying the suite under one fixed
id lets the agent answer 4a from facts it learned in an earlier run.

### Monitoring

| Rubric criterion | Evidence | What it shows |
|---|---|---|
| Metric filter on ERROR entries | [`07-cloudwatch-metric-filter.png`](evaluation/screenshots/07-cloudwatch-metric-filter.png) | `AgentErrorMetricFilter-uiha7UncYcpq`, pattern `ERROR` → `csai/Agent / AgentErrorCount` |
| Alarm above 5 errors in 5 minutes | [`08-cloudwatch-alarm.png`](evaluation/screenshots/08-cloudwatch-alarm.png) | `csai-agent-error-rate`: `AgentErrorCount > 5 for 1 datapoints within 5 minutes`, Sum, period 5 minutes |

### Setup verification

| Evidence | What it shows |
|---|---|
| [`00-caller-identity.png`](evaluation/screenshots/00-caller-identity.png) | Account `079401129916`, `arn:aws:iam::079401129916:user/admin` |
| [`00-mcp-inspector.png`](evaluation/screenshots/00-mcp-inspector.png) | MCP Inspector connected to the Gateway, all six tools listed with their schemas |
| [`00-knowledge-base-test.png`](evaluation/screenshots/00-knowledge-base-test.png) | `CustomerSupportKB` Test tab answering with the **15-day** electronics return window |
| [`00-agentcore-deploy.png`](evaluation/screenshots/00-agentcore-deploy.png) | `agentcore status` → `DEFAULT (READY)`, agent ARN, runtime log group |

### Other artifacts

| Path | |
|---|---|
| [`evaluation/README.md`](evaluation/README.md) | screenshot manifest — filename → rubric requirement → expected content |
| [`evaluation/REFLECTION.md`](evaluation/REFLECTION.md) | 354-word written reflection |
| [`tests/transcripts/`](tests/transcripts/) | full markdown transcripts of every suite run, deployed and local |

---

## Teardown

```bash
agentcore destroy          # the runtime, ECR image and toolkit-created memory
./infra/destroy.sh         # both CloudFormation stacks
```

Run this when finished. The OpenSearch Serverless collection bills by the hour
whether or not the agent is running, and the Gateway uses the `NONE` authorizer,
so neither should be left up.
