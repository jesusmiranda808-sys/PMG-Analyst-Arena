"""
universe.py
Index constituent loaders. Cached for 24h.
"""

from io import StringIO

import pandas as pd
import requests
import streamlit as st

SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
NASDAQ100_URL = "https://en.wikipedia.org/wiki/Nasdaq-100"
DOW30_URL = "https://en.wikipedia.org/wiki/Dow_Jones_Industrial_Average"

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
}


def _normalize_ticker(ticker: str) -> str:
    if not isinstance(ticker, str):
        return ticker
    return ticker.replace(".", "-").strip().upper()


def _clean_name(name: str) -> str:
    return str(name).strip()


@st.cache_data(ttl=86400, show_spinner=False)
def _fetch_tables(url: str):
    resp = requests.get(url, headers=UA, timeout=20)
    resp.raise_for_status()
    return pd.read_html(StringIO(resp.text))


@st.cache_data(ttl=86400, show_spinner=False)
def get_sp500() -> pd.DataFrame:
    tables = _fetch_tables(SP500_URL)
    df = tables[0].copy()
    df = df.rename(columns={
        "Symbol": "Ticker",
        "Security": "Company",
        "GICS Sector": "Sector",
        "GICS Sub-Industry": "Industry",
    })
    df = df[["Ticker", "Company", "Sector", "Industry"]].copy()
    df["Ticker"] = df["Ticker"].astype(str).map(_normalize_ticker)
    df["Company"] = df["Company"].astype(str).map(_clean_name)
    df["Universe"] = "S&P 500"
    return df.drop_duplicates(subset=["Ticker"]).reset_index(drop=True)


@st.cache_data(ttl=86400, show_spinner=False)
def get_nasdaq100() -> pd.DataFrame:
    tables = _fetch_tables(NASDAQ100_URL)
    target = None
    for t in tables:
        cols = [str(c).strip() for c in t.columns]
        if "Ticker" in cols and "Company" in cols:
            target = t.copy()
            break
    if target is None:
        raise ValueError("Could not find Nasdaq-100 constituent table.")

    # Normalize column naming across wiki variants
    rename_map = {
        "ICB Industry": "Sector",
        "ICB Subsector": "Industry",
        "Industry": "Sector",
        "Subsector": "Industry",
    }
    target = target.rename(columns=rename_map)

    if "Sector" not in target.columns:
        target["Sector"] = "Unknown"
    if "Industry" not in target.columns:
        target["Industry"] = "Unknown"

    df = target[["Ticker", "Company", "Sector", "Industry"]].copy()
    df["Ticker"] = df["Ticker"].astype(str).map(_normalize_ticker)
    df["Company"] = df["Company"].astype(str).map(_clean_name)
    df["Universe"] = "Nasdaq-100"
    return df.drop_duplicates(subset=["Ticker"]).reset_index(drop=True)


@st.cache_data(ttl=86400, show_spinner=False)
def get_dow30() -> pd.DataFrame:
    tables = _fetch_tables(DOW30_URL)
    target = None
    for t in tables:
        cols = [str(c).strip() for c in t.columns]
        if "Company" in cols and ("Symbol" in cols or "Ticker symbol" in cols):
            target = t.copy()
            break
    if target is None:
        raise ValueError("Could not find Dow constituent table.")

    if "Symbol" in target.columns:
        target = target.rename(columns={"Symbol": "Ticker"})
    elif "Ticker symbol" in target.columns:
        target = target.rename(columns={"Ticker symbol": "Ticker"})

    if "Industry" not in target.columns:
        target["Industry"] = "Unknown"

    df = target[["Ticker", "Company", "Industry"]].copy()
    df["Sector"] = df["Industry"]
    df["Ticker"] = df["Ticker"].astype(str).map(_normalize_ticker)
    df["Company"] = df["Company"].astype(str).map(_clean_name)
    df["Universe"] = "Dow 30"
    return df.drop_duplicates(subset=["Ticker"]).reset_index(drop=True)


@st.cache_data(ttl=86400, show_spinner=False)
def load_universes() -> pd.DataFrame:
    """All three indices combined. Safe against partial failures."""
    frames = []
    for loader in (get_sp500, get_nasdaq100, get_dow30):
        try:
            frames.append(loader())
        except Exception as e:
            st.warning(f"Could not load {loader.__name__}: {e}")
    if not frames:
        return pd.DataFrame(columns=["Ticker", "Company", "Sector", "Industry", "Universe"])
    combined = pd.concat(frames, ignore_index=True)
    return combined.drop_duplicates(subset=["Ticker", "Universe"]).reset_index(drop=True)


def filter_universe(
    df: pd.DataFrame,
    universes: list[str],
    sectors: list[str] | None = None,
) -> pd.DataFrame:
    """Filter the combined universe by selected indices and optional sectors."""
    pool = df[df["Universe"].isin(universes)].copy()
    if sectors and "All" not in sectors:
        pool = pool[pool["Sector"].isin(sectors)]
    return pool.reset_index(drop=True)


def lookup_ticker(df: pd.DataFrame, ticker: str) -> dict | None:
    """Return the first row matching a ticker (across universes), or None."""
    t = ticker.strip().upper().replace(".", "-")
    match = df[df["Ticker"] == t]
    if match.empty:
        return None
    return match.iloc[0].to_dict()
