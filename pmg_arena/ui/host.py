"""
ui/host.py
Host dashboard. Handles:
  - Lobby: show room code, waiting teams, configure settings
  - Active: manage rounds (start pitch phase, lock, resolve)
  - Finished: view final leaderboard
"""

from datetime import date, datetime, timedelta, timezone
from typing import Optional

import pandas as pd
import streamlit as st

import db
import game
import yahoo
from formatting import fmt_price, fmt_large, fmt_number, fmt_pct_number


# -----------------------------
# Entry
# -----------------------------
def render():
    comp_id = st.session_state.get("competition_id")
    if not comp_id:
        st.error("No competition context.")
        return

    comp = db.get_competition_by_id(comp_id)
    if not comp:
        st.error("Competition not found.")
        return

    _render_header(comp)

    if comp["status"] == "lobby":
        _render_lobby(comp)
    elif comp["status"] == "active":
        _render_active(comp)
    else:
        _render_finished(comp)


# -----------------------------
# Header
# -----------------------------
def _render_header(comp: dict):
    col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
    with col1:
        st.markdown(f"## Host Dashboard — `{comp['room_code']}`")
        st.caption(f"Status: **{comp['status']}** · Host: {comp['host_name']}")
    with col2:
        teams = db.get_teams(comp["id"])
        st.metric("Teams", len(teams))
    with col3:
        st.metric("Round", comp.get("current_round", 0))
    with col4:
        config = comp.get("config", {}) or {}
        st.metric("Total Rounds", config.get("total_rounds", 3))

    if st.button("🔄 Refresh", key="host_refresh"):
        st.rerun()


# -----------------------------
# Lobby
# -----------------------------
def _render_lobby(comp: dict):
    st.markdown("---")
    st.subheader("1) Configure the game")

    config = dict(comp.get("config") or game.DEFAULT_CONFIG)

    with st.form("config_form"):
        c1, c2 = st.columns(2)

        with c1:
            starting_capital = st.number_input(
                "Starting capital per team ($)",
                min_value=1000, max_value=10_000_000,
                value=int(config.get("starting_capital", 100000)),
                step=1000,
            )
            total_rounds = st.number_input(
                "Total rounds",
                min_value=1, max_value=10,
                value=int(config.get("total_rounds", 3)),
            )
            pitch_seconds = st.select_slider(
                "Pitch time per round (seconds)",
                options=[60, 90, 120, 180, 240, 300],
                value=int(config.get("pitch_seconds", 180)),
            )
            allow_short = st.checkbox(
                "Allow short positions",
                value=bool(config.get("allow_short", True)),
            )
            max_conviction = st.selectbox(
                "Max conviction multiplier",
                options=[1, 2, 3, 5],
                index=[1, 2, 3, 5].index(int(config.get("max_conviction", 3))),
            )

        with c2:
            universes = st.multiselect(
                "Stock universes",
                options=["S&P 500", "Nasdaq-100", "Dow 30"],
                default=config.get("universes", ["S&P 500", "Nasdaq-100"]),
            )
            time_mode = st.selectbox(
                "Time mode",
                options=["live_compressed", "historical_replay", "simulated_walk"],
                index=["live_compressed", "historical_replay", "simulated_walk"].index(
                    config.get("time_mode", "live_compressed")
                ),
                help=(
                    "live_compressed: real market prices, short real-time hold. "
                    "historical_replay: re-run a past period at accelerated speed. "
                    "simulated_walk: synthetic returns from stock's own vol/drift."
                ),
            )

            compressed_hold_minutes = st.slider(
                "(live_compressed) Hold minutes per round",
                min_value=1, max_value=60,
                value=int(config.get("compressed_hold_minutes", 15)),
            )
            replay_hold_days = st.slider(
                "(replay / simulated) Trading days per round",
                min_value=1, max_value=30,
                value=int(config.get("replay_hold_days", 5)),
            )

            default_replay = config.get("replay_start_date") or (date.today() - timedelta(days=180)).isoformat()
            replay_start_date = st.date_input(
                "(historical_replay) Start date",
                value=date.fromisoformat(default_replay),
            )

            judges_enabled = st.checkbox(
                "Enable judge pitch-quality scoring",
                value=bool(config.get("judges_enabled", False)),
            )
            research_mode = st.selectbox(
                "Research mode for players",
                options=["lightweight", "full"],
                index=["lightweight", "full"].index(config.get("research_mode", "lightweight")),
            )

        saved = st.form_submit_button("Save settings", type="primary")

        if saved:
            new_config = {
                "starting_capital": float(starting_capital),
                "total_rounds": int(total_rounds),
                "pitch_seconds": int(pitch_seconds),
                "universes": universes,
                "sectors": config.get("sectors", ["All"]),
                "time_mode": time_mode,
                "compressed_hold_minutes": int(compressed_hold_minutes),
                "replay_hold_days": int(replay_hold_days),
                "replay_start_date": replay_start_date.isoformat(),
                "allow_short": bool(allow_short),
                "max_conviction": int(max_conviction),
                "judges_enabled": bool(judges_enabled),
                "research_mode": research_mode,
            }
            db.update_competition(comp["id"], {"config": new_config})
            st.success("Settings saved.")
            st.rerun()

    st.markdown("---")
    st.subheader("2) Waiting Room")

    teams = db.get_teams(comp["id"])
    if not teams:
        st.info(f"Share the room code **{comp['room_code']}** with players. Waiting for teams to join...")
    else:
        team_rows = [
            {"Team": t["team_name"], "Cash": fmt_price(t["cash_remaining"]), "Joined": t["joined_at"][:19]}
            for t in teams
        ]
        st.dataframe(pd.DataFrame(team_rows), use_container_width=True, hide_index=True)

    st.markdown("---")
    st.subheader("3) Start")

    desc = game.mode_description(comp.get("config") or game.DEFAULT_CONFIG)
    st.caption(desc)

    col_a, col_b = st.columns([1, 3])
    with col_a:
        if st.button("🚀 Start Competition", type="primary", disabled=len(teams) < 1):
            db.start_competition(comp["id"])
            _begin_round(comp["id"], 1)
            st.rerun()
    with col_b:
        st.caption(f"Requires at least 1 team. You have {len(teams)}.")


# -----------------------------
# Active
# -----------------------------
def _render_active(comp: dict):
    st.markdown("---")

    config = comp.get("config") or game.DEFAULT_CONFIG
    current_round = db.get_current_round(comp["id"])

    if not current_round:
        st.warning("Competition is active but no round exists. Starting round 1...")
        _begin_round(comp["id"], 1)
        st.rerun()
        return

    st.subheader(f"Round {current_round['round_number']} — phase: `{current_round['phase']}`")

    if current_round["phase"] == "pitch":
        _render_pitch_phase(comp, current_round, config)
    elif current_round["phase"] == "locked":
        _render_locked_phase(comp, current_round, config)
    elif current_round["phase"] == "resolved":
        _render_resolved_phase(comp, current_round, config)

    st.markdown("---")
    _render_overall_standings(comp, config)


def _render_pitch_phase(comp: dict, round_row: dict, config: dict):
    positions = db.get_positions_for_round(round_row["id"])
    teams = db.get_teams(comp["id"])
    submitted_team_ids = {p["team_id"] for p in positions}

    col1, col2 = st.columns(2)
    col1.metric("Teams submitted", f"{len(submitted_team_ids)} / {len(teams)}")
    deadline = round_row.get("pitch_deadline")
    if deadline:
        col2.caption(f"Pitch deadline: {deadline}")

    if positions:
        rows = []
        team_lookup = {t["id"]: t["team_name"] for t in teams}
        for p in positions:
            rows.append({
                "Team": team_lookup.get(p["team_id"], "?"),
                "Ticker": p["ticker"],
                "Direction": p["direction"],
                "Conviction": f"{p['conviction']}x",
                "% Cash": f"{p['pct_of_cash']:.1f}%",
                "Notional": fmt_price(p["notional_allocated"]),
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("No pitches submitted yet.")

    st.markdown("### Advance the round")
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        if st.button("🔒 Lock pitches", type="primary"):
            _lock_round(round_row)
            st.rerun()
    with col_b:
        if st.button("⏭️ Skip to resolve (lock + resolve in one)"):
            _lock_round(round_row)
            _resolve_round(comp, round_row, config)
            st.rerun()
    with col_c:
        st.caption("Lock freezes submissions and captures entry prices.")


def _render_locked_phase(comp: dict, round_row: dict, config: dict):
    positions = db.get_positions_for_round(round_row["id"])
    teams = db.get_teams(comp["id"])

    st.info("Pitches locked. Entry prices captured. Run resolution when the hold window ends.")

    df = _positions_to_dataframe(positions, teams)
    st.dataframe(df, use_container_width=True, hide_index=True)

    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("💥 Resolve round now", type="primary"):
            _resolve_round(comp, round_row, config)
            st.rerun()
    with col_b:
        mode = config.get("time_mode", "live_compressed")
        if mode == "live_compressed":
            st.caption(f"Wait ~{config.get('compressed_hold_minutes', 15)} real minutes, then resolve.")
        elif mode == "historical_replay":
            st.caption("Resolution uses the end date from the replay window.")
        else:
            st.caption("Simulated walk — resolution is instant.")


def _render_resolved_phase(comp: dict, round_row: dict, config: dict):
    positions = db.get_positions_for_round(round_row["id"])
    teams = db.get_teams(comp["id"])

    st.subheader("Round results")
    standings = game.compute_round_standings(teams, positions)
    if not standings.empty:
        display_df = standings.copy()
        for col in ("Notional", "EntryPrice", "ExitPrice", "PnL"):
            if col in display_df.columns:
                display_df[col] = display_df[col].apply(fmt_price)
        if "ReturnPct" in display_df.columns:
            display_df["ReturnPct"] = display_df["ReturnPct"].apply(fmt_pct_number)
        st.dataframe(display_df, use_container_width=True, hide_index=True)
    else:
        st.info("No positions to show.")

    config_total_rounds = int(config.get("total_rounds", 3))
    current_n = int(round_row["round_number"])

    col_a, col_b = st.columns(2)
    with col_a:
        if current_n < config_total_rounds:
            if st.button("▶️ Start next round", type="primary"):
                _begin_round(comp["id"], current_n + 1)
                st.rerun()
        else:
            if st.button("🏁 End competition", type="primary"):
                db.finish_competition(comp["id"])
                st.rerun()
    with col_b:
        st.caption(f"Round {current_n} of {config_total_rounds}")


# -----------------------------
# Finished
# -----------------------------
def _render_finished(comp: dict):
    st.markdown("---")
    st.subheader("🏆 Final Leaderboard")

    config = comp.get("config") or game.DEFAULT_CONFIG
    teams = db.get_teams(comp["id"])
    positions = db.get_all_positions(comp["id"])
    judges = db.get_judge_scores_for_competition(comp["id"]) if config.get("judges_enabled") else []

    standings = game.compute_team_standings(
        teams, positions,
        judge_scores=judges,
        judges_enabled=bool(config.get("judges_enabled")),
    )

    if standings.empty:
        st.info("No standings available.")
        return

    display = standings.drop(columns=["TeamId"], errors="ignore").copy()
    for col in ("StartingCapital", "TotalPnL", "PortfolioValue"):
        if col in display.columns:
            display[col] = display[col].apply(fmt_price)
    if "ReturnPct" in display.columns:
        display["ReturnPct"] = display["ReturnPct"].apply(fmt_pct_number)

    st.dataframe(display, use_container_width=True, hide_index=True)

    # Export
    csv = standings.to_csv(index=False).encode("utf-8")
    st.download_button(
        "📥 Download full results (CSV)",
        data=csv, file_name=f"pmg_arena_{comp['room_code']}_results.csv", mime="text/csv",
    )

    st.markdown("---")
    st.subheader("All positions")
    pos_df = _positions_to_dataframe(positions, teams)
    st.dataframe(pos_df, use_container_width=True, hide_index=True)


# -----------------------------
# Internal actions
# -----------------------------
def _begin_round(competition_id: str, round_number: int):
    comp = db.get_competition_by_id(competition_id)
    config = comp.get("config") or game.DEFAULT_CONFIG

    pitch_seconds = int(config.get("pitch_seconds", 180))
    deadline = (datetime.now(timezone.utc) + timedelta(seconds=pitch_seconds)).isoformat()

    hold_start, hold_end = None, None
    if config.get("time_mode") == "historical_replay":
        start_iso = config.get("replay_start_date") or date.today().isoformat()
        days = int(config.get("replay_hold_days", 5))
        hold_start, hold_end = game.compute_replay_dates(start_iso, round_number, days)

    db.create_round(
        competition_id=competition_id,
        round_number=round_number,
        pitch_deadline=deadline,
        hold_start=hold_start,
        hold_end=hold_end,
    )
    db.update_competition(competition_id, {"current_round": round_number})


def _lock_round(round_row: dict):
    """Lock phase: freeze submissions and populate entry prices."""
    from datetime import datetime, timezone
    positions = db.get_positions_for_round(round_row["id"])

    comp = db.get_competition_by_id(round_row["competition_id"])
    config = comp.get("config") or game.DEFAULT_CONFIG
    mode = config.get("time_mode", "live_compressed")

    for p in positions:
        if p.get("entry_price"):
            continue  # already set

        entry_price = None
        if mode == "live_compressed":
            entry_price = yahoo.get_current_price(p["ticker"])
        elif mode == "historical_replay" and round_row.get("hold_start_price_date"):
            try:
                d = date.fromisoformat(round_row["hold_start_price_date"])
                entry_price = yahoo.get_price_on_date(p["ticker"], d)
            except Exception:
                entry_price = None
        elif mode == "simulated_walk":
            # Use current live price as anchor for the simulated path
            entry_price = yahoo.get_current_price(p["ticker"])

        if entry_price is not None:
            db.set_position_entry_price(p["id"], float(entry_price))

    db.update_round_phase(round_row["id"], "locked")


def _resolve_round(comp: dict, round_row: dict, config: dict):
    # Fetch once — positions already have entry_price set by _lock_round
    positions = db.get_positions_for_round(round_row["id"])
    teams = db.get_teams(comp["id"])
    team_lookup = {t["id"]: t for t in teams}
    mode = config.get("time_mode", "live_compressed")

    cash_updates: dict[str, float] = {}

    for p in positions:
        if p.get("exit_price") is not None:
            continue  # already resolved

        updates = game.resolve_position_live(
            p,
            mode=mode,
            replay_end_date=round_row.get("hold_end_price_date"),
            simulated_seed=int(round_row["round_number"]) * 1000 + hash(p["ticker"]) % 1000,
            simulated_days=int(config.get("replay_hold_days", 5)),
        )
        if not updates:
            continue

        db.resolve_position(p["id"], updates["exit_price"], updates["return_pct"], updates["pnl_dollars"])

        # Accumulate cash updates so we only write once per team
        team_id = p["team_id"]
        cash_updates[team_id] = cash_updates.get(team_id, 0.0) + float(updates["pnl_dollars"])

    # Apply team cash updates in a single pass
    for team_id, pnl_delta in cash_updates.items():
        team = team_lookup.get(team_id)
        if team:
            new_cash = float(team["cash_remaining"]) + pnl_delta
            db.update_team_cash(team_id, new_cash)

    db.update_round_phase(round_row["id"], "resolved", {"resolution_time": datetime.now(timezone.utc).isoformat()})


def _render_overall_standings(comp: dict, config: dict):
    st.subheader("Overall Standings")
    teams = db.get_teams(comp["id"])
    positions = db.get_all_positions(comp["id"])
    judges = db.get_judge_scores_for_competition(comp["id"]) if config.get("judges_enabled") else []

    standings = game.compute_team_standings(
        teams, positions,
        judge_scores=judges,
        judges_enabled=bool(config.get("judges_enabled")),
    )
    if standings.empty:
        st.info("No scores yet.")
        return

    display = standings.drop(columns=["TeamId"], errors="ignore").copy()
    for col in ("StartingCapital", "TotalPnL", "PortfolioValue"):
        if col in display.columns:
            display[col] = display[col].apply(fmt_price)
    if "ReturnPct" in display.columns:
        display["ReturnPct"] = display["ReturnPct"].apply(fmt_pct_number)

    st.dataframe(display, use_container_width=True, hide_index=True)


def _positions_to_dataframe(positions: list[dict], teams: list[dict]) -> pd.DataFrame:
    team_lookup = {t["id"]: t["team_name"] for t in teams}
    rows = []
    for p in positions:
        rows.append({
            "Team": team_lookup.get(p["team_id"], "?"),
            "Ticker": p["ticker"],
            "Direction": p["direction"],
            "Conv": f"{p['conviction']}x",
            "Notional": fmt_price(p.get("notional_allocated")),
            "Entry": fmt_price(p.get("entry_price")),
            "Exit": fmt_price(p.get("exit_price")),
            "Return": fmt_pct_number(p.get("return_pct")),
            "P&L": fmt_price(p.get("pnl_dollars")),
        })
    return pd.DataFrame(rows)
