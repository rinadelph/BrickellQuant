# SEC Module — Deep Reference
`tools/sec/sec_client.py` | Powered by [edgartools](https://github.com/dgunning/edgartools)

---

## Quick Setup

```python
from tools.sec import SECClient

# Option 1: Pass identity directly
sec = SECClient(identity="Jane Smith jane@example.com")

# Option 2: Environment variable (recommended)
# export SEC_IDENTITY="Jane Smith jane@example.com"
sec = SECClient()
```

> **Why do I need an identity?**
> SEC EDGAR requires a User-Agent header identifying who is making requests.
> This is NOT an API key. It's just your name/email so SEC can contact you if needed.
> See: https://www.sec.gov/os/accessing-edgar-data

---

## Full API Reference

### `sec.company(ticker)` → `edgar.Company`

Get the raw edgartools Company object. Use this for advanced queries
not covered by wrapper methods.

```python
c = sec.company("AAPL")
print(c.name)           # "Apple Inc."
print(c.cik)            # "0000320193"
print(c.sic)            # Standard Industrial Classification code
print(c.state_of_inc)   # State of incorporation
print(c.fiscal_year_end)

# Raw filing access
all_10ks = c.get_filings(form="10-K")
latest_10k = all_10ks.latest(1)
```

---

### `sec.filings(ticker, form, limit)` → `list[FilingResult]`

```python
# 10-K annual reports
filings = sec.filings("MSFT", form="10-K", limit=5)

# 8-K current reports
filings = sec.filings("TSLA", form="8-K", limit=20)

# Form 4 insider transactions
filings = sec.filings("NVDA", form="4", limit=50)

# S-1 registration (if applicable)
filings = sec.filings("RDDT", form="S-1")

# Each result is a FilingResult dict:
for f in filings:
    print(f["filing_date"])        # "2024-10-31"
    print(f["form_type"])          # "10-K"
    print(f["period_of_report"])   # "2024-09-28"
    print(f["accession_number"])   # "0000320193-24-000123"
    print(f["url"])                # Link to EDGAR filing index
```

**All supported form types:**
```
10-K     Annual report
10-Q     Quarterly report
8-K      Current/material event report
DEF 14A  Proxy statement
4        Insider transaction (Form 4)
3        Initial beneficial ownership
5        Annual changes in beneficial ownership
S-1      Registration (IPO)
S-3      Shelf registration
S-4      Business combination
13F-HR   Institutional holdings (quarterly)
SC 13D   Activist ownership (>5%)
SC 13G   Passive ownership (>5%)
144      Restricted stock sale notice
```

---

### `sec.financials(ticker)` → `dict[str, DataFrame]`

Extracts financial statements from the latest 10-K/10-Q via XBRL.

```python
fins = sec.financials("AAPL")

# DataFrames (indexed by line item, columns = reporting periods)
income = fins["income_statement"]
balance = fins["balance_sheet"]
cashflow = fins["cash_flow"]

# Common line items to access:
revenue = income.loc["Revenues"].iloc[0]
net_income = income.loc["NetIncomeLoss"].iloc[0]
cash = balance.loc["CashAndCashEquivalentsAtCarryingValue"].iloc[0]
ocf = cashflow.loc["NetCashProvidedByUsedInOperatingActivities"].iloc[0]

# Metadata
print(fins["filing_date"])
print(fins["period"])
```

---

### `sec.insider_trades(ticker, days)` → `DataFrame`

```python
# 90-day window (default)
df = sec.insider_trades("NVDA")

# Custom window
df = sec.insider_trades("AAPL", days=30)

# Filter for open market purchases only
buys = df[df["transaction"] == "Purchase"]

# Filter for C-suite
c_suite = df[df["title"].str.contains("CEO|CFO|COO|President|Chief", na=False)]

# Cluster buy signal: multiple executives buying in same window
c_suite_buys = c_suite[c_suite["transaction"] == "Purchase"]
if len(c_suite_buys) >= 2:
    print("🟢 CLUSTER BUY SIGNAL")

# Large insider buys (>$500K)
big_buys = buys[buys["value"] > 500_000]

# Columns available:
# date, insider, title, transaction, shares, price, value, is_10b5_1, form_url
```

**Transaction types:**
```
Purchase        Open market buy (P) — BULLISH SIGNAL
Sale            Open market sell (S)
Option Exercise Exec exercising granted options (M)
Grant/Award     Company granting equity to insider (A)
Gift            Non-market transfer (G)
Tax Withholding Shares withheld for tax (F) — NEUTRAL
```

---

### `sec.dilution_snapshot(ticker)` → `DilutionSnapshot`

```python
d = sec.dilution_snapshot("LCID")

# Risk assessment
print(f"Risk Level: {d['risk_level']}")        # LOW | MEDIUM | HIGH | CRITICAL
print(f"Dilution: {d['total_dilution_pct']:.1f}%")

# Share structure
print(f"Basic:         {d['basic_shares_out']:.0f}M")
print(f"Options:       {d['options_shares']:.0f}M")
print(f"RSUs/PSUs:     {d['rsu_shares']:.0f}M")
print(f"Warrants:      {d['warrant_shares']:.0f}M")
print(f"Convertibles:  {d['convertible_shares']:.0f}M")
print(f"ATM Capacity:  {d['atm_remaining_shares']:.0f}M")
print(f"──────────────────────────────────")
print(f"Fully Diluted: {d['fully_diluted_shares']:.0f}M")

# Source info
print(f"As of: {d['as_of_date']}")
print(f"Source: {d['source_filing']}")
```

**Risk thresholds:**
```
LOW      < 10% dilution above basic shares
MEDIUM   10–25%
HIGH     25–50%
CRITICAL > 50%  ← Major concern for small caps and SPACs
```

---

### `sec.risk_factors(ticker)` → `list[str]`

```python
risks = sec.risk_factors("TSLA")
print(f"Found {len(risks)} risk factors")

# Print all
for i, risk in enumerate(risks, 1):
    print(f"{i:3d}. {risk}")

# Search for specific risks
supply_chain = [r for r in risks if "supply chain" in r.lower()]
regulatory = [r for r in risks if "regulat" in r.lower()]
cyber = [r for r in risks if "cyber" in r.lower() or "security" in r.lower()]
```

---

### `sec.red_flags(ticker)` → `list[dict]`

```python
flags = sec.red_flags("GME")

if not flags:
    print("✅ No red flags detected")
else:
    for flag in flags:
        icon = "🚨" if flag["severity"] == "CRITICAL" else "⚠️"
        print(f"{icon} [{flag['severity']}] {flag['type']}")
        print(f"   {flag['description']}")
        print(f"   Filed: {flag['filing_date']}")
        print(f"   URL: {flag['filing_url']}")
```

**Flag types and severities:**
```
AUDITOR_CHANGE      CRITICAL  — Change in independent auditor (8-K Item 4.01)
NON_RELIANCE        CRITICAL  — Prior financials can't be relied upon (8-K Item 4.02)
GOING_CONCERN       CRITICAL  — Auditor doubts ability to continue as going concern
IMPAIRMENT          HIGH      — Material asset impairment (8-K Item 2.06)
MATERIAL_WEAKNESS   HIGH      — Internal control failure in 10-K
RESTRUCTURING       MEDIUM    — Exit/restructuring charges (8-K Item 2.05)
```

---

### `sec.search(query, form, limit)` → `list[dict]`

Full-text search across all SEC EDGAR filings (EFTS).

```python
# Search for companies disclosing supply chain risks in 10-Ks
results = sec.search("lithium supply chain disruption", form="10-K", limit=10)

# Search for recent going concern disclosures
concerns = sec.search("going concern substantial doubt", form="10-K")

# Search across all form types
all_results = sec.search("PFAS contamination remediation")

for r in results:
    print(f"{r['company']:40s} {r['filing_date']}  {r['url']}")
```

---

## Advanced: Raw edgartools Access

```python
from edgar import Company, get_filings, find

# Direct edgartools usage (no wrapper)
c = Company("AAPL")

# Get 10-K and parse it directly
tenk = c.get_filings(form="10-K").latest(1).obj()
print(tenk.business_description)
print(tenk.risk_factors)
print(tenk.mda)  # Management Discussion & Analysis

# 8-K with items
eightk = c.get_filings(form="8-K").latest(1).obj()
print(eightk.items)   # e.g. "2.02, 9.01"

# Form 4 details
form4 = c.get_filings(form="4").latest(1).obj()
print(form4.transactions)
```

---

## Common Patterns

### Screen a watchlist for red flags
```python
sec = SECClient(identity="agent@brickellquant.com")
WATCHLIST = ["SOFI","LCID","NKLA","RIDE","HYLN"]

for ticker in WATCHLIST:
    flags = sec.red_flags(ticker)
    critical = [f for f in flags if f["severity"] == "CRITICAL"]
    if critical:
        print(f"🚨 {ticker}: {len(critical)} CRITICAL flag(s)")
        for f in critical:
            print(f"   → {f['type']}: {f['description']}")
```

### Monitor 8-K item 4.01/4.02 in real time
```python
from tools.news import NewsClient

news = NewsClient()

# Get live 8-K feed
filings = news.sec_rss(form_type="8-K", limit=100)

for filing in filings:
    desc = filing.get("description", "")
    if "4.01" in desc or "4.02" in desc:
        print(f"🚨 {filing['company']}: {filing['title']}")
        print(f"   {filing['url']}")
```

---

## edgartools Resources

- GitHub: https://github.com/dgunning/edgartools
- Docs: https://edgartools.readthedocs.io/
- PyPI: https://pypi.org/project/edgartools/
- SEC EDGAR: https://www.sec.gov/cgi-bin/browse-edgar
