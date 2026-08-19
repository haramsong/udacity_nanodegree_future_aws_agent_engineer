# project1 — Verification record

Every rubric criterion, the screenshot that evidences it, and what the screenshot
actually shows. Screenshot filenames follow the numbering in [`../SUBMISSION.md`](../SUBMISSION.md).

Related: [project write-up](../README.md) · [evaluation observations](EVALUATION.md) ·
[screenshots](screenshot/) · [all projects](../../)

| Resource | Value |
| --- | --- |
| Region | `us-east-1` |
| Flow | `customer-support-flow` / `QRTCLTQ0BT` |
| Flow alias | `live` / `N041VVXFZG` → version 2 |
| Bug intake agent | AgentCore harness `customer_support_bug_agent-bpj4oCYaQR`, version 5 |
| Bridge Lambda | `bug-intake-node` |
| Bug report tool | `create-bug-report-bb4af0e0` (step 1) |
| Tickets table | `BugReports-bb4af0e0` |
| Evaluation job | `flow-eval-run-1` (`8du5x70yzzki`), Completed |

---

## 1. Classification and Routing — met

### `screenshot/1-1.png` — full flow diagram

The whole graph in one frame: `Flow input` (output `document`, String) fans out to
`ClassifyRequest`, `BugIntake`, `FaqAnswer` and `OtherRedirect`, with
`ClassifyRequest → RouteRequest` carrying the label.

Three branches, each terminating at its **own** Output node:

| Branch node | Output node |
| --- | --- |
| `BugIntake` (Lambda function) | `BugReportOutput` |
| `FaqAnswer` (Prompt) | `PlatformQuestionOutput` |
| `OtherRedirect` (Prompt) | `OtherRequestOutput` |

The dashed purple lines are the conditional connections out of `RouteRequest`; the solid
grey lines are data connections. Visible in the same frame: the branch nodes take their
text input directly from `Flow input`, because a Condition node routes control flow only
and does not carry the payload.

### `screenshot/1-2a.png` and `screenshot/1-2b.png` — classifier configuration

`1-2a` shows the `ClassifyRequest` node: **Define in node**, model **Nova Lite 1.0**, and
the start of the prompt with the `BUG` category definition.

`1-2b` shows the tail of the same template — `Customer message: {{message}}` — and the
inference configuration that makes the output routable:

- **Maximum output tokens: 5**
- **Temperature: 0**
- Top P: 0.9

Five tokens and zero temperature is what keeps the answer to a single bare label, which
matters because Flows condition expressions have no `trim` or `contains`: a trailing
period or a leading space would miss both `==` comparisons and fall through to `default`.

### `screenshot/1-3a.png` and `screenshot/1-3b.png` — Condition node expressions

The `RouteRequest` configuration panel:

- Input `classification`, type **String**, expression `$.data`
- Condition `BugReport` → `classification == "BUG"` → go to node `BugIntake`
- Condition `PlatformQuestion` → `classification == "FAQ"` → go to node `FaqAnswer`
- **If all conditions are false** → go to node `OtherRedirect`

`1-3a` captures the input definition plus the first condition; `1-3b` scrolls down through
both named conditions and the default branch. Exact string equality against the three
labels the classifier is constrained to emit.

### Routing verified programmatically as well

`check_routing.py` asserts the Output node reached for all 13 prompts in
`flow-tests.json`, independently of answer quality:

```
$ python check_routing.py
ok   faq-01-delivery-and-tracking           -> PlatformQuestionOutput
…
ok   other-03-small-talk                    -> OtherRequestOutput

0 routing failure(s)
```

13/13 reached the expected node. No prompt produced a malformed label that fell through
to `default` unintentionally.

---

## 2. Bug Report Path — met in substance; see the caveat

### `screenshot/2-1a.png` and `screenshot/2-1a2.png` — the agent and its tool

The AgentCore console, `Harness → customer_support_bug_agent → Version 5`:

- Status **Ready**, IAM role `AmazonBedrockAgentCoreHarnessDefaultServiceRole-t7cgm`
- **Model** `amazon.nova-pro-v1:0`, API format Converse API, temperature 0.2, max tokens 1024
- **System prompt** in full. The visible text carries the three collection requirements:
  *"Check whether the message already states (a) the steps to reproduce the problem and
  (b) the customer's environment"*, that a named browser/OS/device is sufficient and a
  version number must never be requested, that a missing item is asked for *"in ONE short
  message and then stop"*, and that `create_bug_report` is called once description plus
  both details are in hand — with *"Never invent details, and never guess a browser, OS,
  or device."*
- `2-1a2` shows **Tools (1)**: `create_bug_report`, type **Custom function**. Memory (0).

This is the substitute for the rubric's "Agent node configuration showing the action
group" screenshot. There is no Agent node and no action group in this account — see the
caveat at the end of this section.

### `screenshot/2-1b.png` — how the flow reaches the agent

`Flow builder: customer-support-flow`, `BugIntake` node selected: a **Lambda function**
node pointing at `bug-intake-node`, version `$LATEST`, input `codeHookInput` (String,
`$.data`). This is the flow-to-agent bridge.

### `screenshot/2-1c.png` — the agent invoking the step 1 Lambda

CloudWatch `/aws/lambda/bug-intake-node` log events, showing the full chain in order:

1. `EVENT: {"node": {"name": "BugIntake", "inputs": [{"name": "codeHookInput", … "value": "I add a hoodie to the cart, go to checkout, fill in my address and click Pay, an…`
2. `TOOL create_bug_report input=` with all three fields populated from what the customer
   actually wrote:
   ```json
   {
     "environment": "Chrome 141 on Windows 11",
     "description": "After adding a hoodie to the cart and proceeding to checkout, filling in the address and clicking Pay results in the page reloading with an empty cart.",
     "stepsToReproduce": "Add a hoodie to the cart, go to checkout, fill in the address, and click Pay."
   }
   ```
3. `-> {"ticketId": "58db61cb-ba33-433f-8341-223cfc85bd77", "status": "OPEN"}` — the step 1
   Lambda's response
4. `REPLY: The ticket ID is 58db61cb-ba33-433f-8341-223cfc85bd77. The team will follow up.`

A second request lower in the same log shows the Korean path: `TOOL create_bug_report
input={"environment": "iPhone Safari", "description": "iPhone Safari에서 프로모션 코드 SAVE10을
입력하고 적용을 누르면 코드가 유효하지 않다는 오류가 계속 나옵니다.", …}` followed by
`REPLY: 티켓 ID bb2bde88-9ccf-4732-90fd-a83d38333130가 생성되었습니다.`

This is the strongest single piece of evidence for "the agent is configured to invoke the
Lambda tool to persist the ticket": the tool call, its arguments, the step 1 Lambda's
`ticketId` response, and the customer-facing reply are all in one frame.

### `screenshot/2-2.png` — bug report created through the flow

The flow builder **Test flow** panel with trace enabled. Input:

> I add a hoodie to the cart, go to checkout, fill in my address and click Pay, and the
> page just reloads with an empty cart. I'm on Chrome 141 on Windows 11.

Response, labelled with the Output node that produced it:

> **BugReportOutput** — The ticket ID is `8839bbf4-466c-421c-96b5-5742c29de9c0`. The team
> will follow up.

The trace pane on the right confirms the execution path and that every node completed:

| Node | Time | Status |
| --- | --- | --- |
| `ClassifyRequest` (Prompt node) | 0.344 sec | Complete |
| `RouteRequest` (Condition node) | 0.001 sec | Complete |
| `BugIntake` (LambdaFunction node) | 8.670 secs | Complete |
| `BugReportOutput` (Output node) | 0.001 sec | Complete |

The expanded input trace for `BugReportOutput` shows the value arriving from
`"nodeName": "BugIntake"`, `"outputFieldName": "functionResponse"` — the ticket
confirmation came from the bug branch, not from anywhere else.

### `screenshot/2-3.png` — follow-up questions, then the ticket

`chat_bug_agent.py --demo` against the same harness, two turns:

```
customer> Your checkout page is broken.
agent   > Please provide the steps you took before encountering the problem and the
          browser or device you were using.

customer> I add a hoodie to the cart, click Checkout, fill in my address and press Pay.
          The spinner runs forever and nothing happens. I'm on Firefox 133 on Ubuntu 24.04.
TOOL create_bug_report input={"environment": "Firefox 133 on Ubuntu 24.04.",
     "description": "The checkout page spinner runs indefinitely after clicking Pay.",
     "stepsToReproduce": "Add a hoodie to the cart, click Checkout, fill in the address,
     and press Pay."} -> {"ticketId": "271c56cb-a411-4b68-9375-64caf0b61540", "status": "OPEN"}
agent   > The ticket ID is 271c56cb-a411-4b68-9375-64caf0b61540 and the team will follow up.

tickets created: ['{"ticketId": "271c56cb-a411-4b68-9375-64caf0b61540", "status": "OPEN"}']
```

Turn 1 is a bare complaint with no steps and no environment: the agent asks for **both**,
in one message, and files nothing. Turn 2 supplies them and the ticket is created
immediately, with no second round of questions. That is the collect-then-file behaviour
the rubric asks for.

This is shown at the agent level rather than in the flow Test panel on purpose: a Flows
Lambda node cannot emit `flowMultiTurnInputRequestEvent`, so inside the flow the
follow-up question is returned as the final answer and the execution ends. See the caveat.

### `screenshot/2-4.png` — the DynamoDB records

`DynamoDB → Tables → BugReports-bb4af0e0 → Scan → Run`, scan at 2026-08-19 13:32:30:
**Completed · Items returned: 7 · Items scanned: 7**.

The two visible rows tie the earlier screenshots to persisted state:

| `ticketId` | `createdAt` | `description` |
| --- | --- | --- |
| `271c56cb-a411-4b68-9375-64caf0b61540` | 2026-08-19T04:31:48.916223+00:00 | The checkout page spinner runs indefinitely after clicking Pay. |
| `8839bbf4-466c-421c-96b5-5742c29de9c0` | 2026-08-19T04:29:37.979740+00:00 | After adding a hoodie to the cart, filling in the address, and clicking Pay, the pa… |

`8839bbf4-…` is the ticket the **flow test in 2-2 returned**, and `271c56cb-…` is the one
from the **two-turn conversation in 2-3**. So the table demonstrably contains records
created by a bug report processed through the flow, not by a direct Lambda invocation.

### Caveat: this is an AgentCore agent behind a Lambda node, not an Agent node

Two hard constraints in this account:

1. `CreateAgent` returns `AccessDeniedException` — *"Bedrock Agents is in Maintenance
   Mode. New agent creation is not available for accounts without prior service usage."*
   Agents Classic closed to new customers on 2026-07-30, and the
   [AWS FAQ](https://docs.aws.amazon.com/bedrock/latest/userguide/agents-classic-maintenance-mode.html)
   states there is no exception process. AWS directs new agent development to AgentCore.
2. A Flows **Agent node** accepts only an Agents Classic alias ARN. The API validates
   `agentAliasArn` against `arn:aws:bedrock:…:agent-alias/[0-9a-zA-Z]{10}/[0-9a-zA-Z]{10}`,
   and `FlowNodeType` has no AgentCore member, so an AgentCore agent cannot be referenced
   by an Agent node at all.

Consequences for this criterion:

| Requirement | Status |
| --- | --- |
| The bug report path includes a Bedrock agent | Partial — a Bedrock **AgentCore** agent, not Agents Classic |
| The agent is configured to invoke the Lambda tool to persist the ticket | Met — `2-1c` |
| The agent collects description, steps to reproduce, and environment | Met — `2-1a`, `2-3` |
| A record is created in the BugReports table via the flow | Met — `2-2` + `2-4` |

`create_bug_report.py` is **unmodified**. The tool is declared on the harness as an
`inline_function`, which is return of control: AgentCore hands the tool call back to
`bug-intake-node`, which invokes the step 1 Lambda in the action-group event format it
already expects (`messageVersion` 1.0, `function`, `parameters`). `deploy_agent.py` builds
the equivalent Agents Classic agent and runs as-is in an allowlisted account;
`deploy_flow.py --agent-alias-arn <arn>` then replaces the Lambda node with a real Agent
node and nothing else changes.

---

## 3. Platform Question and Other Request Paths — met

### `screenshot/3-1.png` — FAQ Prompt node

`FaqAnswer` node: **Define in node**, model **Nova Pro 1.0**, and the Message template
showing the routing rules that separate a covered question from an uncovered one:

> Rules:
> - If the FAQ answers the question, reply in 1-3 sentences and stay faithful to it.
> - If the FAQ does not cover the question, or answering it needs the customer's own order
>   details, say you cannot resolve it over…

The `<faq>` block with the embedded `online_shop_faq.md` content sits further down the
same Message box (see "One screenshot worth retaking" below).

### `screenshot/3-2.png` — covered question

Input: *"How long does delivery take, and how do I track my order?"*

> **PlatformQuestionOutput** — Estimated delivery times are shown at checkout and in your
> shipping confirmation email. Processing typically takes 1–2 business days before
> dispatch. Once your order ships, we'll email a tracking link. If you have an account,
> you can also find tracking under My Orders.

Faithful to FAQ Q8 and Q9, with no invented dates or carriers, and no phone redirect.

### `screenshot/3-3.png` — uncovered question redirects to the phone line

Input: *"Where exactly is my parcel right now? Order 88123, it should have arrived yesterday."*

> **PlatformQuestionOutput** — I'm sorry, but I can't provide specific tracking details
> over chat. Please call our support line at +1-800-555-0199 (Monday-Friday, excluding
> holidays) for assistance with your order.

Answering would need the customer's own order data, so the escape hatch fires. No parcel
location, tracking number, or delivery date is invented.

### `screenshot/3-4.png` — separate path for other requests

Input: *"Hi, I run a logistics startup and I'd like to talk to someone about a partnership."*

> **OtherRequestOutput** — Hello! We appreciate your interest in partnering with us. A
> member of our support team would be happy to assist you with this. You can reach us at
> +1-800-555-0199, available Monday-Friday, excluding holidays.

The Output node label is the point: this answer came from `OtherRequestOutput`, a
different terminal node from the FAQ path's `PlatformQuestionOutput` in 3-2 and 3-3.

---

## 4. Testing and Evaluation — met

| Requirement | Status |
| --- | --- |
| ≥1 test per path in `flow-tests.json` | Met — 13 tests: 4 bug, 6 platform question, 3 other |
| `generate-eval-dataset.py` produces JSONL | Met — `output_eval_dataset.jsonl`, 13 lines, 13 successful flow calls, 0 `[FLOW_ERROR]` |
| JSONL uploaded to S3 and evaluation job created | Met — `s3://udacity-agentic-engineer-c1-eval-809961193920/output_eval_dataset.jsonl`, job `flow-eval-run-1` |
| Correctness score close to 1 | Met — **1.00** |
| Written observation | Met — `EVALUATION.md` |

### `screenshot/4-1.png` — evaluation results

`Evaluations → Model evaluation report → flow-eval-run-1`:

- **Quality metrics → Correctness: 1.00**
- Generation metrics breakdown, Correctness histogram: a single bar at score `1`,
  **Total: 13 prompts**, **Avg score: 1.000**

Every one of the 13 records scored 1.0; the distribution has no mass anywhere below 1.

Written observations are in `EVALUATION.md`. In short: the metric came back binary, so
1.00 means "nothing is outright wrong" rather than "nothing can be improved". The judge's
own explanations are more useful than the number, and they surfaced one real defect the
score hid — `faq-02` pushed the phone line for a question the FAQ does answer (Q12), which
the judge waved through as "does not contradict the essential points". `EVALUATION.md`
also records that the metric cannot see the DynamoDB row (only the confirmation sentence),
and that the judge is `amazon.nova-pro-v1:0` grading output from Nova nodes, which is not
an independent check — this account has model access to the Nova family only.

---

## One screenshot worth retaking

`screenshot/3-1.png` shows the `FaqAnswer` Message box scrolled to the **Rules** section,
so the rubric's "showing embedded FAQ content" is not literally visible. Scrolling the
same Message box up to the `<faq>` block — far enough to catch a couple of real FAQ
entries, e.g. the `Orders` or `Shipping & Delivery` headings — would close that gap. The
rules text currently visible is still useful, since it evidences the covered/uncovered
split behind 3-2 and 3-3, so an additional frame is better than a replacement.

Optional, lower value: `1-2a` shows the `BUG` category definition but not the
*"Reply with one label only … no punctuation, no quotation marks"* rule, which is the
sentence that makes the `==` comparisons in `1-3a`/`1-3b` safe. One more frame of the
middle of that template would make the classifier argument self-contained.
