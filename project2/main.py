"""
Customer Support AI Agent — Starter Code
==========================================
Your task is to complete this file by implementing all sections marked
with # TODO comments.

Reference the step-by-step solution files and INSTRUCTIONS.md for guidance.
Do NOT copy the solution directly — work through each section yourself.

Run locally (after filling in config values):
  uv run main.py '{"prompt": "Hello", "customer_id": "CUST-123", "session_id": "s1"}'

Deploy to AgentCore:
  agentcore deploy

Invoke deployed agent:
  agentcore invoke '{"prompt": "Hello", "customer_id": "CUST-123", "session_id": "s1"}'
"""

# ── Imports ───────────────────────────────────────────────────────────────────
# These imports are provided. Do not remove them.
from strands import Agent, tool
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from bedrock_agentcore.memory import MemoryClient
from strands.models import BedrockModel
from strands.tools.mcp.mcp_client import MCPClient
from mcp.client.streamable_http import streamable_http_client
import argparse, json
import os, asyncio, boto3
from strands.hooks import (
    HookProvider, AfterInvocationEvent, HookRegistry, MessageAddedEvent,
)
import logging
import uuid
from typing import Dict
from bedrock_agentcore.tools.code_interpreter_client import code_session
from strands_tools.browser import AgentCoreBrowser

# Added by the student: lets the Gateway connection be entered conditionally so
# a Gateway outage degrades to the local tools instead of failing the request.
from contextlib import ExitStack


# ── Python 3.14 / nest_asyncio compatibility ─────────────────────────────────
# strands_tools.browser calls nest_asyncio.apply() the first time the browser
# tool actually runs. apply() does two separate things: it makes the event loop
# re-entrant (which the browser wants) and it replaces asyncio.Task with the
# pure-Python implementation (which it does not need here, because Strands runs
# sync tools in a worker thread rather than nesting loops).
#
# On Python 3.14 that second change is destructive: asyncio.current_task()
# returns None inside those tasks, so anyio's cancel scope raises
#   TypeError: cannot create weak reference to 'NoneType' object
# and every subsequent MCP connection to the Gateway fails. The patch is global
# and process-wide, so in a warm AgentCore container it outlives the request
# that triggered it — the agent silently loses its Gateway tools from the next
# request onward and answers from the knowledge base instead.
#
# nest_asyncio._patch_asyncio() returns early when asyncio._nest_patched is
# already set, so claiming it here keeps the loop patches and skips the Task
# swap. Verified both ways: the browser still succeeds, and MCP connections made
# after the browser has run still return all six Gateway tools.
asyncio._nest_patched = True


logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("CSAI_Agent")

# ── TODO 1 — App Initialisation ───────────────────────────────────────────────
# Create a BedrockAgentCoreApp instance.
# This registers the ASGI server for AgentCore deployment.
# There must be exactly one instance per deployment.
#
# Hint: app = BedrockAgentCoreApp()

# TODO: Create the BedrockAgentCoreApp instance
app = BedrockAgentCoreApp()


# Suppress interactive tool-consent prompts (required in headless deployments).
os.environ["BYPASS_TOOL_CONSENT"] = "true"


# ── TODO 2 — Configuration ────────────────────────────────────────────────────
# Replace the placeholder strings with your actual AWS resource values.
# You collected these in Part 1 of the INSTRUCTIONS.
#
# GATEWAY_URL format: https://<alias>.gateway.bedrock-agentcore.<region>.amazonaws.com/mcp
# KB_ID       format: 10-character alphanumeric string from the KB console
# REGION:     your AWS region, e.g. "us-east-1"
# MEMORY_ID   format: shown in the AgentCore Memory console

GATEWAY_URL = "https://customersupportgateway-jegj9um1df.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"   # TODO: Replace with your Gateway URL
KB_ID       = "BKQZ0FINYK"          # TODO: Replace with your Knowledge Base ID
REGION      = "us-east-1"       # TODO: Replace with your AWS region
MEMORY_ID   = "CustomerSupportMemory-y2L27R6Doi"        # TODO: Replace with your Memory ID


def _is_configured(value: str) -> bool:
    """True when a configuration constant has been filled in with a real value."""
    return bool(value) and not value.startswith("<")


# ── TODO 3 — Model and Clients ────────────────────────────────────────────────
# Create:
#   1. A BedrockModel using model_id "global.amazon.nova-2-lite-v1:0"
#   2. A MemoryClient with region_name=REGION
#   3. A boto3 client for the "bedrock-agent-runtime" service in REGION
#
# Hint: model = BedrockModel(model_id=model_id)

model_id = "global.amazon.nova-2-lite-v1:0"

# TODO: Create the BedrockModel instance
model = BedrockModel(model_id=model_id, region_name=REGION)

# TODO: Create the MemoryClient instance
memory_client = MemoryClient(region_name=REGION)

# TODO: Create the boto3 bedrock-agent-runtime client
_bedrock_runtime = boto3.client("bedrock-agent-runtime", region_name=REGION)


# ── TODO 4 — Namespace Helper ─────────────────────────────────────────────────
# Implement get_namespaces() to return a dict mapping strategy type to
# namespace template string.
#
# Steps:
#   1. Call mem_client.get_memory_strategies(memory_id) to get strategy list
#   2. Return a dict: { strategy["type"]: strategy["namespaces"][0] for each strategy }
#
# Example output:
#   { "SEMANTIC": "cs_agent/{actorId}/facts",
#     "USER_PREFERENCE": "cs_agent/{actorId}/preferences" }

def get_namespaces(mem_client: MemoryClient, memory_id: str) -> Dict:
    """Return a dict mapping strategy type → namespace template string."""
    # TODO: Implement this function
    namespaces: Dict[str, str] = {}

    for strategy in mem_client.get_memory_strategies(memory_id):
        # The control-plane response spells this field "namespaceTemplates" in
        # current API versions and "namespaces" in older ones — accept both.
        templates = (
            strategy.get("namespaceTemplates")
            or strategy.get("namespaces")
            or []
        )
        if not templates:
            continue

        # Likewise the strategy type is returned under several key names
        # depending on the SDK / API version.
        strategy_type = (
            strategy.get("type")
            or strategy.get("memoryStrategyType")
            or strategy.get("strategyType")
        )
        if not strategy_type:
            continue

        namespaces[strategy_type] = templates[0]

    return namespaces


# ── TODO 5 — Memory Hook ──────────────────────────────────────────────────────
# Implement MemoryHook, a HookProvider subclass that adds long-term memory.
#
# The class needs:
#   __init__(self, actor_id, session_id, memory_client, memory_id)
#     — store all four as instance attributes
#     — call get_namespaces() and store the result as self.namespaces
#
#   retrieve_customer_context(self, event: MessageAddedEvent)
#     — only runs for plain-text user messages (not tool results)
#     — for each strategy namespace, call memory_client.retrieve_memories(
#          memory_id, namespace (formatted with actorId), query, top_k=5)
#     — collect non-empty memory texts tagged with their strategy type
#     — if any memories found, prepend them to the user message as:
#          "Customer Context:\n<memories>\n\n<original_message>"
#
#   save_support_interaction(self, event: AfterInvocationEvent)
#     — walk the message list backwards to find the last plain-text user
#       query and the last assistant response
#     — call memory_client.create_event(memory_id, actor_id, session_id,
#          messages=[(customer_query, "USER"), (agent_response, "ASSISTANT")])
#
#   register_hooks(self, registry: HookRegistry)
#     — register retrieve_customer_context on MessageAddedEvent
#     — register save_support_interaction on AfterInvocationEvent

class MemoryHook(HookProvider):
    """Long-term memory hook for the customer support agent."""

    def __init__(
        self,
        actor_id: str,
        session_id: str,
        memory_client: MemoryClient,
        memory_id: str,
    ):
        # TODO: Store actor_id, session_id, memory_id, memory_client as attributes
        # TODO: Call get_namespaces() and store the result as self.namespaces
        self.actor_id      = actor_id
        self.session_id    = session_id
        self.memory_client = memory_client
        self.memory_id     = memory_id
        self.namespaces    = get_namespaces(memory_client, memory_id)
        logger.info("MemoryHook namespaces: %s", self.namespaces)

    # ── Helpers ───────────────────────────────────────────────────────────────
    @staticmethod
    def _plain_text(message: Dict) -> str:
        """
        Return the text of a message that is plain prose.

        Returns "" for tool results and tool-use blocks so that the hook only
        ever acts on something a human actually typed or the agent actually said.
        """
        content = message.get("content") or []
        if not content or not isinstance(content[0], dict):
            return ""
        block = content[0]
        if "toolResult" in block or "toolUse" in block:
            return ""
        return (block.get("text") or "").strip()

    def _namespace_for(self, template: str) -> str:
        """Expand a namespace template such as cs_agent/{actorId}/facts."""
        return (
            template
            .replace("{actorId}", self.actor_id)
            .replace("{sessionId}", self.session_id)
            .replace("{memoryStrategyId}", "")
        )

    # ── Retrieval (runs before the model sees the message) ────────────────────
    def retrieve_customer_context(self, event: MessageAddedEvent):
        """Retrieve relevant memories and prepend them to the user message."""
        # TODO: Implement memory retrieval
        # Steps:
        #   1. Get the last message from event.agent.messages
        #   2. Check it is a user message and not a tool result
        #   3. Extract the user query text
        #   4. For each namespace in self.namespaces, call retrieve_memories()
        #   5. Collect non-empty memory texts with strategy type tags
        #   6. If any found, prepend them to the user message
        messages = event.agent.messages
        if not messages:
            return

        last_message = messages[-1]
        if last_message.get("role") != "user":
            return

        user_query = self._plain_text(last_message)
        if not user_query:
            # Tool result or empty block — nothing to search on.
            return

        recalled: list[str] = []
        for strategy_type, template in self.namespaces.items():
            namespace = self._namespace_for(template)
            try:
                memories = self.memory_client.retrieve_memories(
                    memory_id=self.memory_id,
                    namespace=namespace,
                    query=user_query,
                    top_k=5,
                )
            except Exception as e:
                logger.warning(
                    "Memory retrieval failed for namespace %s: %s", namespace, e
                )
                continue

            for memory in memories or []:
                if not isinstance(memory, dict):
                    continue
                content = memory.get("content")
                text = ""
                if isinstance(content, dict):
                    text = (content.get("text") or "").strip()
                elif isinstance(content, str):
                    text = content.strip()
                if text:
                    recalled.append(f"[{strategy_type}] {text}")

        if not recalled:
            return

        context_block = "\n".join(recalled)
        last_message["content"][0]["text"] = (
            f"Customer Context:\n{context_block}\n\n{user_query}"
        )
        logger.info("Injected %d memory item(s) into the user message", len(recalled))

    # ── Persistence (runs after the agent has answered) ───────────────────────
    def save_support_interaction(self, event: AfterInvocationEvent):
        """Save the completed turn to memory after the agent responds."""
        # TODO: Implement memory saving
        # Steps:
        #   1. Get messages from event.agent.messages
        #   2. Walk backwards to find the last user query (plain text)
        #      and the last assistant response
        #   3. Call memory_client.create_event() with both messages
        messages = event.agent.messages
        if not messages:
            return

        customer_query = None
        agent_response = None

        for message in reversed(messages):
            role = message.get("role")
            text = self._plain_text(message)
            if not text:
                continue
            if agent_response is None and role == "assistant":
                agent_response = text
            elif customer_query is None and role == "user":
                # Strip any context we prepended so only the real question is stored.
                if text.startswith("Customer Context:") and "\n\n" in text:
                    text = text.split("\n\n", 1)[1]
                customer_query = text
            if customer_query and agent_response:
                break

        if not (customer_query and agent_response):
            return

        try:
            self.memory_client.create_event(
                memory_id=self.memory_id,
                actor_id=self.actor_id,
                session_id=self.session_id,
                messages=[
                    (customer_query, "USER"),
                    (agent_response, "ASSISTANT"),
                ],
            )
            logger.info("Saved support interaction to memory %s", self.memory_id)
        except Exception as e:
            logger.warning("Failed to save interaction to memory: %s", e)

    def register_hooks(self, registry: HookRegistry) -> None:  # type: ignore
        """Register both memory callbacks."""
        # TODO: Register retrieve_customer_context on MessageAddedEvent
        # TODO: Register save_support_interaction on AfterInvocationEvent
        registry.add_callback(MessageAddedEvent, self.retrieve_customer_context)
        registry.add_callback(AfterInvocationEvent, self.save_support_interaction)


# ── TODO 6 — Knowledge Base Tool ─────────────────────────────────────────────
# Implement search_knowledge_base(query) using the @tool decorator.
#
# Steps:
#   1. Guard: if KB_ID is empty return "Knowledge base not configured."
#   2. Call _bedrock_runtime.retrieve(
#          knowledgeBaseId=KB_ID,
#          retrievalQuery={"text": query}
#      )
#   3. Extract resp["retrievalResults"]; return a message if empty
#   4. Join the text chunks with "\n---\n" and return the result
#
# The docstring is the tool description — the model uses it to decide when
# to call this tool, so keep it clear and accurate.

@tool
def search_knowledge_base(query: str) -> str:
    """
    Search the Amazon product catalog and support knowledge base.
    Use this for product specifications, return policies, warranty
    information, loyalty program details, and order status definitions.

    Args:
        query: The question or topic to search for

    Returns:
        Relevant information retrieved from the knowledge base
    """
    # TODO: Implement the Knowledge Base search
    if not _is_configured(KB_ID):
        return (
            "Knowledge base not configured. Set KB_ID in main.py to the "
            "Bedrock Knowledge Base ID before using this tool."
        )

    try:
        resp = _bedrock_runtime.retrieve(
            knowledgeBaseId=KB_ID,
            retrievalQuery={"text": query},
        )
    except Exception as e:
        logger.warning("Knowledge base retrieval failed: %s", e)
        return f"Knowledge base search failed: {e}"

    results = resp.get("retrievalResults", [])
    if not results:
        return f"No knowledge base results found for '{query}'."

    chunks = [
        (r.get("content", {}).get("text") or "").strip()
        for r in results
    ]
    return "\n---\n".join(chunk for chunk in chunks if chunk)


# ── TODO 7 — Loyalty Discount Tool (Code Interpreter) ────────────────────────
# Implement calculate_loyalty_discount() using the @tool decorator.
#
# The tool must:
#   1. Build a self-contained Python code string that:
#        • Defines earn_rates: {"standard": 1, "device": 2, "fresh": 5}
#        • Defines tier_rates: {"Silver": 0.00, "Gold": 0.10, "Platinum": 0.15}
#        • Calculates points_redeemed (floor to nearest 500, cap at 50% of order)
#        • Calculates tier_discount (applied to subtotal after points)
#        • Calculates final_total, total_savings, points_earned, remaining_points
#        • Prints a JSON result dict
#   2. Execute the code with code_session(REGION).invoke("executeCode", {...})
#      using language="python" and clearContext=True
#   3. Return the first result event as a JSON string
#   4. Include a fallback that computes only the tier discount if the
#      Code Interpreter is unavailable

@tool
def calculate_loyalty_discount(
    loyalty_points: int,
    tier: str,
    order_total: float,
    product_category: str = "standard",
) -> str:
    """
    Calculate the loyalty discount for a customer order using the
    AgentCore Code Interpreter. Runs exact arithmetic in a secure sandbox.

    Args:
        loyalty_points:   Customer's current points balance
        tier:             Customer tier — Silver, Gold, or Platinum
        order_total:      Order total in USD
        product_category: standard, device, or fresh

    Returns:
        Full discount breakdown and final price
    """
    # TODO: Build the code string (use an f-string to inject the arguments)
    code = f'''
import json

# ── Loyalty program business rules (from the product catalog) ────────────────
earn_rates = {{"standard": 1, "device": 2, "fresh": 5}}
tier_rates = {{"Silver": 0.00, "Gold": 0.10, "Platinum": 0.15}}

POINTS_PER_DOLLAR   = 100     # 100 points == $1 discount
REDEMPTION_BLOCK    = 500     # minimum redemption, floor to this multiple
MAX_POINTS_COVERAGE = 0.50    # points may cover at most 50% of the order

loyalty_points   = {int(loyalty_points)}
tier             = {str(tier).strip().capitalize()!r}
order_total      = {float(order_total)!r}
product_category = {str(product_category).strip().lower()!r}

# ── 1. Points redemption: floor to nearest 500, capped at 50% of the order ──
cap_in_points   = int(order_total * MAX_POINTS_COVERAGE * POINTS_PER_DOLLAR)
redeemable      = min(loyalty_points, cap_in_points)
points_redeemed = (redeemable // REDEMPTION_BLOCK) * REDEMPTION_BLOCK
points_value    = round(points_redeemed / POINTS_PER_DOLLAR, 2)

# ── 2. Tier discount, applied to the subtotal after points ──────────────────
subtotal_after_points = round(order_total - points_value, 2)
tier_rate             = tier_rates.get(tier, 0.00)
tier_discount         = round(subtotal_after_points * tier_rate, 2)

# ── 3. Totals ───────────────────────────────────────────────────────────────
final_total   = round(subtotal_after_points - tier_discount, 2)
total_savings = round(order_total - final_total, 2)

# ── 4. Points earned on what the customer actually pays ─────────────────────
earn_rate        = earn_rates.get(product_category, 1)
points_earned    = int(final_total * earn_rate)
remaining_points = loyalty_points - points_redeemed + points_earned

result = {{
    "order_total":          round(order_total, 2),
    "tier":                 tier,
    "product_category":     product_category,
    "points_redeemed":      points_redeemed,
    "points_value_usd":     points_value,
    "tier_discount_pct":    round(tier_rate * 100, 2),
    "tier_discount_amount": tier_discount,
    "final_total":          final_total,
    "total_savings":        total_savings,
    "points_earned":        points_earned,
    "remaining_points":     remaining_points,
    "calculation_method":   "code_interpreter",
}}
print(json.dumps(result, indent=2))
'''

    try:
        # TODO: Execute the code using code_session and return the result
        with code_session(REGION) as interpreter:
            response = interpreter.invoke(
                "executeCode",
                {
                    "code":         code,
                    "language":     "python",
                    "clearContext": True,
                },
            )
            for event in response["stream"]:
                # Return the first result event as a JSON string.
                return json.dumps(event["result"])

        raise RuntimeError("Code Interpreter returned no result events")

    except Exception as e:
        # TODO: Implement fallback calculation using tier discount only
        logger.warning("Code Interpreter unavailable (%s) — using local fallback", e)

        tier_rates    = {"Silver": 0.00, "Gold": 0.10, "Platinum": 0.15}
        tier_name     = str(tier).strip().capitalize()
        tier_rate     = tier_rates.get(tier_name, 0.00)
        order_amount  = float(order_total)
        tier_discount = round(order_amount * tier_rate, 2)
        final_total   = round(order_amount - tier_discount, 2)

        return json.dumps(
            {
                "order_total":          round(order_amount, 2),
                "tier":                 tier_name,
                "product_category":     str(product_category).strip().lower(),
                "points_redeemed":      0,
                "points_value_usd":     0.0,
                "tier_discount_pct":    round(tier_rate * 100, 2),
                "tier_discount_amount": tier_discount,
                "final_total":          final_total,
                "total_savings":        tier_discount,
                "points_earned":        0,
                "remaining_points":     int(loyalty_points),
                "calculation_method":   "local_fallback",
                "note": (
                    "Code Interpreter unavailable; tier discount only — "
                    "loyalty points were not redeemed."
                ),
            },
            indent=2,
        )


# ── System prompt ────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are a customer support specialist for an online Amazon store.

Your job is to resolve customer issues in one turn wherever possible, using the
tools available to you rather than guessing.

Tool guidance:
- search_knowledge_base — product specs, return/refund policies, warranty terms,
  loyalty program rules, and order status definitions.
- get_order / get_customer_orders / get_customer — live order and customer
  lookups through the support API. Always look an order up before commenting on
  its status.
- initiate_refund / check_refund_status / get_return_label — refunds and returns.
  Confirm the order exists and is eligible before initiating a refund.
- calculate_loyalty_discount — any question involving points, tiers, or the final
  price of an order. Never do this arithmetic yourself.
- browser — only when the customer asks for information from a live web page.
  The browser is session-based. Start with the init_session action, then
  navigate, then read the page, reusing the same session_name throughout.
  session_name must be 10-36 characters of lowercase letters, digits and
  hyphens only — no underscores, no capitals (for example "support-browse-1").
  To read a page title, use the evaluate action with the script
  "document.title" rather than get_text, which needs a CSS selector.

Rules:
- Ground every factual claim in a tool result. If a tool fails, say so plainly.
- Never invent order IDs, tracking numbers, refund IDs, or policy details.
- Respect any stated customer preference (for example, a preference for short
  answers) that appears in the Customer Context block.
- Be warm, concise, and specific. Quote exact numbers, dates, and IDs.
"""


# ── TODO 8 — Agent Entrypoint ─────────────────────────────────────────────────
# Implement the invoke() function decorated with @app.entrypoint.
#
# Steps:
#   1. Extract user_input, actor_id, and session_id from the payload
#      (generate a UUID if session_id is missing)
#   2. Instantiate MemoryHook for this actor/session
#   3. Instantiate AgentCoreBrowser(region=REGION)
#   4. Build the tools list: [search_knowledge_base, calculate_loyalty_discount,
#                              agent_core_browser.browser]
#   5. Connect to the Gateway via MCPClient, load gateway_tools, extend tools list
#   6. Create and invoke the Agent with all tools, hooks, and system_prompt
#   7. Return the text from the first content block of the response
#   8. Handle exceptions gracefully

@app.entrypoint
async def invoke(payload, context=None):
    """
    Main handler called by AgentCore for every incoming request.

    Expected payload keys:
      prompt      (str, required) — the customer's message
      customer_id (str, optional) — unique customer identifier
      session_id  (str, optional) — session identifier; generated if absent
    """
    # TODO: Implement the agent invocation
    # ── 1. Payload ───────────────────────────────────────────────────────────
    user_input = (payload or {}).get("prompt", "").strip()
    actor_id   = (payload or {}).get("customer_id") or "anonymous"
    session_id = (payload or {}).get("session_id") or str(uuid.uuid4())

    if not user_input:
        return "Please include a 'prompt' field with your question."

    # ── 2. Long-term memory hook ─────────────────────────────────────────────
    hooks: list = []
    if _is_configured(MEMORY_ID):
        try:
            hooks.append(MemoryHook(actor_id, session_id, memory_client, MEMORY_ID))
        except Exception as e:
            logger.warning("Memory unavailable (%s) — continuing without it", e)

    # ── 3./4. Local tools, including the AgentCore browser ───────────────────
    agent_core_browser = AgentCoreBrowser(region=REGION)
    tools = [
        search_knowledge_base,
        calculate_loyalty_discount,
        agent_core_browser.browser,
    ]

    # ── 5. Gateway tools over MCP ────────────────────────────────────────────
    gateway_client = MCPClient(lambda: streamable_http_client(GATEWAY_URL))

    with ExitStack() as stack:
        if _is_configured(GATEWAY_URL):
            try:
                stack.enter_context(gateway_client)
                gateway_tools = gateway_client.list_tools_sync()
                tools.extend(gateway_tools)
                logger.info(
                    "Loaded %d Gateway tool(s): %s",
                    len(gateway_tools),
                    [t.tool_name for t in gateway_tools],
                )
            except Exception as e:
                # A Gateway outage should degrade the agent, not break it.
                logger.warning(
                    "Gateway unavailable (%s) — continuing with local tools only", e
                )

        # ── 6./7. Run the agent ──────────────────────────────────────────────
        try:
            agent = Agent(
                model=model,
                tools=tools,
                hooks=hooks,
                system_prompt=SYSTEM_PROMPT,
                # The entrypoint returns a single string, so suppress the default
                # token-streaming handler that would otherwise echo the answer.
                callback_handler=None,
            )
            result = await agent.invoke_async(user_input)
            return result.message["content"][0]["text"]

        # ── 8. Graceful failure ──────────────────────────────────────────────
        except Exception as e:
            logger.exception("Agent invocation failed")
            return (
                "Sorry — I ran into a problem while handling that request "
                f"({type(e).__name__}: {e}). Please try again."
            )


# ── CLI entry point (do not modify) ──────────────────────────────────────────
def main():
    """Run one invocation from the command line for local testing."""
    parser = argparse.ArgumentParser()
    parser.add_argument("payload", type=str)
    args = parser.parse_args()
    response = asyncio.run(invoke(json.loads(args.payload)))
    print(response)


if __name__ == "__main__":
    app.run()
    # Uncomment the line below and comment app.run() for local CLI testing:
    # main()
