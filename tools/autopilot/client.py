"""
autopilot.client — Main AutopilotClient

Entry point for all public data access on marketplace.joinautopilot.com.

Architecture:
  - All requests go through the Scraper (curl_cffi TLS impersonation → curl → httpx)
  - Public portfolio data comes from the Next.js RSC payload (no auth needed)
  - The GraphQL API (api.iris.finance/graphql) requires auth — not used here
  - SQLite storage via AutopilotDB (optional, pass db= to sync methods)
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional

from .models import (
    DailyReturn,
    FeaturedPortfolio,
    LeaderboardEntry,
    MarketplaceListing,
    PerformanceData,
    PopularPortfolio,
    Portfolio,
    SitemapEntry,
    Team,
)
from .scraper import Scraper, parse_rsc_payload, parse_sitemap

# ── Defaults ──────────────────────────────────────────────────────────────────

_BASE = "https://marketplace.joinautopilot.com"
_DEFAULT_DELAY   = 0.35   # seconds between requests
_DEFAULT_TIMEOUT = 20     # seconds


class AutopilotClient:
    """
    Client for the Autopilot Marketplace public data.

    Scrapes portfolio performance, AUM, leaderboard, teams, and daily
    return history — all without authentication.

    Args:
        impersonate:    Force a specific browser TLS fingerprint target.
                        e.g. "chrome131", "safari180", "firefox135"
                        Default: rotates randomly.
        rotate_targets: Rotate TLS impersonation target per request. Default True.
        delay:          Seconds between requests. Default 0.35.
        timeout:        Request timeout in seconds. Default 20.
        proxy:          Optional proxy URL. e.g. "http://user:pass@host:1080"
                        or "socks5://user:pass@host:1080"
        max_retries:    Retry count on failure. Default 2.

    Example:
        from tools.autopilot import AutopilotClient

        client = AutopilotClient()

        # Get full marketplace listing (featured, popular, leaderboard, teams)
        listing = client.get_marketplace()
        print(listing.summary())

        # Get a specific portfolio with all daily return data
        p = client.get_portfolio(team_key=1, portfolio_key=8735)
        print(p.summary())
        print(f"1-Year return: {p.one_year_return():.1f}%")

        # Scrape all 36 portfolios from the sitemap
        for portfolio in client.iter_all_portfolios(delay=0.5):
            print(f"{portfolio.title}: AUM=${portfolio.total_aum:,.0f}")

        # Save to SQLite
        from tools.autopilot import AutopilotDB
        db = AutopilotDB("autopilot.db")
        client.sync_all(db, verbose=True)
    """

    def __init__(
        self,
        impersonate: Optional[str] = None,
        rotate_targets: bool = True,
        delay: float = _DEFAULT_DELAY,
        timeout: int = _DEFAULT_TIMEOUT,
        proxy: Optional[str] = None,
        max_retries: int = 2,
    ):
        self._scraper = Scraper(
            impersonate=impersonate,
            rotate_targets=rotate_targets,
            delay=delay,
            timeout=timeout,
            proxy=proxy,
            max_retries=max_retries,
        )

    # ── Sitemap ───────────────────────────────────────────────────────────────

    def get_sitemap(self) -> List[SitemapEntry]:
        """
        Fetch the sitemap and return all portfolio landing page entries.

        Returns:
            List of SitemapEntry with (url, team_key, portfolio_key, last_mod).

        Example:
            entries = client.get_sitemap()
            print(f"{len(entries)} portfolios in sitemap")
            for e in entries:
                print(f"  /landing/{e.team_key}/{e.portfolio_key}")
        """
        status, body = self._scraper.get_sitemap()
        if status != 200:
            raise RuntimeError(f"Sitemap fetch failed: HTTP {status}")
        raw = parse_sitemap(body)
        return [
            SitemapEntry(
                url=e["url"],
                team_key=e["team_key"],
                portfolio_key=e["portfolio_key"],
                last_mod=e.get("last_mod"),
            )
            for e in raw
        ]

    # ── Marketplace listing ───────────────────────────────────────────────────

    def get_marketplace(self) -> MarketplaceListing:
        """
        Fetch the main landing page and return the full marketplace listing.

        Includes:
          - Featured portfolios (hero section)
          - Popular portfolios with AUM ranking
          - Leaderboard for 6 time spans (1W, 1M, 3M, 6M, 1Y, 2Y)
          - All teams with portfolio counts

        Returns:
            MarketplaceListing dataclass.

        Example:
            listing = client.get_marketplace()

            # See top performers by span
            for e in listing.top_by_span("ONE_YEAR", n=5):
                print(f"#{e.rank} {e.title}: {e.span_performance_pct:+.1f}%")

            # List all teams
            for team in listing.teams:
                print(f"{team.title} ({team.portfolio_count} portfolios)")
        """
        status, body = self._scraper.get_rsc("/landing")
        if status != 200:
            raise RuntimeError(f"Marketplace fetch failed: HTTP {status}")

        parsed = parse_rsc_payload(body)
        return self._build_marketplace_listing(parsed)

    def get_leaderboard(self) -> Dict[str, List[LeaderboardEntry]]:
        """
        Get leaderboard rankings for all time spans.

        Returns:
            Dict keyed by span name → sorted list of LeaderboardEntry.
            Spans: ONE_WEEK, ONE_MONTH, THREE_MONTH, SIX_MONTH, ONE_YEAR, TWO_YEAR

        Example:
            lb = client.get_leaderboard()
            for entry in lb.get("ONE_YEAR", []):
                print(f"#{entry.rank} {entry.title}: {entry.span_performance_pct:+.1f}%")
        """
        listing = self.get_marketplace()
        return listing.leaderboard

    def get_teams(self) -> List[Team]:
        """
        Get all teams (Pilots) listed on the marketplace.

        Returns:
            List of Team with team_key, title, company_image_url, portfolio_count.

        Example:
            teams = client.get_teams()
            for t in sorted(teams, key=lambda x: x.portfolio_count or 0, reverse=True):
                print(f"{t.title}: {t.portfolio_count} portfolios")
        """
        listing = self.get_marketplace()
        return listing.teams

    # ── Individual portfolios ─────────────────────────────────────────────────

    def get_portfolio(self, team_key: int, portfolio_key: int) -> Portfolio:
        """
        Fetch a single portfolio with full daily performance history.

        Args:
            team_key:      The team's numeric key (from sitemap or marketplace listing).
            portfolio_key: The portfolio's numeric key.

        Returns:
            Portfolio with all available performance spans and daily return series.

        Raises:
            RuntimeError: If the page returns a non-200 status.

        Example:
            p = client.get_portfolio(team_key=1, portfolio_key=8735)
            print(p.summary())

            # Iterate daily returns for ALL_TIME
            for day in p.get_span("ALL_TIME").cumulative_performance:
                print(day.date.date(), f"{day.cumulative_pct:+.2f}%")
        """
        path   = f"/landing/{team_key}/{portfolio_key}"
        status, body = self._scraper.get_rsc(path)
        if status != 200:
            raise RuntimeError(f"Portfolio {portfolio_key} fetch failed: HTTP {status}")

        parsed = parse_rsc_payload(body)
        raw    = parsed.get("portfolio")
        if not raw:
            raise RuntimeError(f"No portfolio data found in RSC payload for {path}")

        # Build the portfolio — inject team_key from the URL if the RSC team dict omits it
        portfolio = Portfolio.from_rsc_payload({"portfolio": raw})
        if portfolio.team.team_key == 0:
            portfolio.team.team_key = team_key
        return portfolio

    def get_portfolio_by_url(self, landing_url: str) -> Portfolio:
        """
        Fetch a portfolio given its full landing URL.

        Args:
            landing_url: e.g. "https://marketplace.joinautopilot.com/landing/1/8735"

        Example:
            p = client.get_portfolio_by_url("https://marketplace.joinautopilot.com/landing/1/8735")
        """
        import re
        m = re.search(r"/landing/(\d+)/(\d+)", landing_url)
        if not m:
            raise ValueError(f"Cannot extract team/portfolio keys from URL: {landing_url}")
        return self.get_portfolio(int(m.group(1)), int(m.group(2)))

    def iter_all_portfolios(
        self,
        delay: Optional[float] = None,
        verbose: bool = False,
    ) -> Iterator[Portfolio]:
        """
        Iterate over every portfolio in the sitemap, fetching each one.

        Yields portfolios one at a time — memory efficient for large sets.

        Args:
            delay:   Override per-request delay in seconds.
            verbose: Print progress to stdout.

        Yields:
            Portfolio instances with full daily return history.

        Example:
            for p in client.iter_all_portfolios(verbose=True):
                print(f"{p.title}: {p.all_time_return():.1f}% all-time")
        """
        if delay is not None:
            self._scraper.delay = delay

        entries = self.get_sitemap()
        total   = len(entries)

        for i, entry in enumerate(entries, 1):
            if verbose:
                print(f"  [{i}/{total}] Fetching {entry.portfolio_key} ({entry.team_key})...")
            try:
                yield self.get_portfolio(entry.team_key, entry.portfolio_key)
            except Exception as exc:
                if verbose:
                    print(f"    ⚠ Error: {exc}")

    def get_all_portfolios(
        self,
        delay: Optional[float] = None,
        verbose: bool = False,
    ) -> List[Portfolio]:
        """
        Fetch all portfolios from the sitemap and return as a list.

        Convenience wrapper around iter_all_portfolios().
        For large sets, prefer iter_all_portfolios() to save memory.

        Example:
            portfolios = client.get_all_portfolios(verbose=True)
            portfolios.sort(key=lambda p: p.all_time_return() or 0, reverse=True)
            for p in portfolios[:5]:
                print(f"{p.title}: {p.all_time_return():.1f}%")
        """
        return list(self.iter_all_portfolios(delay=delay, verbose=verbose))

    # ── Sync to database ──────────────────────────────────────────────────────

    def sync_marketplace(self, db: Any, verbose: bool = False) -> int:
        """
        Sync the marketplace listing (featured, popular, leaderboard, teams) to DB.

        Args:
            db:      AutopilotDB instance.
            verbose: Print progress.

        Returns:
            Number of records upserted.
        """
        if verbose:
            print("Syncing marketplace listing...")
        listing = self.get_marketplace()
        now     = listing.fetched_at
        count   = 0

        for team in listing.teams:
            db.upsert_team(team)
            count += 1

        for fp in listing.featured_portfolios:
            db.upsert_featured(fp)
            count += 1

        for pp in listing.popular_portfolios:
            db.upsert_popular(pp)
            count += 1

        for span, entries in listing.leaderboard.items():
            for entry in entries:
                db.upsert_leaderboard_entry(entry, snapshot_at=now.isoformat())
                count += 1

        if verbose:
            print(f"  ✓ {count} marketplace records synced")
        return count

    def sync_all(
        self,
        db: Any,
        delay: float = 0.5,
        verbose: bool = True,
    ) -> Dict[str, int]:
        """
        Full sync: marketplace listing + all portfolio pages → SQLite.

        Args:
            db:      AutopilotDB instance.
            delay:   Seconds between portfolio fetches. Default 0.5.
            verbose: Print progress.

        Returns:
            Dict with counts: {"marketplace": N, "portfolios": N, "daily_returns": N}

        Example:
            from tools.autopilot import AutopilotClient, AutopilotDB
            client = AutopilotClient()
            db = AutopilotDB("autopilot.db")
            counts = client.sync_all(db, verbose=True)
            print(counts)
        """
        counts = {"marketplace": 0, "portfolios": 0, "daily_returns": 0}

        # 1. Marketplace listing
        counts["marketplace"] = self.sync_marketplace(db, verbose=verbose)

        # 2. All portfolios
        if verbose:
            print("\nSyncing all portfolio pages...")

        for portfolio in self.iter_all_portfolios(delay=delay, verbose=verbose):
            db.upsert_portfolio(portfolio, include_daily=True)
            counts["portfolios"] += 1
            for perf in portfolio.performance.values():
                counts["daily_returns"] += len(perf.cumulative_performance)

        if verbose:
            print(f"\n✅ Sync complete:")
            for k, v in counts.items():
                print(f"   {k}: {v:,}")

        return counts

    # ── Helper builders ───────────────────────────────────────────────────────

    def _build_marketplace_listing(self, parsed: Dict[str, Any]) -> MarketplaceListing:
        """Convert raw parsed RSC data into MarketplaceListing."""
        now = datetime.now(timezone.utc)

        # Teams
        teams = [Team.from_dict(t) for t in parsed.get("teams", [])]

        # Featured
        featured = [FeaturedPortfolio.from_dict(f) for f in parsed.get("featured_portfolios", [])]

        # Popular
        popular = [PopularPortfolio.from_dict(p) for p in parsed.get("popular_portfolios", [])]

        # Leaderboard — organized by span
        lb_raw = parsed.get("leaderboard", {})
        leaderboard: Dict[str, List[LeaderboardEntry]] = {}
        for span, entries in lb_raw.items():
            leaderboard[span] = [
                LeaderboardEntry.from_dict(span, rank + 1, e)
                for rank, e in enumerate(entries)
            ]

        return MarketplaceListing(
            featured_portfolios=featured,
            popular_portfolios=popular,
            leaderboard=leaderboard,
            teams=teams,
            fetched_at=now,
        )

    # ── Context manager ───────────────────────────────────────────────────────

    def close(self):
        self._scraper.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
