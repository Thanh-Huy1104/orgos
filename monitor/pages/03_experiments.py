"""Experiment runner — configure and launch long-form experiments."""
import streamlit as st
import time
from lib.api import run_experiment, get_experiments, get_experiment
from lib.charts import experiment_progress

st.title("Experiment Runner")

st.subheader("Configure")

col1, col2, col3, col4 = st.columns(4)
sprints_n = col1.number_input("Sprints", 1, 20, 5)
model = col2.selectbox("Model", ["deepseek/deepseek-chat", "deepseek/deepseek-reasoner"])
budget = col3.selectbox("Budget", [100000, 200000, 300000, 400000], index=2)
mode = col4.selectbox("Mode", ["pull"])

if st.button("Launch Experiment", type="primary"):
    result = run_experiment(sprints_n, model, budget, mode)
    if "error" in result:
        st.error(result["error"])
    else:
        st.success(f"Experiment started: {sprints_n} sprints, {model}")
        st.caption("Results will appear as experiment_*.json files. Refresh to view.")

st.divider()
st.subheader("Past Experiments")

exps = get_experiments()
if isinstance(exps, dict) and "error" in exps:
    st.error(exps["error"])
elif exps:
    for exp in exps:
        summary = exp.get("summary", {})
        config = exp.get("config", {})
        completed = summary.get("completed", "?")
        total = config.get("num_sprints", "?")
        tokens = summary.get("total_tokens", 0)
        st.markdown(f"**{exp['id']}** — {completed}/{total} completed, {tokens:,} tokens")

    selected = st.selectbox("View details", [e["id"] for e in exps])
    if selected:
        detail = get_experiment(selected)
        results = detail.get("results", [])
        if results:
            st.plotly_chart(experiment_progress(results), use_container_width=True)
            for r in results:
                emoji = "✅" if r.get("status") == "completed" else "❌"
                st.caption(f"{emoji} {r.get('issue', '?')[:50]} | {r.get('tokens', 0):,} tokens")
else:
    st.info("No past experiments found.")
