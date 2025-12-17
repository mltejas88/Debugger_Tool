#!/usr/bin/env python3
import argparse
import os
import webbrowser
from pathlib import Path

import numpy as np
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
    return int(xmin), int(xmax), dmin, dmax


# -----------------------
# CPU Timeline (same logic as PDF version)
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
# Task list (include everything seen)
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

    # keep IDLE visible
    if "IDLE" in tasks:
        tasks.remove("IDLE")
        tasks.insert(max(0, len(tasks) // 2), "IDLE")

    return tasks


# -----------------------
# Colors (colorful CPU by task)
# -----------------------
def make_task_color_map(tasks):
    # Plotly qualitative palette (nice & colorful)
    palette = [
        "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
        "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
        "#393b79", "#637939", "#8c6d31", "#843c39", "#7b4173",
        "#3182bd", "#e6550d", "#31a354", "#756bb1", "#636363",
    ]
    cmap = {}
    i = 0
    for t in tasks:
        if t == "IDLE":
            cmap[t] = "rgba(180,180,180,0.35)"
        else:
            c = palette[i % len(palette)]
            cmap[t] = c
            i += 1
    return cmap


# -----------------------
# Shape segments + hover
# -----------------------
def axis_suffix(row: int) -> str:
    return "" if row == 1 else str(row)


def add_segments_as_shapes(fig, row, segments, tasks, color_fn, hover_name):
    y_index = {t: i for i, t in enumerate(tasks)}
    suf = axis_suffix(row)
    xref, yref = f"x{suf}", f"y{suf}"

    # Draw shapes
    for task, s, e, hover in segments:
        if task not in y_index:
            continue

        y = y_index[task]
        y0, y1 = y - 0.35, y + 0.35

        disp_s, disp_e = float(s), float(e)
        if disp_e <= disp_s:
            disp_e = disp_s + MIN_VISIBLE_WIDTH

        fillcolor, linecolor = color_fn(task)

        fig.add_shape(
            type="rect",
            x0=disp_s, x1=disp_e,
            y0=y0, y1=y1,
            xref=xref, yref=yref,
            line=dict(color=linecolor, width=1),
            fillcolor=fillcolor,
            opacity=0.9,
            layer="below",
        )

    # Hover markers (invisible)
    hx, hy, htext = [], [], []
    for task, s, e, hover in segments:
        if task not in y_index:
            continue

        hx.append((float(s) + float(e)) / 2.0)
        hy.append(y_index[task])

        extra = ""
        if hover:
            extra = "<br>" + "<br>".join([f"{k}: {v}" for k, v in hover.items()])

        htext.append(
            f"<b>{hover_name}</b><br>"
            f"<b>{task}</b><br>"
            f"start: {s}<br>end: {e}<br>dur: {e - s}{extra}"
        )

    fig.add_trace(
        go.Scatter(
            x=hx, y=hy,
            mode="markers",
            marker=dict(size=8, opacity=0.0),
            hovertemplate="%{text}<extra></extra>",
            text=htext,
            showlegend=False,
        ),
        row=row, col=1
    )


def make_events_table(df: pd.DataFrame, table_rows: int):
    if table_rows == 0:
        return None
    d = df if table_rows < 0 else df.head(table_rows)
    d = d.fillna("").astype(str)

    return go.Table(
        header=dict(values=list(d.columns)),
        cells=dict(values=[d[c].tolist() for c in d.columns]),
    )


# -----------------------
# Global X-max slider
# -----------------------
def build_global_xmax_slider(xmin, dmax, xmax_initial, steps=150):
    """
    One-handle slider that changes x-axis MAX for xaxis, xaxis2, xaxis3 together.
    """
    xmax_min = max(xmin + 1, int(xmin + 10))
    xmax_max = max(xmax_initial, int(dmax + 10))

    # keep steps reasonable
    steps = max(10, int(steps))
    values = np.linspace(xmax_min, xmax_max, steps).astype(int)
    values = np.unique(values)

    slider_steps = []
    for v in values:
        slider_steps.append({
            "method": "relayout",
            "args": [
                {
                    "xaxis.range": [xmin, int(v)],
                    "xaxis2.range": [xmin, int(v)],
                    "xaxis3.range": [xmin, int(v)],
                }
            ],
            "label": str(int(v)),
        })

    # Find closest active index
    active = int(np.argmin(np.abs(values - xmax_initial)))

    slider = {
        "active": active,
        "currentvalue": {"prefix": "Global X max: "},
        "pad": {"t": 10, "b": 10},
        "steps": slider_steps,
    }
    return [slider]


# -----------------------
# Build report (single HTML)
# -----------------------
def build_report(df, xmin, xmax, dmax, out_html: Path, table_rows: int, slider_steps: int):
    cpu_tl = build_cpu_timeline(df, xmin, xmax)
    life, creates, deletes = extract_lifecycle(df, xmax)
    blocking = extract_blocking(df)

    tasks = stable_task_list(df, cpu_tl, life, blocking)
    task_colors = make_task_color_map(tasks)

    def cpu_color_fn(task):
        # CPU: colorful per task
        if task == "IDLE":
            return ("rgba(180,180,180,0.35)", "rgba(130,130,130,1.0)")
        c = task_colors.get(task, "#1f77b4")
        return (c, "rgba(0,0,0,1.0)")

    def lifecycle_color_fn(_task):
        return ("rgba(0,200,0,0.30)", "rgba(0,120,0,1.0)")

    def block_color_fn(_task_kind):
        # color decided by hover kind; we pass task anyway, so just neutral
        return ("rgba(120,120,120,0.0)", "rgba(0,0,0,0.0)")

    fig = make_subplots(
        rows=4 if table_rows != 0 else 3,
        cols=1,
        specs=(
            [[{"type": "xy"}], [{"type": "xy"}], [{"type": "xy"}], [{"type": "table"}]]
            if table_rows != 0 else
            [[{"type": "xy"}], [{"type": "xy"}], [{"type": "xy"}]]
        ),
        row_heights=([0.30, 0.30, 0.30, 0.30] if table_rows != 0 else [0.34, 0.33, 0.33]),
        vertical_spacing=0.08,
        subplot_titles=(
            ["CPU Schedule", "Task Lifecycle (Create → Delete)", "Task Blocking / Waiting", "Raw Events (CSV)"]
            if table_rows != 0 else
            ["CPU Schedule", "Task Lifecycle (Create → Delete)", "Task Blocking / Waiting"]
        ),
    )

    # CPU segments
    cpu_segments = [(t, s, e, {"plot": "CPU"}) for (t, s, e) in cpu_tl]
    add_segments_as_shapes(fig, 1, cpu_segments, tasks, cpu_color_fn, "CPU")

    # Lifecycle segments
    life_segments = [
        (t, s, e, {"created": creates.get(t, ""), "deleted": deletes.get(t, "")})
        for (t, s, e) in life
    ]
    add_segments_as_shapes(fig, 2, life_segments, tasks, lifecycle_color_fn, "Lifecycle")

    # Blocking segments (two overlays)
    block_queue, block_delay = [], []
    for kind, m in blocking.items():
        for t, segs in m.items():
            for s, e in segs:
                item = (t, s, e, {"kind": kind})
                (block_queue if kind == "QUEUE" else block_delay).append(item)

    # Blocking colors depend on kind; implement via two calls:
    def queue_color_fn(_task):  # orange
        return ("rgba(255,165,0,0.40)", "rgba(150,90,0,1.0)")

    def delay_color_fn(_task):  # gray-blue
        return ("rgba(100,100,180,0.30)", "rgba(60,60,120,1.0)")

    if block_queue:
        add_segments_as_shapes(fig, 3, block_queue, tasks, queue_color_fn, "Blocking (QUEUE)")
    if block_delay:
        add_segments_as_shapes(fig, 3, block_delay, tasks, delay_color_fn, "Blocking (DELAY)")

    # Table
    if table_rows != 0:
        table = make_events_table(df, table_rows)
        if table is not None:
            fig.add_trace(table, row=4, col=1)

    # Axes
    for r in (1, 2, 3):
        fig.update_yaxes(
            row=r, col=1,
            tickmode="array",
            tickvals=list(range(len(tasks))),
            ticktext=tasks,
            autorange="reversed",
        )
        fig.update_xaxes(row=r, col=1, range=[xmin, xmax], title_text="Tick")

    # Layout + global slider
    fig.update_layout(
        height=1300 if table_rows != 0 else 1050,
        title="RTOS Trace Visualizer",
        hovermode="closest",
        margin=dict(l=60, r=30, t=80, b=40),
        sliders=build_global_xmax_slider(xmin, dmax, xmax, steps=slider_steps),
    )

    # Important: keep editing minimal
    # (No draw tools; no editable=True)
    config = {
        "displaylogo": False,
        "modeBarButtonsToRemove": [
            "drawline", "drawopenpath", "drawclosedpath", "drawcircle",
            "drawrect", "eraseshape", "lasso2d", "select2d"
        ],
        "responsive": True,
    }

    # write html with config embedded
    html = pio.to_html(fig, include_plotlyjs="cdn", full_html=True, config=config)
    out_html.write_text(html, encoding="utf-8")


# -----------------------
# Main
# -----------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", help="Path to log_entries.csv")
    ap.add_argument("--out", default=None, help="Output HTML filename")
    ap.add_argument("--xmin", type=int, default=None)
    ap.add_argument("--xmax", type=int, default=None)
    ap.add_argument("--no-open", action="store_true")
    ap.add_argument("--table", type=int, default=-1,
                    help="Raw events table rows: -1=ALL (can be slow), N=first N rows, 0=disable")
    ap.add_argument("--slider-steps", type=int, default=150,
                    help="How many positions the global X-max slider has (bigger = smoother but heavier)")
    args = ap.parse_args()

    df = load_csv(args.csv)
    xmin, xmax, _dmin, dmax = infer_xrange(df, args.xmin, args.xmax)

    out = Path(args.out) if args.out else Path(args.csv).with_suffix("").with_name(Path(args.csv).stem + "_rtos_trace.html")
    build_report(df, xmin, xmax, dmax, out, args.table, args.slider_steps)

    print(f"✅ Wrote interactive report: {out.resolve()}")

    if not args.no_open:
        try:
            webbrowser.open("file://" + os.path.abspath(out))
        except Exception:
            pass


if __name__ == "__main__":
    main()
