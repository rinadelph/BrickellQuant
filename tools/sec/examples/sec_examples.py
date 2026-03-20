"""
SEC Module Examples
===================
Run: python -m tools.sec.examples.sec_examples

Requires: pip install edgartools
          export SEC_IDENTITY="your@email.com"
"""

import sys
sys.path.insert(0, "/home/rincon/BrickellQuant")

from tools.sec import SECClient

sec = SECClient(identity="agent@brickellquant.com")


def example_filings():
    """List recent 10-K filings for Apple."""
    print("\n" + "="*60)
    print("  EXAMPLE: Recent 10-K Filings for AAPL")
    print("="*60)

    filings = sec.filings("AAPL", form="10-K", limit=3)
    for f in filings:
        print(f"\n  Form:    {f['form_type']}")
        print(f"  Filed:   {f['filing_date']}")
        print(f"  Period:  {f['period_of_report']}")
        print(f"  Acc#:    {f['accession_number']}")
        print(f"  URL:     {f['url']}")


def example_financials():
    """Extract financial statements."""
    print("\n" + "="*60)
    print("  EXAMPLE: Financial Statements for MSFT")
    print("="*60)

    fins = sec.financials("MSFT")

    if not fins["income_statement"].empty:
        print("\n  Income Statement (first 5 rows):")
        print(fins["income_statement"].head())

    if not fins["balance_sheet"].empty:
        print("\n  Balance Sheet (first 5 rows):")
        print(fins["balance_sheet"].head())

    print(f"\n  Filing date: {fins['filing_date']}")
    print(f"  Period:      {fins['period']}")


def example_insider_trades():
    """Show recent insider trades."""
    print("\n" + "="*60)
    print("  EXAMPLE: Insider Trades for NVDA (90 days)")
    print("="*60)

    df = sec.insider_trades("NVDA", days=90)
    if df.empty:
        print("  No insider trades found.")
        return

    print(f"\n  Found {len(df)} transactions\n")

    buys = df[df["transaction"] == "Purchase"]
    sells = df[df["transaction"] == "Sale"]
    print(f"  Open Market Buys:  {len(buys)}")
    print(f"  Open Market Sells: {len(sells)}")

    if not df.empty:
        print("\n  Recent transactions:")
        display = df[["date","insider","title","transaction","shares","value"]].head(5)
        print(display.to_string(index=False))


def example_dilution():
    """Dilution risk analysis."""
    print("\n" + "="*60)
    print("  EXAMPLE: Dilution Snapshot")
    print("="*60)

    tickers = ["AAPL", "TSLA"]
    for ticker in tickers:
        d = sec.dilution_snapshot(ticker)
        print(f"\n  {d['ticker']}")
        print(f"  ├── Basic Shares:     {d['basic_shares_out']:.0f}M")
        print(f"  ├── Fully Diluted:    {d['fully_diluted_shares']:.0f}M")
        print(f"  ├── Dilution:         {d['total_dilution_pct']:.1f}%")
        print(f"  └── Risk Level:       {d['risk_level']}")


def example_red_flags():
    """Red flag screening."""
    print("\n" + "="*60)
    print("  EXAMPLE: Red Flag Screening")
    print("="*60)

    tickers = ["AAPL", "MSFT"]
    for ticker in tickers:
        flags = sec.red_flags(ticker)
        if not flags:
            print(f"\n  ✅ {ticker}: No red flags detected")
        else:
            print(f"\n  ⚠️  {ticker}: {len(flags)} flag(s)")
            for flag in flags:
                print(f"     [{flag['severity']}] {flag['type']}: {flag['description']}")


def example_search():
    """Full-text EDGAR search."""
    print("\n" + "="*60)
    print("  EXAMPLE: EDGAR Full-Text Search")
    print("="*60)

    results = sec.search("going concern substantial doubt", form="10-K", limit=5)
    print(f"\n  Found {len(results)} results for 'going concern'\n")
    for r in results:
        print(f"  {r.get('company','?'):40s} {r.get('filing_date','')}")
        print(f"  → {r.get('url','')}\n")


if __name__ == "__main__":
    print("\n🔍 Running SEC Module Examples...")
    print("   (Some examples require network access to SEC EDGAR)")

    try:
        example_filings()
    except Exception as e:
        print(f"  [example_filings] Error: {e}")

    try:
        example_insider_trades()
    except Exception as e:
        print(f"  [example_insider_trades] Error: {e}")

    try:
        example_dilution()
    except Exception as e:
        print(f"  [example_dilution] Error: {e}")

    try:
        example_red_flags()
    except Exception as e:
        print(f"  [example_red_flags] Error: {e}")

    print("\n✅ Done.")
