#ifndef TRACE_EVENTS_H
#define TRACE_EVENTS_H

/* TraceEvent covering all macros/events*/
typedef enum {
    EVT_UNKNOWN = 0,

    /* Queue tracing (traceQUEUE_* macros) */
    EVT_QUEUE_SEND,
    EVT_QUEUE_SEND_FAILED,
    EVT_QUEUE_SEND_FROM_ISR,
    EVT_QUEUE_SEND_FROM_ISR_FAILED,

    EVT_QUEUE_RECEIVE,
    EVT_QUEUE_RECEIVE_FAILED,
    EVT_QUEUE_RECEIVE_FROM_ISR,
    EVT_QUEUE_RECEIVE_FROM_ISR_FAILED,

    /* Housekeeping (traceTASK_* macros) */
    EVT_TASK_INCREMENT_TICK,    /* value = new tick count */

    EVT_TASK_CREATE,
    EVT_TASK_CREATE_FAILED,
    EVT_TASK_DELETE,

    EVT_TASK_DELAY,             /* value = ticksToDelay */
    EVT_TASK_DELAY_UNTIL,       /* value = ticksToWait */

    /* Job execution tracing (context switches) */
    EVT_TASK_SWITCHED_IN,
    EVT_TASK_SWITCHED_OUT,

    /* Internal */
    EVT_TRACE_FLUSH_REQUEST,
    EVT_TRACE_EXPORT_CSV,

    EVT_MAX_EVENT
} TraceEvent;

#endif /* TRACE_EVENTS_H */
