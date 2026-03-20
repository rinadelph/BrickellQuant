"""
TranscriptClient — Earnings call transcripts & IR content
=========================================================
Sources (priority order):
  1. Financial Modeling Prep (FMP) — free tier, 250 req/day
  2. SEC 8-K exhibit parser       — 100% free, all US filers
  3. Motley Fool scraper          — free fallback, fragile

SETUP:
    from tools.transcripts import TranscriptClient

    # FMP free key: financialmodelingprep.com/developer/docs (takes 1 min)
    # export FMP_API_KEY="your_free_key"

    tc = TranscriptClient()          # auto-reads FMP_API_KEY env var
    # OR
    tc = TranscriptClient(fmp_key="your_key")

COVERS FinanceForge:
    Section II  — earnings tone analysis, management narrative shift
    Section IV  — CEO/CFO quotes for management assessment
    Section XI  — catalyst calendar, earnings date verification
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup

from tools.utils.cache import cached

FMP_BASE = "https://financialmodelingprep.com/api/v3"
_HEADERS = {"User-Agent": "BrickellQuant/1.0 research@brickellquant.com"}


class TranscriptClient:
    """
    Earnings call transcript client.

    Tries FMP (best quality) → SEC 8-K exhibits → Motley Fool scraper.

    Example:
        tc = TranscriptClient()

        # Latest transcript
        t = tc.latest_transcript("AAPL")
        print(t["date"], t["quarter"])
        print(t["transcript"][:500])

        # Tone analysis
        tone = tc.tone_analysis("NVDA", num_quarters=4)
        print(tone["trend"])   # "IMPROVING" | "DECLINING" | "STABLE"
    """

    def __init__(self, fmp_key: Optional[str] = None):
        self._fmp_key = fmp_key or os.environ.get("FMP_API_KEY", "")

    # ─────────────────────────────────────────────
    # TRANSCRIPT RETRIEVAL
    # ─────────────────────────────────────────────

    @cached(ttl=3600)
    def latest_transcript(self, ticker: str) -> dict:
        """
        Get the most recent earnings call transcript.
        Tries FMP first, then SEC 8-K exhibits, then Motley Fool.

        Args:
            ticker: Stock ticker symbol

        Returns:
            Dict with keys:
                ticker      str
                date        str     "2024-11-01"
                year        int
                quarter     int     1-4
                transcript  str     full transcript text
                source      str     "fmp" | "sec_8k" | "motley_fool" | "unavailable"
                url         str     source URL

        Example:
            t = tc.latest_transcript("AAPL")
            if t["source"] != "unavailable":
                print(f"Q{t['quarter']} {t['year']}: {len(t['transcript'])} chars")
        """
        # 1. Try FMP
        if self._fmp_key:
            result = self._fmp_transcript(ticker, limit=1)
            if result:
                return result[0]

        # 2. Try SEC 8-K earnings press release
        result = self._sec_8k_transcript(ticker)
        if result.get("source") != "unavailable":
            return result

        # 3. Motley Fool fallback
        result = self._motley_fool_transcript(ticker)
        return result

    @cached(ttl=3600)
    def transcript_history(self, ticker: str, num_quarters: int = 4) -> list[dict]:
        """
        Get transcript history for multiple quarters.

        Args:
            ticker:       Stock ticker
            num_quarters: Number of past quarters to retrieve (default: 4)

        Returns:
            List of transcript dicts (same structure as latest_transcript())
            sorted newest first

        Example:
            history = tc.transcript_history("MSFT", num_quarters=4)
            for t in history:
                print(f"Q{t['quarter']} {t['year']}: {t['source']}")
        """
        if self._fmp_key:
            results = self._fmp_transcript(ticker, limit=num_quarters)
            if results:
                return results

        # Fallback — return latest only as list
        latest = self.latest_transcript(ticker)
        return [latest]

    # ─────────────────────────────────────────────
    # TONE ANALYSIS
    # ─────────────────────────────────────────────

    @cached(ttl=3600)
    def tone_analysis(self, ticker: str, num_quarters: int = 4) -> dict:
        """
        Analyse management tone across multiple earnings calls.
        Used for FinanceForge Section II earnings sentiment analysis.

        Args:
            ticker:       Stock ticker
            num_quarters: Number of quarters to analyse

        Returns:
            Dict with keys:
                ticker          str
                quarters_analysed int
                trend           str     "IMPROVING" | "DECLINING" | "STABLE" | "VOLATILE"
                overall_tone    str     "POSITIVE" | "CAUTIOUS" | "NEGATIVE"
                quarterly_scores list   [{quarter, year, tone_score, key_phrases}]
                before_after    dict    {before: str, after: str}  — narrative shift
                ceo_quotes      list    notable CEO quote strings
                guidance_language str  extracted forward-looking language

        Example:
            tone = tc.tone_analysis("TSLA", num_quarters=4)
            print(f"Trend: {tone['trend']}")
            print(f"Before: {tone['before_after']['before']}")
            print(f"After:  {tone['before_after']['after']}")
        """
        transcripts = self.transcript_history(ticker, num_quarters=num_quarters)
        valid = [t for t in transcripts if t.get("source") != "unavailable"
                 and len(t.get("transcript", "")) > 200]

        if not valid:
            return {
                "ticker": ticker.upper(),
                "quarters_analysed": 0,
                "trend": "UNAVAILABLE",
                "overall_tone": "UNAVAILABLE",
                "quarterly_scores": [],
                "before_after": {"before": "", "after": ""},
                "ceo_quotes": [],
                "guidance_language": "",
                "error": "No transcripts available",
            }

        scored = []
        for t in valid:
            text = t.get("transcript", "")
            score = _tone_score(text)
            phrases = _extract_key_phrases(text)
            scored.append({
                "quarter":    t.get("quarter"),
                "year":       t.get("year"),
                "tone_score": score,
                "key_phrases": phrases[:5],
            })

        # Trend: compare oldest to newest
        scores = [s["tone_score"] for s in scored]
        if len(scores) >= 2:
            delta = scores[0] - scores[-1]   # newest first
            if delta > 0.10:
                trend = "IMPROVING"
            elif delta < -0.10:
                trend = "DECLINING"
            elif max(scores) - min(scores) > 0.25:
                trend = "VOLATILE"
            else:
                trend = "STABLE"
        else:
            trend = "STABLE"

        avg_score = sum(scores) / len(scores)
        overall_tone = "POSITIVE" if avg_score > 0.55 else ("NEGATIVE" if avg_score < 0.40 else "CAUTIOUS")

        # Before/after narrative
        before = _summarise_tone(valid[-1].get("transcript", "")) if len(valid) > 1 else ""
        after  = _summarise_tone(valid[0].get("transcript", ""))

        # CEO quotes
        ceo_quotes = _extract_quotes(valid[0].get("transcript", ""), n=3)

        # Guidance language
        guidance = _extract_guidance(valid[0].get("transcript", ""))

        return {
            "ticker":            ticker.upper(),
            "quarters_analysed": len(valid),
            "trend":             trend,
            "overall_tone":      overall_tone,
            "quarterly_scores":  scored,
            "before_after":      {"before": before, "after": after},
            "ceo_quotes":        ceo_quotes,
            "guidance_language": guidance,
        }

    # ─────────────────────────────────────────────
    # EARNINGS CALENDAR
    # ─────────────────────────────────────────────

    @cached(ttl=3600)
    def earnings_calendar(self, ticker: str) -> dict:
        """
        Get upcoming earnings date with EPS/revenue estimates from FMP.

        Args:
            ticker: Stock ticker

        Returns:
            Dict with:
                date            str     "2025-01-30"
                eps_estimate    float
                revenue_estimate float
                fiscal_year     int
                fiscal_quarter  int
                source          str

        Example:
            cal = tc.earnings_calendar("AAPL")
            print(f"Next earnings: {cal['date']}")
        """
        if not self._fmp_key:
            return {"error": "FMP_API_KEY not set", "ticker": ticker.upper()}

        url = f"{FMP_BASE}/earning_calendar"
        try:
            resp = requests.get(
                url,
                params={"symbol": ticker.upper(), "apikey": self._fmp_key},
                timeout=10,
                headers=_HEADERS,
            )
            if not resp.ok:
                return {"error": f"HTTP {resp.status_code}", "ticker": ticker.upper()}

            data = resp.json()
            if not data:
                return {"error": "no_data", "ticker": ticker.upper()}

            # Filter to future dates
            today = datetime.now().date()
            future = [e for e in data if e.get("date", "") >= str(today)]
            item = future[0] if future else data[0]

            return {
                "ticker":            ticker.upper(),
                "date":              item.get("date", ""),
                "eps_estimate":      item.get("epsEstimated"),
                "revenue_estimate":  item.get("revenueEstimated"),
                "fiscal_year":       item.get("fiscalDateEnding", "")[:4],
                "fiscal_quarter":    None,
                "source":            "fmp",
            }
        except Exception as e:
            return {"error": str(e), "ticker": ticker.upper()}

    # ─────────────────────────────────────────────
    # FMP SOURCE
    # ─────────────────────────────────────────────

    def _fmp_transcript(self, ticker: str, limit: int = 1) -> list[dict]:
        """Fetch transcripts from Financial Modeling Prep API."""
        if not self._fmp_key:
            return []
        url = f"{FMP_BASE}/earning_call_transcript/{ticker.upper()}"
        try:
            resp = requests.get(
                url,
                params={"limit": limit, "apikey": self._fmp_key},
                timeout=15,
                headers=_HEADERS,
            )
            if not resp.ok:
                return []
            data = resp.json()
            if not data or isinstance(data, dict):
                return []

            results = []
            for item in data[:limit]:
                results.append({
                    "ticker":     ticker.upper(),
                    "date":       item.get("date", ""),
                    "year":       int(item.get("year", 0)),
                    "quarter":    int(item.get("quarter", 0)),
                    "transcript": item.get("content", ""),
                    "source":     "fmp",
                    "url":        f"https://financialmodelingprep.com/financial-transcripts/{ticker.lower()}",
                })
            return results
        except Exception:
            return []

    # ─────────────────────────────────────────────
    # SEC 8-K SOURCE
    # ─────────────────────────────────────────────

    def _sec_8k_transcript(self, ticker: str) -> dict:
        """
        Fetch earnings press release from SEC 8-K Item 2.02 exhibit.
        Free, covers all US-listed companies, no API key needed.
        """
        try:
            from edgar import Company, set_identity
            set_identity("brickellquant@brickellquant.com")

            c       = Company(ticker.upper())
            filings = c.get_filings(form="8-K").latest(10)

            # Find an 8-K with Item 2.02 (results of operations)
            for filing in filings:
                items = str(getattr(filing, "items", "") or "")
                if "2.02" in items:
                    filing_url = str(getattr(filing, "filing_url", ""))
                    date_str   = str(getattr(filing, "filing_date", ""))

                    # Try to get press release exhibit text
                    try:
                        f_obj = filing.obj()
                        text  = ""
                        for attr in ["press_release", "exhibit_text", "__str__"]:
                            val = getattr(f_obj, attr, None)
                            if callable(val):
                                text = str(val())
                            elif val:
                                text = str(val)
                            if len(text) > 500:
                                break
                    except Exception:
                        text = ""

                    if len(text) > 200:
                        # Parse year/quarter from date
                        year, quarter = _date_to_quarter(date_str)
                        return {
                            "ticker":     ticker.upper(),
                            "date":       date_str,
                            "year":       year,
                            "quarter":    quarter,
                            "transcript": text[:50_000],
                            "source":     "sec_8k",
                            "url":        filing_url,
                        }
        except Exception:
            pass

        return {
            "ticker":     ticker.upper(),
            "date":       "",
            "year":       0,
            "quarter":    0,
            "transcript": "",
            "source":     "unavailable",
            "url":        "",
        }

    # ─────────────────────────────────────────────
    # MOTLEY FOOL SOURCE (fallback, fragile)
    # ─────────────────────────────────────────────

    def _motley_fool_transcript(self, ticker: str) -> dict:
        """Scrape Motley Fool earnings transcript as last resort."""
        try:
            search_url = f"https://www.fool.com/earnings-call-transcripts/?ticker={ticker.upper()}"
            resp = requests.get(search_url, timeout=15, headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"
            })
            if not resp.ok:
                raise Exception(f"HTTP {resp.status_code}")

            soup  = BeautifulSoup(resp.content, "lxml")
            links = soup.find_all("a", href=lambda x: x and "earnings-call-transcript" in str(x))

            if not links:
                raise Exception("no transcript links found")

            time.sleep(2)
            link_url = links[0]["href"]
            if link_url.startswith("/"):
                link_url = "https://www.fool.com" + link_url

            page  = requests.get(link_url, timeout=15, headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"
            })
            psoup = BeautifulSoup(page.content, "lxml")
            body  = (psoup.find("div", class_="article-body")
                     or psoup.find("div", {"data-id": "article-body"})
                     or psoup.find("main"))

            text = body.get_text(separator="\n", strip=True) if body else ""
            if len(text) < 200:
                raise Exception("transcript too short")

            title = links[0].get_text(strip=True)
            year, quarter = _extract_year_quarter_from_title(title)

            return {
                "ticker":     ticker.upper(),
                "date":       "",
                "year":       year,
                "quarter":    quarter,
                "transcript": text[:50_000],
                "source":     "motley_fool",
                "url":        link_url,
            }
        except Exception as e:
            return {
                "ticker":     ticker.upper(),
                "date":       "", "year": 0, "quarter": 0,
                "transcript": "",
                "source":     "unavailable",
                "url":        "",
                "error":      str(e),
            }


# ─────────────────────────────────────────────────────────────
# TEXT ANALYSIS HELPERS
# ─────────────────────────────────────────────────────────────

_POSITIVE_WORDS = {"strong","record","exceed","beat","growth","accelerat","confident",
                   "momentum","expand","robust","deliver","outperform","improve","raised",
                   "guidance","beat","positive","cash","profitable","margin","new high"}
_NEGATIVE_WORDS = {"miss","decline","disappoint","headwind","uncertain","challeng",
                   "concern","weak","slowdown","pressure","below","reduce","cut",
                   "impairment","write","loss","difficult","caution","volatile"}
_GUIDANCE_PHRASES = ["we expect","we guide","we anticipate","outlook","next quarter",
                     "full year","fiscal year","we project","looking ahead","going forward"]


def _tone_score(text: str) -> float:
    """Return a 0.0-1.0 tone score (0=very negative, 0.5=neutral, 1=very positive)."""
    lower = text.lower()
    pos = sum(1 for w in _POSITIVE_WORDS if w in lower)
    neg = sum(1 for w in _NEGATIVE_WORDS if w in lower)
    total = max(pos + neg, 1)
    return round(0.5 + (pos - neg) / (total * 2), 4)


def _extract_key_phrases(text: str) -> list[str]:
    """Extract sentences containing guidance/forward-looking language."""
    sentences = re.split(r"[.!?]\s+", text)
    phrases = []
    for s in sentences:
        if any(p in s.lower() for p in _GUIDANCE_PHRASES):
            phrases.append(s.strip()[:200])
        if len(phrases) >= 10:
            break
    return phrases


def _extract_quotes(text: str, n: int = 3) -> list[str]:
    """Extract sentences that look like direct executive quotes."""
    sentences = re.split(r"[.!?]\s+", text)
    quotes = []
    for s in sentences:
        if any(kw in s.lower() for kw in ["i believe","we believe","our strategy","we are focused"]):
            q = s.strip()
            if 30 < len(q) < 300:
                quotes.append(q)
        if len(quotes) >= n:
            break
    return quotes


def _extract_guidance(text: str) -> str:
    """Extract the first block of forward-looking guidance language."""
    sentences = re.split(r"[.!?]\s+", text)
    for s in sentences:
        if any(p in s.lower() for p in ["we guide","we expect","we anticipate","our outlook"]):
            return s.strip()[:500]
    return ""


def _summarise_tone(text: str) -> str:
    """One-line tone summary for before/after comparison."""
    score = _tone_score(text)
    if score > 0.60:
        return "Confident and forward-looking; management projecting strong momentum"
    elif score > 0.50:
        return "Mildly positive; measured optimism with acknowledgement of challenges"
    elif score > 0.40:
        return "Neutral-cautious; balanced outlook, no clear directional signal"
    else:
        return "Cautious or defensive; headwind language dominant"


def _date_to_quarter(date_str: str) -> tuple[int, int]:
    """Convert ISO date string to (year, quarter)."""
    try:
        dt = datetime.strptime(str(date_str)[:10], "%Y-%m-%d")
        return dt.year, (dt.month - 1) // 3 + 1
    except Exception:
        return 0, 0


def _extract_year_quarter_from_title(title: str) -> tuple[int, int]:
    """Parse year and quarter from title like 'Apple Q3 2024 Earnings Call'."""
    m = re.search(r"Q([1-4])\s*(\d{4})", title, re.IGNORECASE)
    if m:
        return int(m.group(2)), int(m.group(1))
    m = re.search(r"(\d{4})", title)
    if m:
        return int(m.group(1)), 0
    return 0, 0
