"""
Yodel Module Examples
=====================
Run: python -m tools.Yodel.examples.yodel_examples

Demonstrates using YodelClient to treat websites as programmable APIs.
Requires: pip install playwright && playwright install chromium
"""

import sys
sys.path.insert(0, "/home/rincon/BrickellQuant")

from tools.Yodel import YodelClient

# ─────────────────────────────────────────────────────────────────────────────
# EXAMPLE 1 — Simple page fetch
# ─────────────────────────────────────────────────────────────────────────────

def example_fetch():
    """Fetch and display rendered page content."""
    print("\n" + "=" * 60)
    print("  EXAMPLE 1: Simple Page Fetch")
    print("=" * 60)

    with YodelClient(headless=True) as yodel:
        page = yodel.fetch("https://finance.yahoo.com/quote/NVDA/")

    print(f"\n  URL:    {page['url']}")
    print(f"  Title:  {page['title']}")
    print(f"  Status: {page['status']}")
    print(f"\n  First 500 chars of text:")
    print(f"  {page['text'][:500]}")


# ─────────────────────────────────────────────────────────────────────────────
# EXAMPLE 2 — Scrape elements with CSS selectors
# ─────────────────────────────────────────────────────────────────────────────

def example_scrape():
    """Extract specific elements from a rendered page."""
    print("\n" + "=" * 60)
    print("  EXAMPLE 2: Scrape Hacker News Headlines")
    print("=" * 60)

    with YodelClient(headless=True) as yodel:
        items = yodel.scrape(
            url="https://news.ycombinator.com",
            selector=".titleline a",
            attribute="href",
            limit=10,
        )

    print(f"\n  Found {len(items)} headlines:")
    for item in items:
        print(f"\n  ├── {item['text'][:70]}")
        print(f"  │   {item['attribute'][:80]}")


# ─────────────────────────────────────────────────────────────────────────────
# EXAMPLE 3 — Table extraction → DataFrame
# ─────────────────────────────────────────────────────────────────────────────

def example_table():
    """Extract an HTML table directly into a pandas DataFrame."""
    print("\n" + "=" * 60)
    print("  EXAMPLE 3: Extract Table → DataFrame")
    print("=" * 60)

    with YodelClient(headless=True) as yodel:
        df = yodel.table(
            url="https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            table_index=0,
        )

    if not df.empty:
        print(f"\n  Shape: {df.shape[0]} rows × {df.shape[1]} columns")
        print(f"  Columns: {list(df.columns[:6])}")
        print(f"\n  First 5 rows:")
        print(df.head(5).to_string(index=False, max_colwidth=30))
    else:
        print("  No table found.")


# ─────────────────────────────────────────────────────────────────────────────
# EXAMPLE 4 — SEC EDGAR full-text search via form submission
# ─────────────────────────────────────────────────────────────────────────────

def example_sec_search():
    """Submit a search form on SEC EDGAR and extract results."""
    print("\n" + "=" * 60)
    print("  EXAMPLE 4: SEC EDGAR Full-Text Search")
    print("=" * 60)

    with YodelClient(headless=True) as yodel:
        result = yodel.form_submit(
            url="https://efts.sec.gov/LATEST/search-index?q=%22going+concern%22&dateRange=custom&startdt=2024-01-01&enddt=2024-12-31&forms=10-K",
            fields={},   # No form inputs needed — URL contains query params
            submit="",   # Pre-loaded URL, no submit needed
            extract=".entity-name",
            timeout=20_000,
        )

    print(f"  Status:  {result['status']}")
    print(f"  URL:     {result['url']}")
    if result["elements"]:
        print(f"\n  Found {len(result['elements'])} results:")
        for el in result["elements"][:5]:
            print(f"  ├── {el['text']}")
    else:
        # Fall back to raw text
        print(f"\n  Page text snippet:\n  {result['text'][:400]}")


# ─────────────────────────────────────────────────────────────────────────────
# EXAMPLE 5 — Screenshot capture
# ─────────────────────────────────────────────────────────────────────────────

def example_screenshot():
    """Capture a screenshot of a financial page."""
    print("\n" + "=" * 60)
    print("  EXAMPLE 5: Screenshot Capture")
    print("=" * 60)

    out_path = "/tmp/nvda_yahoo.png"
    with YodelClient(headless=True) as yodel:
        png = yodel.screenshot(
            url="https://finance.yahoo.com/quote/NVDA/",
            path=out_path,
            full_page=False,
        )

    print(f"\n  PNG size:    {len(png):,} bytes")
    print(f"  Saved to:    {out_path}")


# ─────────────────────────────────────────────────────────────────────────────
# EXAMPLE 6 — Execute JavaScript on the page
# ─────────────────────────────────────────────────────────────────────────────

def example_execute_js():
    """Run JavaScript on a page to extract dynamic data."""
    print("\n" + "=" * 60)
    print("  EXAMPLE 6: Execute JavaScript")
    print("=" * 60)

    with YodelClient(headless=True) as yodel:
        # Count all links on a page
        link_count = yodel.execute(
            url="https://finance.yahoo.com/",
            script="() => document.querySelectorAll('a[href]').length",
        )

        # Extract the page title via JS
        title = yodel.execute(
            url="https://finance.yahoo.com/",
            script="() => document.title",
        )

    print(f"\n  Yahoo Finance homepage:")
    print(f"  ├── Total links:  {link_count}")
    print(f"  └── Page title:   {title}")


# ─────────────────────────────────────────────────────────────────────────────
# EXAMPLE 7 — Multi-step browser automation
# ─────────────────────────────────────────────────────────────────────────────

def example_multi_step():
    """Execute a sequence of browser actions as one flow."""
    print("\n" + "=" * 60)
    print("  EXAMPLE 7: Multi-Step Automation")
    print("=" * 60)

    with YodelClient(headless=True) as yodel:
        results = yodel.multi_step(
            start_url="https://news.ycombinator.com",
            steps=[
                # Wait for page to load
                {"action": "wait",      "selector": ".titleline"},
                # Extract first page headlines
                {"action": "extract",   "selector": ".titleline a"},
                # Navigate to page 2
                {"action": "click",     "selector": "a.morelink"},
                # Wait for page 2 content
                {"action": "wait",      "selector": ".titleline"},
                # Extract page 2 headlines
                {"action": "extract",   "selector": ".titleline a"},
            ],
        )

    all_headlines = []
    for r in results:
        if r.get("action") == "extract" and r.get("status") == "ok":
            for el in r.get("elements", []):
                all_headlines.append(el["text"])

    print(f"\n  Collected {len(all_headlines)} headlines across 2 pages:")
    for headline in all_headlines[:6]:
        print(f"  ├── {headline[:70]}")
    if len(all_headlines) > 6:
        print(f"  └── ... and {len(all_headlines) - 6} more")


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n🌐 Running Yodel Module Examples...")
    print("   (Requires playwright + chromium: playwright install chromium)")

    examples = [
        ("fetch",        example_fetch),
        ("scrape",       example_scrape),
        ("table",        example_table),
        ("sec_search",   example_sec_search),
        ("screenshot",   example_screenshot),
        ("execute_js",   example_execute_js),
        ("multi_step",   example_multi_step),
    ]

    for name, fn in examples:
        try:
            fn()
        except Exception as e:
            print(f"\n  [example_{name}] ⚠ Error: {e}")

    print("\n✅ Done.")
