"""
News Module Examples
====================
Run: python -m tools.news.examples.news_examples

Requires: pip install feedparser yfinance
"""

import sys
sys.path.insert(0, "/home/rincon/BrickellQuant")

from tools.news import NewsClient

news = NewsClient()


def example_ticker_news():
    """News for a specific ticker."""
    print("\n" + "="*60)
    print("  EXAMPLE: Ticker News — NVDA")
    print("="*60)

    articles = news.ticker_news("NVDA", limit=5)
    if not articles:
        print("  No articles found.")
        return

    for i, a in enumerate(articles, 1):
        print(f"\n  {i}. [{a['source']}]")
        print(f"     {a['title']}")
        print(f"     📅 {a['published'][:19]}")
        print(f"     🔗 {a['url'][:80]}")


def example_sec_rss():
    """Live SEC EDGAR filing feed."""
    print("\n" + "="*60)
    print("  EXAMPLE: Live SEC 8-K Filing Feed")
    print("="*60)

    filings = news.sec_rss(form_type="8-K", limit=10)

    if not filings or "error" in filings[0]:
        print(f"  Error: {filings[0].get('error','Unknown error')}")
        return

    print(f"\n  Latest {len(filings)} 8-K filings:\n")
    for f in filings:
        print(f"  {'─'*55}")
        print(f"  Company:  {f['company']}")
        print(f"  Filed:    {f['published'][:19]}")
        if f.get("description"):
            print(f"  Items:    {f['description'][:100]}")
        print(f"  URL:      {f['url'][:70]}")


def example_sec_company_rss():
    """Company-specific SEC filing history."""
    print("\n" + "="*60)
    print("  EXAMPLE: Apple's Recent SEC Filings")
    print("="*60)

    filings = news.sec_company_rss("AAPL", limit=10)

    if not filings or "error" in filings[0]:
        print(f"  Error: {filings[0].get('error','Unknown')}")
        return

    print(f"\n  Apple's {len(filings)} most recent filings:\n")
    for f in filings:
        form = f.get("form_type", "?")
        date = f.get("published", "")[:10]
        print(f"  {form:10s}  {date}  {f.get('url','')[:60]}")


def example_market_headlines():
    """Market news from RSS feeds."""
    print("\n" + "="*60)
    print("  EXAMPLE: Market Headlines (Reuters + CNBC)")
    print("="*60)

    headlines = news.market_headlines(
        sources=["Reuters Business", "CNBC"],
        limit=10
    )

    if not headlines:
        print("  No headlines found.")
        return

    print(f"\n  Top {len(headlines)} headlines:\n")
    for i, h in enumerate(headlines, 1):
        print(f"  {i:2d}. [{h['source']}]")
        print(f"      {h['title']}")
        if h["summary"]:
            print(f"      → {h['summary'][:120]}...")
        print()


def example_search():
    """Search news by keyword."""
    print("\n" + "="*60)
    print("  EXAMPLE: Search News for 'Federal Reserve'")
    print("="*60)

    results = news.search("Federal Reserve", limit=5)

    if not results:
        print("  No results found.")
        return

    print(f"\n  {len(results)} result(s):\n")
    for r in results:
        print(f"  [{r['source']}] {r['title']}")
        print(f"  {r['published'][:19]}  {r['url'][:70]}")
        print()


def example_summary():
    """Full briefing for a ticker."""
    print("\n" + "="*60)
    print("  EXAMPLE: Full Briefing for TSLA")
    print("="*60)

    brief = news.summary("TSLA", limit=3)

    print(f"\n  Ticker: {brief['ticker']}")
    print(f"  As of:  {brief['as_of'][:19]}")

    print(f"\n  📰 NEWS ({len(brief['news'])} articles):")
    for a in brief["news"]:
        print(f"    [{a['source']}] {a['title'][:70]}")

    print(f"\n  📋 SEC FILINGS ({len(brief['sec_filings'])} filings):")
    for f in brief["sec_filings"]:
        print(f"    {f.get('form_type','?'):10s} {f.get('published','')[:10]}")

    print(f"\n  🌐 MARKET NEWS ({len(brief['market_news'])} articles):")
    for a in brief["market_news"]:
        print(f"    [{a['source']}] {a['title'][:70]}")


def example_ipo_pipeline():
    """Track S-1 (IPO) filings."""
    print("\n" + "="*60)
    print("  EXAMPLE: S-1 Filing Pipeline (IPO Tracker)")
    print("="*60)

    s1s = news.sec_rss(form_type="S-1", limit=10)

    if not s1s or "error" in s1s[0]:
        print(f"  Note: {s1s[0].get('error','No S-1 data')}")
        return

    print(f"\n  Recent S-1 filings:\n")
    for f in s1s:
        print(f"  {f['company']}")
        print(f"  Filed: {f['published'][:10]}  {f['url'][:60]}")
        print()


if __name__ == "__main__":
    print("\n📰 Running News Module Examples...")
    print("   (Requires network access)")

    try:
        example_ticker_news()
    except Exception as e:
        print(f"  [example_ticker_news] Error: {e}")

    try:
        example_sec_rss()
    except Exception as e:
        print(f"  [example_sec_rss] Error: {e}")

    try:
        example_sec_company_rss()
    except Exception as e:
        print(f"  [example_sec_company_rss] Error: {e}")

    try:
        example_market_headlines()
    except Exception as e:
        print(f"  [example_market_headlines] Error: {e}")

    try:
        example_summary()
    except Exception as e:
        print(f"  [example_summary] Error: {e}")

    try:
        example_ipo_pipeline()
    except Exception as e:
        print(f"  [example_ipo_pipeline] Error: {e}")

    print("\n✅ Done.")
