"""Comparison — token cost per mode, paired benchmarks."""
import streamlit as st
import pandas as pd
from lib.api import get_costs, run_paired_benchmark
from lib.charts import mode_comparison_bar

st.title("Comparison")

st.subheader("Token Cost by Mode")
st.plotly_chart(mode_comparison_bar(), use_container_width=True)

st.divider()

st.subheader("Sprint Mode Distribution")
costs = get_costs()
if isinstance(costs, list) and costs:
    df = pd.DataFrame(costs)
    if "mode" in df.columns:
        st.dataframe(
            df.groupby("mode").agg(
                sprints=("sprint_id", "count"),
                completed=("status", lambda x: (x == "completed").sum()),
            ).reset_index(),
            use_container_width=True, hide_index=True,
        )
else:
    st.info("No cost data yet.")

st.divider()
st.subheader("Paired Benchmark")

col1, col2 = st.columns(2)
issue_id = col1.text_input("Issue ID", "42")
issue_title = col2.text_input("Issue Title", "Test comparison")
agents_b = st.text_input("Alternative agents/ dir", "agents_alt")

if st.button("Run Paired Benchmark"):
    with st.spinner("Running dual-team comparison..."):
        result = run_paired_benchmark(issue_id, issue_title, agents_b)
    if "error" in result:
        st.error(result["error"])
    else:
        winner = result.get("winner", "tie")
        score_delta = result.get("score_delta", 0)
        flow_delta = result.get("flow_delta", 0)
        st.success(f"Winner: **{winner}** | Rubric delta: {score_delta:+.3f} | Flow delta: {flow_delta:+.3f}")

        cola, colb = st.columns(2)
        with cola:
            st.metric("Team A", f"Rubric: {result['team_a']['rubric_score']} | Flow: {result['team_a']['flow_score']:.2f}")
        with colb:
            st.metric("Team B", f"Rubric: {result['team_b']['rubric_score']} | Flow: {result['team_b']['flow_score']:.2f}")
