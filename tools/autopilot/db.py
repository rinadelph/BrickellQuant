"""
autopilot.db — SQLite persistence layer for Autopilot Marketplace data

Schema:
  portfolios       — core portfolio metadata + AUM + performance summary
  performance      — per-span performance summary (one row per portfolio+span)
  daily_returns    — full daily return series (one row per portfolio+span+date)
  teams            — team/pilot metadata
  leaderboard      — leaderboard snapshot rows (portfolio+span+rank)
  featured         — featured portfolio list
  popular          — popular portfolios with AUM rankings
  sync_log         — audit trail of when syncs happened

Follows the same patterns as the rest of the BrickellQuant tools stack.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

from .models import (
    DailyReturn,
    FeaturedPortfolio,
    LeaderboardEntry,
    MarketplaceListing,
    PerformanceData,
    PopularPortfolio,
    Portfolio,
    Team,
)

# ── Schema DDL ─────────────────────────────────────────────────────────────────

_DDL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS teams (
    team_key            INTEGER PRIMARY KEY,
    title               TEXT    NOT NULL,
    company_image_url   TEXT,
    portfolio_count     INTEGER,
    updated_at          TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS portfolios (
    portfolio_key           INTEGER PRIMARY KEY,
    title                   TEXT    NOT NULL,
    team_key                INTEGER NOT NULL,
    total_aum               REAL    NOT NULL DEFAULT 0,
    profile_image_url       TEXT,
    profile_image_large_url TEXT,
    performance_method_type TEXT,
    disclaimer_short        TEXT,
    disclaimer_link         TEXT,
    landing_url             TEXT,
    fetched_at              TEXT,
    updated_at              TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (team_key) REFERENCES teams(team_key)
);

CREATE TABLE IF NOT EXISTS performance (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    portfolio_key       INTEGER NOT NULL,
    span                TEXT    NOT NULL,
    span_performance    REAL    NOT NULL,
    num_data_points     INTEGER NOT NULL DEFAULT 0,
    start_date          TEXT,
    end_date            TEXT,
    updated_at          TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (portfolio_key, span),
    FOREIGN KEY (portfolio_key) REFERENCES portfolios(portfolio_key)
);

CREATE TABLE IF NOT EXISTS daily_returns (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    portfolio_key   INTEGER NOT NULL,
    span            TEXT    NOT NULL,
    date            TEXT    NOT NULL,
    daily_return    REAL    NOT NULL,
    cumulative      REAL    NOT NULL,
    UNIQUE (portfolio_key, span, date),
    FOREIGN KEY (portfolio_key) REFERENCES portfolios(portfolio_key)
);

CREATE TABLE IF NOT EXISTS leaderboard (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    span            TEXT    NOT NULL,
    rank            INTEGER NOT NULL,
    portfolio_key   INTEGER NOT NULL,
    title           TEXT    NOT NULL,
    team_key        INTEGER NOT NULL,
    team_title      TEXT,
    total_aum       REAL,
    span_performance REAL,
    all_performances TEXT,   -- JSON blob of all span performances
    snapshot_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (span, portfolio_key, snapshot_at)
);

CREATE TABLE IF NOT EXISTS featured (
    portfolio_key           INTEGER NOT NULL,
    title                   TEXT    NOT NULL,
    team_key                INTEGER NOT NULL,
    team_title              TEXT,
    profile_image_url       TEXT,
    profile_image_large_url TEXT,
    team_image_url          TEXT,
    snapshot_at             TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (portfolio_key, snapshot_at)
);

CREATE TABLE IF NOT EXISTS popular (
    portfolio_key       INTEGER NOT NULL,
    title               TEXT    NOT NULL,
    team_key            INTEGER NOT NULL,
    team_title          TEXT,
    total_aum           REAL,
    profile_image_url   TEXT,
    team_image_url      TEXT,
    snapshot_at         TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (portfolio_key, snapshot_at)
);

CREATE TABLE IF NOT EXISTS sync_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    event           TEXT    NOT NULL,
    detail          TEXT,
    records_written INTEGER DEFAULT 0,
    started_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    finished_at     TEXT
);

-- Indices for common queries
CREATE INDEX IF NOT EXISTS idx_portfolios_team     ON portfolios(team_key);
CREATE INDEX IF NOT EXISTS idx_portfolios_aum      ON portfolios(total_aum DESC);
CREATE INDEX IF NOT EXISTS idx_performance_key     ON performance(portfolio_key);
CREATE INDEX IF NOT EXISTS idx_daily_portfolio_span ON daily_returns(portfolio_key, span);
CREATE INDEX IF NOT EXISTS idx_daily_date          ON daily_returns(date);
CREATE INDEX IF NOT EXISTS idx_leaderboard_span    ON leaderboard(span, rank);
"""

_NOW = lambda: datetime.now(timezone.utc).isoformat()


class AutopilotDB:
    """
    SQLite persistence layer for Autopilot Marketplace data.

    Args:
        path: Path to the SQLite database file. Default "autopilot.db".

    Example:
        from tools.autopilot import AutopilotDB, AutopilotClient

        db = AutopilotDB("autopilot.db")   # creates file if not exists

        # Manual upsert
        client = AutopilotClient()
        p = client.get_portfolio(1, 8735)
        db.upsert_portfolio(p)

        # Query
        row = db.get_portfolio(8735)
        print(row)

        # All portfolios sorted by AUM
        for row in db.get_all_portfolios(order_by="total_aum DESC"):
            print(row["title"], row["total_aum"])

        # Daily returns for a portfolio
        df = db.get_daily_returns(8735, span="ALL_TIME")
        print(df.head())
    """

    def __init__(self, path: str = "autopilot.db"):
        self.path = str(Path(path).resolve())
        self._init_db()

    # ── Setup ──────────────────────────────────────────────────────────────────

    def _init_db(self):
        """Create tables and indices if they don't exist."""
        with self._conn() as conn:
            conn.executescript(_DDL)

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager for a connection with row_factory set."""
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── Teams ──────────────────────────────────────────────────────────────────

    def upsert_team(self, team: Team) -> None:
        """Insert or update a team record."""
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO teams (team_key, title, company_image_url, portfolio_count, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(team_key) DO UPDATE SET
                    title             = excluded.title,
                    company_image_url = excluded.company_image_url,
                    portfolio_count   = excluded.portfolio_count,
                    updated_at        = excluded.updated_at
            """, (
                team.team_key, team.title,
                team.company_image_url, team.portfolio_count,
                _NOW(),
            ))

    def get_team(self, team_key: int) -> Optional[Dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM teams WHERE team_key = ?", (team_key,)
            ).fetchone()
            return dict(row) if row else None

    def get_all_teams(self) -> List[Dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM teams ORDER BY title"
            ).fetchall()
            return [dict(r) for r in rows]

    # ── Portfolios ─────────────────────────────────────────────────────────────

    def upsert_portfolio(self, portfolio: Portfolio, include_daily: bool = True) -> None:
        """
        Insert or update a portfolio and all its performance data.

        Args:
            portfolio:     Portfolio instance to persist.
            include_daily: If True, also upsert all daily return data points.
        """
        # Ensure team exists first
        self.upsert_team(portfolio.team)

        with self._conn() as conn:
            conn.execute("""
                INSERT INTO portfolios (
                    portfolio_key, title, team_key, total_aum,
                    profile_image_url, profile_image_large_url,
                    performance_method_type, disclaimer_short, disclaimer_link,
                    landing_url, fetched_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(portfolio_key) DO UPDATE SET
                    title                   = excluded.title,
                    team_key                = excluded.team_key,
                    total_aum               = excluded.total_aum,
                    profile_image_url       = excluded.profile_image_url,
                    profile_image_large_url = excluded.profile_image_large_url,
                    performance_method_type = excluded.performance_method_type,
                    disclaimer_short        = excluded.disclaimer_short,
                    disclaimer_link         = excluded.disclaimer_link,
                    landing_url             = excluded.landing_url,
                    fetched_at              = excluded.fetched_at,
                    updated_at              = excluded.updated_at
            """, (
                portfolio.portfolio_key,
                portfolio.title,
                portfolio.team.team_key,
                portfolio.total_aum,
                portfolio.profile_image_url,
                portfolio.profile_image_large_url,
                portfolio.performance_method_type,
                portfolio.disclaimer_short,
                portfolio.disclaimer_link,
                portfolio.landing_url,
                portfolio.fetched_at.isoformat() if portfolio.fetched_at else _NOW(),
                _NOW(),
            ))

        # Performance spans
        for perf in portfolio.performance.values():
            self._upsert_performance(portfolio.portfolio_key, perf)
            if include_daily:
                self._upsert_daily_returns(portfolio.portfolio_key, perf)

    def _upsert_performance(self, portfolio_key: int, perf: PerformanceData) -> None:
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO performance (
                    portfolio_key, span, span_performance,
                    num_data_points, start_date, end_date, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(portfolio_key, span) DO UPDATE SET
                    span_performance = excluded.span_performance,
                    num_data_points  = excluded.num_data_points,
                    start_date       = excluded.start_date,
                    end_date         = excluded.end_date,
                    updated_at       = excluded.updated_at
            """, (
                portfolio_key,
                perf.span,
                perf.span_performance,
                perf.num_data_points,
                perf.start_date.isoformat() if perf.start_date else None,
                perf.end_date.isoformat() if perf.end_date else None,
                _NOW(),
            ))

    def _upsert_daily_returns(self, portfolio_key: int, perf: PerformanceData) -> None:
        """Bulk insert daily return data points using INSERT OR IGNORE."""
        rows = [
            (portfolio_key, perf.span, d.date.isoformat(), d.daily_return, d.cumulative)
            for d in perf.cumulative_performance
        ]
        if not rows:
            return
        with self._conn() as conn:
            conn.executemany("""
                INSERT OR IGNORE INTO daily_returns
                    (portfolio_key, span, date, daily_return, cumulative)
                VALUES (?, ?, ?, ?, ?)
            """, rows)

    def get_portfolio(self, portfolio_key: int) -> Optional[Dict]:
        """
        Get a portfolio record with its latest performance summary.

        Returns:
            Dict with all portfolio fields, plus a "performance" key containing
            a dict of {span: {span_performance, num_data_points, start_date, end_date}}.
        """
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM portfolios WHERE portfolio_key = ?", (portfolio_key,)
            ).fetchone()
            if not row:
                return None
            result = dict(row)

            # Attach performance summary
            perf_rows = conn.execute(
                "SELECT * FROM performance WHERE portfolio_key = ?", (portfolio_key,)
            ).fetchall()
            result["performance"] = {
                r["span"]: {
                    "span_performance":     r["span_performance"],
                    "span_performance_pct": r["span_performance"] * 100,
                    "num_data_points":      r["num_data_points"],
                    "start_date":           r["start_date"],
                    "end_date":             r["end_date"],
                }
                for r in perf_rows
            }
            return result

    def get_all_portfolios(
        self,
        order_by: str = "total_aum DESC",
        min_aum: float = 0,
    ) -> List[Dict]:
        """
        Get all portfolios with their performance summary.

        Args:
            order_by: SQL ORDER BY clause. Default "total_aum DESC".
            min_aum:  Filter portfolios with AUM below this threshold.

        Returns:
            List of portfolio dicts with performance summaries attached.
        """
        with self._conn() as conn:
            rows = conn.execute(f"""
                SELECT * FROM portfolios
                WHERE total_aum >= ?
                ORDER BY {order_by}
            """, (min_aum,)).fetchall()
            results = []
            for row in rows:
                p = dict(row)
                perf_rows = conn.execute(
                    "SELECT * FROM performance WHERE portfolio_key = ?",
                    (p["portfolio_key"],)
                ).fetchall()
                p["performance"] = {
                    r["span"]: {
                        "span_performance":     r["span_performance"],
                        "span_performance_pct": r["span_performance"] * 100,
                        "num_data_points":      r["num_data_points"],
                    }
                    for r in perf_rows
                }
                results.append(p)
            return results

    # ── Daily Returns ──────────────────────────────────────────────────────────

    def get_daily_returns(
        self,
        portfolio_key: int,
        span: str = "ALL_TIME",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Dict]:
        """
        Get daily return data for a portfolio and span.

        Args:
            portfolio_key: Portfolio key.
            span:          Performance span. Default "ALL_TIME".
            start_date:    ISO date string to filter from (inclusive).
            end_date:      ISO date string to filter to (inclusive).

        Returns:
            List of dicts: [{date, daily_return, cumulative}, ...]

        Example:
            rows = db.get_daily_returns(8735, span="ALL_TIME")
            for r in rows[-5:]:
                print(r["date"], r["cumulative"])
        """
        query  = "SELECT * FROM daily_returns WHERE portfolio_key = ? AND span = ?"
        params: List[Any] = [portfolio_key, span]

        if start_date:
            query  += " AND date >= ?"
            params.append(start_date)
        if end_date:
            query  += " AND date <= ?"
            params.append(end_date)

        query += " ORDER BY date ASC"

        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def get_daily_returns_df(
        self,
        portfolio_key: int,
        span: str = "ALL_TIME",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ):
        """
        Get daily returns as a pandas DataFrame.

        Requires pandas. Returns DataFrame with columns:
          date, daily_return, cumulative, daily_return_pct, cumulative_pct

        Example:
            df = db.get_daily_returns_df(8735, span="ALL_TIME")
            print(df.tail())
        """
        try:
            import pandas as pd
        except ImportError:
            raise ImportError("pandas is required: pip install pandas")

        rows = self.get_daily_returns(portfolio_key, span, start_date, end_date)
        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        df["date"]              = pd.to_datetime(df["date"])
        df["daily_return_pct"]  = df["daily_return"] * 100
        df["cumulative_pct"]    = df["cumulative"] * 100
        return df.set_index("date").drop(columns=["id", "portfolio_key", "span"], errors="ignore")

    # ── Leaderboard ────────────────────────────────────────────────────────────

    def upsert_leaderboard_entry(self, entry: LeaderboardEntry, snapshot_at: Optional[str] = None) -> None:
        """Insert a leaderboard entry row. Pass snapshot_at to group a batch."""
        ts = snapshot_at or _NOW()
        with self._conn() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO leaderboard (
                    span, rank, portfolio_key, title, team_key, team_title,
                    total_aum, span_performance, all_performances, snapshot_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                entry.span, entry.rank, entry.portfolio_key, entry.title,
                entry.team_key, entry.team_title, entry.total_aum,
                entry.span_performance,
                json.dumps(entry.all_performances),
                ts,
            ))

    def get_leaderboard(
        self,
        span: str,
        snapshot_at: Optional[str] = None,
    ) -> List[Dict]:
        """
        Get leaderboard entries for a span.

        Args:
            span:        e.g. "ONE_YEAR", "ONE_WEEK"
            snapshot_at: Specific snapshot timestamp (ISO). Defaults to latest.

        Returns:
            List of leaderboard dicts sorted by rank.
        """
        with self._conn() as conn:
            if snapshot_at is None:
                # Use rows from the latest snapshot date (truncated to seconds to group nearby inserts)
                rows = conn.execute("""
                    SELECT * FROM leaderboard
                    WHERE span = ?
                      AND snapshot_at = (
                          SELECT MAX(snapshot_at) FROM leaderboard WHERE span = ?
                      )
                    ORDER BY rank ASC
                """, (span, span)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT * FROM leaderboard
                    WHERE span = ? AND snapshot_at = ?
                    ORDER BY rank ASC
                """, (span, snapshot_at)).fetchall()
            return [dict(r) for r in rows]

    def get_leaderboard_history(self, portfolio_key: int, span: str) -> List[Dict]:
        """Get all historical leaderboard entries for a portfolio and span."""
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT * FROM leaderboard
                WHERE portfolio_key = ? AND span = ?
                ORDER BY snapshot_at DESC
            """, (portfolio_key, span)).fetchall()
            return [dict(r) for r in rows]

    # ── Featured / Popular ─────────────────────────────────────────────────────

    def upsert_featured(self, fp: FeaturedPortfolio) -> None:
        now = _NOW()
        with self._conn() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO featured (
                    portfolio_key, title, team_key, team_title,
                    profile_image_url, profile_image_large_url, team_image_url, snapshot_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                fp.portfolio_key, fp.title, fp.team_key, fp.team_title,
                fp.profile_image_url, fp.profile_image_large_url, fp.team_image_url, now,
            ))

    def upsert_popular(self, pp: PopularPortfolio) -> None:
        now = _NOW()
        with self._conn() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO popular (
                    portfolio_key, title, team_key, team_title,
                    total_aum, profile_image_url, team_image_url, snapshot_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                pp.portfolio_key, pp.title, pp.team_key, pp.team_title,
                pp.total_aum, pp.profile_image_url, pp.team_image_url, now,
            ))

    # ── Sync log ───────────────────────────────────────────────────────────────

    def log_sync_start(self, event: str, detail: str = "") -> int:
        """Log the start of a sync event. Returns row ID."""
        with self._conn() as conn:
            cursor = conn.execute("""
                INSERT INTO sync_log (event, detail, started_at)
                VALUES (?, ?, ?)
            """, (event, detail, _NOW()))
            return cursor.lastrowid

    def log_sync_end(self, log_id: int, records_written: int = 0) -> None:
        """Mark a sync event as complete."""
        with self._conn() as conn:
            conn.execute("""
                UPDATE sync_log
                SET finished_at = ?, records_written = ?
                WHERE id = ?
            """, (_NOW(), records_written, log_id))

    # ── Analytics queries ──────────────────────────────────────────────────────

    def top_portfolios_by_aum(self, n: int = 10) -> List[Dict]:
        """Return top N portfolios by AUM."""
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT p.portfolio_key, p.title, t.title as team_title,
                       p.total_aum, p.landing_url
                FROM portfolios p
                JOIN teams t ON p.team_key = t.team_key
                ORDER BY p.total_aum DESC
                LIMIT ?
            """, (n,)).fetchall()
            return [dict(r) for r in rows]

    def top_portfolios_by_performance(
        self, span: str = "ONE_YEAR", n: int = 10
    ) -> List[Dict]:
        """Return top N portfolios by performance for a given span."""
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT p.portfolio_key, p.title, t.title as team_title,
                       p.total_aum, perf.span_performance,
                       perf.span_performance * 100 as span_performance_pct,
                       p.landing_url
                FROM portfolios p
                JOIN teams t ON p.team_key = t.team_key
                JOIN performance perf ON p.portfolio_key = perf.portfolio_key
                WHERE perf.span = ?
                ORDER BY perf.span_performance DESC
                LIMIT ?
            """, (span, n)).fetchall()
            return [dict(r) for r in rows]

    def portfolio_aum_over_time(self, portfolio_key: int) -> List[Dict]:
        """
        Get AUM snapshot history for a portfolio (from popular table).
        Useful for tracking AUM growth over time when syncing regularly.
        """
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT snapshot_at, total_aum
                FROM popular
                WHERE portfolio_key = ?
                ORDER BY snapshot_at ASC
            """, (portfolio_key,)).fetchall()
            return [dict(r) for r in rows]

    def search_portfolios(self, query: str) -> List[Dict]:
        """Search portfolios by title (case-insensitive, partial match)."""
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT p.*, t.title as team_title
                FROM portfolios p
                JOIN teams t ON p.team_key = t.team_key
                WHERE LOWER(p.title) LIKE ?
                ORDER BY p.total_aum DESC
            """, (f"%{query.lower()}%",)).fetchall()
            return [dict(r) for r in rows]

    # ── DB info ────────────────────────────────────────────────────────────────

    def stats(self) -> Dict[str, int]:
        """Return row counts for all tables."""
        tables = [
            "portfolios", "teams", "performance",
            "daily_returns", "leaderboard", "featured", "popular", "sync_log",
        ]
        with self._conn() as conn:
            return {
                t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in tables
            }

    def __repr__(self) -> str:
        s = self.stats()
        return (
            f"AutopilotDB(path={self.path!r}, "
            f"portfolios={s['portfolios']}, "
            f"teams={s['teams']}, "
            f"daily_returns={s['daily_returns']:,})"
        )
