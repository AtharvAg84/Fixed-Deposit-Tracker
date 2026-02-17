"""
bridge.py
FastAPI bridge between React frontend and FastMCP FD Rate server.

Two modes:
  1. Direct tool calls — React calls /rate, /compare, /best, /tenures directly
  2. Chat interface   — React sends natural language query to /chat,
                        AI agent (Gemini/Groq) picks tools and returns answer
"""

import logging
import json
import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from fastmcp.client import Client
from dotenv import load_dotenv

# AI imports
from google import genai
from google.genai import types as gtypes
from groq import Groq

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI(title="FD Rate Comparison Bridge")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000","https://fd-tracker-frontend.onrender.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MCP_SERVER = "mcp_server.py"

# AI clients
GEMINI_MODEL = "gemini-2.0-flash-lite"
GROQ_MODEL   = "llama-3.3-70b-versatile"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY   = os.getenv("GROQ_API_KEY")

gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
groq_client   = Groq(api_key=GROQ_API_KEY)           if GROQ_API_KEY   else None

SYSTEM_PROMPT = """You are an FD rate advisor for Indian banks.
You have tools to fetch live rate data. 

Rules:
- ALWAYS call a tool to get data. Never guess rates.
- Convert tenure to days: 1 month=30, 6 months=180, 1 year=365, 2 years=730, etc.
- default deposit_category is "retail".
- category is "general" unless user says "senior".
- After getting tool data, reply in a clean human-readable format.
"""


# ── Shared MCP call helper (identical pattern to your demo) ───────────────────

async def mcp_call(tool: str, args: dict) -> dict:
    """Call any MCP tool and return the parsed dict response."""
    logger.info(f"[bridge] Calling tool '{tool}' with {args}")
    try:
        client = Client(MCP_SERVER)
        async with client:
            response = await client.call_tool(tool, args)
            logger.debug(f"[bridge] Raw response type: {type(response)}")

            # ── CallToolResult (fastmcp wraps content in .content list) ──
            if hasattr(response, "content"):
                response = response.content
                logger.debug("Extracted .content from CallToolResult")

            # ── List of content blocks → take first ──
            if isinstance(response, list):
                if len(response) == 0:
                    raise ValueError("Empty response from server")
                response = response[0]

            # ── TextContent block → parse .text ──
            if hasattr(response, "text"):
                text = response.text.strip()
                text = text.removeprefix("```json").removesuffix("```").strip()
                response = json.loads(text)
                logger.info("Parsed TextContent to dict")

            if not isinstance(response, dict):
                raise ValueError(f"Unexpected response type: {type(response)}")

            logger.info(f"[bridge] Tool '{tool}' succeeded")
            return response

    except Exception as e:
        logger.error(f"[bridge] Tool '{tool}' failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Request Models ────────────────────────────────────────────────────────────

class GetRateRequest(BaseModel):
    bank_name: str
    days: int
    deposit_category: Optional[str] = "retail"

class CompareBanksRequest(BaseModel):
    days: int
    deposit_category: Optional[str] = "retail"

class BestRateRequest(BaseModel):
    days: int
    category: Optional[str] = "general"
    deposit_category: Optional[str] = "retail"

class ListTenuresRequest(BaseModel):
    bank_name: str
    deposit_category: Optional[str] = "retail"

class ChatRequest(BaseModel):
    query: str


# ── AI Agent Logic (stateless single-turn) ───────────────────────────────────

def build_gemini_tools_for_bridge(raw: list[dict]) -> list[gtypes.Tool]:
    """Convert MCP tool schemas to Gemini function declarations."""
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


def build_groq_tools_for_bridge(raw: list[dict]) -> list[dict]:
    """Convert MCP tool schemas to Groq/OpenAI function format."""
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


async def get_mcp_tools():
    """Fetch tool list from MCP server once."""
    client = Client(MCP_SERVER)
    async with client:
        resp = await client.list_tools()
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
    return {
        "raw":    raw,
        "gemini": build_gemini_tools_for_bridge(raw) if gemini_client else None,
        "groq":   build_groq_tools_for_bridge(raw)   if groq_client   else None,
    }

# Cache tools on startup
TOOLS_CACHE = None

async def run_chat_turn_gemini(query: str) -> str:
    """Run one AI turn with Gemini, return final text answer."""
    global TOOLS_CACHE
    if not TOOLS_CACHE:
        TOOLS_CACHE = await get_mcp_tools()

    config   = gtypes.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        tools=TOOLS_CACHE["gemini"],
    )
    messages = [gtypes.Content(role="user", parts=[gtypes.Part(text=query)])]

    for _ in range(5):   # max 5 tool rounds
        resp  = gemini_client.models.generate_content(
            model=GEMINI_MODEL, contents=messages, config=config
        )
        parts = resp.candidates[0].content.parts
        tool_calls = [p for p in parts if p.function_call is not None]
        text_parts = [p for p in parts if p.text]

        if not tool_calls:
            return "".join(p.text for p in text_parts).strip()

        messages.append(gtypes.Content(role="model", parts=parts))
        result_parts = []
        for p in tool_calls:
            fc     = p.function_call
            result = await mcp_call(fc.name, dict(fc.args))
            result_parts.append(gtypes.Part(
                function_response=gtypes.FunctionResponse(name=fc.name, response=result)
            ))
        messages.append(gtypes.Content(role="tool", parts=result_parts))

    return "Sorry, I could not complete the request."


async def run_chat_turn_groq(query: str) -> str:
    """Run one AI turn with Groq, return final text answer."""
    global TOOLS_CACHE
    if not TOOLS_CACHE:
        TOOLS_CACHE = await get_mcp_tools()

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": query},
    ]

    for _ in range(5):   # max 5 tool rounds
        resp = groq_client.chat.completions.create(
            model=GROQ_MODEL, messages=messages,
            tools=TOOLS_CACHE["groq"], tool_choice="auto",
        )
        msg        = resp.choices[0].message
        tool_calls = msg.tool_calls or []

        if not tool_calls:
            return (msg.content or "").strip()

        messages.append({
            "role": "assistant", "content": msg.content,
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in tool_calls
            ],
        })
        for tc in tool_calls:
            result = await mcp_call(tc.function.name, json.loads(tc.function.arguments))
            messages.append({
                "role": "tool", "tool_call_id": tc.id, "content": json.dumps(result)
            })

    return "Sorry, I could not complete the request."


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/banks")
async def list_banks():
    """List all banks currently in the database."""
    return await mcp_call("list_banks", {})


@app.post("/rate")
async def get_rate(req: GetRateRequest):
    """
    Get FD rate for a specific bank and tenure.
    Body: { bank_name, days, deposit_category? }
    """
    return await mcp_call("get_rate", {
        "bank_name":        req.bank_name,
        "days":             req.days,
        "deposit_category": req.deposit_category,
    })


@app.post("/compare")
async def compare_banks(req: CompareBanksRequest):
    """
    Compare all banks for the same tenure.
    Body: { days, deposit_category? }
    Returns ranked list with general + senior rates.
    """
    return await mcp_call("compare_banks", {
        "days":             req.days,
        "deposit_category": req.deposit_category,
    })


@app.post("/best")
async def best_rate(req: BestRateRequest):
    """
    Top-3 banks for a tenure and citizen category.
    Body: { days, category?, deposit_category? }
    """
    return await mcp_call("best_rate", {
        "days":             req.days,
        "category":         req.category,
        "deposit_category": req.deposit_category,
    })


@app.post("/tenures")
async def list_tenures(req: ListTenuresRequest):
    """
    All tenure slabs for a given bank.
    Body: { bank_name, deposit_category? }
    """
    return await mcp_call("list_tenures", {
        "bank_name":        req.bank_name,
        "deposit_category": req.deposit_category,
    })


@app.post("/refresh")
async def refresh_data():
    """Re-scrape all bank websites and reload the database."""
    return await mcp_call("refresh_data", {})


@app.get("/health")
async def health():
    return {"status": "ok", "server": MCP_SERVER}


@app.post("/chat")
async def chat(req: ChatRequest):
    """
    Natural language chat interface.
    User sends a question → AI agent picks tools → returns conversational answer.
    Body: { query: str }
    Returns: { answer: str }
    """
    query = req.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    logger.info(f"[chat] Query: {query}")
    active = "gemini" if gemini_client else "groq"

    try:
        if active == "gemini":
            answer = await run_chat_turn_gemini(query)
        else:
            answer = await run_chat_turn_groq(query)

        logger.info(f"[chat/{active}] Answer: {answer[:100]}...")
        return {"answer": answer}

    except Exception as e:
        # Fallback to Groq on Gemini rate limit
        if ("429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)) and groq_client:
            logger.warning("[chat] Gemini rate limited, switching to Groq")
            try:
                answer = await run_chat_turn_groq(query)
                return {"answer": answer}
            except Exception as e2:
                logger.error(f"[chat] Groq also failed: {e2}")
                raise HTTPException(status_code=500, detail=str(e2))
        else:
            logger.error(f"[chat] Error: {e}")
            raise HTTPException(status_code=500, detail=str(e))


# ── Run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    logger.info("Starting FD Rate Bridge on http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)