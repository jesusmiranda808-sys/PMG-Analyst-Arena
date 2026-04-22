"""
app.py
Streamlit entry point. Routes between join/host/player views based on session state.

Run locally:
    streamlit run app.py

Required env vars or .streamlit/secrets.toml:
    SUPABASE_URL
    SUPABASE_ANON_KEY
"""

import streamlit as st

from ui import join as ui_join
from ui import host as ui_host
from ui import player as ui_player


# -----------------------------
# Page config
# -----------------------------
st.set_page_config(
    page_title="PMG Analyst Arena",
    page_icon="📈",
    layout="wide",
)

# -----------------------------
# Base styling
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
    </style>
    """,
    unsafe_allow_html=True,
)

# -----------------------------
# Session state defaults
# -----------------------------
for k, v in {
    "role": None,            # None | "host" | "player"
    "competition_id": None,
    "team_id": None,
    "team_name": None,
    "room_code": None,
}.items():
    if k not in st.session_state:
        st.session_state[k] = v


# -----------------------------
# Sidebar: identity + exit
# -----------------------------
with st.sidebar:
    st.markdown("### Session")
    role = st.session_state.get("role")
    if role == "host":
        st.write(f"**Role:** Host")
        st.write(f"**Room:** `{st.session_state.get('room_code', '?')}`")
    elif role == "player":
        st.write(f"**Role:** Player")
        st.write(f"**Team:** {st.session_state.get('team_name', '?')}")
    else:
        st.write("Not in a room yet.")

    if role is not None:
        if st.button("Leave room", use_container_width=True):
            for k in ("role", "competition_id", "team_id", "team_name", "room_code"):
                st.session_state[k] = None
            st.rerun()

    st.markdown("---")
    st.caption(
        "Data: constituent lists from public index pages, prices via yfinance. "
        "Game state persisted in Supabase."
    )


# -----------------------------
# Router
# -----------------------------
role = st.session_state.get("role")

try:
    if role == "host":
        ui_host.render()
    elif role == "player":
        ui_player.render()
    else:
        ui_join.render()
except RuntimeError as e:
    st.error(str(e))
    st.info(
        "Set your Supabase credentials in `.streamlit/secrets.toml`:\n\n"
        "```\nSUPABASE_URL = \"https://your-project.supabase.co\"\n"
        "SUPABASE_ANON_KEY = \"your-anon-key\"\n```"
    )
