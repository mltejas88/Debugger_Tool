#!/usr/bin/env python3
"""
parse_selected_events.py

Parse raw_log.txt and write only selected event types to CSV.
Usage:
    python3 parse_selected_events.py raw_log.txt log_entries.csv
"""

import sys
import csv
import re
from typing import Optional

# --- Allowed events and normalization mapping ---
# Map raw event tokens to normalized eventtype to write into CSV.
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
    # sometimes logs may already use traceTASK names
    'traceTASK_SWITCHED_IN': 'traceTASK_SWITCHED_IN',
    'traceTASK_SWITCHED_OUT': 'traceTASK_SWITCHED_OUT',
}

# Precompile regexes
CSV_LIKE_RE = re.compile(
    r'^\s*([^,]+),\s*([^,]+),\s*([^,]*),\s*([^,]*),\s*([^,]*),\s*([^,]*),\s*(.*)\s*$'
)
KV_PAIR_RE = re.compile(r'(\b[a-zA-Z_]+)\s*[:=]\s*([^\s,\]\[]+)')
# find any of the known event keys as a whole word
EVENT_KEY_RE = re.compile(r'\b(' + '|'.join(re.escape(k) for k in EVENT_MAP.keys()) + r')\b')
# bracketed tick like [tick=123] or [123]
BRACKET_TICK_RE = re.compile(r'\[?\s*tick[:=]?\s*(\d+)\s*\]?')
FIRST_INT_RE = re.compile(r'\b(\d{1,10})\b')

CSV_FIELDS = ['eventtype','tick','timestamp','taskid','object','value','src','raw_line']

def extract_from_csv_like(line: str) -> Optional[dict]:
    m = CSV_LIKE_RE.match(line)
    if not m:
        return None
    eventtype_raw, tick, timestamp, taskid, obj, value, src = m.groups()
    eventtype_raw = eventtype_raw.strip()
    return {
        'eventtype_raw': eventtype_raw,
        'tick': tick.strip(),
        'timestamp': timestamp.strip(),
        'taskid': taskid.strip(),
        'object': obj.strip(),
        'value': value.strip(),
        'src': src.strip(),
        'raw_line': line.rstrip('\n')
    }

def extract_kv(line: str) -> dict:
    kv = dict(KV_PAIR_RE.findall(line))
    return kv

def find_event_key(line: str) -> Optional[str]:
    m = EVENT_KEY_RE.search(line)
    if m:
        return m.group(1)
    return None

def best_effort_tick(line: str, kv: dict) -> str:
    # prefer explicit kv tick
    if 'tick' in kv and kv['tick'].isdigit():
        return kv['tick']
    # bracketed tick like [tick=123] or [123]
    m = BRACKET_TICK_RE.search(line)
    if m:
        return m.group(1)
    # fallback: first integer in line
    m2 = FIRST_INT_RE.search(line)
    if m2:
        return m2.group(1)
    return ''

def best_effort_taskid(line: str, kv: dict) -> str:
    # prefer common keys
    for k in ('taskid','task','task_name'):
        if k in kv:
            return kv[k]
    # try "IDLE" or similar tokens after event name
    # find tokens: words of letters/numbers/underscore
    tokens = re.findall(r'\b[A-Za-z0-9_]+\b', line)
    # remove numeric-only tokens
    tokens = [t for t in tokens if not t.isdigit()]
    # skip event token itself if present
    event = find_event_key(line)
    if event and tokens and tokens[0] == event:
        tokens = tokens[1:]
    # return last token (often task name like IDLE)
    if tokens:
        return tokens[-1]
    return ''

def normalize_eventname(raw: str) -> Optional[str]:
    if not raw:
        return None
    # if raw already matches a key in map, return mapped value
    if raw in EVENT_MAP:
        return EVENT_MAP[raw]
    # try uppercase variant
    up = raw.strip()
    if up in EVENT_MAP:
        return EVENT_MAP[up]
    # no mapping
    return None

def parse_line(line: str) -> Optional[dict]:
    # try CSV-like first
    parsed = extract_from_csv_like(line)
    if parsed:
        raw_event = parsed['eventtype_raw']
        norm = normalize_eventname(raw_event)
        if not norm:
            # even if CSV-like, try to detect event in line body
            found = find_event_key(line)
            norm = normalize_eventname(found) if found else None
        if not norm:
            return None  # event not in allowed set
        # ensure tick and taskid
        kv = extract_kv(line)
        tick = parsed['tick'] or best_effort_tick(line, kv)
        taskid = parsed['taskid'] or best_effort_taskid(line, kv)
        return {
            'eventtype': norm,
            'tick': tick,
            'timestamp': parsed['timestamp'],
            'taskid': taskid,
            'object': parsed['object'],
            'value': parsed['value'],
            'src': parsed['src'],
            'raw_line': parsed['raw_line']
        }

    # not CSV-like: try to find event key in arbitrary text
    found = find_event_key(line)
    if not found:
        return None
    norm = normalize_eventname(found)
    if not norm:
        return None

    kv = extract_kv(line)
    tick = best_effort_tick(line, kv)
    taskid = best_effort_taskid(line, kv)
    return {
        'eventtype': norm,
        'tick': tick,
        'timestamp': kv.get('timestamp',''),
        'taskid': taskid,
        'object': kv.get('object',''),
        'value': kv.get('value',''),
        'src': kv.get('src',''),
        'raw_line': line.rstrip('\n')
    }

def normalize_row(row: dict) -> dict:
    # try to make tick an int if possible
    try:
        row['tick'] = int(row['tick']) if row['tick'] != '' else ''
    except Exception:
        row['tick'] = ''
    # strip spaces
    for k in ('eventtype','timestamp','taskid','object','value','src','raw_line'):
        if k in row and isinstance(row[k], str):
            row[k] = row[k].strip()
    return row

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
                continue  # skip lines that don't match selected events
            row = normalize_row(row)
            writer.writerow(row)
    print(f"Wrote filtered events to {outfile}")

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: python3 parse_selected_events.py raw_log.txt log_entries.csv")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])

