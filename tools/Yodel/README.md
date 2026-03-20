# Yodel Module — Browser-as-API Reference
`tools/Yodel/yodel_client.py` | Powered by [Playwright](https://playwright.dev/python/)

---

## What is Yodel?

Yodel turns **any website into a programmable API** by driving a real Chromium browser.
Unlike plain HTTP requests, Yodel:

- ✅ Renders **JavaScript-heavy SPAs** (React, Vue, Angular)
- ✅ Handles **login sessions** — authenticate once, scrape protected pages
- ✅ Submits **forms** and navigates multi-step flows
- ✅ Extracts **HTML tables** directly into pandas DataFrames
- ✅ Navigates **pagination** automatically
- ✅ Runs **JavaScript** inside the page to extract dynamic data
- ✅ Takes **screenshots** for visual verification

---

## Quick Setup

```bash
# Install playwright
pip install playwright nest_asyncio

# Download the Chromium browser (one-time, ~150 MB)
playwright install chromium
```

```python
from tools.Yodel import YodelClient
yodel = YodelClient()
```

---

## Full API Reference

### `yodel.fetch(url)` → `PageContent`

Open a URL and return the fully-rendered page content.

```python
page = yodel.fetch("https://finance.yahoo.com/quote/NVDA/")

print(page["title"])          # Page <title>
print(page["url"])            # Final URL (after redirects)
print(page["status"])         # HTTP status code (200, 404, etc.)
print(page["text"][:500])     # Visible page text
print(page["html"][:200])     # Raw HTML

# Wait for a specific element before returning
page = yodel.fetch(
    "https://finance.yahoo.com/quote/NVDA/",
    wait_for="[data-testid='qsp-price']",
)
```

**PageContent fields:**
```
url       str    Final URL after any redirects
title     str    Page <title> text
text      str    Visible body text (whitespace-normalized)
html      str    Full outer HTML
status    int    HTTP status code
as_of     str    ISO timestamp when the fetch ran
```

---

### `yodel.scrape(url, selector)` → `list[PageElement]`

Extract all elements matching a CSS selector from a rendered page.

```python
# Get all Hacker News headlines and their links
items = yodel.scrape(
    url="https://news.ycombinator.com",
    selector=".titleline a",
    attribute="href",   # Also grab the href attribute
    limit=30,
)

for item in items:
    print(item["text"])       # Headline text
    print(item["attribute"])  # href URL
    print(item["html"])       # Inner HTML of the <a> element
    print(item["index"])      # 0-based position in match list

# Scrape table rows
rows = yodel.scrape(
    url="https://finviz.com/screener.ashx?v=111",
    selector="table.screener-table tr",
)
for row in rows:
    print(row["text"])
```

**PageElement fields:**
```
text       str    Inner text of the element (whitespace-normalized)
html       str    Inner HTML of the element
attribute  str    Value of requested attribute (e.g. href, src) or ""
index      int    0-based position in the results list
```

---

### `yodel.table(url, table_index)` → `DataFrame`

Extract an HTML table directly into a pandas DataFrame.

```python
# First table on a Wikipedia page
df = yodel.table(
    url="https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
    table_index=0,
)
print(df.head(10))
print(df["Symbol"].tolist())

# Target a specific table with a CSS selector
df = yodel.table(
    url="https://finance.yahoo.com/screener/...",
    selector="#scr-res-table table",
)

# Wait for a dynamic table to load before extracting
df = yodel.table(
    url="https://app.example.com/holdings",
    selector=".holdings-table",
    wait_for=".holdings-table",
)
```

---

### `yodel.form_submit(url, fields, submit)` → `ScrapeResult`

Fill in a form, click submit, and capture the result.

```python
# Search on a site and extract results
result = yodel.form_submit(
    url="https://efts.sec.gov/LATEST/search-index",
    fields={
        "#q": "going concern",
        "[name=dateRange]": "custom",
        "[name=startdt]": "2024-01-01",
    },
    submit="button[type=submit]",
    wait_for=".search-results",
    extract=".result-item",
)

print(result["status"])         # "ok" or "error"
for el in result["elements"]:
    print(el["text"])
```

**ScrapeResult fields:**
```
url       str          Final URL after form submit
title     str          Page title
text      str          Joined text from extract matches (or full page)
html      str          Joined HTML from extract matches (or full page)
elements  list         list[PageElement] when extract= selector used
status    str          "ok" | "error"
error     str          Error message if status == "error"
as_of     str          ISO timestamp
```

---

### `yodel.login(url, fields, submit)` → `dict`

Authenticate and persist the session for all future calls on this instance.

```python
result = yodel.login(
    url="https://app.example.com/login",
    fields={
        "input[name=email]":    "user@example.com",
        "input[name=password]": "secret123",
    },
    submit="button[type=submit]",
    wait_for="#dashboard",          # Element that proves login succeeded
)

if result["success"]:
    # Session is now authenticated — all subsequent calls use it
    holdings = yodel.scrape(
        "https://app.example.com/holdings", selector=".position-row"
    )
    portfolio = yodel.table(
        "https://app.example.com/portfolio", selector=".portfolio-table"
    )

# Save and re-load sessions (avoid re-logging in every run)
yodel.save_session("/tmp/my_session.json")

# Next run — skip the login
yodel2 = YodelClient(storage_state="/tmp/my_session.json")
holdings = yodel2.scrape("https://app.example.com/holdings", ".position-row")
```

**login() return dict:**
```
success   bool         True if login succeeded
url       str          Final URL after login navigation
cookies   list[dict]   Session cookies (Playwright format)
error     str          Error message if success == False
```

---

### `yodel.click_and_extract(url, click, extract)` → `list[PageElement]`

Click a UI element (tab, button, dropdown) then extract revealed data.

```python
# Click "Quarterly" tab and extract income statement rows
rows = yodel.click_and_extract(
    url="https://finance.yahoo.com/quote/AAPL/financials/",
    click="button[data-test='annual']",
    extract="tr.row",
    wait_for="table.financials",
)
for row in rows[:10]:
    print(row["text"])

# Expand accordion, then grab content
content = yodel.click_and_extract(
    url="https://example.com/faq",
    click=".faq-question:first-child",
    extract=".faq-answer",
)
```

---

### `yodel.paginate(url, item_selector, next_selector)` → `list[PageElement]`

Automatically page through multi-page results.

```python
# Scrape all search results across pages
all_results = yodel.paginate(
    url="https://efts.sec.gov/LATEST/search-index?q=going+concern&forms=10-K",
    item_selector=".search-result",
    next_selector="a[aria-label='Next page']",
    max_pages=5,
    wait_for=".search-results",
)

print(f"Collected {len(all_results)} items across pages")
for item in all_results:
    print(f"  Page {item.get('page')} → {item['text'][:60]}")
```

---

### `yodel.screenshot(url)` → `bytes`

Capture a PNG screenshot of a page.

```python
# Capture full-page screenshot
png_bytes = yodel.screenshot("https://finance.yahoo.com/quote/NVDA/")

# Save to file + get bytes back
yodel.screenshot(
    url="https://finance.yahoo.com/quote/AAPL/",
    path="/tmp/aapl.png",
    full_page=True,
)

# Only above-the-fold view
yodel.screenshot(
    url="https://example.com",
    path="/tmp/above_fold.png",
    full_page=False,
)
```

---

### `yodel.execute(url, script)` → `Any`

Run JavaScript inside the page and return the result.

```python
# Extract a global JS variable
data = yodel.execute(
    url="https://finance.yahoo.com/quote/NVDA/",
    script="() => window.__YAHOO_FINANCE_APP_SETTINGS__",
)

# Count matching elements
count = yodel.execute(
    url="https://example.com",
    script="() => document.querySelectorAll('table tr').length",
)

# Extract all text from a specific region
text = yodel.execute(
    url="https://example.com",
    script="() => document.querySelector('#main-content')?.innerText",
)
```

---

### `yodel.multi_step(steps, start_url)` → `list[dict]`

Execute a complete browser workflow as a sequence of named steps.

```python
results = yodel.multi_step(
    start_url="https://example.com",
    steps=[
        # Fill a search box
        {"action": "fill",      "selector": "#search",     "value": "NVDA"},
        # Click search button
        {"action": "click",     "selector": "#search-btn"},
        # Wait for results to appear
        {"action": "wait",      "selector": ".result-list"},
        # Extract all result titles
        {"action": "extract",   "selector": ".result-title"},
        # Go to next page
        {"action": "click",     "selector": "a.next-page"},
        # Pause 1.5 seconds
        {"action": "wait",      "ms": 1500},
        # Grab page 2 results
        {"action": "extract",   "selector": ".result-title"},
        # Run JS to read a window variable
        {"action": "js",        "script": "() => window.__RESULTS_COUNT__"},
        # Take a screenshot
        {"action": "screenshot","path": "/tmp/results.png"},
    ],
)

# Iterate over step results
for step in results:
    print(f"  [{step['action']}] status={step['status']}")
    for el in step.get("elements", []):
        print(f"    → {el['text'][:60]}")
    if "result" in step:
        print(f"    JS result: {step['result']}")
```

**Supported step actions:**
```
navigate    {"action": "navigate",   "url": "https://..."}
click       {"action": "click",      "selector": "button.ok"}
fill        {"action": "fill",       "selector": "#input", "value": "text"}
wait        {"action": "wait",       "selector": ".el"}   ← wait for CSS selector
            {"action": "wait",       "ms": 2000}           ← wait N milliseconds
extract     {"action": "extract",    "selector": ".row", "attribute": "href"}
screenshot  {"action": "screenshot", "path": "/tmp/out.png", "full_page": true}
js          {"action": "js",         "script": "() => expression"}
```

---

## Constructor Options

```python
YodelClient(
    headless=True,          # Run without GUI (False shows browser window)
    slow_mo=0,              # Slow down every action by N ms (debugging)
    timeout=30_000,         # Default timeout in ms (30 seconds)
    user_agent="...",       # Override User-Agent string
    viewport={"width": 1440, "height": 900},
    cookies=[...],          # Pre-load cookies (Playwright format)
    proxy="http://host:port",  # Route through a proxy
    stealth=True,           # Apply anti-bot fingerprint patches
    storage_state="/path/session.json",  # Load saved session
)
```

---

## Common Patterns

### Use as context manager (recommended)

```python
# Browser opens, you work, browser closes automatically
with YodelClient() as yodel:
    df = yodel.table("https://example.com/data")
    data = yodel.scrape("https://example.com/list", ".item")
```

### Reuse session across multiple requests

```python
yodel = YodelClient()

# All three calls share one browser + session
page1 = yodel.fetch("https://example.com/page-1")
page2 = yodel.fetch("https://example.com/page-2")
page3 = yodel.scrape("https://example.com/items", ".item")

yodel.close()  # clean up when done
```

### Authenticated multi-site scraping

```python
yodel = YodelClient()

# Log in once
yodel.login(
    url="https://app.example.com/login",
    fields={"#email": "me@example.com", "#pass": "secret"},
    submit="button[type=submit]",
    wait_for="#home",
)

# Save session for future runs
yodel.save_session("/tmp/session.json")

# Scrape protected content
holdings = yodel.scrape("https://app.example.com/holdings", ".row")
history  = yodel.table("https://app.example.com/history", selector=".history-table")

yodel.close()
```

### Show browser window for debugging

```python
# headless=False opens a real Chrome window so you can watch
yodel = YodelClient(headless=False, slow_mo=500)
page  = yodel.fetch("https://example.com")
yodel.close()
```

---

## Finance Use Cases

| Goal | Method |
|------|--------|
| Extract rendered stock quote | `fetch()` |
| Scrape earnings table from a site | `table()` |
| Pull data from a search form | `form_submit()` |
| Log into a brokerage and get holdings | `login()` + `scrape()` |
| Extract content behind a "Show More" button | `click_and_extract()` |
| Scrape all pages of SEC EDGAR search results | `paginate()` |
| Extract data from JS window variables | `execute()` |
| Automate a complex multi-click workflow | `multi_step()` |
| Screenshot a dashboard for a report | `screenshot()` |

---

## Dependencies

```bash
pip install playwright nest_asyncio
playwright install chromium
```

- `playwright>=1.44` — Browser automation engine
- `nest_asyncio>=1.6` — Required for Jupyter notebook compatibility
- `pandas>=2.0` — For `table()` output

---

## Playwright Resources

- Python docs: https://playwright.dev/python/
- Selectors guide: https://playwright.dev/python/docs/selectors
- GitHub: https://github.com/microsoft/playwright-python
