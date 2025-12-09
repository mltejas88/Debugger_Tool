#ifndef FREERTOS_TRACE_MACROS_H
#define FREERTOS_TRACE_MACROS_H

#include "trace_events.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Minimal prototypes so the compiler sees the functions (no implicit decl). 
 * Use TraceEvent as declared in trace_events.h.
 * These are *not* definitions; implementations must be provided in the trace component.
 */
void trace_record_task(TraceEvent event, void *object, int value);
void trace_record_isr(TraceEvent event, void *object, int value);

#ifdef __cplusplus
}
#endif

/* ---------------- Queue tracing (task) ---------------- */
#define traceQUEUE_SEND(pxQueue) \
    trace_record_task(EVT_QUEUE_SEND, (void*)(pxQueue), 0)
#define traceQUEUE_SEND_FAILED(pxQueue) \
    trace_record_task(EVT_QUEUE_SEND_FAILED, (void*)(pxQueue), 0)

#define traceQUEUE_RECEIVE(pxQueue) \
    trace_record_task(EVT_QUEUE_RECEIVE, (void*)(pxQueue), 0)
#define traceQUEUE_RECEIVE_FAILED(pxQueue) \
    trace_record_task(EVT_QUEUE_RECEIVE_FAILED, (void*)(pxQueue), 0)

/* ---------------- Queue tracing (ISR) ---------------- */
#define traceQUEUE_SEND_FROM_ISR(pxQueue) \
    trace_record_isr(EVT_QUEUE_SEND_FROM_ISR, (void*)(pxQueue), 0)
#define traceQUEUE_SEND_FROM_ISR_FAILED(pxQueue) \
    trace_record_isr(EVT_QUEUE_SEND_FROM_ISR_FAILED, (void*)(pxQueue), 0)

#define traceQUEUE_RECEIVE_FROM_ISR(pxQueue) \
    trace_record_isr(EVT_QUEUE_RECEIVE_FROM_ISR, (void*)(pxQueue), 0)
#define traceQUEUE_RECEIVE_FROM_ISR_FAILED(pxQueue) \
    trace_record_isr(EVT_QUEUE_RECEIVE_FROM_ISR_FAILED, (void*)(pxQueue), 0)

/* ---------------- Housekeeping ---------------- 
#define traceTASK_INCREMENT_TICK(xTickCount) \
    trace_record_task(EVT_TASK_INCREMENT_TICK, NULL, (int)((xTickCount) + 1)) */

#define traceTASK_CREATE(pxNewTCB) \
    trace_record_task(EVT_TASK_CREATE, (void*)(pxNewTCB), 0)
#define traceTASK_CREATE_FAILED() \
    trace_record_task(EVT_TASK_CREATE_FAILED, NULL, 0)
#define traceTASK_DELETE(pxTaskToDelete) \
    trace_record_task(EVT_TASK_DELETE, (void*)(pxTaskToDelete), 0)

#define traceTASK_DELAY(ticksToDelay) \
    trace_record_task(EVT_TASK_DELAY, NULL, (int)(ticksToDelay))
#define traceTASK_DELAY_UNTIL(pxPreviousWakeTime) \
    trace_record_task(EVT_TASK_DELAY_UNTIL, NULL, (int)(pxPreviousWakeTime))

/* ---------------- Job execution / scheduling ---------------- */
#define traceTASK_SWITCHED_IN() \
    trace_record_task(EVT_TASK_SWITCHED_IN, NULL, 0)
#define traceTASK_SWITCHED_OUT() \
    trace_record_task(EVT_TASK_SWITCHED_OUT, NULL, 0) 

#endif /* FREERTOS_TRACE_MACROS_H */
