# FD Rate Tracker — MCP + FastAPI + React

Live Fixed Deposit rate comparison across Indian banks (SBI, ICICI, Kotak),
powered by a FastMCP server, FastAPI bridge, and React frontend.

---

## Project Structure

```
fd-tracker/
│
├── server/                        # Python backend
│   ├── schema.py                  # Universal FD data model + tenure normalizer
│   ├── parser.py                  # Playwright scraper + per-bank HTML parsers
│   ├── db.py                      # SQLite read/write layer
│   ├── mcp_server.py              # FastMCP server (tools: get_rate, compare, best, list)
│   ├── mcp_client.py              # CLI agent client (Gemini → Groq fallback)
│   ├── bridge.py                  # FastAPI REST bridge for React ← YOU ARE HERE
│   ├── fd_rates.db                # Auto-created on first run (SQLite)
│   ├── fd_data.json               # Auto-created on first run (backup)
│   └── .env                       # API keys (never commit this)
│
└── client/                        # React frontend
    ├── src/
    │   ├── App.jsx                # Main app — tabs, views, API calls
    │   └── index.css              # Minimal styles
    ├── package.json
    └── vite.config.js
```

---

## Architecture

```
React (localhost:5173)
    │  HTTP POST/GET
    ▼
bridge.py — FastAPI (localhost:8000)
    │  stdio (spawns subprocess)
    ▼
mcp_server.py — FastMCP
    │
    ├── parser.py (Playwright scrapes bank URLs on startup)
    └── db.py (SQLite — fd_rates.db)
```

---

## Setup & Run

### 1. Server

```bash
cd server
pip install fastmcp playwright beautifulsoup4 fastapi uvicorn python-dotenv groq google-genai
playwright install chromium
```

Create `.env`:
```
GEMINI_API_KEY=AIza...
GROQ_API_KEY=gsk_...
```

Start the bridge (it spawns mcp_server automatically):
```bash
python bridge.py
```

> First run takes ~60s while Playwright scrapes all bank URLs.

---

### 2. Client

```bash
cd client
npm install
npm install recharts
npm run dev
```

Open `http://localhost:5173`

---

## API Endpoints (bridge.py)

| Method | Endpoint    | Body                              | Description                  |
|--------|-------------|-----------------------------------|------------------------------|
| GET    | `/banks`    | —                                 | List loaded banks             |
| POST   | `/rate`     | `{bank_name, days, deposit_category?}` | Rate for one bank+tenure |
| POST   | `/compare`  | `{days, deposit_category?}`       | All banks side-by-side        |
| POST   | `/best`     | `{days, category?, deposit_category?}` | Top-3 banks ranked       |
| POST   | `/tenures`  | `{bank_name, deposit_category?}`  | All tenures for a bank        |
| POST   | `/refresh`  | —                                 | Re-scrape all banks           |
| GET    | `/health`   | —                                 | Health check                  |

---

## Adding a New Bank

To add a new bank (e.g. HDFC), make changes in **4 places only**:

### 1. `parser.py` — Add URL and parser function

```python
# Step 1: Add to BANK_URLS dict
BANK_URLS = {
    "SBI":   "...",
    "ICICI": "...",
    "Kotak": "...",
    "HDFC":  "https://www.hdfcbank.com/..."   # ← ADD HERE
}

# Step 2: Write a parser function
def parse_hdfc(html: str) -> BankFDData:
    tables = get_tables(html)
    bank = BankFDData(bank_name="HDFC", source_url=BANK_URLS["HDFC"], ...)
    # parse tables → append FDRate objects to bank.rates
    return bank

# Step 3: Register in PARSERS dict
PARSERS = {
    "SBI":   parse_sbi,
    "ICICI": parse_icici,
    "Kotak": parse_kotak,
    "HDFC":  parse_hdfc,    # ← ADD HERE
}
```

### 2. `client/src/App.jsx` — Add color for the new bank

```js
const COLORS = {
  SBI:   "#2563eb",
  ICICI: "#f59e0b",
  Kotak: "#10b981",
  HDFC:  "#ef4444",   // ← ADD HERE
};
```

That's it. `schema.py`, `db.py`, `mcp_server.py`, and `bridge.py` require
**zero changes** — they are fully bank-agnostic.

---

## CLI Agent (optional)

You can also query rates directly from the terminal without React:

```bash
cd server
python mcp_client.py
```

```
You: What is SBI's FD rate for 1 year?
You: Compare all banks for 2 years
You: Best rate for senior citizens for 6 months
```

---

## Tech Stack

| Layer      | Technology                        |
|------------|-----------------------------------|
| Scraping   | Playwright + BeautifulSoup4       |
| Storage    | SQLite (via db.py)                |
| MCP Server | FastMCP                           |
| AI Agent   | Gemini 2.0 Flash → Groq LLaMA 3.3 |
| API Bridge | FastAPI + Uvicorn                 |
| Frontend   | React + Vite + Recharts           |

---

## © 2026 FD-Tracker. All Rights Reserved.

All rights reserved. This project and its contents are protected by applicable copyright laws.  
Made with ❤️ by Atharv.
