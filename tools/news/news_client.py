"""
NewsClient — Financial news aggregation
=======================================

Sources:
    1. SEC EDGAR RSS feed (live filings)
    2. Yahoo Finance news (via yfinance)
    3. Financial RSS feeds (Reuters, Bloomberg, FT, etc.)
    4. Finnhub (optional, requires API key)

SETUP:
    from tools.news import NewsClient
    news = NewsClient()

    # Optional: set Finnhub key for enhanced news
    # export FINNHUB_API_KEY="your_key"

REFERENCE: tools/news/README.md
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

import requests
import pandas as pd

try:
    import feedparser
    FEEDPARSER_AVAILABLE = True
except ImportError:
    FEEDPARSER_AVAILABLE = False

try:
    import yfinance as yf
    YF_AVAILABLE = True
except ImportError:
    YF_AVAILABLE = False

from tools.utils.cache import cached
from tools.utils.types import NewsItem


# ─────────────────────────────────────────────────────────────
# SEC EDGAR RSS Endpoints
# ─────────────────────────────────────────────────────────────
_SEC_FULL_RSS = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type={form_type}&dateb=&owner=include&count={count}&search_text=&output=atom"
_SEC_COMPANY_RSS = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company=&CIK={cik_or_ticker}&type={form_type}&dateb=&owner=include&count={count}&search_text=&output=atom"
_SEC_USER_AGENT = "BrickellQuant-Agent research@brickellquant.com"

# ─────────────────────────────────────────────────────────────
# Financial RSS Feeds
# ─────────────────────────────────────────────────────────────
_FINANCIAL_RSS_FEEDS = {
    "MarketWatch":      "https://feeds.marketwatch.com/marketwatch/topstories/",
    "CNBC":             "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "Yahoo Finance":    "https://finance.yahoo.com/rss/topfinstories",
    "Seeking Alpha":    "https://seekingalpha.com/feed.xml",
    "Benzinga":         "https://www.benzinga.com/feed",
    "Investopedia":     "https://www.investopedia.com/feedbuilder/feed/getfeed/?feedName=rss_headline",
    "Barrons":          "https://www.barrons.com/xml/rss/3_7514.xml",
    "WSJ Markets":      "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
}


class NewsClient:
    """
    Financial news aggregator.

    Aggregates from:
    - SEC EDGAR live RSS filings feed
    - Yahoo Finance ticker news
    - Financial RSS feeds (Reuters, MarketWatch, etc.)
    - Finnhub (optional, requires FINNHUB_API_KEY env var)

    Example:
        news = NewsClient()

        # News for a specific ticker
        articles = news.ticker_news("NVDA", limit=10)

        # Live SEC filing feed
        filings = news.sec_rss(form_type="8-K", limit=20)

        # Full briefing for a ticker
        brief = news.summary("TSLA")
    """

    def __init__(self, finnhub_key: Optional[str] = None):
        self._finnhub_key = finnhub_key or os.environ.get("FINNHUB_API_KEY")
        self._headers = {"User-Agent": _SEC_USER_AGENT}

    # ─────────────────────────────────────────────
    # TICKER-SPECIFIC NEWS
    # ─────────────────────────────────────────────

    @cached(ttl=300)
    def ticker_news(self, ticker: str, limit: int = 20) -> list[NewsItem]:
        """
        Get recent news articles for a specific ticker.

        Tries in order: yfinance → Finnhub → empty list

        Args:
            ticker: Stock ticker symbol
            limit: Maximum articles to return

        Returns:
            List of NewsItem dicts with keys:
                - title: str
                - url: str
                - source: str
                - published: str (ISO datetime string)
                - summary: str (may be empty)
                - ticker: str

        Example:
            articles = news.ticker_news("NVDA", limit=10)
            for a in articles:
                print(f"[{a['source']}] {a['title']}")
                print(f"  {a['published']}")
                print(f"  {a['url']}")
        """
        results: list[NewsItem] = []

        # ── yfinance news ──────────────────────────────────────────────
        if YF_AVAILABLE:
            try:
                t = yf.Ticker(ticker.upper())
                raw_news = t.news or []
                for item in raw_news[:limit]:
                    # yfinance ≥1.0 wraps everything inside item["content"] dict
                    c = item.get("content") if isinstance(item.get("content"), dict) else item

                    # Title
                    title = str(c.get("title") or "")

                    # URL — prefer clickThroughUrl, fall back to canonicalUrl or link
                    url = ""
                    for url_key in ("clickThroughUrl", "canonicalUrl"):
                        url_obj = c.get(url_key)
                        if isinstance(url_obj, dict):
                            url = str(url_obj.get("url") or "")
                        elif isinstance(url_obj, str):
                            url = url_obj
                        if url:
                            break
                    if not url:
                        url = str(c.get("link") or item.get("link") or "")

                    # Source / publisher
                    provider = c.get("provider") or {}
                    source = (
                        provider.get("displayName") if isinstance(provider, dict) else None
                    ) or c.get("publisher") or item.get("publisher") or "Yahoo Finance"

                    # Published timestamp
                    published = ""
                    pub_raw = c.get("pubDate") or c.get("displayTime") or ""
                    if pub_raw:
                        published = str(pub_raw)
                    else:
                        ts = item.get("providerPublishTime")
                        if ts:
                            try:
                                published = datetime.fromtimestamp(int(ts)).isoformat()
                            except Exception:
                                published = str(ts)

                    # Summary — strip HTML tags
                    summary = _strip_html(str(c.get("summary") or c.get("description") or ""))

                    if not title:
                        continue  # skip empty entries

                    results.append(
                        NewsItem(
                            title=title,
                            url=url,
                            source=str(source),
                            published=published,
                            summary=summary,
                            ticker=ticker.upper(),
                        )
                    )
            except Exception:
                pass

        # ── Finnhub news (if key available) ───────────────────────────
        if self._finnhub_key and len(results) < limit:
            try:
                from datetime import timedelta
                end = datetime.now()
                start = end - timedelta(days=7)
                url = (
                    f"https://finnhub.io/api/v1/company-news"
                    f"?symbol={ticker.upper()}"
                    f"&from={start.strftime('%Y-%m-%d')}"
                    f"&to={end.strftime('%Y-%m-%d')}"
                    f"&token={self._finnhub_key}"
                )
                resp = requests.get(url, timeout=10)
                if resp.ok:
                    for item in resp.json()[:limit]:
                        published = ""
                        ts = item.get("datetime")
                        if ts:
                            try:
                                published = datetime.fromtimestamp(ts).isoformat()
                            except Exception:
                                published = str(ts)
                        results.append(
                            NewsItem(
                                title=str(item.get("headline") or ""),
                                url=str(item.get("url") or ""),
                                source=str(item.get("source") or "Finnhub"),
                                published=published,
                                summary=str(item.get("summary") or ""),
                                ticker=ticker.upper(),
                            )
                        )
            except Exception:
                pass

        # Deduplicate by URL
        seen_urls: set[str] = set()
        unique: list[NewsItem] = []
        for item in results:
            if item["url"] not in seen_urls:
                seen_urls.add(item["url"])
                unique.append(item)

        return unique[:limit]

    # ─────────────────────────────────────────────
    # SEC EDGAR RSS
    # ─────────────────────────────────────────────

    @cached(ttl=120)
    def sec_rss(
        self,
        form_type: str = "8-K",
        limit: int = 40,
    ) -> list[dict]:
        """
        Pull the live SEC EDGAR RSS feed for a specific form type.

        This is a real-time stream of new filings — no ticker needed.

        Args:
            form_type: SEC form type ("8-K", "10-K", "10-Q", "4", "S-1", "13F-HR", etc.)
            limit: Max filings to return

        Returns:
            List of dicts with keys:
                - title: str
                - company: str
                - form_type: str
                - published: str
                - description: str (may include item numbers for 8-K)
                - url: str (link to SEC filing index)
                - cik: str

        Example:
            # Watch live 8-K filings
            filings = news.sec_rss(form_type="8-K", limit=20)
            for f in filings:
                print(f"{f['company']:40s} {f['form_type']} {f['published']}")

            # Watch S-1 filings (IPO pipeline)
            ipos = news.sec_rss(form_type="S-1", limit=10)

            # Watch Form 4 (insider trades)
            insider_feeds = news.sec_rss(form_type="4", limit=30)
        """
        if not FEEDPARSER_AVAILABLE:
            return [{"error": "feedparser not installed. Run: pip install feedparser"}]

        url = _SEC_FULL_RSS.format(form_type=form_type, count=limit)
        try:
            feed = feedparser.parse(url, request_headers={"User-Agent": _SEC_USER_AGENT})
            results = []
            for entry in feed.entries[:limit]:
                results.append(
                    {
                        "title": str(entry.get("title", "")),
                        "company": _extract_company_from_title(str(entry.get("title", ""))),
                        "form_type": form_type,
                        "published": str(entry.get("published", entry.get("updated", ""))),
                        "description": str(entry.get("summary", "")),
                        "url": str(entry.get("link", "")),
                        "cik": _extract_cik_from_url(str(entry.get("link", ""))),
                    }
                )
            return results
        except Exception as e:
            return [{"error": str(e), "form_type": form_type}]

    @cached(ttl=300)
    def sec_company_rss(
        self,
        ticker: str,
        form_type: str = "",
        limit: int = 20,
    ) -> list[dict]:
        """
        Get SEC EDGAR filing RSS feed for a specific company.

        Args:
            ticker: Stock ticker OR CIK number
            form_type: Filter by form type (empty = all types)
            limit: Max filings to return

        Returns:
            Same structure as sec_rss()

        Example:
            # All recent filings for Apple
            filings = news.sec_company_rss("AAPL", limit=10)

            # Only 10-K filings for Tesla
            tenks = news.sec_company_rss("TSLA", form_type="10-K")

            # Using CIK instead of ticker
            filings = news.sec_company_rss("0000320193")  # Apple CIK
        """
        if not FEEDPARSER_AVAILABLE:
            return [{"error": "feedparser not installed"}]

        url = _SEC_COMPANY_RSS.format(
            cik_or_ticker=ticker,
            form_type=form_type,
            count=limit,
        )
        try:
            feed = feedparser.parse(url, request_headers={"User-Agent": _SEC_USER_AGENT})
            results = []
            for entry in feed.entries[:limit]:
                raw_title = str(entry.get("title", ""))
                results.append(
                    {
                        "title": raw_title,
                        "company": _extract_company_from_title(raw_title),
                        "form_type": _extract_form_type_from_title(raw_title) or form_type,
                        "published": str(entry.get("published", entry.get("updated", ""))),
                        "description": str(entry.get("summary", "")),
                        "url": str(entry.get("link", "")),
                        "cik": _extract_cik_from_url(str(entry.get("link", ""))),
                        "ticker": ticker.upper(),
                    }
                )
            return results
        except Exception as e:
            return [{"error": str(e)}]

    # ─────────────────────────────────────────────
    # MARKET HEADLINES (RSS)
    # ─────────────────────────────────────────────

    @cached(ttl=300)
    def market_headlines(
        self,
        sources: Optional[list[str]] = None,
        limit: int = 30,
    ) -> list[NewsItem]:
        """
        Aggregate market headlines from financial RSS feeds.

        Args:
            sources: List of source names from available feeds:
                     "MarketWatch", "CNBC", "Yahoo Finance", "Seeking Alpha",
                     "Benzinga", "Investopedia", "Barrons", "WSJ Markets"
                     None = use all sources
            limit: Total max articles across all sources

        Returns:
            List of NewsItem dicts sorted by publication date (newest first)

        Example:
            # All sources, top 20
            headlines = news.market_headlines(limit=20)

            # Just Reuters and CNBC
            headlines = news.market_headlines(
                sources=["Reuters Business", "CNBC"],
                limit=10
            )
        """
        if not FEEDPARSER_AVAILABLE:
            return []

        feeds_to_use = {
            k: v for k, v in _FINANCIAL_RSS_FEEDS.items()
            if sources is None or k in sources
        }

        results: list[NewsItem] = []
        per_feed_limit = max(5, limit // max(len(feeds_to_use), 1))

        for source_name, feed_url in feeds_to_use.items():
            try:
                feed = feedparser.parse(feed_url)
                for entry in feed.entries[:per_feed_limit]:
                    published_parsed = entry.get("published_parsed") or entry.get("updated_parsed")
                    published_str = ""
                    if published_parsed:
                        try:
                            published_str = datetime(*published_parsed[:6]).isoformat()
                        except Exception:
                            published_str = str(published_parsed)

                    results.append(
                        NewsItem(
                            title=str(entry.get("title", "")),
                            url=str(entry.get("link", "")),
                            source=source_name,
                            published=published_str,
                            summary=_strip_html(str(entry.get("summary", ""))),
                            ticker="",
                        )
                    )
            except Exception:
                continue

        # Sort by published date, newest first
        results.sort(key=lambda x: x["published"], reverse=True)
        return results[:limit]

    # ─────────────────────────────────────────────
    # SEARCH
    # ─────────────────────────────────────────────

    @cached(ttl=300)
    def search(
        self,
        query: str,
        sources: Optional[list[str]] = None,
        limit: int = 20,
    ) -> list[NewsItem]:
        """
        Search news by keyword across all available sources.

        Args:
            query: Search terms (case-insensitive)
            sources: Optional list of source names to search
            limit: Max results

        Returns:
            List of NewsItem dicts where title or summary contains query terms

        Example:
            results = news.search("Federal Reserve interest rates")
            results = news.search("NVDA earnings", limit=5)
        """
        all_news = self.market_headlines(sources=sources, limit=200)
        query_lower = query.lower()

        matched = [
            item for item in all_news
            if query_lower in item["title"].lower()
            or query_lower in item["summary"].lower()
        ]

        return matched[:limit]

    # ─────────────────────────────────────────────
    # COMBINED SUMMARY
    # ─────────────────────────────────────────────

    @cached(ttl=300)
    def summary(self, ticker: str, limit: int = 10) -> dict:
        """
        Combined news + SEC filings briefing for a ticker.

        Args:
            ticker: Stock ticker symbol
            limit: Max items per source

        Returns:
            Dict with keys:
                - ticker: str
                - news: list[NewsItem]          ← Yahoo Finance news
                - sec_filings: list[dict]        ← Company SEC filings
                - market_news: list[NewsItem]    ← Related market headlines
                - as_of: str (ISO timestamp)

        Example:
            brief = news.summary("TSLA", limit=5)
            print(f"Ticker: {brief['ticker']}")
            print(f"News: {len(brief['news'])} articles")
            print(f"SEC filings: {len(brief['sec_filings'])} filings")

            for article in brief['news']:
                print(f"  [{article['source']}] {article['title']}")

            for filing in brief['sec_filings']:
                print(f"  {filing['form_type']} — {filing['published']}")
        """
        return {
            "ticker": ticker.upper(),
            "news": self.ticker_news(ticker, limit=limit),
            "sec_filings": self.sec_company_rss(ticker, limit=limit),
            "market_news": self.search(ticker.upper(), limit=5),
            "as_of": datetime.now().isoformat(),
        }

    # ─────────────────────────────────────────────
    # AVAILABLE SOURCES
    # ─────────────────────────────────────────────

    def available_rss_sources(self) -> dict[str, str]:
        """
        Return all available RSS feed sources and their URLs.

        Returns:
            Dict of {source_name: url}

        Example:
            sources = news.available_rss_sources()
            for name, url in sources.items():
                print(f"{name}: {url}")
        """
        return dict(_FINANCIAL_RSS_FEEDS)


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def _extract_company_from_title(title: str) -> str:
    """Extract company name from SEC RSS title like '10-K - APPLE INC (0000320193)'"""
    import re
    # Pattern: "FORM_TYPE - COMPANY NAME (CIK)"
    match = re.search(r"-\s+(.+?)\s*\(", title)
    if match:
        return match.group(1).strip()
    return title


def _extract_form_type_from_title(title: str) -> str:
    """Extract form type from SEC RSS title."""
    import re
    match = re.match(r"^([A-Z0-9\-/]+)\s", title)
    if match:
        return match.group(1).strip()
    return ""


def _extract_cik_from_url(url: str) -> str:
    """Extract CIK from SEC EDGAR URL."""
    import re
    match = re.search(r"CIK=(\d+)", url, re.IGNORECASE)
    if match:
        return match.group(1)
    return ""


def _strip_html(text: str) -> str:
    """Remove HTML tags from text."""
    import re
    clean = re.compile(r"<[^>]+>")
    return clean.sub("", text).strip()[:500]
