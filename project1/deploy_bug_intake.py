#!/usr/bin/env python3
"""Step 2b - deploy bug_intake.py as the Lambda behind the flow's BugIntake node.

The flow reaches the bug intake agent through a Lambda node, because a Bedrock
Flows Agent node only accepts an Agents Classic alias ARN (the API validates
arn:aws:bedrock:...:agent-alias/<10>/<10>) and there is no AgentCore node type.
This Lambda is the bridge: flow -> InvokeHarness -> step 1 Lambda -> flow.

The Lambda ships its own boto3, because InvokeHarness/UpdateHarness only landed
in botocore 1.43.x and the managed runtime lags behind. botocore's service data
is pruned to the four services this function actually talks to, which takes the
bundle from 34 MB to about 9 MB.

Idempotent: re-run to push code or configuration changes.
"""
import argparse
import io
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import common

FUNCTION_NAME = "bug-intake-node"
ROLE_NAME = "bug-intake-node-role"
HANDLER = "bug_intake.lambda_handler"
RUNTIME = "python3.12"
SOURCE = Path(__file__).with_name("bug_intake.py")

# botocore service models to keep in the bundle.
KEEP_SERVICES = {"lambda", "sts", "bedrock-agentcore", "bedrock-agentcore-control"}
PIP_PACKAGES = [
    "boto3>=1.43.74",
    "botocore>=1.43.74",
    "jmespath",
    "python-dateutil",
    "six",
    "urllib3",
    "s3transfer",
]


def build_zip():
    """pip install the SDK, prune unused service models, add bug_intake.py."""
    build_dir = Path(tempfile.mkdtemp(prefix="bug-intake-build-"))
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q", "--no-deps", "-t", str(build_dir)]
            + PIP_PACKAGES,
            check=True,
        )

        data_dir = build_dir / "botocore" / "data"
        pruned = 0
        for entry in data_dir.iterdir():
            if entry.is_dir() and entry.name not in KEEP_SERVICES:
                shutil.rmtree(entry)
                pruned += 1
        print(f"  pruned {pruned} unused botocore service models")

        shutil.copy2(SOURCE, build_dir / SOURCE.name)

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(build_dir.rglob("*")):
                if path.is_file() and "__pycache__" not in path.parts:
                    zf.write(path, path.relative_to(build_dir))
        data = buf.getvalue()
        print(f"  package {len(data) / 1e6:.1f} MB zipped")
        return data
    finally:
        shutil.rmtree(build_dir, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default=None)
    args = ap.parse_args()

    sess = common.session(args.profile)
    acct = common.account_id(sess)
    iam = sess.client("iam")
    lam = sess.client("lambda")

    state = common.load_state()
    harness_arn = state.get("harnessArn")
    tool_lambda = state.get("lambdaArn")
    if not tool_lambda:
        fns = [
            f["FunctionArn"]
            for f in lam.list_functions()["Functions"]
            if f["FunctionName"].startswith("create-bug-report")
        ]
        if len(fns) != 1:
            raise SystemExit(f"expected one create-bug-report function, found {len(fns)}")
        tool_lambda = fns[0]
    if not harness_arn:
        raise SystemExit("no harnessArn in deploy-state.json - run configure_harness.py first")

    print(f"Harness    : {harness_arn}")
    print(f"Tool Lambda: {tool_lambda}")

    print("IAM role...")
    role_arn = common.ensure_role(
        iam,
        ROLE_NAME,
        trust={
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"Service": "lambda.amazonaws.com"},
                    "Action": "sts:AssumeRole",
                }
            ],
        },
        policy_name="InvokeHarnessAndTool",
        policy={
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": [
                        "logs:CreateLogGroup",
                        "logs:CreateLogStream",
                        "logs:PutLogEvents",
                    ],
                    "Resource": f"arn:aws:logs:{common.REGION}:{acct}:*",
                },
                {
                    # InvokeHarness authorizes as bedrock-agentcore:InvokeAgentRuntime
                    # against the harness resource, and the harness runs on a runtime.
                    "Effect": "Allow",
                    "Action": [
                        "bedrock-agentcore:InvokeHarness",
                        "bedrock-agentcore:InvokeAgentRuntime",
                    ],
                    "Resource": [
                        harness_arn,
                        f"{harness_arn}/*",
                        f"arn:aws:bedrock-agentcore:{common.REGION}:{acct}:runtime/*",
                    ],
                },
                {
                    "Effect": "Allow",
                    "Action": "lambda:InvokeFunction",
                    "Resource": tool_lambda,
                },
            ],
        },
        description="Lets the flow's bug intake node run the AgentCore harness and the bug report tool",
    )
    print(f"  {role_arn}")

    print("Building package...")
    package = build_zip()

    environment = {
        "Variables": {
            "HARNESS_ARN": harness_arn,
            "TOOL_LAMBDA_ARN": tool_lambda,
            "ACTION_GROUP": "create-bug-report",
            "MAX_TURNS": "4",
            "SUPPORT_PHONE": common.SUPPORT_PHONE,
        }
    }

    print("Lambda...")
    exists = True
    try:
        lam.get_function(FunctionName=FUNCTION_NAME)
    except lam.exceptions.ResourceNotFoundException:
        exists = False

    if exists:
        lam.update_function_code(FunctionName=FUNCTION_NAME, ZipFile=package)
        waiter = lam.get_waiter("function_updated_v2")
        waiter.wait(FunctionName=FUNCTION_NAME)
        lam.update_function_configuration(
            FunctionName=FUNCTION_NAME,
            Role=role_arn,
            Handler=HANDLER,
            Runtime=RUNTIME,
            Timeout=180,
            MemorySize=512,
            Environment=environment,
        )
        waiter.wait(FunctionName=FUNCTION_NAME)
        arn = lam.get_function(FunctionName=FUNCTION_NAME)["Configuration"]["FunctionArn"]
        print(f"  updated {arn}")
    else:
        arn = common.retry(
            lambda: lam.create_function(
                FunctionName=FUNCTION_NAME,
                Runtime=RUNTIME,
                Role=role_arn,
                Handler=HANDLER,
                Code={"ZipFile": package},
                Timeout=180,
                MemorySize=512,
                Environment=environment,
                Description="Bridges the Bedrock Flow to the AgentCore bug intake agent.",
            ),
            on=("InvalidParameterValueException", "cannot be assumed"),
        )["FunctionArn"]
        lam.get_waiter("function_active_v2").wait(FunctionName=FUNCTION_NAME)
        print(f"  created {arn}")

    # Let Bedrock Flows invoke it.
    try:
        lam.add_permission(
            FunctionName=FUNCTION_NAME,
            StatementId="AllowBedrockFlows",
            Action="lambda:InvokeFunction",
            Principal="bedrock.amazonaws.com",
            SourceAccount=acct,
        )
        print("  granted bedrock.amazonaws.com invoke permission")
    except lam.exceptions.ResourceConflictException:
        print("  invoke permission already present")

    common.save_state(bugIntakeLambdaArn=arn, bugIntakeRoleArn=role_arn)
    print(f"\nBug intake Lambda: {arn}")


if __name__ == "__main__":
    main()
