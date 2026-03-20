"""
DCFEngine — Parameterisable Discounted Cash Flow model
=======================================================
Pure Python, no external APIs.
Inputs come from sec.metrics() + mkt.fundamentals() + macro.wacc_inputs().

COVERS FinanceForge:
    Section XIII — DCF Analysis
        - 5-10 year revenue/EBITDA/FCF projections
        - WACC calculation
        - Terminal value (Gordon Growth + EV/EBITDA exit multiple)
        - Implied share price (bear/base/bull)
        - Sensitivity table (WACC vs terminal growth)

USAGE:
    from tools.dcf import DCFEngine, DCFInputs

    inputs = DCFInputs(
        ticker           = "NVDA",
        current_revenue  = 60.9e9,
        revenue_growth   = [0.80, 0.50, 0.35, 0.25, 0.20],  # 5 years
        ebitda_margins   = [0.55, 0.58, 0.60, 0.61, 0.62],
        capex_pct_rev    = [0.06, 0.06, 0.05, 0.05, 0.05],
        wacc             = 0.09,
        terminal_growth  = 0.04,
        terminal_multiple= 30.0,
        net_debt         = -26.0e9,           # negative = net cash
        shares_diluted   = 24_514.0e6,
    )
    result = DCFEngine().run(inputs)
    print(f"Base case: ${result.implied_price_base:.2f}")
    print(result.summary_table())
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd


@dataclass
class DCFInputs:
    """
    All inputs required for a DCF model.
    Units: all dollar amounts in native currency (use consistent units throughout).

    Required:
        ticker            str     Company ticker symbol
        current_revenue   float   Most recent full-year revenue
        revenue_growth    list    YoY revenue growth rates for each projection year
                                  e.g. [0.30, 0.25, 0.20, 0.15, 0.12] = 5-year forecast
        ebitda_margins    list    EBITDA margin for each projection year (same length)
        capex_pct_rev     list    CapEx as % of revenue for each year (same length)
        wacc              float   Weighted average cost of capital (e.g. 0.09 = 9%)
        terminal_growth   float   Terminal growth rate (e.g. 0.03 = 3%)
        shares_diluted    float   Fully diluted shares outstanding (raw count)

    Optional:
        net_debt          float   Net debt (negative = net cash). Default: 0
        terminal_multiple float   EV/EBITDA exit multiple (alternative to Gordon Growth)
                                  If >0, blends 50/50 with Gordon Growth model
        tax_rate          float   Effective tax rate (default: 0.21)
        da_pct_rev        float   D&A as % of revenue (default: 0.05)
        nwc_change_pct    float   NWC change as % of revenue growth (default: 0.02)
        minority_interest float   Minority interest to deduct from equity value
        currency          str     Currency label for output (default: "USD")
        country_iso2      str     2-letter country code for risk-free rate context
    """
    ticker:            str
    current_revenue:   float
    revenue_growth:    list[float]
    ebitda_margins:    list[float]
    capex_pct_rev:     list[float]
    wacc:              float
    terminal_growth:   float
    shares_diluted:    float

    net_debt:          float = 0.0
    terminal_multiple: float = 0.0       # EV/EBITDA exit; 0 = Gordon Growth only
    tax_rate:          float = 0.21
    da_pct_rev:        float = 0.05      # D&A as % of revenue
    nwc_change_pct:    float = 0.02      # NWC change as % of revenue change
    minority_interest: float = 0.0
    currency:          str   = "USD"
    country_iso2:      str   = "US"

    def __post_init__(self):
        n = len(self.revenue_growth)
        assert len(self.ebitda_margins) == n, "ebitda_margins length must equal revenue_growth"
        assert len(self.capex_pct_rev) == n, "capex_pct_rev length must equal revenue_growth"
        assert 0 < self.wacc < 1, "wacc must be between 0 and 1"
        assert 0 <= self.terminal_growth < self.wacc, \
            "terminal_growth must be < wacc (otherwise TV is infinite)"


@dataclass
class DCFResult:
    """Output from DCFEngine.run()"""
    ticker:               str
    projection_years:     int
    currency:             str

    # Projected cash flows
    revenues:             list[float]      # projected revenues
    ebitdas:              list[float]      # projected EBITDAs
    fcfs:                 list[float]      # projected free cash flows
    pv_fcfs:              list[float]      # present values of FCFs

    # Enterprise value components
    pv_sum:               float            # sum of discounted FCFs
    terminal_value_gg:    float            # Gordon Growth terminal value
    terminal_value_mult:  float            # exit multiple terminal value
    terminal_value_used:  float            # blended terminal value (discounted)
    enterprise_value:     float            # PV sum + terminal value

    # Equity bridge
    net_debt:             float
    minority_interest:    float
    equity_value:         float            # EV - net_debt - minority_interest
    shares_diluted:       float

    # Implied prices
    implied_price_base:   float
    implied_price_bear:   float            # +1% WACC, -0.5% terminal growth
    implied_price_bull:   float            # -1% WACC, +0.5% terminal growth

    # Sensitivity table
    sensitivity:          dict             # {wacc: {tgr: implied_price}}

    # Metadata
    wacc:                 float
    terminal_growth:      float
    terminal_multiple:    float

    def summary_table(self) -> str:
        """Return a markdown-formatted DCF summary table."""
        n = self.projection_years
        years = [f"Year {i+1}" for i in range(n)]

        rows = []
        rows.append("| " + " | ".join(["Metric"] + years) + " |")
        rows.append("| " + " | ".join(["---"] * (n + 1)) + " |")

        def fmt(vals):
            return [_fmt_num(v, self.currency) for v in vals]

        rows.append("| Revenue | " + " | ".join(fmt(self.revenues)) + " |")
        rows.append("| EBITDA  | " + " | ".join(fmt(self.ebitdas))  + " |")
        rows.append("| FCF     | " + " | ".join(fmt(self.fcfs))     + " |")
        rows.append("| PV(FCF) | " + " | ".join(fmt(self.pv_fcfs))  + " |")
        rows.append("")
        rows.append(f"**Sum PV(FCFs):** {_fmt_num(self.pv_sum, self.currency)}")
        rows.append(f"**Terminal Value (discounted):** {_fmt_num(self.terminal_value_used, self.currency)}")
        rows.append(f"**Enterprise Value:** {_fmt_num(self.enterprise_value, self.currency)}")
        rows.append(f"**Net Debt / (Cash):** {_fmt_num(self.net_debt, self.currency)}")
        rows.append(f"**Equity Value:** {_fmt_num(self.equity_value, self.currency)}")
        rows.append(f"**Diluted Shares:** {self.shares_diluted/1e6:,.0f}M")
        rows.append("")
        rows.append(f"**Base Price:** {self.currency} {self.implied_price_base:,.2f}")
        rows.append(f"**Bear Price:** {self.currency} {self.implied_price_bear:,.2f}  "
                    f"(WACC +1%, tgr -0.5%)")
        rows.append(f"**Bull Price:** {self.currency} {self.implied_price_bull:,.2f}  "
                    f"(WACC -1%, tgr +0.5%)")

        return "\n".join(rows)

    def sensitivity_table(self) -> str:
        """Return markdown sensitivity table: WACC (rows) × terminal growth (cols)."""
        if not self.sensitivity:
            return "_No sensitivity data_"

        waccs = sorted(self.sensitivity.keys())
        tgrs  = sorted(next(iter(self.sensitivity.values())).keys())

        header = "| WACC \\ TGR | " + " | ".join(f"{t:.1%}" for t in tgrs) + " |"
        sep    = "| --- | " + " | ".join(["---"] * len(tgrs)) + " |"

        rows = [header, sep]
        for w in waccs:
            row = f"| {w:.1%} | "
            row += " | ".join(
                f"**{self.currency} {self.sensitivity[w][t]:,.2f}**"
                if (abs(w - self.wacc) < 0.001 and abs(t - self.terminal_growth) < 0.001)
                else f"{self.currency} {self.sensitivity[w][t]:,.2f}"
                for t in tgrs
            )
            row += " |"
            rows.append(row)

        return "\n".join(rows)


class DCFEngine:
    """
    Discounted Cash Flow modelling engine.

    All arithmetic is explicit and traceable — no black boxes.

    Example:
        from tools.dcf import DCFEngine, DCFInputs
        from tools.sec import SECClient
        from tools.market import MarketClient
        from tools.macro import MacroClient

        sec   = SECClient()
        mkt   = MarketClient()
        macro = MacroClient()

        # Pull real data
        m     = sec.metrics("NVDA")
        funds = mkt.fundamentals("NVDA")
        wacc_data = macro.wacc_inputs("US")

        beta = funds["beta"] or 1.5
        wacc = (wacc_data["risk_free_rate"]
                + beta * wacc_data["total_erp"]
                + 0.02)   # + size premium

        inputs = DCFInputs(
            ticker           = "NVDA",
            current_revenue  = m["revenue"],
            revenue_growth   = [0.80, 0.50, 0.35, 0.25, 0.20],
            ebitda_margins   = [0.55, 0.58, 0.60, 0.61, 0.62],
            capex_pct_rev    = [0.06, 0.06, 0.05, 0.05, 0.05],
            wacc             = wacc,
            terminal_growth  = 0.04,
            terminal_multiple= 30.0,
            net_debt         = -(m.get("total_cash",0) - m.get("total_debt",0)),
            shares_diluted   = m["shares_outstanding_diluted"],
        )
        result = DCFEngine().run(inputs)
        print(result.summary_table())
        print(result.sensitivity_table())
    """

    def run(self, inputs: DCFInputs) -> DCFResult:
        """
        Execute the DCF model.

        Args:
            inputs: DCFInputs dataclass with all model parameters

        Returns:
            DCFResult with all outputs, tables, and scenario prices
        """
        n = len(inputs.revenue_growth)

        # ── Project revenues ──────────────────────────────────────────
        revenues: list[float] = []
        rev = inputs.current_revenue
        for g in inputs.revenue_growth:
            rev = rev * (1 + g)
            revenues.append(rev)

        # ── Project EBITDA ────────────────────────────────────────────
        ebitdas: list[float] = [
            rev * m for rev, m in zip(revenues, inputs.ebitda_margins)
        ]

        # ── Project FCF ───────────────────────────────────────────────
        # FCF = EBITDA - taxes on EBIT - CapEx - NWC change
        fcfs: list[float] = []
        pv_fcfs: list[float] = []
        prev_rev = inputs.current_revenue

        for i, (rev, ebitda, capex_pct) in enumerate(
            zip(revenues, ebitdas, inputs.capex_pct_rev)
        ):
            da          = rev * inputs.da_pct_rev
            ebit        = ebitda - da
            taxes       = max(ebit, 0) * inputs.tax_rate
            nopat       = ebit - taxes
            capex       = rev * capex_pct
            da_addback  = da
            nwc_change  = (rev - prev_rev) * inputs.nwc_change_pct
            fcf         = nopat + da_addback - capex - nwc_change
            fcfs.append(fcf)

            # Present value
            discount = (1 + inputs.wacc) ** (i + 1)
            pv_fcfs.append(fcf / discount)
            prev_rev = rev

        pv_sum = sum(pv_fcfs)

        # ── Terminal value ────────────────────────────────────────────
        final_fcf   = fcfs[-1]
        final_rev   = revenues[-1]
        final_ebitda= ebitdas[-1]
        last_year   = n

        # Gordon Growth Model terminal value
        tv_gg_raw = (final_fcf * (1 + inputs.terminal_growth)
                     / (inputs.wacc - inputs.terminal_growth))
        tv_gg_pv  = tv_gg_raw / (1 + inputs.wacc) ** last_year

        # Exit multiple terminal value
        tv_mult_pv = 0.0
        if inputs.terminal_multiple > 0:
            tv_mult_raw = final_ebitda * inputs.terminal_multiple
            tv_mult_pv  = tv_mult_raw / (1 + inputs.wacc) ** last_year

        # Blend if both available
        if inputs.terminal_multiple > 0:
            tv_used = (tv_gg_pv + tv_mult_pv) / 2
        else:
            tv_used = tv_gg_pv

        # ── Enterprise value ──────────────────────────────────────────
        ev = pv_sum + tv_used

        # ── Equity value ──────────────────────────────────────────────
        equity_value = ev - inputs.net_debt - inputs.minority_interest
        base_price   = equity_value / inputs.shares_diluted if inputs.shares_diluted else 0

        # ── Scenarios ─────────────────────────────────────────────────
        bear_price = self._scenario_price(inputs, wacc_delta=+0.01, tgr_delta=-0.005)
        bull_price = self._scenario_price(inputs, wacc_delta=-0.01, tgr_delta=+0.005)

        # ── Sensitivity table ─────────────────────────────────────────
        wacc_range = [inputs.wacc + d for d in (-0.02, -0.01, 0, +0.01, +0.02)]
        tgr_range  = [inputs.terminal_growth + d for d in (-0.01, -0.005, 0, +0.005, +0.01)]
        # Clip invalid combos
        sensitivity: dict[float, dict[float, float]] = {}
        for w in wacc_range:
            w = round(max(0.04, w), 4)
            sensitivity[w] = {}
            for t in tgr_range:
                t = round(max(0.0, min(t, w - 0.005)), 4)
                try:
                    p = self._scenario_price(
                        inputs,
                        wacc_override=w,
                        tgr_override=t,
                    )
                    sensitivity[w][t] = round(p, 2)
                except Exception:
                    sensitivity[w][t] = 0.0

        return DCFResult(
            ticker               = inputs.ticker,
            projection_years     = n,
            currency             = inputs.currency,
            revenues             = revenues,
            ebitdas              = ebitdas,
            fcfs                 = fcfs,
            pv_fcfs              = pv_fcfs,
            pv_sum               = pv_sum,
            terminal_value_gg    = tv_gg_pv,
            terminal_value_mult  = tv_mult_pv,
            terminal_value_used  = tv_used,
            enterprise_value     = ev,
            net_debt             = inputs.net_debt,
            minority_interest    = inputs.minority_interest,
            equity_value         = equity_value,
            shares_diluted       = inputs.shares_diluted,
            implied_price_base   = round(base_price, 4),
            implied_price_bear   = round(bear_price, 4),
            implied_price_bull   = round(bull_price, 4),
            sensitivity          = sensitivity,
            wacc                 = inputs.wacc,
            terminal_growth      = inputs.terminal_growth,
            terminal_multiple    = inputs.terminal_multiple,
        )

    def _scenario_price(
        self,
        inputs: DCFInputs,
        wacc_delta: float = 0.0,
        tgr_delta: float = 0.0,
        wacc_override: Optional[float] = None,
        tgr_override: Optional[float] = None,
    ) -> float:
        """Run a scenario with adjusted WACC and/or terminal growth rate."""
        from dataclasses import replace

        new_wacc = wacc_override if wacc_override is not None else inputs.wacc + wacc_delta
        new_tgr  = tgr_override  if tgr_override  is not None else inputs.terminal_growth + tgr_delta

        # Safety clip
        new_wacc = max(0.04, new_wacc)
        new_tgr  = max(0.0, min(new_tgr, new_wacc - 0.005))

        new_inputs = replace(inputs, wacc=new_wacc, terminal_growth=new_tgr)
        result = self.run(new_inputs)
        return result.implied_price_base


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def _fmt_num(v: float, currency: str = "USD") -> str:
    """Format a large number as e.g. '$1.23B', '$450M'."""
    sign = "-" if v < 0 else ""
    av = abs(v)
    if av >= 1e12:
        return f"{sign}{currency} {av/1e12:.2f}T"
    elif av >= 1e9:
        return f"{sign}{currency} {av/1e9:.2f}B"
    elif av >= 1e6:
        return f"{sign}{currency} {av/1e6:.2f}M"
    elif av >= 1e3:
        return f"{sign}{currency} {av/1e3:.2f}K"
    return f"{sign}{currency} {av:.2f}"
