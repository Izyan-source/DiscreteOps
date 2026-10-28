"""DiscreteOps UI entry point. Run with: streamlit run app.py."""

from pathlib import Path

import streamlit as st

from ui import PAGES, render_sidebar


st.set_page_config(
    page_title="DiscreteOps — A space for discrete thinking",
    page_icon="✳",
    layout="wide",
    initial_sidebar_state="auto",
)

st.html(Path(__file__).parent / "assets" / "styles.css")

# Migrate sessions left open on the previous topic-based navigation.
if st.session_state.get("page") not in PAGES:
    st.session_state.page = "explore"

render_sidebar()

PAGES[st.session_state.page][1]()
