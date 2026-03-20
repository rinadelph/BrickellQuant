"""
SentimentClient — Social sentiment aggregator
============================================
Sources: Reddit (PRAW) · StockTwits · Google Trends (pytrends)

SETUP:
    from tools.sentiment import SentimentClient

    # Reddit requires a free app at reddit.com/prefs/apps (takes 2 min)
    # export REDDIT_CLIENT_ID="..."
    # export REDDIT_CLIENT_SECRET="..."
    # export REDDIT_USER_AGENT="BrickellQuant/1.0"

    # StockTwits: no key needed for public streams
    # Google Trends: no key needed

    sent = SentimentClient()

COVERS FinanceForge: Section X (Narrative & Discovery)
    - Meme potential score
    - Discovery level by investor segment
    - Reddit mention volume + sentiment
    - Google Trends interest trajectory
    - StockTwits bullish/bearish ratio
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests
import pandas as pd

try:
    import praw
    PRAW_AVAILABLE = True
except ImportError:
    PRAW_AVAILABLE = False

try:
    from pytrends.request import TrendReq
    PYTRENDS_AVAILABLE = True
except ImportError:
    PYTRENDS_AVAILABLE = False

from tools.utils.cache import cached

# ── Finance subreddits with signal weighting ──────────────────────────────────
FINANCE_SUBREDDITS = {
    "wallstreetbets":   {"signal": "momentum/meme",  "noise": "very_high", "weight": 0.20},
    "stocks":           {"signal": "fundamental",    "noise": "medium",    "weight": 0.30},
    "investing":        {"signal": "long_term",      "noise": "low",       "weight": 0.25},
    "SecurityAnalysis": {"signal": "deep_research",  "noise": "very_low",  "weight": 0.15},
    "options":          {"signal": "derivatives",    "noise": "high",      "weight": 0.05},
    "pennystocks":      {"signal": "speculative",    "noise": "very_high", "weight": 0.05},
}

# ── Bullish / bearish keyword sets ───────────────────────────────────────────
_BULLISH = {"bull","bullish","buy","calls","long","moon","rocket","squeeze","upside","beat",
            "breakout","undervalued","buy the dip","strong buy","accumulate","green"}
_BEARISH = {"bear","bearish","sell","puts","short","crash","overvalued","dump","baghold",
            "miss","downside","avoid","red flag","bubble","cut","bankrupt"}


class SentimentClient:
    """
    Social sentiment aggregator for FinanceForge Section X.

    Collects from Reddit, StockTwits, and Google Trends.
    All methods return plain dicts or DataFrames — no raw API objects.

    Example:
        sent = SentimentClient()
        score = sent.ticker_sentiment("NVDA")
        print(score["overall_score"], score["signal"])   # 0.72, "BULLISH"

        trends = sent.google_trends("NVDA", timeframe="today 3-m")
        meme = sent.meme_score("GME")
    """

    def __init__(
        self,
        reddit_client_id: Optional[str] = None,
        reddit_client_secret: Optional[str] = None,
        reddit_user_agent: Optional[str] = None,
    ):
        # Reddit credentials (optional — falls back gracefully)
        self._reddit_id     = reddit_client_id     or os.environ.get("REDDIT_CLIENT_ID", "")
        self._reddit_secret = reddit_client_secret or os.environ.get("REDDIT_CLIENT_SECRET", "")
        self._reddit_agent  = reddit_user_agent    or os.environ.get("REDDIT_USER_AGENT",
                                                      "BrickellQuant/1.0 by research_agent")
        self._reddit: Optional["praw.Reddit"] = None

        if PRAW_AVAILABLE and self._reddit_id and self._reddit_secret:
            try:
                self._reddit = praw.Reddit(
                    client_id=self._reddit_id,
                    client_secret=self._reddit_secret,
                    user_agent=self._reddit_agent,
                    ratelimit_seconds=1,
                )
                self._reddit.read_only = True
            except Exception:
                self._reddit = None

    # ─────────────────────────────────────────────
    # MASTER SENTIMENT SCORE
    # ─────────────────────────────────────────────

    @cached(ttl=900)
    def ticker_sentiment(self, ticker: str, days: int = 7) -> dict:
        """
        Composite sentiment score combining all available sources.

        Args:
            ticker: Stock ticker symbol (e.g. "NVDA")
            days:   Lookback window in days (default: 7)

        Returns:
            Dict with keys:
                overall_score   float   0.0 (max bearish) → 1.0 (max bullish)
                signal          str     "STRONG_BULLISH" | "BULLISH" | "NEUTRAL"
                                        | "BEARISH" | "STRONG_BEARISH"
                reddit          dict    {mention_count, bullish_pct, bearish_pct,
                                         posts, top_post_title, top_post_score}
                stocktwits      dict    {bull_pct, bear_pct, message_count, watchers}
                google_trends   dict    {current_interest, vs_1m_ago, vs_3m_ago}
                sources_used    list[str]
                as_of           str     ISO timestamp

        Example:
            score = sent.ticker_sentiment("NVDA")
            print(f"{score['ticker']} → {score['signal']} ({score['overall_score']:.2f})")
        """
        scores = []
        sources_used = []
        result = {
            "ticker": ticker.upper(),
            "overall_score": 0.5,
            "signal": "NEUTRAL",
            "reddit": {},
            "stocktwits": {},
            "google_trends": {},
            "sources_used": [],
            "as_of": datetime.now().isoformat(),
        }

        # ── Reddit ────────────────────────────────────────────────────
        reddit_data = self.reddit_mentions(ticker, days=days)
        if reddit_data.get("mention_count", 0) > 0:
            result["reddit"] = reddit_data
            if reddit_data.get("total_scored", 0) > 0:
                bull = reddit_data.get("bullish_pct", 50) / 100
                scores.append(("reddit", bull, 0.35))
                sources_used.append("Reddit")

        # ── StockTwits ────────────────────────────────────────────────
        st_data = self.stocktwits(ticker)
        if not st_data.get("error"):
            result["stocktwits"] = st_data
            bull = st_data.get("bull_pct", 50) / 100
            scores.append(("stocktwits", bull, 0.35))
            sources_used.append("StockTwits")

        # ── Google Trends ─────────────────────────────────────────────
        gt_data = self.google_trends(ticker, timeframe="today 1-m")
        if not gt_data.get("error"):
            result["google_trends"] = gt_data
            # Normalise trend momentum as sentiment proxy
            momentum = gt_data.get("momentum_score", 0.5)
            scores.append(("google_trends", momentum, 0.30))
            sources_used.append("Google Trends")

        # ── Composite ─────────────────────────────────────────────────
        if scores:
            total_weight = sum(w for _, _, w in scores)
            composite = sum(s * w for _, s, w in scores) / total_weight
        else:
            composite = 0.5

        result["overall_score"] = round(composite, 4)
        result["sources_used"]  = sources_used

        if composite >= 0.70:
            result["signal"] = "STRONG_BULLISH"
        elif composite >= 0.55:
            result["signal"] = "BULLISH"
        elif composite >= 0.45:
            result["signal"] = "NEUTRAL"
        elif composite >= 0.30:
            result["signal"] = "BEARISH"
        else:
            result["signal"] = "STRONG_BEARISH"

        return result

    # ─────────────────────────────────────────────
    # REDDIT
    # ─────────────────────────────────────────────

    @cached(ttl=900)
    def reddit_mentions(
        self,
        ticker: str,
        subreddits: Optional[list[str]] = None,
        days: int = 7,
        limit_per_sub: int = 100,
    ) -> dict:
        """
        Aggregate Reddit mentions and sentiment across finance subreddits.

        Args:
            ticker:        Stock symbol — searched as "$TICKER" and "TICKER"
            subreddits:    List of subreddit names (default: all FINANCE_SUBREDDITS)
            days:          Lookback window in days
            limit_per_sub: Max posts to scan per subreddit

        Returns:
            Dict with:
                mention_count   int     total posts/comments mentioning ticker
                bullish_pct     float   % bullish scored mentions
                bearish_pct     float   % bearish scored mentions
                total_scored    int     mentions with detectable sentiment
                avg_score       float   avg post score (upvotes)
                top_posts       list    [{title, score, url, sub, sentiment}]
                subreddit_breakdown  dict  {sub: mention_count}

        Example:
            data = sent.reddit_mentions("GME", days=3)
            print(f"GME: {data['mention_count']} mentions, "
                  f"{data['bullish_pct']:.0f}% bullish")
        """
        if not PRAW_AVAILABLE or not self._reddit:
            return _reddit_no_credentials_fallback(ticker)

        subs = subreddits or list(FINANCE_SUBREDDITS.keys())
        query  = f"${ticker.upper()} OR {ticker.upper()}"
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        all_posts: list[dict] = []
        sub_counts: dict[str, int] = {}

        for sub_name in subs:
            try:
                sub = self._reddit.subreddit(sub_name)
                results = sub.search(query, limit=limit_per_sub, sort="new", time_filter="week")
                count = 0
                for post in results:
                    created = datetime.fromtimestamp(post.created_utc, tz=timezone.utc)
                    if created < cutoff:
                        continue
                    sentiment = _score_text(post.title + " " + (post.selftext or ""))
                    all_posts.append({
                        "title":     post.title[:120],
                        "score":     post.score,
                        "url":       f"https://reddit.com{post.permalink}",
                        "sub":       sub_name,
                        "sentiment": sentiment,
                        "created":   created.isoformat(),
                    })
                    count += 1
                sub_counts[sub_name] = count
            except Exception:
                continue

        total   = len(all_posts)
        scored  = [p for p in all_posts if p["sentiment"] != "neutral"]
        bullish = [p for p in scored if p["sentiment"] == "bullish"]
        bearish = [p for p in scored if p["sentiment"] == "bearish"]

        return {
            "mention_count":       total,
            "bullish_pct":         round(len(bullish) / max(len(scored), 1) * 100, 1),
            "bearish_pct":         round(len(bearish) / max(len(scored), 1) * 100, 1),
            "total_scored":        len(scored),
            "avg_score":           round(sum(p["score"] for p in all_posts) / max(total, 1), 1),
            "top_posts":           sorted(all_posts, key=lambda x: x["score"], reverse=True)[:5],
            "subreddit_breakdown": sub_counts,
        }

    # ─────────────────────────────────────────────
    # STOCKTWITS
    # ─────────────────────────────────────────────

    @cached(ttl=600)
    def stocktwits(self, ticker: str) -> dict:
        """
        StockTwits public stream sentiment for a ticker.
        No API key required.

        Args:
            ticker: Stock symbol

        Returns:
            Dict with:
                bull_pct        float   % of bullish messages (last 30)
                bear_pct        float
                message_count   int     messages in response (max 30)
                watchers        int     number of users watching
                top_messages    list    [{body, sentiment, created_at}]

        Example:
            st = sent.stocktwits("TSLA")
            print(f"TSLA StockTwits: {st['bull_pct']:.0f}% bull / {st['bear_pct']:.0f}% bear")
        """
        url = f"https://api.stocktwits.com/api/2/streams/symbol/{ticker.upper()}.json"
        try:
            resp = requests.get(url, timeout=10,
                                headers={"User-Agent": "BrickellQuant/1.0"})
            if resp.status_code == 429:
                return {"error": "rate_limited", "ticker": ticker.upper()}
            if not resp.ok:
                return {"error": f"HTTP {resp.status_code}", "ticker": ticker.upper()}

            data     = resp.json()
            messages = data.get("messages", [])
            symbol   = data.get("symbol", {})

            bull = sum(1 for m in messages if
                       m.get("entities", {}).get("sentiment", {}).get("basic") == "Bullish")
            bear = sum(1 for m in messages if
                       m.get("entities", {}).get("sentiment", {}).get("basic") == "Bearish")
            total = max(len(messages), 1)

            top = [
                {
                    "body":       m.get("body", "")[:200],
                    "sentiment":  m.get("entities", {}).get("sentiment", {}).get("basic", ""),
                    "created_at": m.get("created_at", ""),
                    "likes":      m.get("likes", {}).get("total", 0),
                }
                for m in messages[:5]
            ]

            return {
                "ticker":        ticker.upper(),
                "bull_pct":      round(bull / total * 100, 1),
                "bear_pct":      round(bear / total * 100, 1),
                "message_count": len(messages),
                "watchers":      symbol.get("watchlist_count", 0),
                "top_messages":  top,
            }
        except Exception as e:
            return {"error": str(e), "ticker": ticker.upper()}

    # ─────────────────────────────────────────────
    # GOOGLE TRENDS
    # ─────────────────────────────────────────────

    @cached(ttl=3600)
    def google_trends(
        self,
        ticker: str,
        company_name: Optional[str] = None,
        timeframe: str = "today 3-m",
        geo: str = "",
    ) -> dict:
        """
        Google Trends search interest for a ticker/company.
        No API key required.

        Args:
            ticker:       Stock symbol
            company_name: Optional full company name to search alongside ticker
            timeframe:    "today 1-m" | "today 3-m" | "today 12-m" | "today 5-y"
            geo:          Country code e.g. "US" (empty = worldwide)

        Returns:
            Dict with:
                current_interest    int     current week interest (0-100)
                peak_interest       int     peak in period
                avg_interest        float   mean over period
                momentum_score      float   0.0-1.0 (recent vs avg ratio)
                vs_1m_ago           float   % change vs 4 weeks ago
                trend_direction     str     "RISING" | "FALLING" | "FLAT"
                interest_series     list    [{date, interest}]

        Example:
            t = sent.google_trends("NVDA", timeframe="today 3-m")
            print(f"NVDA Google interest: {t['current_interest']}/100  "
                  f"direction: {t['trend_direction']}")
        """
        if not PYTRENDS_AVAILABLE:
            return {"error": "pytrends not installed. Run: uv add pytrends"}

        kw = f"${ticker.upper()}" if not company_name else company_name
        try:
            pt = TrendReq(hl="en-US", tz=360, timeout=(10, 25))
            pt.build_payload([kw], timeframe=timeframe, geo=geo)
            df = pt.interest_over_time()

            if df is None or df.empty:
                return {"error": "no_data", "ticker": ticker.upper()}

            series = df[kw].values.tolist()
            dates  = [str(d.date()) for d in df.index]

            current  = int(series[-1])
            peak     = int(max(series))
            avg      = float(sum(series) / len(series))
            momentum = min(current / max(avg, 1), 1.0)

            # Compare last 4 data points vs previous 4
            half = max(len(series) // 2, 1)
            recent_avg = sum(series[-half:]) / half
            prior_avg  = sum(series[:half]) / half
            vs_prior   = ((recent_avg - prior_avg) / max(prior_avg, 1)) * 100

            trend = "RISING" if vs_prior > 10 else ("FALLING" if vs_prior < -10 else "FLAT")

            return {
                "ticker":           ticker.upper(),
                "keyword":          kw,
                "current_interest": current,
                "peak_interest":    peak,
                "avg_interest":     round(avg, 1),
                "momentum_score":   round(momentum, 4),
                "vs_1m_ago":        round(vs_prior, 1),
                "trend_direction":  trend,
                "interest_series":  [{"date": d, "interest": int(v)}
                                     for d, v in zip(dates, series)],
                "timeframe":        timeframe,
                "geo":              geo or "worldwide",
            }
        except Exception as e:
            return {"error": str(e), "ticker": ticker.upper()}

    # ─────────────────────────────────────────────
    # MEME SCORE
    # ─────────────────────────────────────────────

    @cached(ttl=1800)
    def meme_score(self, ticker: str, company_name: Optional[str] = None) -> dict:
        """
        Composite meme potential score for FinanceForge Section X.

        Aggregates Reddit WSB mentions, Google Trends spike, StockTwits bull/bear ratio,
        and sector meme-ability into a 0-100 score.

        Returns:
            Dict with:
                score           int     0-100 meme materialisation score
                label           str     "COLD" | "WARM" | "HOT" | "NUCLEAR"
                wsb_mentions    int     r/wallstreetbets mention count (7 days)
                trends_spike    bool    Google search interest > 70/100
                st_bull_pct     float   StockTwits bullish %
                narrative       str     one-line meme narrative assessment

        Example:
            m = sent.meme_score("GME")
            print(f"GME meme score: {m['score']}/100 — {m['label']}")
        """
        wsb_data = {}
        gt_data  = {}
        st_data  = {}

        score_components = []

        # WSB mentions
        try:
            wsb_data = self.reddit_mentions(ticker, subreddits=["wallstreetbets"], days=7)
            mentions = wsb_data.get("mention_count", 0)
            # Scale: 0 mentions = 0, 100+ = 100 pts
            wsb_score = min(mentions / 100 * 100, 100)
            score_components.append(wsb_score * 0.40)
        except Exception:
            pass

        # Google Trends
        try:
            gt_data = self.google_trends(ticker, company_name=company_name, timeframe="today 1-m")
            interest = gt_data.get("current_interest", 0)
            score_components.append(interest * 0.35)
        except Exception:
            pass

        # StockTwits
        try:
            st_data = self.stocktwits(ticker)
            bull_pct = st_data.get("bull_pct", 50)
            # High bull or high bear = sentiment conviction = meme energy
            conviction = abs(bull_pct - 50) * 2   # 0-100 scale
            score_components.append(conviction * 0.25)
        except Exception:
            pass

        raw_score = int(sum(score_components) / max(len(score_components) / 3, 1)) if score_components else 0
        raw_score = max(0, min(raw_score, 100))

        if raw_score >= 75:
            label = "NUCLEAR"
        elif raw_score >= 50:
            label = "HOT"
        elif raw_score >= 25:
            label = "WARM"
        else:
            label = "COLD"

        return {
            "ticker":       ticker.upper(),
            "score":        raw_score,
            "label":        label,
            "wsb_mentions": wsb_data.get("mention_count", 0),
            "trends_spike": gt_data.get("current_interest", 0) > 70,
            "st_bull_pct":  st_data.get("bull_pct", 50.0),
            "narrative":    f"{ticker.upper()} meme energy: {raw_score}/100 — {label}",
        }

    # ─────────────────────────────────────────────
    # DISCOVERY LEVEL
    # ─────────────────────────────────────────────

    @cached(ttl=3600)
    def discovery_level(self, ticker: str) -> dict:
        """
        Investor discovery level assessment for FinanceForge Section X.

        Returns:
            Dict with:
                retail_status       str   "UNKNOWN" | "NICHE" | "DISCOVERED" | "MAINSTREAM"
                institutional_signal str  based on StockTwits watcher count
                reddit_discovery    str   based on subreddit mention spread
                overall             str   composite discovery label

        Example:
            d = sent.discovery_level("ASTS")
            print(d["overall"])  # "NICHE — discovered by specialists"
        """
        st = self.stocktwits(ticker)
        reddit = self.reddit_mentions(ticker, days=30)

        watchers     = st.get("watchers", 0)
        sub_spread   = len([v for v in reddit.get("subreddit_breakdown", {}).values() if v > 0])
        total_reddit = reddit.get("mention_count", 0)

        # Retail status from StockTwits watchers
        if watchers > 100_000:
            retail = "MAINSTREAM"
        elif watchers > 10_000:
            retail = "DISCOVERED"
        elif watchers > 1_000:
            retail = "NICHE"
        else:
            retail = "UNKNOWN"

        # Reddit breadth
        if sub_spread >= 4 and total_reddit > 50:
            reddit_disc = "MAINSTREAM"
        elif sub_spread >= 2 and total_reddit > 10:
            reddit_disc = "DISCOVERED"
        elif total_reddit > 2:
            reddit_disc = "NICHE"
        else:
            reddit_disc = "UNKNOWN"

        # Composite
        levels = {"UNKNOWN": 0, "NICHE": 1, "DISCOVERED": 2, "MAINSTREAM": 3}
        avg = (levels.get(retail, 0) + levels.get(reddit_disc, 0)) / 2
        labels_inv = {0: "UNKNOWN", 1: "NICHE", 2: "DISCOVERED", 3: "MAINSTREAM"}
        overall = labels_inv[round(avg)]

        return {
            "ticker":               ticker.upper(),
            "retail_status":        retail,
            "reddit_discovery":     reddit_disc,
            "reddit_sub_spread":    sub_spread,
            "reddit_total_mentions":total_reddit,
            "stocktwits_watchers":  watchers,
            "overall":              overall,
        }


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def _score_text(text: str) -> str:
    """Simple keyword-based sentiment scorer. Returns 'bullish'/'bearish'/'neutral'."""
    lower  = text.lower()
    bull_n = sum(1 for w in _BULLISH if w in lower)
    bear_n = sum(1 for w in _BEARISH if w in lower)
    if bull_n > bear_n:
        return "bullish"
    elif bear_n > bull_n:
        return "bearish"
    return "neutral"


def _reddit_no_credentials_fallback(ticker: str) -> dict:
    """Return empty structure with instructions when no Reddit credentials are set."""
    return {
        "mention_count":       0,
        "bullish_pct":         0.0,
        "bearish_pct":         0.0,
        "total_scored":        0,
        "avg_score":           0.0,
        "top_posts":           [],
        "subreddit_breakdown": {},
        "error":               (
            "Reddit credentials not set. Register a free app at "
            "reddit.com/prefs/apps then: "
            "export REDDIT_CLIENT_ID=... REDDIT_CLIENT_SECRET=... REDDIT_USER_AGENT=..."
        ),
    }
