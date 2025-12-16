#!/usr/bin/env python3
"""
parse_selected_events.py

Parse raw_log.txt and write only selected event types to CSV

Usage:
    python3 parse_selected_events.py raw_log.txt log_entries.csv
"""

import sys
import csv
import re
from typing import Optional

# ---------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------

FILTER_TASKIDS = {
    "flush",
}

# ---------------------------------------------------------------------
# Allowed events and normalization mapping
# ---------------------------------------------------------------------

EVENT_MAP = {
    'EVT_QUEUE_SEND': 'EVT_QUEUE_SEND',
    'EVT_QUEUE_SEND_FAILED': 'EVT_QUEUE_SEND_FAILED',
    'EVT_QUEUE_SEND_FROM_ISR': 'EVT_QUEUE_SEND_FROM_ISR',
    'EVT_QUEUE_SEND_FROM_ISR_FAILED': 'EVT_QUEUE_SEND_FROM_ISR_FAILED',
    'EVT_QUEUE_RECEIVE': 'EVT_QUEUE_RECEIVE',
    'EVT_QUEUE_RECEIVE_FAILED': 'EVT_QUEUE_RECEIVE_FAILED',
    'EVT_QUEUE_RECEIVE_FROM_ISR': 'EVT_QUEUE_RECEIVE_FROM_ISR',
    'EVT_QUEUE_RECEIVE_FROM_ISR_FAILED': 'EVT_QUEUE_RECEIVE_FROM_ISR_FAILED',
    'EVT_TASK_INCREMENT_TICK': 'EVT_TASK_INCREMENT_TICK',
    'EVT_TASK_CREATE': 'EVT_TASK_CREATE',
    'EVT_TASK_CREATE_FAILED': 'EVT_TASK_CREATE_FAILED',
    'EVT_TASK_DELETE': 'EVT_TASK_DELETE',
    'EVT_TASK_DELAY': 'EVT_TASK_DELAY',
    'EVT_TASK_DELAY_UNTIL': 'EVT_TASK_DELAY_UNTIL',
    'EVT_TASK_SWITCHED_IN': 'traceTASK_SWITCHED_IN',
    'EVT_TASK_SWITCHED_OUT': 'traceTASK_SWITCHED_OUT',
    'traceTASK_SWITCHED_IN': 'traceTASK_SWITCHED_IN',
    'traceTASK_SWITCHED_OUT': 'traceTASK_SWITCHED_OUT',
}

# ---------------------------------------------------------------------
# Regex helpers
# ---------------------------------------------------------------------

CSV_LIKE_RE = re.compile(
    r'^\s*([^,]+),\s*([^,]+),\s*([^,]*),\s*([^,]*),\s*([^,]*),\s*([^,]*),\s*(.*)\s*$'
)

KV_PAIR_RE = re.compile(r'(\b[a-zA-Z_]+)\s*[:=]\s*([^\s,\]\[]+)')

EVENT_KEY_RE = re.compile(
    r'\b(' + '|'.join(re.escape(k) for k in EVENT_MAP.keys()) + r')\b'
)

BRACKET_TICK_RE = re.compile(r'\[?\s*tick[:=]?\s*(\d+)\s*\]?')
FIRST_INT_RE = re.compile(r'\b(\d{1,10})\b')

CSV_FIELDS = [
    'eventtype',
    'tick',
    'timestamp',
    'taskid',
    'object',
    'value',
    'src',
]

# ---------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------

def extract_from_csv_like(line: str) -> Optional[dict]:
    m = CSV_LIKE_RE.match(line)
    if not m:
        return None
    eventtype_raw, tick, timestamp, taskid, obj, value, src = m.groups()
    return {
        'eventtype_raw': eventtype_raw.strip(),
        'tick': tick.strip(),
        'timestamp': timestamp.strip(),
        'taskid': taskid.strip(),
        'object': obj.strip(),
        'value': value.strip(),
        'src': src.strip(),
    }

def extract_kv(line: str) -> dict:
    return dict(KV_PAIR_RE.findall(line))

def find_event_key(line: str) -> Optional[str]:
    m = EVENT_KEY_RE.search(line)
    return m.group(1) if m else None

def best_effort_tick(line: str, kv: dict) -> str:
    if 'tick' in kv and kv['tick'].isdigit():
        return kv['tick']
    m = BRACKET_TICK_RE.search(line)
    if m:
        return m.group(1)
    m2 = FIRST_INT_RE.search(line)
    if m2:
        return m2.group(1)
    return ''

def best_effort_taskid(line: str, kv: dict) -> str:
    for k in ('taskid', 'task', 'task_name'):
        if k in kv:
            return kv[k]
    tokens = re.findall(r'\b[A-Za-z0-9_]+\b', line)
    tokens = [t for t in tokens if not t.isdigit()]
    event = find_event_key(line)
    if event and tokens and tokens[0] == event:
        tokens = tokens[1:]
    return tokens[-1] if tokens else ''

def normalize_eventname(raw: str) -> Optional[str]:
    if not raw:
        return None
    raw = raw.strip()
    return EVENT_MAP.get(raw)

# ---------------------------------------------------------------------
# Line parser
# ---------------------------------------------------------------------

def parse_line(line: str) -> Optional[dict]:
    parsed = extract_from_csv_like(line)
    if parsed:
        raw_event = parsed['eventtype_raw']
        norm = normalize_eventname(raw_event)
        if not norm:
            found = find_event_key(line)
            norm = normalize_eventname(found) if found else None
        if not norm:
            return None

        kv = extract_kv(line)
        return {
            'eventtype': norm,
            'tick': parsed['tick'] or best_effort_tick(line, kv),
            'timestamp': parsed['timestamp'],
            'taskid': parsed['taskid'] or best_effort_taskid(line, kv),
            'object': parsed['object'],
            'value': parsed['value'],
            'src': parsed['src'],
        }

    found = find_event_key(line)
    if not found:
        return None

    norm = normalize_eventname(found)
    if not norm:
        return None

    kv = extract_kv(line)
    return {
        'eventtype': norm,
        'tick': best_effort_tick(line, kv),
        'timestamp': kv.get('timestamp', ''),
        'taskid': best_effort_taskid(line, kv),
        'object': kv.get('object', ''),
        'value': kv.get('value', ''),
        'src': kv.get('src', ''),
    }

# ---------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------

def normalize_row(row: dict) -> dict:
    try:
        row['tick'] = int(row['tick']) if row['tick'] != '' else ''
    except Exception:
        row['tick'] = ''
    for k in ('eventtype', 'timestamp', 'taskid', 'object', 'value', 'src'):
        if isinstance(row.get(k), str):
            row[k] = row[k].strip()
    return row

# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def main(infile: str, outfile: str):
    with open(infile, 'r', encoding='utf-8', errors='ignore') as fin, \
         open(outfile, 'w', newline='', encoding='utf-8') as fout:

        writer = csv.DictWriter(fout, fieldnames=CSV_FIELDS)
        writer.writeheader()

        for ln in fin:
            if not ln.strip():
                continue

            row = parse_line(ln)
            if row is None:
                continue

            row = normalize_row(row)

            task = row.get('taskid', '').lower()
            if task in FILTER_TASKIDS:
                continue

            writer.writerow(row)

    print(f"Wrote filtered events to {outfile}")

# ---------------------------------------------------------------------

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: python3 parse_selected_events.py raw_log.txt log_entries.csv")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
