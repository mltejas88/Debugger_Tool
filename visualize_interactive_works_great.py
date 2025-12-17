#!/usr/bin/env python3
"""
RTOS Trace Visualizer — Interactive (Fixed: shows ALL thin segments)

Fixes:
- Avoids private Plotly APIs (works across plotly versions)
- Draws segments as rectangle SHAPES so 0–1 tick slices don't vanish
- Adds raw CSV events table at the bottom

Usage:
  python3 visualize_interactive_fixed.py path/to/log_entries.csv
  python3 visualize_interactive_fixed.py path/to/log_entries.csv --out report.html --no-open
  python3 visualize_interactive_fixed.py path/to/log_entries.csv --xmin -10 --xmax 12000
"""

import argparse
import os
import webbrowser
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.io as pio

EXCLUDE_TASKS = {"Flush"}
MIN_VISIBLE_WIDTH = 0.35  # visual-only width for zero-length segments


# -----------------------
# CSV
# -----------------------
def load_csv(path: str) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"CSV not found: {p.resolve()}")

    df = pd.read_csv(p)
    df["tick"] = pd.to_numeric(df.get("tick", 0), errors="coerce").fillna(0).astype(int)
    df["taskid"] = df.get("taskid", "").astype(str)
    df["eventtype"] = df.get("eventtype", "").astype(str)
    df["object"] = df.get("object", "").astype(str)
    return df.sort_values("tick", kind="stable").reset_index(drop=True)


def infer_xrange(df: pd.DataFrame, xmin_arg, xmax_arg):
    dmin = int(df["tick"].min()) if not df.empty else 0
    dmax = int(df["tick"].max()) if not df.empty else 0

    xmin = xmin_arg if xmin_arg is not None else dmin - 10
    xmax = xmax_arg if xmax_arg is not None else dmax + 10

    if xmax <= xmin:
        xmax = xmin + 1
    return int(xmin), int(xmax)


# -----------------------
# CPU Timeline (same logic as your PDF script)
# -----------------------
def build_cpu_timeline(df: pd.DataFrame, xmin: int, xmax: int):
    timeline = []
    current = "IDLE"
    start = xmin

    for _, r in df.iterrows():
        ev = r["eventtype"]
        tick = int(r["tick"])
        task = r["taskid"]

        if ev == "traceTASK_SWITCHED_IN":
            timeline.append((current, start, tick))
            current = task
            start = tick

        elif ev == "traceTASK_SWITCHED_OUT":
            timeline.append((current, start, tick))
            current = "IDLE"
            start = tick

    timeline.append((current, start, xmax))
    return [(t, s, e) for (t, s, e) in timeline if t not in EXCLUDE_TASKS]


# -----------------------
# Lifecycle
# -----------------------
def extract_lifecycle(df: pd.DataFrame, xmax: int):
    creates = {}
    deletes = {}
    delete_edges = []

    for _, r in df.iterrows():
        ev = r["eventtype"]
        tick = int(r["tick"])
        obj = r["object"]
        actor = r["taskid"]

        if obj in EXCLUDE_TASKS:
            continue

        if ev == "EVT_TASK_CREATE":
            creates.setdefault(obj, tick)
        elif ev == "EVT_TASK_DELETE":
            deletes[obj] = tick
            delete_edges.append((tick, actor, obj))

    segments = []
    for t, s in creates.items():
        e = deletes.get(t, xmax)
        segments.append((t, s, e))
    return segments, delete_edges, creates, deletes


# -----------------------
# Blocking inference (same as your PDF script)
# -----------------------
def extract_blocking(df: pd.DataFrame):
    blocking = {"QUEUE": {}, "DELAY": {}}
    last_blocking_api = {}
    open_block = {}

    for _, r in df.iterrows():
        task = r["taskid"]
        ev = r["eventtype"]
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
                del last_blocking_api[task]

        elif ev == "traceTASK_SWITCHED_IN":
            if task in open_block:
                kind, start = open_block.pop(task)
                blocking[kind].setdefault(task, []).append((start, tick))

    return blocking


# -----------------------
# Task list (include everything we see anywhere)
# -----------------------
def stable_task_list(df, cpu_timeline, lifecycle_segments, blocking):
    tasks = set()

    for t, _, _ in cpu_timeline:
        if t and t not in EXCLUDE_TASKS:
            tasks.add(t)

    for t in df["taskid"].unique():
        if t and t not in EXCLUDE_TASKS:
            tasks.add(t)

    for t, _, _ in lifecycle_segments:
        if t and t not in EXCLUDE_TASKS:
            tasks.add(t)

    for kind in blocking.values():
        for t in kind.keys():
            if t and t not in EXCLUDE_TASKS:
                tasks.add(t)

    tasks = sorted(tasks)
    if "IDLE" in tasks:
        tasks.remove("IDLE")
        tasks.insert(max(0, len(tasks) // 2), "IDLE")
    return tasks


# -----------------------
# Shape drawing + hover points (stable subplot axis ids)
# -----------------------
def axis_suffix(row: int, col: int) -> str:
    # In make_subplots with 1 col:
    # row1 -> x/y, row2 -> x2/y2, row3 -> x3/y3 ...
    # plotly uses '' for first axis
    if row == 1 and col == 1:
        return ""
    # axis index equals subplot number (row since 1 col)
    return str(row)


def add_segments_as_shapes(fig, row, col, segments, tasks, fillcolor, name):
    y_index = {t: i for i, t in enumerate(tasks)}
    suf = axis_suffix(row, col)
    xref = f"x{suf}"
    yref = f"y{suf}"

    # shapes
    for (task, s, e, hover) in segments:
        if task not in y_index:
            continue
        y = y_index[task]
        y0, y1 = y - 0.35, y + 0.35

        real_s, real_e = float(s), float(e)
        disp_s, disp_e = real_s, real_e
        if disp_e <= disp_s:
            disp_e = disp_s + MIN_VISIBLE_WIDTH  # visual only

        fig.add_shape(
            type="rect",
            x0=disp_s, x1=disp_e,
            y0=y0, y1=y1,
            xref=xref, yref=yref,
            line=dict(color="black", width=1),
            fillcolor=fillcolor,
            opacity=0.9,
            layer="below",
        )

    # hover (invisible markers)
    hx, hy, htext = [], [], []
    for (task, s, e, hover) in segments:
        if task not in y_index:
            continue
        mid = (float(s) + float(e)) / 2.0
        hx.append(mid)
        hy.append(y_index[task])

        extra = ""
        if hover:
            extra = "<br>" + "<br>".join([f"{k}: {v}" for k, v in hover.items()])

        htext.append(f"<b>{task}</b><br>start: {s}<br>end: {e}<br>dur: {e - s}{extra}")

    fig.add_trace(
        go.Scatter(
            x=hx, y=hy,
            mode="markers",
            marker=dict(size=8, opacity=0.0),
            hovertemplate="%{text}<extra></extra>",
            text=htext,
            name=name,
            showlegend=False,
        ),
        row=row, col=col
    )


def make_events_table(df: pd.DataFrame):
    d = df.fillna("").astype(str)
    return go.Table(
        header=dict(values=list(d.columns)),
        cells=dict(values=[d[c].tolist() for c in d.columns]),
    )


# -----------------------
# Report
# -----------------------
def build_report(df: pd.DataFrame, xmin: int, xmax: int, out_html: Path):
    cpu_timeline = build_cpu_timeline(df, xmin, xmax)
    lifecycle_segments, _, creates, deletes = extract_lifecycle(df, xmax)
    blocking = extract_blocking(df)

    tasks = stable_task_list(df, cpu_timeline, lifecycle_segments, blocking)

    cpu_segments = [(t, s, e, {"plot": "CPU"}) for (t, s, e) in cpu_timeline]
    life_segments = [(t, s, e, {"plot": "LIFECYCLE", "created": creates.get(t, ""), "deleted": deletes.get(t, "")})
                     for (t, s, e) in lifecycle_segments]

    block_queue, block_delay = [], []
    for kind, m in blocking.items():
        for t, segs in m.items():
            for s, e in segs:
                item = (t, s, e, {"plot": "BLOCK", "kind": kind})
                (block_queue if kind == "QUEUE" else block_delay).append(item)

    fig = make_subplots(
        rows=4, cols=1,
        specs=[[{"type": "xy"}], [{"type": "xy"}], [{"type": "xy"}], [{"type": "table"}]],
        row_heights=[0.30, 0.30, 0.30, 0.30],
        vertical_spacing=0.08,
        subplot_titles=[
            "CPU Schedule (shows all thin segments)",
            "Task Lifecycle (Create → Delete)",
            "Task Blocking / Waiting (RTOS-correct)",
            "Raw Events (CSV)"
        ],
    )

    add_segments_as_shapes(fig, 1, 1, cpu_segments, tasks, "rgba(0,0,0,0.15)", "CPU")
    add_segments_as_shapes(fig, 2, 1, life_segments, tasks, "rgba(0,200,0,0.25)", "Lifecycle")
    if block_queue:
        add_segments_as_shapes(fig, 3, 1, block_queue, tasks, "rgba(255,165,0,0.35)", "Queue Block")
    if block_delay:
        add_segments_as_shapes(fig, 3, 1, block_delay, tasks, "rgba(120,120,120,0.35)", "Delay Block")

    fig.add_trace(make_events_table(df), row=4, col=1)

    for r in (1, 2, 3):
        fig.update_yaxes(
            row=r, col=1,
            tickmode="array",
            tickvals=list(range(len(tasks))),
            ticktext=tasks,
            autorange="reversed"
        )
        fig.update_xaxes(row=r, col=1, range=[xmin, xmax], title_text="Tick")

    fig.update_layout(
        height=1200,
        title="RTOS Trace Visualizer — Interactive (Fixed)",
        hovermode="closest",
        margin=dict(l=60, r=30, t=80, b=40),
    )

    pio.write_html(fig, file=str(out_html), include_plotlyjs="cdn", full_html=True)


# -----------------------
# Main
# -----------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", help="Path to log_entries.csv (relative or absolute)")
    ap.add_argument("--out", default=None, help="Output HTML filename")
    ap.add_argument("--xmin", type=int, default=None)
    ap.add_argument("--xmax", type=int, default=None)
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()

    df = load_csv(args.csv)
    xmin, xmax = infer_xrange(df, args.xmin, args.xmax)

    out = Path(args.out) if args.out else Path(args.csv).with_suffix("").with_name(Path(args.csv).stem + "_rtos_trace.html")
    build_report(df, xmin, xmax, out)

    print(f"✅ Wrote interactive report: {out.resolve()}")

    if not args.no_open:
        try:
            webbrowser.open("file://" + os.path.abspath(out))
        except Exception:
            pass


if __name__ == "__main__":
    main()
