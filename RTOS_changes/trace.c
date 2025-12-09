/* trace.c - Compact trace system for ESP32
 * Ring buffer with overwrite policy and statistics
 */

#include "trace.h"
#include <stdio.h>

/* Buffer size - adjust based on available RAM */
#define TRACE_BUFFER_SIZE 512

/* Trace entry - compact structure */
typedef struct {
    uint32_t     tick;
    uint32_t     time_us;
    void*        object;
    uint32_t     value;
    TraceEvent   event;
    uint8_t      from_isr;
    TaskHandle_t task;
} __attribute__((packed)) trace_entry_t;

/* Ring buffer */
static trace_entry_t buffer[TRACE_BUFFER_SIZE];
static volatile uint32_t wr_idx = 0;      /* Write index (head) */
static volatile uint32_t count = 0;       /* Current entries in buffer */

/* Statistics */
static volatile uint32_t total_written = 0;    /* Total events recorded */
static volatile uint32_t overwrite_count = 0;  /* Number of overwrites */
static volatile uint32_t flush_count = 0;      /* Number of flushes */

/* Flush task handle for recursion prevention */
static TaskHandle_t flush_task = NULL;
static volatile uint8_t flushing = 0;

/* Get timestamp in microseconds */
static inline uint32_t get_us(void) {
    return (uint32_t)((uint64_t)xTaskGetTickCount() * 1000000ULL / (uint64_t)configTICK_RATE_HZ);
}


/* Initialize */
void trace_init(void) {
    taskENTER_CRITICAL(NULL);
    wr_idx = 0;
    count = 0;
    total_written = 0;
    overwrite_count = 0;
    flush_count = 0;
    flushing = 0;
    flush_task = NULL;
    taskEXIT_CRITICAL(NULL);
}

/* Record from task */
void trace_record_task(TraceEvent event, void *object, int value) {
    TaskHandle_t current = xTaskGetCurrentTaskHandle();
    
    /* Skip if flushing or if we're the flush task */
    if (flushing || current == flush_task) return;

    taskENTER_CRITICAL(NULL);
    
    /* Double-check inside critical section */
    if (flushing) {
        taskEXIT_CRITICAL(NULL);
        return;
    }
    
    uint32_t idx = wr_idx;
    
    buffer[idx].tick = xTaskGetTickCount();
    buffer[idx].time_us = get_us();
    buffer[idx].object = object;
    buffer[idx].value = (uint32_t)value;
    buffer[idx].event = event;
    buffer[idx].from_isr = 0;
    buffer[idx].task = current;
    
    wr_idx = (idx + 1) % TRACE_BUFFER_SIZE;
    
    /* Ring buffer with overwrite policy */
    if (count < TRACE_BUFFER_SIZE) {
        count++;
    } else {
        overwrite_count++;  /* Buffer full, overwriting oldest entry */
    }
    
    total_written++;
    taskEXIT_CRITICAL(NULL);
}

/* Record from ISR */
void trace_record_isr(TraceEvent event, void *object, int value) {
    /* Skip if flushing */
    if (flushing) return;

#ifdef portSET_INTERRUPT_MASK_FROM_ISR
    UBaseType_t mask = portSET_INTERRUPT_MASK_FROM_ISR();
#else
    UBaseType_t flags = taskENTER_CRITICAL_FROM_ISR();
#endif

    /* Double-check inside critical section */
    if (flushing) {
#ifdef portSET_INTERRUPT_MASK_FROM_ISR
        portCLEAR_INTERRUPT_MASK_FROM_ISR(mask);
#else
        taskEXIT_CRITICAL_FROM_ISR(flags);
#endif
        return;
    }

    uint32_t idx = wr_idx;
    
#ifdef xTaskGetTickCountFromISR
    buffer[idx].tick = xTaskGetTickCountFromISR();
#else
    buffer[idx].tick = xTaskGetTickCount();
#endif
    buffer[idx].time_us = get_us();
    buffer[idx].object = object;
    buffer[idx].value = (uint32_t)value;
    buffer[idx].event = event;
    buffer[idx].from_isr = 1;
    buffer[idx].task = NULL;
    
    wr_idx = (idx + 1) % TRACE_BUFFER_SIZE;
    
    /* Ring buffer with overwrite policy */
    if (count < TRACE_BUFFER_SIZE) {
        count++;
    } else {
        overwrite_count++;  /* Buffer full, overwriting oldest entry */
    }
    
    total_written++;

#ifdef portSET_INTERRUPT_MASK_FROM_ISR
    portCLEAR_INTERRUPT_MASK_FROM_ISR(mask);
#else
    taskEXIT_CRITICAL_FROM_ISR(flags);
#endif
}

/* Event to string */
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

/* Flush buffer to stdout */
void trace_flush(void) {
    /* Use static buffer to avoid stack overflow */
    static trace_entry_t snap[TRACE_BUFFER_SIZE];
    uint32_t n = 0, start = 0;
    uint32_t total, overwrites, flushes;

    /* Set flushing flag BEFORE entering critical section */
    flushing = 1;

    /* Atomically copy buffer and statistics */
    taskENTER_CRITICAL(NULL);
    n = count;
    total = total_written;
    overwrites = overwrite_count;
    flush_count++;  /* Increment inside critical section */
    flushes = flush_count;
    
    if (n > 0) {
        /* Calculate start index in ring buffer */
        start = (wr_idx >= n) ? (wr_idx - n) : (TRACE_BUFFER_SIZE + wr_idx - n);
        
        /* Copy entries to snapshot */
        for (uint32_t i = 0; i < n; i++) {
            snap[i] = buffer[(start + i) % TRACE_BUFFER_SIZE];
        }
        
        /* Reset buffer */
        count = 0;
        wr_idx = 0;
    }
    taskEXIT_CRITICAL(NULL);

    if (n == 0) {
        printf("# TRACE: No entries to flush\n");
        flushing = 0;
        return;
    }

    /* Print statistics header */
    printf("# ========================================\n");
    printf("# TRACE STATISTICS (Flush #%lu)\n", (unsigned long)flushes);
    printf("# Total events recorded: %lu\n", (unsigned long)total);
    printf("# Buffer overwrites: %lu\n", (unsigned long)overwrites);
    printf("# Entries in this dump: %lu\n", (unsigned long)n);
    printf("# Buffer utilization: %lu/%d (%.1f%%)\n", 
           (unsigned long)n, TRACE_BUFFER_SIZE, 
           (100.0f * n) / TRACE_BUFFER_SIZE);
    printf("# ========================================\n");

    /* Print CSV header */
    printf("eventtype,tick,timestamp,taskid,object,value,src\n");

    /* Print entries */
    for (uint32_t i = 0; i < n; i++) {
        trace_entry_t *e = &snap[i];
        const char *evt = evt2str(e->event);
        const char *src = e->from_isr ? "ISR" : "TASK";
        const char *task = e->task ? pcTaskGetName(e->task) : "ISR";

        printf("%s,%lu,%lu,%s,%p,%lu,%s\n",
               evt, (unsigned long)e->tick, (unsigned long)e->time_us,
               task, e->object, (unsigned long)e->value, src);
    }
    
    printf("# ========================================\n\n");

    flushing = 0;
}

/* Force flush (alias for trace_flush) */
void trace_force_flush(void) {
    trace_flush();
}

/* Set flush task handle */
void trace_set_flush_task(TaskHandle_t t) {
    flush_task = t;
}

/* Get statistics (optional - useful for debugging) */
void trace_get_stats(uint32_t *total, uint32_t *overwrites, uint32_t *entries) {
    taskENTER_CRITICAL(NULL);
    if (total) *total = total_written;
    if (overwrites) *overwrites = overwrite_count;
    if (entries) *entries = count;
    taskEXIT_CRITICAL(NULL);
}