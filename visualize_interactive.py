#!/usr/bin/env python3
from __future__ import annotations

import argparse
import webbrowser
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots


# ------------------------------------------------------------
# CONFIG (same defaults as your original script)
# ------------------------------------------------------------
X_MIN = -10
X_MAX = 12000
EXCLUDE_TASKS = {"Flush"}


# ------------------------------------------------------------
# Load CSV
# ------------------------------------------------------------
def load_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    # Make the types robust (same intent as your original script)
    df["tick"] = pd.to_numeric(df.get("tick"), errors="coerce").fillna(0).astype(int)
    df["taskid"] = df.get("taskid", "").astype(str)
    df["eventtype"] = df.get("eventtype", "").astype(str)
    df["object"] = df.get("object", "").astype(str)
    return df.sort_values("tick").reset_index(drop=True)


# ------------------------------------------------------------
# 1) CPU Schedule
# ------------------------------------------------------------
def build_cpu_timeline(df: pd.DataFrame) -> pd.DataFrame:
    segments: List[Tuple[str, int, int]] = []
    current = "IDLE"
    start = X_MIN

    for _, r in df.iterrows():
        ev = r["eventtype"]
        tick = int(r["tick"])

        if ev == "traceTASK_SWITCHED_IN":
            segments.append((current, start, tick))
            current = str(r["taskid"])
            start = tick

        elif ev == "traceTASK_SWITCHED_OUT":
            segments.append((current, start, tick))
            current = "IDLE"
            start = tick

    segments.append((current, start, X_MAX))

    cpu_df = pd.DataFrame(segments, columns=["Task", "Start", "End"])
    cpu_df = cpu_df[cpu_df["End"] > cpu_df["Start"]].copy()
    cpu_df = cpu_df[~cpu_df["Task"].isin(EXCLUDE_TASKS)].copy()
    return cpu_df


def fig_cpu(cpu_df: pd.DataFrame) -> go.Figure:
    """
    Numeric Gantt using go.Bar (avoids datetime/timedelta issues in px.timeline).
    """
    fig = go.Figure()
    if cpu_df.empty:
        fig.update_layout(title="CPU Schedule (no data after filtering)")
        return fig

    tasks_order = sorted(cpu_df["Task"].unique().tolist())
    for task in tasks_order:
        segs = cpu_df[cpu_df["Task"] == task]
        fig.add_trace(
            go.Bar(
                name=task,
                y=[task] * len(segs),
                x=(segs["End"] - segs["Start"]).tolist(),
                base=segs["Start"].tolist(),
                orientation="h",
                hovertemplate="Task=%{y}<br>Start=%{base}<br>Dur=%{x}<extra></extra>",
            )
        )

    fig.update_layout(
        title="CPU Schedule (Who Runs When)",
        barmode="stack",  # base already sets position; stack works well visually
        bargap=0.15,
        margin=dict(l=60, r=20, t=60, b=50),
        hovermode="closest",
        legend_title_text="Task",
    )
    fig.update_xaxes(range=[X_MIN, X_MAX], title="Tick", showgrid=True)
    fig.update_yaxes(categoryorder="array", categoryarray=tasks_order[::-1], title="")
    return fig


# ------------------------------------------------------------
# 2) Task Lifecycle (USES object field)
# ------------------------------------------------------------ (USES object field)
# ------------------------------------------------------------
def build_lifecycle(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    creates: Dict[str, int] = {}
    deletes: Dict[str, int] = {}
    delete_edges: List[Tuple[int, str, str]] = []

    for _, r in df.iterrows():
        ev = r["eventtype"]
        tick = int(r["tick"])

        if ev == "EVT_TASK_CREATE":
            obj = str(r["object"])
            if obj and obj not in EXCLUDE_TASKS:
                creates[obj] = tick

        elif ev == "EVT_TASK_DELETE":
            obj = str(r["object"])
            if obj and obj not in EXCLUDE_TASKS:
                deletes[obj] = tick
                delete_edges.append((tick, str(r["taskid"]), obj))

    tasks = sorted(creates.keys())
    segs = []
    markers = []

    for t in tasks:
        start = int(creates[t])
        end = int(deletes.get(t, X_MAX))
        if end <= start:
            end = start + 1  # keep it visible

        segs.append((t, start, end))
        markers.append((t, start, "create"))
        if t in deletes:
            markers.append((t, end, "delete"))

    lifecycle_df = pd.DataFrame(segs, columns=["Task", "Start", "End"])
    markers_df = pd.DataFrame(markers, columns=["Task", "Tick", "Kind"])
    edges_df = pd.DataFrame(delete_edges, columns=["Tick", "Actor", "Target"])

    return lifecycle_df, markers_df, edges_df


def fig_lifecycle(lifecycle_df: pd.DataFrame, markers_df: pd.DataFrame, edges_df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    if lifecycle_df.empty:
        fig.update_layout(title="Task Lifecycle (no EVT_TASK_CREATE events found)")
        return fig

    tasks_order = sorted(lifecycle_df["Task"].unique().tolist())

    # Bars (one per task; typically one segment)
    for task in tasks_order:
        segs = lifecycle_df[lifecycle_df["Task"] == task]
        fig.add_trace(
            go.Bar(
                name="lifecycle",
                showlegend=False,
                y=[task] * len(segs),
                x=(segs["End"] - segs["Start"]).tolist(),
                base=segs["Start"].tolist(),
                orientation="h",
                hovertemplate="Task=%{y}<br>Start=%{base}<br>Dur=%{x}<extra></extra>",
            )
        )

    # Create/Delete markers
    if not markers_df.empty:
        create_df = markers_df[markers_df["Kind"] == "create"]
        delete_df = markers_df[markers_df["Kind"] == "delete"]

        if not create_df.empty:
            fig.add_trace(
                go.Scatter(
                    x=create_df["Tick"],
                    y=create_df["Task"],
                    mode="markers",
                    name="create",
                    marker=dict(size=9, symbol="circle"),
                    hovertemplate="create<br>Task=%{y}<br>Tick=%{x}<extra></extra>",
                )
            )
        if not delete_df.empty:
            fig.add_trace(
                go.Scatter(
                    x=delete_df["Tick"],
                    y=delete_df["Task"],
                    mode="markers",
                    name="delete",
                    marker=dict(size=10, symbol="x"),
                    hovertemplate="delete<br>Task=%{y}<br>Tick=%{x}<extra></extra>",
                )
            )

    # Actor → target arrows (best-effort)
    if not edges_df.empty:
        yset = set(tasks_order)
        for _, row in edges_df.iterrows():
            tick = int(row["Tick"])
            actor = str(row["Actor"])
            target = str(row["Target"])
            if actor in yset and target in yset:
                fig.add_annotation(
                    x=tick, y=target,
                    ax=tick, ay=actor,
                    xref="x", yref="y", axref="x", ayref="y",
                    showarrow=True,
                    arrowhead=3,
                    arrowsize=1,
                    arrowwidth=1.5,
                    opacity=0.8,
                    text="",
                )

    fig.update_layout(
        title="Task Lifecycle (Create → Delete)",
        barmode="stack",
        bargap=0.15,
        margin=dict(l=60, r=20, t=60, b=50),
        hovermode="closest",
        legend_title_text="",
    )
    fig.update_xaxes(range=[X_MIN, X_MAX], title="Tick", showgrid=True)
    fig.update_yaxes(categoryorder="array", categoryarray=tasks_order[::-1], title="")
    return fig


# ------------------------------------------------------------
# 3) Blocking / Waiting (RTOS-correct)
# ------------------------------------------------------------ (RTOS-correct)
# ------------------------------------------------------------
def extract_blocking(df: pd.DataFrame) -> pd.DataFrame:
    # Mirrors your original inference logic
    last_blocking_api: Dict[str, str] = {}
    open_block: Dict[str, Tuple[str, int]] = {}
    segs: List[Tuple[str, str, int, int]] = []  # (Task, Kind, Start, End)

    for _, r in df.iterrows():
        task = str(r["taskid"])
        ev = str(r["eventtype"])
        tick = int(r["tick"])

        if task in EXCLUDE_TASKS:
            continue

        if ev in (
            "EVT_QUEUE_RECEIVE",
            "EVT_QUEUE_SEND",
            "EVT_QUEUE_RECEIVE_FROM_ISR",
            "EVT_QUEUE_SEND_FROM_ISR",
        ):
            last_blocking_api[task] = "QUEUE"

        elif ev in ("EVT_TASK_DELAY", "EVT_TASK_DELAY_UNTIL"):
            last_blocking_api[task] = "DELAY"

        elif ev == "traceTASK_SWITCHED_OUT":
            if task in last_blocking_api:
                open_block[task] = (last_blocking_api[task], tick)
                last_blocking_api.pop(task, None)

        elif ev == "traceTASK_SWITCHED_IN":
            if task in open_block:
                kind, start = open_block.pop(task)
                if tick > start:
                    segs.append((task, kind, start, tick))

    blocking_df = pd.DataFrame(segs, columns=["Task", "Kind", "Start", "End"])
    blocking_df = blocking_df[~blocking_df["Task"].isin(EXCLUDE_TASKS)].copy()
    return blocking_df


def fig_blocking(blocking_df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    if blocking_df.empty:
        fig.update_layout(title="Task Blocking / Waiting (no inferred blocking segments found)")
        return fig

    tasks_order = sorted(blocking_df["Task"].unique().tolist())
    kinds_order = sorted(blocking_df["Kind"].unique().tolist())

    for kind in kinds_order:
        kind_df = blocking_df[blocking_df["Kind"] == kind]
        # one trace per kind (legend stays small)
        fig.add_trace(
            go.Bar(
                name=kind,
                y=kind_df["Task"].tolist(),
                x=(kind_df["End"] - kind_df["Start"]).tolist(),
                base=kind_df["Start"].tolist(),
                orientation="h",
                hovertemplate="Kind=%{fullData.name}<br>Task=%{y}<br>Start=%{base}<br>Dur=%{x}<extra></extra>",
            )
        )

    fig.update_layout(
        title="Task Blocking / Waiting (RTOS-correct inference)",
        barmode="stack",
        bargap=0.15,
        margin=dict(l=60, r=20, t=60, b=50),
        hovermode="closest",
        legend_title_text="Kind",
    )
    fig.update_xaxes(range=[X_MIN, X_MAX], title="Tick", showgrid=True)
    fig.update_yaxes(categoryorder="array", categoryarray=tasks_order[::-1], title="")
    return fig


# ------------------------------------------------------------
# HTML report helper
# ------------------------------------------------------------
# ------------------------------------------------------------
def write_report(figs: List[go.Figure], titles: List[str], out_html: Path) -> None:
    import plotly.io as pio

    parts = [
        "<!doctype html>",
        "<html><head><meta charset='utf-8' />",
        "<meta name='viewport' content='width=device-width, initial-scale=1' />",
        "<title>RTOS Trace Visualizer</title>",
        "<style>",
        "body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,Cantarell,Noto Sans,sans-serif;margin:0;padding:16px;}",
        "h1{margin:0 0 12px 0;font-size:20px;}",
        "h2{margin:18px 0 8px 0;font-size:16px;}",
        ".card{border:1px solid #ddd;border-radius:12px;padding:10px;margin:12px 0;}",
        "</style>",
        "</head><body>",
        "<h1>RTOS Trace Visualizer (Interactive)</h1>",
    ]

    # Use a single Plotly.js bundle for the whole page (first figure includes JS; others don't)
    include_js = True
    for fig, title in zip(figs, titles):
        parts.append("<div class='card'>")
        parts.append(f"<h2>{title}</h2>")
        parts.append(pio.to_html(fig, include_plotlyjs=include_js, full_html=False))
        include_js = False
        parts.append("</div>")

    parts.append("</body></html>")
    out_html.write_text("\n".join(parts), encoding="utf-8")


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="Interactive RTOS Trace Visualizer (Plotly)")
    ap.add_argument("csv", type=Path, help="Path to log_entries.csv")
    ap.add_argument("--out", type=Path, default=None, help="Output HTML file (default: <csv_stem>_rtos_trace.html)")
    ap.add_argument("--no-open", action="store_true", help="Do not open the HTML in a browser")
    ap.add_argument("--xmin", type=int, default=X_MIN, help="X-axis min tick (default: -10)")
    ap.add_argument("--xmax", type=int, default=X_MAX, help="X-axis max tick (default: 12000)")
    args = ap.parse_args()

    globals()["X_MIN"] = int(args.xmin)
    globals()["X_MAX"] = int(args.xmax)

    df = load_csv(args.csv)

    cpu_df = build_cpu_timeline(df)
    lifecycle_df, markers_df, edges_df = build_lifecycle(df)
    blocking_df = extract_blocking(df)

    figs = [
        fig_cpu(cpu_df),
        fig_lifecycle(lifecycle_df, markers_df, edges_df),
        fig_blocking(blocking_df),
    ]
    titles = [
        "CPU Schedule",
        "Task Lifecycle",
        "Blocking / Waiting",
    ]

    out_html = args.out if args.out else args.csv.with_name(args.csv.stem + "_rtos_trace.html")
    write_report(figs, titles, out_html)

    print(f"✅ Wrote interactive report: {out_html}")

    if not args.no_open:
        try:
            webbrowser.open(out_html.resolve().as_uri())
        except Exception as e:
            print(f"Could not auto-open browser ({e}). Open the file manually: {out_html}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())