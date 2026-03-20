"""
SECClient — SEC EDGAR interface via edgartools
=============================================

SETUP:
    from tools.sec import SECClient
    sec = SECClient(identity="your@email.com")
    # Or: export SEC_IDENTITY="your@email.com"

REFERENCE: tools/sec/README.md
edgartools docs: https://edgartools.readthedocs.io/
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

# edgartools — https://github.com/dgunning/edgartools
try:
    from edgar import Company, set_identity
    EDGAR_AVAILABLE = True
except ImportError:
    EDGAR_AVAILABLE = False

from tools.utils.cache import cached
from tools.utils.types import DilutionSnapshot, FilingResult


class SECClient:
    """
    Clean agent interface to SEC EDGAR via edgartools 5.x.

    All methods return plain Python dicts or pandas DataFrames.

    Args:
        identity: Your name/email for SEC EDGAR user-agent header.
                  Required by SEC. Example: "agent@brickellquant.com"
                  Can also be set via SEC_IDENTITY env var.

    Example:
        sec = SECClient(identity="agent@brickellquant.com")
        fins = sec.financials("AAPL")
        print(fins["income_statement"])
    """

    def __init__(self, identity: Optional[str] = None):
        if not EDGAR_AVAILABLE:
            raise ImportError(
                "edgartools is not installed. Run: uv add edgartools"
            )
        self._identity = (
            identity
            or os.environ.get("SEC_IDENTITY")
            or "brickellquant-agent@brickellquant.com"
        )
        set_identity(self._identity)

    # ─────────────────────────────────────────────
    # COMPANY & FILING RETRIEVAL
    # ─────────────────────────────────────────────

    @cached(ttl=300)
    def company(self, ticker: str) -> "Company":
        """
        Get edgartools Company object for a ticker.

        Returns:
            Company with .name, .cik, .get_filings(), .get_financials()

        Example:
            c = sec.company("AAPL")
            print(c.name, c.cik)   # "Apple Inc."  320193
        """
        return Company(ticker.upper())

    @cached(ttl=300)
    def filings(
        self,
        ticker: str,
        form: str = "10-K",
        limit: int = 10,
    ) -> list[FilingResult]:
        """
        Get recent filings for a company.

        Args:
            ticker: Stock ticker symbol
            form:   SEC form type ("10-K","10-Q","8-K","4","S-1","DEF 14A",etc.)
            limit:  Max number of filings to return

        Returns:
            List of FilingResult dicts:
                accession_number, form_type, filing_date,
                period_of_report, company, cik, url

        Example:
            for f in sec.filings("TSLA", form="8-K", limit=5):
                print(f["filing_date"], f["form_type"], f["url"])
        """
        c = Company(ticker.upper())
        entity_filings = c.get_filings(form=form)

        results: list[FilingResult] = []
        # latest(n>1) returns EntityFilings (iterable); latest(1) returns EntityFiling
        raw = entity_filings.latest(limit) if limit > 1 else entity_filings.latest(1)

        # Normalise to iterable
        items = list(raw) if not _is_single_filing(raw) else [raw]

        for filing in items:
            results.append(
                FilingResult(
                    accession_number=str(getattr(filing, "accession_no", "") or
                                        getattr(filing, "accession_number", "")),
                    form_type=str(getattr(filing, "form", form)),
                    filing_date=str(getattr(filing, "filing_date", "")),
                    period_of_report=str(getattr(filing, "period_of_report", "")),
                    company=str(getattr(filing, "company", ticker.upper())),
                    cik=str(getattr(filing, "cik", "")),
                    url=str(getattr(filing, "filing_url", "")),
                )
            )
        return results

    @cached(ttl=300)
    def latest(self, ticker: str, form: str = "10-K"):
        """
        Get the most recent filing object (raw edgartools EntityFiling).

        Example:
            f = sec.latest("AAPL", "10-K")
            print(f.filing_date, f.period_of_report)
            print(f.filing_url)
        """
        c = Company(ticker.upper())
        return c.get_filings(form=form).latest(1)

    def tenk(self, ticker: str):
        """Latest 10-K EntityFiling. Use sec.financials() for parsed statements."""
        return self.latest(ticker, "10-K")

    def tenq(self, ticker: str):
        """Latest 10-Q EntityFiling."""
        return self.latest(ticker, "10-Q")

    def eightk(self, ticker: str):
        """Latest 8-K EntityFiling."""
        return self.latest(ticker, "8-K")

    # ─────────────────────────────────────────────
    # FINANCIAL STATEMENTS
    # ─────────────────────────────────────────────

    @cached(ttl=600)
    def financials(self, ticker: str) -> dict:
        """
        Extract income statement, balance sheet, cash flow, and key metrics.

        Uses edgartools Financials XBRL engine — most accurate available.

        Args:
            ticker: Stock ticker symbol

        Returns:
            Dict with keys:
                "income_statement"  → pd.DataFrame
                "balance_sheet"     → pd.DataFrame
                "cash_flow"         → pd.DataFrame
                "metrics"           → dict (revenue, net_income, total_assets, etc.)
                "ticker"            → str

        Example:
            fins = sec.financials("AAPL")
            print(fins["income_statement"].head(10))
            print(fins["balance_sheet"].head(10))
            print(fins["metrics"])
            # metrics keys: revenue, operating_income, net_income, total_assets,
            #   total_liabilities, stockholders_equity, current_assets,
            #   current_liabilities, capital_expenditures, shares_outstanding_basic,
            #   shares_outstanding_diluted, current_ratio, debt_to_assets
        """
        c = Company(ticker.upper())
        fin = c.get_financials()

        result: dict = {
            "ticker": ticker.upper(),
            "income_statement": pd.DataFrame(),
            "balance_sheet":    pd.DataFrame(),
            "cash_flow":        pd.DataFrame(),
            "metrics":          {},
        }

        for key, method_name in [
            ("income_statement", "income_statement"),
            ("balance_sheet",    "balance_sheet"),
            ("cash_flow",        "cash_flow_statement"),
        ]:
            try:
                stmt = getattr(fin, method_name)()
                if stmt is not None and hasattr(stmt, "to_dataframe"):
                    result[key] = stmt.to_dataframe()
            except Exception as e:
                result[f"{key}_error"] = str(e)

        try:
            result["metrics"] = fin.get_financial_metrics() or {}
        except Exception as e:
            result["metrics_error"] = str(e)

        return result

    @cached(ttl=600)
    def metrics(self, ticker: str) -> dict:
        """
        Shortcut: key financial metrics from latest 10-K XBRL data.

        Returns:
            Dict with: revenue, operating_income, net_income, total_assets,
            total_liabilities, stockholders_equity, current_assets,
            current_liabilities, capital_expenditures, free_cash_flow,
            shares_outstanding_basic, shares_outstanding_diluted,
            current_ratio, debt_to_assets

        Example:
            m = sec.metrics("AAPL")
            print(f"Revenue:    ${m['revenue']/1e9:.1f}B")
            print(f"Net Income: ${m['net_income']/1e9:.1f}B")
            print(f"Shares:     {m['shares_outstanding_basic']/1e9:.2f}B")
        """
        return self.financials(ticker).get("metrics", {})

    # ─────────────────────────────────────────────
    # INSIDER TRANSACTIONS (FORM 4)
    # ─────────────────────────────────────────────

    @cached(ttl=600)
    def insider_trades(self, ticker: str, days: int = 90) -> pd.DataFrame:
        """
        Fetch Form 4 insider transactions for a company.

        Args:
            ticker: Stock ticker symbol
            days:   Lookback window in days (default: 90)

        Returns:
            DataFrame with columns:
                date, insider, title, transaction, shares, price,
                value, is_10b5_1, form_url

        Example:
            df = sec.insider_trades("NVDA", days=90)
            buys = df[df["transaction"] == "Purchase"]
            c_suite = buys[buys["title"].str.contains("CEO|CFO", na=False)]
        """
        c = Company(ticker.upper())
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        try:
            form4_filings = c.get_filings(form="4").filter(date_from=cutoff)
        except Exception:
            form4_filings = c.get_filings(form="4").latest(50)

        rows = []
        try:
            for filing in form4_filings:
                try:
                    f4 = filing.obj()
                    for txn in getattr(f4, "transactions", []):
                        rows.append(
                            {
                                "date": getattr(txn, "transaction_date", None),
                                "insider": getattr(f4, "reporting_owner_name", "Unknown"),
                                "title": getattr(f4, "reporting_owner_title", ""),
                                "transaction": _map_transaction_code(
                                    getattr(txn, "transaction_code", "")
                                ),
                                "shares": abs(float(getattr(txn, "shares", 0) or 0)),
                                "price": float(getattr(txn, "price_per_share", 0) or 0),
                                "value": abs(float(getattr(txn, "shares", 0) or 0))
                                         * float(getattr(txn, "price_per_share", 0) or 0),
                                "is_10b5_1": bool(
                                    getattr(txn, "transaction_plan_code", "") == "A"
                                ),
                                "form_url": str(getattr(filing, "filing_url", "")),
                            }
                        )
                except Exception:
                    continue
        except Exception:
            pass

        if not rows:
            return pd.DataFrame(
                columns=["date","insider","title","transaction",
                         "shares","price","value","is_10b5_1","form_url"]
            )

        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        return df.sort_values("date", ascending=False).reset_index(drop=True)

    # ─────────────────────────────────────────────
    # DILUTION ANALYSIS
    # ─────────────────────────────────────────────

    @cached(ttl=3600)
    def dilution_snapshot(self, ticker: str) -> DilutionSnapshot:
        """
        Dilution risk from XBRL data (basic vs fully-diluted shares).

        Args:
            ticker: Stock ticker symbol

        Returns:
            DilutionSnapshot TypedDict:
                ticker, basic_shares_out (M), options_shares (M),
                rsu_shares (M), warrant_shares (M), convertible_shares (M),
                atm_remaining_shares (M), fully_diluted_shares (M),
                total_dilution_pct, risk_level, source_filing, as_of_date

        Risk levels:
            LOW <10%  MEDIUM 10-25%  HIGH 25-50%  CRITICAL >50%

        Example:
            d = sec.dilution_snapshot("LCID")
            print(f"{d['ticker']} | {d['risk_level']} | {d['total_dilution_pct']:.1f}%")
        """
        c = Company(ticker.upper())
        source = ""
        as_of  = ""
        basic  = 0.0
        diluted = 0.0

        try:
            fin = c.get_financials()

            # Most reliable source: XBRL financial data
            basic_raw   = fin.get_shares_outstanding_basic()
            diluted_raw = fin.get_shares_outstanding_diluted()

            if basic_raw:
                basic = float(basic_raw) / 1_000_000
            if diluted_raw:
                diluted = float(diluted_raw) / 1_000_000

            # Filing metadata
            filing = c.get_filings(form="10-K").latest(1)
            source = str(getattr(filing, "filing_url", ""))
            as_of  = str(getattr(filing, "period_of_report", ""))

        except Exception:
            pass

        # Implied options/RSU/warrant dilution = diluted - basic
        implied_dilutive = max(0.0, diluted - basic)
        fully_diluted    = diluted if diluted > 0 else basic
        dilution_pct     = (implied_dilutive / basic * 100) if basic > 0 else 0.0

        if dilution_pct < 10:
            risk = "LOW"
        elif dilution_pct < 25:
            risk = "MEDIUM"
        elif dilution_pct < 50:
            risk = "HIGH"
        else:
            risk = "CRITICAL"

        return DilutionSnapshot(
            ticker=ticker.upper(),
            basic_shares_out=round(basic, 2),
            options_shares=round(implied_dilutive, 2),   # implied from diluted - basic
            rsu_shares=0.0,
            warrant_shares=0.0,
            convertible_shares=0.0,
            atm_remaining_shares=0.0,
            fully_diluted_shares=round(fully_diluted, 2),
            total_dilution_pct=round(dilution_pct, 2),
            risk_level=risk,
            source_filing=source,
            as_of_date=as_of,
        )

    # ─────────────────────────────────────────────
    # OWNERSHIP (13F / 13D / 13G)
    # ─────────────────────────────────────────────

    @cached(ttl=3600)
    def ownership(self, ticker: str, form: str = "13F-HR") -> pd.DataFrame:
        """
        Institutional / activist ownership filings.

        Args:
            form: "13F-HR" (institutional), "SC 13D" (activist), "SC 13G" (passive)

        Example:
            inst = sec.ownership("AAPL", form="13F-HR")
            activist = sec.ownership("X", form="SC 13D")
        """
        c = Company(ticker.upper())
        try:
            raw = c.get_filings(form=form).latest(5)
            rows = []
            for f in (list(raw) if not _is_single_filing(raw) else [raw]):
                rows.append({
                    "filing_date": str(getattr(f, "filing_date", "")),
                    "period":      str(getattr(f, "period_of_report", "")),
                    "form_type":   str(getattr(f, "form", form)),
                    "url":         str(getattr(f, "filing_url", "")),
                })
            return pd.DataFrame(rows)
        except Exception as e:
            return pd.DataFrame({"error": [str(e)]})

    # ─────────────────────────────────────────────
    # RISK FACTORS
    # ─────────────────────────────────────────────

    @cached(ttl=3600)
    def risk_factors(self, ticker: str) -> list[str]:
        """
        Risk factor headings from the latest 10-K (Item 1A).

        Returns:
            List of risk factor title strings (up to 50)

        Example:
            risks = sec.risk_factors("NVDA")
            supply_chain = [r for r in risks if "supply chain" in r.lower()]
        """
        c = Company(ticker.upper())
        try:
            filing  = c.get_filings(form="10-K").latest(1)
            tenk    = filing.obj()
            rf      = getattr(tenk, "risk_factors", None)
            if rf is None:
                return ["[Risk factors not available for this filing]"]
            if isinstance(rf, str):
                lines = [l.strip() for l in rf.split("\n") if len(l.strip()) > 20]
                return lines[:50]
            if isinstance(rf, list):
                return rf[:50]
            return [str(rf)]
        except Exception as e:
            return [f"[Error: {e}]"]

    # ─────────────────────────────────────────────
    # RED FLAG DETECTION
    # ─────────────────────────────────────────────

    @cached(ttl=1800)
    def red_flags(self, ticker: str) -> list[dict]:
        """
        Scan recent 8-K filings and 10-K for critical red flags.

        Checks:
          8-K Item 4.01 — Auditor change        (CRITICAL)
          8-K Item 4.02 — Non-reliance/restate  (CRITICAL)
          8-K Item 2.06 — Material impairment   (HIGH)
          8-K Item 2.05 — Restructuring         (MEDIUM)
          10-K going concern language           (CRITICAL)
          10-K material weakness                (HIGH)

        Returns:
            List of dicts: type, severity, description, filing_date, filing_url

        Example:
            for f in sec.red_flags("GME"):
                print(f"[{f['severity']}] {f['type']}: {f['description']}")
        """
        flags  = []
        c      = Company(ticker.upper())

        CRITICAL_ITEMS = {
            "4.01": ("AUDITOR_CHANGE", "CRITICAL",
                     "Auditor change detected (8-K Item 4.01)"),
            "4.02": ("NON_RELIANCE",   "CRITICAL",
                     "Non-reliance on prior financials — potential restatement (8-K Item 4.02)"),
            "2.06": ("IMPAIRMENT",     "HIGH",
                     "Material impairment charge (8-K Item 2.06)"),
            "2.05": ("RESTRUCTURING",  "MEDIUM",
                     "Restructuring/exit costs (8-K Item 2.05)"),
        }

        # ── Scan 8-K items ────────────────────────────────────────────
        try:
            eightk_filings = c.get_filings(form="8-K").latest(20)
            for filing in (list(eightk_filings)
                           if not _is_single_filing(eightk_filings)
                           else [eightk_filings]):
                filing_date = str(getattr(filing, "filing_date", ""))
                filing_url  = str(getattr(filing, "filing_url",  ""))
                items_str   = str(getattr(filing, "items", "") or "")

                for item_code, (flag_type, severity, msg) in CRITICAL_ITEMS.items():
                    if item_code in items_str:
                        flags.append({
                            "type":        flag_type,
                            "severity":    severity,
                            "description": msg,
                            "filing_date": filing_date,
                            "filing_url":  filing_url,
                        })
        except Exception:
            pass

        # ── Scan 10-K for going concern / material weakness ───────────
        try:
            tenk_filing = c.get_filings(form="10-K").latest(1)
            filing_date = str(getattr(tenk_filing, "filing_date", ""))
            filing_url  = str(getattr(tenk_filing, "filing_url",  ""))
            tenk        = tenk_filing.obj()

            text = ""
            for attr in ["auditor_report", "management_report"]:
                try:
                    val = getattr(tenk, attr, None)
                    if val:
                        text += str(val) + " "
                except Exception:
                    pass
            text_lower = text.lower()

            if any(p in text_lower for p in
                   ["going concern", "substantial doubt",
                    "ability to continue as a going concern"]):
                flags.append({
                    "type":        "GOING_CONCERN",
                    "severity":    "CRITICAL",
                    "description": "Going concern language in 10-K auditor/management report",
                    "filing_date": filing_date,
                    "filing_url":  filing_url,
                })

            if "material weakness" in text_lower:
                flags.append({
                    "type":        "MATERIAL_WEAKNESS",
                    "severity":    "HIGH",
                    "description": "Material weakness in internal controls disclosed in 10-K",
                    "filing_date": filing_date,
                    "filing_url":  filing_url,
                })
        except Exception:
            pass

        return flags

    # ─────────────────────────────────────────────
    # FULL-TEXT SEARCH
    # ─────────────────────────────────────────────

    @cached(ttl=600)
    def search(
        self,
        query: str,
        form: Optional[str] = None,
        limit: int = 10,
    ) -> list[dict]:
        """
        Full-text search across SEC EDGAR filings (EFTS).

        Args:
            query: Search terms (e.g. "going concern substantial doubt")
            form:  Optional form type filter ("10-K", "8-K", etc.)
            limit: Max results

        Returns:
            List of dicts: company, ticker, form_type, filing_date, url

        Example:
            results = sec.search("lithium supply chain risk", form="10-K", limit=5)
            for r in results:
                print(r["company"], r["filing_date"])
        """
        try:
            from edgar import full_text_search
            results = full_text_search(query, form=form, hits=limit)
            return [
                {
                    "company":     str(getattr(r, "entity_name", "")),
                    "ticker":      str(getattr(r, "ticker",       "")),
                    "form_type":   str(getattr(r, "form_type",    "")),
                    "filing_date": str(getattr(r, "file_date",    "")),
                    "url":         str(getattr(r, "filing_url",   "")
                                       or getattr(r, "filing_index", "")),
                }
                for r in (results or [])
            ]
        except Exception as e:
            return [{"error": str(e)}]


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def _is_single_filing(obj) -> bool:
    """True if obj is a single EntityFiling (not iterable EntityFilings)."""
    return hasattr(obj, "filing_url") and not hasattr(obj, "latest")


_TRANSACTION_CODES = {
    "P": "Purchase",
    "S": "Sale",
    "M": "Option Exercise",
    "A": "Grant/Award",
    "G": "Gift",
    "F": "Tax Withholding",
    "D": "Disposition",
    "I": "Discretionary Transaction",
    "C": "Convertible Note Conversion",
    "X": "Exercise of In-Money Derivative",
    "J": "Other",
}


def _map_transaction_code(code: str) -> str:
    return _TRANSACTION_CODES.get(str(code).strip().upper(), f"Other ({code})")
