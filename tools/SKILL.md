---
name: brickellquant-tools
description: >
  Financial data tools for SEC EDGAR, market data, and news.
  Wraps edgartools, yfinance, and RSS feeds into clean agent-callable functions.
  Enables quick queries for filings, prices, fundamentals, insider trades, dilution analysis, and news.
version: "0.1.0"
author: BrickellQuant
triggers:
  - on_request: "sec|edgar|10-k|10-q|8-k|filing|insider|dilution|yfinance|market data|stock price|fundamentals|news|rss"
dependencies:
  - edgartools>=2.0
  - yfinance>=0.2.38
  - feedparser>=6.0
  - pandas>=2.0
  - rich>=13.0
  - diskcache>=5.6
env:
  SEC_IDENTITY: "Required. Your name/email for SEC EDGAR access. e.g. 'agent@brickellquant.com'"
  FINNHUB_API_KEY: "Optional. Finnhub API key for enhanced ticker news."
  NEWSAPI_KEY: "Optional. NewsAPI key for additional news sources."
---

# BrickellQuant Tools Skill

Financial data library for agents. Three clients, one import each.

## Installation

```bash
cd /home/rincon/BrickellQuant
pip install -r tools/requirements.txt
export SEC_IDENTITY="your@email.com"
```

## The Three Clients

```python
from tools.sec import SECClient       # SEC EDGAR filings
from tools.market import MarketClient  # Prices, fundamentals, options
from tools.news import NewsClient      # News + live SEC RSS feed

sec = SECClient(identity="agent@brickellquant.com")
mkt = MarketClient()
news = NewsClient()
```

## What Each Client Does

### SECClient — tools/sec/sec_client.py

```python
# Company and filings
sec.company("AAPL")                          # edgartools Company object
sec.filings("AAPL", form="10-K", limit=5)   # list of FilingResult dicts
sec.latest("AAPL", "8-K")                   # most recent filing object

# Financial statements (from XBRL)
fins = sec.financials("AAPL")
fins["income_statement"]   # DataFrame
fins["balance_sheet"]      # DataFrame
fins["cash_flow"]          # DataFrame

# Insider transactions (Form 4)
df = sec.insider_trades("NVDA", days=90)     # DataFrame
buys = df[df["transaction"] == "Purchase"]

# Dilution analysis
d = sec.dilution_snapshot("LCID")
# d["risk_level"]          → "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"
# d["total_dilution_pct"]  → float
# d["fully_diluted_shares"]→ float (millions)

# Risk factors (Item 1A from 10-K)
risks = sec.risk_factors("TSLA")             # list[str]

# Red flag detection
flags = sec.red_flags("GME")                 # list[dict]
# flag["type"]     → "AUDITOR_CHANGE" | "NON_RELIANCE" | "GOING_CONCERN" | ...
# flag["severity"] → "CRITICAL" | "HIGH" | "MEDIUM"

# Full-text EDGAR search
results = sec.search("going concern substantial doubt", form="10-K")
```

### MarketClient — tools/market/market_client.py

```python
# Prices
q = mkt.price("NVDA")
# q["price"], q["change_pct"], q["market_cap_fmt"]

# History
hist = mkt.history("AAPL", period="1y")         # DataFrame (OHLCV)
hist = mkt.history("SPY", period="5d", interval="1h")  # intraday
hist = mkt.history("MSFT", start="2023-01-01", end="2024-01-01")

# Multiple tickers at once
df = mkt.multi_history(["AAPL","MSFT","GOOGL"], period="1y")
close = df["Close"]   # one column per ticker

# Fundamentals
f = mkt.fundamentals("MSFT")
# f["pe_ratio"], f["gross_margin"], f["roe"], f["fcf_yield"], f["ev_ebitda"] ...

# Financial statements (Yahoo Finance)
mkt.income("AAPL")                     # annual income statement DataFrame
mkt.income("AAPL", quarterly=True)     # quarterly
mkt.balance("AAPL")                    # balance sheet
mkt.cashflow("NVDA")                   # cash flow

# Options
chain = mkt.options("SPY")              # nearest expiry
chain["calls"]                          # DataFrame
chain["puts"]                           # DataFrame
chain["expiry"]                         # str "2025-01-17"
mkt.options("AAPL", expiry="2025-01-17")  # specific date

# Holders
h = mkt.holders("AAPL")
h["institutional"]                      # top institutional holders
h["major"]                              # % float, % institutions

# Analyst data
mkt.recommendations("NVDA")            # DataFrame
mkt.price_targets("NVDA")              # dict: low, mean, high
mkt.calendar("AAPL")                   # earnings calendar

# Comparison & screening
mkt.compare(["AAPL","MSFT","GOOGL"], metric="pe_ratio")  # DataFrame
mkt.screen(tickers, filters={
    "gross_margin": ("gt", 0.40),
    "pe_ratio": ("lt", 35),
})
```

### NewsClient — tools/news/news_client.py

```python
# Ticker news (Yahoo Finance + optional Finnhub)
articles = news.ticker_news("NVDA", limit=20)
# article["title"], article["source"], article["published"], article["url"]

# Live SEC EDGAR RSS (real-time filing stream)
news.sec_rss(form_type="8-K", limit=40)    # live 8-K filings
news.sec_rss(form_type="10-K", limit=20)   # annual reports
news.sec_rss(form_type="S-1", limit=10)    # IPO pipeline
news.sec_rss(form_type="4", limit=50)      # insider trades

# Company-specific SEC filing feed
news.sec_company_rss("AAPL", limit=20)
news.sec_company_rss("TSLA", form_type="8-K")

# Market headlines from financial RSS feeds
news.market_headlines(limit=30)
news.market_headlines(sources=["Reuters Business","CNBC"], limit=20)

# Search
news.search("Federal Reserve interest rates", limit=10)

# Full briefing
brief = news.summary("TSLA", limit=5)
# brief["news"]         → ticker news
# brief["sec_filings"]  → recent SEC filings
# brief["market_news"]  → general market news mentioning ticker
```

## Common Agent Workflows

### Full equity research
```python
sec = SECClient(identity="agent@brickellquant.com")
mkt = MarketClient()
news = NewsClient()
TICKER = "NVDA"

price = mkt.price(TICKER)
funds = mkt.fundamentals(TICKER)
fins = sec.financials(TICKER)
dilution = sec.dilution_snapshot(TICKER)
flags = sec.red_flags(TICKER)
insiders = sec.insider_trades(TICKER, days=90)
brief = news.summary(TICKER, limit=10)
```

### Screen watchlist for dilution risk
```python
for ticker in ["SOFI","LCID","RIVN","NKLA"]:
    d = sec.dilution_snapshot(ticker)
    print(f"{ticker}: {d['risk_level']} | {d['total_dilution_pct']:.1f}%")
```

### Monitor 8-K red flags in real time
```python
filings = news.sec_rss(form_type="8-K", limit=100)
for f in filings:
    if "4.01" in f.get("description","") or "4.02" in f.get("description",""):
        print(f"🚨 {f['company']}: {f['title']}")
```

### Detect insider cluster buys
```python
for ticker in UNIVERSE:
    trades = sec.insider_trades(ticker, days=30)
    c_suite_buys = trades[
        (trades["transaction"] == "Purchase") &
        trades["title"].str.contains("CEO|CFO|President", na=False)
    ]
    if len(c_suite_buys) >= 2:
        print(f"🟢 {ticker}: cluster buy signal")
```

## Caching

All methods are cached automatically:
- Prices: 60 seconds
- News: 300 seconds (5 min)
- SEC filings: 300–1800 seconds
- Financial data: 3600 seconds (1 hour)

```python
from tools.utils.cache import clear_cache, get_cache
get_cache()       # show cache info
clear_cache()     # wipe all cached results
```

## Full Reference Files

Read these for complete API docs:
- `tools/AGENT_README.md` — Master overview (start here)
- `tools/sec/README.md` — SEC module deep reference
- `tools/market/README.md` — Market module deep reference
- `tools/news/README.md` — News module deep reference

Run examples:
```bash
python tools/sec/examples/sec_examples.py
python tools/market/examples/market_examples.py
python tools/news/examples/news_examples.py
```
