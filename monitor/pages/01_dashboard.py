"""Dashboard — live sprint overview, DORA, flow metrics."""
import streamlit as st
from lib.api import get_dora, get_sprints, get_heuristics
from lib.charts import sprint_streak_dots, flow_score_gauge

st.title("Orgos Monitor")

cola, colb, colc = st.columns(3)

with cola:
    dora = get_dora()
    tier = dora.get("latest", {}).get("tier", "—")
    st.metric("DORA Tier", tier)

with colb:
    sprints = get_sprints(14)
    completed = sum(1 for s in sprints if s.get("status") == "completed")
    st.metric("Completed (14 sprints)", f"{completed}/14")

with colc:
    heur = get_heuristics()
    active = len(heur.get("active", []))
    st.metric("Active Heuristics", active)

st.divider()

col1, col2 = st.columns([2, 1])

with col1:
    st.subheader("Sprint Streak")
    if isinstance(sprints, list) and sprints:
        st.plotly_chart(sprint_streak_dots(sprints), use_container_width=True)
    else:
        st.caption("No sprint data yet.")

with col2:
    st.subheader("Flow Score")
    st.plotly_chart(flow_score_gauge(0.65), use_container_width=True)

st.divider()

st.subheader("Recent Sprints")
if isinstance(sprints, list):
    for s in sprints[:5]:
        emoji = "✅" if s.get("status") == "completed" else "⚠️" if s.get("status") == "needs_revision" else "❌"
        issue = s.get("picked_issue", {})
        title = issue.get("title", "?") if isinstance(issue, dict) else str(issue)[:60]
        st.caption(f"{emoji} `{s['id'][:12]}` {title}")
else:
    st.info("No sprint data available. Run a sprint to populate.")
