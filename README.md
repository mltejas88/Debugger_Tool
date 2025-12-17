# RTOS Project

## Team Member Information

- **Name:** Tejas Mysore Lakshmikanth  
  **Matriculation Number:** 269243

- **Name:** Pavan Shetty  
  **Matriculation Number:** 266318

---

## Changes Made

### 1. Main Folder
- Added `trace.c` and `trace.h`
- Updated `main.cpp`
- Updated `CMakeLists.txt`

### 2. Path: `freertos/config/include/freertos`
- Added `freertos_trace_macros.h`
- Added `trace_events.h`
- Updated `FreeRTOSConfig.h`

### 3. Path: `FreeRTOS-Kernel/include/freertos`
- Updated `tasks.c` and `FreeRTOS.h`
- Modified `traceTASK_DELAY()` to `traceTASK_DELAY(xTicksToDelay)`

---

## Storage and Visualization

### Step 1: Build, Flash, and Log Data
From the root project directory (`RTOS`), execute:
```bash
./run.sh
```
This script:
- Builds the project
- Flashes it to the device
- Monitors serial output
- Stores logs and parses them into a CSV file

### Step 2: Visualize Data
Run the following command to visualize the generated CSV file:
```bash
python3 visualize_pro.py log_entries.csv
```

---

## Notes
- Ensure ESP-IDF is correctly installed and sourced before running the scripts.
- Python 3 is required for visualization.
