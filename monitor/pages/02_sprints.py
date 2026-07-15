"""Sprint history — filterable table, detail view, flow metrics."""
import streamlit as st
import pandas as pd
from lib.api import get_sprints, get_sprint, get_flow_metrics
from lib.charts import token_cost_bar

st.title("Sprint History")

sprints = get_sprints(50)
if isinstance(sprints, dict) and "error" in sprints:
    st.error(f"API error: {sprints['error']}")
    st.stop()

df = pd.DataFrame(sprints)
if df.empty:
    st.info("No sprints yet. Run a sprint to populate.")
    st.stop()

df["issue_title"] = df["picked_issue"].apply(
    lambda x: x.get("title", "")[:60] if isinstance(x, dict) else ""
)

mode_filter = st.selectbox("Mode", ["all", "completed", "needs_revision"])
if mode_filter != "all":
    df = df[df["status"] == mode_filter]

st.dataframe(
    df[["id", "status", "issue_title", "started_at"]].head(20),
    use_container_width=True, hide_index=True,
)

st.divider()
st.subheader("Token Cost Over Time")
st.plotly_chart(token_cost_bar(sprints), use_container_width=True)

st.divider()
selected = st.selectbox("Inspect sprint", df["id"].tolist()[:20])
if selected:
    detail = get_sprint(selected)
    flow = get_flow_metrics(selected)
    s = detail.get("sprint", {})
    envs = detail.get("envelopes", {})

    col1, col2, col3 = st.columns(3)
    col1.metric("Status", s.get("status", "?"))
    col2.metric("Branch", s.get("branch", "")[:20])
    col3.metric("Flow Score", flow.get("flow_score", "?"))
    st.caption(f"Started: {s.get('started_at', '?')}")
    st.text_area("Envelopes", str(envs)[:1000], height=200)
