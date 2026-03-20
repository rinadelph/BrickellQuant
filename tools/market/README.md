# Market Module — Deep Reference
`tools/market/market_client.py` | Powered by [yfinance](https://github.com/ranaroussi/yfinance)

---

## Quick Setup

```python
from tools.market import MarketClient
mkt = MarketClient()
# No API key required
```

---

## Full API Reference

### `mkt.price(ticker)` → `PriceQuote`

Current price and daily stats.

```python
q = mkt.price("NVDA")

print(f"Price:     ${q['price']:,.2f}")
print(f"Change:    {q['change']:+.2f} ({q['change_pct']:+.2f}%)")
print(f"Volume:    {q['volume']:,}")
print(f"Mkt Cap:   {q['market_cap_fmt']}")
print(f"52W High:  ${q['fifty_two_week_high']:,.2f}")
print(f"52W Low:   ${q['fifty_two_week_low']:,.2f}")
```

**All PriceQuote fields:**
```
ticker              str     "NVDA"
price               float   Current/last price
open                float   Day open
high                float   Day high
low                 float   Day low
prev_close          float   Previous close
change              float   Price change today ($)
change_pct          float   % change today
volume              int     Today's volume
avg_volume          int     30-day avg volume
market_cap          float   Market cap (raw)
market_cap_fmt      str     "1.23T", "450B", etc.
fifty_two_week_high float
fifty_two_week_low  float
currency            str     "USD"
exchange            str     "NMS", "NYQ", etc.
```

---

### `mkt.history(ticker, period, interval)` → `DataFrame`

OHLCV historical price data.

```python
# Standard periods
hist = mkt.history("AAPL", period="1y")       # 1 year daily
hist = mkt.history("SPY", period="5d", interval="1h")  # 5 days hourly
hist = mkt.history("MSFT", period="max")      # Max available

# Custom date range
hist = mkt.history("GOOGL", start="2023-01-01", end="2024-01-01")

# Access columns
hist["Close"].plot()                          # Closing prices
hist["Volume"].tail(5)                        # Last 5 days volume
returns = hist["Close"].pct_change()          # Daily returns
```

**Period options:** `1d`, `5d`, `1mo`, `3mo`, `6mo`, `1y`, `2y`, `5y`, `10y`, `ytd`, `max`

**Interval options:** `1m`, `2m`, `5m`, `15m`, `30m`, `60m`, `90m`, `1h`, `1d`, `5d`, `1wk`, `1mo`, `3mo`

> Note: 1m data only available for last 7 days. 1h data for last 730 days.

---

### `mkt.multi_history(tickers, period, interval)` → `DataFrame`

```python
# Multiple tickers at once
df = mkt.multi_history(["AAPL","MSFT","GOOGL","META"], period="1y")

# Access close prices for all
close_prices = df["Close"]
print(close_prices.corr())  # Correlation matrix

# Normalized returns from a base date
normalized = close_prices / close_prices.iloc[0] * 100
```

---

### `mkt.fundamentals(ticker)` → `dict`

All key valuation and financial ratios.

```python
f = mkt.fundamentals("MSFT")

# Valuation
print(f"P/E (TTM):       {f['pe_ratio']:.1f}x")
print(f"Forward P/E:     {f['forward_pe']:.1f}x")
print(f"PEG Ratio:       {f['peg_ratio']:.2f}")
print(f"P/B:             {f['price_to_book']:.2f}x")
print(f"P/S:             {f['price_to_sales']:.2f}x")
print(f"EV/EBITDA:       {f['ev_ebitda']:.1f}x")
print(f"EV/Revenue:      {f['ev_revenue']:.1f}x")

# Profitability
print(f"Gross Margin:    {f['gross_margin']:.1%}")
print(f"Operating Margin:{f['operating_margin']:.1%}")
print(f"Net Margin:      {f['profit_margin']:.1%}")
print(f"ROE:             {f['roe']:.1%}")
print(f"ROA:             {f['roa']:.1%}")
print(f"FCF Yield:       {f['fcf_yield']:.2%}")

# Balance sheet / risk
print(f"Debt/Equity:     {f['debt_to_equity']:.1f}")
print(f"Current Ratio:   {f['current_ratio']:.2f}")
print(f"Beta:            {f['beta']:.2f}")
print(f"Dividend Yield:  {f['dividend_yield']:.2%}")
```

---

### `mkt.income(ticker, quarterly)` → `DataFrame`

```python
# Annual income statement (last 4 years)
annual = mkt.income("AAPL")

# Quarterly income statement (last 4 quarters)
quarterly = mkt.income("AAPL", quarterly=True)

# Common line items
revenue = annual.loc["Total Revenue"]
gross_profit = annual.loc["Gross Profit"]
operating_income = annual.loc["Operating Income"]
net_income = annual.loc["Net Income"]
ebitda = annual.loc["EBITDA"]

# Growth calculation
rev_growth = annual.loc["Total Revenue"].pct_change(periods=-1)
```

---

### `mkt.balance(ticker, quarterly)` → `DataFrame`

```python
bs = mkt.balance("AAPL")

# Key items
cash = bs.loc["Cash And Cash Equivalents"]
total_assets = bs.loc["Total Assets"]
total_debt = bs.loc["Total Debt"]
equity = bs.loc["Stockholders Equity"]

# Net cash position
net_cash = bs.loc["Cash And Cash Equivalents"].iloc[0] - bs.loc["Total Debt"].iloc[0]
```

---

### `mkt.cashflow(ticker, quarterly)` → `DataFrame`

```python
cf = mkt.cashflow("NVDA")

# Key items
ocf = cf.loc["Operating Cash Flow"].iloc[0]
capex = cf.loc["Capital Expenditure"].iloc[0]  # negative number
fcf = ocf + capex  # Free Cash Flow

sbc = cf.loc["Stock Based Compensation"].iloc[0]  # dilution cost

# FCF margin
revenue = mkt.income("NVDA").loc["Total Revenue"].iloc[0]
fcf_margin = fcf / revenue
print(f"FCF Margin: {fcf_margin:.1%}")
```

---

### `mkt.options(ticker, expiry)` → `dict`

```python
# Nearest expiry (default)
chain = mkt.options("SPY")
print(f"Expiry: {chain['expiry']}")
print(f"Available: {chain['available_expiries'][:5]}")

# Calls and puts DataFrames
calls = chain["calls"]
puts = chain["puts"]

# Key columns: strike, lastPrice, bid, ask, volume, openInterest, impliedVolatility, inTheMoney

# Find highest volume calls
hot_calls = calls.nlargest(5, "volume")[["strike","lastPrice","volume","openInterest","impliedVolatility"]]

# Options activity (put/call ratio)
put_volume = puts["volume"].sum()
call_volume = calls["volume"].sum()
pcr = put_volume / call_volume
print(f"Put/Call Volume Ratio: {pcr:.2f}")

# Specific expiry
chain_jan = mkt.options("AAPL", expiry="2025-01-17")

# Farthest expiry (LEAPS)
leaps = mkt.options("AAPL", expiry="farthest")
```

---

### `mkt.holders(ticker)` → `dict`

```python
h = mkt.holders("AAPL")

print(h["major"])           # % float, % institutions, % insiders

inst = h["institutional"]   # Top institutional holders
print(inst[["Holder","Shares","% Out","Value"]].head(15))

mf = h["mutual_funds"]      # Top mutual fund holders
print(mf[["Holder","Shares","% Out"]].head(10))
```

---

### `mkt.compare(tickers, metric)` → `DataFrame`

```python
# Compare P/E ratios
pe = mkt.compare(["AAPL","MSFT","GOOGL","META","AMZN"], metric="pe_ratio")
print(pe.sort_values("pe_ratio"))

# Compare gross margins
margins = mkt.compare(["AAPL","MSFT","GOOGL","META"], metric="gross_margin")

# Compare FCF yields
fcf = mkt.compare(
    ["AAPL","MSFT","GOOGL","META","NVDA"],
    metric="fcf_yield"
)
print(fcf.sort_values("fcf_yield", ascending=False))
```

---

### `mkt.screen(tickers, filters)` → `DataFrame`

```python
UNIVERSE = ["AAPL","MSFT","GOOGL","META","AMZN","TSLA","NVDA","NFLX","AMD","QCOM"]

# Find quality compounders: low P/E, high margins, low debt
result = mkt.screen(
    UNIVERSE,
    filters={
        "pe_ratio": ("lt", 35),
        "gross_margin": ("gt", 0.45),
        "roe": ("gt", 0.15),
        "debt_to_equity": ("lt", 100),
    }
)
print(result[["pe_ratio","gross_margin","roe","debt_to_equity"]])

# Find oversold value plays
value = mkt.screen(
    UNIVERSE,
    filters={
        "pe_ratio": ("lt", 15),
        "price_to_book": ("lt", 3),
    }
)
```

**Filter operators:** `gt` (>), `lt` (<), `gte` (>=), `lte` (<=), `eq` (==)

---

## Common Patterns

### Quick equity snapshot
```python
def equity_snapshot(ticker: str):
    mkt = MarketClient()
    q = mkt.price(ticker)
    f = mkt.fundamentals(ticker)
    
    print(f"{'─'*50}")
    print(f"  {ticker.upper()} | ${q['price']:,.2f} ({q['change_pct']:+.2f}%)")
    print(f"  Mkt Cap: {q['market_cap_fmt']} | Beta: {f['beta']}")
    print(f"{'─'*50}")
    print(f"  P/E: {f['pe_ratio']}x | Fwd P/E: {f['forward_pe']}x | EV/EBITDA: {f['ev_ebitda']}x")
    print(f"  Gross Margin: {f['gross_margin']:.1%} | FCF Yield: {f['fcf_yield']:.2%}")
    print(f"  52W: ${q['fifty_two_week_low']:.2f} – ${q['fifty_two_week_high']:.2f}")
```

### Calculate 1-year returns for a basket
```python
import pandas as pd

tickers = ["AAPL","MSFT","GOOGL","META","NVDA"]
mkt = MarketClient()

returns = {}
for ticker in tickers:
    hist = mkt.history(ticker, period="1y")
    if not hist.empty:
        ret = (hist["Close"].iloc[-1] / hist["Close"].iloc[0] - 1) * 100
        returns[ticker] = round(ret, 2)

df = pd.DataFrame.from_dict(returns, orient="index", columns=["1Y Return %"])
print(df.sort_values("1Y Return %", ascending=False))
```

---

## yfinance Resources

- GitHub: https://github.com/ranaroussi/yfinance
- Docs: https://ranaroussi.github.io/yfinance/
- PyPI: https://pypi.org/project/yfinance/
