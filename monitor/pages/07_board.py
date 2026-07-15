"""Board view — READY gate, column flow, story cards."""
import streamlit as st
from lib.api import get_board_status, get_sprints

st.title("Board")

status = get_board_status()
if isinstance(status, dict) and "error" in status:
    st.error(status["error"])
else:
    cols = st.columns(len(status.get("columns", [])))
    for i, column in enumerate(status.get("columns", [])):
        with cols[i]:
            st.markdown(f"**{column.upper()}**")
            st.caption("—")

st.divider()
st.subheader("READY Gate Rules")

cola, colb, colc = st.columns(3)
cola.metric("Max Files", 5)
colb.metric("Max LOC", 400)
colc.metric("Required Signoffs", 3)

st.caption("Roles: architect, test, devsecops must all sign off before a story enters READY.")

st.divider()
st.subheader("Recent Sprints on Board")

sprints = get_sprints(20)
if isinstance(sprints, list):
    for s in sprints[:10]:
        envs_data = s.get("envelopes_json", "{}")
        import json
        envs = json.loads(envs_data) if isinstance(envs_data, str) else envs_data
        roles = [k for k in envs.keys() if k != "_replay"]
        st.caption(f"`{s['id'][:12]}` [{s.get('status','?')}] roles: {', '.join(roles[:4])}")
