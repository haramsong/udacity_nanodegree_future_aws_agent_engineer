# Future AWS Agent Engineer — Udacity course projects

Project artifacts from the Udacity **Future AWS Agent Engineer** course. One directory per
project, each self-contained: deployment scripts, test suite, evaluation output, and a
verification record that maps the course rubric onto captured evidence.

Every project's **verification record** is the `evaluation/` directory — open it and the
record renders directly.

| Project                 | What it builds                                                                                                                       | Verification record                               |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------- |
| [`project1`](project1/) | Customer support Bedrock Flow — classifies a customer message and routes it to a bug-ticket agent, an FAQ answer, or a phone handoff | **[project1/evaluation →](project1/evaluation/)** |

---

## project1 — Customer support Bedrock Flow

A Bedrock Flow that classifies an incoming customer message into `BUG` / `FAQ` / `OTHER`
and routes it down one of three branches, each terminating at its own Output node.

```
[FlowInput] → [ClassifyRequest] → [RouteRequest]
                                    ├ == "BUG"  → [BugIntake]      → [BugReportOutput]
                                    ├ == "FAQ"  → [FaqAnswer]      → [PlatformQuestionOutput]
                                    └ default   → [OtherRedirect]  → [OtherRequestOutput]
```

The bug branch runs an **Amazon Bedrock AgentCore** agent that collects the description,
the steps to reproduce, and the environment, then files a ticket through the course's
step 1 Lambda into DynamoDB. The FAQ branch answers from an embedded FAQ and falls back to
the support phone line when the FAQ cannot answer. The other branch hands off to the phone
line.

|            |                                                                                                                                  |
| ---------- | -------------------------------------------------------------------------------------------------------------------------------- |
| Routing    | 13/13 test prompts reached the expected Output node                                                                              |
| Evaluation | `Builtin.Correctness` **1.00** across 13 prompts (LLM-as-a-judge, BYOI)                                                          |
| Tickets    | Records created in DynamoDB by messages processed through the flow                                                               |
| Caveat     | No Agents Classic **Agent node** — `CreateAgent` is blocked in this account, so the agent runs on AgentCore behind a Lambda node |

**Where to look**

|                                                                        |                                                                     |
| ---------------------------------------------------------------------- | ------------------------------------------------------------------- |
| [project1/evaluation/](project1/evaluation/)                           | verification record — rubric criterion → screenshot → what it shows |
| [project1/README.md](project1/README.md)                               | architecture, deploy order, commands                                |
| [project1/SUBMISSION.md](project1/SUBMISSION.md)                       | submission checklist and the unmet items (Korean)                   |
| [project1/evaluation/EVALUATION.md](project1/evaluation/EVALUATION.md) | evaluation results and written observations                         |
| [project1/evaluation/screenshot/](project1/evaluation/screenshot/)     | 18 evidence screenshots                                             |

---

## Conventions across projects

- **Region**: `us-east-1` for all Bedrock features.
- **Credentials**: `export AWS_PROFILE=udacity` before running anything.
- **Python**: per-project `.venv`, created from that project's `requirements*.txt`.
- **Deployment state**: each project writes resource ids to its own `deploy-state.json`,
  which later scripts read instead of taking ids on the command line. It holds no secrets.
- **Docs**: `README.md` is the technical write-up, `evaluation/` is the rubric evidence,
  `SUBMISSION.md` is the submission-facing checklist.

---

## Repository files

| File                       |                                                                    |
| -------------------------- | ------------------------------------------------------------------ |
| [`LICENSE.md`](LICENSE.md) | Udacity's Educational Content license                              |
| [`CODEOWNERS`](CODEOWNERS) | review ownership for the repository                                |
| [`.gitignore`](.gitignore) | virtualenvs, build artifacts, credentials, and local tool settings |

### License

The course material in this repository — starter code, templates, assignment text, and the
FAQ document — is Udacity Educational Content, © 2012–2024 Udacity, Inc., licensed under
**[CC BY-NC-ND 4.0](http://creativecommons.org/licenses/by-nc-nd/4.0)** with the
non-commercial carve-outs Udacity spells out in [`LICENSE.md`](LICENSE.md). Those carve-outs
explicitly exclude, among other things, reselling the content or derivative works, charging
for training or support that references it, and use for internal professional development
at a for-profit or non-profit organisation. The content is provided **as is**, with no
warranties. Read [`LICENSE.md`](LICENSE.md) before reusing anything here.

Project solutions are coursework submissions, kept public as a learning record rather than
as reusable material.

---

## Provenance and attribution

### What came from the course

These files ship with the course and are unmodified:

| File | |
| --- | --- |
| `project1/cloudformation-tool.yaml` | step 1 stack: DynamoDB table, bug report Lambda, IAM role |
| `project1/cloudformation-testing.yaml` | testing stack: eval S3 bucket and Bedrock Evaluations role |
| `project1/create_bug_report.py` | the bug report Lambda's source, mirrored inside the stack above |
| `project1/generate-eval-dataset.py` | flow → evaluation JSONL |
| `project1/online_shop_faq.md` | the FAQ embedded in the flow's FAQ prompt node |
| `project1/flow-test-template.json` | template the test suite was written from |
| `project1/requirements.txt` | pinned boto3 |
| `LICENSE.md`, `CODEOWNERS` | Udacity repository boilerplate |

The rubric text and the step-by-step testing instructions also come from the course; they
are quoted where the write-ups refer to them rather than reproduced in full.

### What was written for the submission

Everything else: the deployment scripts, the flow definition, the classifier / FAQ /
redirect prompts, the agent instruction, the test suite, and all the write-ups. See
[project1/README.md](project1/README.md#provenance) for the file-by-file split, including
which artifacts are generated rather than authored.

Screenshots under `project1/evaluation/screenshot/` were captured from the AWS console and
terminal by [@haramsong](https://github.com/haramsong).

### Written with AI assistance

The implementation and documentation in this repository were produced in a pair-programming
session with **Claude Code** (Claude Opus 5, Anthropic), directed and reviewed by
[@haramsong](https://github.com/haramsong). Every AWS resource was deployed and verified
against the live account, and the results quoted in the write-ups are real command and
console output, not illustrative examples.

### External references

Design decisions that depended on AWS behaviour were checked against primary sources rather
than assumed:

| Source | What it settled |
| --- | --- |
| [Bedrock Agents Classic maintenance mode](https://docs.aws.amazon.com/bedrock/latest/userguide/agents-classic-maintenance-mode.html) | `CreateAgent` and `InvokeInlineAgent` are restricted to accounts with prior usage from 2026-07-30, with **no exception process**; AgentCore is the migration path |
| [Node types for your flow](https://docs.aws.amazon.com/bedrock/latest/userguide/flows-nodes.html) | the Lambda node's input event shape, the Condition node's operators, and the Agent node's `agentAliasArn`-only configuration |
| `bedrock-agent` API model (`2023-06-05`) | `FlowNodeType` has no AgentCore member, and `agentAliasArn` is validated against `agent-alias/[0-9a-zA-Z]{10}/[0-9a-zA-Z]{10}` — so an AgentCore agent cannot be referenced by an Agent node |
| `bedrock-agentcore-control` / `bedrock-agentcore` API models | the harness tool types (`inline_function` and its return-of-control behaviour) and the `InvokeHarness` request and event-stream shapes |

The API models were read from the service definitions bundled with AWS CLI v2.34.62, which
is also what confirmed that the harness APIs need botocore 1.43.x — the reason for
`project1/requirements-agentcore.txt`.
