"""Shared helpers for the customer-support flow deployment scripts."""
import json
import os
import time
from pathlib import Path

import boto3

REGION = "us-east-1"
STATE_FILE = Path(__file__).with_name("deploy-state.json")

# Models. Nova Pro handles the tool-calling agent and the grounded FAQ answers;
# Nova Lite is enough for the one-word classifier and the fixed redirect.
AGENT_MODEL = "amazon.nova-pro-v1:0"
FAQ_MODEL = "amazon.nova-pro-v1:0"
CLASSIFIER_MODEL = "amazon.nova-lite-v1:0"
REDIRECT_MODEL = "amazon.nova-lite-v1:0"

SUPPORT_PHONE = "+1-800-555-0199"
SUPPORT_HOURS = "Monday-Friday, excluding holidays"

# The bug intake agent's instruction. Used by the AgentCore harness
# (configure_harness.py) and by deploy_agent.py if Agents Classic is ever
# available again, so the two stay in step.
BUG_INTAKE_INSTRUCTION = f"""You are the bug intake assistant for an online shop's customer support team.
Your only job is to turn a customer's bug report into a ticket with the create_bug_report tool.

Work through these steps:
1. Read the customer's message and write down what is broken. That is the bug description.
2. Check whether the message already states (a) the steps to reproduce the problem and
   (b) the customer's environment. Any browser, operating system, or device the customer names
   counts as the environment, even without a version number: "iPhone Safari", "Chrome on Mac",
   and "your Android app" are all sufficient. Never ask for a version number.
   A message that says what the customer did before the problem appeared - clicked Pay, applied
   a code, opened a page - already counts as steps to reproduce.
3. If one of them is genuinely absent, ask the customer for it in ONE short message and then
   stop. Ask only once, ask only for what is missing, and do not call the tool in that turn.
4. When you have a description plus both of those details, call create_bug_report. Pass
   stepsToReproduce and environment only when the customer actually stated them. Never invent
   details, and never guess a browser, OS, or device.
5. After the tool returns, reply with one or two sentences that repeat the ticket ID exactly as
   returned and tell the customer the team will follow up.

Rules:
- Never promise a fix date, a refund, a discount, or a delivery date.
- Do not answer general shop questions about orders, shipping, returns, or payments; another
  part of the system handles those.
- Reply in the customer's language and keep every reply under four sentences.
- The support phone line is {SUPPORT_PHONE} ({SUPPORT_HOURS}); mention it only if the customer
  explicitly asks to talk to a person."""

# JSON Schema for the create_bug_report tool. Mirrors the parameters the step 1
# Lambda reads out of the action-group event.
BUG_TOOL_DESCRIPTION = (
    "Create a bug report ticket in the engineering tracker. Call this once you know what is "
    "broken and the customer has given the steps to reproduce and their environment. "
    "Returns the ticket ID."
)
BUG_TOOL_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "description": {
            "type": "string",
            "description": (
                "What is broken, in one or two sentences, written from the customer's report."
            ),
        },
        "stepsToReproduce": {
            "type": "string",
            "description": (
                "The steps the customer took before hitting the problem, as stated by the "
                "customer. Omit if the customer did not say."
            ),
        },
        "environment": {
            "type": "string",
            "description": (
                "The customer's browser, operating system, and/or device, as stated by the "
                "customer. Omit if the customer did not say."
            ),
        },
    },
    "required": ["description"],
}


def session(profile=None):
    profile = profile or os.environ.get("AWS_PROFILE") or "udacity"
    return boto3.Session(profile_name=profile, region_name=REGION)


def account_id(sess):
    return sess.client("sts").get_caller_identity()["Account"]


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(**kwargs):
    state = load_state()
    state.update(kwargs)
    STATE_FILE.write_text(json.dumps(state, indent=2) + "\n")
    return state


def ensure_role(iam, role_name, trust, policy_name, policy, description=""):
    """Create or update an IAM role with a single inline policy. Idempotent."""
    try:
        arn = iam.get_role(RoleName=role_name)["Role"]["Arn"]
        iam.update_assume_role_policy(
            RoleName=role_name, PolicyDocument=json.dumps(trust)
        )
        print(f"  role {role_name} already exists")
    except iam.exceptions.NoSuchEntityException:
        arn = iam.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(trust),
            Description=description,
        )["Role"]["Arn"]
        print(f"  created role {role_name}")

    iam.put_role_policy(
        RoleName=role_name,
        PolicyName=policy_name,
        PolicyDocument=json.dumps(policy),
    )
    return arn


def retry(fn, attempts=12, delay=5, on=("ValidationException", "AccessDeniedException")):
    """Retry around IAM eventual consistency (a fresh role isn't assumable yet)."""
    last = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - botocore raises dynamic classes
            code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
            msg = str(exc)
            if code not in on and not any(o in msg for o in on):
                raise
            last = exc
            print(f"  waiting for IAM propagation ({i + 1}/{attempts}): {code}")
            time.sleep(delay)
    raise last
