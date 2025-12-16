/* trace.c - Compact trace system for ESP32
 * Double-buffered ring buffer with overwrite minimization
 */

#include "trace.h"
#include <stdio.h>

/* Buffer size */
#define TRACE_BUFFER_SIZE 768

/* High watermark to trigger early flush (75%) */
#define TRACE_HIGH_WATERMARK (TRACE_BUFFER_SIZE * 3 / 4)

/* Trace entry */
typedef struct {
    uint32_t     tick;
    uint32_t     time_us;
    void*        object;
    uint32_t     value;
    TraceEvent   event;
    uint8_t      from_isr;
    TaskHandle_t task;
} __attribute__((packed)) trace_entry_t;

/* Ring buffer container */
typedef struct {
    trace_entry_t buffer[TRACE_BUFFER_SIZE];
    uint32_t wr_idx;
    uint32_t count;
    uint32_t overwrite_count;
} trace_ring_t;

/* Two buffers */
static trace_ring_t rings[2];
static volatile uint8_t active_ring = 0;

/* Global stats */
static volatile uint32_t total_written = 0;
static volatile uint32_t flush_count = 0;

/* Flush signaling */
static volatile uint8_t flush_requested = 0;

/* Flush task handle */
static TaskHandle_t flush_task = NULL;

/* Timestamp helper */
static inline uint32_t get_us(void) {
    return (uint32_t)((uint64_t)xTaskGetTickCount() * 1000000ULL /
                      (uint64_t)configTICK_RATE_HZ);
}

/* Init */
void trace_init(void) {
    taskENTER_CRITICAL(NULL);
    for (int i = 0; i < 2; i++) {
        rings[i].wr_idx = 0;
        rings[i].count = 0;
        rings[i].overwrite_count = 0;
    }
    active_ring = 0;
    total_written = 0;
    flush_count = 0;
    flush_requested = 0;
    flush_task = NULL;
    taskEXIT_CRITICAL(NULL);
}

/* Record from task */
void trace_record_task(TraceEvent event, void *object, int value) {
    TaskHandle_t current = xTaskGetCurrentTaskHandle();
    if (current == flush_task) return;

    taskENTER_CRITICAL(NULL);

    trace_ring_t *r = &rings[active_ring];
    uint32_t idx = r->wr_idx;

    r->buffer[idx].tick = xTaskGetTickCount();
    r->buffer[idx].time_us = get_us();
    r->buffer[idx].object = object;
    r->buffer[idx].value = (uint32_t)value;
    r->buffer[idx].event = event;
    r->buffer[idx].from_isr = 0;
    r->buffer[idx].task = current;

    r->wr_idx = (idx + 1) % TRACE_BUFFER_SIZE;

    if (r->count < TRACE_BUFFER_SIZE) {
        r->count++;
        if (r->count >= TRACE_HIGH_WATERMARK) {
            flush_requested = 1;
        }
    } else {
        r->overwrite_count++;
    }

    total_written++;
    taskEXIT_CRITICAL(NULL);
}

/* Record from ISR */
void trace_record_isr(TraceEvent event, void *object, int value) {
#ifdef portSET_INTERRUPT_MASK_FROM_ISR
    UBaseType_t mask = portSET_INTERRUPT_MASK_FROM_ISR();
#else
    UBaseType_t flags = taskENTER_CRITICAL_FROM_ISR();
#endif

    trace_ring_t *r = &rings[active_ring];
    uint32_t idx = r->wr_idx;

#ifdef xTaskGetTickCountFromISR
    r->buffer[idx].tick = xTaskGetTickCountFromISR();
#else
    r->buffer[idx].tick = xTaskGetTickCount();
#endif
    r->buffer[idx].time_us = get_us();
    r->buffer[idx].object = object;
    r->buffer[idx].value = (uint32_t)value;
    r->buffer[idx].event = event;
    r->buffer[idx].from_isr = 1;
    r->buffer[idx].task = NULL;

    r->wr_idx = (idx + 1) % TRACE_BUFFER_SIZE;

    if (r->count < TRACE_BUFFER_SIZE) {
        r->count++;
        if (r->count >= TRACE_HIGH_WATERMARK) {
            flush_requested = 1;
        }
    } else {
        r->overwrite_count++;
    }

    total_written++;

#ifdef portSET_INTERRUPT_MASK_FROM_ISR
    portCLEAR_INTERRUPT_MASK_FROM_ISR(mask);
#else
    taskEXIT_CRITICAL_FROM_ISR(flags);
#endif
}

static const char* evt2str(TraceEvent e) {
    switch (e) {
        case EVT_QUEUE_SEND: return "EVT_QUEUE_SEND";
        case EVT_QUEUE_SEND_FAILED: return "EVT_QUEUE_SEND_FAILED";
        case EVT_QUEUE_SEND_FROM_ISR: return "EVT_QUEUE_SEND_FROM_ISR";
        case EVT_QUEUE_SEND_FROM_ISR_FAILED: return "EVT_QUEUE_SEND_FROM_ISR_FAILED";
        case EVT_QUEUE_RECEIVE: return "EVT_QUEUE_RECEIVE";
        case EVT_QUEUE_RECEIVE_FAILED: return "EVT_QUEUE_RECEIVE_FAILED";
        case EVT_QUEUE_RECEIVE_FROM_ISR: return "EVT_QUEUE_RECEIVE_FROM_ISR";
        case EVT_QUEUE_RECEIVE_FROM_ISR_FAILED: return "EVT_QUEUE_RECEIVE_FROM_ISR_FAILED";
        case EVT_TASK_INCREMENT_TICK: return "EVT_TASK_INCREMENT_TICK";
        case EVT_TASK_CREATE: return "EVT_TASK_CREATE";
        case EVT_TASK_CREATE_FAILED: return "EVT_TASK_CREATE_FAILED";
        case EVT_TASK_DELETE: return "EVT_TASK_DELETE";
        case EVT_TASK_DELAY: return "EVT_TASK_DELAY";
        case EVT_TASK_DELAY_UNTIL: return "EVT_TASK_DELAY_UNTIL";
        case EVT_TASK_SWITCHED_IN: return "traceTASK_SWITCHED_IN";
        case EVT_TASK_SWITCHED_OUT: return "traceTASK_SWITCHED_OUT";
        default: return "UNKNOWN";
    }
}


/* Flush with chaining */
void trace_flush(void) {
    static trace_entry_t snap[TRACE_BUFFER_SIZE];

    for (;;) {
        uint8_t flush_ring;
        uint32_t n, start;
        uint32_t total, overwrites, flushes;

        taskENTER_CRITICAL(NULL);
        flush_ring = active_ring;
        active_ring ^= 1;

        trace_ring_t *r = &rings[flush_ring];

        n = r->count;
        overwrites = r->overwrite_count;
        total = total_written;
        flush_count++;
        flushes = flush_count;

        if (n > 0) {
            start = (r->wr_idx >= n) ?
                    (r->wr_idx - n) :
                    (TRACE_BUFFER_SIZE + r->wr_idx - n);

            for (uint32_t i = 0; i < n; i++) {
                snap[i] = r->buffer[(start + i) % TRACE_BUFFER_SIZE];
            }
        }

        r->count = 0;
        r->wr_idx = 0;
        r->overwrite_count = 0;

        taskEXIT_CRITICAL(NULL);

        if (n == 0) break;

        printf("# ========================================\n");
        printf("# TRACE STATISTICS (Flush #%lu)\n", (unsigned long)flushes);
        printf("# Total events recorded: %lu\n", (unsigned long)total);
        printf("# Buffer overwrites: %lu\n", (unsigned long)overwrites);
        printf("# Entries in this dump: %lu\n", (unsigned long)n);
        printf("# Buffer utilization: %lu/%d (%.1f%%)\n",
               (unsigned long)n, TRACE_BUFFER_SIZE,
               (100.0f * n) / TRACE_BUFFER_SIZE);
        printf("# ========================================\n");

        printf("eventtype,tick,timestamp,taskid,object,value,src\n");

        for (uint32_t i = 0; i < n; i++) {
            trace_entry_t *e = &snap[i];

            /* For TASK CREATE / DELETE, object is a task name (char*) */
            if (e->event == EVT_TASK_CREATE ||
            e->event == EVT_TASK_DELETE ||
            e->event == EVT_TASK_CREATE_FAILED) {

                printf("%s,%lu,%lu,%s,%s,%lu,%s\n",
               evt2str(e->event),
               (unsigned long)e->tick,
               (unsigned long)e->time_us,
               e->task ? pcTaskGetName(e->task) : "ISR",
               e->object ? (const char*)e->object : "",
               (unsigned long)e->value,
               e->from_isr ? "ISR" : "TASK");
            }
            /* All other events: object is a pointer */
            else {
                printf("%s,%lu,%lu,%s,%p,%lu,%s\n",
               evt2str(e->event),
               (unsigned long)e->tick,
               (unsigned long)e->time_us,
               e->task ? pcTaskGetName(e->task) : "ISR",
               e->object,
               (unsigned long)e->value,
               e->from_isr ? "ISR" : "TASK");
            }
        }

        printf("# ========================================\n\n");

        /* Check if the other buffer filled while we were flushing */
        taskENTER_CRITICAL(NULL);
        uint32_t pending = rings[active_ring].count;
        flush_requested = 0;
        taskEXIT_CRITICAL(NULL);

        if (pending == 0) {
            break;  // nothing more to flush
        }
    }
}

/* Helpers */
void trace_force_flush(void) { trace_flush(); }
void trace_set_flush_task(TaskHandle_t t) { flush_task = t; }

void trace_get_stats(uint32_t *total, uint32_t *overwrites, uint32_t *entries) {
    taskENTER_CRITICAL(NULL);
    if (total) *total = total_written;
    if (overwrites)
        *overwrites = rings[0].overwrite_count + rings[1].overwrite_count;
    if (entries)
        *entries = rings[0].count + rings[1].count;
    taskEXIT_CRITICAL(NULL);
}
