"""
db.py
All Supabase read/write ops live here. Single source of truth for data access.
Other modules should NEVER hit the Supabase client directly.
"""

import os
import random
import string
from datetime import datetime, timezone
from typing import Any, Optional

import streamlit as st
from supabase import Client, create_client

# -----------------------------
# Client
# -----------------------------
@st.cache_resource(show_spinner=False)
def get_client() -> Client:
    url = os.environ.get("SUPABASE_URL") or st.secrets.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_ANON_KEY") or st.secrets.get("SUPABASE_ANON_KEY")
    if not url or not key:
        raise RuntimeError(
            "Missing SUPABASE_URL or SUPABASE_ANON_KEY. "
            "Set them in .streamlit/secrets.toml or environment variables."
        )
    return create_client(url, key)


# -----------------------------
# Helpers
# -----------------------------
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_room_code() -> str:
    # 6-char alphanumeric, avoiding easily-confused characters
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(random.choices(alphabet, k=6))


# -----------------------------
# Competitions
# -----------------------------
def create_competition(host_name: str, config: dict) -> dict:
    client = get_client()

    # Retry room-code generation up to 5 times to avoid collisions
    for _ in range(5):
        code = generate_room_code()
        existing = client.table("competitions").select("id").eq("room_code", code).execute()
        if not existing.data:
            break
    else:
        raise RuntimeError("Could not generate unique room code after 5 tries.")

    payload = {
        "room_code": code,
        "host_name": host_name,
        "status": "lobby",
        "config": config,
        "current_round": 0,
    }
    result = client.table("competitions").insert(payload).execute()
    return result.data[0]


def get_competition_by_code(room_code: str) -> Optional[dict]:
    client = get_client()
    result = (
        client.table("competitions")
        .select("*")
        .eq("room_code", room_code.upper().strip())
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def get_competition_by_id(competition_id: str) -> Optional[dict]:
    client = get_client()
    result = (
        client.table("competitions")
        .select("*")
        .eq("id", competition_id)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def update_competition(competition_id: str, updates: dict) -> dict:
    client = get_client()
    result = (
        client.table("competitions")
        .update(updates)
        .eq("id", competition_id)
        .execute()
    )
    return result.data[0] if result.data else {}


def start_competition(competition_id: str) -> dict:
    return update_competition(
        competition_id,
        {"status": "active", "started_at": _now()},
    )


def finish_competition(competition_id: str) -> dict:
    return update_competition(
        competition_id,
        {"status": "finished", "finished_at": _now()},
    )


# -----------------------------
# Teams
# -----------------------------
def add_team(competition_id: str, team_name: str, starting_capital: float = 100000.0) -> dict:
    client = get_client()
    payload = {
        "competition_id": competition_id,
        "team_name": team_name.strip(),
        "starting_capital": starting_capital,
        "cash_remaining": starting_capital,
    }
    result = client.table("teams").insert(payload).execute()
    return result.data[0]


def get_teams(competition_id: str) -> list[dict]:
    client = get_client()
    result = (
        client.table("teams")
        .select("*")
        .eq("competition_id", competition_id)
        .order("joined_at")
        .execute()
    )
    return result.data or []


def get_team_by_name(competition_id: str, team_name: str) -> Optional[dict]:
    client = get_client()
    result = (
        client.table("teams")
        .select("*")
        .eq("competition_id", competition_id)
        .eq("team_name", team_name.strip())
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def update_team_cash(team_id: str, new_cash: float) -> dict:
    client = get_client()
    result = (
        client.table("teams")
        .update({"cash_remaining": new_cash})
        .eq("id", team_id)
        .execute()
    )
    return result.data[0] if result.data else {}


# -----------------------------
# Rounds
# -----------------------------
def create_round(
    competition_id: str,
    round_number: int,
    pitch_deadline: Optional[str] = None,
    hold_start: Optional[str] = None,
    hold_end: Optional[str] = None,
) -> dict:
    client = get_client()
    payload = {
        "competition_id": competition_id,
        "round_number": round_number,
        "phase": "pitch",
        "pitch_deadline": pitch_deadline,
        "hold_start_price_date": hold_start,
        "hold_end_price_date": hold_end,
    }
    result = client.table("rounds").insert(payload).execute()
    return result.data[0]


def get_rounds(competition_id: str) -> list[dict]:
    client = get_client()
    result = (
        client.table("rounds")
        .select("*")
        .eq("competition_id", competition_id)
        .order("round_number")
        .execute()
    )
    return result.data or []


def get_current_round(competition_id: str) -> Optional[dict]:
    rounds = get_rounds(competition_id)
    if not rounds:
        return None
    # Return the highest round_number (most recent)
    return max(rounds, key=lambda r: r["round_number"])


def update_round_phase(round_id: str, phase: str, extra: Optional[dict] = None) -> dict:
    client = get_client()
    updates: dict[str, Any] = {"phase": phase}
    if extra:
        updates.update(extra)
    result = client.table("rounds").update(updates).eq("id", round_id).execute()
    return result.data[0] if result.data else {}


# -----------------------------
# Positions (pitches)
# -----------------------------
def submit_position(payload: dict) -> dict:
    client = get_client()
    # Upsert so a team can edit their pitch during the pitch phase
    result = (
        client.table("positions")
        .upsert(payload, on_conflict="round_id,team_id")
        .execute()
    )
    return result.data[0] if result.data else {}


def get_positions_for_round(round_id: str) -> list[dict]:
    client = get_client()
    result = (
        client.table("positions")
        .select("*")
        .eq("round_id", round_id)
        .execute()
    )
    return result.data or []


def get_positions_for_team(team_id: str) -> list[dict]:
    client = get_client()
    result = (
        client.table("positions")
        .select("*")
        .eq("team_id", team_id)
        .order("submitted_at")
        .execute()
    )
    return result.data or []


def get_all_positions(competition_id: str) -> list[dict]:
    client = get_client()
    result = (
        client.table("positions")
        .select("*")
        .eq("competition_id", competition_id)
        .order("submitted_at")
        .execute()
    )
    return result.data or []


def set_position_entry_price(position_id: str, entry_price: float) -> dict:
    """Set entry_price on a position (used when locking a round)."""
    client = get_client()
    result = (
        client.table("positions")
        .update({"entry_price": float(entry_price)})
        .eq("id", position_id)
        .execute()
    )
    return result.data[0] if result.data else {}


def resolve_position(position_id: str, exit_price: float, return_pct: float, pnl_dollars: float) -> dict:
    client = get_client()
    result = (
        client.table("positions")
        .update({
            "exit_price": exit_price,
            "return_pct": return_pct,
            "pnl_dollars": pnl_dollars,
            "resolved_at": _now(),
        })
        .eq("id", position_id)
        .execute()
    )
    return result.data[0] if result.data else {}


# -----------------------------
# Judge scores
# -----------------------------
def submit_judge_score(payload: dict) -> dict:
    client = get_client()
    result = client.table("judge_scores").insert(payload).execute()
    return result.data[0] if result.data else {}


def get_judge_scores_for_competition(competition_id: str) -> list[dict]:
    client = get_client()
    result = (
        client.table("judge_scores")
        .select("*")
        .eq("competition_id", competition_id)
        .execute()
    )
    return result.data or []


# -----------------------------
# Price cache
# -----------------------------
def get_cached_price(ticker: str, price_date: str) -> Optional[dict]:
    client = get_client()
    result = (
        client.table("price_cache")
        .select("*")
        .eq("ticker", ticker)
        .eq("price_date", price_date)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def upsert_price_cache(rows: list[dict]) -> None:
    if not rows:
        return
    client = get_client()
    client.table("price_cache").upsert(rows, on_conflict="ticker,price_date").execute()
