#!/usr/bin/env python3
"""
parse_switch_events.py

Extract only traceTASK_SWITCHED_IN / traceTASK_SWITCHED_OUT (and EVT_TASK_SWITCHED_IN/OUT)
from a raw log file and write them to a CSV preserving original order.

Usage:
    python3 parse_switch_events.py raw_log.txt log_entries.csv
"""

import sys
import csv
import re
from typing import Optional

# Map allowed raw tokens to normalized event names
EVENT_MAP = {
    'EVT_TASK_SWITCHED_IN': 'traceTASK_SWITCHED_IN',
    'EVT_TASK_SWITCHED_OUT': 'traceTASK_SWITCHED_OUT',
    'traceTASK_SWITCHED_IN': 'traceTASK_SWITCHED_IN',
    'traceTASK_SWITCHED_OUT': 'traceTASK_SWITCHED_OUT',
    # include possible small variants (case-insensitive matching handled separately)
}

# regexes
EVENT_RE = re.compile(r'\b(EVT_TASK_SWITCHED_IN|EVT_TASK_SWITCHED_OUT|traceTASK_SWITCHED_IN|traceTASK_SWITCHED_OUT)\b', re.IGNORECASE)
KV_RE = re.compile(r'(\b[a-zA-Z_]+)\s*[:=]\s*([^\s,\]\[]+)')   # key=value pairs
BRACKET_TICK_RE = re.compile(r'\[?\s*tick[:=]?\s*(\d+)\s*\]?', re.IGNORECASE)
FIRST_INT_RE = re.compile(r'\b(\d{1,10})\b')
TASK_KW_RE = re.compile(r'\b(taskid|task|task_name)\b', re.IGNORECASE)

CSV_FIELDS = ['eventtype','tick','taskid','timestamp','object','value','src','raw_line']

def find_event(line: str) -> Optional[str]:
    m = EVENT_RE.search(line)
    if not m:
        return None
    raw = m.group(1)
    # normalize key (map uppercase/lowercase)
    raw_up = raw.strip()
    # exact map keys are uppercase; ensure mapping works ignoring case
    for k in EVENT_MAP:
        if raw_up.upper() == k.upper():
            return EVENT_MAP[k]
    # fallback to raw
    return raw_up

def extract_kv(line: str):
    """Return dict of key:value pairs found in line"""
    return {k.lower(): v for k, v in KV_RE.findall(line)}

def best_tick(line: str, kv: dict) -> str:
    # kv already lowercased
    if 'tick' in kv and kv['tick'].isdigit():
        return kv['tick']
    # bracketed tick like [tick=123] or [123]
    m = BRACKET_TICK_RE.search(line)
    if m:
        return m.group(1)
    # first integer fallback (careful: could be timestamp)
    m2 = FIRST_INT_RE.search(line)
    if m2:
        return m2.group(1)
    return ''

def best_taskid(line: str, kv: dict) -> str:
    # prefer keys in kv
    for k in ('taskid', 'task', 'task_name'):
        if k in kv:
            return kv[k]
    # Sometimes task appears right after event token: "traceTASK_SWITCHED_IN 12345 IDLE"
    # Try to capture token(s) after event token
    m = EVENT_RE.search(line)
    if m:
        idx = m.end()
        tail = line[idx:].strip()
        # split tail into tokens
        tokens = re.findall(r'\b[A-Za-z0-9_@/.-]+\b', tail)
        # skip if next token is numeric (likely tick)
        for t in tokens:
            if not t.isdigit():
                return t
    # fallback: last non-numeric token in line
    tokens_all = re.findall(r'\b[A-Za-z0-9_@/.-]+\b', line)
    non_num = [t for t in tokens_all if not t.isdigit()]
    if non_num:
        return non_num[-1]
    return ''

def parse_line(line: str) -> Optional[dict]:
    evt = find_event(line)
    if not evt:
        return None
    kv = extract_kv(line)
    tick = best_tick(line, kv)
    taskid = best_taskid(line, kv)
    # timestamp/object/value/src might be in kv; keep them if present
    return {
        'eventtype': evt,
        'tick': tick,
        'taskid': taskid,
        'timestamp': kv.get('timestamp',''),
        'object': kv.get('object',''),
        'value': kv.get('value',''),
        'src': kv.get('src',''),
        'raw_line': line.rstrip('\n')
    }

def normalize_row(row: dict) -> dict:
    # make tick int if possible
    try:
        row['tick'] = int(row['tick']) if row['tick'] != '' else ''
    except Exception:
        row['tick'] = ''
    # strip strings
    for k in ('eventtype','taskid','timestamp','object','value','src','raw_line'):
        if k in row and isinstance(row[k], str):
            row[k] = row[k].strip()
    return row

def main(infile: str, outfile: str):
    written = 0
    with open(infile, 'r', encoding='utf-8', errors='ignore') as fin, \
         open(outfile, 'w', newline='', encoding='utf-8') as fout:
        writer = csv.DictWriter(fout, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for ln in fin:
            if not ln.strip():
                continue
            rec = parse_line(ln)
            if rec is None:
                continue
            rec = normalize_row(rec)
            writer.writerow(rec)
            written += 1
    print(f"Wrote {written} switch events to {outfile}")

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: python3 parse_switch_events.py raw_log.txt log_entries.csv")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])

