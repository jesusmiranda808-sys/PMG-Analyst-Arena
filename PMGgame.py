import random
import time
from typing import List, Optional

import pandas as pd
import requests
import streamlit as st
import yfinance as yf

# -----------------------------
# Page config
# -----------------------------
st.set_page_config(
    page_title="PMG Analyst Arena",
    page_icon="📈",
    layout="wide"
)

# -----------------------------
# Styling
# -----------------------------
st.markdown(
    """
    <style>
    .main-title {
        font-size: 2.3rem;
        font-weight: 800;
        margin-bottom: 0.25rem;
    }
    .subtle {
        color: #666;
        font-size: 0.95rem;
        margin-bottom: 1rem;
    }
    .card {
        padding: 1rem 1.2rem;
        border: 1px solid #ddd;
        border-radius: 14px;
        background: #fafafa;
        margin-bottom: 1rem;
    }
    .metric-box {
        padding: 0.8rem 1rem;
        border-radius: 12px;
        border: 1px solid #ddd;
        background: #ffffff;
        text-align: center;
    }
    .small-note {
        font-size: 0.85rem;
        color: #666;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# -----------------------------
# Constants
# -----------------------------
SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
NASDAQ100_URL = "https://en.wikipedia.org/wiki/Nasdaq-100"
DOW30_URL = "https://en.wikipedia.org/wiki/Dow_Jones_Industrial_Average"

DEFAULT_USER_AGENT = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
}

# -----------------------------
# Session state init
# -----------------------------
if "teams" not in st.session_state:
    st.session_state.teams = {}

if "round_number" not in st.session_state:
    st.session_state.round_number = 1

if "current_stock" not in st.session_state:
    st.session_state.current_stock = None

if "current_universe" not in st.session_state:
    st.session_state.current_universe = None

if "pitch_submissions" not in st.session_state:
    st.session_state.pitch_submissions = {}

if "score_log" not in st.session_state:
    st.session_state.score_log = []

if "timer_seconds" not in st.session_state:
    st.session_state.timer_seconds = 180


# -----------------------------
# Utility functions
# -----------------------------
def normalize_ticker(ticker: str) -> str:
    if not isinstance(ticker, str):
        return ticker
    return ticker.replace(".", "-").strip().upper()


def clean_company_name(name: str) -> str:
    return str(name).strip()


def safe_float(value):
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_tables_from_url(url: str):
    resp = requests.get(url, headers=DEFAULT_USER_AGENT, timeout=20)
    resp.raise_for_status()
    return pd.read_html(resp.text)


@st.cache_data(ttl=3600, show_spinner=False)
def get_sp500_constituents() -> pd.DataFrame:
    tables = fetch_tables_from_url(SP500_URL)
    df = tables[0].copy()

    df = df.rename(
        columns={
            "Symbol": "Ticker",
            "Security": "Company",
            "GICS Sector": "Sector",
            "GICS Sub-Industry": "Industry"
        }
    )

    df = df[["Ticker", "Company", "Sector", "Industry"]].copy()
    df["Ticker"] = df["Ticker"].astype(str).apply(normalize_ticker)
    df["Company"] = df["Company"].astype(str).apply(clean_company_name)
    df["Universe"] = "S&P 500"
    return df.drop_duplicates(subset=["Ticker"]).reset_index(drop=True)


@st.cache_data(ttl=3600, show_spinner=False)
def get_nasdaq100_constituents() -> pd.DataFrame:
    tables = fetch_tables_from_url(NASDAQ100_URL)

    target = None
    for t in tables:
        cols = [str(c).strip() for c in t.columns]
        if "Ticker" in cols and "Company" in cols:
            target = t.copy()
            break

    if target is None:
        raise ValueError("Could not find Nasdaq-100 constituent table.")

    target = target.rename(
        columns={
            "ICB Industry": "Sector",
            "ICB Subsector": "Industry",
            "Industry": "Sector",
            "Subsector": "Industry"
        }
    )

    if "Sector" not in target.columns:
        target["Sector"] = "Unknown"
    if "Industry" not in target.columns:
        target["Industry"] = "Unknown"

    df = target[["Ticker", "Company", "Sector", "Industry"]].copy()
    df["Ticker"] = df["Ticker"].astype(str).apply(normalize_ticker)
    df["Company"] = df["Company"].astype(str).apply(clean_company_name)
    df["Universe"] = "Nasdaq-100"
    return df.drop_duplicates(subset=["Ticker"]).reset_index(drop=True)


@st.cache_data(ttl=3600, show_spinner=False)
def get_dow30_constituents() -> pd.DataFrame:
    tables = fetch_tables_from_url(DOW30_URL)

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
    df["Ticker"] = df["Ticker"].astype(str).apply(normalize_ticker)
    df["Company"] = df["Company"].astype(str).apply(clean_company_name)
    df["Universe"] = "Dow 30"
    return df.drop_duplicates(subset=["Ticker"]).reset_index(drop=True)


@st.cache_data(ttl=3600, show_spinner=False)
def load_universes() -> pd.DataFrame:
    sp = get_sp500_constituents()
    ndx = get_nasdaq100_constituents()
    dow = get_dow30_constituents()
    combined = pd.concat([sp, ndx, dow], ignore_index=True)
    return combined.drop_duplicates(subset=["Ticker", "Universe"]).reset_index(drop=True)


def format_large_number(value) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    try:
        value = float(value)
        if abs(value) >= 1_000_000_000_000:
            return f"${value / 1_000_000_000_000:.2f}T"
        if abs(value) >= 1_000_000_000:
            return f"${value / 1_000_000_000:.2f}B"
        if abs(value) >= 1_000_000:
            return f"${value / 1_000_000:.2f}M"
        return f"${value:,.0f}"
    except Exception:
        return "N/A"


def format_percent_decimal(value) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    try:
        return f"{float(value) * 100:.2f}%"
    except Exception:
        return "N/A"


def format_percent_number(value) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    try:
        return f"{float(value):.2f}%"
    except Exception:
        return "N/A"


def format_price(value) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    try:
        return f"${float(value):,.2f}"
    except Exception:
        return "N/A"


def format_number(value) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    try:
        return f"{float(value):,.2f}"
    except Exception:
        return "N/A"


def choose_random_stock(
    df: pd.DataFrame,
    universes: List[str],
    sectors: Optional[List[str]] = None,
    exclude_recent: Optional[List[str]] = None
) -> Optional[dict]:
    pool = df[df["Universe"].isin(universes)].copy()

    if sectors and "All" not in sectors:
        pool = pool[pool["Sector"].isin(sectors)]

    if exclude_recent:
        pool = pool[~pool["Ticker"].isin(exclude_recent)]

    if pool.empty:
        return None

    row = pool.sample(1, random_state=random.randint(1, 10_000_000)).iloc[0]
    return row.to_dict()


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_market_caps_for_tickers(tickers: tuple) -> dict:
    """
    Safer batch-ish market cap fetcher.
    Uses fast_info only, and silently skips broken tickers.
    """
    market_caps = {}

    for ticker in tickers:
        try:
            tk = yf.Ticker(ticker)
            fi = tk.fast_info
            mc = fi.get("marketCap")
            market_caps[ticker] = safe_float(mc)
        except Exception:
            market_caps[ticker] = None

    return market_caps


@st.cache_data(ttl=900, show_spinner=False)
def get_stock_snapshot(stock_row: dict) -> dict:
    """
    Robust Yahoo wrapper:
    - avoids tk.info for core logic because it's flaky / auth-prone
    - uses price history for price + change
    - tries fast_info for extra fields
    - returns safe None values instead of crashing
    """
    ticker = stock_row["Ticker"]

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

    try:
        tk = yf.Ticker(ticker)

        # History is usually the least cursed source for price data
        hist = tk.history(period="6mo", interval="1d", auto_adjust=False)

        if hist is not None and not hist.empty:
            hist = hist.dropna(subset=["Close"], how="all")

            if not hist.empty:
                last_close = safe_float(hist["Close"].iloc[-1])
                price = last_close

                if len(hist) >= 2:
                    prev_close = safe_float(hist["Close"].iloc[-2])
                    if prev_close not in (None, 0):
                        change_pct = ((last_close - prev_close) / prev_close) * 100 if last_close is not None else None

                if "Volume" in hist.columns:
                    last_vol = hist["Volume"].dropna()
                    if not last_vol.empty:
                        volume = safe_float(last_vol.iloc[-1])

                    vol_30 = hist["Volume"].dropna().tail(30)
                    if not vol_30.empty:
                        avg_volume = safe_float(vol_30.mean())

        # Fast info for extras; may fail, so keep it isolated
        try:
            fi = tk.fast_info
            market_cap = safe_float(fi.get("marketCap"))
            if price is None:
                price = safe_float(fi.get("lastPrice"))
            if volume is None:
                volume = safe_float(fi.get("lastVolume"))
        except Exception:
            pass

        # Optional metadata block: do not trust, do not require
        # This may still fail for some tickers. That's fine.
        try:
            info = tk.get_info()
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
        return {
            "Ticker": ticker,
            "Company": stock_row.get("Company", "Unknown"),
            "Universe": stock_row.get("Universe", "Unknown"),
            "Sector": stock_row.get("Sector", "Unknown"),
            "Industry": stock_row.get("Industry", "Unknown"),
            "Price": None,
            "ChangePct": None,
            "MarketCap": None,
            "TrailingPE": None,
            "ForwardPE": None,
            "Volume": None,
            "AvgVolume": None,
            "Beta": None,
            "RevenueGrowth": None,
            "OperatingMargins": None,
            "Summary": "",
            "Error": str(e)
        }

    return {
        "Ticker": ticker,
        "Company": stock_row.get("Company", "Unknown"),
        "Universe": stock_row.get("Universe", "Unknown"),
        "Sector": stock_row.get("Sector", "Unknown"),
        "Industry": stock_row.get("Industry", "Unknown"),
        "Price": price,
        "ChangePct": change_pct,
        "MarketCap": market_cap,
        "TrailingPE": trailing_pe,
        "ForwardPE": forward_pe,
        "Volume": volume,
        "AvgVolume": avg_volume,
        "Beta": beta,
        "RevenueGrowth": revenue_growth,
        "OperatingMargins": operating_margins,
        "Summary": summary,
        "Error": None
    }


def reset_round_state():
    st.session_state.current_stock = None
    st.session_state.current_universe = None


# -----------------------------
# Header
# -----------------------------
st.markdown('<div class="main-title">PMG Analyst Arena</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="subtle">Gamified stock pitch battle with live universe auto-pull.</div>',
    unsafe_allow_html=True
)

# -----------------------------
# Load universes
# -----------------------------
try:
    universe_df = load_universes()
except Exception as e:
    st.error(f"Failed to load index constituents: {e}")
    st.stop()

sector_options = ["All"] + sorted(
    [s for s in universe_df["Sector"].dropna().unique().tolist() if str(s).strip()]
)

# -----------------------------
# Sidebar controls
# -----------------------------
with st.sidebar:
    st.header("Game Controls")

    st.markdown("### Round Setup")
    selected_universes = st.multiselect(
        "Choose stock universe(s)",
        options=["S&P 500", "Nasdaq-100", "Dow 30"],
        default=["S&P 500", "Nasdaq-100"]
    )

    selected_sectors = st.multiselect(
        "Optional sector filter",
        options=sector_options,
        default=["All"]
    )

    difficulty = st.selectbox(
        "Difficulty mode",
        options=["Normal", "No Mega Caps", "Chaos Mode"],
        index=0
    )

    timer_choice = st.selectbox(
        "Pitch timer",
        options=[60, 90, 120, 180, 300],
        format_func=lambda x: f"{x} seconds"
    )
    st.session_state.timer_seconds = timer_choice

    st.markdown("---")
    st.markdown("### Team Setup")
    new_team = st.text_input("Add team name")

    if st.button("Add Team", use_container_width=True):
        name = new_team.strip()
        if not name:
            st.warning("Enter a team name.")
        elif name in st.session_state.teams:
            st.warning("Team already exists.")
        else:
            st.session_state.teams[name] = {"score": 0}
            st.success(f"Added team: {name}")

    if st.button("Reset Current Round", use_container_width=True):
        reset_round_state()
        st.success("Current round cleared.")

    if st.button("Start Next Round", use_container_width=True):
        st.session_state.round_number += 1
        reset_round_state()
        st.success(f"Moved to round {st.session_state.round_number}.")

# -----------------------------
# Difficulty filter helper
# -----------------------------
filtered_df = universe_df.copy()

if difficulty == "No Mega Caps":
    mega_cap_cutoff = 200_000_000_000

    try:
        sampled_tickers = tuple(filtered_df["Ticker"].dropna().unique().tolist()[:250])
        mc_map = fetch_market_caps_for_tickers(sampled_tickers)

        mega_caps = {
            ticker for ticker, mc in mc_map.items()
            if mc is not None and mc >= mega_cap_cutoff
        }

        if mega_caps:
            filtered_df = filtered_df[~filtered_df["Ticker"].isin(mega_caps)]
    except Exception:
        pass

elif difficulty == "Chaos Mode":
    try:
        # Light chaos: random sample of the available universe each run
        tickers = filtered_df["Ticker"].dropna().unique().tolist()
        if len(tickers) > 60:
            chosen = set(random.sample(tickers, 60))
            filtered_df = filtered_df[filtered_df["Ticker"].isin(chosen)]
    except Exception:
        pass

# -----------------------------
# Top stats
# -----------------------------
c1, c2, c3 = st.columns(3)
with c1:
    st.markdown(
        f'<div class="metric-box"><h3>{len(st.session_state.teams)}</h3><div>Teams</div></div>',
        unsafe_allow_html=True
    )
with c2:
    st.markdown(
        f'<div class="metric-box"><h3>{st.session_state.round_number}</h3><div>Current Round</div></div>',
        unsafe_allow_html=True
    )
with c3:
    unique_tickers = filtered_df["Ticker"].nunique()
    st.markdown(
        f'<div class="metric-box"><h3>{unique_tickers}</h3><div>Available Tickers</div></div>',
        unsafe_allow_html=True
    )

st.markdown("---")

# -----------------------------
# Main layout
# -----------------------------
left, right = st.columns([1.2, 1])

with left:
    st.subheader("1) Generate a Stock")

    if not selected_universes:
        st.warning("Pick at least one universe in the sidebar.")
    else:
        recent_tickers = []
        if st.session_state.score_log:
            recent_tickers = [x["Ticker"] for x in st.session_state.score_log[-10:] if "Ticker" in x]

        if st.button("Generate Random Stock", type="primary"):
            picked = choose_random_stock(
                df=filtered_df,
                universes=selected_universes,
                sectors=selected_sectors,
                exclude_recent=recent_tickers
            )

            if picked is None:
                st.error("No stocks matched the selected filters.")
            else:
                stock_snapshot = get_stock_snapshot(picked)
                st.session_state.current_stock = stock_snapshot
                st.session_state.current_universe = picked.get("Universe")

                if stock_snapshot.get("Error"):
                    st.warning(
                        f"Loaded {picked.get('Ticker')} with partial data only. "
                        f"Yahoo glitched: {stock_snapshot['Error']}"
                    )

    if st.session_state.current_stock:
        stock = st.session_state.current_stock
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown(
            f"## {stock['Company']} ({stock['Ticker']})\n"
            f"**Universe:** {stock['Universe']}  \n"
            f"**Sector:** {stock['Sector']}  \n"
            f"**Industry:** {stock['Industry']}"
        )

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Price", format_price(stock["Price"]))
        m2.metric("Daily %", format_percent_number(stock["ChangePct"]))
        m3.metric("Market Cap", format_large_number(stock["MarketCap"]))
        m4.metric("Trailing P/E", format_number(stock["TrailingPE"]))

        n1, n2, n3, n4 = st.columns(4)
        n1.metric("Forward P/E", format_number(stock["ForwardPE"]))
        n2.metric("Beta", format_number(stock["Beta"]))
        n3.metric("Revenue Growth", format_percent_decimal(stock["RevenueGrowth"]))
        n4.metric("Op Margin", format_percent_decimal(stock["OperatingMargins"]))

        extra1, extra2 = st.columns(2)
        extra1.metric("Volume", format_large_number(stock["Volume"]))
        extra2.metric("Avg Volume", format_large_number(stock["AvgVolume"]))

        with st.expander("Company summary / quick context"):
            summary_text = stock.get("Summary") or "No business summary available."
            st.write(summary_text)

        st.markdown(
            '<div class="small-note">Use the data as clues, not gospel. The game is about building a coherent thesis under uncertainty.</div>',
            unsafe_allow_html=True
        )
        st.markdown("</div>", unsafe_allow_html=True)
    else:
        st.info("No stock selected yet. Generate one to begin.")

    st.subheader("2) Pitch Timer")
    seconds = st.session_state.timer_seconds
    mins = seconds // 60
    secs = seconds % 60
    st.write(f"Suggested pitch time: **{mins}:{secs:02d}**")

    timer_placeholder = st.empty()
    timer_col1, timer_col2 = st.columns(2)

    if timer_col1.button("Run Countdown"):
        for remaining in range(seconds, -1, -1):
            mm = remaining // 60
            ss = remaining % 60
            timer_placeholder.markdown(f"## ⏳ {mm}:{ss:02d}")
            time.sleep(1)
        timer_placeholder.markdown("## ⏰ Time's up.")

    if timer_col2.button("Clear Countdown"):
        timer_placeholder.empty()

with right:
    st.subheader("3) Team Pitch Card")

    if not st.session_state.teams:
        st.info("Add at least one team in the sidebar.")
    else:
        team_names = list(st.session_state.teams.keys())
        selected_team = st.selectbox("Team", options=team_names)

        with st.form("pitch_form"):
            what_it_does = st.text_area("What does the company do?", height=80)
            thesis = st.text_area("Investment thesis", height=110, help="Why is the market wrong?")
            metric = st.text_input("One supporting metric")
            catalyst = st.text_input("One catalyst")
            direction = st.selectbox("Call", options=["Long / Bullish", "Short / Bearish", "Neutral / Watchlist"])
            submitted = st.form_submit_button("Save Pitch Card")

            if submitted:
                st.session_state.pitch_submissions[selected_team] = {
                    "WhatItDoes": what_it_does,
                    "Thesis": thesis,
                    "Metric": metric,
                    "Catalyst": catalyst,
                    "Direction": direction,
                    "Round": st.session_state.round_number,
                    "Ticker": st.session_state.current_stock["Ticker"] if st.session_state.current_stock else None,
                    "Company": st.session_state.current_stock["Company"] if st.session_state.current_stock else None,
                }
                st.success(f"Saved pitch for {selected_team}")

    st.subheader("4) Judge Scoring")

    if st.session_state.teams:
        judge_team = st.selectbox("Score team", options=list(st.session_state.teams.keys()), key="judge_team")

        clarity = st.slider("Clarity", 1, 5, 3)
        logic = st.slider("Logic", 1, 5, 3)
        metric_use = st.slider("Use of Metric", 1, 5, 3)
        catalyst_strength = st.slider("Catalyst Strength", 1, 5, 3)
        confidence = st.slider("Presentation Confidence", 1, 5, 3)

        if st.button("Submit Score"):
            total = clarity + logic + metric_use + catalyst_strength + confidence
            st.session_state.teams[judge_team]["score"] += total

            log_entry = {
                "Round": st.session_state.round_number,
                "Team": judge_team,
                "ScoreAdded": total,
                "Ticker": st.session_state.current_stock["Ticker"] if st.session_state.current_stock else None,
                "Company": st.session_state.current_stock["Company"] if st.session_state.current_stock else None,
                "Universe": st.session_state.current_stock["Universe"] if st.session_state.current_stock else None,
                "Clarity": clarity,
                "Logic": logic,
                "MetricUse": metric_use,
                "CatalystStrength": catalyst_strength,
                "Confidence": confidence,
            }
            st.session_state.score_log.append(log_entry)
            st.success(f"{judge_team} received {total} points.")

st.markdown("---")
st.subheader("Leaderboard")

if st.session_state.teams:
    leaderboard = pd.DataFrame(
        [{"Team": team, "Score": data["score"]} for team, data in st.session_state.teams.items()]
    ).sort_values(by="Score", ascending=False).reset_index(drop=True)

    leaderboard.index = leaderboard.index + 1
    st.dataframe(leaderboard, use_container_width=True)
else:
    st.write("No teams yet.")

st.subheader("Saved Pitch Cards")

if st.session_state.pitch_submissions:
    for team, pitch in st.session_state.pitch_submissions.items():
        with st.expander(f"{team} | Round {pitch.get('Round', 'N/A')} | {pitch.get('Company', 'No Company')}"):
            st.write(f"**Ticker:** {pitch.get('Ticker', 'N/A')}")
            st.write(f"**Call:** {pitch.get('Direction', 'N/A')}")
            st.write(f"**What they do:** {pitch.get('WhatItDoes', '')}")
            st.write(f"**Thesis:** {pitch.get('Thesis', '')}")
            st.write(f"**Metric:** {pitch.get('Metric', '')}")
            st.write(f"**Catalyst:** {pitch.get('Catalyst', '')}")
else:
    st.write("No saved pitch cards yet.")

st.subheader("Round History")

if st.session_state.score_log:
    score_df = pd.DataFrame(st.session_state.score_log)
    st.dataframe(score_df, use_container_width=True)

    csv_bytes = score_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download Score Log CSV",
        data=csv_bytes,
        file_name="pmg_analyst_arena_score_log.csv",
        mime="text/csv"
    )
else:
    st.write("No scores submitted yet.")

st.markdown("---")
st.caption(
    "Constituent lists are pulled from public index pages, while market data uses yfinance with defensive fallbacks."
)