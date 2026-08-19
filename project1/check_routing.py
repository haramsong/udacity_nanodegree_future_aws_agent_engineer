#!/usr/bin/env python3
"""Run every prompt in flow-tests.json and report which Output node answered.

Checks the classify-and-route behaviour on its own, separately from answer
quality, by asserting the test id prefix against the Output node reached.

  python check_routing.py                  # all tests
  python check_routing.py --filter bug     # only ids containing "bug"
"""
import argparse
import json
from pathlib import Path

import common
import invoke_flow

# test id prefix -> the Output node that should answer
EXPECTED_NODE = {
    "faq": "PlatformQuestionOutput",
    "bug": "BugReportOutput",
    "other": "OtherRequestOutput",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default=None)
    ap.add_argument("--tests-json", default="evaluation/flow-tests.json")
    ap.add_argument("--filter", default="", help="only run test ids containing this string")
    args = ap.parse_args()

    suite = json.loads(Path(args.tests_json).read_text(encoding="utf-8"))
    state = common.load_state()
    client = common.session(args.profile).client("bedrock-agent-runtime")

    failures = 0
    for t in suite["tests"]:
        if args.filter and args.filter not in t["id"]:
            continue
        want = EXPECTED_NODE[t["id"].split("-")[0]]
        try:
            result = invoke_flow.invoke(
                client, state["flowId"], state["flowAliasId"], t["prompt"]
            )
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL {t['id']:38} -> ERROR {type(exc).__name__}: {exc}"[:300])
            failures += 1
            continue

        got = result["node"]
        ok = got == want
        failures += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {t['id']:38} -> {got}")
        if not ok:
            print(f"       expected {want}")
        print(f"       {(result['text'] or '').strip()[:260]}")

    print(f"\n{failures} routing failure(s)")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
