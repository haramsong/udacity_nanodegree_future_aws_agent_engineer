# Customer support Bedrock Flow

A Bedrock Flow that classifies an incoming customer message and routes it down one of
three paths: file a bug ticket, answer from the shop FAQ, or hand off to the phone line.

## Architecture

```
[FlowInput]  document (String)
     │
     ├─ Data ─────────────────────────────────────────────────────┐
     ▼                                                            │
[ClassifyRequest]  Prompt · nova-lite · T=0 · maxTokens=5         │
     │             returns exactly BUG | FAQ | OTHER              │
     ▼                                                            │
[RouteRequest]  Condition                                         │  (branch text inputs
     ├─ classification == "BUG"  ─┐                               │   come straight from
     ├─ classification == "FAQ"  ─┼─ Conditional ──┐              │   FlowInput, because a
     └─ default                  ─┘                │              │   Condition node carries
                                                   ▼              │   control flow only)
                        [BugIntake]  LambdaFunction ◀─────────────┤ → [BugReportOutput]
                        [FaqAnswer]  Prompt · nova-pro   ◀────────┤ → [PlatformQuestionOutput]
                        [OtherRedirect] Prompt · nova-lite ◀──────┘ → [OtherRequestOutput]
```

Three paths, three separate Output nodes. The Condition node compares the classifier's
output with `==` against the three fixed labels, which is why the classifier prompt is
pinned to `temperature=0`, `maxTokens=5`, and "reply with one label only" — Flows
condition expressions have no `trim` or `contains`, so a stray space or period would
fall through to `default`.

### The bug-report path

```
[BugIntake] Lambda node → bug-intake-node
                            │  bedrock-agentcore:InvokeHarness
                            ▼
                          AgentCore harness  customer_support_bug_agent
                            · model amazon.nova-pro-v1:0
                            · system prompt = common.BUG_INTAKE_INSTRUCTION
                            · tool create_bug_report (inline_function)
                            │
                            │  returns a tool_use for create_bug_report
                            │  (inline_function = return of control)
                            ▼
                          bug-intake-node invokes create-bug-report-bb4af0e0
                            with messageVersion 1.0 / function / parameters
                            ▼
                          DynamoDB  BugReports-bb4af0e0
```

The agent collects the description, the steps to reproduce, and the environment, asking
once for whatever is missing, then files the ticket and repeats the returned ticket ID.

**Why this is not an Agent node.** Two constraints in this account:

1. `CreateAgent` returns `AccessDeniedException` — *"Bedrock Agents is in Maintenance
   Mode. New agent creation is not available for accounts without prior service usage."*
   Agents Classic closed to new customers on 2026-07-30 and the
   [AWS FAQ](https://docs.aws.amazon.com/bedrock/latest/userguide/agents-classic-maintenance-mode.html)
   states there is no exception process. AWS directs new agent development to
   Amazon Bedrock AgentCore, which is what the bug intake agent runs on.
2. A Flows **Agent node** only accepts an Agents Classic alias ARN — the API validates
   `agentAliasArn` against `arn:aws:bedrock:…:agent-alias/[0-9a-zA-Z]{10}/[0-9a-zA-Z]{10}`,
   and `FlowNodeType` has no AgentCore member. So an AgentCore agent cannot be referenced
   by an Agent node; it has to be reached through a Lambda node.

`deploy_agent.py` is kept in the repo unused: it builds the equivalent Agents Classic
agent (role → agent → `create-bug-report` function-schema action group → `AMAZON.UserInput`
→ prepare → alias) and runs as-is in an allowlisted account. `deploy_flow.py
--agent-alias-arn <arn>` then swaps the Lambda node for a real Agent node with no other
changes.

The step 1 Lambda (`create_bug_report.py`) is **unmodified**. `inline_function` return of
control is what makes that possible: AgentCore hands the tool call back to
`bug-intake-node`, which calls the Lambda in the action-group event format it already
expects, rather than AgentCore calling it directly with a different payload shape.

## Files

| File | |
| --- | --- |
| `common.py` | shared config, IAM helper, the bug intake instruction and tool schema |
| `configure_harness.py` | points the AgentCore harness at the instruction + `create_bug_report` tool |
| `bug_intake.py` | the bridge: flow event → InvokeHarness → step 1 Lambda → reply |
| `deploy_bug_intake.py` | deploys `bug_intake.py` as the `bug-intake-node` Lambda |
| `deploy_flow.py` | creates/updates the flow, prepares it, versions it, rolls the alias |
| `deploy_agent.py` | Agents Classic equivalent; unusable in this account (see above) |
| `invoke_flow.py` | invoke the flow, showing which Output node answered |
| `chat_bug_agent.py` | multi-turn conversation with the bug intake agent (`--demo` for a scripted two-turn run) |
| `check_routing.py` | runs `evaluation/flow-tests.json` and asserts the Output node per test |
| `generate-eval-dataset.py` | course-provided; flow → `evaluation/output_eval_dataset.jsonl` |
| `deploy-state.json` | generated; resource ids the scripts pass to each other |
| `SUBMISSION.md` | rubric checklist: which screenshot proves what, and what is not met |

### `evaluation/`

| File | |
| --- | --- |
| `flow-tests.json` | 13 test prompts across all three paths |
| `output_eval_dataset.jsonl` | dataset fed to Bedrock Evaluations |
| `output_eval_results.jsonl` | per-record judge scores and explanations, pulled back from S3 |
| `EVALUATION.md` | evaluation results and written observations |
| `README.md` | verification record: every rubric criterion, its screenshot, and what the screenshot shows |
| `screenshot/` | 18 evidence screenshots, numbered per `SUBMISSION.md` |

## Deployed resources

| | |
| --- | --- |
| Flow | `customer-support-flow` `QRTCLTQ0BT`, alias `live` `N041VVXFZG` → version 2 |
| AgentCore harness | `customer_support_bug_agent-bpj4oCYaQR` (runtime `harness_customer_support_bug_agent-fJuENY8Sx2`) |
| Bridge Lambda | `bug-intake-node` |
| Bug report tool | `create-bug-report-bb4af0e0` (stack `bug-report-tool-stack`) |
| Tickets table | `BugReports-bb4af0e0` |
| Eval bucket / role | `udacity-agentic-engineer-c1-eval-809961193920`, `bedrock-eval-role` (stack `bug-report-testing-stack`) |

Region is `us-east-1` throughout.

## Setup

`invoke_harness` / `update_harness` only exist from botocore 1.43.x, so the pinned
`requirements.txt` (boto3 1.42.54) is not enough for `configure_harness.py`,
`bug_intake.py`, or `deploy_bug_intake.py`. `generate-eval-dataset.py` works with either.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -r requirements-agentcore.txt
export AWS_PROFILE=udacity
```

`deploy_bug_intake.py` bundles its own boto3 into the Lambda zip for the same reason,
pruning botocore's service models down to the four services the function talks to
(34 MB → 9 MB unpacked, 1.6 MB zipped).

## Deploy

Order matters; each step writes what the next one reads into `deploy-state.json`.

```bash
.venv/bin/python configure_harness.py      # harness: instruction + create_bug_report tool
.venv/bin/python deploy_bug_intake.py      # role + bug-intake-node Lambda
.venv/bin/python deploy_flow.py            # flow → prepare → new version → roll alias
```

Re-run any of them after editing prompts or code. `deploy_flow.py` always prepares,
cuts a new version, and repoints the alias, so `invoke_flow.py` never serves a stale
version.

## Test

```bash
.venv/bin/python invoke_flow.py "How long does delivery take?"
.venv/bin/python check_routing.py              # all 13, asserts the Output node
.venv/bin/python check_routing.py --filter bug

# multi-turn: vague report -> agent asks once -> details -> ticket filed
.venv/bin/python chat_bug_agent.py --demo
```

## Evaluate

```bash
.venv/bin/python generate-eval-dataset.py \
  --tests-json evaluation/flow-tests.json \
  --flow-id QRTCLTQ0BT --flow-alias-id N041VVXFZG \
  --region us-east-1 \
  --out-jsonl evaluation/output_eval_dataset.jsonl

aws s3 cp evaluation/output_eval_dataset.jsonl \
  s3://udacity-agentic-engineer-c1-eval-809961193920/output_eval_dataset.jsonl

aws bedrock create-evaluation-job \
  --job-name flow-eval-run-1 \
  --role-arn arn:aws:iam::809961193920:role/bedrock-eval-role \
  --evaluation-config '{"automated":{"datasetMetricConfigs":[{"taskType":"General","dataset":{"name":"flow-eval-dataset","datasetLocation":{"s3Uri":"s3://udacity-agentic-engineer-c1-eval-809961193920/output_eval_dataset.jsonl"}},"metricNames":["Builtin.Correctness"]}],"evaluatorModelConfig":{"bedrockEvaluatorModels":[{"modelIdentifier":"amazon.nova-pro-v1:0"}]}}}' \
  --inference-config '{"models":[{"precomputedInferenceSource":{"inferenceSourceIdentifier":"my-flow-app"}}]}' \
  --output-data-config '{"s3Uri":"s3://udacity-agentic-engineer-c1-eval-809961193920/results/"}' \
  --region us-east-1
```

## Verification status

All four rubric areas were exercised against the deployed flow and captured in 18
screenshots under `evaluation/screenshot/`. [`evaluation/`](evaluation/) walks each
criterion, names the screenshot, and states what it shows.

| Area | Status | Key evidence |
| --- | --- | --- |
| Classification and routing | Met | `1-1` full graph with three separate Output nodes; `1-2b` temperature 0 / max 5 tokens; `1-3a`–`1-3b` `== "BUG"` / `== "FAQ"` / default; `check_routing.py` 13/13 |
| Bug report path | Met in substance, one caveat | `2-1a`–`2-1a2` agent + `create_bug_report` tool; `2-1c` tool call → step 1 Lambda → `ticketId`; `2-2` flow test returns a ticket ID; `2-3` follow-up then file; `2-4` those same ticket IDs in DynamoDB |
| Platform question and other paths | Met | `3-2` covered answer; `3-3` uncovered → phone; `3-4` separate `OtherRequestOutput` path |
| Testing and evaluation | Met | `4-1` Correctness **1.00** over 13 prompts; `evaluation/EVALUATION.md` |

Results and written observations: `evaluation/EVALUATION.md`.

**The caveat**: there is no Agent node and no action group, because `CreateAgent` is
blocked in this account and a Flows Agent node only accepts an Agents Classic alias ARN
(see "Why this is not an Agent node" above). The bug intake agent is a Bedrock **AgentCore**
agent reached through a Lambda node. A related consequence: a Lambda node cannot emit
`flowMultiTurnInputRequestEvent`, so inside the flow a follow-up question is returned as
the final answer and the execution ends — `chat_bug_agent.py --demo` (screenshot `2-3`)
shows the full two-turn exchange at the agent level instead. `SUBMISSION.md` records both
points and what it would take to close them.

## Model access in this account

Only the Nova family is usable. `Converse` against `global.anthropic.claude-sonnet-4-6`
and `anthropic.claude-3-haiku-20240307-v1:0` both fail on AWS Marketplace model access,
so `configure_harness.py` moves the harness off its default
`global.anthropic.claude-sonnet-4-6` onto `amazon.nova-pro-v1:0`.

Nova wraps its reasoning in `<thinking>…</thinking>` before the reply; `bug_intake.py`
strips those blocks so they never reach the customer.

## Provenance

**Course-provided, unmodified** — `cloudformation-tool.yaml`, `cloudformation-testing.yaml`,
`create_bug_report.py`, `generate-eval-dataset.py`, `online_shop_faq.md`,
`flow-test-template.json`, `requirements.txt`.

`create_bug_report.py` staying untouched is a design constraint, not an accident: it reads
the Bedrock Agent action-group event format, so the bug branch had to call it in that
format. That is why the agent's tool is an `inline_function` (return of control) and why
`bug_intake.py` builds the `messageVersion` / `function` / `parameters` payload by hand.

**Authored for this submission**

| | |
| --- | --- |
| `common.py`, `configure_harness.py`, `bug_intake.py`, `deploy_bug_intake.py`, `deploy_flow.py`, `deploy_agent.py` | deployment and runtime code |
| `invoke_flow.py`, `check_routing.py`, `chat_bug_agent.py` | test and inspection tools |
| `evaluation/flow-tests.json` | 13-prompt test suite, written from `flow-test-template.json` |
| `requirements-agentcore.txt` | botocore 1.43.x floor for the harness APIs |
| `README.md`, `SUBMISSION.md`, `evaluation/README.md`, `evaluation/EVALUATION.md` | write-ups |

The prompts themselves are part of this: the classifier, FAQ and redirect templates live in
`deploy_flow.py`, and the agent instruction plus the `create_bug_report` tool schema live in
`common.py`, so the deployed configuration has a single source in version control.

**Generated, not authored** — `deploy-state.json` (written by the deploy scripts),
`evaluation/output_eval_dataset.jsonl` (by `generate-eval-dataset.py`),
`evaluation/output_eval_results.jsonl` (downloaded from the Bedrock Evaluations output
bucket).

**Created outside these scripts** — the AgentCore harness `customer_support_bug_agent` and
its runtime were stood up manually; `configure_harness.py` then set its model, system
prompt, and tool. The screenshots in `evaluation/screenshot/` were captured from the AWS
console and terminal.

See the [repository README](../README.md#provenance-and-attribution) for external references
and the AI-assistance note.
