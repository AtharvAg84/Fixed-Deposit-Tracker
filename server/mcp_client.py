"""
mcp_client.py
FastMCP Client + AI Agent (Gemini → Groq fallback).

STATELESS design — every query is a fresh API call.
No conversation history = minimal token usage = no quota blowout.

Flow per query:
  User input → AI picks MCP tool → MCP executes → AI formats answer → User sees result
"""

import asyncio
import json
import logging
import time
import re
import os

from google import genai
from google.genai import types as gtypes
from groq import Groq
from fastmcp.client import Client
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
SERVER_SCRIPT = "mcp_server.py"
GEMINI_MODEL  = "gemini-2.0-flash-lite"
GROQ_MODEL    = "llama-3.3-70b-versatile"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY   = os.getenv("GROQ_API_KEY")

gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
groq_client   = Groq(api_key=GROQ_API_KEY)           if GROQ_API_KEY   else None

if not gemini_client and not groq_client:
    raise ValueError("Set at least one of GEMINI_API_KEY or GROQ_API_KEY in .env")

SYSTEM_PROMPT = """You are an FD (Fixed Deposit) rate advisor for Indian banks.
You have tools to fetch live rate data. 

Rules:
- ALWAYS call a tool to get data. Never guess rates.
- Convert tenure to days: 1 month=30, 3 months=90, 6 months=180,
  1 year=365, 2 years=730, 3 years=1095, 5 years=1825.
- default deposit_category is "retail".
- category is "general" unless user says "senior".
- After getting tool data, reply in a clean human-readable format.
"""


# ── MCP Tool Call ─────────────────────────────────────────────────────────────

async def call_mcp_tool(mcp: Client, name: str, args: dict) -> dict:
    logger.info(f"[MCP] {name}({args})")
    try:
        resp = await mcp.call_tool(name, args)

        if isinstance(resp, list):
            resp = resp[0] if resp else {"status": "error", "error": "Empty response"}

        if hasattr(resp, "text"):
            text = resp.text.strip().removeprefix("```json").removesuffix("```").strip()
            resp = json.loads(text)

        return resp if isinstance(resp, dict) else {"status": "error", "error": str(resp)}

    except Exception as e:
        logger.error(f"[MCP] Error: {e}")
        return {"status": "error", "error": str(e)}


# ── Tool Schema Builders ──────────────────────────────────────────────────────

def build_gemini_tools(raw: list[dict]) -> list[gtypes.Tool]:
    decls = []
    for t in raw:
        params = t.get("parameters") or {"type": "object", "properties": {}}
        props  = {
            k: gtypes.Schema(
                type=v.get("type", "string").upper(),
                description=v.get("description", ""),
                enum=v.get("enum"),
            )
            for k, v in params.get("properties", {}).items()
        }
        decls.append(gtypes.FunctionDeclaration(
            name=t["name"],
            description=t.get("description", ""),
            parameters=gtypes.Schema(type="OBJECT", properties=props,
                                     required=params.get("required", [])),
        ))
    return [gtypes.Tool(function_declarations=decls)]


def build_groq_tools(raw: list[dict]) -> list[dict]:
    tools = []
    for t in raw:
        params = t.get("parameters") or {"type": "object", "properties": {}}
        tools.append({
            "type": "function",
            "function": {
                "name":        t["name"],
                "description": t.get("description", ""),
                "parameters": {
                    "type": "object",
                    "properties": {
                        k: {k2: v2 for k2, v2 in v.items()
                            if k2 in ("type", "description", "enum", "items")}
                        for k, v in params.get("properties", {}).items()
                    },
                    "required": params.get("required", []),
                },
            },
        })
    return tools


async def discover_tools(mcp: Client) -> dict:
    resp = await mcp.list_tools()
    raw  = [
        {
            "name":        t.name,
            "description": t.description or "",
            "parameters":  t.parameters if hasattr(t, "parameters") else {
                "type": "object", "properties": {}
            },
        }
        for t in resp
    ]
    logger.info(f"Tools: {[t['name'] for t in raw]}")
    return {
        "raw":    raw,
        "gemini": build_gemini_tools(raw) if gemini_client else None,
        "groq":   build_groq_tools(raw)   if groq_client   else None,
    }


# ── Single-turn AI call (stateless) ──────────────────────────────────────────
# Each call is: [system + user_query] only — no history appended.
# Tool results are fed back in the same turn until AI gives a final text answer.

async def run_turn_gemini(user_query: str, schemas: dict, mcp: Client) -> str:
    """Run one full user turn with Gemini. Returns final answer string."""
    config = gtypes.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        tools=schemas["gemini"],
    )
    # Start with just the user message — no history
    messages = [gtypes.Content(role="user", parts=[gtypes.Part(text=user_query)])]

    for _ in range(5):   # max 5 tool-call rounds per query
        resp  = gemini_client.models.generate_content(
            model=GEMINI_MODEL, contents=messages, config=config
        )
        parts = resp.candidates[0].content.parts
        tool_calls = [p for p in parts if p.function_call is not None]
        text_parts = [p for p in parts if p.text]

        if not tool_calls:
            return "".join(p.text for p in text_parts).strip()

        # Append model turn + execute tools + append results
        messages.append(gtypes.Content(role="model", parts=parts))
        result_parts = []
        for p in tool_calls:
            fc     = p.function_call
            result = await call_mcp_tool(mcp, fc.name, dict(fc.args))
            result_parts.append(gtypes.Part(
                function_response=gtypes.FunctionResponse(name=fc.name, response=result)
            ))
        messages.append(gtypes.Content(role="tool", parts=result_parts))

    return "Sorry, I could not complete the request."


async def run_turn_groq(user_query: str, schemas: dict, mcp: Client) -> str:
    """Run one full user turn with Groq. Returns final answer string."""
    messages = [
        {"role": "system",  "content": SYSTEM_PROMPT},
        {"role": "user",    "content": user_query},
    ]

    for _ in range(5):   # max 5 tool-call rounds per query
        resp = groq_client.chat.completions.create(
            model=GROQ_MODEL, messages=messages,
            tools=schemas["groq"], tool_choice="auto",
        )
        msg        = resp.choices[0].message
        tool_calls = msg.tool_calls or []

        if not tool_calls:
            return (msg.content or "").strip()

        # Append model turn
        messages.append({
            "role": "assistant", "content": msg.content,
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in tool_calls
            ],
        })
        # Execute tools and append results
        for tc in tool_calls:
            result = await call_mcp_tool(mcp, tc.function.name,
                                         json.loads(tc.function.arguments))
            messages.append({
                "role": "tool", "tool_call_id": tc.id, "content": json.dumps(result)
            })

    return "Sorry, I could not complete the request."


# ── Main Loop ─────────────────────────────────────────────────────────────────

async def run_agent():
    mcp = Client(SERVER_SCRIPT)
    logger.info(f"Connecting to {SERVER_SCRIPT}")

    async with mcp:
        schemas = await discover_tools(mcp)
        active  = "gemini" if gemini_client else "groq"

        print("\n" + "=" * 60)
        print("  FD Rate Advisor  |  Gemini → Groq fallback")
        print(f"  Active : {active.upper()}")
        print(f"  Tools  : {[t['name'] for t in schemas['raw']]}")
        print("  Type 'exit' to quit.")
        print("=" * 60 + "\n")

        while True:
            user_input = input("You: ").strip()
            if user_input.lower() in ("exit", "quit", "q"):
                print("Goodbye!")
                break
            if not user_input:
                continue

            try:
                if active == "gemini":
                    answer = await run_turn_gemini(user_input, schemas, mcp)
                else:
                    answer = await run_turn_groq(user_input, schemas, mcp)

            except Exception as e:
                if ("429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)) and groq_client:
                    print(f"\n[Gemini rate limited → switching to Groq]\n")
                    logger.warning("Switching to Groq")
                    active = "groq"
                    try:
                        answer = await run_turn_groq(user_input, schemas, mcp)
                    except Exception as e2:
                        print(f"[Error] Groq also failed: {e2}")
                        continue
                else:
                    print(f"[Error] {e}")
                    continue

            print(f"\nAdvisor [{active.upper()}]: {answer}\n")


if __name__ == "__main__":
    asyncio.run(run_agent())