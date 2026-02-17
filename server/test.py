from playwright.sync_api import sync_playwright
from urllib.parse import urlparse

urls = [
    "https://sbi.bank.in/web/interest-rates/deposit-rates/retail-domestic-term-deposits",
    "https://www.icici.bank.in/personal-banking/deposits/fixed-deposit/fd-interest-rates",
    "https://www.kotak.bank.in/en/personal-banking/deposits/fixed-deposit/fixed-deposit-interest-rate.html"
]

def get_bank_name(url):
    """Extract bank name from the URL (e.g., 'sbi.bank.in' -> 'SBI')"""
    domain = urlparse(url).netloc
    if "sbi" in domain.lower():
        return "SBI"
    elif "icici" in domain.lower():
        return "ICICI"
    elif "kotak" in domain.lower():
        return "Kotak"
    else:
        return domain.split('.')[0].capitalize()

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()

    for i, url in enumerate(urls, start=1):
        page.goto(url, wait_until="networkidle")

        tables = page.locator("table")
        table_count = tables.count()

        bank_name = get_bank_name(url)
        filtered_html = f"<html><body><h1>{bank_name}</h1><hr>"

        for t in range(table_count):
            table = tables.nth(t)

            # Get table HTML
            table_html = table.evaluate("el => el.outerHTML")

            # Try to get nearest previous heading
            heading_text = table.evaluate("""
                el => {
                    let prev = el.previousElementSibling;
                    while (prev) {
                        if (['H1','H2','H3','H4'].includes(prev.tagName)) {
                            return prev.outerHTML;
                        }
                        prev = prev.previousElementSibling;
                    }
                    return null;
                }
            """)

            if heading_text:
                filtered_html += heading_text

            filtered_html += table_html + "<br><br>"

        filtered_html += "</body></html>"

        filename = f"filtered_output_{i}.html"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(filtered_html)

        print(f"Saved filtered table data -> {filename}")

    browser.close()

print("All filtered HTML files saved successfully.")
