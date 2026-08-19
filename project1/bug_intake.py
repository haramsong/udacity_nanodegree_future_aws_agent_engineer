"""Bridge between the Bedrock Flow and the AgentCore bug intake agent.

Deployed as the Lambda behind the flow's BugIntake node. On each call it:

  1. reads the customer message out of the flow's Lambda node event,
  2. runs the AgentCore harness (InvokeHarness) over that message,
  3. when the harness returns a create_bug_report tool call, invokes the step 1
     Lambda in its own action-group event format and feeds the result back,
  4. returns the agent's final reply as a plain string.

The harness declares create_bug_report as an inline_function tool, which means
return of control: AgentCore does not call the Lambda itself, it hands the tool
call to this code. That is what lets create_bug_report.py stay untouched.

Runs unchanged locally (for testing) and in Lambda.
"""
import json
import os
import re
import uuid

import boto3

# Nova wraps its deliberation in <thinking>...</thinking> before the actual reply.
# That is internal reasoning, not something to show a customer.
THINKING_RE = re.compile(r"<thinking>.*?</thinking>\s*", re.DOTALL | re.IGNORECASE)

REGION = os.environ.get("AWS_REGION", "us-east-1")
HARNESS_ARN = os.environ["HARNESS_ARN"]
TOOL_LAMBDA_ARN = os.environ["TOOL_LAMBDA_ARN"]
ACTION_GROUP = os.environ.get("ACTION_GROUP", "create-bug-report")
TOOL_NAME = "create_bug_report"
MAX_TURNS = int(os.environ.get("MAX_TURNS", "4"))

agentcore = boto3.client("bedrock-agentcore", region_name=REGION)
lambda_client = boto3.client("lambda", region_name=REGION)


def strip_thinking(text):
    cleaned = THINKING_RE.sub("", text or "")
    # An unterminated <thinking> block means everything after it is reasoning too.
    cleaned = re.split(r"<thinking>", cleaned, flags=re.IGNORECASE)[0]
    return cleaned.strip()


def new_session_id():
    """runtimeSessionId must be 33-100 chars of [a-zA-Z0-9][a-zA-Z0-9-_]*."""
    return f"flow-{uuid.uuid4().hex}"


def call_step1_lambda(tool_input, session_id):
    """Invoke the step 1 Lambda using the Bedrock Agent action-group contract it
    expects: messageVersion 1.0, a function name, and a parameters list."""
    parameters = [
        {"name": name, "type": "string", "value": str(value)}
        for name, value in tool_input.items()
        if isinstance(value, str) and value.strip()
    ]
    payload = {
        "messageVersion": "1.0",
        "actionGroup": ACTION_GROUP,
        "function": TOOL_NAME,
        "parameters": parameters,
        "sessionId": session_id,
    }
    resp = lambda_client.invoke(
        FunctionName=TOOL_LAMBDA_ARN,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode("utf-8"),
    )
    raw = resp["Payload"].read().decode("utf-8")
    if resp.get("FunctionError"):
        return json.dumps({"error": "tool_failed", "detail": raw[:500]})

    body = json.loads(raw)
    try:
        return body["response"]["functionResponse"]["responseBody"]["TEXT"]["body"]
    except (KeyError, TypeError):
        return json.dumps({"error": "unexpected_tool_response", "detail": raw[:500]})


def run_harness_turn(session_id, messages):
    """One InvokeHarness call. Returns the assistant content blocks, any tool
    uses, the plain text, and the stop reason."""
    resp = agentcore.invoke_harness(
        harnessArn=HARNESS_ARN,
        runtimeSessionId=session_id,
        messages=messages,
    )

    text_parts = []
    # contentBlockIndex -> partially accumulated tool use
    pending = {}
    order = []
    stop_reason = None

    for event in resp["stream"]:
        if "contentBlockStart" in event:
            start = event["contentBlockStart"]
            idx = start["contentBlockIndex"]
            tool = start.get("start", {}).get("toolUse")
            if tool:
                pending[idx] = {
                    "toolUseId": tool["toolUseId"],
                    "name": tool["name"],
                    "input": "",
                }
                order.append(idx)
        elif "contentBlockDelta" in event:
            delta = event["contentBlockDelta"]
            idx = delta["contentBlockIndex"]
            d = delta.get("delta", {})
            if "text" in d:
                text_parts.append(d["text"])
            tool_delta = d.get("toolUse")
            if tool_delta and idx in pending:
                pending[idx]["input"] += tool_delta.get("input", "")
        elif "messageStop" in event:
            stop_reason = event["messageStop"].get("stopReason")
        elif "internalServerException" in event or "runtimeClientError" in event:
            raise RuntimeError(f"harness stream error: {event}")
        elif "validationException" in event:
            raise RuntimeError(f"harness validation error: {event}")

    tool_uses = []
    for idx in order:
        item = pending[idx]
        try:
            parsed = json.loads(item["input"]) if item["input"].strip() else {}
        except json.JSONDecodeError:
            parsed = {}
        tool_uses.append(
            {"toolUseId": item["toolUseId"], "name": item["name"], "input": parsed}
        )

    text = strip_thinking("".join(text_parts))
    content = []
    if text:
        content.append({"text": text})
    for tu in tool_uses:
        content.append({"toolUse": tu})

    return {
        "content": content,
        "toolUses": tool_uses,
        "text": text,
        "stopReason": stop_reason,
    }


def run_agent(messages, session_id, on_tool=None):
    """Drive the harness until it stops asking for tools.

    `messages` is the running conversation and is appended to in place, so a
    caller can keep it around and add the customer's next turn (that is how
    chat_bug_agent.py holds a multi-turn conversation together). Returns the
    agent's reply text.
    """
    last_text = ""

    for _ in range(MAX_TURNS):
        turn = run_harness_turn(session_id, messages)
        last_text = turn["text"] or last_text

        if not turn["toolUses"]:
            messages.append({"role": "assistant", "content": turn["content"]})
            return turn["text"] or last_text

        messages.append({"role": "assistant", "content": turn["content"]})
        results = []
        for tu in turn["toolUses"]:
            if tu["name"] != TOOL_NAME:
                body = json.dumps({"error": "unknown_tool", "name": tu["name"]})
                status = "error"
            else:
                body = call_step1_lambda(tu["input"], session_id)
                status = "error" if '"error"' in body else "success"
            print(f"TOOL {tu['name']} input={json.dumps(tu['input'], ensure_ascii=False)} -> {body}")
            if on_tool:
                on_tool(tu, body)
            results.append(
                {
                    "toolResult": {
                        "toolUseId": tu["toolUseId"],
                        "content": [{"text": body}],
                        "status": status,
                    }
                }
            )
        messages.append({"role": "user", "content": results})

    return last_text or (
        "Sorry, I could not file that bug report. Please call "
        f"{os.environ.get('SUPPORT_PHONE', '+1-800-555-0199')} and the team will help."
    )


def handle_message(message, session_id=None):
    """Run the agent over one customer message and return its reply."""
    return run_agent(
        [{"role": "user", "content": [{"text": message}]}],
        session_id or new_session_id(),
    )


def message_from_flow_event(event):
    """Pull the customer message out of a Bedrock Flows Lambda node event."""
    inputs = {i["name"]: i.get("value") for i in event.get("node", {}).get("inputs", [])}
    for key in ("codeHookInput", "message", "document"):
        value = inputs.get(key)
        if isinstance(value, str) and value.strip():
            return value
    # Fall back to any string input, then to a direct {"message": ...} payload.
    for value in inputs.values():
        if isinstance(value, str) and value.strip():
            return value
    if isinstance(event.get("message"), str):
        return event["message"]
    raise ValueError(f"no customer message in event: {json.dumps(event)[:500]}")


def lambda_handler(event, _context):
    print("EVENT:", json.dumps(event, default=str)[:2000])
    message = message_from_flow_event(event)
    reply = handle_message(message)
    print("REPLY:", reply)
    return reply
