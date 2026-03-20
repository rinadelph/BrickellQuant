"""
Market Module Examples
======================
Run: python -m tools.market.examples.market_examples

Requires: pip install yfinance
"""

import sys
sys.path.insert(0, "/home/rincon/BrickellQuant")

from tools.market import MarketClient
from tools.utils.formatters import print_table, fmt_number, fmt_pct

mkt = MarketClient()


def example_price_quote():
    """Current price and stats."""
    print("\n" + "="*60)
    print("  EXAMPLE: Price Quote")
    print("="*60)

    for ticker in ["NVDA", "AAPL", "SPY"]:
        q = mkt.price(ticker)
        bar = "🟢" if q["change_pct"] >= 0 else "🔴"
        print(
            f"\n  {bar} {q['ticker']:6s}  ${q['price']:>10,.2f}  "
            f"({q['change_pct']:+.2f}%)  "
            f"MCap: {q['market_cap_fmt']:>8s}  "
            f"Vol: {fmt_number(q['volume'])}"
        )
        print(
            f"           52W: ${q['fifty_two_week_low']:,.2f} – ${q['fifty_two_week_high']:,.2f}"
        )


def example_history():
    """Price history and returns calculation."""
    print("\n" + "="*60)
    print("  EXAMPLE: 1-Year Price History & Returns")
    print("="*60)

    tickers = ["AAPL", "MSFT", "GOOGL", "NVDA", "META"]
    returns = {}

    for ticker in tickers:
        try:
            hist = mkt.history(ticker, period="1y")
            if not hist.empty:
                start_price = hist["Close"].iloc[0]
                end_price = hist["Close"].iloc[-1]
                ret = (end_price / start_price - 1) * 100
                returns[ticker] = round(ret, 2)
        except Exception as e:
            returns[ticker] = None

    print("\n  1-Year Returns:")
    sorted_returns = sorted(returns.items(), key=lambda x: (x[1] or -999), reverse=True)
    for ticker, ret in sorted_returns:
        if ret is not None:
            bar = "🟢" if ret >= 0 else "🔴"
            print(f"    {bar} {ticker:6s}  {ret:+.2f}%")


def example_fundamentals():
    """Key fundamental metrics."""
    print("\n" + "="*60)
    print("  EXAMPLE: Fundamental Metrics")
    print("="*60)

    ticker = "MSFT"
    f = mkt.fundamentals(ticker)

    print(f"\n  {ticker} Fundamentals:")
    print(f"  ├── Valuation")
    print(f"  │   ├── P/E (TTM):      {f['pe_ratio']}")
    print(f"  │   ├── Forward P/E:    {f['forward_pe']}")
    print(f"  │   ├── PEG Ratio:      {f['peg_ratio']}")
    print(f"  │   ├── EV/EBITDA:      {f['ev_ebitda']}")
    print(f"  │   └── P/S:            {f['price_to_sales']}")
    print(f"  ├── Profitability")
    print(f"  │   ├── Gross Margin:   {fmt_pct(f['gross_margin'])}")
    print(f"  │   ├── Op Margin:      {fmt_pct(f['operating_margin'])}")
    print(f"  │   ├── Net Margin:     {fmt_pct(f['profit_margin'])}")
    print(f"  │   ├── ROE:            {fmt_pct(f['roe'])}")
    print(f"  │   └── FCF Yield:      {fmt_pct(f['fcf_yield'])}")
    print(f"  └── Risk / Structure")
    print(f"      ├── Debt/Equity:    {f['debt_to_equity']}")
    print(f"      ├── Current Ratio:  {f['current_ratio']}")
    print(f"      ├── Beta:           {f['beta']}")
    print(f"      └── Div Yield:      {fmt_pct(f['dividend_yield'])}")


def example_compare():
    """Multi-ticker comparison."""
    print("\n" + "="*60)
    print("  EXAMPLE: Compare P/E Ratios Across Big Tech")
    print("="*60)

    tickers = ["AAPL", "MSFT", "GOOGL", "META", "AMZN", "NVDA"]
    df = mkt.compare(tickers, metric="pe_ratio")
    df = df.sort_values("pe_ratio")

    print("\n  P/E Ratios (ascending):")
    for ticker, row in df.iterrows():
        val = row["pe_ratio"]
        if val is not None:
            bar = "█" * min(int(float(val) / 5), 20)
            print(f"  {ticker:6s}  {float(val):6.1f}x  {bar}")


def example_screen():
    """Screen tickers by criteria."""
    print("\n" + "="*60)
    print("  EXAMPLE: Screen for Quality Growth")
    print("="*60)

    universe = ["AAPL", "MSFT", "GOOGL", "META", "AMZN", "NVDA", "TSLA", "AMD"]
    result = mkt.screen(
        universe,
        filters={
            "gross_margin": ("gt", 0.40),
            "pe_ratio": ("lt", 60),
        }
    )

    if result.empty:
        print("  No tickers passed the screen.")
    else:
        print(f"\n  {len(result)} ticker(s) passed screen:")
        cols = [c for c in ["pe_ratio", "gross_margin", "roe", "fcf_yield"] if c in result.columns]
        print(result[cols].to_string())


def example_options():
    """Options chain overview."""
    print("\n" + "="*60)
    print("  EXAMPLE: Options Chain (SPY nearest expiry)")
    print("="*60)

    chain = mkt.options("SPY")
    print(f"\n  Expiry: {chain['expiry']}")
    print(f"  Available expiries: {chain['available_expiries'][:4]} ...")

    calls = chain["calls"]
    puts = chain["puts"]

    if not calls.empty:
        print(f"\n  Top 5 calls by volume:")
        top_calls = calls.nlargest(5, "volume")[["strike","lastPrice","bid","ask","volume","openInterest","impliedVolatility"]]
        print(top_calls.to_string(index=False))

    if not puts.empty and not calls.empty:
        pcr = puts["volume"].sum() / max(calls["volume"].sum(), 1)
        print(f"\n  Put/Call Volume Ratio: {pcr:.2f}")


if __name__ == "__main__":
    print("\n📊 Running Market Module Examples...")
    print("   (Requires network access to Yahoo Finance)")

    try:
        example_price_quote()
    except Exception as e:
        print(f"  [example_price_quote] Error: {e}")

    try:
        example_history()
    except Exception as e:
        print(f"  [example_history] Error: {e}")

    try:
        example_fundamentals()
    except Exception as e:
        print(f"  [example_fundamentals] Error: {e}")

    try:
        example_compare()
    except Exception as e:
        print(f"  [example_compare] Error: {e}")

    try:
        example_screen()
    except Exception as e:
        print(f"  [example_screen] Error: {e}")

    try:
        example_options()
    except Exception as e:
        print(f"  [example_options] Error: {e}")

    print("\n✅ Done.")
