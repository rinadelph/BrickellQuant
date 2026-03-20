"""
GlobalClient — Global equity coverage
=====================================
Handles:
  · Exchange ticker normalisation (LSE, TSX, ASX, Frankfurt, Tokyo, HK, NSE, etc.)
  · Non-US regulatory filing RSS feeds (FCA, ESMA, ASX, HKEX, TSX)
  · ISIN ↔ ticker cross-reference
  · Multi-currency price helpers

SETUP:
    from tools.global_data import GlobalClient
    g = GlobalClient()

COVERS FinanceForge:
    All sections — when the target company is non-US listed
    Section III — short interest (ESMA short positions)
    Section XII — peer comps across exchanges
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

import pandas as pd
import requests

try:
    import yfinance as yf
    YF_AVAILABLE = True
except ImportError:
    YF_AVAILABLE = False

try:
    import feedparser
    FEEDPARSER_AVAILABLE = True
except ImportError:
    FEEDPARSER_AVAILABLE = False

from tools.utils.cache import cached

_HEADERS = {"User-Agent": "BrickellQuant/1.0 research@brickellquant.com"}

# ── Exchange suffix map ───────────────────────────────────────────────────────
# yfinance uses these suffixes for non-US tickers
EXCHANGE_SUFFIXES = {
    # Europe
    "LSE":        ".L",     # London Stock Exchange
    "XETRA":      ".DE",    # Deutsche Börse Xetra (Germany)
    "FRANKFURT":  ".F",     # Frankfurt Stock Exchange
    "EURONEXT":   ".PA",    # Euronext Paris
    "AMSTERDAM":  ".AS",    # Euronext Amsterdam
    "BRUSSELS":   ".BR",    # Euronext Brussels
    "MILAN":      ".MI",    # Borsa Italiana / Euronext Milan
    "MADRID":     ".MC",    # Bolsa de Madrid
    "STOCKHOLM":  ".ST",    # Nasdaq Stockholm
    "OSLO":       ".OL",    # Oslo Børs
    "COPENHAGEN": ".CO",    # Nasdaq Copenhagen
    "HELSINKI":   ".HE",    # Nasdaq Helsinki
    "ZURICH":     ".SW",    # SIX Swiss Exchange
    "WARSAW":     ".WA",    # Warsaw Stock Exchange
    "VIENNA":     ".VI",    # Wiener Börse
    # Americas
    "TSX":        ".TO",    # Toronto Stock Exchange
    "TSXV":       ".V",     # TSX Venture
    "BMV":        ".MX",    # Bolsa Mexicana de Valores
    "BOVESPA":    ".SA",    # B3 / São Paulo
    "BVBA":       ".BA",    # Buenos Aires
    # Asia-Pacific
    "TSE":        ".T",     # Tokyo Stock Exchange
    "JPX":        ".T",
    "KOSPI":      ".KS",    # Korea Stock Exchange
    "KOSDAQ":     ".KQ",    # KOSDAQ
    "SSE":        ".SS",    # Shanghai Stock Exchange
    "SZSE":       ".SZ",    # Shenzhen Stock Exchange
    "HKEX":       ".HK",    # Hong Kong Stock Exchange
    "ASX":        ".AX",    # Australian Securities Exchange
    "NSE":        ".NS",    # National Stock Exchange India
    "BSE":        ".BO",    # Bombay Stock Exchange
    "SGX":        ".SI",    # Singapore Exchange
    "BURSA":      ".KL",    # Bursa Malaysia
    "SET":        ".BK",    # Stock Exchange of Thailand
    "IDX":        ".JK",    # Indonesia Stock Exchange
    "PSE":        ".PS",    # Philippine Stock Exchange
    "TWSE":       ".TW",    # Taiwan Stock Exchange
    "TPEX":       ".TWO",   # Taipei Exchange
    # Middle East / Africa
    "TADAWUL":    ".SR",    # Saudi Exchange
    "ADX":        ".AD",    # Abu Dhabi Securities Exchange
    "DFM":        ".DU",    # Dubai Financial Market
    "TASE":       ".TA",    # Tel Aviv Stock Exchange
    "JSE":        ".JO",    # Johannesburg Stock Exchange
    "EGX":        ".CA",    # Egyptian Exchange
}

# ── Non-US regulatory filing RSS feeds ───────────────────────────────────────
GLOBAL_FILING_FEEDS = {
    # UK
    "FCA_UK":        "https://data.fca.org.uk/artefacts/NSM/TCRData.json",  # API, not RSS
    "RNS_UK":        "https://www.londonstockexchange.com/exchange/news/market-news/market-news-home.html",
    # ESMA
    "ESMA_SHORT":    "https://registers.esma.europa.eu/publication/searchRegister?core=esma_registers_sh_shsreg&q=*&wt=json&rows=20",
    # ASX
    "ASX_ANNOUNCEMENTS": "https://asx.api.markitdigital.com/asx-research/1.0/announcements/query?count=20",
    # HKEX
    "HKEX_NEWS":     "https://www1.hkexnews.hk/listedco/listconews/advancedsearch/search_active_main.aspx",
    # Canada SEDAR+
    "SEDAR_RSS":     "https://www.sedarplus.ca/landingpage/",
    # Japan EDINET
    "EDINET":        "https://disclosure.edinet-fsa.go.jp/api/v2/",
}


class GlobalClient:
    """
    Global equity coverage — ticker normalisation, non-US filing feeds,
    multi-currency price helpers, ISIN lookups.

    Example:
        g = GlobalClient()

        # Normalise ticker for any exchange
        t = g.normalise("BP", "LSE")       # → "BP.L"
        t = g.normalise("SAP", "XETRA")    # → "SAP.DE"
        t = g.normalise("7203", "TSE")     # → "7203.T"  (Toyota)

        # Get price in local currency
        q = g.price("BP.L")
        print(f"BP: {q['price']} {q['currency']}")

        # Live regulatory news feed for UK RNS
        news = g.rns_feed(limit=10)

        # ESMA short position disclosures
        shorts = g.esma_short_positions()
    """

    # ─────────────────────────────────────────────
    # TICKER NORMALISATION
    # ─────────────────────────────────────────────

    def normalise(self, ticker: str, exchange: str) -> str:
        """
        Add the correct yfinance suffix for a given exchange.

        Args:
            ticker:   Raw ticker (e.g. "BP", "SAP", "7203", "RELIANCE")
            exchange: Exchange name from EXCHANGE_SUFFIXES keys
                      (e.g. "LSE", "XETRA", "TSE", "NSE", "HKEX")

        Returns:
            yfinance-compatible ticker string (e.g. "BP.L", "SAP.DE", "7203.T")

        Example:
            g.normalise("BP",          "LSE")       → "BP.L"
            g.normalise("SAP",         "XETRA")     → "SAP.DE"
            g.normalise("7203",        "TSE")       → "7203.T"  (Toyota)
            g.normalise("RELIANCE",    "NSE")       → "RELIANCE.NS"
            g.normalise("700",         "HKEX")      → "700.HK"  (Tencent)
            g.normalise("SHOP",        "TSX")       → "SHOP.TO" (Shopify on TSX)
            g.normalise("RIO",         "LSE")       → "RIO.L"
            g.normalise("BHP",         "ASX")       → "BHP.AX"
            g.normalise("NESN",        "ZURICH")    → "NESN.SW"
        """
        suffix = EXCHANGE_SUFFIXES.get(exchange.upper(), "")
        base   = ticker.upper().split(".")[0]   # strip any existing suffix
        return f"{base}{suffix}" if suffix else base

    def detect_exchange(self, ticker: str) -> Optional[str]:
        """
        Detect the exchange from a ticker's suffix.

        Args:
            ticker: Ticker with suffix (e.g. "BP.L", "SAP.DE")

        Returns:
            Exchange name string or None

        Example:
            g.detect_exchange("BP.L")    → "LSE"
            g.detect_exchange("SAP.DE")  → "XETRA"
            g.detect_exchange("AAPL")    → None  (US, no suffix)
        """
        suffix_to_exchange = {v: k for k, v in EXCHANGE_SUFFIXES.items()}
        if "." not in ticker:
            return None
        suffix = "." + ticker.split(".")[-1]
        return suffix_to_exchange.get(suffix)

    def is_us_ticker(self, ticker: str) -> bool:
        """Return True if ticker has no exchange suffix (assumed US-listed)."""
        return "." not in ticker

    def all_exchanges(self) -> dict[str, str]:
        """Return all supported exchange names and their yfinance suffixes."""
        return dict(EXCHANGE_SUFFIXES)

    # ─────────────────────────────────────────────
    # MULTI-EXCHANGE PRICE
    # ─────────────────────────────────────────────

    @cached(ttl=120)
    def price(self, ticker: str) -> dict:
        """
        Price quote for any global ticker (raw yfinance ticker format).

        Args:
            ticker: yfinance-format ticker, e.g. "BP.L", "SAP.DE", "7203.T"

        Returns:
            Dict with: ticker, price, currency, exchange, change_pct, market_cap

        Example:
            # BP on London Stock Exchange (price in GBp)
            q = g.price("BP.L")
            print(f"{q['ticker']}: {q['price']} {q['currency']}")

            # SAP on Xetra (price in EUR)
            q = g.price("SAP.DE")

            # Toyota on Tokyo (price in JPY)
            q = g.price("7203.T")
        """
        if not YF_AVAILABLE:
            return {"error": "yfinance not available"}

        try:
            t    = yf.Ticker(ticker)
            info = t.info

            price    = float(info.get("currentPrice") or info.get("regularMarketPrice")
                             or info.get("previousClose") or 0)
            prev     = float(info.get("previousClose") or price)
            chg_pct  = ((price - prev) / prev * 100) if prev else 0.0
            currency = str(info.get("currency") or "")
            exchange = str(info.get("exchange") or self.detect_exchange(ticker) or "")
            mkt_cap  = float(info.get("marketCap") or 0)

            return {
                "ticker":      ticker,
                "price":       round(price, 4),
                "currency":    currency,
                "exchange":    exchange,
                "change_pct":  round(chg_pct, 4),
                "market_cap":  mkt_cap,
                "market_cap_usd": None,   # set by caller if FX rate available
            }
        except Exception as e:
            return {"error": str(e), "ticker": ticker}

    @cached(ttl=1800)
    def fundamentals(self, ticker: str) -> dict:
        """
        Fundamental ratios for a global ticker. Same as MarketClient.fundamentals()
        but accepts exchange-suffixed tickers directly.

        Example:
            f = g.fundamentals("7203.T")   # Toyota
            f = g.fundamentals("BP.L")     # BP London
        """
        if not YF_AVAILABLE:
            return {}
        info = yf.Ticker(ticker).info
        return {
            "pe_ratio":        info.get("trailingPE"),
            "forward_pe":      info.get("forwardPE"),
            "ev_ebitda":       info.get("enterpriseToEbitda"),
            "ev_revenue":      info.get("enterpriseToRevenue"),
            "gross_margin":    info.get("grossMargins"),
            "operating_margin":info.get("operatingMargins"),
            "profit_margin":   info.get("profitMargins"),
            "roe":             info.get("returnOnEquity"),
            "debt_to_equity":  info.get("debtToEquity"),
            "current_ratio":   info.get("currentRatio"),
            "dividend_yield":  info.get("dividendYield"),
            "beta":            info.get("beta"),
            "currency":        info.get("currency"),
        }

    # ─────────────────────────────────────────────
    # NON-US FILING FEEDS
    # ─────────────────────────────────────────────

    @cached(ttl=300)
    def rns_feed(self, company: Optional[str] = None, limit: int = 20) -> list[dict]:
        """
        UK Regulatory News Service (RNS) — London Stock Exchange announcements.
        Free, no API key. Real-time.

        Args:
            company: Optional company name filter
            limit:   Max results

        Returns:
            List of dicts: {headline, company, datetime, category, url}

        Example:
            # All RNS news
            news = g.rns_feed(limit=15)

            # Filter for a company
            bp_news = g.rns_feed(company="BP", limit=5)
        """
        # LSE RNS via their public feed
        url = "https://api.londonstockexchange.com/api/gw/lse/instruments/alldata/announcements"
        try:
            resp = requests.get(url, timeout=10, headers=_HEADERS)
            if not resp.ok:
                # Fallback to feedparser
                return self._lse_rss_fallback(company, limit)
            data = resp.json()
            items = data.get("announcements", data) if isinstance(data, dict) else data
            results = []
            for item in (items or [])[:limit]:
                if company and company.lower() not in str(item).lower():
                    continue
                results.append({
                    "headline": item.get("headline", item.get("title", "")),
                    "company":  item.get("issuerName", item.get("company", "")),
                    "datetime": item.get("releaseTime", item.get("date", "")),
                    "category": item.get("category", ""),
                    "url":      item.get("url", ""),
                })
            return results
        except Exception:
            return self._lse_rss_fallback(company, limit)

    def _lse_rss_fallback(self, company: Optional[str], limit: int) -> list[dict]:
        """RSS fallback for LSE RNS."""
        if not FEEDPARSER_AVAILABLE:
            return [{"error": "feedparser not installed"}]
        try:
            feed = feedparser.parse(
                "https://www.londonstockexchange.com/exchange/news/market-news/market-news-home.html",
                request_headers=_HEADERS
            )
            results = []
            for entry in feed.entries[:limit]:
                title = entry.get("title", "")
                if company and company.lower() not in title.lower():
                    continue
                results.append({
                    "headline": title,
                    "company":  company or "",
                    "datetime": str(entry.get("published", "")),
                    "category": "",
                    "url":      str(entry.get("link", "")),
                })
            return results
        except Exception as e:
            return [{"error": str(e)}]

    @cached(ttl=3600)
    def esma_short_positions(
        self,
        min_pct: float = 0.5,
        country: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        ESMA short position disclosures (EU regulation — all positions ≥ 0.5% of float).
        Free, no API key.

        Args:
            min_pct: Minimum short position % (default: 0.5)
            country: EU country code filter ("DE","FR","IT","NL","ES",etc.)

        Returns:
            DataFrame with: company, isin, position_holder, position_pct, date, country

        Example:
            shorts = g.esma_short_positions()
            high = shorts[shorts["position_pct"] > 2.0]
            print(high)
        """
        url = (
            "https://registers.esma.europa.eu/publication/searchRegister"
            "?core=esma_registers_sh_shsreg&q=*&wt=json&rows=100"
        )
        if country:
            url += f"&fq=issuer_country%3A{country.upper()}"

        try:
            resp = requests.get(url, timeout=15, headers=_HEADERS)
            if not resp.ok:
                return pd.DataFrame({"error": [f"HTTP {resp.status_code}"]})

            data = resp.json()
            docs = data.get("response", {}).get("docs", [])

            rows = []
            for d in docs:
                pct = float(d.get("net_short_position", 0) or 0)
                if pct < min_pct:
                    continue
                rows.append({
                    "company":         d.get("issuer_name", ""),
                    "isin":            d.get("isin", ""),
                    "position_holder": d.get("position_holder_name", ""),
                    "position_pct":    round(pct, 4),
                    "date":            d.get("position_date", ""),
                    "country":         d.get("issuer_country", ""),
                })

            if not rows:
                return pd.DataFrame(columns=["company","isin","position_holder",
                                              "position_pct","date","country"])
            df = pd.DataFrame(rows)
            return df.sort_values("position_pct", ascending=False).reset_index(drop=True)

        except Exception as e:
            return pd.DataFrame({"error": [str(e)]})

    @cached(ttl=600)
    def asx_announcements(self, ticker: Optional[str] = None, limit: int = 20) -> list[dict]:
        """
        ASX (Australian Securities Exchange) company announcements.
        Free API.

        Args:
            ticker: ASX ticker without suffix (e.g. "BHP", "RIO", "CBA")
            limit:  Max results

        Returns:
            List of dicts: {headline, company, date, url, category}

        Example:
            news = g.asx_announcements("BHP", limit=5)
            all_news = g.asx_announcements(limit=20)
        """
        base_url = "https://asx.api.markitdigital.com/asx-research/1.0/announcements/query"
        params = {"count": limit}
        if ticker:
            params["asxCode"] = ticker.upper()

        try:
            resp = requests.get(base_url, params=params, timeout=10, headers=_HEADERS)
            if not resp.ok:
                return [{"error": f"HTTP {resp.status_code}"}]

            data  = resp.json()
            items = data.get("data", {}).get("announcements", []) if isinstance(data, dict) else []

            return [
                {
                    "headline": item.get("header", ""),
                    "company":  item.get("issuerCode", ticker or ""),
                    "date":     item.get("marketSensitiveAt", ""),
                    "category": item.get("documentType", ""),
                    "url":      f"https://www.asx.com.au/asx/statistics/displayAnnouncement.do?display=pdf&idsId={item.get('id','')}",
                }
                for item in items[:limit]
            ]
        except Exception as e:
            return [{"error": str(e)}]

    # ─────────────────────────────────────────────
    # ISIN / IDENTIFIER HELPERS
    # ─────────────────────────────────────────────

    @cached(ttl=86400)
    def isin_lookup(self, isin: str) -> dict:
        """
        Look up company info by ISIN via GLEIF/OpenFIGI.
        No API key required for basic lookups.

        Args:
            isin: International Securities Identification Number
                  e.g. "US0378331005" (Apple), "GB0007980591" (BP)

        Returns:
            Dict with: name, ticker, exchange, country, currency, isin

        Example:
            info = g.isin_lookup("GB0007980591")
            print(info["name"], info["ticker"])   # "BP PLC", "BP"
        """
        # OpenFIGI (free, 25 req/min without key)
        url = "https://api.openfigi.com/v3/mapping"
        try:
            resp = requests.post(
                url,
                json=[{"idType": "ID_ISIN", "idValue": isin}],
                headers={**_HEADERS, "Content-Type": "application/json"},
                timeout=10,
            )
            if resp.ok:
                data = resp.json()
                hits = data[0].get("data", []) if data else []
                if hits:
                    h = hits[0]
                    return {
                        "isin":     isin,
                        "name":     h.get("name", ""),
                        "ticker":   h.get("ticker", ""),
                        "exchange": h.get("exchCode", ""),
                        "country":  "",
                        "currency": h.get("currency", ""),
                        "figi":     h.get("figi", ""),
                    }
        except Exception:
            pass

        return {"isin": isin, "error": "lookup failed"}

    @cached(ttl=86400)
    def ticker_to_isin(self, ticker: str, exchange: str = "") -> str:
        """
        Convert ticker to ISIN using OpenFIGI.

        Args:
            ticker:   Ticker symbol (with or without exchange suffix)
            exchange: Exchange MIC code or name (optional but improves accuracy)

        Returns:
            ISIN string or empty string if not found

        Example:
            isin = g.ticker_to_isin("BP", "LSE")    # "GB0007980591"
            isin = g.ticker_to_isin("AAPL")          # "US0378331005"
        """
        url = "https://api.openfigi.com/v3/mapping"
        body = [{"idType": "TICKER", "idValue": ticker.upper()}]
        if exchange:
            body[0]["exchCode"] = exchange.upper()

        try:
            resp = requests.post(
                url, json=body,
                headers={**_HEADERS, "Content-Type": "application/json"},
                timeout=10,
            )
            if resp.ok:
                data = resp.json()
                hits = data[0].get("data", []) if data else []
                for h in hits:
                    isin = h.get("isin", "")
                    if isin:
                        return isin
        except Exception:
            pass
        return ""
