# Future AWS Agent Engineer — Udacity course projects

Project artifacts from the Udacity **Future AWS Agent Engineer** course. One directory per
project, each self-contained: deployment scripts, test suite, evaluation output, and a
verification record that maps the course rubric onto captured evidence.

Every project's **verification record** is the `evaluation/` directory — open it and the
record renders directly.

| Project | What it builds | Verification record |
| --- | --- | --- |
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

| | |
| --- | --- |
| Routing | 13/13 test prompts reached the expected Output node |
| Evaluation | `Builtin.Correctness` **1.00** across 13 prompts (LLM-as-a-judge, BYOI) |
| Tickets | Records created in DynamoDB by messages processed through the flow |
| Caveat | No Agents Classic **Agent node** — `CreateAgent` is blocked in this account, so the agent runs on AgentCore behind a Lambda node |

**Where to look**

| | |
| --- | --- |
| [project1/evaluation/](project1/evaluation/) | verification record — rubric criterion → screenshot → what it shows |
| [project1/README.md](project1/README.md) | architecture, deploy order, commands |
| [project1/SUBMISSION.md](project1/SUBMISSION.md) | submission checklist and the unmet items (Korean) |
| [project1/evaluation/EVALUATION.md](project1/evaluation/EVALUATION.md) | evaluation results and written observations |
| [project1/evaluation/screenshot/](project1/evaluation/screenshot/) | 18 evidence screenshots |

---

## Conventions across projects

- **Region**: `us-east-1` for all Bedrock features.
- **Credentials**: `export AWS_PROFILE=udacity` before running anything.
- **Python**: per-project `.venv`, created from that project's `requirements*.txt`.
- **Deployment state**: each project writes resource ids to its own `deploy-state.json`,
  which later scripts read instead of taking ids on the command line. It holds no secrets.
- **Docs**: `README.md` is the technical write-up, `evaluation/` is the rubric evidence,
  `SUBMISSION.md` is the submission-facing checklist.
