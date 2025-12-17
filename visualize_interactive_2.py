#!/usr/bin/env python3
"""
RTOS Trace Visualizer — Interactive (SECTIONS)

Creates separate interactive HTML files:
1) CPU Schedule        -> <prefix>_cpu.html
2) Task Lifecycle      -> <prefix>_lifecycle.html
3) Blocking / Waiting  -> <prefix>_blocking.html
(Optional) Raw Events  -> <prefix>_events.html

Uses Plotly rectangle SHAPES to ensure ultra-thin segments (0–1 tick) are visible.

Usage:
  python3 visualize_interactive_sections.py path/to/log_entries.csv
  python3 visualize_interactive_sections.py path/to/log_entries.csv --out-prefix report
  python3 visualize_interactive_sections.py path/to/log_entries.csv --xmin -10 --xmax 12000
  python3 visualize_interactive_sections.py path/to/log_entries.csv --table 500
  python3 visualize_interactive_sections.py path/to/log_entries.csv --table -1   # ALL rows (slow)
  python3 visualize_interactive_sections.py path/to/log_entries.csv --no-open
"""

import argparse
import os
import webbrowser
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
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
# CPU Timeline
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
    creates, deletes = {}, {}
    for _, r in df.iterrows():
        ev = r["eventtype"]
        tick = int(r["tick"])
        obj = r["object"]
        if obj in EXCLUDE_TASKS:
            continue
        if ev == "EVT_TASK_CREATE":
            creates.setdefault(obj, tick)
        elif ev == "EVT_TASK_DELETE":
            deletes[obj] = tick

    segments = []
    for t, s in creates.items():
        segments.append((t, s, deletes.get(t, xmax)))
    return segments, creates, deletes


# -----------------------
# Blocking inference
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
# Task list
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

    for m in blocking.values():
        for t in m.keys():
            if t and t not in EXCLUDE_TASKS:
                tasks.add(t)

    tasks = sorted(tasks)
    if "IDLE" in tasks:
        tasks.remove("IDLE")
        tasks.insert(max(0, len(tasks) // 2), "IDLE")
    return tasks


# -----------------------
# Shape plot helper (single-figure)
# -----------------------
def make_shape_figure(title: str, tasks, xmin: int, xmax: int):
    fig = go.Figure()
    fig.update_layout(
        title=title,
        height=max(450, 120 + len(tasks) * 22),
        hovermode="closest",
        margin=dict(l=70, r=20, t=70, b=50),
    )
    fig.update_xaxes(range=[xmin, xmax], title_text="Tick")
    fig.update_yaxes(
        tickmode="array",
        tickvals=list(range(len(tasks))),
        ticktext=tasks,
        autorange="reversed",
    )
    return fig


def add_segments(fig, segments, tasks, fillcolor):
    y_index = {t: i for i, t in enumerate(tasks)}

    # Shapes
    for task, s, e, hover in segments:
        if task not in y_index:
            continue
        y = y_index[task]
        y0, y1 = y - 0.35, y + 0.35

        disp_s, disp_e = float(s), float(e)
        if disp_e <= disp_s:
            disp_e = disp_s + MIN_VISIBLE_WIDTH

        fig.add_shape(
            type="rect",
            x0=disp_s, x1=disp_e,
            y0=y0, y1=y1,
            xref="x", yref="y",
            line=dict(color="black", width=1),
            fillcolor=fillcolor,
            opacity=0.9,
            layer="below",
        )

    # Hover points (invisible)
    hx, hy, htext = [], [], []
    for task, s, e, hover in segments:
        if task not in y_index:
            continue
        hx.append((float(s) + float(e)) / 2.0)
        hy.append(y_index[task])

        extra = ""
        if hover:
            extra = "<br>" + "<br>".join([f"{k}: {v}" for k, v in hover.items()])
        htext.append(f"<b>{task}</b><br>start: {s}<br>end: {e}<br>dur: {e-s}{extra}")

    fig.add_trace(
        go.Scatter(
            x=hx, y=hy,
            mode="markers",
            marker=dict(size=8, opacity=0.0),
            hovertemplate="%{text}<extra></extra>",
            text=htext,
            showlegend=False,
        )
    )


def write_html(fig, out_path: Path):
    pio.write_html(fig, file=str(out_path), include_plotlyjs="cdn", full_html=True)


# -----------------------
# Optional events table
# -----------------------
def make_events_table_figure(df: pd.DataFrame, title: str, table_rows: int):
    if table_rows == 0:
        return None
    d = df if table_rows < 0 else df.head(table_rows)
    d = d.fillna("").astype(str)

    fig = go.Figure(
        data=[
            go.Table(
                header=dict(values=list(d.columns)),
                cells=dict(values=[d[c].tolist() for c in d.columns]),
            )
        ]
    )
    fig.update_layout(
        title=title,
        height=700,
        margin=dict(l=20, r=20, t=70, b=30),
    )
    return fig


# -----------------------
# Main
# -----------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", help="Path to log_entries.csv")
    ap.add_argument("--out-prefix", default=None, help="Output prefix (default: CSV stem)")
    ap.add_argument("--xmin", type=int, default=None)
    ap.add_argument("--xmax", type=int, default=None)
    ap.add_argument("--no-open", action="store_true")
    ap.add_argument("--table", type=int, default=0,
                    help="Raw events table rows: 0=disable, N=first N rows, -1=ALL (slow)")
    args = ap.parse_args()

    df = load_csv(args.csv)
    xmin, xmax = infer_xrange(df, args.xmin, args.xmax)

    prefix = Path(args.out_prefix) if args.out_prefix else Path(args.csv).with_suffix("")
    cpu_out = prefix.with_name(prefix.name + "_cpu.html")
    life_out = prefix.with_name(prefix.name + "_lifecycle.html")
    block_out = prefix.with_name(prefix.name + "_blocking.html")
    events_out = prefix.with_name(prefix.name + "_events.html")

    cpu_timeline = build_cpu_timeline(df, xmin, xmax)
    lifecycle_segments, creates, deletes = extract_lifecycle(df, xmax)
    blocking = extract_blocking(df)
    tasks = stable_task_list(df, cpu_timeline, lifecycle_segments, blocking)

    # --- CPU ---
    cpu_fig = make_shape_figure("CPU Schedule (Interactive)", tasks, xmin, xmax)
    cpu_segments = [(t, s, e, {"plot": "CPU"}) for (t, s, e) in cpu_timeline]
    add_segments(cpu_fig, cpu_segments, tasks, "rgba(0,0,0,0.15)")
    write_html(cpu_fig, cpu_out)

    # --- Lifecycle ---
    life_fig = make_shape_figure("Task Lifecycle (Create → Delete)", tasks, xmin, xmax)
    life_segments = [
        (t, s, e, {"plot": "LIFECYCLE", "created": creates.get(t, ""), "deleted": deletes.get(t, "")})
        for (t, s, e) in lifecycle_segments
    ]
    add_segments(life_fig, life_segments, tasks, "rgba(0,200,0,0.25)")
    write_html(life_fig, life_out)

    # --- Blocking ---
    block_fig = make_shape_figure("Task Blocking / Waiting (RTOS-correct)", tasks, xmin, xmax)

    block_queue, block_delay = [], []
    for kind, m in blocking.items():
        for t, segs in m.items():
            for s, e in segs:
                item = (t, s, e, {"plot": "BLOCK", "kind": kind})
                (block_queue if kind == "QUEUE" else block_delay).append(item)

    if block_queue:
        add_segments(block_fig, block_queue, tasks, "rgba(255,165,0,0.35)")
    if block_delay:
        add_segments(block_fig, block_delay, tasks, "rgba(120,120,120,0.35)")
    write_html(block_fig, block_out)

    # --- Optional events table ---
    ev_fig = make_events_table_figure(df, "Raw Events (CSV)", args.table)
    if ev_fig is not None:
        write_html(ev_fig, events_out)

    print("✅ Generated interactive sections:")
    print(f" - {cpu_out.resolve()}")
    print(f" - {life_out.resolve()}")
    print(f" - {block_out.resolve()}")
    if ev_fig is not None:
        print(f" - {events_out.resolve()}")

    if not args.no_open:
        for p in [cpu_out, life_out, block_out] + ([events_out] if ev_fig is not None else []):
            try:
                webbrowser.open("file://" + os.path.abspath(p))
            except Exception:
                pass


if __name__ == "__main__":
    main()
