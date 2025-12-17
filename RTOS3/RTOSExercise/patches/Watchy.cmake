cmake_minimum_required(VERSION 3.5)
idf_component_register(SRCS "src/BLE.cpp" "src/bma.cpp" "src/bma4.c" "src/bma423.c" "src/Display.cpp" "src/WatchyRTC.cpp" "src/Watchy.cpp"
    INCLUDE_DIRS "src"
    REQUIRES arduino app_update WiFiManager NTPClient Arduino_JSON GxEPD2 Adafruit-GFX-Library Adafruit_BusIO DS3232RTC Rtc_Pcf8563 Time)
project(Watchy)