# Reflection

## A design decision

The Gateway integration is where I made the choice I keep going back and forth
on. `invoke()` connects to the AgentCore Gateway over MCP inside an `ExitStack`,
and if that connection fails it logs a warning and builds the agent with only
the local tools rather than failing the request. I chose availability: a
customer asking about the return policy should still get an answer when the
order-lookup path is down. The cost of that choice showed up immediately. When
the Gateway connection broke on the deployed runtime, the agent did not error —
it answered from the knowledge base and told the customer it had no access to
order details. A hard failure would have been obvious; graceful degradation made
a broken integration look like a model that simply chose not to call a tool. I
kept the behaviour but treat the "Gateway unavailable" warning as an alertable
event rather than a log line.

## A challenge

That same failure was the hardest thing to diagnose. The agent worked locally
and failed in the cloud, and only after the first request. The runtime logs held
the answer: `TypeError: cannot create weak reference to 'NoneType' object`,
raised from anyio inside the MCP transport. The cause was
`strands_tools.browser`, which calls `nest_asyncio.apply()` the first time the
browser runs. That replaces `asyncio.Task` with the pure-Python implementation,
and on Python 3.14 `asyncio.current_task()` then returns `None`, so anyio's
cancel scope fails. It never reproduced locally because each local run is a
fresh process; in a warm container the patch outlives the request that caused
it. I reproduced it deliberately — connect, apply, connect again — which turned
an intermittent cloud-only bug into a two-line test.

## A production consideration

Security is the gap I would close first. The Gateway uses the `NONE` authorizer,
so anything that can reach the URL can call `initiate_refund` with an arbitrary
order ID and amount. That is acceptable for a graded exercise and indefensible
in production: refunds move money. I would move to `CUSTOM_JWT`, have the agent
pass the caller's token through, and authorize the refund against the
authenticated customer's own orders in the Lambda rather than trusting the
model's arguments.
