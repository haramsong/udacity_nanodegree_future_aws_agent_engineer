# project3 — Verification record

Every rubric criterion, the evidence for it, and what that evidence actually shows.
The two required screenshots are in [`screenshots/`](screenshots/); everything else below
was read back from AWS or captured from terminal runs against the same deployment.

Related: [project README](../README.md) · [implementation](../src/agent_orchestrator.py) ·
[populated `.env`](../.env) · [screenshots](screenshots/) · [all projects](../../)

| Resource | Value |
| --- | --- |
| Region / account | `us-east-1` / `087411424993` |
| Foundation stack | `udacity-agentcore` (CloudFormation) |
| Orchestrator model | `us.anthropic.claude-haiku-4-5-20251001-v1:0` (`config.ORCHESTRATOR_MODEL_ID`) |
| Worker model | `us.anthropic.claude-sonnet-4-5-20250929-v1:0` (`config.WORKER_MODEL_ID`) |
| Knowledge Bases | Returns `3JBAYDYDV9` · Shipping `VEWGFB92H4` · Warranty `XLGHQHZ6DY` |
| Vector store | S3 Vectors `udacity-agentcore-vectors-087411424993-efc6d440`, indexes `returns-` / `shipping-` / `warranty-policy-index` |
| Guardrail | `udacity-agentcore-guardrail` / `8yqe7mjgvtmd`, version `1` (READY) |
| AgentCore Runtime | `udacity_agentcore_runtime-pKgrBJD9Sh` (CLI stack `AgentCore-udacity-default`) |
| AgentCore Memory | `udacity_agentcore_memory-uJstPACOjE` (ACTIVE) |
| Log group | `/aws/bedrock/agentcore/udacity-agentcore` |

---

## Required screenshots

| File | Deliverable |
| --- | --- |
| [`screenshots/1-1a.png`](screenshots/1-1a.png), [`screenshots/1-1b.png`](screenshots/1-1b.png) | `python tests/test_agent.py all` — **120/120** |
| [`screenshots/2-1a.png`](screenshots/2-1a.png), [`screenshots/2-1b.png`](screenshots/2-1b.png) | X-Ray Service Map — `NovaMart-Orchestrator → Worker (→ Knowledge Base)` |

### `screenshots/1-1a.png` and `screenshots/1-1b.png` — full test suite, 120/120

One run of `AWS_PROFILE=udacity python tests/test_agent.py all`, split across two frames.

`1-1a` covers Tasks 2–5:

- **Task 2** — all five builders return an `Agent`; InventoryAgent has 3 tools, PolicyAgent 1,
  Orchestrator 5; Orchestrator uses `ORCHESTRATOR_MODEL_ID` (Haiku 4.5), workers use
  `WORKER_MODEL_ID` (Sonnet 4.5); the static check confirms `build_policy_agent()` runs
  the retrievers with `ThreadPoolExecutor`.
- **Task 3** — guardrail `udacity-agentcore-guardrail` exists; content, PII, topic and word
  policies match the specification; **version 1 is published and READY**; the runtime is
  **READY (PUBLIC / HTTP) with guardrail + KB environment variables**.
- **Task 4** — memory `udacity_agentcore_memory-uJstPACOjE` is ACTIVE, uses
  `summaryMemoryStrategy`, `eventExpiryDuration` is 7 days.
- **Task 5** — each KB ID is set, each KB is ACTIVE, uses `amazon.titan-embed-text-v2:0`,
  and has a completed sync; all three return passages for a policy question. The frame ends
  on the `[PARALLEL RETRIEVAL - START]` banner of `test_5_parallel_retrieval`, with the
  three sub-agents dispatched to their KB IDs.

`1-1b` continues from there:

- The three retriever results printed sequentially after the parallel run — `ShippingRetriever`
  and `WarrantyRetriever` (and `ReturnsRetriever` above the fold) each quoting passages with
  their `s3://…/policies/<domain>/…` source — followed by **`search_all_policies()` returned
  combined results from the three retrievers (9.1s)**.
- **Task 6** — CloudWatch logging enabled at INFO → `/aws/bedrock/agentcore/udacity-agentcore`;
  X-Ray tracing enabled at **100% sampling, Transaction Search → CloudWatch Logs (ACTIVE)**;
  12 NovaMart traces received by X-Ray in the last 6 hours.
- **Score: 120/120 pts (100%)**.

### `screenshots/2-1a.png` and `screenshots/2-1b.png` — X-Ray Service Map

`CloudWatch → X-Ray traces → Trace Map` after `python src/agent_orchestrator.py test` and
several `invoke` calls against the deployed runtime. The map is taller than one screen, so it
is captured in two overlapping frames; node labels are truncated by the console
(`NovaMart…estrator` = `NovaMart-Orchestrator`, `Knowledg…:warranty` = `KnowledgeBase:warranty`).

There are **two `NovaMart-Orchestrator` nodes**, and that is expected:

| Orchestrator node | Origin |
| --- | --- |
| `Client → NovaMart-Orchestrator` | local runs (`test`, `chat`, `demo`) |
| `Client (Environment …ric:default) → NovaMart-Orchestrator (Environment …ric:default)` | the deployed AgentCore Runtime (`invoke`) |

Both fan out to the same downstream nodes, all marked **Remote**:

| Node | Frame |
| --- | --- |
| `RefundAgent`, `CommunicationAgent` | `2-1a` |
| `PolicyAgent`, `InventoryAgent` | `2-1b` |
| `KnowledgeBase:returns`, `KnowledgeBase:shipping` | both |
| `KnowledgeBase:warranty` | `2-1a` |

That is all four worker agents and all three Knowledge Bases, connected to the orchestrator.
Each `route_to_*` tool call is recorded as a worker-agent subsegment and each KB retrieval as a
`KnowledgeBase:<domain>` subsegment by the pre-written `agent_observability.py`, so the
Knowledge Base nodes appear as edges from the orchestrator node rather than from
`PolicyAgent` — the map shows every node the request touched, flattened to one level.

The same graph read through the API (`aws xray get-service-graph`, last 20 minutes) lists
`CommunicationAgent`, `InventoryAgent`, `KnowledgeBase:returns|shipping|warranty`,
`PolicyAgent`, `RefundAgent`, and `NovaMart-Orchestrator` with 7 outgoing edges.

> CloudWatch's **Application Map** (Application Signals) is a different view: it shows the
> orchestrator connected to a single `UnknownRemoteService`. The rubric asks for the X-Ray
> Service/Trace Map, which is what these frames show.

---

## 1. Multi-Agent Graph — met

| Requirement | Evidence |
| --- | --- |
| Inventory / Refund / Communication agents with the correct tools | `1-1a` (tool counts) · `build_*_agent()` in `src/agent_orchestrator.py` |
| Refund windows: Standard 30 days, Premium 60 days | `RETURN_WINDOW_DAYS` + RefundAgent prompt; run below |
| All workers on `config.WORKER_MODEL_ID`; Inventory/Refund `temperature=0.1`, Communication `0.3` | `1-1a` · builders |
| Three retriever sub-agents with the correct KB IDs | `ReturnsPolicyRetrieverAgent` / `ShippingPolicyRetrieverAgent` / `WarrantyPolicyRetrieverAgent`; `1-1b` |
| Parallel retrieval with `ThreadPoolExecutor(max_workers=3)` + `as_completed()` | `1-1a` static check · `1-1b` combined result |
| Retrievers `temperature=0.0`, PolicyAgent `0.2` | `build_policy_agent()` |
| Orchestrator on `config.ORCHESTRATOR_MODEL_ID`, `temperature=0.0`, six routing rules | `1-1a` · `build_orchestrator_agent()` |
| Routing tools read WorkflowState, then write with `expected_version` | `_run_worker()` |
| `route_to_communication_agent` always last; orchestrator never writes the reply | routing traces below |

### Routing, observed in the local `test` run

Tool calls printed by `python src/agent_orchestrator.py test` (orchestrator tool numbers):

```
CUST-001  "I want to return my wireless headphones from order ORD-27176"
  #1 initialize_session → #2 route_to_inventory_agent → #3 route_to_refund_agent → #4 route_to_communication_agent

CUST-002  "What is the return policy for premium customers?"
  #5 initialize_session → #6 route_to_policy_agent → #7 route_to_communication_agent
          (PolicyAgent → search_all_policies → 3 retrievers in parallel)

CUST-003  "How much would 5 items at $29.99 be with a 10% discount?"
  #8 initialize_session → #9 route_to_communication_agent
```

Each matches the expected routing in the project's end-to-end table: Inventory → Refund for a
return, Policy for a policy question, straight to CommunicationAgent for arithmetic, and
CommunicationAgent last every time.

### The same scenarios against the deployed runtime

`python src/agent_orchestrator.py invoke "<message>" <customer>` — responses abridged:

| Customer | Request | Response |
| --- | --- | --- |
| CUST-001 (Premium) | I want to return my order ORD-27176 | Approved, reference `RET-D294CB03`, label within 24 h, refund of $149.99 in 5–7 business days; *"As a Premium member, you have a 60-day return window"* |
| CUST-002 | What is the return policy for premium customers? | 60-day window vs. standard 30, Premium qualification ($500+ or 20+ orders), other Premium benefits |
| CUST-003 | How much are 5 items at $29.99 with 10% off? | $149.95 subtotal, $14.995 discount, **final total $134.96** |

---

## 2. AgentCore Runtime and Guardrails — met

| Requirement | Evidence |
| --- | --- |
| Content filters SEXUAL / VIOLENCE / HATE HIGH, INSULTS / MISCONDUCT MEDIUM | `1-1a` (policies match the specification) |
| PII: card number and SSN BLOCK, email and phone ANONYMIZE | `1-1a` |
| DENY topics: competitor products, pricing negotiations, legal threats | `1-1a` |
| Managed profanity list | `1-1a` |
| `create_guardrail_version()` → numbered version | `1-1a`: version 1 published and READY |
| Deployed via `agentcore_cli.configure_runtime()` / `deploy()` / `deployed_runtime_arn()`, PUBLIC / HTTP, stack execution role | `1-1a`: runtime READY (PUBLIC / HTTP) |
| Runtime env includes the KB IDs, log group and numbered `GUARDRAIL_VERSION` | `1-1a`: guardrail + KB environment variables |
| `.env` has `AGENTCORE_RUNTIME_ARN` | [`../.env`](../.env) |

The topic policy uses the STANDARD tier (`tierConfig`) with the `us.guardrail.v1:0`
cross-region profile, and defines *pricing negotiations* as haggling or changing an advertised
price while excluding arithmetic on a price the customer supplies.

### Guardrail behaviour on the deployed runtime

| Request (CUST-001) | Result |
| --- | --- |
| How much are 5 items at $29.99 with 10% off? | **Allowed** — question and answer both pass ($134.96 above) |
| Can you knock 20 dollars off my headphones or I'll cancel? | **Blocked** (pricing negotiation) |
| Is Amazon cheaper than NovaMart for wireless headphones? | **Blocked** (competitor products) |
| I'm going to sue NovaMart if you don't refund me today. | **Blocked** (legal threats) |

All three blocked requests return the configured input message: *"I'm sorry, but I can't help
with that request. I'm happy to assist with your NovaMart orders, returns, shipping or warranty
questions."*

---

## 3. Memory and Knowledge Bases — met

| Requirement | Evidence |
| --- | --- |
| `create_memory()` with `summaryMemoryStrategy`, name and description | `configure_memory()` · `1-1a` |
| `eventExpiryDuration=7`, returns `memoryArn` | `1-1a` |
| Three KBs on `policies/returns/`, `policies/shipping/`, `policies/warranty/` | `1-1a` |
| Titan Embed Text v2, S3 Vectors bucket from the stack with the matching index | `1-1a` (embedding model) · resource table above |
| Each data source synced | `1-1a`: completed sync ×3 (2 documents indexed per KB, 0 failed) |
| `.env` has the three KB IDs | `1-1a` · [`../.env`](../.env) |
| `search_all_policies()` returns results from all three KBs | `1-1b` |

The KBs are self-managed (not Managed KB): each uses the stack's vector bucket with its own
index, and the stack's `udacity-agentcore-agentcore-role` as the service role.

---

## 4. Observability — met

| Requirement | Evidence |
| --- | --- |
| `configure_observability()` builds `loggingConfiguration`, applies it in `try/except` | `src/agent_orchestrator.py` |
| CloudWatch: `config.AGENT_LOG_GROUP`, `INFO`, enabled | `1-1b` |
| X-Ray: enabled, `samplingRate=1.0` | `1-1b` (100% sampling, Transaction Search ACTIVE) |
| Service Map: `NovaMart-Orchestrator` → worker agents incl. `PolicyAgent` and the KB nodes | `2-1a`, `2-1b` |

`AGENT_TRACING_ENABLED`, `AGENT_TRACE_SAMPLING_RATE` and `AGENT_LOG_LEVEL` stay commented out in
`.env`: they are optional local overrides whose defaults are already *on*, *1.0* and *INFO*.
The deployed runtime receives them from `apply_observability_config()` via
`agentcore/agentcore.json`.

---

## Issues found while testing, and the fixes

| Symptom | Cause | Fix |
| --- | --- | --- |
| A routing tool failed and was retried on the first call of a request | Haiku requested `initialize_session` and `route_to_*` in the same turn; Strands runs tool calls concurrently by default, so the routing tool read WorkflowState before it existed | Orchestrator uses `SequentialToolExecutor()`; the order also protects Inventory → Refund |
| Math answer came back as $134.95 once | The model rounded the $14.995 discount to $15.00 mid-calculation | CommunicationAgent prompt: full precision throughout, round half up once at the end |
| Math reply began with *"This is a straightforward arithmetic question…"* | CommunicationAgent's reasoning leaked into the customer message | Prompt: output only the customer message, no preamble |
| A return was denied on a second run | The first run had already set ORD-27176 to `return_initiated` — correct behaviour | `infrastructure/seed_data.py` re-run before the final tests |

---

## Clean-up

After the review is complete: `AWS_PROFILE=udacity python infrastructure/cleanup.py --yes`.
The resources are left in place until then in case the reviewer asks for changes.
