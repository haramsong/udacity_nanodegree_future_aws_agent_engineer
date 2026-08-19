# Testing and Evaluation

## What was run

| | |
| --- | --- |
| Flow | `customer-support-flow` / `QRTCLTQ0BT` |
| Flow alias | `live` / `N041VVXFZG` → version 2 |
| Input node | `FlowInput` (output `document`) |
| Test suite | `flow-tests.json` — 13 prompts (6 FAQ, 4 bug, 3 other) |
| Dataset | `output_eval_dataset.jsonl` — 13 lines, 13 flow calls succeeded, 0 `[FLOW_ERROR]` |
| Eval job | `flow-eval-run-1` / `arn:aws:bedrock:us-east-1:809961193920:evaluation-job/8du5x70yzzki` |
| Metric | `Builtin.Correctness`, LLM-as-a-judge (BYOI) |
| Judge model | `amazon.nova-pro-v1:0` |
| Status | `Completed` (2026-08-19 02:37 → 02:44 UTC, ~7 min) |
| Raw results | `output_eval_results.jsonl` (copied from `s3://udacity-agentic-engineer-c1-eval-809961193920/results/flow-eval-run-1/8du5x70yzzki/…`) |

Commands used are in `README.md`.

## Two checks, not one

`Builtin.Correctness` judges the **text of the answer**. It never sees which branch
produced that text, so a misrouted message that happens to read plausibly still
scores 1.0. Routing is therefore checked separately by `check_routing.py`, which
asserts the Output node reached for each test id:

```
$ python check_routing.py
ok   faq-01-delivery-and-tracking           -> PlatformQuestionOutput
...
ok   other-03-small-talk                    -> OtherRequestOutput

0 routing failure(s)
```

13/13 reached the expected Output node — `PlatformQuestionOutput`, `BugReportOutput`,
`OtherRequestOutput` respectively. The classifier returned only `BUG`, `FAQ`, or `OTHER`
on every prompt; no `default` fallback was triggered by a malformed label.

## Scores

| Category | n | Mean `Builtin.Correctness` |
| --- | --- | --- |
| faq | 6 | 1.000 |
| bug | 4 | 1.000 |
| other | 3 | 1.000 |
| **all** | **13** | **1.000** |

Score distribution: `{1.0: 13}`. Every record passed.

## Observations

**1. A perfect score here says less than it looks like.**
`Builtin.Correctness` came back binary — every record was exactly `1.0`, never a
fractional value. With 13 records and no partial credit there is no gradient to
improve against: the metric can only tell me nothing is outright wrong. The
judge's own explanations are more informative than the number, and two of them
flag omissions while still awarding a pass (see 3 and 4 below). I would not read
13/13 as "the app is finished".

**2. The judge honoured the negative constraints in the reference responses.**
I wrote each `expected` as a behavioural description including explicit "must not"
clauses ("does not invent specific dates or carriers", "does not promise a refund",
"does not invent an email address, form, or contact person"). The explanations show
the judge checked those clauses, not just topical overlap — e.g. for `faq-01`:
*"does not invent specific dates or carriers, nor does it redirect to the phone
line, which is consistent with the ground truth answer."* Writing references as
intent-plus-prohibitions worked better than writing an ideal answer verbatim,
because the flow's phrasing varies run to run while the constraints do not.

**3. Real defect the metric did not catch: `faq-02` over-redirects to the phone line.**
The response was:

> You can return most items within 30 days of delivery as long as they're unused and in
> original packaging. If you need assistance with starting a return, please contact our
> support team at +1-800-555-0199 (Monday-Friday, excluding holidays).

But FAQ Q12 *does* cover starting a return — "contact support with your order number
and the items you want to return". The FAQ prompt's escape hatch ("if the FAQ does not
cover it, give the phone line") fired on a question the FAQ answers, so the customer
got a phone number instead of the actual next step. The judge scored it 1.0 and
reasoned that the extra phone number *"does not contradict the essential points"* —
a lenient reading that hides a genuine regression in helpfulness. Compare `faq-06`,
where redirecting **is** correct because the question needs the customer's own order
data. The fix is in the FAQ prompt, not the flow: make the redirect condition narrower,
e.g. redirect only when answering requires order-specific data or the topic is absent
from the FAQ, and prefer the FAQ's own instruction when one exists.

**4. The eval cannot see the DynamoDB ticket, only the confirmation sentence.**
For `bug-03` (Korean) the flow replied `티켓 ID 801fb50c-… 가 생성되었습니다.` and the
judge noted *"the candidate response does not explicitly mention the promo code SAVE10
or the environment (iPhone Safari)"* — then passed it anyway. Whether the ticket
**content** is any good is invisible to this metric. I verified it out of band: the
table holds 8 tickets and the fields are populated from what the customer actually
said, with no invented values, e.g.

```
801fb50c-… | iPhone Safari              | An error occurs when applying a promotion code on iPhone Safari.
5dd033d6-… | Chrome 141 on Windows 11   | After adding a hoodie to the cart, filling in the address, and clicking…
```

A stronger suite would add a metric or an assertion over the written row, not just
the reply text.

**5. The bug path's ask-once behaviour works, and asks only for what is missing.**
`bug-01` ("Your checkout page is broken.") returned a single request for both steps
and environment. `bug-04` ("The order summary shows $58 but the confirmation email
charged me $85. Something in your app is swapping the numbers.") asked only for steps —
"your app" was accepted as the environment, so it did not re-ask for it. That is the
behaviour the instruction asks for, and it took an explicit prompt change to get:
the first version re-asked for the environment even when the customer had written
"아이폰 사파리", because the model wanted a version number. The instruction now states
that a named browser/OS/device is sufficient and that version numbers must never be
requested.

**6. Self-evaluation bias, one judge, one run.**
The FAQ and redirect nodes run on `amazon.nova-pro-v1:0` and the judge is also
`amazon.nova-pro-v1:0`. A model grading its own family's output is not an independent
check. This account only has model access to the Nova family (Claude and Claude 3
Haiku both return `AccessDeniedException` about AWS Marketplace subscriptions), so a
cross-family judge was not available here. There is also a single run per prompt and
a single judge, so nothing in these numbers estimates variance — the classifier
labels are produced at `temperature=0` with `maxTokens=5`, which makes routing stable,
but the answer text does vary between runs (the `faq-02` phone-line drift in 3 above
appeared in the eval run and not in the earlier routing run).

## What I would change next

1. Narrow the FAQ prompt's redirect condition (observation 3). This is the one concrete
   defect found.
2. Add negative-routing tests: messages engineered to sit on a boundary — a return
   question that also mentions a broken button, a partnership offer that mentions an
   error page — to see whether "if it reports something broken AND asks a question,
   answer BUG" holds under pressure.
3. Add an assertion on the DynamoDB row for bug tests, so ticket content is graded and
   not just the confirmation sentence (observation 4).
4. Re-run with a second judge model once a non-Nova model is available in the account,
   and run each prompt more than once, to separate real regressions from run-to-run
   variance (observation 6).
5. Expand beyond 13 prompts. With a binary metric, a small suite saturates at 100%
   immediately; more prompts, especially adversarial ones, is the only way to make
   the score move.

## Known limitation of the bug path under test

The bug-report branch is a Lambda node (see `README.md` for why: `CreateAgent` is
blocked in this account and a Flows Agent node only accepts an Agents Classic alias
ARN). A Lambda node cannot emit `flowMultiTurnInputRequestEvent`, so when the agent
asks for the missing steps or environment, the flow **returns that question and ends**
rather than pausing the execution for a reply. Each test prompt is therefore a single
turn, which matches how `generate-eval-dataset.py` drives the flow anyway — it sends
one prompt per test and breaks out of the response stream on the first output event.
`bug-01` and `bug-04` are written to expect the question as the final answer, and
`bug-02`/`bug-03` supply enough detail in one message for the ticket to be filed
immediately.
