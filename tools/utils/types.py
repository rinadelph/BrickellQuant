"""
tools.utils.types — Shared TypedDicts and dataclasses
"""

from __future__ import annotations

from typing import Optional
try:
    from typing import TypedDict
except ImportError:
    from typing_extensions import TypedDict


class PriceQuote(TypedDict):
    """Returned by MarketClient.price()"""
    ticker: str
    price: float
    open: float
    high: float
    low: float
    prev_close: float
    change: float
    change_pct: float
    volume: int
    avg_volume: int
    market_cap: float
    market_cap_fmt: str
    fifty_two_week_high: float
    fifty_two_week_low: float
    currency: str
    exchange: str


class NewsItem(TypedDict):
    """Returned by NewsClient methods"""
    title: str
    url: str
    source: str
    published: str
    summary: str
    ticker: str


class FilingResult(TypedDict):
    """Returned by SECClient.filings()"""
    accession_number: str
    form_type: str
    filing_date: str
    period_of_report: str
    company: str
    cik: str
    url: str


class DilutionSnapshot(TypedDict):
    """Returned by SECClient.dilution_snapshot()"""
    ticker: str
    basic_shares_out: float        # millions
    options_shares: float          # millions
    rsu_shares: float              # millions
    warrant_shares: float          # millions
    convertible_shares: float      # millions
    atm_remaining_shares: float    # millions
    fully_diluted_shares: float    # millions
    total_dilution_pct: float      # percentage
    risk_level: str                # LOW | MEDIUM | HIGH | CRITICAL
    source_filing: str
    as_of_date: str


class InsiderTrade(TypedDict):
    """Row in SECClient.insider_trades() DataFrame"""
    date: str
    insider: str
    title: str
    transaction: str     # "Purchase" | "Sale" | "Option Exercise" | etc.
    shares: float
    price: float
    value: float
    is_10b5_1: bool
    form_url: str


class RedFlag(TypedDict):
    """Item in SECClient.red_flags() list"""
    type: str            # "AUDITOR_CHANGE" | "NON_RELIANCE" | "GOING_CONCERN" | etc.
    severity: str        # "CRITICAL" | "HIGH" | "MEDIUM"
    description: str
    filing_date: str
    filing_url: str


# ── Yodel (Playwright browser-as-API) ─────────────────────────────────────────

class PageContent(TypedDict):
    """Returned by YodelClient.fetch()"""
    url: str            # Final URL after redirects
    title: str          # Page <title> text
    text: str           # Visible body text (whitespace-normalized)
    html: str           # Full outer HTML
    status: int         # HTTP status code
    as_of: str          # ISO timestamp when fetched


class PageElement(TypedDict):
    """Single extracted DOM element — returned in lists by YodelClient methods"""
    text: str           # Inner text of the element
    html: str           # Inner HTML of the element
    attribute: str      # Value of the requested attribute (e.g. href, src) or ""
    index: int          # 0-based position in the match list


class ScrapeResult(TypedDict):
    """Returned by YodelClient.form_submit()"""
    url: str            # Final URL after form submit
    title: str          # Page title
    text: str           # Joined text content (from extract selector or full page)
    html: str           # Joined HTML content (from extract selector or full page)
    elements: list      # list[PageElement] — populated when extract= selector used
    status: str         # "ok" | "error"
    error: str          # Error message if status == "error", else ""
    as_of: str          # ISO timestamp
