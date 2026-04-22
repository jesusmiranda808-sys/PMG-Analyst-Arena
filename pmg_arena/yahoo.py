"""
yahoo.py
Robust price layer. Replaces the flaky tk.get_info() dependency from the old app.

Strategy:
  1. History-based price/return (cheapest, most reliable)
  2. fast_info for extras (market cap, last price fallback)
  3. tk.info only as last-resort with tight try/except and NO requirement that it succeeds

This module is the ONLY place we should be touching yfinance.
"""

from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd
import streamlit as st
import yfinance as yf


def safe_float(value) -> Optional[float]:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


@st.cache_data(ttl=900, show_spinner=False)
def get_snapshot(ticker: str) -> dict:
    """
    Single-ticker snapshot for pitch-time display.
    Returns safe None values rather than raising on Yahoo failures.
    """
    price = None
    change_pct = None
    market_cap = None
    trailing_pe = None
    forward_pe = None
    volume = None
    avg_volume = None
    beta = None
    revenue_growth = None
    operating_margins = None
    summary = ""
    error = None

    try:
        tk = yf.Ticker(ticker)

        # Layer 1: history (most reliable)
        hist = tk.history(period="6mo", interval="1d", auto_adjust=False)
        if hist is not None and not hist.empty:
            hist = hist.dropna(subset=["Close"], how="all")
            if not hist.empty:
                last_close = safe_float(hist["Close"].iloc[-1])
                price = last_close
                if len(hist) >= 2 and last_close is not None:
                    prev_close = safe_float(hist["Close"].iloc[-2])
                    if prev_close not in (None, 0):
                        change_pct = ((last_close - prev_close) / prev_close) * 100

                if "Volume" in hist.columns:
                    vol_series = hist["Volume"].dropna()
                    if not vol_series.empty:
                        volume = safe_float(vol_series.iloc[-1])
                        avg_volume = safe_float(vol_series.tail(30).mean())

        # Layer 2: fast_info for extras
        try:
            fi = tk.fast_info
            market_cap = safe_float(fi.get("marketCap"))
            if price is None:
                price = safe_float(fi.get("lastPrice"))
            if volume is None:
                volume = safe_float(fi.get("lastVolume"))
        except Exception:
            pass

        # Layer 3: info (flaky, optional)
        try:
            info = tk.info
            trailing_pe = safe_float(info.get("trailingPE"))
            forward_pe = safe_float(info.get("forwardPE"))
            beta = safe_float(info.get("beta"))
            revenue_growth = safe_float(info.get("revenueGrowth"))
            operating_margins = safe_float(info.get("operatingMargins"))
            summary = info.get("longBusinessSummary", "") or ""
            if market_cap is None:
                market_cap = safe_float(info.get("marketCap"))
            if avg_volume is None:
                avg_volume = safe_float(info.get("averageVolume"))
        except Exception:
            pass

    except Exception as e:
        error = str(e)

    return {
        "ticker": ticker,
        "price": price,
        "change_pct": change_pct,
        "market_cap": market_cap,
        "trailing_pe": trailing_pe,
        "forward_pe": forward_pe,
        "volume": volume,
        "avg_volume": avg_volume,
        "beta": beta,
        "revenue_growth": revenue_growth,
        "operating_margins": operating_margins,
        "summary": summary,
        "error": error,
    }


@st.cache_data(ttl=3600, show_spinner=False)
def get_history(ticker: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    """Raw price history. Returns empty DataFrame on failure, never raises."""
    try:
        tk = yf.Ticker(ticker)
        hist = tk.history(period=period, interval=interval, auto_adjust=False)
        return hist if hist is not None else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def get_history_range(ticker: str, start: str, end: str) -> pd.DataFrame:
    """Historical price range for replay mode."""
    try:
        tk = yf.Ticker(ticker)
        hist = tk.history(start=start, end=end, interval="1d", auto_adjust=False)
        return hist if hist is not None else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def get_price_on_date(ticker: str, target_date: date) -> Optional[float]:
    """
    Get close price for a ticker on a specific trading date.
    If the date is a holiday/weekend, walks back up to 5 days to find the nearest trading day.
    Returns None if target_date is in the future (data doesn't exist yet).
    """
    if target_date > date.today():
        # Future date in historical_replay mode — can't resolve yet
        return None
    start = target_date - timedelta(days=7)
    end = target_date + timedelta(days=1)
    hist = get_history_range(ticker, start.isoformat(), end.isoformat())
    if hist is None or hist.empty:
        return None
    hist = hist.dropna(subset=["Close"])
    if hist.empty:
        return None
    # Closest trading day on or before target_date
    hist.index = pd.to_datetime(hist.index).tz_localize(None)
    target_ts = pd.Timestamp(target_date)
    valid = hist[hist.index <= target_ts]
    if valid.empty:
        return safe_float(hist["Close"].iloc[0])
    return safe_float(valid["Close"].iloc[-1])


def get_current_price(ticker: str) -> Optional[float]:
    """Latest price for live-compressed mode."""
    try:
        tk = yf.Ticker(ticker)
        try:
            fi = tk.fast_info
            p = safe_float(fi.get("lastPrice"))
            if p is not None:
                return p
        except Exception:
            pass
        hist = tk.history(period="1d", interval="1m")
        if hist is not None and not hist.empty:
            return safe_float(hist["Close"].dropna().iloc[-1])
    except Exception:
        return None
    return None


def simulate_walk_return(ticker: str, days: int, seed: Optional[int] = None) -> Optional[float]:
    """
    For 'simulated walk' mode: generate a synthetic return path using the stock's own
    historical drift and vol. Returns the final pct return over `days` trading days.

    Uses geometric Brownian motion calibrated to trailing 6mo of daily returns.
    """
    import numpy as np

    hist = get_history(ticker, period="6mo", interval="1d")
    if hist.empty or "Close" not in hist.columns:
        return None

    closes = hist["Close"].dropna()
    if len(closes) < 20:
        return None

    log_returns = (closes / closes.shift(1)).dropna().apply(lambda x: np.log(x) if x > 0 else 0)
    if len(log_returns) < 10:
        return None

    mu = float(log_returns.mean())
    sigma = float(log_returns.std())

    if seed is not None:
        np.random.seed(seed)

    shocks = np.random.normal(mu, sigma, days)
    total_log_return = float(shocks.sum())
    final_return_pct = (float(np.exp(total_log_return)) - 1) * 100
    return final_return_pct
