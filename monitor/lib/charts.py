"""Reusable chart components for the monitor."""

from __future__ import annotations

import json
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd


def sprint_streak_dots(sprints: list[dict]) -> go.Figure:
    data = []
    for s in sprints[:14]:
        color = (
            "#22c55e" if s.get("status") == "completed"
            else "#eab308" if s.get("status") == "needs_revision"
            else "#ef4444"
        )
        data.append({"x": s["id"][:12], "color": color, "status": s["status"]})
    df = pd.DataFrame(data)
    fig = px.scatter(df, x="x", y=[1]*len(df), color="color",
                     color_discrete_map="identity",
                     size=[20]*len(df), symbol_sequence=["circle"])
    fig.update_traces(marker=dict(line=dict(width=1, color="white")))
    fig.update_layout(
        showlegend=False, height=60, margin=dict(l=0, r=0, t=0, b=0),
        xaxis=dict(showticklabels=False, showgrid=False, zeroline=False),
        yaxis=dict(showticklabels=False, showgrid=False, zeroline=False),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def token_cost_bar(sprints: list[dict]) -> go.Figure:
    rows = []
    for s in sprints[:20]:
        envs = s.get("envelopes_json", "{}")
        if isinstance(envs, str):
            try:
                envs = json.loads(envs)
            except Exception:
                envs = {}
        rows.append({
            "id": s.get("id", "?")[:12],
            "status": s.get("status", "?"),
            "envelopes": len(envs) if isinstance(envs, dict) else 0,
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return go.Figure()
    fig = px.bar(df, x="id", y="envelopes", color="status",
                 color_discrete_map={
                     "completed": "#22c55e", "needs_revision": "#eab308",
                     "failed": "#ef4444",
                 })
    fig.update_layout(
        height=300, margin=dict(l=0, r=0, t=0, b=0),
        xaxis=dict(tickangle=-45, tickfont=dict(size=10)),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def mode_comparison_bar() -> go.Figure:
    data = [
        {"mode": "Old (hierarchical)", "avg_tokens": 65000, "completion_rate": 0},
        {"mode": "New scrum (hier)", "avg_tokens": 500000, "completion_rate": 0},
        {"mode": "Pull (self-org)", "avg_tokens": 11000, "completion_rate": 100},
    ]
    df = pd.DataFrame(data)
    fig = go.Figure()
    fig.add_trace(go.Bar(name="Avg tokens", x=df["mode"], y=df["avg_tokens"],
                          marker_color="#6366f1", yaxis="y"))
    fig.add_trace(go.Bar(name="Completion %", x=df["mode"], y=df["completion_rate"],
                          marker_color="#22c55e", yaxis="y2"))
    fig.update_layout(
        height=300, margin=dict(l=0, r=0, t=0, b=0),
        yaxis=dict(title="Tokens", side="left"),
        yaxis2=dict(title="%", side="right", overlaying="y", range=[0, 100]),
        barmode="group",
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def flow_score_gauge(score: float) -> go.Figure:
    color = "#22c55e" if score >= 0.7 else "#eab308" if score >= 0.5 else "#ef4444"
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=score,
        number={"suffix": "", "font": {"size": 40}},
        gauge={
            "axis": {"range": [0, 1]},
            "bar": {"color": color},
            "steps": [
                {"range": [0, 0.5], "color": "rgba(239,68,68,0.2)"},
                {"range": [0.5, 0.7], "color": "rgba(234,179,8,0.2)"},
                {"range": [0.7, 1], "color": "rgba(34,197,94,0.2)"},
            ],
            "threshold": {"line": {"color": "white"}, "value": score},
        },
    ))
    fig.update_layout(height=200, margin=dict(l=0, r=0, t=0, b=0),
                      paper_bgcolor="rgba(0,0,0,0)")
    return fig


def experiment_progress(results: list[dict]) -> go.Figure:
    if not results:
        return go.Figure()
    df = pd.DataFrame(results)
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=list(range(len(results))), y=df["tokens"],
        mode="lines+markers", name="Tokens",
        line=dict(color="#6366f1"),
    ))
    completed = [r for r in results if r["status"] == "completed"]
    failed = [r for r in results if r["status"] != "completed"]
    if completed:
        x_vals = [results.index(r) for r in completed]
        y_vals = [r["tokens"] for r in completed]
        fig.add_trace(go.Scatter(
            x=x_vals, y=y_vals,
            mode="markers", name="Completed",
            marker=dict(color="#22c55e", size=10),
        ))
    if failed:
        x_vals = [results.index(r) for r in failed]
        y_vals = [r["tokens"] for r in failed]
        fig.add_trace(go.Scatter(
            x=x_vals, y=y_vals,
            mode="markers", name="Failed",
            marker=dict(color="#ef4444", size=10),
        ))
    fig.update_layout(
        height=250, margin=dict(l=0, r=0, t=0, b=0),
        xaxis=dict(title="Sprint #"),
        yaxis=dict(title="Tokens"),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig
