import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import re
import seaborn as sns
from typing import List, Tuple, Dict, Optional


def load_data(csv_file_path: str) -> Optional[pd.DataFrame]:
    try:
        df = pd.read_csv(csv_file_path)
    except FileNotFoundError:
        print(f"Error: The file '{csv_file_path}' was not found.")
        return None
    except pd.errors.EmptyDataError:
        print(f"Error: The file '{csv_file_path}' is empty.")
        return None
    except Exception as e:
        print(f"Error reading CSV file: {e}")
        return None

    if df.empty:
        print("The CSV file is empty.")
        return None

    # Ensure 'tick' is numeric
    df['tick'] = pd.to_numeric(df['tick'], errors='coerce')
    df.dropna(subset=['tick'], inplace=True)
    df['tick'] = df['tick'].astype(int)

    return df


def get_task_segments(df: pd.DataFrame) -> Tuple[Dict[str, List[Tuple[int, int]]], int, List[str]]:
    try:
        task_ids = sorted(
            df['taskid'].dropna().unique(),
            key=lambda x: int(re.sub(r'\D', '', str(x)))
        )
    except ValueError:
        task_ids = sorted(df['taskid'].dropna().unique())

    if not task_ids:
        return {}, 0, []

    task_segments = {}
    max_tick = 0

    for task_id in task_ids:
        task_df = df[df['taskid'] == task_id].sort_values('tick')

        switched_in_ticks = task_df.loc[task_df['eventtype'] == 'traceTASK_SWITCHED_IN', 'tick'].tolist()
        switched_out_ticks = task_df.loc[task_df['eventtype'] == 'traceTASK_SWITCHED_OUT', 'tick'].tolist()

        segments = []
        in_idx = 0
        out_idx = 0

        # get job execution segments
        while in_idx < len(switched_in_ticks):
            in_tick = switched_in_ticks[in_idx]

            # next switched out event
            while out_idx < len(switched_out_ticks) and switched_out_ticks[out_idx] <= in_tick:
                out_idx += 1

            if out_idx < len(switched_out_ticks):
                out_tick = switched_out_ticks[out_idx]
                segments.append((in_tick, out_tick))
                in_idx += 1
                out_idx += 1
            else:
                # last event is IN
                last_known_tick = df['tick'].max()
                if last_known_tick > in_tick:
                    segments.append((in_tick, last_known_tick))
                break

        if segments:
            # Find the max tick for this task and update overall max_tick
            current_max_tick = max(end for start, end in segments)
            max_tick = max(max_tick, current_max_tick)
            task_segments[task_id] = segments
        elif not task_df.empty:
            # Handle task with no segments but has events (updates max_tick)
            max_tick = max(max_tick, task_df['tick'].max())
            task_segments[task_id] = []

    return task_segments, max_tick, task_ids


def calculate_x_ticks(max_tick: int) -> np.ndarray:
    """Helper function to calculate x-axis ticks"""
    if max_tick <= 0:
        return np.arange(0, 10, 1)

    # scale to 10-20 ticks in total
    tick_step = max(1, round(max_tick / 15))

    if tick_step > 1:
        # Round to 1, 2, 5, 10, 20, 50...
        power_of_ten = 10**np.floor(np.log10(tick_step))
        if power_of_ten == 0:
            power_of_ten = 1

        relative_step = tick_step / power_of_ten

        if relative_step < 1.5:
            nice_step = 1
        elif relative_step < 3:
            nice_step = 2
        elif relative_step < 7:
            nice_step = 5
        else:
            nice_step = 10

        tick_step = nice_step * power_of_ten

    return np.arange(0, max_tick + tick_step, tick_step)


def plot_task_schedule(task_segments: Dict[str, List[Tuple[int, int]]],
                       task_ids: List[str],
                       max_tick: int,
                       output_image_name: str):
    sns.set_theme(style="white", palette="muted")

    y_height = 0.7
    y_spacing = 0.5
    palette = sns.color_palette("muted", n_colors=len(task_ids))

    y_base_positions = {task_id: i * (y_height + y_spacing) for i, task_id in enumerate(task_ids)}
    y_center_positions = {task_id: base + y_height / 2 for task_id, base in y_base_positions.items()}

    fig, ax = plt.subplots(figsize=(15, len(task_ids) * 1.0 + 1))

    # execution segments for each task
    for i, task_id in enumerate(task_ids):
        y_pos = y_center_positions[task_id]
        y_base = y_base_positions[task_id]
        bar_color = palette[i % len(palette)]

        # horizontal baseline
        if i > 0:
            ax.axhline(y=y_base, color='grey', linewidth=0.6, zorder=0, alpha=0.8)

        # job execution segments
        for start, end in task_segments.get(task_id, []):
            if end > start:
                ax.barh(y=y_pos, width=end - start, left=start, height=y_height,
                        align='center',
                        color=bar_color,
                        edgecolor=bar_color,
                        linewidth=0.5,
                        zorder=2)

    # Y-Axis
    labels = [str(task_id) for task_id in task_ids]
    ax.set_yticks(list(y_center_positions.values()))
    ax.set_yticklabels(labels, fontsize=12)
    ax.tick_params(axis='y', length=0)

    # X-Axis
    x_ticks = calculate_x_ticks(max_tick)
    ax.set_xticks(x_ticks)
    ax.set_xticklabels([str(int(t)) for t in x_ticks], fontsize=12, color="black")
    ax.tick_params(axis='x', direction='out', length=6, width=1, colors='grey')

    sns.despine(left=True, bottom=False, right=True, top=True)
    ax.spines['bottom'].set_linewidth(0.8)
    ax.spines['bottom'].set_color('black')
    ax.spines['bottom'].set_position(('data', 0))

    if max_tick > 0:
        ax.set_xlim(0, max_tick * 1.02)
    else:
        ax.set_xlim(0, 10)

    final_y_top = y_height + y_spacing
    if task_ids:
        last_task_base = y_base_positions[task_ids[-1]]
        final_y_top = last_task_base + y_height + y_spacing

    ax.set_ylim(bottom=0, top=final_y_top)

    # Vertical Grid Lines
    for tick in x_ticks:
        if tick > 0:
            ax.vlines(x=tick, ymin=0, ymax=final_y_top,
                      color='grey', linestyle='--', alpha=0.5, linewidth=0.7,
                      zorder=1)

    ax.set_xlabel('Tick Count', fontsize=14, color="black")
    ax.set_title('Task Schedule Diagram', fontsize=16, pad=20, weight='bold', color="black")

    plt.tight_layout()
    plt.savefig(output_image_name)
    print(f"Plot saved as {output_image_name}.")
    plt.show()


if __name__ == "__main__":
    # load csv
    df = load_data("log_entries.csv")
    if df is None:
        raise Exception("Failed to load data from CSV.")

    # postprocess log entries
    task_segments, max_tick, task_ids = get_task_segments(df)
    if not task_ids:
        raise Exception("No valid task IDs found in the data.")

    # create plot
    plot_task_schedule(task_segments, task_ids, max_tick, "task_schedule.pdf")
