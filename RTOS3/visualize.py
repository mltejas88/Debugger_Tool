#!/usr/bin/env python3
"""
visualize.py
Improved RTOS trace visualizer:
 - Detects columns automatically
 - Uses SWITCHED_IN/OUT to build real execution segments
 - Falls back to other events (EVT_*) to draw small activity segments
 - Merges overlapping segments per task
"""

import sys
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path

DEFAULT_MARKER_FRAC = 0.01  # marker width as fraction of max_tick if no switch events

# ---------- Load + normalize ----------
def load_csv(path):
    df = pd.read_csv(path, dtype=str).fillna('')
    df = df.applymap(lambda x: x.strip() if isinstance(x, str) else x)
    cols = list(df.columns)

    def find(cols, candidates):
        for cand in candidates:
            for c in cols:
                if c.lower() == cand.lower():
                    return c
        return None

    event_col = find(cols, ["eventtype","event","etype","type"])
    tick_col  = find(cols, ["tick","time","timestamp"])
    task_col  = find(cols, ["taskid","task","task_name","taskname"])

    # fallbacks using heuristics
    if event_col is None:
        event_col = max(cols, key=lambda c: df[c].astype(str).str.contains(r"SWITCHED|EVT_", case=False).mean())
    if tick_col is None:
        tick_col = max(cols, key=lambda c: df[c].astype(str).str.match(r"^\s*\d+\s*$").mean())
    if task_col is None:
        # choose the column with many alphabetic tokens (best-effort)
        task_col = max(cols, key=lambda c: df[c].astype(str).str.match(r'^[A-Za-z0-9_ -]+$').mean())

    df = df.rename(columns={event_col: "eventtype", tick_col: "tick", task_col: "taskid"})
    df["tick"] = pd.to_numeric(df["tick"], errors="coerce").fillna(0).astype(int)
    # convert empty taskid to empty string
    df["taskid"] = df["taskid"].astype(str).replace("nan","").fillna("").astype(str)
    df["eventtype"] = df["eventtype"].astype(str)
    return df

# ---------- Fill missing taskid by looking nearby ----------
def fill_taskid_context(df, max_look=6):
    s = df['taskid'].replace('', np.nan)
    arr = s.values.copy()
    n = len(arr)
    for i in range(n):
        if pd.isna(arr[i]):
            # look forward then backward
            found = None
            for j in range(i+1, min(n, i+1+max_look)):
                if not pd.isna(arr[j]):
                    found = arr[j]; break
            if found is not None:
                arr[i] = found
                continue
            for j in range(max(0, i-max_look), i)[::-1]:
                if not pd.isna(arr[j]):
                    found = arr[j]; break
            if found is not None:
                arr[i] = found
    df['taskid_filled'] = pd.Series(arr).fillna('').astype(str)
    return df

# ---------- Build segments ----------
def build_segments(df, marker_frac=DEFAULT_MARKER_FRAC):
    max_tick = int(df['tick'].max()) if not df.empty else 0
    min_tick = int(df['tick'].min()) if not df.empty else 0
    marker_width = max(1, int(max(1, round(max_tick * marker_frac)))) if max_tick>0 else 1

    # 1) Use SWITCHED_IN/OUT pairs
    sw_df = df[df['eventtype'].str.contains('SWITCHED', case=False, na=False)].sort_values('tick').reset_index(drop=True)
    segments = {}

    # stack: for each task keep last in-tick if open
    open_in = {}
    for idx, row in sw_df.iterrows():
        ev = row['eventtype'].upper()
        t = row['taskid_filled'] if row['taskid_filled'] != '' else None
        tick = int(row['tick'])
        if 'SWITCHED_IN' in ev:
            if not t:
                # try lookahead for task name
                t = None
                for j in range(idx+1, min(len(sw_df), idx+6)):
                    cand = sw_df.loc[j,'taskid_filled']
                    if cand!='':
                        t = cand; break
            if t is None:
                t = 'UNKNOWN'
            open_in[t] = tick
            segments.setdefault(t, [])
            # append open segment (end None)
            segments[t].append([tick, None])
        elif 'SWITCHED_OUT' in ev:
            if t is None:
                # try close any open last-most
                # find the most recent open segment
                found = None
                for name, segs in segments.items():
                    if segs and segs[-1][1] is None:
                        found = name; break
                if found:
                    segments[found][-1][1] = tick
            else:
                if t in segments and segments[t] and segments[t][-1][1] is None:
                    segments[t][-1][1] = tick
                else:
                    # no open - create zero-length visible segment
                    segments.setdefault(t, []).append([tick, tick+marker_width])

    # 2) For tasks that never had switch segments, use EVT_* events to create small markers
    # collect any task appearing anywhere
    all_tasks = set(df['taskid_filled'].unique())
    for task in list(all_tasks):
        if task == '' or task is None:
            continue
        if task not in segments or len(segments[task]) == 0:
            # gather ticks where this task had other events (non-SWITCHED)
            ev_ticks = df[(df['taskid_filled']==task) & (~df['eventtype'].str.contains('SWITCHED', case=False, na=False))]['tick'].tolist()
            if ev_ticks:
                # create small segments centered or starting at each tick
                segments.setdefault(task, [])
                for t in ev_ticks:
                    start = int(t)
                    end = start + marker_width
                    segments[task].append([start, end])

    # 3) Fill open segments to max_tick
    for name, segs in list(segments.items()):
        for seg in segs:
            if seg[1] is None:
                seg[1] = max_tick

    # 4) Merge overlapping/adjacent segments per task (adjacent within 1 tick)
    merged = {}
    for name, segs in segments.items():
        if not segs:
            continue
        # sort by start
        segs_sorted = sorted(segs, key=lambda s: s[0])
        m = [segs_sorted[0].copy()]
        for s in segs_sorted[1:]:
            if s[0] <= m[-1][1] + 1:
                # overlap/adjacent -> extend
                m[-1][1] = max(m[-1][1], s[1])
            else:
                m.append(s.copy())
        merged[name] = m

    return merged, max_tick

# ---------- Plot ----------
def plot_segments(segments, max_tick, out_path):
    sns.set_theme(style="white", palette="muted")
    tasks = sorted(segments.keys(), key=lambda s: (s=='UNKNOWN', s))
    if not tasks:
        print("No tasks to plot.")
        return
    y_height = 0.6
    y_spacing = 0.6
    fig, ax = plt.subplots(figsize=(14, max(4, len(tasks)*0.6 + 1)))
    palette = sns.color_palette("tab10", n_colors=max(3, len(tasks)))
    y_positions = {t: i*(y_height+y_spacing) for i,t in enumerate(tasks)}
    y_centers = {t: base + y_height/2 for t, base in y_positions.items()}
    for i, t in enumerate(tasks):
        for start, end in segments.get(t, []):
            width = max(0.5, end - start)
            ax.barh(y=y_centers[t], width=width, left=start, height=y_height,
                    color=palette[i % len(palette)], edgecolor='k', linewidth=0.5)
    ax.set_yticks([y_centers[t] for t in tasks])
    ax.set_yticklabels(tasks)
    ax.set_xlabel("Tick Count")
    ax.set_xlim(0, max_tick*1.02 if max_tick>0 else 10)
    step = max(1, round(max_tick/12)) if max_tick>0 else 1
    ax.set_xticks(range(0, max_tick+step, step))
    ax.set_title("Task Schedule Diagram")
    plt.tight_layout()
    plt.savefig(out_path)
    print(f"Saved plot to {out_path}")

# ---------- CLI ----------
def main():
    if len(sys.argv) < 3:
        print("Usage: python visualize.py <input_csv> <output_pdf>")
        sys.exit(1)
    inp = Path(sys.argv[1])
    out = Path(sys.argv[2])
    print("Loading", inp)
    df = load_csv(inp)
    print("Filling taskid context...")
    df = fill_taskid_context(df, max_look=8)
    print("Building segments...")
    segments, max_tick = build_segments(df, marker_frac=DEFAULT_MARKER_FRAC)
    print("Plotting...")
    plot_segments(segments, max_tick, out)
    print("Done. Tasks plotted:", sorted(segments.keys()))

if __name__ == "__main__":
    main()

