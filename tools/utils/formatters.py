"""
tools.utils.formatters — Output formatting utilities

Usage:
    from tools.utils.formatters import print_table, to_markdown, fmt_number, fmt_pct
"""

from __future__ import annotations

from typing import Optional, Union
import pandas as pd


def fmt_number(n: Union[int, float, None], decimals: int = 2) -> str:
    """
    Format a large number into a human-readable string.

    Args:
        n: Number to format (None → "N/A")
        decimals: Decimal places

    Returns:
        str like "1.23T", "450.00B", "12.30M", "450.00K", "123.45"

    Example:
        fmt_number(1_234_567_890_000)  → "1.23T"
        fmt_number(450_000_000)        → "450.00M"
        fmt_number(12_345)             → "12.35K"
        fmt_number(123.45)             → "123.45"
        fmt_number(None)               → "N/A"
    """
    if n is None:
        return "N/A"
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "N/A"

    if abs(n) >= 1_000_000_000_000:
        return f"{n / 1_000_000_000_000:.{decimals}f}T"
    elif abs(n) >= 1_000_000_000:
        return f"{n / 1_000_000_000:.{decimals}f}B"
    elif abs(n) >= 1_000_000:
        return f"{n / 1_000_000:.{decimals}f}M"
    elif abs(n) >= 1_000:
        return f"{n / 1_000:.{decimals}f}K"
    else:
        return f"{n:.{decimals}f}"


def fmt_pct(n: Union[float, None], decimals: int = 2, sign: bool = True) -> str:
    """
    Format a float as a percentage string.

    Args:
        n: Decimal form (0.123 = 12.3%) OR already-percentage (12.3 → detect)
        decimals: Decimal places
        sign: If True, prefix positive numbers with "+"

    Returns:
        str like "+12.30%", "-5.40%", "N/A"

    Example:
        fmt_pct(0.1234)    → "+12.34%"
        fmt_pct(-0.054)    → "-5.40%"
        fmt_pct(None)      → "N/A"
    """
    if n is None:
        return "N/A"
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "N/A"

    # Auto-detect if already in percentage form
    pct_val = n * 100 if abs(n) < 1.5 else n
    prefix = "+" if (sign and pct_val > 0) else ""
    return f"{prefix}{pct_val:.{decimals}f}%"


def fmt_dollar(n: Union[float, None], decimals: int = 2) -> str:
    """
    Format a number as a dollar amount.

    Example:
        fmt_dollar(1234567.89)  → "$1,234,567.89"
        fmt_dollar(None)        → "N/A"
    """
    if n is None:
        return "N/A"
    try:
        return f"${float(n):,.{decimals}f}"
    except (TypeError, ValueError):
        return "N/A"


def to_markdown(
    df: pd.DataFrame,
    max_rows: int = 50,
    float_fmt: str = "{:.4f}",
) -> str:
    """
    Convert a DataFrame to a Markdown table string.

    Args:
        df: DataFrame to convert
        max_rows: Max rows to include (truncates with note if exceeded)
        float_fmt: Format string for float values

    Returns:
        Markdown table string

    Example:
        md = to_markdown(fins["income_statement"])
        print(md)
    """
    if df is None or df.empty:
        return "_No data available_"

    # Truncate if needed
    truncated = False
    if len(df) > max_rows:
        df = df.head(max_rows)
        truncated = True

    # Format floats
    display_df = df.copy()
    for col in display_df.select_dtypes(include=["float64", "float32"]).columns:
        display_df[col] = display_df[col].apply(
            lambda x: float_fmt.format(x) if pd.notna(x) else "N/A"
        )

    # Build markdown
    lines = []

    # Header
    cols = list(display_df.columns)
    header = "| " + " | ".join(str(c) for c in cols) + " |"
    separator = "| " + " | ".join("---" for _ in cols) + " |"
    lines.append(header)
    lines.append(separator)

    # Rows
    for _, row in display_df.iterrows():
        line = "| " + " | ".join(str(v) if pd.notna(v) else "N/A" for v in row) + " |"
        lines.append(line)

    if truncated:
        lines.append(f"\n_... truncated to {max_rows} rows_")

    return "\n".join(lines)


def print_table(
    df: pd.DataFrame,
    title: Optional[str] = None,
    max_rows: int = 30,
) -> None:
    """
    Pretty-print a DataFrame to the terminal using rich if available,
    otherwise plain text.

    Args:
        df: DataFrame to display
        title: Optional table title
        max_rows: Max rows to display

    Example:
        print_table(fins["income_statement"], title="Income Statement")
        print_table(mkt.history("AAPL"), title="AAPL Price History", max_rows=10)
    """
    if df is None or df.empty:
        print("(empty table)")
        return

    display_df = df.head(max_rows)

    try:
        from rich.table import Table
        from rich.console import Console
        from rich import box

        console = Console()
        table = Table(
            title=title,
            box=box.SIMPLE_HEAVY,
            show_header=True,
            header_style="bold cyan",
        )

        # Add index as first column if meaningful
        if display_df.index.name or not isinstance(display_df.index, pd.RangeIndex):
            table.add_column(str(display_df.index.name or ""), style="bold")

        for col in display_df.columns:
            table.add_column(str(col))

        for idx, row in display_df.iterrows():
            row_vals = []
            if display_df.index.name or not isinstance(display_df.index, pd.RangeIndex):
                row_vals.append(str(idx))
            for val in row:
                if isinstance(val, float):
                    row_vals.append(f"{val:,.4f}" if abs(val) < 1e9 else fmt_number(val))
                else:
                    row_vals.append(str(val) if pd.notna(val) else "N/A")
            table.add_row(*row_vals)

        if len(df) > max_rows:
            table.caption = f"Showing {max_rows} of {len(df)} rows"

        console.print(table)

    except ImportError:
        # Fallback: plain pandas print
        if title:
            print(f"\n{'─' * 60}")
            print(f"  {title}")
            print(f"{'─' * 60}")
        print(display_df.to_string())
        if len(df) > max_rows:
            print(f"... ({len(df) - max_rows} more rows)")
        print()
