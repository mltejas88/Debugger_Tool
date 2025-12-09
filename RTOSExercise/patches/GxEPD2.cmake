idf_component_register( SRCS "src/GxEPD2_EPD.cpp"
    INCLUDE_DIRS "src" "src/bitmaps" "src/epd" "src/epd3c" "src/it8951" 
    REQUIRES arduino)
project(GxEPD2)