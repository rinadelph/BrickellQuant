"""
YodelClient — Playwright Browser-as-API
========================================

Treats any website as a programmable API using a real Chromium browser.
Handles JavaScript-rendered pages, login sessions, forms, pagination,
and dynamic content — things plain HTTP requests cannot reach.

SETUP:
    from tools.Yodel import YodelClient
    yodel = YodelClient()

    # One-time browser install (run once after pip install playwright):
    #   playwright install chromium

REFERENCE: tools/Yodel/README.md
"""

from __future__ import annotations

import asyncio
import re
import time
from contextlib import asynccontextmanager, contextmanager
from typing import Any, Optional, Union

import pandas as pd

# ── Playwright availability guard ──────────────────────────────────────────────
try:
    from playwright.async_api import (
        async_playwright,
        Browser as AsyncBrowser,
        BrowserContext as AsyncBrowserContext,
        Page as AsyncPage,
        Playwright as AsyncPlaywright,
        TimeoutError as PWTimeoutError,
    )
    from playwright.sync_api import (
        sync_playwright,
        Browser as SyncBrowser,
        Page as SyncPage,
    )
    PW_AVAILABLE = True
except ImportError:
    PW_AVAILABLE = False

from tools.utils.cache import cached
from tools.utils.types import ScrapeResult, PageElement, PageContent


# ──────────────────────────────────────────────────────────────────────────────
# Defaults
# ──────────────────────────────────────────────────────────────────────────────
_DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_DEFAULT_TIMEOUT = 30_000   # 30 seconds in ms
_DEFAULT_WAIT    = "networkidle"  # domcontentloaded | load | networkidle


# ──────────────────────────────────────────────────────────────────────────────
# YodelClient
# ──────────────────────────────────────────────────────────────────────────────

class YodelClient:
    """
    Turn any website into a programmable data source using a real browser.

    Uses Playwright (Chromium) under the hood. Handles:
    - JavaScript-heavy SPAs (React, Vue, Angular)
    - Login/session state across multiple requests
    - Form submission and multi-step flows
    - Dynamic content, infinite scroll, and pagination
    - Table extraction directly into DataFrames
    - Screenshot capture for visual verification

    Args:
        headless:       Run browser without GUI. Default True.
        slow_mo:        Slow down browser actions by N ms (useful for debugging).
        timeout:        Default timeout in ms for navigation/selectors. Default 30000.
        user_agent:     Override the browser User-Agent string.
        viewport:       Browser viewport dict {"width": int, "height": int}.
        cookies:        Pre-load cookies as list of dicts (Playwright cookie format).
        proxy:          Proxy server URL, e.g. "http://user:pass@host:port".
        stealth:        Apply basic anti-bot fingerprint patches. Default True.
        storage_state:  Path to a saved Playwright storage state JSON file.
                        Use this to re-use a previously authenticated session.

    Example:
        yodel = YodelClient()

        # Simple page content fetch
        page = yodel.fetch("https://finance.yahoo.com/quote/NVDA/")
        print(page["title"])
        print(page["text"][:500])

        # Scrape a specific element
        items = yodel.scrape("https://example.com/data", selector=".data-row")
        for item in items:
            print(item["text"])

        # Log in and then scrape protected pages
        yodel.login(
            url="https://app.example.com/login",
            fields={
                "#email": "user@example.com",
                "#password": "secret",
            },
            submit="button[type=submit]",
            wait_for="#dashboard",
        )
        data = yodel.scrape("https://app.example.com/portfolio", selector=".position-row")

        # Extract a table into a DataFrame
        df = yodel.table("https://finance.yahoo.com/screener/...", table_index=0)
        print(df.head())
    """

    def __init__(
        self,
        headless: bool = True,
        slow_mo: int = 0,
        timeout: int = _DEFAULT_TIMEOUT,
        user_agent: str = _DEFAULT_UA,
        viewport: Optional[dict] = None,
        cookies: Optional[list[dict]] = None,
        proxy: Optional[str] = None,
        stealth: bool = True,
        storage_state: Optional[str] = None,
    ):
        if not PW_AVAILABLE:
            raise ImportError(
                "playwright is not installed.\n"
                "  Run:  pip install playwright\n"
                "  Then: playwright install chromium"
            )

        self._headless      = headless
        self._slow_mo       = slow_mo
        self._timeout       = timeout
        self._user_agent    = user_agent
        self._viewport      = viewport or {"width": 1440, "height": 900}
        self._init_cookies  = cookies or []
        self._proxy         = proxy
        self._stealth       = stealth
        self._storage_state = storage_state

        # Session state — populated on first use
        self._context: Optional[Any] = None   # AsyncBrowserContext
        self._browser: Optional[Any] = None   # AsyncBrowser
        self._pw:      Optional[Any] = None   # Playwright instance
        self._loop:    Optional[Any] = None   # event loop

    # ──────────────────────────────────────────────
    # PUBLIC API — synchronous wrappers
    # ──────────────────────────────────────────────

    def fetch(
        self,
        url: str,
        wait_until: str = _DEFAULT_WAIT,
        wait_for: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> PageContent:
        """
        Open a URL and return the full rendered page content.

        Args:
            url:        The URL to open.
            wait_until: When to consider navigation complete.
                        "load" | "domcontentloaded" | "networkidle" (default)
            wait_for:   Optional CSS selector to wait for before returning.
            timeout:    Override default timeout (ms).

        Returns:
            PageContent TypedDict with keys:
                - url:          str  (final URL after redirects)
                - title:        str  (page <title>)
                - text:         str  (visible text, whitespace-normalized)
                - html:         str  (full outer HTML)
                - status:       int  (HTTP status code)
                - as_of:        str  (ISO timestamp of when fetch ran)

        Example:
            page = yodel.fetch("https://finance.yahoo.com/quote/NVDA/")
            print(page["title"])
            print(page["text"][:1000])
        """
        return self._run(self._async_fetch(url, wait_until, wait_for, timeout))

    def scrape(
        self,
        url: str,
        selector: str,
        attribute: Optional[str] = None,
        wait_until: str = _DEFAULT_WAIT,
        wait_for: Optional[str] = None,
        limit: int = 500,
        timeout: Optional[int] = None,
    ) -> list[PageElement]:
        """
        Navigate to a URL and extract all elements matching a CSS selector.

        Args:
            url:        The URL to scrape.
            selector:   CSS selector for target elements (e.g. "tr.data-row", ".price").
            attribute:  If set, return this HTML attribute value instead of text content.
                        E.g. "href" to get links, "src" to get image sources.
            wait_until: Navigation wait strategy.
            wait_for:   Optional CSS selector to wait for before extracting.
            limit:      Maximum number of matching elements to return.
            timeout:    Override default timeout (ms).

        Returns:
            List of PageElement dicts:
                - text:      str  (inner text of the element)
                - html:      str  (inner HTML of the element)
                - attribute: str  (value of requested attribute, or "")
                - index:     int  (0-based position in match list)

        Example:
            # Scrape all article titles from a news page
            items = yodel.scrape("https://news.ycombinator.com", selector=".titleline a")
            for item in items[:10]:
                print(item["text"], "→", item["attribute"])  # title + href

            # Get all table row texts
            rows = yodel.scrape("https://example.com/data", selector="table tr")
        """
        return self._run(
            self._async_scrape(url, selector, attribute, wait_until, wait_for, limit, timeout)
        )

    def table(
        self,
        url: str,
        table_index: int = 0,
        selector: Optional[str] = None,
        wait_until: str = _DEFAULT_WAIT,
        wait_for: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        Extract an HTML table from a page directly into a pandas DataFrame.

        Args:
            url:         The URL to load.
            table_index: Which <table> to use (0 = first). Ignored if selector given.
            selector:    CSS selector targeting a specific <table> element.
            wait_until:  Navigation wait strategy.
            wait_for:    Optional CSS selector to wait for before parsing.
            timeout:     Override default timeout (ms).

        Returns:
            pandas DataFrame parsed from the HTML table.
            Returns an empty DataFrame if no table is found.

        Example:
            # Extract the first table on a Wikipedia page
            df = yodel.table("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
            print(df.head())

            # Extract a specific table by selector
            df = yodel.table(
                "https://finance.yahoo.com/screener/...",
                selector="#scr-res-table table",
            )
        """
        return self._run(
            self._async_table(url, table_index, selector, wait_until, wait_for, timeout)
        )

    def form_submit(
        self,
        url: str,
        fields: dict[str, str],
        submit: str,
        wait_for: Optional[str] = None,
        wait_until: str = _DEFAULT_WAIT,
        extract: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> ScrapeResult:
        """
        Navigate to a URL, fill form fields, click submit, and return the result.

        Args:
            url:        URL of the page with the form.
            fields:     Dict of {css_selector: value} to fill in.
                        E.g. {"#search": "NVDA", "#date-from": "2024-01-01"}
            submit:     CSS selector for the submit button/element to click.
            wait_for:   CSS selector to wait for after form submission.
            wait_until: Navigation wait strategy after submit.
            extract:    Optional CSS selector to extract results after submit.
                        If None, returns full page content.
            timeout:    Override default timeout (ms).

        Returns:
            ScrapeResult TypedDict:
                - url:       str  (final URL after form submit)
                - title:     str
                - text:      str  (page text or extracted elements' text joined)
                - html:      str  (page HTML or matched HTML joined)
                - elements:  list[PageElement]  (if extract selector was used)
                - status:    str  ("ok" | "error")
                - error:     str  (error message if status == "error")
                - as_of:     str  (ISO timestamp)

        Example:
            # Submit a search form
            result = yodel.form_submit(
                url="https://efts.sec.gov/LATEST/search-index?q=%22going+concern%22",
                fields={"#query": "going concern"},
                submit="button[type=submit]",
                wait_for=".hits",
                extract=".hit-text",
            )
            print(result["text"])
        """
        return self._run(
            self._async_form_submit(url, fields, submit, wait_for, wait_until, extract, timeout)
        )

    def login(
        self,
        url: str,
        fields: dict[str, str],
        submit: str,
        wait_for: Optional[str] = None,
        success_check: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> dict:
        """
        Authenticate on a site and persist the session for subsequent calls.

        After calling login(), all future YodelClient calls in this instance
        (scrape, fetch, table, form_submit) will use the authenticated session.

        Args:
            url:           Login page URL.
            fields:        Dict of {css_selector: value} to fill in.
                           E.g. {"#email": "user@example.com", "#password": "secret"}
            submit:        CSS selector for the login/submit button.
            wait_for:      CSS selector that appears only when logged in (e.g. "#dashboard").
            success_check: CSS selector or text to verify login succeeded.
            timeout:       Override default timeout (ms).

        Returns:
            Dict with keys:
                - success:     bool
                - url:         str  (final URL after login)
                - cookies:     list[dict]  (session cookies — can be saved and reloaded)
                - error:       str  (error message if success == False)

        Example:
            result = yodel.login(
                url="https://app.example.com/login",
                fields={
                    "input[name=email]":    "user@example.com",
                    "input[name=password]": "secret123",
                },
                submit="button[type=submit]",
                wait_for=".portfolio-overview",
            )
            if result["success"]:
                data = yodel.scrape("https://app.example.com/holdings", ".position")
        """
        return self._run(
            self._async_login(url, fields, submit, wait_for, success_check, timeout)
        )

    def click_and_extract(
        self,
        url: str,
        click: str,
        extract: str,
        wait_for: Optional[str] = None,
        wait_until: str = "networkidle",
        timeout: Optional[int] = None,
    ) -> list[PageElement]:
        """
        Load a page, click an element, then extract results.

        Useful for tabs, dropdowns, "Load More" buttons, accordion sections,
        or any UI element that reveals data after a click.

        Args:
            url:        The URL to open.
            click:      CSS selector for the element to click.
            extract:    CSS selector for elements to extract after the click.
            wait_for:   Optional CSS selector to wait for after click.
            wait_until: Wait strategy (default "networkidle").
            timeout:    Override default timeout (ms).

        Returns:
            List of PageElement dicts from the extract selector.

        Example:
            # Click "Annual" tab then extract table rows
            rows = yodel.click_and_extract(
                url="https://finance.yahoo.com/quote/AAPL/financials/",
                click="button[data-test='annual']",
                extract="tr.row",
                wait_for="table.financials",
            )
        """
        return self._run(
            self._async_click_and_extract(url, click, extract, wait_for, wait_until, timeout)
        )

    def paginate(
        self,
        url: str,
        item_selector: str,
        next_selector: str,
        max_pages: int = 10,
        wait_for: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> list[PageElement]:
        """
        Scrape across multiple pages by clicking a "next page" button.

        Args:
            url:            Starting URL.
            item_selector:  CSS selector for the data items to collect on each page.
            next_selector:  CSS selector for the "next page" link/button.
            max_pages:      Safety cap on how many pages to traverse. Default 10.
            wait_for:       CSS selector to wait for after each page navigation.
            timeout:        Override default timeout (ms).

        Returns:
            Combined list of PageElement dicts from all pages, with an added
            "page" key indicating which page number the element came from.

        Example:
            # Paginate through search results
            all_results = yodel.paginate(
                url="https://efts.sec.gov/LATEST/search-index?q=going+concern",
                item_selector=".search-result",
                next_selector="a[aria-label='Next page']",
                max_pages=5,
            )
            print(f"Collected {len(all_results)} items across pages")
        """
        return self._run(
            self._async_paginate(url, item_selector, next_selector, max_pages, wait_for, timeout)
        )

    def screenshot(
        self,
        url: str,
        path: Optional[str] = None,
        full_page: bool = True,
        wait_until: str = _DEFAULT_WAIT,
        wait_for: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> bytes:
        """
        Capture a screenshot of a rendered web page.

        Args:
            url:        The URL to screenshot.
            path:       Optional file path to save the PNG (e.g. "/tmp/page.png").
                        If None, returns raw bytes only.
            full_page:  Capture the full scrollable page. Default True.
            wait_until: Navigation wait strategy.
            wait_for:   Optional CSS selector to wait for before screenshot.
            timeout:    Override default timeout (ms).

        Returns:
            PNG image as bytes.

        Example:
            png_bytes = yodel.screenshot("https://finance.yahoo.com/quote/NVDA/")

            # Save to file
            yodel.screenshot(
                "https://finance.yahoo.com/quote/AAPL/",
                path="/tmp/aapl_quote.png",
            )
        """
        return self._run(
            self._async_screenshot(url, path, full_page, wait_until, wait_for, timeout)
        )

    def execute(
        self,
        url: str,
        script: str,
        wait_until: str = _DEFAULT_WAIT,
        wait_for: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> Any:
        """
        Run arbitrary JavaScript on a page and return the result.

        The script runs in the browser page context. Use this to extract
        data from window objects, call site APIs, or manipulate the DOM.

        Args:
            url:        The URL to open.
            script:     JavaScript expression to evaluate. Must return a
                        JSON-serializable value.
            wait_until: Navigation wait strategy.
            wait_for:   Optional CSS selector to wait for before executing.
            timeout:    Override default timeout (ms).

        Returns:
            The JavaScript return value (deserialized from JSON).

        Example:
            # Extract data from a JavaScript variable
            result = yodel.execute(
                url="https://finance.yahoo.com/quote/NVDA/",
                script="() => window.YAHOO?.context?.dispatcher?.stores",
            )

            # Count elements
            count = yodel.execute(
                "https://example.com",
                script="() => document.querySelectorAll('table tr').length",
            )
        """
        return self._run(
            self._async_execute(url, script, wait_until, wait_for, timeout)
        )

    def multi_step(
        self,
        steps: list[dict],
        start_url: str,
        timeout: Optional[int] = None,
    ) -> list[dict]:
        """
        Execute a sequence of browser actions as a single flow.

        Each step is a dict describing an action. Steps run in order on
        the same browser page, preserving session/cookie state.

        Supported step types:
            {"action": "navigate",  "url": "https://..."}
            {"action": "click",     "selector": "button#ok"}
            {"action": "fill",      "selector": "#input", "value": "text"}
            {"action": "wait",      "selector": ".result"}  OR  "ms": 2000
            {"action": "extract",   "selector": ".row",  "attribute": "href"}
            {"action": "screenshot","path": "/tmp/step.png"}
            {"action": "js",        "script": "() => window.something"}

        Args:
            steps:      Ordered list of step dicts (see above).
            start_url:  The initial URL to navigate to before running steps.
            timeout:    Override default timeout (ms).

        Returns:
            List of result dicts, one per step that produced output.
            Extract steps include "elements": list[PageElement].
            Screenshot steps include "path" and "bytes" (PNG bytes).
            JS steps include "result": Any.

        Example:
            results = yodel.multi_step(
                start_url="https://app.example.com",
                steps=[
                    {"action": "fill",      "selector": "#ticker", "value": "NVDA"},
                    {"action": "click",     "selector": "#search-btn"},
                    {"action": "wait",      "selector": ".results"},
                    {"action": "extract",   "selector": ".result-row"},
                    {"action": "click",     "selector": "a.next-page"},
                    {"action": "wait",      "ms": 1500},
                    {"action": "extract",   "selector": ".result-row"},
                ],
            )
            for r in results:
                for el in r.get("elements", []):
                    print(el["text"])
        """
        return self._run(self._async_multi_step(steps, start_url, timeout))

    def save_session(self, path: str) -> None:
        """
        Save the current browser session (cookies, localStorage) to a JSON file.
        Load it later with storage_state= in the constructor to skip re-login.

        Args:
            path: File path to write the JSON session to.

        Example:
            yodel.login(...)
            yodel.save_session("/tmp/my_session.json")

            # Next time:
            yodel2 = YodelClient(storage_state="/tmp/my_session.json")
            # Already authenticated — no login needed
        """
        self._run(self._async_save_session(path))

    def close(self) -> None:
        """
        Close the browser and free all resources.

        Called automatically if you use YodelClient as a context manager.

        Example:
            with YodelClient() as yodel:
                page = yodel.fetch("https://example.com")
            # Browser closed automatically
        """
        self._run(self._async_close())

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # ──────────────────────────────────────────────
    # INTERNAL — event loop bridge
    # ──────────────────────────────────────────────

    def _run(self, coro):
        """Run an async coroutine synchronously, reusing the event loop."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Inside an existing event loop (e.g. Jupyter) — use nest_asyncio
                import nest_asyncio
                nest_asyncio.apply()
                return loop.run_until_complete(coro)
            return loop.run_until_complete(coro)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(coro)
            finally:
                pass  # keep loop alive for subsequent calls

    # ──────────────────────────────────────────────
    # INTERNAL — browser lifecycle
    # ──────────────────────────────────────────────

    async def _ensure_context(self) -> AsyncBrowserContext:
        """Lazily start the browser and create a context (reused across calls)."""
        if self._context is not None:
            return self._context

        self._pw      = await async_playwright().start()
        launch_opts   = {"headless": self._headless, "slow_mo": self._slow_mo}
        if self._proxy:
            launch_opts["proxy"] = {"server": self._proxy}

        self._browser = await self._pw.chromium.launch(**launch_opts)

        ctx_opts: dict = {
            "user_agent": self._user_agent,
            "viewport":   self._viewport,
            "locale":     "en-US",
        }
        if self._storage_state:
            ctx_opts["storage_state"] = self._storage_state

        self._context = await self._browser.new_context(**ctx_opts)

        # Inject pre-loaded cookies
        if self._init_cookies:
            await self._context.add_cookies(self._init_cookies)

        # Basic stealth patches
        if self._stealth:
            await self._context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'plugins',   {get: () => [1, 2, 3]});
                Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
                window.chrome = { runtime: {} };
            """)

        return self._context

    async def _new_page(self) -> AsyncPage:
        """Open a fresh page in the shared context."""
        ctx  = await self._ensure_context()
        page = await ctx.new_page()
        page.set_default_timeout(self._timeout)
        return page

    # ──────────────────────────────────────────────
    # INTERNAL — async implementations
    # ──────────────────────────────────────────────

    async def _async_fetch(
        self,
        url: str,
        wait_until: str,
        wait_for: Optional[str],
        timeout: Optional[int],
    ) -> PageContent:
        page   = await self._new_page()
        _to    = timeout or self._timeout
        status = 0
        try:
            resp = await page.goto(url, wait_until=wait_until, timeout=_to)
            status = resp.status if resp else 0
            if wait_for:
                await page.wait_for_selector(wait_for, timeout=_to)
            return PageContent(
                url=page.url,
                title=await page.title(),
                text=_clean_text(await page.inner_text("body")),
                html=await page.content(),
                status=status,
                as_of=_now(),
            )
        finally:
            await page.close()

    async def _async_scrape(
        self,
        url: str,
        selector: str,
        attribute: Optional[str],
        wait_until: str,
        wait_for: Optional[str],
        limit: int,
        timeout: Optional[int],
    ) -> list[PageElement]:
        page = await self._new_page()
        _to  = timeout or self._timeout
        try:
            await page.goto(url, wait_until=wait_until, timeout=_to)
            if wait_for:
                await page.wait_for_selector(wait_for, timeout=_to)
            await page.wait_for_selector(selector, timeout=_to)
            handles = await page.query_selector_all(selector)
            results: list[PageElement] = []
            for i, el in enumerate(handles[:limit]):
                text  = _clean_text(await el.inner_text() or "")
                html  = await el.inner_html() or ""
                attr  = ""
                if attribute:
                    attr = (await el.get_attribute(attribute)) or ""
                results.append(PageElement(text=text, html=html, attribute=attr, index=i))
            return results
        finally:
            await page.close()

    async def _async_table(
        self,
        url: str,
        table_index: int,
        selector: Optional[str],
        wait_until: str,
        wait_for: Optional[str],
        timeout: Optional[int],
    ) -> pd.DataFrame:
        page = await self._new_page()
        _to  = timeout or self._timeout
        try:
            await page.goto(url, wait_until=wait_until, timeout=_to)
            if wait_for:
                await page.wait_for_selector(wait_for, timeout=_to)

            table_selector = selector or "table"
            await page.wait_for_selector(table_selector, timeout=_to)

            if selector:
                table_html = await page.eval_on_selector(
                    selector, "el => el.outerHTML"
                )
            else:
                tables_html = await page.evaluate(
                    """() => Array.from(document.querySelectorAll('table'))
                                .map(t => t.outerHTML)"""
                )
                if not tables_html or table_index >= len(tables_html):
                    return pd.DataFrame()
                table_html = tables_html[table_index]

            dfs = pd.read_html(table_html)
            return dfs[0] if dfs else pd.DataFrame()
        except Exception:
            return pd.DataFrame()
        finally:
            await page.close()

    async def _async_form_submit(
        self,
        url: str,
        fields: dict[str, str],
        submit: str,
        wait_for: Optional[str],
        wait_until: str,
        extract: Optional[str],
        timeout: Optional[int],
    ) -> ScrapeResult:
        page = await self._new_page()
        _to  = timeout or self._timeout
        try:
            await page.goto(url, wait_until=wait_until, timeout=_to)

            for selector, value in fields.items():
                await page.wait_for_selector(selector, timeout=_to)
                await page.fill(selector, value)

            await page.click(submit)

            if wait_for:
                await page.wait_for_selector(wait_for, timeout=_to)
            else:
                await page.wait_for_load_state(wait_until, timeout=_to)

            elements: list[PageElement] = []
            if extract:
                try:
                    handles = await page.query_selector_all(extract)
                    for i, el in enumerate(handles):
                        elements.append(PageElement(
                            text=_clean_text(await el.inner_text() or ""),
                            html=await el.inner_html() or "",
                            attribute="",
                            index=i,
                        ))
                except Exception:
                    pass

            joined_text = "\n".join(e["text"] for e in elements) if elements else \
                          _clean_text(await page.inner_text("body"))
            joined_html = "\n".join(e["html"] for e in elements) if elements else \
                          await page.content()

            return ScrapeResult(
                url=page.url,
                title=await page.title(),
                text=joined_text,
                html=joined_html,
                elements=elements,
                status="ok",
                error="",
                as_of=_now(),
            )
        except Exception as exc:
            return ScrapeResult(
                url=url, title="", text="", html="",
                elements=[], status="error", error=str(exc), as_of=_now(),
            )
        finally:
            await page.close()

    async def _async_login(
        self,
        url: str,
        fields: dict[str, str],
        submit: str,
        wait_for: Optional[str],
        success_check: Optional[str],
        timeout: Optional[int],
    ) -> dict:
        page = await self._new_page()
        _to  = timeout or self._timeout
        try:
            await page.goto(url, wait_until=_DEFAULT_WAIT, timeout=_to)

            for selector, value in fields.items():
                await page.wait_for_selector(selector, timeout=_to)
                await page.fill(selector, value)

            await page.click(submit)

            if wait_for:
                await page.wait_for_selector(wait_for, timeout=_to)
            else:
                await page.wait_for_load_state("networkidle", timeout=_to)

            success = True
            if success_check:
                try:
                    await page.wait_for_selector(success_check, timeout=5_000)
                except Exception:
                    success = False

            ctx     = await self._ensure_context()
            cookies = await ctx.cookies()
            return {
                "success": success,
                "url":     page.url,
                "cookies": cookies,
                "error":   "",
            }
        except Exception as exc:
            return {
                "success": False,
                "url":     url,
                "cookies": [],
                "error":   str(exc),
            }
        finally:
            await page.close()

    async def _async_click_and_extract(
        self,
        url: str,
        click: str,
        extract: str,
        wait_for: Optional[str],
        wait_until: str,
        timeout: Optional[int],
    ) -> list[PageElement]:
        page = await self._new_page()
        _to  = timeout or self._timeout
        try:
            await page.goto(url, wait_until=wait_until, timeout=_to)
            await page.wait_for_selector(click, timeout=_to)
            await page.click(click)
            if wait_for:
                await page.wait_for_selector(wait_for, timeout=_to)
            else:
                await page.wait_for_load_state(wait_until, timeout=_to)
            await page.wait_for_selector(extract, timeout=_to)
            handles = await page.query_selector_all(extract)
            results = []
            for i, el in enumerate(handles):
                results.append(PageElement(
                    text=_clean_text(await el.inner_text() or ""),
                    html=await el.inner_html() or "",
                    attribute="",
                    index=i,
                ))
            return results
        finally:
            await page.close()

    async def _async_paginate(
        self,
        url: str,
        item_selector: str,
        next_selector: str,
        max_pages: int,
        wait_for: Optional[str],
        timeout: Optional[int],
    ) -> list[PageElement]:
        page = await self._new_page()
        _to  = timeout or self._timeout
        all_items: list[PageElement] = []
        page_num = 0
        try:
            await page.goto(url, wait_until=_DEFAULT_WAIT, timeout=_to)
            while page_num < max_pages:
                if wait_for:
                    try:
                        await page.wait_for_selector(wait_for, timeout=_to)
                    except Exception:
                        break
                try:
                    await page.wait_for_selector(item_selector, timeout=_to)
                except Exception:
                    break

                handles = await page.query_selector_all(item_selector)
                for i, el in enumerate(handles):
                    item = PageElement(
                        text=_clean_text(await el.inner_text() or ""),
                        html=await el.inner_html() or "",
                        attribute="",
                        index=len(all_items) + i,
                    )
                    item["page"] = page_num + 1  # type: ignore[typeddict-unknown-key]
                    all_items.append(item)

                page_num += 1

                # Try to click "next" — stop if not found
                try:
                    next_el = await page.query_selector(next_selector)
                    if not next_el:
                        break
                    is_disabled = await next_el.get_attribute("disabled")
                    if is_disabled is not None:
                        break
                    await next_el.click()
                    await page.wait_for_load_state("networkidle", timeout=_to)
                except Exception:
                    break

            return all_items
        finally:
            await page.close()

    async def _async_screenshot(
        self,
        url: str,
        path: Optional[str],
        full_page: bool,
        wait_until: str,
        wait_for: Optional[str],
        timeout: Optional[int],
    ) -> bytes:
        page = await self._new_page()
        _to  = timeout or self._timeout
        try:
            await page.goto(url, wait_until=wait_until, timeout=_to)
            if wait_for:
                await page.wait_for_selector(wait_for, timeout=_to)
            opts: dict = {"full_page": full_page}
            if path:
                opts["path"] = path
            return await page.screenshot(**opts)
        finally:
            await page.close()

    async def _async_execute(
        self,
        url: str,
        script: str,
        wait_until: str,
        wait_for: Optional[str],
        timeout: Optional[int],
    ) -> Any:
        page = await self._new_page()
        _to  = timeout or self._timeout
        try:
            await page.goto(url, wait_until=wait_until, timeout=_to)
            if wait_for:
                await page.wait_for_selector(wait_for, timeout=_to)
            return await page.evaluate(script)
        finally:
            await page.close()

    async def _async_multi_step(
        self,
        steps: list[dict],
        start_url: str,
        timeout: Optional[int],
    ) -> list[dict]:
        page = await self._new_page()
        _to  = timeout or self._timeout
        results: list[dict] = []
        try:
            await page.goto(start_url, wait_until=_DEFAULT_WAIT, timeout=_to)
            for step in steps:
                action = step.get("action", "")
                out: dict = {"action": action}
                try:
                    if action == "navigate":
                        await page.goto(step["url"], wait_until=_DEFAULT_WAIT, timeout=_to)
                        out["url"] = page.url

                    elif action == "click":
                        await page.wait_for_selector(step["selector"], timeout=_to)
                        await page.click(step["selector"])
                        out["clicked"] = step["selector"]

                    elif action == "fill":
                        await page.wait_for_selector(step["selector"], timeout=_to)
                        await page.fill(step["selector"], step.get("value", ""))
                        out["filled"] = step["selector"]

                    elif action == "wait":
                        if "selector" in step:
                            await page.wait_for_selector(step["selector"], timeout=_to)
                            out["waited_for"] = step["selector"]
                        elif "ms" in step:
                            await asyncio.sleep(step["ms"] / 1000)
                            out["waited_ms"] = step["ms"]

                    elif action == "extract":
                        handles = await page.query_selector_all(step["selector"])
                        attr    = step.get("attribute")
                        elements = []
                        for i, el in enumerate(handles):
                            elements.append(PageElement(
                                text=_clean_text(await el.inner_text() or ""),
                                html=await el.inner_html() or "",
                                attribute=(await el.get_attribute(attr) or "") if attr else "",
                                index=i,
                            ))
                        out["elements"] = elements

                    elif action == "screenshot":
                        ss_path = step.get("path")
                        opts: dict = {"full_page": step.get("full_page", True)}
                        if ss_path:
                            opts["path"] = ss_path
                        out["bytes"] = await page.screenshot(**opts)
                        if ss_path:
                            out["path"] = ss_path

                    elif action == "js":
                        out["result"] = await page.evaluate(step["script"])

                    out["status"] = "ok"
                except Exception as exc:
                    out["status"] = "error"
                    out["error"]  = str(exc)

                results.append(out)
            return results
        finally:
            await page.close()

    async def _async_save_session(self, path: str) -> None:
        ctx = await self._ensure_context()
        await ctx.storage_state(path=path)

    async def _async_close(self) -> None:
        if self._context:
            await self._context.close()
            self._context = None
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._pw:
            await self._pw.stop()
            self._pw = None


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _clean_text(raw: str) -> str:
    """Collapse whitespace and strip invisible chars from extracted text."""
    text = re.sub(r"[ \t]+", " ", raw)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _now() -> str:
    """Return current UTC timestamp as ISO string."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
