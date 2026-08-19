#!/usr/bin/env python3
"""Step 2a - configure the AgentCore harness that acts as the bug intake agent.

Bedrock Agents Classic is in maintenance mode and CreateAgent is blocked in this
account, so the bug intake agent lives in Amazon Bedrock AgentCore instead - the
migration path AWS points at. This script takes the harness that already exists
in the account and gives it:

  * the bug intake system prompt (common.BUG_INTAKE_INSTRUCTION)
  * a create_bug_report tool declared as an inline_function

inline_function means return of control: the harness hands the tool call back to
whoever invoked it, so the caller runs the step 1 Lambda with its own
action-group event format and feeds the result back. That keeps
create_bug_report.py completely unmodified. bug_intake_node.py is that caller.

Idempotent: safe to re-run after editing the instruction or the schema.
"""
import argparse
import time

import common

HARNESS_NAME = "customer_support_bug_agent"
TOOL_NAME = "create_bug_report"


def find_harness(control, name):
    for h in control.list_harnesses()["harnesses"]:
        if h["harnessName"] == name:
            return h
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default=None)
    ap.add_argument("--harness-name", default=HARNESS_NAME)
    args = ap.parse_args()

    sess = common.session(args.profile)
    acct = common.account_id(sess)
    control = sess.client("bedrock-agentcore-control")

    harness = find_harness(control, args.harness_name)
    if not harness:
        names = [h["harnessName"] for h in control.list_harnesses()["harnesses"]]
        raise SystemExit(
            f"no harness named {args.harness_name!r}. Existing harnesses: {names or 'none'}\n"
            "Create one first, e.g. with the AgentCore CLI:\n"
            "  agentcore create --name customer-support-bug-agent"
        )

    harness_id = harness["harnessId"]
    before = control.get_harness(harnessId=harness_id)["harness"]
    print(f"Harness {harness_id}")
    print(f"  model  : {before.get('model', {}).get('bedrockModelConfig', {}).get('modelId')}")
    print(f"  tools  : {[t.get('name') for t in before.get('tools', [])] or 'none'}")

    control.update_harness(
        harnessId=harness_id,
        # The harness ships pointing at global.anthropic.claude-sonnet-4-6, which this
        # account has no model access for (Converse returns AccessDeniedException about
        # AWS Marketplace). Only the Nova family is enabled here.
        model={
            "bedrockModelConfig": {
                "modelId": common.AGENT_MODEL,
                "apiFormat": "converse_stream",
                "temperature": 0.2,
                "maxTokens": 1024,
            }
        },
        systemPrompt=[{"text": common.BUG_INTAKE_INSTRUCTION}],
        tools=[
            {
                "type": "inline_function",
                "name": TOOL_NAME,
                "config": {
                    "inlineFunction": {
                        "description": common.BUG_TOOL_DESCRIPTION,
                        "inputSchema": common.BUG_TOOL_INPUT_SCHEMA,
                    }
                },
            }
        ],
        allowedTools=["*"],
        # One tool call plus the wrap-up reply is all this agent should ever need.
        maxIterations=6,
        timeoutSeconds=120,
    )

    for _ in range(60):
        h = control.get_harness(harnessId=harness_id)["harness"]
        if h["status"] == "READY":
            break
        if h["status"] in ("CREATE_FAILED", "UPDATE_FAILED", "FAILED"):
            raise RuntimeError(f"harness {h['status']}: {h}")
        time.sleep(3)
    else:
        raise TimeoutError(f"harness stuck in {h['status']}")

    print("  updated ->")
    print(f"  tools  : {[t.get('name') for t in h.get('tools', [])]}")
    print(f"  prompt : {h['systemPrompt'][0]['text'].splitlines()[0]}...")

    common.save_state(
        accountId=acct,
        harnessId=harness_id,
        harnessArn=h["arn"],
        harnessName=h["harnessName"],
        harnessModelId=h.get("model", {}).get("bedrockModelConfig", {}).get("modelId"),
    )
    print(f"\nHarness ARN: {h['arn']}")


if __name__ == "__main__":
    main()
