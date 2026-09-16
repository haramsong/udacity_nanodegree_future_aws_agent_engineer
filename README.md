# Future AWS Agent Engineer — Udacity course projects

Project artifacts from the Udacity **Future AWS Agent Engineer** course. One directory per
project, each self-contained: deployment scripts, test suite, evaluation output, and a
verification record that maps the course rubric onto captured evidence.

Every project's **verification record** is the `evaluation/` directory — open it and the
record renders directly.

| Project                 | What it builds                                                                                                                       | Verification record                               |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------- |
| [`project1`](project1/) | Customer support Bedrock Flow — classifies a customer message and routes it to a bug-ticket agent, an FAQ answer, or a phone handoff | **[project1/evaluation →](project1/evaluation/)** |
| [`project2`](project2/) | Customer support AI agent on Amazon Bedrock AgentCore — RAG, Gateway tools over MCP, cross-session memory, a code sandbox, and a browser | **[project2/evaluation →](project2/evaluation/)** |

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

## project2 — Customer support AI agent on AgentCore

A production-shaped support agent for a fictional store, deployed to the Amazon Bedrock
AgentCore Runtime. It answers policy and product questions from a knowledge base, looks up
live orders and processes refunds through the AgentCore Gateway, remembers customers across
sessions, computes loyalty discounts in a sandbox, and reads live web pages.

```
            agentcore invoke
                   │
    ┌──────────────▼───────────────┐
    │   AgentCore Runtime          │  main.py, @app.entrypoint, Nova 2 Lite
    └───┬───────┬───────┬──────┬───┘
        │       │       │      └─► AgentCore Browser ──► live web
        │       │       └────────► Code Interpreter (loyalty maths)
        │       └────────────────► AgentCore Memory (facts + preferences)
        ├────────────────────────► Knowledge Base ◄─ OpenSearch Serverless ◄─ S3
        └────────────────────────► Gateway (MCP) ├─ order-tracker    → API Gateway → Lambda
                                                 └─ refund-processor → Lambda (direct)
```

|            |                                                                                                              |
| ---------- | ------------------------------------------------------------------------------------------------------------ |
| Tests      | 6/6 functional scenarios pass against the **deployed** runtime                                               |
| Gateway    | 6 MCP tools across two target types — 3 from an API Gateway REST stage, 3 from a direct Lambda target        |
| Infra      | Two CloudFormation stacks cover everything except the runtime, which `agentcore deploy` builds and ships     |
| Monitoring | `ERROR` metric filter and an alarm at more than 5 errors in 5 minutes                                        |
| Caveat     | CodeBuild is blocked by an Organizations SCP, so the ARM64 image is built locally with `--local-build`       |

Three failures worth recording, because each one only appeared in the cloud:

- **The Gateway lost its tools after the first request.** `strands_tools.browser` calls
  `nest_asyncio.apply()`, which swaps in the pure-Python `asyncio.Task`; on Python 3.14
  `asyncio.current_task()` then returns `None` and every later MCP connection dies inside
  anyio. The patch is process-wide, so a warm container carries it into the next request.
- **The generated execution role knew nothing about the project's own resources.** RAG,
  memory and browsing all failed on the deployed agent while working locally, because local
  runs use the developer's credentials.
- **`uv pip install .` aborted the Docker build**, because without an explicit build backend
  setuptools treats `infra/`, `lambda/` and `starter/` as packages.

**Where to look**

|                                                                        |                                                                          |
| ---------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| [project2/evaluation/](project2/evaluation/)                           | verification record — rubric criterion → screenshot → what it shows       |
| [project2/README.md](project2/README.md)                               | architecture, deploy order, implementation notes, teardown                |
| [project2/main.py](project2/main.py)                                   | the agent — all eight starter TODO sections implemented                   |
| [project2/infra/](project2/infra/)                                     | CloudFormation templates and the deploy / permissions / destroy scripts   |
| [project2/tests/transcripts/](project2/tests/transcripts/)             | full transcripts of every test suite run                                  |
| [project2/evaluation/REFLECTION.md](project2/evaluation/REFLECTION.md) | written reflection                                                        |

---

## Conventions across projects

- **Region**: `us-east-1` for all Bedrock features.
- **Credentials**: `export AWS_PROFILE=udacity` before running anything.
- **Python**: per-project `.venv`. project1 installs from `requirements*.txt`; project2 is
  managed by [uv](https://docs.astral.sh/uv/) from its `pyproject.toml` (Python 3.14).
- **Deployment state**: project1 writes resource ids to `deploy-state.json`; project2 reads
  them back from CloudFormation stack outputs. Neither holds secrets.
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
