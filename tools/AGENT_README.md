# BrickellQuant Tools — Agent Skill Guide

> **This file is the single source of truth for any agent using this library.**
> Read this first. Every module, function, and pattern is documented here.

---

## 📦 What This Is

A thin, opinionated Python wrapper library over best-in-class financial data sources.
Agents call clean functions. The library handles auth, rate limits, caching, and formatting.

```
tools/
├── AGENT_README.md          ← YOU ARE HERE (read first)
├── __init__.py              ← from tools import sec, market, news, utils
├── requirements.txt         ← pip install -r requirements.txt
│
├── sec/                     ← SEC EDGAR via edgartools
│   ├── sec_client.py        ← Main SEC interface
│   └── README.md            ← SEC-specific deep reference
│
├── market/                  ← Market data via yfinance
│   ├── market_client.py     ← Price, fundamentals, options
│   └── README.md            ← Market-specific deep reference
│
├── news/                    ← News via RSS + SEC filings feed
│   ├── news_client.py       ← News aggregation
│   └── README.md            ← News-specific deep reference
│
└── utils/                   ← Shared across all modules
    ├── formatters.py        ← Pretty print DataFrames, tables
    ├── cache.py             ← Simple TTL file cache
    └── types.py             ← Common dataclasses/TypedDicts
```

---

## ⚡ Quick Start (30 seconds)

```bash
pip install -r tools/requirements.txt
```

```python
import sys
sys.path.insert(0, "/home/rincon/BrickellQuant")

# One-liner imports
from tools.sec import SECClient
from tools.market import MarketClient
from tools.news import NewsClient

# Identity required by SEC EDGAR (just your email)
sec = SECClient(identity="agent@brickellquant.com")
mkt = MarketClient()
news = NewsClient()
```

---

## 🏗️ Module Reference

### 1. SEC Module (`tools/sec/sec_client.py`)

**Full deep reference →** `tools/sec/README.md`

#### Setup
```python
from tools.sec import SECClient
sec = SECClient(identity="your@email.com")
```

#### Core Functions

| Function | What It Does | Returns |
|---|---|---|
| `sec.company(ticker)` | Get Company object | `Company` |
| `sec.filings(ticker, form)` | Get filings list | `EntityFilings` |
| `sec.latest(ticker, form)` | Most recent filing | `Filing` |
| `sec.tenk(ticker)` | Latest 10-K | `TenK` |
| `sec.tenq(ticker)` | Latest 10-Q | `TenQ` |
| `sec.eightk(ticker)` | Latest 8-K | `EightK` |
| `sec.financials(ticker)` | Balance sheet, income, cash flow | `dict[DataFrame]` |
| `sec.insider_trades(ticker, days)` | Form 4 transactions | `DataFrame` |
| `sec.ownership(ticker)` | 13F/13D/13G holdings | `DataFrame` |
| `sec.search(query, form)` | Full-text EDGAR search | `list[Filing]` |
| `sec.dilution_snapshot(ticker)` | Share structure + dilution risk | `dict` |
| `sec.risk_factors(ticker)` | Parsed risk factor section | `list[str]` |
| `sec.red_flags(ticker)` | Auditor changes, restatements | `list[dict]` |

#### Quick Examples
```python
# Get Apple's latest 10-K financials
fins = sec.financials("AAPL")
print(fins["income_statement"])
print(fins["balance_sheet"])
print(fins["cash_flow"])

# Dilution check
d = sec.dilution_snapshot("TSLA")
print(f"Risk: {d['risk_level']} | Dilution: {d['total_dilution_pct']:.1f}%")

# Recent insider trades
df = sec.insider_trades("NVDA", days=90)
print(df[["date","insider","title","transaction","shares","value"]])

# Red flags
flags = sec.red_flags("GME")
for f in flags:
    print(f"⚠ {f['type']}: {f['description']}")
```

---

### 2. Market Module (`tools/market/market_client.py`)

**Full deep reference →** `tools/market/README.md`

#### Setup
```python
from tools.market import MarketClient
mkt = MarketClient()
```

#### Core Functions

| Function | What It Does | Returns |
|---|---|---|
| `mkt.price(ticker)` | Current price + basic stats | `dict` |
| `mkt.history(ticker, period, interval)` | OHLCV price history | `DataFrame` |
| `mkt.info(ticker)` | Full company metadata | `dict` |
| `mkt.fundamentals(ticker)` | Key financial ratios | `dict` |
| `mkt.income(ticker, quarterly)` | Income statement | `DataFrame` |
| `mkt.balance(ticker, quarterly)` | Balance sheet | `DataFrame` |
| `mkt.cashflow(ticker, quarterly)` | Cash flow statement | `DataFrame` |
| `mkt.options(ticker, expiry)` | Options chain | `dict[DataFrame]` |
| `mkt.holders(ticker)` | Institutional + insider holders | `dict` |
| `mkt.recommendations(ticker)` | Analyst recs | `DataFrame` |
| `mkt.calendar(ticker)` | Earnings/event calendar | `dict` |
| `mkt.compare(tickers, metric, period)` | Multi-ticker comparison | `DataFrame` |
| `mkt.screen(tickers, filters)` | Filter tickers by metrics | `DataFrame` |

#### Quick Examples
```python
# Current price
p = mkt.price("NVDA")
print(f"${p['price']:,.2f}  ({p['change_pct']:+.2f}%)")

# 1-year history
hist = mkt.history("AAPL", period="1y")
print(hist.tail())

# Key fundamentals
f = mkt.fundamentals("MSFT")
print(f"P/E: {f['pe_ratio']} | EV/EBITDA: {f['ev_ebitda']} | FCF Yield: {f['fcf_yield']:.2%}")

# Compare P/E ratios across basket
df = mkt.compare(["AAPL","MSFT","GOOGL","META"], metric="pe_ratio")
print(df.sort_values("pe_ratio"))

# Options chain
chain = mkt.options("SPY", expiry="nearest")
print(chain["calls"].head(10))
print(chain["puts"].head(10))
```

---

### 3. News Module (`tools/news/news_client.py`)

**Full deep reference →** `tools/news/README.md`

#### Setup
```python
from tools.news import NewsClient
news = NewsClient()
```

#### Core Functions

| Function | What It Does | Returns |
|---|---|---|
| `news.ticker_news(ticker, limit)` | News for a specific ticker | `list[dict]` |
| `news.sec_rss(form_type, limit)` | Live SEC EDGAR RSS filings | `list[dict]` |
| `news.sec_company_rss(ticker, limit)` | Company-specific SEC filings RSS | `list[dict]` |
| `news.market_headlines(limit)` | General market headlines | `list[dict]` |
| `news.search(query, sources, limit)` | Search across all sources | `list[dict]` |
| `news.summary(ticker, limit)` | Combined news + SEC for ticker | `dict` |

#### Quick Examples
```python
# News for ticker
articles = news.ticker_news("NVDA", limit=10)
for a in articles:
    print(f"[{a['source']}] {a['title']}  ({a['published']})")
    print(f"  → {a['url']}")

# Live SEC EDGAR 8-K filings feed
filings = news.sec_rss(form_type="8-K", limit=20)
for f in filings:
    print(f"{f['company']} filed {f['form_type']} — {f['published']}")

# Full ticker briefing
brief = news.summary("TSLA", limit=5)
print(f"Recent news: {len(brief['news'])} articles")
print(f"Recent filings: {len(brief['sec_filings'])} filings")
```

---

### 4. Utils (`tools/utils/`)

```python
from tools.utils.formatters import print_table, to_markdown, fmt_number
from tools.utils.cache import cached, clear_cache
from tools.utils.types import FilingResult, PriceQuote, NewsItem
```

| Utility | Function | Description |
|---|---|---|
| `formatters` | `print_table(df)` | Rich terminal table |
| `formatters` | `to_markdown(df)` | Markdown table string |
| `formatters` | `fmt_number(n)` | "1.23B", "450M", "12.3K" |
| `formatters` | `fmt_pct(n)` | "+12.3%" with color codes |
| `cache` | `@cached(ttl=300)` | Decorator, 5-min TTL |
| `cache` | `clear_cache()` | Wipe all cached results |
| `types` | `FilingResult` | TypedDict for filings |
| `types` | `PriceQuote` | TypedDict for prices |
| `types` | `NewsItem` | TypedDict for news |

---

## 🔁 Common Agent Workflows

### Workflow 1: Full Equity Research on a Ticker
```python
from tools.sec import SECClient
from tools.market import MarketClient
from tools.news import NewsClient

sec = SECClient(identity="agent@brickellquant.com")
mkt = MarketClient()
news = NewsClient()

TICKER = "NVDA"

# Step 1: Market snapshot
price = mkt.price(TICKER)
funds = mkt.fundamentals(TICKER)

# Step 2: SEC financials
fins = sec.financials(TICKER)
dilution = sec.dilution_snapshot(TICKER)
flags = sec.red_flags(TICKER)

# Step 3: Insider activity
insiders = sec.insider_trades(TICKER, days=90)

# Step 4: News briefing
brief = news.summary(TICKER, limit=10)

# Now synthesize and output
```

### Workflow 2: Screen for Dilution Risk
```python
from tools.sec import SECClient

sec = SECClient(identity="agent@brickellquant.com")

WATCHLIST = ["SOFI","LCID","RIVN","NKLA","BFLY"]
for ticker in WATCHLIST:
    d = sec.dilution_snapshot(ticker)
    print(f"{ticker:6s} | {d['risk_level']:8s} | {d['total_dilution_pct']:.1f}% dilution | {d['basic_shares_out']:.0f}M basic")
```

### Workflow 3: 8-K Alert Triage
```python
from tools.news import NewsClient
from tools.sec import SECClient

news = NewsClient()
sec = SECClient(identity="agent@brickellquant.com")

# Pull live 8-K feed
filings = news.sec_rss(form_type="8-K", limit=50)

CRITICAL_ITEMS = ["4.01", "4.02", "2.06"]  # auditor/restatement/impairment

for f in filings:
    ticker = f.get("ticker", "")
    if ticker and any(item in f.get("description","") for item in CRITICAL_ITEMS):
        print(f"🚨 CRITICAL: {ticker} — {f['title']}")
        flags = sec.red_flags(ticker)
        for flag in flags:
            print(f"   ⚠ {flag['type']}: {flag['description']}")
```

### Workflow 4: Insider Buy Signal Detection
```python
from tools.sec import SECClient
from tools.market import MarketClient

sec = SECClient(identity="agent@brickellquant.com")
mkt = MarketClient()

UNIVERSE = ["AAPL","MSFT","GOOGL","AMZN","META","NVDA","TSLA"]

for ticker in UNIVERSE:
    trades = sec.insider_trades(ticker, days=30)
    if trades.empty:
        continue
    
    buys = trades[trades["transaction"] == "Purchase"]
    c_suite = buys[buys["title"].str.contains("CEO|CFO|President", na=False)]
    
    if len(c_suite) > 0:
        total_value = c_suite["value"].sum()
        print(f"🟢 {ticker}: {len(c_suite)} C-suite buy(s), ${total_value:,.0f} total")
```

---

## 🚦 Rate Limits & Constraints

| Source | Limit | Notes |
|---|---|---|
| SEC EDGAR | 10 req/sec | edgartools handles this automatically |
| Yahoo Finance | Unofficial | Use `mkt.history()` not raw yfinance in loops |
| RSS Feeds | None | Cached for 5 min by default |
| Finnhub (optional) | 60 req/min free | Set `FINNHUB_API_KEY` env var |

---

## 🔑 Environment Variables

```bash
# Required for SEC EDGAR (your identity, not an API key)
export SEC_IDENTITY="yourname@youremail.com"

# Optional - enhances news module
export FINNHUB_API_KEY="your_key_here"
export NEWSAPI_KEY="your_key_here"
```

Or in Python:
```python
import os
os.environ["SEC_IDENTITY"] = "agent@brickellquant.com"
```

---

## 📚 Dependencies

```
edgartools>=2.0        # SEC EDGAR - github.com/dgunning/edgartools
yfinance>=0.2.38       # Yahoo Finance market data
feedparser>=6.0        # RSS feed parsing
pandas>=2.0            # DataFrames everywhere
requests>=2.28         # HTTP calls
rich>=13.0             # Terminal formatting
python-dateutil>=2.8   # Date parsing
pyarrow>=14.0          # Fast XBRL parsing (edgartools dep)
```

---

## 📂 Deep Reference Files

- `tools/sec/README.md` — Complete SEC module reference
- `tools/market/README.md` — Complete market module reference
- `tools/news/README.md` — Complete news module reference

---

*BrickellQuant Tools v0.1.0 | Agent-first Python library*
