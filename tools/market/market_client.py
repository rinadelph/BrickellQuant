"""
MarketClient — Market data via yfinance
=======================================

SETUP:
    from tools.market import MarketClient
    mkt = MarketClient()

No API keys required. Uses Yahoo Finance (unofficial API).

REFERENCE: tools/market/README.md
"""

from __future__ import annotations

from typing import Optional, Union

import pandas as pd

try:
    import yfinance as yf
    YF_AVAILABLE = True
except ImportError:
    YF_AVAILABLE = False

from tools.utils.cache import cached
from tools.utils.types import PriceQuote
from tools.utils.formatters import fmt_number


class MarketClient:
    """
    Clean agent interface for market data via yfinance.

    All methods return plain Python dicts or pandas DataFrames.
    No authentication required.

    Example:
        mkt = MarketClient()
        price = mkt.price("NVDA")
        print(f"${price['price']:,.2f}  ({price['change_pct']:+.2f}%)")
    """

    def __init__(self):
        if not YF_AVAILABLE:
            raise ImportError(
                "yfinance is not installed. Run: pip install yfinance"
            )

    # ─────────────────────────────────────────────
    # PRICE & QUOTE
    # ─────────────────────────────────────────────

    @cached(ttl=60)
    def price(self, ticker: str) -> PriceQuote:
        """
        Get current price and basic trading stats for a ticker.

        Args:
            ticker: Stock ticker symbol (e.g. "AAPL")

        Returns:
            PriceQuote TypedDict with keys:
                - ticker: str
                - price: float          ← current/last price
                - open: float
                - high: float
                - low: float
                - prev_close: float
                - change: float         ← price change today
                - change_pct: float     ← % change today
                - volume: int
                - avg_volume: int
                - market_cap: float
                - market_cap_fmt: str   ← "1.23T", "450B", "12.3M"
                - fifty_two_week_high: float
                - fifty_two_week_low: float
                - currency: str
                - exchange: str

        Example:
            q = mkt.price("NVDA")
            print(f"${q['price']:,.2f}  ({q['change_pct']:+.2f}%)")
            print(f"Market Cap: {q['market_cap_fmt']}")
        """
        t = yf.Ticker(ticker.upper())
        info = t.info

        price = float(
            info.get("currentPrice")
            or info.get("regularMarketPrice")
            or info.get("previousClose")
            or 0
        )
        prev_close = float(info.get("regularMarketPreviousClose") or info.get("previousClose") or price)
        change = price - prev_close
        change_pct = (change / prev_close * 100) if prev_close else 0.0
        mkt_cap = float(info.get("marketCap") or 0)

        return PriceQuote(
            ticker=ticker.upper(),
            price=price,
            open=float(info.get("regularMarketOpen") or info.get("open") or 0),
            high=float(info.get("regularMarketDayHigh") or info.get("dayHigh") or 0),
            low=float(info.get("regularMarketDayLow") or info.get("dayLow") or 0),
            prev_close=prev_close,
            change=round(change, 4),
            change_pct=round(change_pct, 4),
            volume=int(info.get("regularMarketVolume") or info.get("volume") or 0),
            avg_volume=int(info.get("averageVolume") or 0),
            market_cap=mkt_cap,
            market_cap_fmt=fmt_number(mkt_cap),
            fifty_two_week_high=float(info.get("fiftyTwoWeekHigh") or 0),
            fifty_two_week_low=float(info.get("fiftyTwoWeekLow") or 0),
            currency=str(info.get("currency") or "USD"),
            exchange=str(info.get("exchange") or ""),
        )

    # ─────────────────────────────────────────────
    # HISTORICAL DATA
    # ─────────────────────────────────────────────

    @cached(ttl=300)
    def history(
        self,
        ticker: str,
        period: str = "1y",
        interval: str = "1d",
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Get OHLCV price history.

        Args:
            ticker: Stock ticker symbol
            period: "1d","5d","1mo","3mo","6mo","1y","2y","5y","10y","ytd","max"
            interval: "1m","2m","5m","15m","30m","60m","90m","1h","1d","5d","1wk","1mo","3mo"
            start: ISO date string "YYYY-MM-DD" (overrides period if provided)
            end: ISO date string "YYYY-MM-DD"

        Returns:
            DataFrame with columns: Open, High, Low, Close, Volume, Dividends, Stock Splits
            Index: DatetimeIndex

        Example:
            hist = mkt.history("AAPL", period="1y")
            print(hist.tail())

            # Intraday
            intraday = mkt.history("SPY", period="5d", interval="1h")

            # Custom range
            hist = mkt.history("MSFT", start="2023-01-01", end="2024-01-01")
        """
        t = yf.Ticker(ticker.upper())
        if start:
            df = t.history(start=start, end=end, interval=interval)
        else:
            df = t.history(period=period, interval=interval)
        return df

    @cached(ttl=300)
    def multi_history(
        self,
        tickers: list[str],
        period: str = "1y",
        interval: str = "1d",
    ) -> pd.DataFrame:
        """
        Download OHLCV history for multiple tickers simultaneously.

        Args:
            tickers: List of ticker symbols
            period: Time period (same options as history())
            interval: Data interval (same options as history())

        Returns:
            DataFrame with MultiIndex columns (field, ticker)

        Example:
            df = mkt.multi_history(["AAPL","MSFT","GOOGL"], period="1y")
            close_prices = df["Close"]   # DataFrame with one column per ticker
        """
        return yf.download(
            " ".join([t.upper() for t in tickers]),
            period=period,
            interval=interval,
            group_by="ticker",
            progress=False,
        )

    # ─────────────────────────────────────────────
    # COMPANY INFO
    # ─────────────────────────────────────────────

    @cached(ttl=1800)
    def info(self, ticker: str) -> dict:
        """
        Get full company metadata from Yahoo Finance.

        Args:
            ticker: Stock ticker symbol

        Returns:
            Raw yfinance info dict with 100+ fields including:
                sector, industry, website, fullTimeEmployees,
                longBusinessSummary, country, city, etc.

        Example:
            info = mkt.info("AAPL")
            print(info["sector"], info["industry"])
            print(info["fullTimeEmployees"])
            print(info["longBusinessSummary"][:200])
        """
        return yf.Ticker(ticker.upper()).info

    @cached(ttl=1800)
    def fundamentals(self, ticker: str) -> dict:
        """
        Key fundamental ratios and valuation metrics.

        Args:
            ticker: Stock ticker symbol

        Returns:
            Dict with keys:
                - pe_ratio: float           ← Trailing P/E
                - forward_pe: float         ← Forward P/E
                - peg_ratio: float
                - price_to_book: float
                - price_to_sales: float
                - ev_ebitda: float          ← Enterprise Value / EBITDA
                - ev_revenue: float
                - gross_margin: float       ← 0.0–1.0
                - operating_margin: float
                - profit_margin: float
                - roe: float                ← Return on Equity
                - roa: float                ← Return on Assets
                - debt_to_equity: float
                - current_ratio: float
                - quick_ratio: float
                - fcf_yield: float          ← FCF / Market Cap
                - dividend_yield: float
                - beta: float
                - eps_ttm: float            ← EPS trailing 12 months
                - revenue_ttm: float
                - ebitda: float
                - total_debt: float
                - total_cash: float
                - book_value_per_share: float
                - shares_outstanding: int

        Example:
            f = mkt.fundamentals("MSFT")
            print(f"P/E: {f['pe_ratio']:.1f}  EV/EBITDA: {f['ev_ebitda']:.1f}")
            print(f"Gross Margin: {f['gross_margin']:.1%}")
            print(f"FCF Yield: {f['fcf_yield']:.2%}")
        """
        info = yf.Ticker(ticker.upper()).info

        mkt_cap = float(info.get("marketCap") or 0)
        fcf = float(info.get("freeCashflow") or 0)
        fcf_yield = (fcf / mkt_cap) if mkt_cap > 0 else 0.0

        return {
            "pe_ratio": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "peg_ratio": info.get("pegRatio"),
            "price_to_book": info.get("priceToBook"),
            "price_to_sales": info.get("priceToSalesTrailing12Months"),
            "ev_ebitda": info.get("enterpriseToEbitda"),
            "ev_revenue": info.get("enterpriseToRevenue"),
            "gross_margin": info.get("grossMargins"),
            "operating_margin": info.get("operatingMargins"),
            "profit_margin": info.get("profitMargins"),
            "roe": info.get("returnOnEquity"),
            "roa": info.get("returnOnAssets"),
            "debt_to_equity": info.get("debtToEquity"),
            "current_ratio": info.get("currentRatio"),
            "quick_ratio": info.get("quickRatio"),
            "fcf_yield": round(fcf_yield, 6),
            "dividend_yield": info.get("dividendYield"),
            "beta": info.get("beta"),
            "eps_ttm": info.get("trailingEps"),
            "revenue_ttm": info.get("totalRevenue"),
            "ebitda": info.get("ebitda"),
            "total_debt": info.get("totalDebt"),
            "total_cash": info.get("totalCash"),
            "book_value_per_share": info.get("bookValue"),
            "shares_outstanding": info.get("sharesOutstanding"),
        }

    # ─────────────────────────────────────────────
    # FINANCIAL STATEMENTS
    # ─────────────────────────────────────────────

    @cached(ttl=3600)
    def income(self, ticker: str, quarterly: bool = False) -> pd.DataFrame:
        """
        Income statement from Yahoo Finance.

        Args:
            ticker: Stock ticker
            quarterly: If True, return quarterly statements. Default: annual.

        Returns:
            DataFrame indexed by line item, columns are periods

        Example:
            annual = mkt.income("AAPL")
            quarterly = mkt.income("AAPL", quarterly=True)
        """
        t = yf.Ticker(ticker.upper())
        return t.quarterly_income_stmt if quarterly else t.income_stmt

    @cached(ttl=3600)
    def balance(self, ticker: str, quarterly: bool = False) -> pd.DataFrame:
        """
        Balance sheet from Yahoo Finance.

        Args:
            ticker: Stock ticker
            quarterly: If True, return quarterly. Default: annual.

        Returns:
            DataFrame indexed by line item, columns are periods

        Example:
            bs = mkt.balance("AAPL")
            cash = bs.loc["Cash And Cash Equivalents"].iloc[0]
        """
        t = yf.Ticker(ticker.upper())
        return t.quarterly_balance_sheet if quarterly else t.balance_sheet

    @cached(ttl=3600)
    def cashflow(self, ticker: str, quarterly: bool = False) -> pd.DataFrame:
        """
        Cash flow statement from Yahoo Finance.

        Args:
            ticker: Stock ticker
            quarterly: If True, return quarterly. Default: annual.

        Returns:
            DataFrame indexed by line item, columns are periods

        Example:
            cf = mkt.cashflow("NVDA")
            ocf = cf.loc["Operating Cash Flow"].iloc[0]
            capex = cf.loc["Capital Expenditure"].iloc[0]
            fcf = ocf + capex   # capex is negative
        """
        t = yf.Ticker(ticker.upper())
        return t.quarterly_cashflow if quarterly else t.cashflow

    # ─────────────────────────────────────────────
    # OPTIONS
    # ─────────────────────────────────────────────

    @cached(ttl=600)
    def options(
        self,
        ticker: str,
        expiry: Union[str, int] = "nearest",
    ) -> dict[str, pd.DataFrame]:
        """
        Get options chain for a specific expiration.

        Args:
            ticker: Stock ticker symbol
            expiry: "nearest" (default) | "farthest" | ISO date str "YYYY-MM-DD"
                    | int index into available expirations (0=nearest)

        Returns:
            Dict with keys:
                - "calls": DataFrame of call options
                - "puts": DataFrame of put options
                - "expiry": str (the expiration date used)
                - "available_expiries": list[str]

            Columns include: strike, lastPrice, bid, ask, volume,
                             openInterest, impliedVolatility, inTheMoney

        Example:
            chain = mkt.options("SPY")
            print(f"Expiry: {chain['expiry']}")
            print(chain["calls"][["strike","lastPrice","volume","openInterest"]].head(10))

            # Specific date
            chain = mkt.options("AAPL", expiry="2025-01-17")
        """
        t = yf.Ticker(ticker.upper())
        expirations = t.options

        if not expirations:
            return {"calls": pd.DataFrame(), "puts": pd.DataFrame(), "expiry": "", "available_expiries": []}

        if expiry == "nearest":
            chosen = expirations[0]
        elif expiry == "farthest":
            chosen = expirations[-1]
        elif isinstance(expiry, int):
            chosen = expirations[min(expiry, len(expirations) - 1)]
        else:
            # Find closest date
            chosen = min(expirations, key=lambda x: abs(pd.Timestamp(x) - pd.Timestamp(str(expiry))))

        chain = t.option_chain(chosen)
        return {
            "calls": chain.calls,
            "puts": chain.puts,
            "expiry": chosen,
            "available_expiries": list(expirations),
        }

    # ─────────────────────────────────────────────
    # HOLDERS
    # ─────────────────────────────────────────────

    @cached(ttl=3600)
    def holders(self, ticker: str) -> dict[str, pd.DataFrame]:
        """
        Institutional and insider ownership data.

        Args:
            ticker: Stock ticker symbol

        Returns:
            Dict with keys:
                - "institutional": DataFrame of top institutional holders
                - "mutual_funds": DataFrame of top mutual fund holders
                - "major": DataFrame (% float, % insiders, % institutions)

        Example:
            h = mkt.holders("AAPL")
            print(h["major"])
            print(h["institutional"].head(10))
        """
        t = yf.Ticker(ticker.upper())
        return {
            "institutional": t.institutional_holders or pd.DataFrame(),
            "mutual_funds": t.mutualfund_holders or pd.DataFrame(),
            "major": t.major_holders or pd.DataFrame(),
        }

    # ─────────────────────────────────────────────
    # ANALYST DATA
    # ─────────────────────────────────────────────

    @cached(ttl=3600)
    def recommendations(self, ticker: str) -> pd.DataFrame:
        """
        Analyst recommendation history.

        Args:
            ticker: Stock ticker

        Returns:
            DataFrame with period, strongBuy, buy, hold, sell, strongSell columns

        Example:
            recs = mkt.recommendations("AAPL")
            print(recs.tail(4))
        """
        t = yf.Ticker(ticker.upper())
        return t.recommendations or pd.DataFrame()

    @cached(ttl=3600)
    def price_targets(self, ticker: str) -> dict:
        """
        Analyst price targets.

        Args:
            ticker: Stock ticker

        Returns:
            Dict with: current, low, high, mean, median

        Example:
            pt = mkt.price_targets("NVDA")
            print(f"Mean target: ${pt['mean']:.2f}  High: ${pt['high']:.2f}")
        """
        t = yf.Ticker(ticker.upper())
        raw = t.analyst_price_targets or {}
        return {
            "current": raw.get("current"),
            "low": raw.get("low"),
            "high": raw.get("high"),
            "mean": raw.get("mean"),
            "median": raw.get("median"),
        }

    @cached(ttl=3600)
    def calendar(self, ticker: str) -> dict:
        """
        Earnings and event calendar.

        Args:
            ticker: Stock ticker

        Returns:
            Dict with upcoming earnings date, revenue/EPS estimates, ex-dividend date

        Example:
            cal = mkt.calendar("AAPL")
            print(cal)
        """
        t = yf.Ticker(ticker.upper())
        raw = t.calendar or {}
        return dict(raw) if hasattr(raw, "items") else {}

    # ─────────────────────────────────────────────
    # COMPARISON & SCREENING
    # ─────────────────────────────────────────────

    @cached(ttl=600)
    def compare(
        self,
        tickers: list[str],
        metric: str = "pe_ratio",
        period: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Compare a single metric across multiple tickers.

        Args:
            tickers: List of ticker symbols
            metric: Any key from fundamentals() dict, or:
                    "price","change_pct","market_cap" from price()
            period: For historical metrics, e.g. "1y" returns price returns

        Returns:
            DataFrame with tickers as index, metric as column

        Example:
            # Compare P/E ratios
            df = mkt.compare(["AAPL","MSFT","GOOGL","META"], metric="pe_ratio")
            print(df.sort_values("pe_ratio"))

            # Compare gross margins
            df = mkt.compare(["AAPL","MSFT","GOOGL"], metric="gross_margin")
        """
        rows = []
        for ticker in tickers:
            try:
                # Check fundamentals first, then price
                funds = self.fundamentals(ticker)
                if metric in funds and funds[metric] is not None:
                    rows.append({"ticker": ticker.upper(), metric: funds[metric]})
                else:
                    price_data = self.price(ticker)
                    rows.append({"ticker": ticker.upper(), metric: price_data.get(metric)})
            except Exception as e:
                rows.append({"ticker": ticker.upper(), metric: None, "error": str(e)})

        df = pd.DataFrame(rows).set_index("ticker")
        return df

    def screen(
        self,
        tickers: list[str],
        filters: Optional[dict] = None,
    ) -> pd.DataFrame:
        """
        Screen a list of tickers by fundamental criteria.

        Args:
            tickers: List of ticker symbols to screen
            filters: Dict of {metric: (operator, value)} pairs
                     Operators: "gt" (>), "lt" (<), "gte" (>=), "lte" (<=), "eq" (==)

        Returns:
            DataFrame of tickers passing all filters, with all fundamental metrics

        Example:
            # Find stocks with P/E < 20 and gross margin > 50%
            result = mkt.screen(
                ["AAPL","MSFT","GOOGL","META","AMZN","TSLA","NVDA"],
                filters={
                    "pe_ratio": ("lt", 30),
                    "gross_margin": ("gt", 0.40),
                    "debt_to_equity": ("lt", 100),
                }
            )
            print(result)
        """
        _ops = {
            "gt": lambda a, b: a > b,
            "lt": lambda a, b: a < b,
            "gte": lambda a, b: a >= b,
            "lte": lambda a, b: a <= b,
            "eq": lambda a, b: a == b,
        }

        rows = []
        for ticker in tickers:
            try:
                data = self.fundamentals(ticker)
                data["ticker"] = ticker.upper()
                rows.append(data)
            except Exception:
                continue

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows).set_index("ticker")

        if filters:
            for metric, (op, val) in filters.items():
                if metric in df.columns:
                    mask = df[metric].apply(
                        lambda x: _ops[op](float(x), val)
                        if x is not None and x == x  # not NaN
                        else False
                    )
                    df = df[mask]

        return df
