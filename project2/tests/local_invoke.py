"""
Run one invocation of main.py's entrypoint locally, for pre-deployment testing.

Uses an explicitly managed event loop rather than asyncio.run(): strands_tools.browser
imports nest_asyncio, whose patched run_until_complete breaks asyncio.run()'s
shutdown_default_executor teardown on Python 3.14.
"""
import asyncio, json, sys
import main

if __name__ == "__main__":
    payload = json.loads(sys.argv[1])
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        print(loop.run_until_complete(main.invoke(payload)))
    finally:
        loop.close()
