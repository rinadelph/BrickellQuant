"""
autopilot.models — Data structures for Autopilot Marketplace

All fields reflect what is actually returned by the RSC payload at:
  https://marketplace.joinautopilot.com/landing/{team_key}/{portfolio_key}

No authentication is required for any of these fields.

Internal enums found in the JS bundle (not publicly queryable, but reveals backend schema):
  PayoutStatus:       CLAIMED | PENDING_CLAIM | PENDING_PAYMENT
  MetricType:         ARR | AUM | AUM_PAID | NEXT_PAYOUT_AMOUNT | SUBSCRIBERS | ORDERS_*
  AccountType:        INDIVIDUAL | ROTH_IRA | TRADITIONAL_IRA | ROLLOVER_IRA | SEP_IRA | ...
  BrokerType:         ROBINHOOD | SCHWAB | FIDELITY | ETRADE | IBKR | WEBULL | ALPACA | ...
  SubscriptionStatus: ACTIVE | CANCELLED | INCOMPLETE | PAST_DUE | TRIALING | UNPAID
  AdminRole:          AUTOPILOT_ADMIN | COMPLIANCE_OFFICER | CUSTOMER_SERVICE | DEVELOPER
  PerformanceMethod:  TWR_NORMALIZED (simulated) | TWR_NORMALIZED_CLIENT_AGG (real)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from enum import Enum


# ── Enums ─────────────────────────────────────────────────────────────────────

class PerformanceSpan(str, Enum):
    """Time spans available for performance data."""
    ALL_TIME    = "ALL_TIME"
    ONE_WEEK    = "ONE_WEEK"
    ONE_MONTH   = "ONE_MONTH"
    THREE_MONTH = "THREE_MONTH"
    SIX_MONTH   = "SIX_MONTH"
    ONE_YEAR    = "ONE_YEAR"
    TWO_YEAR    = "TWO_YEAR"
    YTD         = "YTD"


class PerformanceMethodType(str, Enum):
    """How portfolio performance is calculated and sourced."""
    TWR_NORMALIZED           = "TWR_NORMALIZED"            # Simulated back-test
    TWR_NORMALIZED_CLIENT_AGG = "TWR_NORMALIZED_CLIENT_AGG" # Real client aggregate


# ── Core models ───────────────────────────────────────────────────────────────

@dataclass
class DailyReturn:
    """A single daily data point in a cumulative performance series."""
    date: datetime
    daily_return: float    # That day's return (decimal)
    cumulative: float      # Running cumulative return from series start (decimal)

    @property
    def daily_return_pct(self) -> float:
        return self.daily_return * 100

    @property
    def cumulative_pct(self) -> float:
        return self.cumulative * 100

    @classmethod
    def from_dict(cls, d: dict) -> "DailyReturn":
        raw_date = d["date"]
        # Handle both "2026-02-11T08:00:00.000Z" and "+00:00" variants
        if raw_date.endswith("Z"):
            raw_date = raw_date[:-1] + "+00:00"
        return cls(
            date=datetime.fromisoformat(raw_date),
            daily_return=d.get("dailyReturn", 0.0),
            cumulative=d.get("return", 0.0),
        )

    def to_dict(self) -> dict:
        return {
            "date": self.date.isoformat(),
            "daily_return": self.daily_return,
            "cumulative": self.cumulative,
        }


@dataclass
class PerformanceData:
    """Performance over a specific time span, with the full daily history."""
    span: str                                           # e.g. "ALL_TIME", "ONE_YEAR"
    span_performance: float                             # Total return for this span (decimal)
    cumulative_performance: List[DailyReturn] = field(default_factory=list)

    @property
    def span_performance_pct(self) -> float:
        """Return as percentage, e.g. 18.4"""
        return self.span_performance * 100

    @property
    def num_data_points(self) -> int:
        return len(self.cumulative_performance)

    @property
    def start_date(self) -> Optional[datetime]:
        return self.cumulative_performance[0].date if self.cumulative_performance else None

    @property
    def end_date(self) -> Optional[datetime]:
        return self.cumulative_performance[-1].date if self.cumulative_performance else None

    @classmethod
    def from_dict(cls, d: dict) -> "PerformanceData":
        return cls(
            span=d["span"],
            span_performance=d.get("spanPerformance", 0.0),
            cumulative_performance=[
                DailyReturn.from_dict(p)
                for p in d.get("cumulativePerformance", [])
            ],
        )


@dataclass
class Team:
    """A portfolio manager / Pilot on Autopilot."""
    team_key: int
    title: str
    company_image_url: Optional[str] = None
    portfolio_count: Optional[int] = None

    @property
    def image_url(self) -> Optional[str]:
        return self.company_image_url

    @classmethod
    def from_dict(cls, d: dict) -> "Team":
        return cls(
            team_key=int(d.get("teamKey", 0)),
            title=d.get("title", ""),
            company_image_url=d.get("companyImageUrl"),
            portfolio_count=d.get("portfolioCount"),
        )

    def to_dict(self) -> dict:
        return {
            "team_key": self.team_key,
            "title": self.title,
            "company_image_url": self.company_image_url,
            "portfolio_count": self.portfolio_count,
        }


@dataclass
class Portfolio:
    """
    A publicly accessible portfolio on the Autopilot Marketplace.

    Scraped from: https://marketplace.joinautopilot.com/landing/{team_key}/{portfolio_key}
    Method: RSC (React Server Component) payload — no authentication required.

    All monetary values are in USD. Returns are decimals (multiply by 100 for %).
    """
    portfolio_key: int
    title: str
    team: Team
    total_aum: float                                # Total assets under management (USD)
    profile_image_url: Optional[str] = None
    profile_image_large_url: Optional[str] = None
    performance: Dict[str, PerformanceData] = field(default_factory=dict)
    performance_method_type: Optional[str] = None   # TWR_NORMALIZED or TWR_NORMALIZED_CLIENT_AGG
    disclaimer_short: Optional[str] = None
    disclaimer_link: Optional[str] = None
    fetched_at: Optional[datetime] = None

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def landing_url(self) -> str:
        return f"https://marketplace.joinautopilot.com/landing/{self.team.team_key}/{self.portfolio_key}"

    @property
    def is_simulated(self) -> bool:
        """True if performance is simulated (not real client aggregate)."""
        return self.performance_method_type == PerformanceMethodType.TWR_NORMALIZED

    def get_span(self, span: str) -> Optional[PerformanceData]:
        """Get PerformanceData for a specific span. e.g. get_span('ONE_YEAR')"""
        return self.performance.get(span)

    def all_time_return(self) -> Optional[float]:
        """All-time return as a percentage. e.g. 184.1"""
        p = self.performance.get("ALL_TIME")
        return p.span_performance_pct if p else None

    def one_year_return(self) -> Optional[float]:
        p = self.performance.get("ONE_YEAR")
        return p.span_performance_pct if p else None

    def six_month_return(self) -> Optional[float]:
        p = self.performance.get("SIX_MONTH")
        return p.span_performance_pct if p else None

    def one_month_return(self) -> Optional[float]:
        p = self.performance.get("ONE_MONTH")
        return p.span_performance_pct if p else None

    def one_week_return(self) -> Optional[float]:
        p = self.performance.get("ONE_WEEK")
        return p.span_performance_pct if p else None

    def available_spans(self) -> List[str]:
        return list(self.performance.keys())

    # ── Parsing ───────────────────────────────────────────────────────────────

    @classmethod
    def from_rsc_payload(cls, data: dict) -> "Portfolio":
        """
        Parse a Portfolio from the RSC payload dict.
        Handles both the top-level wrapper {"portfolio": {...}} and the inner dict.
        """
        portfolio = data.get("portfolio", data)
        apm       = portfolio.get("autoPilotMasterPortfolio", {})
        team_data = portfolio.get("team", {})
        sub       = portfolio.get("subscriberOverview", {})
        stats     = portfolio.get("stats", {})

        # Build performance dict keyed by span name
        perf_dict: Dict[str, PerformanceData] = {}
        for p in stats.get("performance", []):
            perf = PerformanceData.from_dict(p)
            perf_dict[perf.span] = perf

        # Performance metadata
        perf_meta  = stats.get("performanceMetaData", {})
        disclaimer = perf_meta.get("disclaimer", {})

        return cls(
            portfolio_key=int(apm.get("portfolioKey") or portfolio.get("portfolioKey", 0)),
            title=apm.get("title", ""),
            team=Team.from_dict(team_data),
            total_aum=float(sub.get("totalAUM", 0.0)),
            profile_image_url=apm.get("profileImageUrl"),
            profile_image_large_url=apm.get("profileImageLargeUrl"),
            performance=perf_dict,
            performance_method_type=perf_meta.get("performanceMethodType"),
            disclaimer_short=disclaimer.get("shortVersion"),
            disclaimer_link=disclaimer.get("disclaimerLink"),
            fetched_at=datetime.now(timezone.utc),
        )

    def to_dict(self, include_daily: bool = True) -> dict:
        perf = {}
        for span, pd_obj in self.performance.items():
            perf[span] = {
                "span_performance": pd_obj.span_performance,
                "span_performance_pct": pd_obj.span_performance_pct,
                "num_data_points": pd_obj.num_data_points,
            }
            if include_daily:
                perf[span]["daily"] = [d.to_dict() for d in pd_obj.cumulative_performance]
        return {
            "portfolio_key": self.portfolio_key,
            "title": self.title,
            "team": self.team.to_dict(),
            "total_aum": self.total_aum,
            "profile_image_url": self.profile_image_url,
            "profile_image_large_url": self.profile_image_large_url,
            "performance_method_type": self.performance_method_type,
            "performance": perf,
            "landing_url": self.landing_url,
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
        }

    def summary(self) -> str:
        lines = [
            f"Portfolio: {self.title} [{self.portfolio_key}]",
            f"  Team:    {self.team.title} (teamKey={self.team.team_key})",
            f"  AUM:     ${self.total_aum:,.0f}",
            f"  Method:  {self.performance_method_type or 'unknown'}",
            f"  URL:     {self.landing_url}",
        ]
        for span, p in self.performance.items():
            lines.append(f"  {span:12s}: {p.span_performance_pct:+.2f}%  ({p.num_data_points} pts)")
        return "\n".join(lines)


@dataclass
class LeaderboardEntry:
    """A single portfolio's entry in the leaderboard for a given span."""
    span: str
    rank: int
    portfolio_key: int
    title: str
    team_key: int
    team_title: str
    team_image_url: Optional[str]
    profile_image_url: Optional[str]
    total_aum: float
    span_performance: float             # Decimal for THIS span
    all_performances: Dict[str, float] = field(default_factory=dict)

    @property
    def span_performance_pct(self) -> float:
        return self.span_performance * 100

    @property
    def landing_url(self) -> str:
        return f"https://marketplace.joinautopilot.com/landing/{self.team_key}/{self.portfolio_key}"

    @classmethod
    def from_dict(cls, span: str, rank: int, d: dict) -> "LeaderboardEntry":
        apm      = d.get("autoPilotMasterPortfolio", {})
        team     = d.get("team", {})
        sub      = d.get("subscriberOverview", {})
        perf_list = d.get("stats", {}).get("performance", [])
        span_map  = {p["span"]: p["spanPerformance"] for p in perf_list}

        return cls(
            span=span,
            rank=rank,
            portfolio_key=int(apm.get("portfolioKey", 0)),
            title=apm.get("title", ""),
            team_key=int(team.get("teamKey", 0)),
            team_title=team.get("title", ""),
            team_image_url=team.get("companyImageUrl"),
            profile_image_url=apm.get("profileImageUrl"),
            total_aum=float(sub.get("totalAUM", 0.0)),
            span_performance=span_map.get(span, 0.0),
            all_performances=span_map,
        )

    def to_dict(self) -> dict:
        return {
            "span": self.span,
            "rank": self.rank,
            "portfolio_key": self.portfolio_key,
            "title": self.title,
            "team_key": self.team_key,
            "team_title": self.team_title,
            "team_image_url": self.team_image_url,
            "profile_image_url": self.profile_image_url,
            "total_aum": self.total_aum,
            "span_performance": self.span_performance,
            "span_performance_pct": self.span_performance_pct,
            "all_performances": self.all_performances,
            "landing_url": self.landing_url,
        }


@dataclass
class FeaturedPortfolio:
    """A portfolio shown in the featured/hero section of the main landing page."""
    portfolio_key: int
    title: str
    team_key: int
    team_title: str
    profile_image_url: Optional[str] = None
    profile_image_large_url: Optional[str] = None
    team_image_url: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict) -> "FeaturedPortfolio":
        apm  = d.get("autoPilotMasterPortfolio", {})
        team = d.get("team", {})
        return cls(
            portfolio_key=int(apm.get("portfolioKey", 0)),
            title=apm.get("title", ""),
            team_key=int(team.get("teamKey", 0)),
            team_title=team.get("title", ""),
            profile_image_url=apm.get("profileImageUrl"),
            profile_image_large_url=apm.get("profileImageLargeUrl"),
            team_image_url=team.get("companyImageUrl"),
        )


@dataclass
class PopularPortfolio:
    """A portfolio shown in the popular section, with AUM data."""
    portfolio_key: int
    title: str
    team_key: int
    team_title: str
    total_aum: float
    profile_image_url: Optional[str] = None
    team_image_url: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict) -> "PopularPortfolio":
        apm  = d.get("autoPilotMasterPortfolio", {})
        team = d.get("team", {})
        sub  = d.get("subscriberOverview", {})
        return cls(
            portfolio_key=int(apm.get("portfolioKey", 0)),
            title=apm.get("title", ""),
            team_key=int(team.get("teamKey", 0)),
            team_title=team.get("title", ""),
            total_aum=float(sub.get("totalAUM", 0.0)),
            profile_image_url=apm.get("profileImageUrl"),
            team_image_url=team.get("companyImageUrl"),
        )


@dataclass
class SitemapEntry:
    """A portfolio URL from the sitemap."""
    url: str
    team_key: int
    portfolio_key: int
    last_mod: Optional[str] = None

    @property
    def landing_path(self) -> str:
        return f"/landing/{self.team_key}/{self.portfolio_key}"


@dataclass
class MarketplaceListing:
    """
    Complete marketplace snapshot from the main landing page RSC payload.
    Contains featured, popular, and leaderboard data for all portfolios.
    """
    featured_portfolios: List[FeaturedPortfolio] = field(default_factory=list)
    popular_portfolios: List[PopularPortfolio]   = field(default_factory=list)
    leaderboard: Dict[str, List[LeaderboardEntry]] = field(default_factory=dict)
    teams: List[Team]                            = field(default_factory=list)
    fetched_at: Optional[datetime]               = None

    def top_by_span(self, span: str, n: int = 5) -> List[LeaderboardEntry]:
        return self.leaderboard.get(span, [])[:n]

    def get_team(self, team_key: int) -> Optional[Team]:
        for t in self.teams:
            if t.team_key == team_key:
                return t
        return None

    def summary(self) -> str:
        lines = [
            f"Autopilot Marketplace Snapshot — {self.fetched_at}",
            f"  Featured portfolios: {len(self.featured_portfolios)}",
            f"  Popular portfolios:  {len(self.popular_portfolios)}",
            f"  Teams listed:        {len(self.teams)}",
            "",
        ]
        for span, entries in self.leaderboard.items():
            lines.append(f"  Top {span}:")
            for e in entries[:3]:
                lines.append(f"    #{e.rank} {e.title}: {e.span_performance_pct:+.1f}%  AUM=${e.total_aum/1e6:.1f}M")
        return "\n".join(lines)
