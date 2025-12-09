
#ifndef TRACE_H
#define TRACE_H

#include "trace_events.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Initialize trace system */
void trace_init(void);

/* Flush trace buffer to stdout with statistics */
void trace_flush(void);

/* Force immediate flush (alias for trace_flush) */
void trace_force_flush(void);

/* Set flush task handle to prevent recursion */
void trace_set_flush_task(TaskHandle_t t);

/* Record trace events - called by FreeRTOS macros */
void trace_record_task(TraceEvent event, void *object, int value);
void trace_record_isr(TraceEvent event, void *object, int value);

/* Get trace statistics (optional - for debugging) */
void trace_get_stats(uint32_t *total, uint32_t *overwrites, uint32_t *entries);

#ifdef __cplusplus
}
#endif

#endif