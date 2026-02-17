"""
db.py
SQLite persistence for FD rate data.
Schema is intentionally flat so MCP tools can query it with simple SQL.

Tables:
    banks        — one row per bank per scrape session
    fd_rates     — one row per tenure slab
"""

import sqlite3
from datetime import datetime, timezone
from schema import BankFDData, FDRate

DB_PATH = "fd_rates.db"


# ── DDL ────────────────────────────────────────────────────────────────────────

DDL = """
CREATE TABLE IF NOT EXISTS banks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    bank_name       TEXT NOT NULL,
    source_url      TEXT,
    scraped_at      TEXT NOT NULL,
    effective_date  TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS fd_rates (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    bank_id             INTEGER NOT NULL REFERENCES banks(id),
    bank_name           TEXT NOT NULL,
    tenure_label        TEXT NOT NULL,
    min_days            INTEGER NOT NULL,
    max_days            INTEGER NOT NULL,
    general_rate        REAL,
    senior_rate         REAL,
    deposit_category    TEXT NOT NULL DEFAULT 'retail',
    deposit_min_cr      REAL,
    deposit_max_cr      REAL,
    is_tax_saver        INTEGER NOT NULL DEFAULT 0,
    notes               TEXT DEFAULT '',
    scraped_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_fd_bank      ON fd_rates(bank_name);
CREATE INDEX IF NOT EXISTS idx_fd_days      ON fd_rates(min_days, max_days);
CREATE INDEX IF NOT EXISTS idx_fd_category  ON fd_rates(deposit_category);
CREATE INDEX IF NOT EXISTS idx_fd_scraped   ON fd_rates(scraped_at);
"""


def get_conn(path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row          # rows accessible as dicts
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path: str = DB_PATH) -> None:
    with get_conn(path) as conn:
        conn.executescript(DDL)
    print(f"[db] Initialized database at {path}")


# ── Write ──────────────────────────────────────────────────────────────────────

def upsert_bank_data(bank: BankFDData, path: str = DB_PATH) -> None:
    """
    Insert a fresh scrape. Old rows for the same bank are NOT deleted —
    this preserves history. MCP tools always query the LATEST scraped_at.
    """
    with get_conn(path) as conn:
        cur = conn.execute(
            "INSERT INTO banks (bank_name, source_url, scraped_at, effective_date) VALUES (?,?,?,?)",
            (bank.bank_name, bank.source_url, bank.scraped_at, bank.effective_date),
        )
        bank_id = cur.lastrowid

        rows = [
            (
                bank_id,
                bank.bank_name,
                r.tenure_label,
                r.min_days,
                r.max_days,
                r.general_rate,
                r.senior_rate,
                r.deposit_category,
                r.deposit_min_cr,
                r.deposit_max_cr,
                int(r.is_tax_saver),
                r.notes,
                bank.scraped_at,
            )
            for r in bank.rates
        ]
        conn.executemany(
            """INSERT INTO fd_rates
               (bank_id, bank_name, tenure_label, min_days, max_days,
                general_rate, senior_rate, deposit_category,
                deposit_min_cr, deposit_max_cr, is_tax_saver, notes, scraped_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
    print(f"[db] Upserted {len(bank.rates)} rates for {bank.bank_name}")


def save_all(banks: list[BankFDData], path: str = DB_PATH) -> None:
    init_db(path)
    for b in banks:
        upsert_bank_data(b, path)


# ── Read Helpers ───────────────────────────────────────────────────────────────

def _latest_scraped_at(conn: sqlite3.Connection) -> dict[str, str]:
    """Return {bank_name: latest_scraped_at} for all banks."""
    rows = conn.execute(
        "SELECT bank_name, MAX(scraped_at) as ts FROM fd_rates GROUP BY bank_name"
    ).fetchall()
    return {r["bank_name"]: r["ts"] for r in rows}


def query_rates(
    days: int,
    category: str = "general",          # "general" | "senior"
    deposit_category: str = "retail",
    bank_name: str = None,
    path: str = DB_PATH,
) -> list[dict]:
    """
    Return rate rows where the tenure slab covers `days`.
    Only returns the latest scraped data per bank.
    """
    col = "general_rate" if category == "general" else "senior_rate"
    with get_conn(path) as conn:
        latest = _latest_scraped_at(conn)
        results = []
        banks_to_query = [bank_name] if bank_name else list(latest.keys())
        for bn in banks_to_query:
            ts = latest.get(bn)
            if not ts:
                continue
            rows = conn.execute(
                f"""SELECT * FROM fd_rates
                    WHERE bank_name=? AND scraped_at=?
                    AND deposit_category=?
                    AND min_days<=? AND max_days>=?
                    AND {col} IS NOT NULL
                    ORDER BY (max_days - min_days) ASC""",
                (bn, ts, deposit_category, days, days),
            ).fetchall()
            results.extend([dict(r) for r in rows])
    return results


def query_best_rate(
    days: int,
    category: str = "general",
    deposit_category: str = "retail",
    path: str = DB_PATH,
) -> list[dict]:
    """Return top-3 rates for a given tenure across all banks, sorted desc."""
    col = "general_rate" if category == "general" else "senior_rate"
    rows = query_rates(days, category, deposit_category, path=path)
    rows = [r for r in rows if r.get(col) is not None]
    rows.sort(key=lambda r: r[col], reverse=True)
    return rows[:3]


def query_all_tenures(bank_name: str, deposit_category: str = "retail", path: str = DB_PATH) -> list[dict]:
    """Return all tenure slabs for a given bank (latest scrape)."""
    with get_conn(path) as conn:
        latest = _latest_scraped_at(conn)
        ts = latest.get(bank_name)
        if not ts:
            return []
        rows = conn.execute(
            """SELECT tenure_label, min_days, max_days, general_rate, senior_rate
               FROM fd_rates
               WHERE bank_name=? AND scraped_at=? AND deposit_category=?
               ORDER BY min_days ASC""",
            (bank_name, ts, deposit_category),
        ).fetchall()
        return [dict(r) for r in rows]


def query_compare(
    days: int,
    category: str = "general",
    deposit_category: str = "retail",
    path: str = DB_PATH,
) -> list[dict]:
    """Compare all banks for the same tenor. Returns one row per bank."""
    col = "general_rate" if category == "general" else "senior_rate"
    rows = query_rates(days, category, deposit_category, path=path)
    # one best row per bank
    seen = {}
    for r in rows:
        bn = r["bank_name"]
        if bn not in seen or (r[col] or 0) > (seen[bn][col] or 0):
            seen[bn] = r
    result = list(seen.values())
    result.sort(key=lambda r: r.get(col) or 0, reverse=True)
    return result


def list_banks(path: str = DB_PATH) -> list[str]:
    with get_conn(path) as conn:
        rows = conn.execute("SELECT DISTINCT bank_name FROM fd_rates").fetchall()
        return [r["bank_name"] for r in rows]