"""DiscreteOps UI entry point. Run with: streamlit run app.py."""

from pathlib import Path

import streamlit as st

from ui import PAGES, render_sidebar


st.set_page_config(
    page_title="DiscreteOps — From problem to solution",
    page_icon="✳",
    layout="wide",
    initial_sidebar_state="auto",
)

st.html(Path(__file__).parent / "assets" / "styles.css")

# New sessions start with a real-world problem; existing page selections survive.
if st.session_state.get("page") not in PAGES:
    st.session_state.page = "studio"

render_sidebar()

PAGES[st.session_state.page][1]()
