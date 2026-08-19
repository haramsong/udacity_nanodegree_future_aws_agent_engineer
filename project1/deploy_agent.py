#!/usr/bin/env python3
"""Step 2a - create the Bedrock Agent that files bug reports.

The Lambda from step 1 speaks the Bedrock Agent action-group protocol
(messageVersion 1.0 + a `parameters` list, see create_bug_report.py), so the
bug-report path in the flow has to go through an Agent node, not a Lambda node.

Idempotent: re-run after editing the instruction or the schema and it will
update, re-prepare, and roll the alias to a fresh version.
"""
import argparse
import time

import common

AGENT_NAME = "customer-support-bug-agent"
ALIAS_NAME = "live"
ROLE_NAME = "AmazonBedrockExecutionRoleForAgents_bugreport"
ACTION_GROUP = "create-bug-report"

INSTRUCTION = f"""You are the bug intake assistant for an online shop's customer support team.
Your only job is to turn a customer's bug report into a ticket with the create_bug_report tool.

Work through these steps:
1. Read the customer's message and write down what is broken. That is the bug description.
2. Check whether the message already states (a) the steps to reproduce the problem and
   (b) the customer's environment, meaning browser, operating system, or device.
3. If either one is missing, ask the customer for the missing items in ONE short message and
   then wait for their reply. Ask only once; never send a second round of questions.
4. As soon as you have a description, call create_bug_report. Pass stepsToReproduce and
   environment only when the customer actually stated them. Never invent details, and never
   guess a browser, OS, or device.
5. After the tool returns, reply with one or two sentences that repeat the ticket ID exactly as
   returned and tell the customer the team will follow up.

Rules:
- Never promise a fix date, a refund, a discount, or a delivery date.
- Do not answer general shop questions about orders, shipping, returns, or payments; another
  part of the system handles those.
- Reply in the customer's language and keep every reply under four sentences.
- The support phone line is {common.SUPPORT_PHONE} ({common.SUPPORT_HOURS}); mention it only if
  the customer explicitly asks to talk to a person."""

FUNCTION_SCHEMA = {
    "functions": [
        {
            "name": "create_bug_report",
            "description": (
                "Create a bug report ticket in the engineering tracker. Call this once you know "
                "what is broken. Returns the ticket ID."
            ),
            "parameters": {
                "description": {
                    "type": "string",
                    "required": True,
                    "description": (
                        "What is broken, in one or two sentences, written from the customer's "
                        "report."
                    ),
                },
                "stepsToReproduce": {
                    "type": "string",
                    "required": False,
                    "description": (
                        "The steps the customer took before hitting the problem, as stated by "
                        "the customer. Omit if the customer did not say."
                    ),
                },
                "environment": {
                    "type": "string",
                    "required": False,
                    "description": (
                        "The customer's browser, operating system, and/or device, as stated by "
                        "the customer. Omit if the customer did not say."
                    ),
                },
            },
        }
    ]
}


def find_agent(bedrock):
    for page in bedrock.get_paginator("list_agents").paginate():
        for a in page["agentSummaries"]:
            if a["agentName"] == AGENT_NAME:
                return a["agentId"]
    return None


def wait_for_status(bedrock, agent_id, wanted, timeout=300):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = bedrock.get_agent(agentId=agent_id)["agent"]["agentStatus"]
        if status in wanted:
            return status
        if status == "FAILED":
            reasons = bedrock.get_agent(agentId=agent_id)["agent"].get("failureReasons")
            raise RuntimeError(f"agent FAILED: {reasons}")
        time.sleep(5)
    raise TimeoutError(f"agent stuck in {status}, wanted {wanted}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default=None)
    ap.add_argument(
        "--lambda-arn",
        default=None,
        help="create-bug-report Lambda ARN (default: look it up by name prefix)",
    )
    args = ap.parse_args()

    sess = common.session(args.profile)
    acct = common.account_id(sess)
    iam = sess.client("iam")
    bedrock = sess.client("bedrock-agent")

    lambda_arn = args.lambda_arn
    if not lambda_arn:
        fns = [
            f
            for f in sess.client("lambda").list_functions()["Functions"]
            if f["FunctionName"].startswith("create-bug-report")
        ]
        if len(fns) != 1:
            raise SystemExit(f"expected exactly one create-bug-report function, found {len(fns)}")
        lambda_arn = fns[0]["FunctionArn"]
    print(f"Lambda: {lambda_arn}")

    print("IAM role...")
    role_arn = common.ensure_role(
        iam,
        ROLE_NAME,
        trust={
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"Service": "bedrock.amazonaws.com"},
                    "Action": "sts:AssumeRole",
                    "Condition": {
                        "StringEquals": {"aws:SourceAccount": acct},
                        "ArnLike": {
                            "aws:SourceArn": f"arn:aws:bedrock:{common.REGION}:{acct}:agent/*"
                        },
                    },
                }
            ],
        },
        policy_name="InvokeModelAndTool",
        policy={
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                    "Resource": [
                        f"arn:aws:bedrock:{common.REGION}::foundation-model/{common.AGENT_MODEL}"
                    ],
                },
                {
                    "Effect": "Allow",
                    "Action": "lambda:InvokeFunction",
                    "Resource": lambda_arn,
                },
            ],
        },
        description="Execution role for the customer-support bug report agent",
    )
    print(f"  {role_arn}")

    print("Agent...")
    agent_id = find_agent(bedrock)
    kwargs = dict(
        agentName=AGENT_NAME,
        agentResourceRoleArn=role_arn,
        foundationModel=common.AGENT_MODEL,
        instruction=INSTRUCTION,
        description="Collects bug details from customers and files a ticket via Lambda.",
        idleSessionTTLInSeconds=600,
    )
    if agent_id:
        wait_for_status(bedrock, agent_id, {"NOT_PREPARED", "PREPARED", "VERSIONED"})
        bedrock.update_agent(agentId=agent_id, **kwargs)
        print(f"  updated {agent_id}")
    else:
        agent_id = common.retry(lambda: bedrock.create_agent(**kwargs))["agent"]["agentId"]
        print(f"  created {agent_id}")
    wait_for_status(bedrock, agent_id, {"NOT_PREPARED", "PREPARED", "VERSIONED"})

    print("Action groups...")
    existing = {
        g["actionGroupName"]: g["actionGroupId"]
        for g in bedrock.list_agent_action_groups(agentId=agent_id, agentVersion="DRAFT")[
            "actionGroupSummaries"
        ]
    }

    tool_kwargs = dict(
        agentId=agent_id,
        agentVersion="DRAFT",
        actionGroupName=ACTION_GROUP,
        description="Files a bug report ticket in DynamoDB.",
        actionGroupExecutor={"lambda": lambda_arn},
        functionSchema=FUNCTION_SCHEMA,
        actionGroupState="ENABLED",
    )
    if ACTION_GROUP in existing:
        bedrock.update_agent_action_group(
            actionGroupId=existing[ACTION_GROUP], **tool_kwargs
        )
        print(f"  updated {ACTION_GROUP}")
    else:
        common.retry(lambda: bedrock.create_agent_action_group(**tool_kwargs))
        print(f"  created {ACTION_GROUP}")

    # Without AMAZON.UserInput the agent cannot ask the customer for the missing
    # steps-to-reproduce / environment: it would have to guess or give up.
    user_input_kwargs = dict(
        agentId=agent_id,
        agentVersion="DRAFT",
        actionGroupName="UserInputAction",
        parentActionGroupSignature="AMAZON.UserInput",
        actionGroupState="ENABLED",
    )
    if "UserInputAction" in existing:
        bedrock.update_agent_action_group(
            actionGroupId=existing["UserInputAction"], **user_input_kwargs
        )
        print("  updated UserInputAction")
    else:
        bedrock.create_agent_action_group(**user_input_kwargs)
        print("  created UserInputAction (lets the agent ask follow-up questions)")

    print("Preparing agent...")
    bedrock.prepare_agent(agentId=agent_id)
    wait_for_status(bedrock, agent_id, {"PREPARED"})
    print("  PREPARED")

    print("Alias...")
    aliases = {
        a["agentAliasName"]: a["agentAliasId"]
        for a in bedrock.list_agent_aliases(agentId=agent_id)["agentAliasSummaries"]
    }
    if ALIAS_NAME in aliases:
        alias_id = aliases[ALIAS_NAME]
        # No routingConfiguration => Bedrock snapshots DRAFT into a new version.
        bedrock.update_agent_alias(
            agentId=agent_id, agentAliasId=alias_id, agentAliasName=ALIAS_NAME
        )
        print(f"  rolled {ALIAS_NAME} to a new version")
    else:
        alias_id = bedrock.create_agent_alias(
            agentId=agent_id, agentAliasName=ALIAS_NAME
        )["agentAlias"]["agentAliasId"]
        print(f"  created alias {ALIAS_NAME}")

    for _ in range(60):
        alias = bedrock.get_agent_alias(agentId=agent_id, agentAliasId=alias_id)["agentAlias"]
        status = alias["agentAliasStatus"]
        if status == "PREPARED":
            break
        if status == "FAILED":
            raise RuntimeError(f"alias failed: {alias.get('failureReasons')}")
        time.sleep(5)
    else:
        raise TimeoutError(f"alias stuck in {status}")

    alias_arn = f"arn:aws:bedrock:{common.REGION}:{acct}:agent-alias/{agent_id}/{alias_id}"
    common.save_state(
        accountId=acct,
        lambdaArn=lambda_arn,
        agentId=agent_id,
        agentAliasId=alias_id,
        agentAliasArn=alias_arn,
        agentRoleArn=role_arn,
    )
    print(f"\nAgent alias ARN: {alias_arn}")
    print(f"State written to {common.STATE_FILE}")


if __name__ == "__main__":
    main()
