"""Orgos Monitor — Sprint Dashboard and Control Center."""
import streamlit as st

st.set_page_config(page_title="Orgos Monitor", layout="wide", page_icon="📊")

pages = {
    "Dashboard": [
        st.Page("pages/01_dashboard.py", title="Overview"),
    ],
    "Sprints": [
        st.Page("pages/02_sprints.py", title="History"),
    ],
    "Experiments": [
        st.Page("pages/03_experiments.py", title="Runner"),
    ],
    "Analysis": [
        st.Page("pages/04_comparison.py", title="Comparison"),
        st.Page("pages/05_personas.py", title="Personas"),
    ],
    "Knowledge": [
        st.Page("pages/06_wiki.py", title="Wiki"),
        st.Page("pages/07_board.py", title="Board"),
    ],
}

pg = st.navigation(pages)
pg.run()
