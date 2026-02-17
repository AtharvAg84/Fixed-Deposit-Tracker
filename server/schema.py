"""
schema.py
Universal FD Rate Schema — normalized, bank-agnostic data model.
All rates stored as floats (e.g. 6.5 not "6.5%").
Tenures normalized to (min_days, max_days) integer ranges.
"""

from dataclasses import dataclass, field, asdict
from typing import Optional
import json


# ── Tenure Normalization ───────────────────────────────────────────────────────

TENURE_ALIASES = {
    "day": 1, "days": 1,
    "month": 30, "months": 30,
    "year": 365, "years": 365,
}

def parse_tenure_to_days(text: str) -> Optional[int]:
    """
    Convert a human tenure string to days.
    Examples:
        "1 year"         -> 365
        "18 months"      -> 540
        "45 days"        -> 45
        "2 years"        -> 730
    Returns None if unparseable.
    """
    import re
    text = text.strip().lower()
    m = re.match(r"(\d+(?:\.\d+)?)\s*(day|days|month|months|year|years)", text)
    if not m:
        return None
    val = float(m.group(1))
    unit = m.group(2)
    return int(val * TENURE_ALIASES[unit])


def normalize_tenure_label(raw: str) -> tuple[int, int]:
    """
    Parse a tenure range string into (min_days, max_days).
    Handles patterns like:
        "7 days to 45 days"
        "1 year to less than 2 years"
        "2 years to less than 3 years"
        "5 years and up to 10 years"
        "46 to 90 Days"
        "365 Days to less than 15 Months"
        "15 Months - less than 18 Months"
        "18 months - less than 2 years"
    Returns (min_days, max_days). max_days = min_days for single-point tenures.
    """
    import re
    raw = raw.strip()

    # Single-point tenures like "91 Days", "180 Days"
    sp = re.match(r"^(\d+)\s*(day|days|month|months|year|years)$", raw, re.I)
    if sp:
        d = parse_tenure_to_days(raw)
        return (d, d)

    # Split on separators: "to less than", "and up to", " - ", " to "
    for sep in [r"\s+to\s+less\s+than\s+", r"\s+and\s+(?:up\s+)?to\s+", r"\s+-\s+less\s+than\s+", r"\s+-\s+", r"\s+to\s+"]:
        parts = re.split(sep, raw, maxsplit=1, flags=re.I)
        if len(parts) == 2:
            lo = parse_tenure_to_days(parts[0].strip())
            hi = parse_tenure_to_days(parts[1].strip())
            if lo and hi:
                return (lo, hi)
            elif lo:
                # "less than" side — hi = lo - 1
                return (lo, lo)

    # Fallback: grab first number+unit
    m = re.search(r"(\d+)\s*(day|days|month|months|year|years)", raw, re.I)
    if m:
        d = parse_tenure_to_days(m.group(0))
        return (d, d)

    return (0, 0)  # unparseable sentinel


# ── Core Data Classes ──────────────────────────────────────────────────────────

@dataclass
class FDRate:
    """A single FD rate entry for one tenure slab."""
    tenure_label: str           # raw label, e.g. "1 Year to less than 2 years"
    min_days: int               # normalized lower bound
    max_days: int               # normalized upper bound
    general_rate: Optional[float] = None    # % p.a. for general/regular citizens
    senior_rate: Optional[float] = None     # % p.a. for senior citizens
    deposit_category: str = "retail"        # "retail" | "non_callable" | "bulk"
    deposit_min_cr: Optional[float] = None  # minimum deposit in crores (None = no min)
    deposit_max_cr: Optional[float] = None  # maximum deposit in crores (None = no limit)
    is_tax_saver: bool = False
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BankFDData:
    """All FD rates for a single bank."""
    bank_name: str              # "SBI" | "ICICI" | "Kotak"
    source_url: str
    scraped_at: str             # ISO timestamp
    effective_date: str = ""    # e.g. "15/12/2025" if mentioned on page
    rates: list[FDRate] = field(default_factory=list)

    def get_rate_for_days(
        self,
        days: int,
        category: str = "general",       # "general" | "senior"
        deposit_category: str = "retail"
    ) -> Optional[FDRate]:
        """Find the best matching rate slab for a given number of days."""
        matches = [
            r for r in self.rates
            if r.min_days <= days <= r.max_days
            and r.deposit_category == deposit_category
        ]
        if not matches:
            return None
        # Prefer narrowest slab
        matches.sort(key=lambda r: r.max_days - r.min_days)
        return matches[0]

    def to_dict(self) -> dict:
        return {
            "bank_name": self.bank_name,
            "source_url": self.source_url,
            "scraped_at": self.scraped_at,
            "effective_date": self.effective_date,
            "rates": [r.to_dict() for r in self.rates],
        }


# ── Rate Parsing Helpers ───────────────────────────────────────────────────────

def parse_rate(raw: str) -> Optional[float]:
    """
    Extract float rate from a raw cell string.
    "6.50%"  -> 6.5
    "7.05*"  -> 7.05
    "NA"     -> None
    "&nbsp;" -> None
    """
    import re
    if not raw:
        return None
    raw = raw.replace("\xa0", "").replace("%", "").replace("*", "").strip()
    if raw.lower() in ("na", "n/a", "-", ""):
        return None
    m = re.search(r"\d+(?:\.\d+)?", raw)
    return float(m.group()) if m else None


# ── JSON Storage ───────────────────────────────────────────────────────────────

def save_to_json(banks: list[BankFDData], path: str = "fd_data.json") -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump([b.to_dict() for b in banks], f, indent=2)
    print(f"[schema] Saved {len(banks)} banks -> {path}")


def load_from_json(path: str = "fd_data.json") -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)