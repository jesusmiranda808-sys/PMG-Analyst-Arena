"""
formatting.py
Small pure-function formatters used by all UI modules.
"""

import pandas as pd


def fmt_large(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "N/A"
    try:
        v = float(value)
        if abs(v) >= 1_000_000_000_000:
            return f"${v / 1_000_000_000_000:.2f}T"
        if abs(v) >= 1_000_000_000:
            return f"${v / 1_000_000_000:.2f}B"
        if abs(v) >= 1_000_000:
            return f"${v / 1_000_000:.2f}M"
        return f"${v:,.0f}"
    except Exception:
        return "N/A"


def fmt_pct_decimal(value) -> str:
    """For ratios expressed as decimals (e.g. 0.23 → 23.00%)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "N/A"
    try:
        return f"{float(value) * 100:.2f}%"
    except Exception:
        return "N/A"


def fmt_pct_number(value) -> str:
    """For numbers already in percent (e.g. 1.25 → 1.25%)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "N/A"
    try:
        return f"{float(value):.2f}%"
    except Exception:
        return "N/A"


def fmt_price(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "N/A"
    try:
        return f"${float(value):,.2f}"
    except Exception:
        return "N/A"


def fmt_number(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "N/A"
    try:
        return f"{float(value):,.2f}"
    except Exception:
        return "N/A"
