"""
autopilot — Python library for the Autopilot Marketplace
=========================================================
Scrapes and queries public portfolio data from https://marketplace.joinautopilot.com

HOW IT WORKS:
    The marketplace is a Next.js App Router app (Vercel + Cloudflare).
    All public portfolio pages embed data in the RSC (React Server Component)
    payload — accessible without auth via the "RSC: 1" header.

    Request layer (in order of preference):
      1. curl_cffi  — TLS fingerprint impersonation (Chrome/Safari/Firefox/Edge)
                      Bypasses JA3/JA4 bot detection, looks like a real browser
      2. subprocess curl — System curl with native TLS stack
      3. httpx — Plain fallback (detectable by advanced bot systems)

    Backend API:  https://api.iris.finance/graphql  (GraphQL — 403 without auth)
    Public data:  marketplace.joinautopilot.com RSC payload (no auth needed)
    Media:        storage.googleapis.com/iris-main-prod  (public GCS)

PUBLICLY ACCESSIBLE DATA (no login):
    ✅ All portfolio metadata (title, description, images, team)
    ✅ Total AUM per portfolio
    ✅ Full daily return history (ALL_TIME, 1W, 1M, 3M, 6M, 1Y, 2Y)
    ✅ Leaderboard rankings by all time spans
    ✅ Featured & popular portfolios
    ✅ All team/pilot metadata
    ✅ 36 active portfolio pages + sitemap

WHAT REQUIRES AUTH (GraphQL — 403 without token):
    ❌ Payout data (NEXT_PAYOUT_AMOUNT, ARR, AUM_PAID)
    ❌ Subscriber/follower counts
    ❌ Individual user accounts
    ❌ Holdings/positions detail
    ❌ Trade execution history

USAGE:
    from tools.autopilot import AutopilotClient, AutopilotDB

    # Get full marketplace (featured, popular, leaderboard, all teams)
    client = AutopilotClient()
    listing = client.get_marketplace()
    print(listing.summary())

    # One specific portfolio with full daily history
    p = client.get_portfolio(team_key=1, portfolio_key=8735)
    print(p.summary())

    # All portfolios from sitemap
    for p in client.iter_all_portfolios(verbose=True):
        print(f"{p.title}: ${p.total_aum:,.0f} AUM | {p.all_time_return():.1f}% all-time")

    # Custom impersonation / proxy
    client = AutopilotClient(
        impersonate="safari180",        # or "chrome136", "firefox135", etc.
        proxy="socks5://127.0.0.1:9050",
        delay=0.5,
    )

    # Save everything to SQLite
    db = AutopilotDB("autopilot.db")
    client.sync_all(db, verbose=True)

    # Query the DB
    db.top_portfolios_by_aum(10)
    db.top_portfolios_by_performance("ONE_YEAR", n=5)
    df = db.get_daily_returns_df(8735, span="ALL_TIME")
"""

from .client  import AutopilotClient
from .db      import AutopilotDB
from .models  import (
    DailyReturn,
    FeaturedPortfolio,
    LeaderboardEntry,
    MarketplaceListing,
    PerformanceData,
    PerformanceSpan,
    PerformanceMethodType,
    PopularPortfolio,
    Portfolio,
    SitemapEntry,
    Team,
)
from .scraper import Scraper

__all__ = [
    # Main entry points
    "AutopilotClient",
    "AutopilotDB",
    "Scraper",
    # Models
    "Portfolio",
    "Team",
    "PerformanceData",
    "DailyReturn",
    "LeaderboardEntry",
    "FeaturedPortfolio",
    "PopularPortfolio",
    "MarketplaceListing",
    "SitemapEntry",
    # Enums
    "PerformanceSpan",
    "PerformanceMethodType",
]

__version__ = "0.1.0"
