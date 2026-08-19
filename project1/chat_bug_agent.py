#!/usr/bin/env python3
"""Hold a multi-turn conversation with the bug intake agent.

The flow's bug branch is a Lambda node, and a Lambda node cannot emit
flowMultiTurnInputRequestEvent, so a follow-up question ends the flow execution
instead of pausing it. The agent itself is perfectly capable of the two-turn
exchange - ask for what's missing, then file the ticket - and this script shows
that against the same AgentCore harness the flow uses.

  # scripted: turn 1 is vague, turn 2 supplies the missing details
  python chat_bug_agent.py --demo

  # free-form
  python chat_bug_agent.py
  python chat_bug_agent.py "Your checkout page is broken"
"""
import argparse
import os
import sys

import common

DEMO_TURNS = [
    "Your checkout page is broken.",
    "I add a hoodie to the cart, click Checkout, fill in my address and press Pay. "
    "The spinner runs forever and nothing happens. I'm on Firefox 133 on Ubuntu 24.04.",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("message", nargs="*", help="opening message")
    ap.add_argument("--profile", default=None)
    ap.add_argument(
        "--demo",
        action="store_true",
        help="run a scripted two-turn exchange: vague report, then the missing details",
    )
    args = ap.parse_args()

    state = common.load_state()
    harness_arn = state.get("harnessArn")
    tool_lambda = state.get("lambdaArn") or state.get("bugToolLambdaArn")
    if not harness_arn:
        raise SystemExit("no harnessArn in deploy-state.json - run configure_harness.py first")

    os.environ.setdefault("AWS_PROFILE", args.profile or "udacity")
    os.environ.setdefault("AWS_REGION", common.REGION)
    os.environ["HARNESS_ARN"] = harness_arn
    if not tool_lambda:
        sess = common.session(args.profile)
        fns = [
            f["FunctionArn"]
            for f in sess.client("lambda").list_functions()["Functions"]
            if f["FunctionName"].startswith("create-bug-report")
        ]
        tool_lambda = fns[0]
    os.environ["TOOL_LAMBDA_ARN"] = tool_lambda

    import bug_intake  # imported after the env vars it reads at module load

    session_id = bug_intake.new_session_id()
    messages = []
    tickets = []
    print(f"session {session_id}")
    print(f"harness {harness_arn}\n")

    scripted = list(DEMO_TURNS) if args.demo else []
    if args.message:
        scripted = [" ".join(args.message)] + scripted[1:] if args.demo else [" ".join(args.message)]

    while True:
        if scripted:
            text = scripted.pop(0)
            print(f"customer> {text}")
        else:
            if args.demo:
                break
            try:
                text = input("customer> ").strip()
            except EOFError:
                break
            if not text:
                break

        messages.append({"role": "user", "content": [{"text": text}]})
        reply = bug_intake.run_agent(
            messages, session_id, on_tool=lambda tu, body: tickets.append(body)
        )
        print(f"agent   > {reply}\n")

        if not scripted and args.demo:
            break

    if tickets:
        print(f"tickets created: {tickets}")
    else:
        print("no ticket was created in this conversation", file=sys.stderr)


if __name__ == "__main__":
    main()
