#!/usr/bin/env python3
"""
RTOS Trace Visualizer (Final Fixed Version)

Plots:
1) CPU Schedule
2) Task Lifecycle (object = created/deleted task)
3) Blocking / Waiting (RTOS-correct inference)

Excludes:
- Flush task ONLY

Tick axis: -10 to 12000
"""

import sys
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path

# ------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------
X_MIN = -10
X_MAX = 12000
EXCLUDE_TASKS = {"Flush"}

# ------------------------------------------------------------
# Load CSV
# ------------------------------------------------------------
def load_csv(path):
    df = pd.read_csv(path)
    df["tick"] = pd.to_numeric(df["tick"], errors="coerce").fillna(0).astype(int)
    df["taskid"] = df["taskid"].astype(str)
    df["eventtype"] = df["eventtype"].astype(str)
    df["object"] = df["object"].astype(str)
    return df.sort_values("tick")

# ------------------------------------------------------------
# Color helper (NO deprecation warning)
# ------------------------------------------------------------
def task_colors(tasks):
    cmap = plt.get_cmap("tab20")
    return {t: cmap(i % cmap.N) for i, t in enumerate(tasks)}

# ------------------------------------------------------------
# 1) CPU Schedule
# ------------------------------------------------------------
def build_cpu_timeline(df):
    timeline = []
    current = "IDLE"
    start = X_MIN

    for _, r in df.iterrows():
        if r["eventtype"] == "traceTASK_SWITCHED_IN":
            timeline.append((current, start, r["tick"]))
            current = r["taskid"]
            start = r["tick"]

        elif r["eventtype"] == "traceTASK_SWITCHED_OUT":
            timeline.append((current, start, r["tick"]))
            current = "IDLE"
            start = r["tick"]

    timeline.append((current, start, X_MAX))
    return timeline

def plot_cpu(timeline, out):
    tasks = sorted({t for t, _, _ in timeline if t not in EXCLUDE_TASKS})
    ypos = {t: i for i, t in enumerate(tasks)}
    colors = task_colors(tasks)

    fig, ax = plt.subplots(figsize=(14, max(4, len(tasks) * 0.6)))

    for t, s, e in timeline:
        if t in EXCLUDE_TASKS:
            continue
        ax.barh(
            ypos[t],
            e - s,
            left=s,
            height=0.6,
            color=colors[t],
            edgecolor="black"
        )

    ax.set_xlim(X_MIN, X_MAX)
    ax.set_yticks(list(ypos.values()))
    ax.set_yticklabels(list(ypos.keys()))
    ax.set_xlabel("Tick")
    ax.set_title("CPU Schedule (Who Runs When)")
    ax.grid(axis="x", linestyle="--", alpha=0.4)
    plt.tight_layout()
    plt.savefig(out)
    plt.close()

# ------------------------------------------------------------
# 2) Task Lifecycle (USES object field)
# ------------------------------------------------------------
def plot_lifecycle(df, out):
    creates = {}
    deletes = {}
    delete_edges = []

    for _, r in df.iterrows():
        if r["eventtype"] == "EVT_TASK_CREATE":
            if r["object"] not in EXCLUDE_TASKS:
                creates[r["object"]] = r["tick"]

        elif r["eventtype"] == "EVT_TASK_DELETE":
            if r["object"] not in EXCLUDE_TASKS:
                deletes[r["object"]] = r["tick"]
                delete_edges.append((r["tick"], r["taskid"], r["object"]))

    tasks = sorted(creates.keys())
    ypos = {t: i for i, t in enumerate(tasks)}

    fig, ax = plt.subplots(figsize=(14, max(4, len(tasks) * 0.6)))

    for t in tasks:
        start = creates[t]
        end = deletes.get(t, X_MAX)

        ax.barh(
            ypos[t],
            end - start,
            left=start,
            height=0.4,
            color="lightgreen",
            edgecolor="black"
        )
        ax.scatter(start, ypos[t], color="green", s=40)
        if t in deletes:
            ax.scatter(end, ypos[t], color="red", s=60)

    # Actor → target arrows
    for tick, actor, target in delete_edges:
        if actor in ypos and target in ypos:
            ax.annotate(
                "",
                xy=(tick, ypos[target]),
                xytext=(tick, ypos[actor]),
                arrowprops=dict(arrowstyle="->", color="red", lw=1.5)
            )

    ax.set_xlim(X_MIN, X_MAX)
    ax.set_yticks(list(ypos.values()))
    ax.set_yticklabels(list(ypos.keys()))
    ax.set_xlabel("Tick")
    ax.set_title("Task Lifecycle (Create → Delete)")
    plt.tight_layout()
    plt.savefig(out)
    plt.close()

# ------------------------------------------------------------
# 3) Blocking / Waiting (RTOS-correct)
# ------------------------------------------------------------
def extract_blocking(df):
    blocking = {"QUEUE": {}, "DELAY": {}}
    last_blocking_api = {}
    open_block = {}

    for _, r in df.iterrows():
        task = r["taskid"]
        ev = r["eventtype"]
        tick = r["tick"]

        if task in EXCLUDE_TASKS:
            continue

        # Only real blocking APIs
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

def plot_blocking(blocking, out):
    tasks = sorted(
        t for m in blocking.values() for t in m
        if t not in EXCLUDE_TASKS
    )

    if not tasks:
        print("No blocking events to plot.")
        return

    ypos = {t: i for i, t in enumerate(tasks)}

    fig, ax = plt.subplots(figsize=(14, max(4, len(tasks) * 0.6)))
    colors = {"QUEUE": "orange", "DELAY": "gray"}

    for kind, cmap in blocking.items():
        for t, segs in cmap.items():
            if t not in ypos:
                continue
            for s, e in segs:
                ax.barh(
                    ypos[t],
                    e - s,
                    left=s,
                    height=0.4,
                    color=colors[kind],
                    label=kind
                )

    ax.set_yticks(list(ypos.values()))
    ax.set_yticklabels(list(ypos.keys()))

    handles, labels = ax.get_legend_handles_labels()
    uniq = dict(zip(labels, handles))
    ax.legend(uniq.values(), uniq.keys())

    ax.set_xlim(X_MIN, X_MAX)
    ax.set_xlabel("Tick")
    ax.set_title("Task Blocking / Waiting (RTOS-correct)")
    plt.tight_layout()
    plt.savefig(out)
    plt.close()

# ------------------------------------------------------------
# Main
# ------------------------------------------------------------
def main():
    if len(sys.argv) < 3:
        print("Usage: python visualize_updated.py log_entries.csv output_prefix")
        sys.exit(1)

    df = load_csv(sys.argv[1])
    prefix = Path(sys.argv[2])

    timeline = build_cpu_timeline(df)
    blocking = extract_blocking(df)

    plot_cpu(timeline, prefix.with_name(prefix.name + "_cpu.pdf"))
    plot_lifecycle(df, prefix.with_name(prefix.name + "_lifecycle.pdf"))
    plot_blocking(blocking, prefix.with_name(prefix.name + "_blocking.pdf"))

    print("Generated plots:")
    print(" - CPU schedule")
    print(" - Task lifecycle")
    print(" - Blocking / waiting")

if __name__ == "__main__":
    main()
