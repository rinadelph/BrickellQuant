# News Module — Deep Reference
`tools/news/news_client.py` | Sources: SEC EDGAR RSS, Yahoo Finance, RSS Feeds, Finnhub

---

## Quick Setup

```python
from tools.news import NewsClient

# Basic (no API key needed)
news = NewsClient()

# With Finnhub for enhanced ticker news (optional)
# export FINNHUB_API_KEY="your_key"
news = NewsClient()  # auto-reads env var
# OR
news = NewsClient(finnhub_key="your_key_here")
```

---

## Full API Reference

### `news.ticker_news(ticker, limit)` → `list[NewsItem]`

News articles for a specific stock ticker.

**Sources in order:**
1. Yahoo Finance (always available)
2. Finnhub (if API key set)

```python
articles = news.ticker_news("NVDA", limit=20)

for a in articles:
    print(f"[{a['source']}] {a['title']}")
    print(f"  Published: {a['published']}")
    print(f"  URL: {a['url']}")
    if a['summary']:
        print(f"  Summary: {a['summary'][:150]}...")
    print()
```

**NewsItem fields:**
```
title       str   Article headline
url         str   Article URL
source      str   Publisher name
published   str   ISO datetime string "2024-12-15T10:30:00"
summary     str   Article summary/excerpt (may be empty)
ticker      str   Associated ticker symbol
```

---

### `news.sec_rss(form_type, limit)` → `list[dict]`

**Live stream of new SEC EDGAR filings — no ticker needed.**

This is the real-time SEC EDGAR RSS feed. New filings appear here within
minutes of submission.

```python
# Latest 8-K filings (material events)
eightks = news.sec_rss(form_type="8-K", limit=30)

# Latest 10-K annual reports
tenks = news.sec_rss(form_type="10-K", limit=20)

# S-1 filings (IPO pipeline)
ipos = news.sec_rss(form_type="S-1", limit=10)

# Form 4 insider transactions (very active feed)
insider_feed = news.sec_rss(form_type="4", limit=50)

for f in eightks:
    print(f"{f['company']:40s} {f['form_type']} {f['published']}")
    print(f"  {f['description'][:100]}")
    print(f"  {f['url']}")
```

**Result fields:**
```
title           str   Full filing title from RSS
company         str   Company name (extracted from title)
form_type       str   The form type you requested
published       str   Filing timestamp
description     str   May contain 8-K item numbers (e.g. "2.02, 9.01")
url             str   SEC EDGAR filing index URL
cik             str   Company CIK number
```

**Supported form types for RSS:**
```
8-K      Current/material events        ← Most active, ~50-100/day
10-K     Annual reports
10-Q     Quarterly reports
4        Insider transactions            ← Very active
S-1      IPO registrations
S-3      Shelf registrations
13F-HR   Institutional holdings
SC 13D   Activist positions
SC 13G   Passive positions
DEF 14A  Proxy statements
```

---

### `news.sec_company_rss(ticker, form_type, limit)` → `list[dict]`

Company-specific SEC filing history via EDGAR RSS.

```python
# All recent filings for Apple
filings = news.sec_company_rss("AAPL", limit=20)

# Only 8-K filings
eightks = news.sec_company_rss("TSLA", form_type="8-K", limit=10)

# Only 10-K filings
tenks = news.sec_company_rss("MSFT", form_type="10-K", limit=5)

# Works with CIK too
apple = news.sec_company_rss("0000320193", limit=10)

for f in filings:
    print(f"{f['form_type']:10s} {f['published'][:10]}  {f['url']}")
```

---

### `news.market_headlines(sources, limit)` → `list[NewsItem]`

Aggregate financial RSS headlines from major sources.

```python
# All sources, top 30 articles
all_news = news.market_headlines(limit=30)

# Select sources only
cnbc_reuters = news.market_headlines(
    sources=["CNBC", "Reuters Business", "Reuters Markets"],
    limit=20
)

# Just one source
wsj = news.market_headlines(sources=["WSJ Markets"], limit=10)
```

**Available RSS sources:**
```python
news.available_rss_sources()
# Returns:
{
    "Reuters Business": "https://feeds.reuters.com/reuters/businessNews",
    "Reuters Markets":  "https://feeds.reuters.com/reuters/UKmarkets",
    "MarketWatch":      "https://feeds.marketwatch.com/marketwatch/topstories/",
    "Seeking Alpha":    "https://seekingalpha.com/feed.xml",
    "Benzinga":         "https://www.benzinga.com/feed",
    "Financial Times":  "https://www.ft.com/rss/home/uk",
    "CNBC":             "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "Yahoo Finance":    "https://finance.yahoo.com/rss/topfinstories",
    "WSJ Markets":      "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
}
```

---

### `news.search(query, sources, limit)` → `list[NewsItem]`

Keyword search across aggregated RSS news.

```python
# Search for specific topics
fed_news = news.search("Federal Reserve interest rates")
inflation = news.search("CPI inflation", limit=5)
nvda_news = news.search("NVIDIA earnings guidance", limit=10)

# Search specific sources
wsj_fed = news.search(
    "Federal Reserve",
    sources=["WSJ Markets", "Reuters Markets"],
    limit=10
)
```

---

### `news.summary(ticker, limit)` → `dict`

All-in-one briefing for a ticker.

```python
brief = news.summary("TSLA", limit=5)

print(f"Ticker: {brief['ticker']}")
print(f"As of: {brief['as_of']}")

print(f"\n📰 NEWS ({len(brief['news'])} articles):")
for a in brief["news"]:
    print(f"  [{a['source']}] {a['title']}")

print(f"\n📋 SEC FILINGS ({len(brief['sec_filings'])} filings):")
for f in brief["sec_filings"]:
    print(f"  {f['form_type']:10s} {f['published'][:10]}  {f.get('description','')[:50]}")

print(f"\n🌐 MARKET NEWS ({len(brief['market_news'])} articles):")
for a in brief["market_news"]:
    print(f"  [{a['source']}] {a['title']}")
```

**Result structure:**
```
ticker          str
news            list[NewsItem]   Yahoo Finance news for ticker
sec_filings     list[dict]       Company's recent SEC filings
market_news     list[NewsItem]   General news mentioning ticker
as_of           str              ISO timestamp
```

---

## Common Patterns

### 8-K Critical Item Monitor
```python
news = NewsClient()
sec = SECClient(identity="agent@brickellquant.com")

# Poll every few minutes in a real system
filings = news.sec_rss(form_type="8-K", limit=100)

CRITICAL_ITEMS = ["4.01", "4.02"]  # Auditor change, non-reliance
HIGH_ITEMS = ["2.06", "2.05"]       # Impairment, restructuring

for filing in filings:
    desc = filing.get("description", "")
    company = filing.get("company", "Unknown")

    if any(item in desc for item in CRITICAL_ITEMS):
        print(f"🚨 CRITICAL — {company}")
        print(f"   {filing['url']}")
    elif any(item in desc for item in HIGH_ITEMS):
        print(f"⚠️  HIGH — {company}")
        print(f"   {filing['url']}")
```

### Daily Market Briefing
```python
from datetime import datetime

news = NewsClient()

print(f"{'='*60}")
print(f"  MARKET BRIEFING — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
print(f"{'='*60}")

# Top headlines
headlines = news.market_headlines(
    sources=["Reuters Business", "WSJ Markets", "CNBC"],
    limit=10
)

for i, h in enumerate(headlines, 1):
    print(f"\n{i:2d}. [{h['source']}] {h['title']}")
    if h["summary"]:
        print(f"    {h['summary'][:200]}")

# Recent 8-Ks
print(f"\n{'─'*60}")
print(f"  RECENT 8-K FILINGS")
print(f"{'─'*60}")

eightks = news.sec_rss(form_type="8-K", limit=10)
for f in eightks:
    print(f"  {f['company']:40s} {f['published'][:16]}")
```

### IPO Pipeline Tracker
```python
news = NewsClient()

print("S-1 FILINGS (IPO PIPELINE):")
print("─" * 60)
s1_filings = news.sec_rss(form_type="S-1", limit=20)
for f in s1_filings:
    print(f"  {f['company']}")
    print(f"  Filed: {f['published'][:10]}")
    print(f"  URL: {f['url']}")
    print()
```

---

## Optional: Finnhub Setup

Finnhub provides higher-quality, more reliable ticker news.

1. Get free API key: https://finnhub.io/register (free tier: 60 req/min)
2. Set environment variable:
   ```bash
   export FINNHUB_API_KEY="your_key_here"
   ```
3. NewsClient will automatically use it:
   ```python
   news = NewsClient()  # auto-reads FINNHUB_API_KEY
   articles = news.ticker_news("NVDA")  # now uses Finnhub too
   ```

---

## SEC EDGAR RSS Documentation

- EDGAR Full-Text RSS: https://efts.sec.gov/LATEST/search-index?q=%22going+concern%22&dateRange=custom&startdt=2024-01-01&forms=10-K
- EDGAR Company RSS: https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=AAPL&type=8-K&output=atom
- feedparser docs: https://feedparser.readthedocs.io/
