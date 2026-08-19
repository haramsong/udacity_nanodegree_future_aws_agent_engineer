#!/usr/bin/env python3
"""Step 2b - create the Bedrock Flow that classifies and routes customer messages.

    [FlowInput] --data--> [ClassifyRequest] --data--> [RouteRequest]
                                                        |
        BugReport  ---------------------------------> [BugIntake]      -> [BugReportOutput]
        PlatformQuestion ---------------------------> [FaqAnswer]      -> [PlatformQuestionOutput]
        default (other) ----------------------------> [OtherRedirect]  -> [OtherRequestOutput]

A Condition node only carries control flow, so each branch node also takes a
separate Data connection straight from [FlowInput] for its text input.

The BugIntake node has three possible shapes, picked in this order:

  1. --agent-alias-arn  -> an Agent node, if Agents Classic is available.
  2. --bug-lambda-arn   -> a LambdaFunction node calling bug-intake-node, which
                           runs the AgentCore bug intake agent. This is the live
                           setup: CreateAgent is blocked in this account, and a
                           Flows Agent node only accepts an Agents Classic alias
                           ARN, so AgentCore has to be reached through Lambda.
  3. neither             -> a clearly-marked placeholder Prompt node, so the rest
                           of the flow can still be deployed and tested.

Both ARNs default to whatever deploy_bug_intake.py / deploy_agent.py recorded in
deploy-state.json.
"""
import argparse
import time
from pathlib import Path

import common

FLOW_NAME = "customer-support-flow"
ALIAS_NAME = "live"
ROLE_NAME = "AmazonBedrockExecutionRoleForFlows_customersupport"

FAQ_PATH = Path(__file__).with_name("online_shop_faq.md")

# Exactly one of these three labels comes back, so the Condition node can use
# plain string equality. Keep in sync with CLASSIFIER_PROMPT.
LABELS = ("BUG", "FAQ", "OTHER")

CLASSIFIER_PROMPT = """You are a request classifier for an online shop's customer support system.
Classify the customer message into exactly one category.

BUG - the customer reports that the website, app, or checkout is broken or misbehaving:
      an error message, a crash, a button or page that does not work, a wrong total,
      a coupon field that rejects a valid code, a page that will not load.
FAQ - the customer asks a question that shop policy can answer: orders, shipping and
      delivery, returns and refunds, payments and promotions, products and stock,
      account settings, or privacy.
OTHER - anything else: greetings and small talk, partnership or sales offers, press or
      job enquiries, legal threats, complaints with no answerable question, or a request
      to speak with a person.

Rules:
- Reply with one label only: BUG, FAQ, or OTHER.
- No punctuation, no quotation marks, no explanation, no text before or after the label.
- If the message reports something broken AND asks a question, answer BUG.
- If you are unsure between FAQ and OTHER, answer OTHER.

Customer message:
{{message}}

Label:"""

FAQ_PROMPT_TEMPLATE = """You are a customer support assistant for an online shop.
Answer the customer's question using only the FAQ below.

Rules:
- If the FAQ answers the question, reply in 1-3 sentences and stay faithful to it.
- If the FAQ does not cover the question, or answering it needs the customer's own order
  details, say you cannot resolve it over chat and give them the support line:
  {phone} ({hours}).
- Never invent policies, prices, dates, tracking numbers, or order details.
- Do not ask the customer for personal data.
- Reply in the same language the customer used.

<faq>
{faq}
</faq>

Customer question:
{{{{question}}}}

Answer:"""

REDIRECT_PROMPT = f"""You are a customer support assistant for an online shop.
The message below is not a bug report and is not covered by the shop's FAQ, so it has to go
to a human agent.

Write a short, warm reply that:
1. acknowledges what the customer wrote in one clause, without promising anything,
2. explains that a member of the support team can help them directly,
3. gives the phone line {common.SUPPORT_PHONE}, available {common.SUPPORT_HOURS}.

Rules:
- Three sentences at most. No bullet points, no subject line, no signature.
- Do not answer the request yourself, do not quote policy, and do not invent other contact
  channels, hours, or ticket numbers.
- Reply in the same language the customer used.

Customer message:
{{{{message}}}}

Reply:"""

PLACEHOLDER_PROMPT = """A customer reported a problem with the online shop. The bug intake agent is
not deployed yet, so reply with exactly this text and nothing else:

[PLACEHOLDER] Bug intake agent not deployed - no ticket was created.

Customer message:
{{message}}"""


def prompt_node(name, model, template, variable, max_tokens, temperature=0.0):
    return {
        "name": name,
        "type": "Prompt",
        "configuration": {
            "prompt": {
                "sourceConfiguration": {
                    "inline": {
                        "modelId": model,
                        "templateType": "TEXT",
                        "templateConfiguration": {
                            "text": {
                                "text": template,
                                "inputVariables": [{"name": variable}],
                            }
                        },
                        "inferenceConfiguration": {
                            "text": {"temperature": temperature, "maxTokens": max_tokens}
                        },
                    }
                }
            }
        },
        "inputs": [{"name": variable, "type": "String", "expression": "$.data"}],
        "outputs": [{"name": "modelCompletion", "type": "String"}],
    }


def output_node(name):
    return {
        "name": name,
        "type": "Output",
        "configuration": {"output": {}},
        "inputs": [{"name": "document", "type": "String", "expression": "$.data"}],
    }


def data_conn(source, source_output, target, target_input):
    return {
        "type": "Data",
        "name": f"{source}To{target}",
        "source": source,
        "target": target,
        "configuration": {
            "data": {"sourceOutput": source_output, "targetInput": target_input}
        },
    }


def cond_conn(source, target, condition):
    return {
        "type": "Conditional",
        "name": f"{source}To{target}",
        "source": source,
        "target": target,
        "configuration": {"conditional": {"condition": condition}},
    }


def build_definition(agent_alias_arn=None, bug_lambda_arn=None):
    faq_text = FAQ_PATH.read_text(encoding="utf-8").strip()
    faq_prompt = FAQ_PROMPT_TEMPLATE.format(
        faq=faq_text, phone=common.SUPPORT_PHONE, hours=common.SUPPORT_HOURS
    )

    if agent_alias_arn:
        bug_node = {
            "name": "BugIntake",
            "type": "Agent",
            "configuration": {"agent": {"agentAliasArn": agent_alias_arn}},
            "inputs": [
                {"name": "agentInputText", "type": "String", "expression": "$.data"}
            ],
            "outputs": [{"name": "agentResponse", "type": "String"}],
        }
        bug_input, bug_output = "agentInputText", "agentResponse"
    elif bug_lambda_arn:
        bug_node = {
            "name": "BugIntake",
            "type": "LambdaFunction",
            "configuration": {"lambdaFunction": {"lambdaArn": bug_lambda_arn}},
            "inputs": [
                {"name": "codeHookInput", "type": "String", "expression": "$.data"}
            ],
            "outputs": [{"name": "functionResponse", "type": "String"}],
        }
        bug_input, bug_output = "codeHookInput", "functionResponse"
    else:
        bug_node = prompt_node(
            "BugIntake", common.CLASSIFIER_MODEL, PLACEHOLDER_PROMPT, "message", 60
        )
        bug_input, bug_output = "message", "modelCompletion"

    nodes = [
        {
            "name": "FlowInput",
            "type": "Input",
            "configuration": {"input": {}},
            "outputs": [{"name": "document", "type": "String"}],
        },
        prompt_node(
            "ClassifyRequest",
            common.CLASSIFIER_MODEL,
            CLASSIFIER_PROMPT,
            "message",
            max_tokens=5,
        ),
        {
            "name": "RouteRequest",
            "type": "Condition",
            "configuration": {
                "condition": {
                    "conditions": [
                        {"name": "BugReport", "expression": 'classification == "BUG"'},
                        {
                            "name": "PlatformQuestion",
                            "expression": 'classification == "FAQ"',
                        },
                        {"name": "default"},
                    ]
                }
            },
            "inputs": [
                {"name": "classification", "type": "String", "expression": "$.data"}
            ],
        },
        bug_node,
        prompt_node("FaqAnswer", common.FAQ_MODEL, faq_prompt, "question", 400),
        prompt_node(
            "OtherRedirect", common.REDIRECT_MODEL, REDIRECT_PROMPT, "message", 250
        ),
        output_node("BugReportOutput"),
        output_node("PlatformQuestionOutput"),
        output_node("OtherRequestOutput"),
    ]

    connections = [
        data_conn("FlowInput", "document", "ClassifyRequest", "message"),
        data_conn("ClassifyRequest", "modelCompletion", "RouteRequest", "classification"),
        # Branch text inputs come straight from the input node.
        data_conn("FlowInput", "document", "BugIntake", bug_input),
        data_conn("FlowInput", "document", "FaqAnswer", "question"),
        data_conn("FlowInput", "document", "OtherRedirect", "message"),
        # Routing.
        cond_conn("RouteRequest", "BugIntake", "BugReport"),
        cond_conn("RouteRequest", "FaqAnswer", "PlatformQuestion"),
        cond_conn("RouteRequest", "OtherRedirect", "default"),
        # Each path has its own output node.
        data_conn("BugIntake", bug_output, "BugReportOutput", "document"),
        data_conn("FaqAnswer", "modelCompletion", "PlatformQuestionOutput", "document"),
        data_conn("OtherRedirect", "modelCompletion", "OtherRequestOutput", "document"),
    ]
    return {"nodes": nodes, "connections": connections}


def find_flow(bedrock):
    for page in bedrock.get_paginator("list_flows").paginate():
        for f in page["flowSummaries"]:
            if f["name"] == FLOW_NAME:
                return f["id"]
    return None


def wait_flow(bedrock, flow_id, wanted, timeout=300):
    deadline = time.time() + timeout
    status = None
    while time.time() < deadline:
        flow = bedrock.get_flow(flowIdentifier=flow_id)
        status = flow["status"]
        if status in wanted:
            return flow
        if status == "Failed":
            raise RuntimeError(f"flow failed: {flow.get('validations')}")
        time.sleep(3)
    raise TimeoutError(f"flow stuck in {status}, wanted {wanted}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default=None)
    ap.add_argument(
        "--agent-alias-arn",
        default=None,
        help="Agent alias ARN for the bug-report branch (default: deploy-state.json)",
    )
    ap.add_argument(
        "--bug-lambda-arn",
        default=None,
        help="bug-intake-node Lambda ARN for the bug-report branch (default: deploy-state.json)",
    )
    ap.add_argument(
        "--placeholder-bug-branch",
        action="store_true",
        help="Force the placeholder bug branch even if an agent or Lambda is known",
    )
    args = ap.parse_args()

    sess = common.session(args.profile)
    acct = common.account_id(sess)
    iam = sess.client("iam")
    bedrock = sess.client("bedrock-agent")

    state = common.load_state()
    if args.placeholder_bug_branch:
        alias_arn = bug_lambda_arn = None
    else:
        alias_arn = args.agent_alias_arn or state.get("agentAliasArn")
        bug_lambda_arn = args.bug_lambda_arn or state.get("bugIntakeLambdaArn")

    if alias_arn:
        print(f"Bug branch: Agent node -> {alias_arn}")
    elif bug_lambda_arn:
        print(f"Bug branch: Lambda node -> {bug_lambda_arn}")
    else:
        print("Bug branch: PLACEHOLDER prompt node")

    print("IAM role...")
    model_arns = [
        f"arn:aws:bedrock:{common.REGION}::foundation-model/{m}"
        for m in sorted(
            {common.CLASSIFIER_MODEL, common.FAQ_MODEL, common.REDIRECT_MODEL}
        )
    ]
    statements = [
        {
            "Effect": "Allow",
            "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
            "Resource": model_arns,
        },
        {
            "Effect": "Allow",
            "Action": "bedrock:GetFlow",
            "Resource": f"arn:aws:bedrock:{common.REGION}:{acct}:flow/*",
        },
        {
            "Effect": "Allow",
            "Action": "bedrock:InvokeAgent",
            "Resource": f"arn:aws:bedrock:{common.REGION}:{acct}:agent-alias/*",
        },
    ]
    if bug_lambda_arn:
        statements.append(
            {
                "Effect": "Allow",
                "Action": "lambda:InvokeFunction",
                "Resource": bug_lambda_arn,
            }
        )
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
                            "aws:SourceArn": f"arn:aws:bedrock:{common.REGION}:{acct}:flow/*"
                        },
                    },
                }
            ],
        },
        policy_name="FlowExecution",
        policy={"Version": "2012-10-17", "Statement": statements},
        description="Execution role for the customer support flow",
    )
    print(f"  {role_arn}")

    definition = build_definition(alias_arn, bug_lambda_arn)

    print("Flow...")
    flow_id = find_flow(bedrock)
    if flow_id:
        bedrock.update_flow(
            flowIdentifier=flow_id,
            name=FLOW_NAME,
            description="Classifies customer messages and routes bug reports, FAQ questions, and everything else.",
            executionRoleArn=role_arn,
            definition=definition,
        )
        print(f"  updated {flow_id}")
    else:
        flow_id = common.retry(
            lambda: bedrock.create_flow(
                name=FLOW_NAME,
                description="Classifies customer messages and routes bug reports, FAQ questions, and everything else.",
                executionRoleArn=role_arn,
                definition=definition,
            )
        )["id"]
        print(f"  created {flow_id}")

    print("Preparing flow...")
    bedrock.prepare_flow(flowIdentifier=flow_id)
    flow = wait_flow(bedrock, flow_id, {"Prepared"})
    print("  Prepared")

    version = bedrock.create_flow_version(flowIdentifier=flow_id)["version"]
    print(f"  version {version}")

    aliases = {
        a["name"]: a["id"]
        for a in bedrock.list_flow_aliases(flowIdentifier=flow_id)["flowAliasSummaries"]
    }
    routing = {"routingConfiguration": [{"flowVersion": version}]}
    if ALIAS_NAME in aliases:
        alias_id = aliases[ALIAS_NAME]
        bedrock.update_flow_alias(
            flowIdentifier=flow_id, aliasIdentifier=alias_id, name=ALIAS_NAME, **routing
        )
        print(f"  alias {ALIAS_NAME} -> version {version}")
    else:
        alias_id = bedrock.create_flow_alias(
            flowIdentifier=flow_id, name=ALIAS_NAME, **routing
        )["id"]
        print(f"  created alias {ALIAS_NAME} -> version {version}")

    common.save_state(
        flowId=flow_id,
        flowVersion=version,
        flowAliasId=alias_id,
        flowArn=flow["arn"],
        flowRoleArn=role_arn,
        bugBranch="agent" if alias_arn else ("lambda" if bug_lambda_arn else "placeholder"),
    )
    print(f"\nFlow id {flow_id}, alias id {alias_id} (version {version})")
    print(f"Input node name: FlowInput   output name: document")


if __name__ == "__main__":
    main()
