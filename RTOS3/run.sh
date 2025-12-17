#!/usr/bin/env bash
set -e

# Always resolve script location (works from anywhere)
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
ESP_DIR="$ROOT_DIR/RTOSExercise"
LOG_FILE="$ROOT_DIR/raw_log.txt"
CSV_FILE="$ROOT_DIR/log_entries.csv"

echo "Project root: $ROOT_DIR"
echo "ESP project:  $ESP_DIR"

# Go into ESP-IDF project
cd "$ESP_DIR"
source ./esp/esp-idf/export.sh
echo "[1/4] Building project..."
idf.py build

echo "[2/4] Flashing device..."
idf.py flash

echo "[3/4] Monitoring (Ctrl+] to exit)..."
idf.py monitor | tee "$LOG_FILE"

# Go back to RTOS folder
cd "$ROOT_DIR"

echo "Log saved to raw_log.txt"

echo "[4/4] Parsing trace log..."
python3 parse_trace_log.py "$LOG_FILE" "$CSV_FILE"

echo "===================================="
echo "Done."
echo "Log file        : raw_log.txt"
echo "Parsed CSV      : log_entries.csv"
echo "===================================="
