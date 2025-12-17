idf_component_register( SRCS "src/DS3232RTC.cpp"
    INCLUDE_DIRS "src" 
    REQUIRES arduino Time)
project(DS3232RTC)