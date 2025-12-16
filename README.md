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
- Step (1) From ROOT folder directory (RTOS) execute bash file as ./run.sh (It builds, flash, monitor, stores the serial output and parse it to write csv file).

- Step (2) Visualize the csv file using command : python3 visualize.py log_entries.csv output.
