"""
mcp_server.py
FastMCP Server for FD Rate Comparison.

On startup:
  1. Scrapes all bank URLs with Playwright
  2. Parses HTML → FDRate objects
  3. Persists to SQLite (fd_rates.db) + backup JSON (fd_data.json)
  4. Exposes FastMCP tools for querying

Run:
    python mcp_server.py
"""

import json
import logging
import os
from fastmcp import FastMCP
from dotenv import load_dotenv

# NOTE: If you use Gemini anywhere, use the NEW package:
#   pip install google-genai
#   from google import genai                    ← new
#   client = genai.Client(api_key=API_KEY)
#   client.models.generate_content(...)
# NOT the old deprecated package:
#   import google.generativeai as genai         ← deprecated, causes FutureWarning

import db
import parser as fd_parser
from schema import save_to_json

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

load_dotenv()

# ── FastMCP Init ───────────────────────────────────────────────────────────────
try:
    mcp = FastMCP("FD Rate Comparison Server")
    logger.info("FastMCP server initialized: FD Rate Comparison Server")
except Exception as e:
    logger.error(f"Failed to initialize FastMCP: {e}")
    raise


# ── Bootstrap: scrape → parse → persist ───────────────────────────────────────

def bootstrap():
    """Scrape all banks, parse, and store to SQLite + JSON on server start."""
    logger.info("[bootstrap] Starting data scrape...")
    try:
        banks = fd_parser.scrape_all()
        db.save_all(banks)
        save_to_json(banks, "fd_data.json")
        total = sum(len(b.rates) for b in banks)
        logger.info(f"[bootstrap] Complete — {total} rate slabs loaded across {len(banks)} banks.")
    except Exception as e:
        logger.error(f"[bootstrap] FAILED: {e}")
        raise

bootstrap()  # runs once at import/startup


# ── Helper: safe JSON response ─────────────────────────────────────────────────

def ok(payload: dict) -> dict:
    return {"status": "success", **payload}

def err(message: str) -> dict:
    return {"status": "error", "error": message}


# ── Tools ──────────────────────────────────────────────────────────────────────

@mcp.tool()
def list_banks() -> dict:
    """
    List all banks currently loaded in the FD rate database.

    Returns:
        dict: { status, banks: [str], count: int }
    """
    logger.info("[tool] list_banks called")
    try:
        banks = db.list_banks()
        logger.info(f"[tool] list_banks → {banks}")
        return ok({"banks": banks, "count": len(banks)})
    except Exception as e:
        logger.error(f"[tool] list_banks error: {e}")
        return err(str(e))


@mcp.tool()
def get_rate(bank_name: str, days: int, deposit_category: str = "retail") -> dict:
    """
    Get the FD interest rate for a specific bank and tenure.

    Args:
        bank_name (str):         Bank name — SBI, ICICI, or Kotak.
        days (int):              Tenure in days (e.g. 365 = 1 year, 180 = 6 months).
        deposit_category (str):  "retail" | "non_callable" | "bulk". Default: retail.

    Returns:
        dict: { status, bank, tenure_label, days_range,
                general_rate, senior_rate, deposit_category, scraped_at }
    """
    logger.info(f"[tool] get_rate called: bank={bank_name}, days={days}, cat={deposit_category}")
    try:
        gen_rows = db.query_rates(days, "general", deposit_category, bank_name=bank_name)
        sen_rows = db.query_rates(days, "senior",  deposit_category, bank_name=bank_name)

        if not gen_rows and not sen_rows:
            msg = f"No rate found for {bank_name} at {days} days ({deposit_category})"
            logger.warning(f"[tool] get_rate: {msg}")
            return err(msg)

        row = (gen_rows or sen_rows)[0]
        result = ok({
            "bank":             bank_name,
            "tenure_label":     row["tenure_label"],
            "days_range":       f"{row['min_days']}–{row['max_days']}",
            "general_rate":     row.get("general_rate"),
            "senior_rate":      row.get("senior_rate"),
            "deposit_category": deposit_category,
            "scraped_at":       row["scraped_at"],
        })
        logger.info(f"[tool] get_rate → general={result.get('general_rate')}%, senior={result.get('senior_rate')}%")
        return result
    except Exception as e:
        logger.error(f"[tool] get_rate error: {e}")
        return err(str(e))


@mcp.tool()
def compare_banks(days: int, deposit_category: str = "retail") -> dict:
    """
    Compare FD rates across all banks for the same tenure, sorted best-first.

    Args:
        days (int):              Tenure in days.
        deposit_category (str):  "retail" | "non_callable" | "bulk". Default: retail.

    Returns:
        dict: { status, query_days, deposit_category,
                comparison: [{bank, tenure_label, general_rate, senior_rate}],
                best_general, best_senior }
    """
    logger.info(f"[tool] compare_banks called: days={days}, cat={deposit_category}")
    try:
        rows = db.query_compare(days, "general", deposit_category)
        comparison = [
            {
                "bank":         r["bank_name"],
                "tenure_label": r["tenure_label"],
                "general_rate": r.get("general_rate"),
                "senior_rate":  r.get("senior_rate"),
            }
            for r in rows
        ]
        # Best senior
        sen_sorted = sorted(
            [c for c in comparison if c["senior_rate"] is not None],
            key=lambda x: x["senior_rate"], reverse=True
        )
        result = ok({
            "query_days":       days,
            "deposit_category": deposit_category,
            "comparison":       comparison,
            "best_general":     comparison[0]["bank"] if comparison else None,
            "best_senior":      sen_sorted[0]["bank"] if sen_sorted else None,
        })
        logger.info(f"[tool] compare_banks → {len(comparison)} banks, best_general={result.get('best_general')}")
        return result
    except Exception as e:
        logger.error(f"[tool] compare_banks error: {e}")
        return err(str(e))


@mcp.tool()
def best_rate(days: int, category: str = "general", deposit_category: str = "retail") -> dict:
    """
    Find the top-3 banks offering the highest FD rate for a given tenure.

    Args:
        days (int):              Tenure in days.
        category (str):          "general" | "senior". Default: general.
        deposit_category (str):  "retail" | "non_callable" | "bulk". Default: retail.

    Returns:
        dict: { status, query_days, category, deposit_category,
                top_banks: [{rank, bank, rate, tenure_label}] }
    """
    logger.info(f"[tool] best_rate called: days={days}, cat={category}, dep={deposit_category}")
    try:
        rows = db.query_best_rate(days, category, deposit_category)
        col  = f"{category}_rate"
        top  = [
            {
                "rank":         i + 1,
                "bank":         r["bank_name"],
                "rate":         r.get(col),
                "tenure_label": r["tenure_label"],
            }
            for i, r in enumerate(rows)
        ]
        result = ok({
            "query_days":       days,
            "category":         category,
            "deposit_category": deposit_category,
            "top_banks":        top,
        })
        logger.info(f"[tool] best_rate → top bank: {top[0] if top else 'none'}")
        return result
    except Exception as e:
        logger.error(f"[tool] best_rate error: {e}")
        return err(str(e))


@mcp.tool()
def list_tenures(bank_name: str, deposit_category: str = "retail") -> dict:
    """
    List all tenure slabs available for a given bank with their rates.

    Args:
        bank_name (str):         Bank name — SBI, ICICI, or Kotak.
        deposit_category (str):  "retail" | "non_callable" | "bulk". Default: retail.

    Returns:
        dict: { status, bank, deposit_category, tenure_count, tenures: [...] }
    """
    logger.info(f"[tool] list_tenures called: bank={bank_name}, cat={deposit_category}")
    try:
        tenures = db.query_all_tenures(bank_name, deposit_category)
        if not tenures:
            msg = f"No tenures found for {bank_name} ({deposit_category})"
            logger.warning(f"[tool] list_tenures: {msg}")
            return err(msg)
        result = ok({
            "bank":             bank_name,
            "deposit_category": deposit_category,
            "tenure_count":     len(tenures),
            "tenures":          tenures,
        })
        logger.info(f"[tool] list_tenures → {len(tenures)} slabs for {bank_name}")
        return result
    except Exception as e:
        logger.error(f"[tool] list_tenures error: {e}")
        return err(str(e))


@mcp.tool()
def refresh_data() -> dict:
    """
    Re-scrape all bank websites and reload the database with fresh rate data.
    Use this when rates may have changed since server start.

    Returns:
        dict: { status, banks: [str], refreshed_at }
    """
    logger.info("[tool] refresh_data called")
    try:
        bootstrap()
        from datetime import datetime, timezone
        banks = db.list_banks()
        result = ok({
            "banks":        banks,
            "refreshed_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.info(f"[tool] refresh_data complete: {banks}")
        return result
    except Exception as e:
        logger.error(f"[tool] refresh_data error: {e}")
        return err(str(e))


# ── Entrypoint ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        logger.info("Starting FastMCP FD Rate server with stdio transport")
        mcp.run(transport="stdio")
        logger.info("FastMCP server started successfully")
    except Exception as e:
        logger.error(f"Failed to start server: {e}")
        raise