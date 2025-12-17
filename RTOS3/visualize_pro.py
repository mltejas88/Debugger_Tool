#!/usr/bin/env python3
import argparse
import html
import os
import webbrowser
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio

# -------------------------------------------------------------------
# Filters requested
# 1) Remove esp_timer from Lifecycle + Blocking/Waiting
# 2) Remove IDLE from Blocking/Waiting
# -------------------------------------------------------------------
EXCLUDE_CPU_TASKS = {"Flush"}                 # CPU: remove only Flush
EXCLUDE_LIFECYCLE_TASKS = {"Flush", "esp_timer"}
EXCLUDE_BLOCK_TASKS = {"Flush", "esp_timer", "IDLE"}

# Make ultra-short segments visible (visual-only)
MIN_VISIBLE_WIDTH = 1


# -----------------------
# CSV
# -----------------------
def load_csv(path: str):
    """
    Returns:
      df_sorted: used for timeline inference (sorted by tick, stable)
      df_raw:    preserved original CSV row order for the raw table
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"CSV not found: {p.resolve()}")

    df_raw = pd.read_csv(p)

    # Normalize columns for processing
    df = df_raw.copy()
    df["tick"] = pd.to_numeric(df.get("tick", 0), errors="coerce").fillna(0).astype(int)
    df["taskid"] = df.get("taskid", "").astype(str)
    df["eventtype"] = df.get("eventtype", "").astype(str)
    df["object"] = df.get("object", "").astype(str)

    # Keep inference stable, but DO NOT affect df_raw (table stays in original file order)
    df_sorted = df.sort_values("tick", kind="stable").reset_index(drop=True)
    df_raw = df_raw.reset_index(drop=True)  # original order, clean index
    return df_sorted, df_raw


def infer_xrange(df_sorted: pd.DataFrame, xmin_arg, xmax_arg):
    dmin = int(df_sorted["tick"].min()) if not df_sorted.empty else 0
    dmax = int(df_sorted["tick"].max()) if not df_sorted.empty else 0

    xmin = xmin_arg if xmin_arg is not None else dmin - 10
    xmax = xmax_arg if xmax_arg is not None else dmax + 10
    if xmax <= xmin:
        xmax = xmin + 1
    return int(xmin), int(xmax), int(dmin), int(dmax)


# -----------------------
# CPU timeline (same inference as PDF version)
# -----------------------
def build_cpu_timeline(df_sorted: pd.DataFrame, xmin: int, xmax: int):
    timeline = []
    current = "IDLE"
    start = xmin

    for _, r in df_sorted.iterrows():
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
    return [(t, s, e) for (t, s, e) in timeline if t not in EXCLUDE_CPU_TASKS]


# -----------------------
# Lifecycle
# -----------------------
def extract_lifecycle(df_sorted: pd.DataFrame, xmax: int):
    creates, deletes = {}, {}
    for _, r in df_sorted.iterrows():
        ev = r["eventtype"]
        tick = int(r["tick"])
        obj = r["object"]

        if obj in EXCLUDE_LIFECYCLE_TASKS:
            continue
        if ev == "EVT_TASK_CREATE":
            creates.setdefault(obj, tick)
        elif ev == "EVT_TASK_DELETE":
            deletes[obj] = tick

    segments = []
    for t, s in creates.items():
        if t in EXCLUDE_LIFECYCLE_TASKS:
            continue
        segments.append((t, s, deletes.get(t, xmax)))
    return segments


# -----------------------
# Blocking inference
# -----------------------
def extract_blocking(df_sorted: pd.DataFrame):
    blocking = {"QUEUE": {}, "DELAY": {}}
    last_blocking_api = {}
    open_block = {}

    for _, r in df_sorted.iterrows():
        task = r["taskid"]
        ev = r["eventtype"]
        tick = int(r["tick"])

        if task in EXCLUDE_BLOCK_TASKS:
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
# Tasks lists (per-plot)
# -----------------------
def tasks_for_cpu(df_sorted, cpu_timeline):
    tasks = set()
    for t, _, _ in cpu_timeline:
        if t and t not in EXCLUDE_CPU_TASKS:
            tasks.add(t)
    for t in df_sorted["taskid"].unique():
        if t and t not in EXCLUDE_CPU_TASKS:
            tasks.add(t)
    tasks = sorted(tasks)
    if "IDLE" in tasks:
        tasks.remove("IDLE")
        tasks.insert(max(0, len(tasks) // 2), "IDLE")
    return tasks


def tasks_for_lifecycle(lifecycle_segments):
    return sorted({t for (t, _, _) in lifecycle_segments if t and t not in EXCLUDE_LIFECYCLE_TASKS})


def tasks_for_blocking(blocking):
    tasks = set()
    for m in blocking.values():
        for t in m.keys():
            if t and t not in EXCLUDE_BLOCK_TASKS:
                tasks.add(t)
    return sorted(tasks)


# -----------------------
# Colors (more contrast)
# -----------------------
def make_task_color_map(tasks):
    palette = [
        "#2563eb",  # blue
        "#f97316",  # orange
        "#22c55e",  # green
        "#ef4444",  # red
        "#a855f7",  # purple
        "#14b8a6",  # teal
        "#eab308",  # yellow
        "#ec4899",  # pink
        "#0ea5e9",  # sky
        "#84cc16",  # lime
        "#f43f5e",  # rose
        "#8b5cf6",  # violet
    ]
    cmap, i = {}, 0
    for t in tasks:
        if t == "IDLE":
            cmap[t] = "rgba(156,163,175,0.90)"
        else:
            cmap[t] = palette[i % len(palette)]
            i += 1
    return cmap


# -----------------------
# WebGL segment plotting
# -----------------------
def add_webgl_segments(fig, segments, tasks, color_for_task, line_width=24, y_gap=2.8, hover_prefix=""):
    y_index = {t: i for i, t in enumerate(tasks)}
    per_task = {}

    for task, s, e, hover in segments:
        if task not in y_index:
            continue
        s = int(s); e = int(e)
        if e <= s:
            e = s + MIN_VISIBLE_WIDTH
        per_task.setdefault(task, []).append((s, e, hover))

    for task, segs in per_task.items():
        y = y_index[task] * y_gap
        xs, ys = [], []
        hx, hy, htext = [], [], []

        for s, e, hover in segs:
            xs.extend([s, e, None])
            ys.extend([y, y, None])

            mid = (s + e) / 2.0
            hx.append(mid)
            hy.append(y)

            extra = ""
            if hover:
                extra = "<br>" + "<br>".join([f"{k}: {v}" for k, v in hover.items()])

            prefix = f"<b>{hover_prefix}</b><br>" if hover_prefix else ""
            htext.append(f"{prefix}<b>{task}</b><br>start: {s}<br>end: {e}<br>dur: {e - s}{extra}")

        fig.add_trace(
            go.Scattergl(
                x=xs, y=ys,
                mode="lines",
                line=dict(width=line_width, color=color_for_task(task)),
                hoverinfo="skip",
                showlegend=False,
            )
        )
        fig.add_trace(
            go.Scattergl(
                x=hx, y=hy,
                mode="markers",
                marker=dict(size=9, opacity=0.0),
                text=htext,
                hovertemplate="%{text}<extra></extra>",
                showlegend=False,
            )
        )


def add_cpu_switch_markers(fig, cpu_timeline, tasks, xmin, xmax, y_gap=2.8, max_markers=2500):
    ticks = [int(e) for (_, _, e) in cpu_timeline]
    ticks = [t for t in ticks if xmin <= t <= xmax]
    if not ticks:
        return

    ticks = sorted(set(ticks))
    if len(ticks) > max_markers:
        step = max(1, len(ticks) // max_markers)
        ticks = ticks[::step]

    y0 = -0.5 * y_gap
    y1 = (len(tasks) - 0.5) * y_gap

    xs, ys = [], []
    for t in ticks:
        xs.extend([t, t, None])
        ys.extend([y0, y1, None])

    fig.add_trace(
        go.Scattergl(
            x=xs, y=ys,
            mode="lines",
            line=dict(width=1, color="rgba(17,24,39,0.14)"),
            hoverinfo="skip",
            showlegend=False,
        )
    )


def make_base_figure(title, tasks, xmin, xmax, height, y_gap=2.8):
    fig = go.Figure()
    fig.update_layout(
        title=dict(text=title, x=0.02, xanchor="left"),
        height=height,
        template="plotly_white",
        margin=dict(l=95, r=25, t=70, b=55),
        hovermode="closest",
        font=dict(size=13),
    )
    fig.update_xaxes(
        range=[xmin, xmax],
        title_text="Tick",
        showgrid=True,
        gridcolor="rgba(17,24,39,0.06)",
        zeroline=False,
    )
    fig.update_yaxes(
        tickmode="array",
        tickvals=[i * y_gap for i in range(len(tasks))],
        ticktext=tasks,
        autorange="reversed",
        showgrid=False,
        zeroline=False,
    )
    return fig


# -----------------------
# DataTables table (fast) — KEEP ORIGINAL CSV ORDER
# -----------------------
def df_to_datatable_html(df_raw: pd.DataFrame, table_rows: int):
    """
    df_raw must be the original-order DataFrame (CSV row order).
    """
    if table_rows == 0:
        return "<p><i>Raw table disabled.</i></p>"

    d = df_raw if table_rows < 0 else df_raw.head(table_rows)
    d = d.fillna("").astype(str).applymap(lambda s: html.escape(s))

    cols = "".join([f"<th>{c}</th>" for c in d.columns])
    rows = []
    for row in d.itertuples(index=False):
        tds = "".join([f"<td>{v}</td>" for v in row])
        rows.append(f"<tr>{tds}</tr>")
    body = "\n".join(rows)

    return f"""
<table id="events" class="display compact stripe" style="width:100%">
  <thead><tr>{cols}</tr></thead>
  <tbody>{body}</tbody>
</table>
"""


def task_legend_html(tasks, cmap, max_items=70):
    items = []
    shown = 0
    for t in tasks:
        if t in EXCLUDE_CPU_TASKS:
            continue
        if shown >= max_items:
            items.append("<div class='legend-more'>… (legend truncated)</div>")
            break
        c = cmap.get(t, "#999")
        items.append(
            f"<div class='legend-item'><span class='swatch' style='background:{c}'></span>"
            f"<span class='lname'>{html.escape(t)}</span></div>"
        )
        shown += 1
    return "\n".join(items)


# -----------------------
# Single HTML
# -----------------------
def build_single_html(cpu_fig, life_fig, block_fig, cpu_tasks, cmap, df_raw,
                      out_html: Path, xmin, xmax, dmax, table_rows, slider_steps):

    config = {
        "displaylogo": False,
        "modeBarButtonsToRemove": ["lasso2d", "select2d"],
        "responsive": True,
    }
    cpu_div = pio.to_html(cpu_fig, include_plotlyjs="cdn", full_html=False, config=config, div_id="cpuPlot")
    life_div = pio.to_html(life_fig, include_plotlyjs=False, full_html=False, config=config, div_id="lifePlot")
    block_div = pio.to_html(block_fig, include_plotlyjs=False, full_html=False, config=config, div_id="blockPlot")

    xmax_min = max(xmin + 1, xmin + 10)
    xmax_max = max(xmax, dmax + 10)
    step = max(1, int((xmax_max - xmax_min) / max(10, slider_steps)))

    # IMPORTANT: raw table uses df_raw (original CSV order)
    table_html = df_to_datatable_html(df_raw, table_rows)
    legend_html = task_legend_html(cpu_tasks, cmap, max_items=70)

    html_doc = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>RTOS Trace Visualizer</title>

  <style>
    body {{
      font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
      background: #f6f7fb;
      margin: 16px;
      color: #111;
    }}
    .grid {{
      display: grid;
      grid-template-columns: 1fr 280px;
      gap: 14px;
      align-items: start;
    }}
    .card {{
      background: white;
      border: 1px solid rgba(0,0,0,0.08);
      border-radius: 14px;
      box-shadow: 0 10px 25px rgba(0,0,0,0.04);
      padding: 12px;
      margin-bottom: 14px;
    }}
    .card h2 {{
      margin: 0 0 8px 0;
      font-size: 16px;
      font-weight: 650;
    }}
    .subtle {{
      color: #555;
      font-size: 13px;
      margin-top: 6px;
    }}
    .slider-row {{
      display:flex;
      align-items:center;
      gap:12px;
      flex-wrap: wrap;
    }}
    #xmaxValue {{
      font-weight: 650;
      background: #eef2ff;
      border: 1px solid rgba(0,0,0,0.06);
      padding: 6px 10px;
      border-radius: 10px;
      min-width: 96px;
      text-align: center;
    }}
    input[type="range"] {{
      width: 520px;
      accent-color: #6366f1;
    }}

    .legend {{
      max-height: 980px;
      overflow: auto;
      padding-right: 6px;
    }}
    .legend-item {{
      display:flex;
      align-items:center;
      gap:10px;
      padding: 6px 6px;
      border-radius: 10px;
    }}
    .legend-item:hover {{
      background: rgba(99,102,241,0.08);
    }}
    .swatch {{
      width: 16px;
      height: 10px;
      border-radius: 3px;
      border: 1px solid rgba(0,0,0,0.15);
      flex: 0 0 auto;
    }}
    .lname {{
      font-size: 13px;
      word-break: break-word;
    }}
    .legend-more {{
      color:#666; font-size: 12px; padding: 8px 6px;
    }}

    table.dataTable tbody td {{ font-size: 12px; }}
    table.dataTable thead th {{ font-size: 12px; }}
  </style>

  <link rel="stylesheet" href="https://cdn.datatables.net/1.13.8/css/jquery.dataTables.min.css">
  <script src="https://code.jquery.com/jquery-3.7.1.min.js"></script>
  <script src="https://cdn.datatables.net/1.13.8/js/jquery.dataTables.min.js"></script>
</head>
<body>

  <div class="card">
    <h2>RTOS Trace Visualizer</h2>
    <div class="slider-row">
      <div style="font-weight:650;">Global X max</div>
      <input id="xmaxSlider" type="range" min="{xmax_min}" max="{xmax_max}" value="{xmax}" step="{step}">
      <div id="xmaxValue">{xmax}</div>
    </div>
    <div class="subtle">This slider updates the X-axis limit for CPU, Lifecycle, and Blocking together.</div>
  </div>

  <div class="grid">
    <div>
      <div class="card">{cpu_div}</div>
      <div class="card">{life_div}</div>
      <div class="card">{block_div}</div>
    </div>

    <div class="card">
      <h2>Task Colors (CPU)</h2>
      <div class="subtle">Color legend for CPU schedule.</div>
      <div class="legend">{legend_html}</div>
      <div class="subtle" style="margin-top:10px;">
        Blocking colors: <span style="font-weight:650;color:#b45309;">QUEUE</span> (orange),
        <span style="font-weight:650;color:#1e3a8a;">DELAY</span> (blue)
      </div>
    </div>
  </div>



<script>
  function setXMax(v) {{
    document.getElementById("xmaxValue").textContent = v;
    Plotly.relayout('cpuPlot',  {{'xaxis.range': [{xmin}, v] }});
    Plotly.relayout('lifePlot', {{'xaxis.range': [{xmin}, v] }});
    Plotly.relayout('blockPlot',{{'xaxis.range': [{xmin}, v] }});
  }}

  const slider = document.getElementById("xmaxSlider");
  slider.addEventListener("input", (e) => {{
    setXMax(parseInt(e.target.value));
  }});

  $(document).ready(function() {{
    const hasTable = document.getElementById('events');
    if (hasTable) {{
      $('#events').DataTable({{
        pageLength: 25,
        lengthMenu: [ [25, 50, 100, 250], [25, 50, 100, 250] ]
      }});
    }}
  }});
</script>

</body>
</html>
"""
    out_html.write_text(html_doc, encoding="utf-8")


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
    ap.add_argument("--table", type=int, default=5000,
                    help="Raw table rows: N=first N rows (fast), -1=ALL (heavier), 0=disable")
    ap.add_argument("--slider-steps", type=int, default=140,
                    help="Controls slider smoothness (affects slider step size)")
    ap.add_argument("--line-width", type=int, default=24,
                    help="Thickness of timeline lines (bigger looks more like bars)")
    ap.add_argument("--y-gap", type=float, default=2.8,
                    help="Vertical spacing between task lanes (bigger = more space)")
    ap.add_argument("--switch-markers", action="store_true",
                    help="Show faint vertical markers on CPU plot at task switches")
    args = ap.parse_args()

    df_sorted, df_raw = load_csv(args.csv)
    xmin, xmax, _dmin, dmax = infer_xrange(df_sorted, args.xmin, args.xmax)

    out = Path(args.out) if args.out else Path(args.csv).with_suffix("").with_name(
        Path(args.csv).stem + "_rtos_trace_fast_pretty.html"
    )

    cpu_tl = build_cpu_timeline(df_sorted, xmin, xmax)
    life = extract_lifecycle(df_sorted, xmax)
    blocking = extract_blocking(df_sorted)

    cpu_tasks = tasks_for_cpu(df_sorted, cpu_tl)
    life_tasks = tasks_for_lifecycle(life)
    block_tasks = tasks_for_blocking(blocking)

    cmap = make_task_color_map(cpu_tasks)

    def lane_height(n):
        return max(520, 200 + int(n * args.y_gap * 18))

    # CPU
    cpu_fig = make_base_figure("CPU Schedule", cpu_tasks, xmin, xmax, height=lane_height(len(cpu_tasks)), y_gap=args.y_gap)
    cpu_segments = [(t, s, e, {"plot": "CPU"}) for (t, s, e) in cpu_tl]
    add_webgl_segments(
        cpu_fig, cpu_segments, cpu_tasks,
        color_for_task=lambda t: cmap.get(t, "#2563eb"),
        line_width=args.line_width, y_gap=args.y_gap, hover_prefix="CPU"
    )
    if args.switch_markers:
        add_cpu_switch_markers(cpu_fig, cpu_tl, cpu_tasks, xmin, xmax, y_gap=args.y_gap)

    # Lifecycle
    life_fig = make_base_figure("Task Lifecycle (Create → Delete)", life_tasks, xmin, xmax, height=lane_height(len(life_tasks)), y_gap=args.y_gap)
    life_segments = [(t, s, e, {}) for (t, s, e) in life]
    add_webgl_segments(
        life_fig, life_segments, life_tasks,
        color_for_task=lambda _t: "rgba(16,185,129,0.95)",
        line_width=args.line_width, y_gap=args.y_gap, hover_prefix="Lifecycle"
    )

    # Blocking
    block_fig = make_base_figure("Task Blocking / Waiting", block_tasks, xmin, xmax, height=lane_height(len(block_tasks)), y_gap=args.y_gap)

    queue_segments, delay_segments = [], []
    for kind, m in blocking.items():
        for t, segs in m.items():
            if t in EXCLUDE_BLOCK_TASKS:
                continue
            for s, e in segs:
                if kind == "QUEUE":
                    queue_segments.append((t, s, e, {"kind": "QUEUE"}))
                else:
                    delay_segments.append((t, s, e, {"kind": "DELAY"}))

    if queue_segments:
        add_webgl_segments(
            block_fig, queue_segments, block_tasks,
            color_for_task=lambda _t: "rgba(245,158,11,0.95)",
            line_width=args.line_width, y_gap=args.y_gap, hover_prefix="Blocking (QUEUE)"
        )
    if delay_segments:
        add_webgl_segments(
            block_fig, delay_segments, block_tasks,
            color_for_task=lambda _t: "rgba(59,130,246,0.85)",
            line_width=args.line_width, y_gap=args.y_gap, hover_prefix="Blocking (DELAY)"
        )

    build_single_html(cpu_fig, life_fig, block_fig, cpu_tasks, cmap, df_raw, out, xmin, xmax, dmax, args.table, args.slider_steps)

    print(f"✅ Wrote report: {out.resolve()}")
    print("Raw CSV table: original file order (no tick-sorting).")

    if not args.no_open:
        try:
            webbrowser.open("file://" + os.path.abspath(out))
        except Exception:
            pass


if __name__ == "__main__":
    main()