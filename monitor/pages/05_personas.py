"""Persona file browser and editor."""
import streamlit as st
from lib.api import get_personas, get_persona_file, update_persona_file

st.title("Personas")

personas = get_personas()
if isinstance(personas, dict) and "error" in personas:
    st.error(personas["error"])
    st.stop()

agents = [p["agent"] for p in personas]
agent = st.selectbox("Agent", agents)

if agent:
    agent_data = next((p for p in personas if p["agent"] == agent), None)
    if agent_data:
        file_types = [f["name"] for f in agent_data["files"]]
        tabs = st.tabs([ft.upper() for ft in file_types])

        for i, ft in enumerate(file_types):
            with tabs[i]:
                file_data = get_persona_file(agent, ft)
                if "error" in file_data:
                    st.error(file_data["error"])
                    continue

                st.caption(f"Size: {file_data['size']:,} chars")
                content = st.text_area(
                    "Content", file_data["content"], height=400,
                    key=f"{agent}_{ft}"
                )

                col1, col2 = st.columns([1, 4])
                if col1.button("Save", key=f"save_{agent}_{ft}"):
                    result = update_persona_file(agent, ft, content)
                    if "error" in result:
                        st.error(result["error"])
                    else:
                        st.success("Saved!")
