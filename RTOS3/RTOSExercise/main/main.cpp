#include <Arduino.h>
#include <Display.h>
#include <Fonts/FreeMonoBold24pt7b.h>
#include <GxEPD2_BW.h>
#include <esp_log.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <stdio.h>
#include <Watchy.h>

#define TICKS_PER_MS 1000

#define BOTTOM_LEFT 26
#define TOP_LEFT 25
#define BOTTOM_RIGHT 4
#define TOP_RIGHT 35
#define DISPLAY_CS 5
#define DISPLAY_RES 9
#define DISPLAY_DC 10
#define DISPLAY_BUSY 19

#define MSG_LEN 64
static QueueHandle_t queue;
TaskHandle_t h2, h3, hPrinter, hFlush;

GxEPD2_BW<WatchyDisplay, WatchyDisplay::HEIGHT> display(WatchyDisplay{});

extern "C" {
#include "trace.h"
}

void initDisplay(void* pvParameters) {
    ESP_LOGI("initDisplay", "initializing display");

    /* Setting gpio pin types, always necessary at the start. */
    pinMode(DISPLAY_CS, OUTPUT);
    pinMode(DISPLAY_RES, OUTPUT);
    pinMode(DISPLAY_DC, OUTPUT);
    pinMode(DISPLAY_BUSY, OUTPUT);
    pinMode(BOTTOM_LEFT, INPUT);
    pinMode(BOTTOM_RIGHT, INPUT);
    pinMode(TOP_LEFT, INPUT);
    pinMode(TOP_RIGHT, INPUT);

    /* Init the display. */
    display.epd2.initWatchy();
    display.setFullWindow();
    display.fillScreen(GxEPD_WHITE);
    display.setTextColor(GxEPD_BLACK);
    display.setFont(&FreeMonoBold24pt7b);
    display.setCursor(0, 90);
    display.print("RTOS!");
    display.display(false);

    /* Delete the display initialization task. */
    ESP_LOGI("initDisplay", "finished display initialization");
    vTaskDelete(NULL);
}

void buttonWatch(void* pvParameters) {
    unsigned int refresh = 0;
    for (;;) {
        if (digitalRead(BOTTOM_LEFT) == HIGH) {
            ESP_LOGI("buttonWatch", "Bottom Left pressed!");
            display.fillRoundRect(0, 150, 50, 50, 20, GxEPD_BLACK);
            display.display(true);
            vTaskDelay(500);
            display.fillRoundRect(0, 150, 50, 50, 20, GxEPD_WHITE);
            display.display(true);
            refresh++;
        } else if (digitalRead(BOTTOM_RIGHT) == HIGH) {
            ESP_LOGI("buttonWatch", "Bottom Right pressed!");
            display.fillRoundRect(150, 150, 50, 50, 20, GxEPD_BLACK);
            display.display(true);
            vTaskDelay(500);
            display.fillRoundRect(150, 150, 50, 50, 20, GxEPD_WHITE);
            display.display(true);
            refresh++;
        } else if (digitalRead(TOP_LEFT) == HIGH) {
            ESP_LOGI("buttonWatch", "Top Left pressed!");
            display.fillRoundRect(0, 0, 50, 50, 20, GxEPD_BLACK);
            display.display(true);
            vTaskDelay(500);
            display.fillRoundRect(0, 0, 50, 50, 20, GxEPD_WHITE);
            display.display(true);
            refresh++;
        } else if (digitalRead(TOP_RIGHT) == HIGH) {
            ESP_LOGI("buttonWatch", "Top Right pressed!");
            display.fillRoundRect(150, 0, 50, 50, 20, GxEPD_BLACK);
            display.display(true);
            vTaskDelay(500);
            display.fillRoundRect(150, 0, 50, 50, 20, GxEPD_WHITE);
            display.display(true);
            refresh++;
        } else if (refresh >= 10) {
            ESP_LOGI("buttonWatch", "Performing full refresh of display");
            display.display(false);
            refresh = 0;
        }
    }
}

void produceItem1(void *pvParameters) {
    // Produce item 1
    TickType_t xlastWakeTime = xTaskGetTickCount();
    char msg[MSG_LEN];

    for (;;) {
        // Produce an item every 100 ms
        snprintf(msg, MSG_LEN, "Item 1 produced at tick %u", (unsigned)xTaskGetTickCount());

        if (xQueueSend(queue, msg, 0) != pdPASS) {
            ESP_LOGI("Producer1", "queue full, drop message");
        } else {
            ESP_LOGI("Producer1", "Producer1 sent");
        }

        vTaskDelayUntil(&xlastWakeTime, pdMS_TO_TICKS(200));
    }
}

void produceItem2(void *pvParameters) {
    // Produce item 2
    TickType_t xlastWakeTime = xTaskGetTickCount();
    char msg[MSG_LEN];

    for (;;) {
        // Produce an item every 200 ms
        snprintf(msg, MSG_LEN, "Item 2 produced at tick %u", (unsigned)xTaskGetTickCount());

        if (xQueueSend(queue, msg, 0) != pdPASS) {
            ESP_LOGI("Producer2", "queue full, drop message");
        } else {
            ESP_LOGI("Producer2", "Producer2 sent");
        }

        vTaskDelayUntil(&xlastWakeTime, pdMS_TO_TICKS(200));
    }
}

void produceItem3(void *pvParameters) {
    // Produce item 3
    TickType_t xlastWakeTime = xTaskGetTickCount();
    char msg[MSG_LEN];

    for (;;) {
        // Produce an item every 300 ms
        snprintf(msg, MSG_LEN, "Item 3 produced at tick %u", (unsigned)xTaskGetTickCount());

        if (xQueueSend(queue, msg, 0) != pdPASS) {
            ESP_LOGI("Producer3", "queue full, drop message");
        } else {
            ESP_LOGI("Producer3", "Producer3 sent");
        }

        vTaskDelayUntil(&xlastWakeTime, pdMS_TO_TICKS(300));
    }
}

void sharedPrinter(void *pvParameters) {
    char recv[MSG_LEN];

    for (;;) {
        // Block until an item arrives
        if (xQueueReceive(queue, recv, portMAX_DELAY) == pdPASS) {
            // 'recv' now contains a NUL-terminated copy of the message
            ESP_LOGI("sharedPrinter", "Printing: %s", recv);

            // Simulate print duration if needed, e.g.:
            // vTaskDelay(pdMS_TO_TICKS(50));
        } else {
            // Should never reach here with portMAX_DELAY
        }
    }
}

void flushTask(void *pvParameters) {
    // Tell trace system not to trace this task (prevents recursion)
    trace_set_flush_task(xTaskGetCurrentTaskHandle());
    
    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(2000));  // Flush every 5 seconds
        ESP_LOGI("Flush", "=== TRACE DUMP START ===");
        trace_flush();
        ESP_LOGI("Flush", "=== TRACE DUMP END ===");
    }
}

void taskKiller(void *pvParameters)
{
    vTaskDelay(pdMS_TO_TICKS(15000));   // Wait 10 seconds

    ESP_LOGI("Killer", "Stopping tasks...");
    
    //vTaskDelete(h1);
    vTaskDelete(h2);
    vTaskDelete(h3);  // Only if you enable producer3
    vTaskDelete(hPrinter);

    // Final flush before exiting
    //ESP_LOGI("Killer", "Final trace dump...");
    //trace_flush();
    
    ESP_LOGI("Killer", "All tasks terminated");
    vTaskDelete(NULL);
}


extern "C" void app_main() {
    /* Only priorities from 1-25 (configMAX_PRIORITIES) possible. */
    /* Initialize the display first. */
    trace_init();
    ESP_LOGI("app_main", "Trace system initialized");
    //xTaskCreate(initDisplay, "initDisplay", 4096, NULL, configMAX_PRIORITIES-1, NULL);
    //xTaskCreate(buttonWatch, "watch", 8192, NULL, 1, NULL);

    

    queue = xQueueCreate(100, MSG_LEN);


    if (queue == NULL) {
        ESP_LOGI("app_main", "Failed to create queue");
        abort();
    }
    xTaskCreate(taskKiller, "Killer", 4096, NULL, 5, NULL);
    xTaskCreate(flushTask, "Flush", 8192, NULL, 1, &hFlush);
    //xTaskCreate(produceItem1, "Car", 4096, NULL, 2, &h1);
    xTaskCreate(produceItem2, "Bus", 4096, NULL, 2, &h2);
    xTaskCreate(produceItem3, "Cycle", 4096, NULL, 2, &h3);
    xTaskCreate(sharedPrinter, "printer", 4096, NULL, 3, &hPrinter); 

    
    

    ESP_LOGI("app_main", "Starting scheduler from app_main()");
    vTaskStartScheduler();
    /* vTaskStartScheduler is blocking - this should never be reached */
    ESP_LOGE("app_main", "insufficient RAM! aborting");
    abort();
}
