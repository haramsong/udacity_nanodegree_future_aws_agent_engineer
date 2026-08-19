# 제출 체크리스트 — 스크린샷 위치와 미충족 항목

리전은 전부 **us-east-1**. 콘솔은 Amazon Bedrock → 왼쪽 사이드바 기준입니다.

| 리소스 | 값 |
| --- | --- |
| Flow | `customer-support-flow` / `QRTCLTQ0BT` |
| Flow alias | `live` / `N041VVXFZG` → version 2 |
| AgentCore harness | `customer_support_bug_agent-bpj4oCYaQR` |
| Bridge Lambda | `bug-intake-node` |
| Bug tool Lambda | `create-bug-report-bb4af0e0` |
| DynamoDB | `BugReports-bb4af0e0` (현재 5건) |
| Eval job | `flow-eval-run-1` (Completed) |

---

## 1. Classification and Routing — 충족

### 1-1. 전체 flow 다이어그램
`Builder tools → Flows → customer-support-flow → Edit in flow builder`
캔버스에서 zoom-to-fit. 9개 노드가 다 보이게:
`FlowInput → ClassifyRequest → RouteRequest`, 그리고 3갈래
`BugIntake / FaqAnswer / OtherRedirect` 와 각각의
`BugReportOutput / PlatformQuestionOutput / OtherRequestOutput`.
→ **경로 3개가 각각 별도 Output 노드로 끝난다**는 게 이 한 장으로 증명됩니다.

### 1-2. 분류기 프롬프트 설정
캔버스에서 **`ClassifyRequest`** 노드 클릭 → 오른쪽 패널.
같이 보이게 할 것:
- 모델 `Nova Lite`
- 프롬프트 본문 (BUG / FAQ / OTHER 정의 + "Reply with one label only" 규칙)
- Inference configuration의 **Temperature `0`**, **Max tokens `5`**

프롬프트 박스를 스크롤해서 라벨 정의 3줄과 Rules 블록이 함께 잡히도록 하세요. 이게
"consistent, unambiguous output" 근거입니다.

### 1-3. Condition 노드 표현식
**`RouteRequest`** 노드 클릭. 보여야 할 것:
- 입력 `classification` (String)
- 조건 3개: `classification == "BUG"` / `classification == "FAQ"` / `default`

---

## 2. Bug Report Path — **부분 충족** (아래 "미충족" 절 참고)

### 2-1. 에이전트 + 도구 설정 ← Agent 노드 스크린샷 대체
Agents Classic Agent가 없어서 **Agent 노드 + action group 화면은 존재하지 않습니다.**
대체 증거 두 장:

**(a) AgentCore 에이전트 설정** — 콘솔에서 AgentCore 항목을 찾을 수 있으면
harness `customer_support_bug_agent`의 system prompt와 tools(`create_bug_report`)가 보이는 화면.
콘솔 메뉴 위치가 확실치 않으면 CLI 출력을 그대로 찍는 게 확실합니다:

```bash
aws bedrock-agentcore-control get-harness \
  --harness-id customer_support_bug_agent-bpj4oCYaQR --region us-east-1
```
→ `model.bedrockModelConfig.modelId`, `systemPrompt`(설명·재현절차·환경 수집 지시),
`tools[0]`의 `inline_function` + `create_bug_report` + `inputSchema`의
`description`/`stepsToReproduce`/`environment`가 한 화면에 나옵니다.

**(b) flow의 BugIntake 노드** — 캔버스에서 `BugIntake` 클릭 →
Lambda function `bug-intake-node`가 보이는 패널. 이게 flow → 에이전트 연결 지점입니다.

**(c) 도구가 실제로 Step 1 Lambda를 호출한 로그** (권장, 강한 증거):
```bash
aws logs tail /aws/lambda/bug-intake-node --since 1h --format short \
  --region us-east-1 | grep TOOL
```
→ `TOOL create_bug_report input={...} -> {"ticketId": "...", "status": "OPEN"}`
에이전트가 도구를 호출하고 티켓이 만들어진 순간이 한 줄로 남습니다.

### 2-2. 버그 리포트 생성 (정보 충분 → 즉시 티켓)
flow builder 오른쪽 **Test** 패널에 입력:
```
I add a hoodie to the cart, go to checkout, fill in my address and click Pay,
and the page just reloads with an empty cart. I'm on Chrome 141 on Windows 11.
```
→ 응답에 티켓 ID(UUID)가 포함됩니다. 그 화면 캡처.

### 2-3. 후속 질문 (follow-up) ← **flow Test 패널로는 반쪽만 나옵니다**
Test 패널에 입력:
```
Your checkout page is broken.
```
→ 재현 절차 + 환경을 묻는 응답 1턴이 나옵니다. **다만 여기서 답을 이어서 넣어도 대화가
계속되지 않습니다** (Lambda 노드는 flow 실행을 멈춰 세울 수 없음 — 미충족 절 2 참고).

되묻고 → 답변받고 → 티켓 생성까지 이어지는 걸 보여주려면 터미널 출력을 찍으세요:
```bash
AWS_PROFILE=udacity .venv/bin/python chat_bug_agent.py --demo
```
```
customer> Your checkout page is broken.
agent   > Please provide the steps you took before encountering the problem and
          the browser or device you were using.
customer> I add a hoodie to the cart, click Checkout, fill in my address and press Pay.
          The spinner runs forever and nothing happens. I'm on Firefox 133 on Ubuntu 24.04.
TOOL create_bug_report input={"environment": "Firefox 133 on Ubuntu 24.04.", ...}
     -> {"ticketId": "f63bc2b4-...", "status": "OPEN"}
agent   > The ticket ID is f63bc2b4-29bf-4387-979f-18934497dfcd. The team will follow up.
```
한 장에 후속질문·답변·도구호출·티켓ID가 다 들어갑니다.

### 2-4. DynamoDB 테이블
`DynamoDB → Tables → BugReports-bb4af0e0 → Explore table items → Run`
→ 5건. `ticketId` / `description` / `stepsToReproduce` / `environment` / `status=OPEN` /
`createdAt` 열이 보이게. 위 2-2에서 받은 티켓 ID가 목록에 있으면 "flow가 만든 항목"이라는
연결이 명확해집니다.

---

## 3. Platform Question and Other Request Paths — 충족

### 3-1. FAQ Prompt 노드 템플릿 (FAQ 본문 임베드)
**`FaqAnswer`** 노드 클릭 → 프롬프트 템플릿. `<faq>` 태그와 그 안의 실제 FAQ 문단
(예: "Orders", "Shipping & Delivery"...)이 보이도록 스크롤해서 캡처.
규칙 부분("If the FAQ does not cover the question ... give them the support line")도
같이 잡히면 3-3 근거까지 한 장에 들어갑니다.

### 3-2. FAQ가 커버하는 질문
Test 패널:
```
How long does delivery take, and how do I track my order?
```
→ FAQ 내용대로 답변 (checkout/확인 메일 표시, 1–2 영업일 처리, tracking 링크, My Orders).

### 3-3. FAQ가 커버하지 못하는 질문 → 전화 안내
```
Where exactly is my parcel right now? Order 88123, it should have arrived yesterday.
```
→ 채팅으로 조회 불가 + `+1-800-555-0199` (Monday-Friday, excluding holidays) 안내.

### 3-4. Other 요청 → 전화 안내 (별도 경로)
```
Hi, I run a logistics startup and I'd like to talk to someone about a partnership.
```
→ 전화 안내. 응답 화면과 함께, 1-1 다이어그램에서 이 경로가 `OtherRequestOutput`으로
따로 끝나는 게 보이면 "separate path" 요건이 채워집니다.

---

## 4. Testing and Evaluation — 충족

- `evaluation/flow-tests.json` — 13개 (bug 4, faq 6, other 3). 파일 그대로 제출.
- `evaluation/output_eval_dataset.jsonl` — 13줄, flow 호출 13건 성공, `[FLOW_ERROR]` 0건. 파일 제출.
- S3 업로드 + eval job 생성 완료.
- Correctness **1.000** (13/13). 요건 "close to 1" 충족.

### 4-1. Evaluation 결과 페이지
`Amazon Bedrock → Evaluations → flow-eval-run-1` 클릭 → status **Completed**와
`Builtin.Correctness` 점수가 보이는 화면. 가능하면 per-record 목록까지 스크롤해서 한 장 더.

### 4-2. 서면 관찰
`evaluation/EVALUATION.md` 제출. 각 루브릭 항목과 스크린샷의 대응은
[`evaluation/`](evaluation/)의 README에 영문으로 정리돼 있습니다. 관찰 내용: 이진 메트릭의 천장 효과, judge가 놓친 실제 결함
(`faq-02`의 과도한 전화 리다이렉트), eval이 DynamoDB 티켓 내용을 못 본다는 점,
Nova가 Nova를 채점하는 자기평가 편향, 다음 개선안 5가지.

---

# 미충족 / 설명이 필요한 부분

## 1. Bedrock **Agent 노드**와 action group 화면이 없습니다 (핵심)

루브릭이 요구하는 `Screenshot of the Agent node configuration showing the action group`은
이 계정에서 만들 수 없습니다. 이유 두 개:

1. `CreateAgent`가 403 —
   *"Bedrock Agents is in Maintenance Mode. New agent creation is not available for accounts
   without prior service usage."* Agents Classic은 2026-07-30부터 신규 고객에게 닫혔고,
   [AWS FAQ](https://docs.aws.amazon.com/bedrock/latest/userguide/agents-classic-maintenance-mode.html)에
   **예외 신청 절차가 없다**고 명시돼 있습니다. AWS는 AgentCore로 가라고 안내합니다.
2. Flows의 Agent 노드는 Agents Classic alias ARN만 받습니다 — API가 `agentAliasArn`을
   `arn:aws:bedrock:…:agent-alias/[0-9a-zA-Z]{10}/[0-9a-zA-Z]{10}` 정규식으로 검증하고,
   `FlowNodeType` enum에 AgentCore 항목이 없습니다. 즉 AgentCore 에이전트는 Agent 노드로
   참조 자체가 불가능하고, Lambda 노드를 거쳐야 합니다.

**루브릭 항목별 실제 상태:**

| 요건 | 상태 |
| --- | --- |
| The bug report path includes a Bedrock agent | △ Bedrock **AgentCore** 에이전트 (Agents Classic 아님) |
| The agent is configured to invoke the Lambda tool to persist the ticket | ○ 에이전트의 `create_bug_report` 도구 호출이 Step 1 Lambda를 **원본 계약 그대로** 실행 |
| The agent collects description / steps / environment | ○ |
| A record is created in the BugReports table via the flow | ○ |

제출 시 위 두 제약과 대체 구조를 명시하시는 게 안전합니다. `README.md`에 그대로 적어뒀습니다.

**정석으로 맞추고 싶다면**: 지난 12개월 내 Bedrock Agents 사용 이력이 있는 계정(=allowlist)이
필요합니다. 확보되면 그 계정에 `cloudformation-tool.yaml` 재배포 후

```bash
.venv/bin/python deploy_agent.py                       # role → agent → action group → prepare → alias
.venv/bin/python deploy_flow.py --agent-alias-arn <arn> # Lambda 노드를 Agent 노드로 교체
```

두 줄이면 Agent 노드 구성으로 바뀝니다. `deploy_agent.py`는 이미 그 목적으로 작성돼 있습니다
(function-schema action group + `AMAZON.UserInput` 포함).

## 2. flow 안에서 후속질문 대화가 이어지지 않습니다

Lambda 노드는 `flowMultiTurnInputRequestEvent`를 낼 수 없어서, 에이전트가 되물으면 그 질문이
**flow의 최종 응답으로 나가고 실행이 끝납니다.** Agents Classic Agent 노드였다면 flow 실행이
일시정지하고 답을 받아 이어갔습니다.

- 에이전트 자체는 멀티턴이 되고, `chat_bug_agent.py --demo`로 증명됩니다 (2-3 참고).
- `generate-eval-dataset.py`도 테스트당 1턴만 보내고 첫 출력 이벤트에서 끊기 때문에
  (`generate-eval-dataset.py:43-53`) eval 결과에는 영향이 없습니다.
- `evaluation/flow-tests.json`의 `bug-01`/`bug-04`는 "되묻는 질문"을 기대 응답으로,
  `bug-02`/`bug-03`은 1턴에 티켓이 나오도록 작성돼 있습니다.

## 3. 참고 사항 (감점 요소는 아님)

- **모델**: 이 계정은 Nova 계열만 접근 가능합니다. Claude Sonnet 4.6과 Claude 3 Haiku 모두
  AWS Marketplace 모델 접근 거부가 납니다. 그래서 harness 기본 모델
  `global.anthropic.claude-sonnet-4-6` → `amazon.nova-pro-v1:0`으로 변경했습니다.
- **boto3**: `InvokeHarness`/`UpdateHarness`가 botocore 1.43.x부터라서 `requirements-agentcore.txt`를
  따로 뒀습니다. 원본 `requirements.txt`는 수정하지 않았고, `generate-eval-dataset.py`는
  둘 중 어느 버전으로도 동작합니다.
- **DynamoDB 항목 수**: 테이블에 5건 있습니다. 그 이전 항목들은 중간에 삭제됐습니다
  (제 스크립트는 삭제하지 않습니다). 남은 5건 모두 flow 또는 에이전트를 거쳐 생성된 것입니다.
