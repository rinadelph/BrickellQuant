"""
MacroClient — Macroeconomic data
================================
Sources: FRED (Federal Reserve) · yfinance FX/rates · World Bank API

SETUP:
    from tools.macro import MacroClient

    # FRED free key: fred.stlouisfed.org/docs/api/api_key.html (instant)
    # export FRED_API_KEY="your_key"

    macro = MacroClient()

COVERS FinanceForge:
    Section VII  — macro tailwinds, sector spending, AI/tech exposure
    Section VIII — geopolitical risk, commodity exposure
    Section IX   — strategic context, country risk
    Section XIII — WACC country risk premium, discount rate inputs
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import requests

try:
    from fredapi import Fred
    FRED_AVAILABLE = True
except ImportError:
    FRED_AVAILABLE = False

try:
    import yfinance as yf
    YF_AVAILABLE = True
except ImportError:
    YF_AVAILABLE = False

from tools.utils.cache import cached

# ── Key FRED series IDs ───────────────────────────────────────────────────────
FRED_SERIES = {
    # Growth
    "gdp_growth":        "A191RL1Q225SBEA",  # Real GDP growth rate QoQ
    "gdp_level":         "GDPC1",             # Real GDP level
    "us_pmi":            "NAPM",              # ISM Manufacturing PMI
    # Inflation
    "cpi":               "CPIAUCSL",          # CPI All items
    "pce":               "PCE",               # Personal consumption expenditures
    "ppi":               "PPIACO",            # PPI - All commodities
    # Rates
    "fed_funds":         "DFF",               # Fed Funds effective rate
    "sofr":              "SOFR",              # Secured overnight financing rate
    "us_10y":            "DGS10",             # 10-year treasury yield
    "us_2y":             "DGS2",              # 2-year treasury yield
    "yield_curve":       "T10Y2Y",            # 10Y-2Y spread (recession indicator)
    "vix":               "VIXCLS",            # CBOE VIX
    # Credit
    "hy_spread":         "BAMLH0A0HYM2",      # HY OAS spread
    "ig_spread":         "BAMLC0A0CM",        # IG OAS spread
    # Labour
    "unemployment":      "UNRATE",            # US unemployment rate
    "nonfarm_payrolls":  "PAYEMS",            # Non-farm payrolls
    # Housing / consumer
    "retail_sales":      "RSXFS",             # Retail sales ex-food services
    "consumer_sentiment":"UMCSENT",           # U of Mich consumer sentiment
    # Sector specific
    "it_spending":       "Y033RC1Q027SBEA",   # ICT investment (AI proxy)
    "defense_spending":  "FDEFX",             # Federal defence outlays
    "energy_prices_wti": "DCOILWTICO",        # WTI crude oil price
    "nat_gas":           "DHHNGSP",           # Henry Hub natural gas
    # Global
    "dxy":               "DTWEXBGS",          # US dollar broad index
    "euribor_3m":        "IR3TIB01EZM156N",   # Euribor 3-month
}

# ── Country risk premium estimates (Damodaran approach) ──────────────────────
# ERP = US_ERP + country_risk_premium
COUNTRY_RISK_PREMIUMS = {
    "US":  0.00, "CA":  0.005,"GB":  0.005,"DE":  0.005,"FR":  0.005,
    "JP":  0.005,"AU":  0.005,"NL":  0.005,"SE":  0.007,"CH":  0.003,
    "KR":  0.010,"TW":  0.010,"SG":  0.007,"HK":  0.010,"CN":  0.015,
    "BR":  0.040,"MX":  0.025,"IN":  0.020,"IT":  0.012,"ES":  0.010,
    "PL":  0.015,"RU":  0.150,"TR":  0.060,"ZA":  0.040,"NG":  0.080,
    "AR":  0.200,"VN":  0.030,"ID":  0.025,"TH":  0.020,"PH":  0.025,
    "IL":  0.020,"SA":  0.020,"AE":  0.015,
}


class MacroClient:
    """
    Macroeconomic data for FinanceForge tailwind/headwind + DCF inputs.

    All methods return dicts or DataFrames. Units noted in docstrings.

    Example:
        macro = MacroClient()

        # US macro snapshot
        snap = macro.us_snapshot()
        print(f"Fed Funds: {snap['fed_funds_rate']:.2f}%")
        print(f"10Y yield: {snap['us_10y_yield']:.2f}%")

        # WACC inputs for a UK company
        wacc = macro.wacc_inputs("GB")
        print(f"Risk-free rate: {wacc['risk_free_rate']:.2%}")
        print(f"Equity risk premium: {wacc['equity_risk_premium']:.2%}")
    """

    def __init__(self, fred_key: Optional[str] = None):
        self._fred_key = fred_key or os.environ.get("FRED_API_KEY", "")
        self._fred: Optional["Fred"] = None

        if FRED_AVAILABLE and self._fred_key:
            try:
                self._fred = Fred(api_key=self._fred_key)
            except Exception:
                self._fred = None

    # ─────────────────────────────────────────────
    # US MACRO SNAPSHOT
    # ─────────────────────────────────────────────

    @cached(ttl=3600)
    def us_snapshot(self) -> dict:
        """
        Key US macro indicators in a single call.

        Returns:
            Dict with:
                fed_funds_rate      float   current Fed Funds rate (%)
                us_10y_yield        float   10-year Treasury yield (%)
                us_2y_yield         float   2-year Treasury yield (%)
                yield_curve_spread  float   10Y - 2Y spread (negative = inverted)
                cpi_yoy             float   CPI YoY % (latest)
                unemployment        float   unemployment rate (%)
                vix                 float   VIX fear index
                hy_spread           float   High yield OAS spread (bps)
                dxy                 float   US Dollar broad index
                as_of               str     ISO date of most recent data

        Example:
            snap = macro.us_snapshot()
            if snap["yield_curve_spread"] < 0:
                print("WARNING: Inverted yield curve — recession signal")
        """
        if not self._fred:
            return self._no_fred_fallback()

        result = {"as_of": datetime.now().strftime("%Y-%m-%d")}
        mapping = {
            "fed_funds_rate":     "fed_funds",
            "us_10y_yield":       "us_10y",
            "us_2y_yield":        "us_2y",
            "yield_curve_spread": "yield_curve",
            "unemployment":       "unemployment",
            "vix":                "vix",
            "hy_spread":          "hy_spread",
            "dxy":                "dxy",
        }
        for key, series_id_key in mapping.items():
            try:
                val = self._fred.get_series(FRED_SERIES[series_id_key]).dropna().iloc[-1]
                result[key] = round(float(val), 4)
            except Exception:
                result[key] = None

        # CPI YoY
        try:
            cpi = self._fred.get_series(FRED_SERIES["cpi"]).dropna()
            if len(cpi) >= 13:
                yoy = (cpi.iloc[-1] / cpi.iloc[-13] - 1) * 100
                result["cpi_yoy"] = round(float(yoy), 2)
        except Exception:
            result["cpi_yoy"] = None

        return result

    # ─────────────────────────────────────────────
    # FRED SERIES
    # ─────────────────────────────────────────────

    @cached(ttl=3600)
    def fred_series(
        self,
        series_id: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> pd.Series:
        """
        Fetch any FRED series by ID.

        Args:
            series_id: FRED series ID (see FRED_SERIES dict for common ones)
                       or any ID from fred.stlouisfed.org
            start:     ISO date string "YYYY-MM-DD" (default: 5 years ago)
            end:       ISO date string (default: today)

        Returns:
            pandas Series indexed by date

        Example:
            # Get Fed Funds rate history
            ff = macro.fred_series("DFF", start="2020-01-01")
            print(ff.tail())

            # Named shortcut — use FRED_SERIES dict
            from tools.macro.macro_client import FRED_SERIES
            gdp = macro.fred_series(FRED_SERIES["gdp_growth"])
        """
        if not self._fred:
            return pd.Series(dtype=float, name=series_id)

        if start is None:
            start = (datetime.now() - timedelta(days=5 * 365)).strftime("%Y-%m-%d")

        try:
            return self._fred.get_series(series_id, observation_start=start,
                                         observation_end=end).dropna()
        except Exception as e:
            return pd.Series(dtype=float, name=series_id)

    @cached(ttl=3600)
    def named_series(self, name: str, **kwargs) -> pd.Series:
        """
        Fetch a FRED series by friendly name from the FRED_SERIES dict.

        Args:
            name: Key from FRED_SERIES (e.g. "fed_funds", "cpi", "us_10y")

        Returns:
            pandas Series

        Example:
            fed_funds = macro.named_series("fed_funds", start="2022-01-01")
            cpi       = macro.named_series("cpi")
            vix       = macro.named_series("vix")
        """
        series_id = FRED_SERIES.get(name)
        if not series_id:
            available = list(FRED_SERIES.keys())
            raise ValueError(f"Unknown name '{name}'. Available: {available}")
        return self.fred_series(series_id, **kwargs)

    # ─────────────────────────────────────────────
    # FX RATES
    # ─────────────────────────────────────────────

    @cached(ttl=300)
    def fx_rate(self, from_ccy: str, to_ccy: str = "USD") -> float:
        """
        Current FX rate via yfinance.

        Args:
            from_ccy: Base currency ISO code ("EUR", "GBP", "JPY", etc.)
            to_ccy:   Quote currency (default: "USD")

        Returns:
            float: Exchange rate (1 from_ccy = X to_ccy)

        Example:
            eur_usd = macro.fx_rate("EUR")      # e.g. 1.0850
            gbp_usd = macro.fx_rate("GBP")      # e.g. 1.2700
            usd_jpy = macro.fx_rate("USD","JPY") # e.g. 149.50
        """
        if not YF_AVAILABLE:
            return 1.0

        if from_ccy.upper() == to_ccy.upper():
            return 1.0

        symbol = f"{from_ccy.upper()}{to_ccy.upper()}=X"
        try:
            t = yf.Ticker(symbol)
            price = (t.info.get("regularMarketPrice")
                     or t.info.get("previousClose")
                     or t.history(period="1d")["Close"].iloc[-1])
            return float(price)
        except Exception:
            return 1.0

    @cached(ttl=300)
    def fx_history(
        self,
        from_ccy: str,
        to_ccy: str = "USD",
        period: str = "1y",
    ) -> pd.DataFrame:
        """
        Historical FX rate data.

        Returns:
            DataFrame with OHLCV columns, DatetimeIndex

        Example:
            eurusd = macro.fx_history("EUR", period="1y")
            gbpusd = macro.fx_history("GBP", "USD", period="2y")
        """
        if not YF_AVAILABLE:
            return pd.DataFrame()
        symbol = f"{from_ccy.upper()}{to_ccy.upper()}=X"
        try:
            return yf.Ticker(symbol).history(period=period)
        except Exception:
            return pd.DataFrame()

    # ─────────────────────────────────────────────
    # INTEREST RATES
    # ─────────────────────────────────────────────

    @cached(ttl=3600)
    def interest_rates(self, region: str = "US") -> dict:
        """
        Key interest rates for a region.

        Args:
            region: "US" | "EU" | "UK" | "JP"

        Returns:
            Dict of rate_name → current value (%)

        Example:
            us_rates = macro.interest_rates("US")
            eu_rates = macro.interest_rates("EU")
        """
        if region.upper() == "US" and self._fred:
            rates = {}
            for name in ["fed_funds", "sofr", "us_10y", "us_2y", "yield_curve"]:
                try:
                    val = self._fred.get_series(FRED_SERIES[name]).dropna().iloc[-1]
                    rates[name] = round(float(val), 4)
                except Exception:
                    rates[name] = None
            return rates

        # Non-US: use yfinance treasury approximations
        symbols = {
            "EU": {"ecb_rate": "^EURIBO3M", "eu_10y": "^TNX"},
            "UK": {"uk_base": "^GBP3M",     "uk_10y": "^TYX"},
            "JP": {"boj_rate": "^JGB10Y"},
        }
        region_syms = symbols.get(region.upper(), {})
        result = {}
        for name, sym in region_syms.items():
            try:
                val = yf.Ticker(sym).info.get("regularMarketPrice") or 0
                result[name] = round(float(val), 4)
            except Exception:
                result[name] = None
        return result

    # ─────────────────────────────────────────────
    # WACC INPUTS (for DCF engine)
    # ─────────────────────────────────────────────

    @cached(ttl=86400)
    def wacc_inputs(self, country_iso2: str = "US") -> dict:
        """
        WACC component inputs for a given country.
        Uses Damodaran country risk premium methodology.

        Args:
            country_iso2: 2-letter ISO country code (e.g. "US","GB","DE","CN")

        Returns:
            Dict with:
                risk_free_rate          float   e.g. 0.0425 (4.25%)
                equity_risk_premium     float   e.g. 0.055  (5.5%)
                country_risk_premium    float   e.g. 0.012  (1.2%)
                total_erp               float   ERP + CRP
                country                 str
                source                  str

        Example:
            # US company
            w = macro.wacc_inputs("US")
            # cost_of_equity = risk_free + beta * total_erp

            # Italian company
            w = macro.wacc_inputs("IT")
        """
        # Risk-free rate: US 10Y treasury
        risk_free = 0.04   # fallback
        try:
            if self._fred:
                val = self._fred.get_series(FRED_SERIES["us_10y"]).dropna().iloc[-1]
                risk_free = round(float(val) / 100, 6)
            elif YF_AVAILABLE:
                val = yf.Ticker("^TNX").info.get("regularMarketPrice", 4.0)
                risk_free = round(float(val) / 100, 6)
        except Exception:
            pass

        # Damodaran ERP for US (mature market baseline)
        us_erp = 0.0472     # approximate 2024 Damodaran estimate

        crp = COUNTRY_RISK_PREMIUMS.get(country_iso2.upper(), 0.03)
        total_erp = us_erp + crp

        return {
            "country":               country_iso2.upper(),
            "risk_free_rate":        risk_free,
            "equity_risk_premium":   us_erp,
            "country_risk_premium":  crp,
            "total_erp":             round(total_erp, 6),
            "source":                "FRED 10Y Treasury + Damodaran CRP (2024)",
        }

    # ─────────────────────────────────────────────
    # COMMODITY PRICES
    # ─────────────────────────────────────────────

    @cached(ttl=900)
    def commodities(self) -> dict:
        """
        Key commodity spot prices via yfinance.

        Returns:
            Dict of commodity_name → current price (USD)

        Example:
            c = macro.commodities()
            print(f"WTI Crude: ${c['wti_crude']:.2f}")
            print(f"Gold:      ${c['gold']:.0f}")
            print(f"Copper:    ${c['copper']:.4f}")
        """
        if not YF_AVAILABLE:
            return {}

        COMMODITY_TICKERS = {
            "wti_crude":  "CL=F",
            "brent":      "BZ=F",
            "nat_gas":    "NG=F",
            "gold":       "GC=F",
            "silver":     "SI=F",
            "copper":     "HG=F",
            "aluminium":  "ALI=F",
            "lithium":    "LIT",    # ETF proxy
            "iron_ore":   "TIO=F",
            "corn":       "ZC=F",
            "wheat":      "ZW=F",
            "soybeans":   "ZS=F",
        }
        result = {}
        for name, symbol in COMMODITY_TICKERS.items():
            try:
                t = yf.Ticker(symbol)
                price = (t.info.get("regularMarketPrice")
                         or t.info.get("previousClose")
                         or None)
                if price:
                    result[name] = round(float(price), 4)
            except Exception:
                pass
        return result

    # ─────────────────────────────────────────────
    # HELPERS
    # ─────────────────────────────────────────────

    def available_fred_series(self) -> dict[str, str]:
        """Return all pre-defined FRED series names and their IDs."""
        return dict(FRED_SERIES)

    def available_country_risk_premiums(self) -> dict[str, float]:
        """Return Damodaran country risk premiums table."""
        return dict(COUNTRY_RISK_PREMIUMS)

    def _no_fred_fallback(self) -> dict:
        return {
            "error": ("FRED_API_KEY not set. Get a free key at "
                      "fred.stlouisfed.org/docs/api/api_key.html then: "
                      "export FRED_API_KEY=your_key"),
            "as_of": datetime.now().strftime("%Y-%m-%d"),
        }
