"""
parser.py
Scrapes bank URLs with Playwright, parses HTML tables into FDRate objects.
Each bank has a dedicated parser since table structures differ.
"""

from datetime import datetime, timezone
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from schema import BankFDData, FDRate, normalize_tenure_label, parse_rate

# ── URL Registry ───────────────────────────────────────────────────────────────

BANK_URLS = {
    "SBI":   "https://sbi.co.in/web/interest-rates/deposit-rates/retail-domestic-term-deposits",
    "ICICI": "https://www.icicibank.com/personal-banking/deposits/fixed-deposit/fd-interest-rates",
    "Kotak": "https://www.kotak.com/en/personal-banking/deposits/fixed-deposit/fixed-deposit-interest-rate.html",
}


# ── Scraper ────────────────────────────────────────────────────────────────────

def scrape_html(url: str) -> str:
    """Return full page HTML after JS render using Playwright."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="networkidle", timeout=30000)
        html = page.content()
        browser.close()
    return html


def get_tables(html: str) -> list:
    """Return all BeautifulSoup table elements from page HTML."""
    soup = BeautifulSoup(html, "html.parser")
    return soup.find_all("table")


def preceding_heading(table) -> str:
    """Walk backwards from a table tag to find the nearest h1-h4."""
    el = table.find_previous_sibling()
    while el:
        if el.name in ("h1", "h2", "h3", "h4"):
            return el.get_text(strip=True)
        el = el.find_previous_sibling()
    return ""


# ── SBI Parser ─────────────────────────────────────────────────────────────────

def parse_sbi(html: str) -> BankFDData:
    """
    SBI Table 1: Retail rates — columns are:
      Tenors | Existing Public | Revised Public | Existing Senior | Revised Senior
    We take the REVISED columns (latest rates).

    SBI Table 2: Non-callable retail (>1cr) — different structure, handled separately.
    """
    tables = get_tables(html)
    bank = BankFDData(
        bank_name="SBI",
        source_url=BANK_URLS["SBI"],
        scraped_at=datetime.now(timezone.utc).isoformat(),
    )

    for tbl in tables:
        rows = tbl.find_all("tr")
        if not rows:
            continue

        # Detect header row
        headers = [th.get_text(strip=True).lower() for th in rows[0].find_all(["th", "td"])]
        header_text = " ".join(headers)

        # ── Table 1: Retail card rates ──
        if "revised rates for public" in header_text or "revised rates for senior" in header_text:
            # Find column indices dynamically
            col_pub = col_sen = col_tenor = None
            for i, h in enumerate(headers):
                if "tenor" in h:
                    col_tenor = i
                if "revised" in h and "public" in h:
                    col_pub = i
                if "revised" in h and "senior" in h:
                    col_sen = i

            if col_tenor is None:
                col_tenor = 0
            if col_pub is None:
                col_pub = 2
            if col_sen is None:
                col_sen = 4

            for row in rows[1:]:
                cells = row.find_all(["td", "th"])
                if len(cells) < max(col_pub, col_sen) + 1:
                    continue
                tenure_raw = cells[col_tenor].get_text(strip=True)
                if not tenure_raw or tenure_raw.lower() in ("tenors", "tenor"):
                    continue
                min_d, max_d = normalize_tenure_label(tenure_raw)
                rate = FDRate(
                    tenure_label=tenure_raw,
                    min_days=min_d,
                    max_days=max_d,
                    general_rate=parse_rate(cells[col_pub].get_text(strip=True)),
                    senior_rate=parse_rate(cells[col_sen].get_text(strip=True)),
                    deposit_category="retail",
                )
                bank.rates.append(rate)

        # ── Table 2: Non-callable (1.01cr–3cr) ──
        elif "non-callable" in header_text or "non-callable" in preceding_heading(tbl).lower():
            for row in rows[1:]:
                cells = row.find_all(["td", "th"])
                if len(cells) < 3:
                    continue
                tenure_raw = cells[0].get_text(strip=True)
                if not tenure_raw or "tenor" in tenure_raw.lower():
                    continue
                min_d, max_d = normalize_tenure_label(tenure_raw)
                rate = FDRate(
                    tenure_label=tenure_raw,
                    min_days=min_d,
                    max_days=max_d,
                    general_rate=parse_rate(cells[2].get_text(strip=True)) if len(cells) > 2 else None,
                    senior_rate=parse_rate(cells[3].get_text(strip=True)) if len(cells) > 3 else None,
                    deposit_category="non_callable",
                    deposit_min_cr=1.01,
                    deposit_max_cr=3.0,
                )
                bank.rates.append(rate)

    return bank


# ── ICICI Parser ───────────────────────────────────────────────────────────────

def parse_icici(html: str) -> BankFDData:
    """
    ICICI Table 1 (class hidewp): Retail FD rates
      Tenure | General Citizen | Senior Citizen
    We skip penalty/TDS tables (no rate % in column 2).
    """
    tables = get_tables(html)
    bank = BankFDData(
        bank_name="ICICI",
        source_url=BANK_URLS["ICICI"],
        scraped_at=datetime.now(timezone.utc).isoformat(),
    )

    for tbl in tables:
        # Only the main rate table has class "hidewp"
        cls = " ".join(tbl.get("class", []))
        rows = tbl.find_all("tr")
        if len(rows) < 3:
            continue

        # Check if this is a rate table by looking at headers
        all_text = tbl.get_text(" ").lower()
        if "general citizen" not in all_text and "general" not in all_text:
            continue
        if "penalty" in all_text and "general citizen" not in all_text:
            continue

        is_tax_saver_table = "tax saver" in all_text

        for row in rows:
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            tenure_raw = cells[0].get_text(" ", strip=True)
            if not tenure_raw or tenure_raw.lower() in ("tenure", ""):
                continue
            # Skip header rows
            if cells[0].name == "th" and len(cells) > 1 and cells[1].name == "th":
                continue

            gen_raw = cells[1].get_text(strip=True) if len(cells) > 1 else ""
            sen_raw = cells[2].get_text(strip=True) if len(cells) > 2 else ""
            gen = parse_rate(gen_raw)
            sen = parse_rate(sen_raw)
            if gen is None and sen is None:
                continue

            min_d, max_d = normalize_tenure_label(tenure_raw)
            is_ts = "tax saver" in tenure_raw.lower()

            rate = FDRate(
                tenure_label=tenure_raw,
                min_days=min_d,
                max_days=max_d,
                general_rate=gen,
                senior_rate=sen,
                deposit_category="retail",
                is_tax_saver=is_ts,
            )
            bank.rates.append(rate)

    return bank


# ── Kotak Parser ───────────────────────────────────────────────────────────────

def parse_kotak(html: str) -> BankFDData:
    """
    Kotak Table 1: Retail (<3cr) — columns:
      Tenure | Regular <3cr | Regular 3–5cr | Senior <3cr | Senior 3–5cr

    Kotak Table 2: Bulk rates (5cr+) — multiple deposit slabs per row.
    Kotak Table 3: Non-callable bulk.

    We parse Table 1 as retail, Table 2 as bulk.
    """
    tables = get_tables(html)
    bank = BankFDData(
        bank_name="Kotak",
        source_url=BANK_URLS["Kotak"],
        scraped_at=datetime.now(timezone.utc).isoformat(),
    )

    for tbl in tables:
        rows = tbl.find_all("tr")
        if len(rows) < 3:
            continue

        all_text = tbl.get_text(" ").lower()

        # Skip penalty/TDS tables
        if "penalty" in all_text or "tax rate" in all_text:
            continue

        # Detect table type from header caption row
        header_row = rows[0].get_text(" ").lower() if rows else ""
        is_non_callable = "premature withdrawal not allowed" in all_text
        is_bulk = "5 crore" in all_text or "10 crore" in all_text

        # Identify column layout from the header rows
        # Row 0 = caption, Row 1 = category labels, Row 2 = sub-labels (deposit sizes)
        # Data starts at row 3

        if "regular" in all_text and "senior citizen" in all_text and not is_bulk:
            # ── Retail table (<3cr, 3–5cr) ──
            deposit_cat = "non_callable" if is_non_callable else "retail"
            for row in rows[3:]:
                cells = row.find_all(["td", "th"])
                if len(cells) < 3:
                    continue
                tenure_raw = cells[0].get_text(strip=True)
                if not tenure_raw or "maturity" in tenure_raw.lower():
                    continue
                min_d, max_d = normalize_tenure_label(tenure_raw)
                # col1=regular<3cr, col2=regular3-5cr, col3=senior<3cr, col4=senior3-5cr
                rate = FDRate(
                    tenure_label=tenure_raw,
                    min_days=min_d,
                    max_days=max_d,
                    general_rate=parse_rate(cells[1].get_text(strip=True)),
                    senior_rate=parse_rate(cells[3].get_text(strip=True)) if len(cells) > 3 else None,
                    deposit_category=deposit_cat,
                    deposit_max_cr=3.0,
                )
                bank.rates.append(rate)

        elif is_bulk and not is_non_callable:
            # ── Bulk table (5cr+) — take first bulk slab (5–10cr) as representative ──
            for row in rows[2:]:
                cells = row.find_all(["td", "th"])
                if len(cells) < 2:
                    continue
                tenure_raw = cells[0].get_text(strip=True)
                if not tenure_raw or "maturity" in tenure_raw.lower():
                    continue
                min_d, max_d = normalize_tenure_label(tenure_raw)
                rate = FDRate(
                    tenure_label=tenure_raw,
                    min_days=min_d,
                    max_days=max_d,
                    general_rate=parse_rate(cells[1].get_text(strip=True)),
                    deposit_category="bulk",
                    deposit_min_cr=5.0,
                )
                bank.rates.append(rate)

    return bank


# ── Master Scrape & Parse ──────────────────────────────────────────────────────

PARSERS = {
    "SBI":   parse_sbi,
    "ICICI": parse_icici,
    "Kotak": parse_kotak,
}

def scrape_all(banks: list[str] = None) -> list[BankFDData]:
    """
    Scrape and parse all (or selected) banks.
    Returns list of BankFDData objects.
    """
    targets = banks or list(BANK_URLS.keys())
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        for name in targets:
            url = BANK_URLS[name]
            print(f"[parser] Scraping {name} from {url} ...")
            try:
                page.goto(url, wait_until="networkidle", timeout=30000)
                html = page.content()
                data = PARSERS[name](html)
                print(f"[parser] {name}: {len(data.rates)} rate slabs extracted.")
                results.append(data)
            except Exception as e:
                print(f"[parser] ERROR scraping {name}: {e}")
        browser.close()
    return results


if __name__ == "__main__":
    from schema import save_to_json
    banks = scrape_all()
    save_to_json(banks)