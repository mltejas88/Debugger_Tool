# Debugger_Tool
Project: Build Your Own Debug Tool

# Project Overview
- Refer the project.pdf file for the details.
- Additionally for visualization purpose visualize.py is provide and respective requirement.txt file.

- The esp-idf environment can then be activated by calling: source ./esp/esp-idf/export.sh

- For build : idf.py build
- For Flash idf.py flash
- For monitor : idf.py monitor
- Combined command : idf.py build flash monitor

- For the updates done to the project : Refer the RTOS_changes.txt

### Storage and visualization:
- Store the serial monitor output to raw_log.txt file using command :  idf.py monitor |  tee  ~/Semester3/RTOS3/raw_log.txt
- Filter out the required trace events in log_entries.csv files using command :  python3 parse_trace_log_updated.py raw_log.txt log_entries.csv
- Visualize the filtered dat using command : python3 visualize_updated.py log_entries.csv output
