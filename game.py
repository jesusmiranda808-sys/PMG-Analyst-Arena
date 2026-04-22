"""
game.py
Core game logic: portfolio math, round resolution, ranking.
This module is deliberately pure logic — no DB calls, no Streamlit.
Callers pass in data, get back computed results.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

import pandas as pd

import yahoo

# Default config values. Host can override via competition config.
DEFAULT_CONFIG = {
    "starting_capital": 100000.0,
    "total_rounds": 3,
    "pitch_seconds": 180,
    "universes": ["S&P 500", "Nasdaq-100"],
    "sectors": ["All"],
    "time_mode": "live_compressed",   # historical_replay | simulated_walk | live_compressed
    "compressed_hold_minutes": 15,    # for live_compressed: how long each hold lasts in real time
    "replay_hold_days": 5,            # for historical_replay: trading days per round
    "replay_start_date": None,        # ISO date string; host picks
    "allow_short": True,
    "max_conviction": 3,              # 1x | 2x | 3x
    "judges_enabled": False,
    "research_mode": "lightweight",   # lightweight | full
}


# -----------------------------
# Portfolio math
# -----------------------------
@dataclass
class PositionResult:
    position_id: str
    team_id: str
    ticker: str
    direction: str
    conviction: int
    notional_allocated: float
    entry_price: float
    exit_price: float
    return_pct: float     # price return on the stock (unsigned for direction)
    pnl_dollars: float    # signed dollar P&L including direction and conviction


def compute_pnl(
    entry_price: float,
    exit_price: float,
    notional: float,
    direction: str,
    conviction: int,
) -> tuple[float, float]:
    """
    Returns (signed_return_pct, pnl_dollars).

    signed_return_pct is the effective return on the allocated notional after
    applying direction and conviction (i.e., the % of allocated cash gained/lost).
    """
    if entry_price in (None, 0) or exit_price is None:
        return 0.0, 0.0

    raw_pct = (exit_price - entry_price) / entry_price
    direction_sign = 1 if direction == "long" else -1
    effective_pct = raw_pct * direction_sign * conviction
    pnl = notional * effective_pct
    return effective_pct * 100, pnl


def allocate_notional(cash_remaining: float, pct_of_cash: float) -> float:
    """Convert 'pct of remaining cash' into dollar notional."""
    pct = max(0.0, min(100.0, float(pct_of_cash))) / 100.0
    return round(cash_remaining * pct, 2)


# -----------------------------
# Round resolution
# -----------------------------
def resolve_position_live(
    position: dict,
    mode: str,
    replay_end_date: Optional[str] = None,
    simulated_seed: Optional[int] = None,
    simulated_days: int = 5,
) -> Optional[dict]:
    """
    Given a position dict + time mode, figure out the exit price and compute P&L.
    Returns a dict of updates to persist, or None if the position can't be resolved yet.
    """
    ticker = position["ticker"]
    entry_price = position.get("entry_price")
    direction = position["direction"]
    conviction = int(position.get("conviction") or 1)
    notional = float(position.get("notional_allocated") or 0.0)

    if entry_price is None:
        return None

    exit_price = None

    if mode == "live_compressed":
        exit_price = yahoo.get_current_price(ticker)

    elif mode == "historical_replay":
        if replay_end_date:
            try:
                end_d = date.fromisoformat(replay_end_date)
                exit_price = yahoo.get_price_on_date(ticker, end_d)
            except Exception:
                exit_price = None

    elif mode == "simulated_walk":
        sim_return_pct = yahoo.simulate_walk_return(
            ticker, days=simulated_days, seed=simulated_seed
        )
        if sim_return_pct is not None:
            exit_price = entry_price * (1 + sim_return_pct / 100.0)

    if exit_price is None:
        return None

    return_pct, pnl = compute_pnl(
        entry_price=float(entry_price),
        exit_price=float(exit_price),
        notional=notional,
        direction=direction,
        conviction=conviction,
    )

    return {
        "exit_price": float(exit_price),
        "return_pct": float(return_pct),
        "pnl_dollars": float(pnl),
    }


# -----------------------------
# Leaderboard
# -----------------------------
def compute_team_standings(
    teams: list[dict],
    positions: list[dict],
    judge_scores: list[dict] | None = None,
    judges_enabled: bool = False,
) -> pd.DataFrame:
    """
    Roll up all positions per team into a leaderboard.

    Columns:
      Team, StartingCapital, TotalPnL, PortfolioValue, ReturnPct, JudgeScore, FinalRank
    """
    rows = []
    team_lookup = {t["id"]: t for t in teams}

    for team in teams:
        team_positions = [p for p in positions if p["team_id"] == team["id"]]
        total_pnl = sum((p.get("pnl_dollars") or 0) for p in team_positions if p.get("pnl_dollars") is not None)
        starting = float(team["starting_capital"])
        port_value = starting + total_pnl
        return_pct = (total_pnl / starting) * 100 if starting > 0 else 0.0

        judge_total = 0
        if judges_enabled and judge_scores:
            team_position_ids = {p["id"] for p in team_positions}
            judge_total = sum(
                (js.get("total") or 0)
                for js in judge_scores
                if js.get("position_id") in team_position_ids
            )

        rows.append({
            "TeamId": team["id"],
            "Team": team["team_name"],
            "Positions": len(team_positions),
            "StartingCapital": starting,
            "TotalPnL": round(total_pnl, 2),
            "PortfolioValue": round(port_value, 2),
            "ReturnPct": round(return_pct, 3),
            "JudgeScore": judge_total,
        })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df = df.sort_values(by="ReturnPct", ascending=False).reset_index(drop=True)
    df.insert(0, "Rank", df.index + 1)
    return df


def compute_round_standings(
    teams: list[dict],
    positions_in_round: list[dict],
) -> pd.DataFrame:
    """Per-round leaderboard showing just this round's P&L."""
    team_lookup = {t["id"]: t["team_name"] for t in teams}
    rows = []
    for p in positions_in_round:
        rows.append({
            "Team": team_lookup.get(p["team_id"], "Unknown"),
            "Ticker": p["ticker"],
            "Direction": p["direction"],
            "Conviction": p["conviction"],
            "Notional": p.get("notional_allocated"),
            "EntryPrice": p.get("entry_price"),
            "ExitPrice": p.get("exit_price"),
            "ReturnPct": p.get("return_pct"),
            "PnL": p.get("pnl_dollars"),
        })
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    if "PnL" in df.columns:
        df = df.sort_values(by="PnL", ascending=False, na_position="last").reset_index(drop=True)
        df.insert(0, "Rank", df.index + 1)
    return df


# -----------------------------
# Time-mode helpers
# -----------------------------
def compute_replay_dates(start_date_iso: str, round_number: int, days_per_round: int) -> tuple[str, str]:
    """
    For historical replay mode, given the competition's start date and round number,
    return the (hold_start, hold_end) ISO date strings for that round.
    """
    start = date.fromisoformat(start_date_iso)
    round_start = start + timedelta(days=(round_number - 1) * days_per_round)
    round_end = round_start + timedelta(days=days_per_round)
    return round_start.isoformat(), round_end.isoformat()


def mode_description(config: dict) -> str:
    mode = config.get("time_mode", "live_compressed")
    if mode == "live_compressed":
        mins = config.get("compressed_hold_minutes", 15)
        return f"Live market, each position held for {mins} real minutes."
    if mode == "historical_replay":
        start = config.get("replay_start_date", "unset")
        days = config.get("replay_hold_days", 5)
        return f"Historical replay starting {start}, {days} trading days per round."
    if mode == "simulated_walk":
        days = config.get("replay_hold_days", 5)
        return f"Simulated price walk, {days}-trading-day synthetic horizon per round."
    return "Unknown mode."
