"""
ui/join.py
Landing page: choose Host or Join. Handles team creation inside an existing room.
"""

import streamlit as st

import db


def render():
    st.markdown('<div class="main-title">PMG Analyst Arena</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="subtle">Live stock pitch tournaments with real market scoring.</div>',
        unsafe_allow_html=True,
    )

    tab_join, tab_host = st.tabs(["Join a Game", "Host a Game"])

    with tab_join:
        _render_join_tab()

    with tab_host:
        _render_host_tab()


def _render_join_tab():
    st.subheader("Enter room code")

    with st.form("join_form"):
        col1, col2 = st.columns([1, 2])
        with col1:
            code = st.text_input("Room code", max_chars=6, placeholder="ABC123")
        with col2:
            team_name = st.text_input("Team name", placeholder="e.g., Liquidity Capital")

        join_submitted = st.form_submit_button("Join Game", type="primary", use_container_width=True)

        if join_submitted:
            code_clean = code.strip().upper()
            team_clean = team_name.strip()

            if not code_clean or not team_clean:
                st.error("Room code and team name are both required.")
                return

            comp = db.get_competition_by_code(code_clean)
            if not comp:
                st.error(f"No competition found for code {code_clean}.")
                return

            if comp["status"] == "finished":
                st.error("This competition has already ended.")
                return

            existing = db.get_team_by_name(comp["id"], team_clean)
            if existing:
                # Allow rejoin with same name
                st.session_state.role = "player"
                st.session_state.competition_id = comp["id"]
                st.session_state.team_id = existing["id"]
                st.session_state.team_name = team_clean
                st.success(f"Welcome back, {team_clean}.")
                st.rerun()
                return

            if comp["status"] == "active":
                st.error("This competition has already started. New teams cannot join mid-game.")
                return

            starting = float(comp.get("config", {}).get("starting_capital", 100000.0))
            try:
                team = db.add_team(comp["id"], team_clean, starting)
            except Exception as e:
                st.error(f"Could not create team: {e}")
                return

            st.session_state.role = "player"
            st.session_state.competition_id = comp["id"]
            st.session_state.team_id = team["id"]
            st.session_state.team_name = team_clean
            st.success(f"Joined as {team_clean}. Waiting for host to start.")
            st.rerun()


def _render_host_tab():
    st.subheader("Start a new competition")

    with st.form("host_form"):
        host_name = st.text_input("Your name (host)", placeholder="e.g., Jesus")
        host_submitted = st.form_submit_button("Create Room", type="primary", use_container_width=True)

        if host_submitted:
            if not host_name.strip():
                st.error("Host name is required.")
                return

            # Minimal default config - host can edit in the next screen
            from game import DEFAULT_CONFIG
            config = dict(DEFAULT_CONFIG)

            try:
                comp = db.create_competition(host_name.strip(), config)
            except Exception as e:
                st.error(f"Could not create room: {e}")
                return

            st.session_state.role = "host"
            st.session_state.competition_id = comp["id"]
            st.session_state.room_code = comp["room_code"]
            st.success(f"Room created! Code: {comp['room_code']}")
            st.rerun()
