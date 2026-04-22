"""
ui/player.py
Player view:
  - Waiting room (pre-start)
  - Active round: research, pick ticker, submit pitch
  - Locked: watch leaderboard
  - Finished: see final results
"""

from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import streamlit as st

import db
import game
import yahoo
import universe as uni
from formatting import fmt_price, fmt_large, fmt_number, fmt_pct_decimal, fmt_pct_number


def render():
    comp_id = st.session_state.get("competition_id")
    team_id = st.session_state.get("team_id")
    team_name = st.session_state.get("team_name", "Unknown")

    if not comp_id or not team_id:
        st.error("Missing competition context. Please rejoin.")
        return

    comp = db.get_competition_by_id(comp_id)
    if not comp:
        st.error("Competition no longer exists.")
        return

    teams = db.get_teams(comp_id)
    team = next((t for t in teams if t["id"] == team_id), None)
    if not team:
        st.error("Your team was removed from this competition.")
        return

    _render_header(comp, team)

    if comp["status"] == "lobby":
        _render_waiting_room(comp, teams)
        return

    if comp["status"] == "finished":
        _render_final_view(comp, team, teams)
        return

    # Active
    current_round = db.get_current_round(comp_id)
    if not current_round:
        st.info("Waiting for host to start the first round...")
        _refresh_button()
        return

    phase = current_round["phase"]

    if phase == "pitch":
        _render_pitch_phase(comp, current_round, team)
    elif phase == "locked":
        _render_locked_phase(comp, current_round, team, teams)
    elif phase == "resolved":
        _render_resolved_phase(comp, current_round, team, teams)


# -----------------------------
# Header
# -----------------------------
def _render_header(comp: dict, team: dict):
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        st.markdown(f"## Team: {team['team_name']}")
        st.caption(f"Room `{comp['room_code']}` · Status: **{comp['status']}**")
    with col2:
        st.metric("Cash remaining", fmt_price(team["cash_remaining"]))
    with col3:
        config = comp.get("config") or {}
        st.metric("Round", f"{comp.get('current_round', 0)} / {config.get('total_rounds', 3)}")

    _refresh_button()


def _refresh_button():
    comp_id = st.session_state.get("competition_id", "none")
    if st.button("🔄 Refresh", key=f"player_refresh_{comp_id}"):
        st.rerun()


# -----------------------------
# Waiting room
# -----------------------------
def _render_waiting_room(comp: dict, teams: list[dict]):
    st.markdown("---")
    st.subheader("Waiting for host to start...")
    st.caption(game.mode_description(comp.get("config") or game.DEFAULT_CONFIG))

    rows = [{"Team": t["team_name"], "Cash": fmt_price(t["cash_remaining"])} for t in teams]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# -----------------------------
# Pitch phase
# -----------------------------
def _render_pitch_phase(comp: dict, round_row: dict, team: dict):
    st.markdown("---")
    st.subheader(f"Round {round_row['round_number']} — Submit your pitch")

    # Deadline countdown (client-side, non-blocking)
    deadline_iso = round_row.get("pitch_deadline")
    if deadline_iso:
        _render_countdown(deadline_iso)

    config = comp.get("config") or game.DEFAULT_CONFIG
    allow_short = bool(config.get("allow_short", True))
    max_conv = int(config.get("max_conviction", 3))
    research_mode = config.get("research_mode", "lightweight")

    # Did we already submit for this round?
    existing = db.get_positions_for_round(round_row["id"])
    my_position = next((p for p in existing if p["team_id"] == team["id"]), None)

    if my_position:
        st.success(f"Pitch submitted: {my_position['direction'].upper()} {my_position['ticker']} "
                   f"at {my_position['conviction']}x, {my_position['pct_of_cash']:.1f}% of cash. "
                   f"You can edit below until the host locks the round.")

    # Effective cash can't go below zero for new allocations
    effective_cash = max(0.0, float(team["cash_remaining"]))
    if effective_cash <= 0:
        st.error(
            "Your cash balance is depleted. You cannot open new positions. "
            "Wait for remaining rounds to resolve — existing positions can still recover."
        )
        return

    # Ticker picker
    try:
        universe_df = uni.load_universes()
    except Exception as e:
        st.error(f"Could not load universe: {e}")
        return

    pool = uni.filter_universe(universe_df, config.get("universes", ["S&P 500"]), config.get("sectors", ["All"]))
    if pool.empty:
        st.error("No tickers match the competition's universe/sector filters.")
        return

    ticker_options = pool["Ticker"].tolist()
    default_ticker = my_position["ticker"] if my_position else ticker_options[0]

    ticker_selected = st.selectbox(
        "Pick a ticker",
        options=ticker_options,
        index=ticker_options.index(default_ticker) if default_ticker in ticker_options else 0,
        help="Start typing to filter. You can change your pick until the host locks the round.",
    )

    ticker_row = uni.lookup_ticker(pool, ticker_selected) or {}
    _render_research_panel(ticker_selected, ticker_row, research_mode)

    st.markdown("### Size your position")

    with st.form("pitch_form"):
        c1, c2, c3 = st.columns(3)
        with c1:
            direction_options = ["long", "short"] if allow_short else ["long"]
            default_dir = my_position["direction"] if my_position else "long"
            direction = st.radio(
                "Direction",
                options=direction_options,
                index=direction_options.index(default_dir) if default_dir in direction_options else 0,
                horizontal=True,
            )
        with c2:
            conviction_options = list(range(1, max_conv + 1))
            default_conv = int(my_position["conviction"]) if my_position else 1
            conviction = st.selectbox(
                "Conviction multiplier",
                options=conviction_options,
                index=conviction_options.index(default_conv) if default_conv in conviction_options else 0,
                format_func=lambda x: f"{x}x",
                help="Higher conviction amplifies both gains AND losses.",
            )
        with c3:
            default_pct = float(my_position["pct_of_cash"]) if my_position else 25.0
            pct_of_cash = st.slider(
                "% of remaining cash",
                min_value=1.0, max_value=100.0,
                value=default_pct, step=1.0,
            )

        st.markdown("### Pitch details")
        default_what = my_position.get("what_it_does") if my_position else ""
        default_thesis = my_position.get("thesis") if my_position else ""
        default_metric = my_position.get("metric") if my_position else ""
        default_catalyst = my_position.get("catalyst") if my_position else ""

        what_it_does = st.text_area("What does the company do? (1 sentence)", value=default_what or "", height=70)
        thesis = st.text_area("Investment thesis — why is the market wrong?", value=default_thesis or "", height=100)
        col_m, col_c = st.columns(2)
        with col_m:
            metric = st.text_input("One supporting metric", value=default_metric or "")
        with col_c:
            catalyst = st.text_input("One catalyst", value=default_catalyst or "")

        # Live preview
        notional = game.allocate_notional(effective_cash, float(pct_of_cash))
        st.caption(f"**Allocation:** {fmt_price(notional)} (before conviction). "
                   f"At {conviction}x {direction}, gains/losses are amplified accordingly.")

        submit_clicked = st.form_submit_button("Submit Pitch", type="primary")

        if submit_clicked:
            payload = {
                "competition_id": comp["id"],
                "round_id": round_row["id"],
                "team_id": team["id"],
                "ticker": ticker_selected,
                "company": ticker_row.get("Company"),
                "sector": ticker_row.get("Sector"),
                "direction": direction,
                "conviction": int(conviction),
                "pct_of_cash": float(pct_of_cash),
                "notional_allocated": notional,
                "thesis": thesis,
                "what_it_does": what_it_does,
                "metric": metric,
                "catalyst": catalyst,
            }
            try:
                db.submit_position(payload)
                st.success("Pitch submitted.")
                st.rerun()
            except Exception as e:
                st.error(f"Could not submit pitch: {e}")


def _render_research_panel(ticker: str, ticker_row: dict, mode: str):
    st.markdown(f"### {ticker_row.get('Company', ticker)} ({ticker})")
    st.caption(f"Sector: {ticker_row.get('Sector', 'Unknown')} · Universe: {ticker_row.get('Universe', 'Unknown')}")

    snap = yahoo.get_snapshot(ticker)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Price", fmt_price(snap["price"]))
    c2.metric("Daily %", fmt_pct_number(snap["change_pct"]))
    c3.metric("Market Cap", fmt_large(snap["market_cap"]))
    c4.metric("Trailing P/E", fmt_number(snap["trailing_pe"]))

    if mode == "full":
        d1, d2, d3, d4 = st.columns(4)
        d1.metric("Forward P/E", fmt_number(snap["forward_pe"]))
        d2.metric("Beta", fmt_number(snap["beta"]))
        d3.metric("Rev Growth", fmt_pct_decimal(snap["revenue_growth"]))
        d4.metric("Op Margin", fmt_pct_decimal(snap["operating_margins"]))

        with st.expander("Business summary"):
            st.write(snap["summary"] or "No summary available.")

    # 6-month chart (lightweight + full both show this)
    hist = yahoo.get_history(ticker, period="6mo", interval="1d")
    if hist is not None and not hist.empty and "Close" in hist.columns:
        st.line_chart(hist["Close"], height=180)


def _render_countdown(deadline_iso: str):
    """Client-side JS countdown. Non-blocking (unlike the old time.sleep loop)."""
    try:
        deadline = datetime.fromisoformat(deadline_iso.replace("Z", "+00:00"))
    except Exception:
        return

    now = datetime.now(timezone.utc)
    remaining = int((deadline - now).total_seconds())

    if remaining <= 0:
        st.warning("⏰ Pitch deadline passed. Host may lock the round any moment.")
        return

    # Inject JS countdown
    st.markdown(
        f"""
        <div style="padding:0.5rem;border:1px solid #ddd;border-radius:12px;background:#fafafa;text-align:center;">
            <span style="font-size:0.85rem;color:#666;">Pitch deadline</span><br/>
            <span id="countdown-timer" style="font-size:1.6rem;font-weight:700;">--:--</span>
        </div>
        <script>
            (function() {{
                const end = new Date("{deadline_iso}").getTime();
                const el = document.getElementById("countdown-timer");
                if (!el) return;
                function tick() {{
                    const now = Date.now();
                    let diff = Math.max(0, Math.floor((end - now) / 1000));
                    const m = Math.floor(diff / 60);
                    const s = diff % 60;
                    el.textContent = m + ":" + (s < 10 ? "0" + s : s);
                    if (diff > 0) setTimeout(tick, 1000);
                }}
                tick();
            }})();
        </script>
        """,
        unsafe_allow_html=True,
    )


# -----------------------------
# Locked phase
# -----------------------------
def _render_locked_phase(comp: dict, round_row: dict, team: dict, teams: list[dict]):
    st.markdown("---")
    st.subheader(f"Round {round_row['round_number']} — Locked")
    st.info("Pitches are frozen. Waiting for host to resolve the round.")

    positions = db.get_positions_for_round(round_row["id"])
    my_pos = next((p for p in positions if p["team_id"] == team["id"]), None)
    if my_pos:
        st.markdown(
            f"**Your position:** {my_pos['direction'].upper()} **{my_pos['ticker']}** "
            f"at {my_pos['conviction']}x — entry {fmt_price(my_pos.get('entry_price'))} · "
            f"notional {fmt_price(my_pos.get('notional_allocated'))}"
        )
    else:
        st.warning("You did not submit a pitch this round.")


# -----------------------------
# Resolved phase
# -----------------------------
def _render_resolved_phase(comp: dict, round_row: dict, team: dict, teams: list[dict]):
    st.markdown("---")
    st.subheader(f"Round {round_row['round_number']} — Resolved")

    positions = db.get_positions_for_round(round_row["id"])
    my_pos = next((p for p in positions if p["team_id"] == team["id"]), None)
    if my_pos and my_pos.get("exit_price") is not None:
        pnl = my_pos.get("pnl_dollars", 0) or 0
        color = "green" if pnl >= 0 else "red"
        st.markdown(
            f"<div style='padding:1rem;border-radius:12px;border:2px solid {color};'>"
            f"<h3 style='color:{color};margin:0;'>{'+' if pnl >= 0 else ''}{fmt_price(pnl)}</h3>"
            f"<span>{my_pos['direction'].upper()} {my_pos['ticker']} · "
            f"Entry {fmt_price(my_pos.get('entry_price'))} → Exit {fmt_price(my_pos.get('exit_price'))} · "
            f"Return {fmt_pct_number(my_pos.get('return_pct'))}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

    st.markdown("### Round standings")
    round_board = game.compute_round_standings(teams, positions)
    if not round_board.empty:
        display = round_board.copy()
        for col in ("Notional", "EntryPrice", "ExitPrice", "PnL"):
            if col in display.columns:
                display[col] = display[col].apply(fmt_price)
        if "ReturnPct" in display.columns:
            display["ReturnPct"] = display["ReturnPct"].apply(fmt_pct_number)
        st.dataframe(display, use_container_width=True, hide_index=True)

    st.markdown("### Overall standings")
    _render_overall_standings(comp, teams)

    st.info("Waiting for host to start the next round...")


def _render_overall_standings(comp: dict, teams: list[dict]):
    config = comp.get("config") or game.DEFAULT_CONFIG
    positions = db.get_all_positions(comp["id"])
    judges = db.get_judge_scores_for_competition(comp["id"]) if config.get("judges_enabled") else []
    standings = game.compute_team_standings(
        teams, positions,
        judge_scores=judges,
        judges_enabled=bool(config.get("judges_enabled")),
    )
    if standings.empty:
        st.caption("No standings yet.")
        return
    display = standings.drop(columns=["TeamId"], errors="ignore").copy()
    for col in ("StartingCapital", "TotalPnL", "PortfolioValue"):
        if col in display.columns:
            display[col] = display[col].apply(fmt_price)
    if "ReturnPct" in display.columns:
        display["ReturnPct"] = display["ReturnPct"].apply(fmt_pct_number)
    st.dataframe(display, use_container_width=True, hide_index=True)


# -----------------------------
# Final
# -----------------------------
def _render_final_view(comp: dict, team: dict, teams: list[dict]):
    st.markdown("---")
    st.subheader("🏁 Competition complete")
    _render_overall_standings(comp, teams)

    st.markdown("### Your positions")
    my_positions = db.get_positions_for_team(team["id"])
    if not my_positions:
        st.info("No positions recorded.")
        return

    rows = []
    for p in my_positions:
        rows.append({
            "Ticker": p["ticker"],
            "Direction": p["direction"],
            "Conv": f"{p['conviction']}x",
            "Notional": fmt_price(p.get("notional_allocated")),
            "Entry": fmt_price(p.get("entry_price")),
            "Exit": fmt_price(p.get("exit_price")),
            "Return": fmt_pct_number(p.get("return_pct")),
            "P&L": fmt_price(p.get("pnl_dollars")),
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
