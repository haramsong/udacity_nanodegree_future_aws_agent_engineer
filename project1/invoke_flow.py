#!/usr/bin/env python3
"""Invoke the customer support flow. Shows which Output node answered, so you can
see the routing decision, and continues multi-turn conversations when the bug
intake agent asks a follow-up question.

  python invoke_flow.py "The checkout button does nothing"
  python invoke_flow.py --interactive "Your checkout page crashes"
  python invoke_flow.py --trace "How long does delivery take?"
"""
import argparse
import sys

import common

INPUT_NODE = "FlowInput"


def invoke(client, flow_id, alias_id, text, execution_id=None, trace=False):
    kwargs = dict(
        flowIdentifier=flow_id,
        flowAliasIdentifier=alias_id,
        enableTrace=trace,
        inputs=[
            {
                "nodeName": INPUT_NODE,
                "nodeOutputName": "document",
                "content": {"document": text},
            }
        ],
    )
    if execution_id:
        kwargs["executionId"] = execution_id

    resp = client.invoke_flow(**kwargs)
    result = {
        "executionId": resp.get("executionId"),
        "node": None,
        "text": None,
        "needsMoreInput": False,
        "traces": [],
    }

    for event in resp["responseStream"]:
        if "flowOutputEvent" in event:
            oe = event["flowOutputEvent"]
            result["node"] = oe.get("nodeName")
            result["text"] = oe.get("content", {}).get("document")
        elif "flowMultiTurnInputRequestEvent" in event:
            ce = event["flowMultiTurnInputRequestEvent"]
            result["node"] = ce.get("nodeName")
            result["text"] = ce.get("content", {}).get("document")
            result["needsMoreInput"] = True
        elif "flowTraceEvent" in event and trace:
            result["traces"].append(event["flowTraceEvent"]["trace"])
        elif "flowCompletionEvent" in event:
            result["completion"] = event["flowCompletionEvent"].get("completionReason")

    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("message", nargs="+", help="customer message")
    ap.add_argument("--profile", default=None)
    ap.add_argument("--trace", action="store_true")
    ap.add_argument(
        "--interactive",
        action="store_true",
        help="keep the session open while the flow asks for more information",
    )
    args = ap.parse_args()

    state = common.load_state()
    flow_id, alias_id = state.get("flowId"), state.get("flowAliasId")
    if not flow_id or not alias_id:
        raise SystemExit("no flow in deploy-state.json - run deploy_flow.py first")

    client = common.session(args.profile).client("bedrock-agent-runtime")

    text = " ".join(args.message)
    execution_id = None
    while True:
        result = invoke(client, flow_id, alias_id, text, execution_id, args.trace)
        execution_id = result["executionId"] or execution_id

        print(f"\n[{result['node']}]{' (needs more input)' if result['needsMoreInput'] else ''}")
        print(result["text"])
        for t in result["traces"]:
            print(f"  trace: {t}", file=sys.stderr)

        if not (result["needsMoreInput"] and args.interactive):
            break
        try:
            text = input("\nyou> ").strip()
        except EOFError:
            break
        if not text:
            break


if __name__ == "__main__":
    main()
