#!/bin/bash
. esp/esp-idf/export.sh
idf.py build && idf.py flash && idf.py monitor