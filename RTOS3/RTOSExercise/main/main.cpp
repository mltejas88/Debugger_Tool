#include <Arduino.h>
#include <Display.h>
#include <Fonts/FreeMonoBold24pt7b.h>
#include <GxEPD2_BW.h>
#include <esp_log.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <stdio.h>
#include <Watchy.h>
#include <driver/gpio.h>

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

/* ============================
 * GPIO BUTTON ISR
 * ============================ */
static void IRAM_ATTR button_isr(void *arg)
{
    uint32_t gpio_num = (uint32_t)arg;
    BaseType_t xHigherPriorityTaskWoken = pdFALSE;

    static uint32_t last_tick = 0;
    uint32_t now = xTaskGetTickCountFromISR();

    // Simple debounce (200 ms)
    if ((now - last_tick) < pdMS_TO_TICKS(200)) {
        return;
    }
    last_tick = now;

    char msg[MSG_LEN];
    snprintf(msg, MSG_LEN,
             "ISR: Button GPIO %lu at tick %lu",
             gpio_num,
             (unsigned long)now);

    // Queue send FROM ISR (triggers traceQUEUE_SEND_FROM_ISR)
    if (xQueueSendFromISR(queue, msg, &xHigherPriorityTaskWoken) != pdPASS) {
        // Queue full → traceQUEUE_SEND_FROM_ISR_FAILED
    }

    if (xHigherPriorityTaskWoken) {
        portYIELD_FROM_ISR();
    }
}

/* ============================
 * EXISTING TASKS (UNCHANGED)
 * ============================ */

void initDisplay(void* pvParameters) {
    ESP_LOGI("initDisplay", "initializing display");

    pinMode(DISPLAY_CS, OUTPUT);
    pinMode(DISPLAY_RES, OUTPUT);
    pinMode(DISPLAY_DC, OUTPUT);
    pinMode(DISPLAY_BUSY, OUTPUT);
    pinMode(BOTTOM_LEFT, INPUT);
    pinMode(BOTTOM_RIGHT, INPUT);
    pinMode(TOP_LEFT, INPUT);
    pinMode(TOP_RIGHT, INPUT);

    display.epd2.initWatchy();
    display.setFullWindow();
    display.fillScreen(GxEPD_WHITE);
    display.setTextColor(GxEPD_BLACK);
    display.setFont(&FreeMonoBold24pt7b);
    display.setCursor(0, 90);
    display.print("RTOS!");
    display.display(false);

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

void Car(void *pvParameters) {
    TickType_t xlastWakeTime = xTaskGetTickCount();
    char msg[MSG_LEN];

    for (;;) {
        snprintf(msg, MSG_LEN, "Item 2 produced at tick %u",
                 (unsigned)xTaskGetTickCount());

        if (xQueueSend(queue, msg, 0) != pdPASS) {
            ESP_LOGI("Producer2", "queue full, drop message");
        }

        vTaskDelayUntil(&xlastWakeTime, pdMS_TO_TICKS(200));
    }
}

void Bike(void *pvParameters) {
    TickType_t xlastWakeTime = xTaskGetTickCount();
    char msg[MSG_LEN];

    for (;;) {
        snprintf(msg, MSG_LEN, "Item 3 produced at tick %u",
                 (unsigned)xTaskGetTickCount());

        if (xQueueSend(queue, msg, 0) != pdPASS) {
            ESP_LOGI("Producer3", "queue full, drop message");
        }

        vTaskDelayUntil(&xlastWakeTime, pdMS_TO_TICKS(300));
    }
}

void sharedPrinter(void *pvParameters) {
    char recv[MSG_LEN];

    for (;;) {
        if (xQueueReceive(queue, recv, portMAX_DELAY) == pdPASS) {
            ESP_LOGI("sharedPrinter", "Printing: %s", recv);
        }
    }
}

void flushTask(void *pvParameters) {
    trace_set_flush_task(xTaskGetCurrentTaskHandle());
    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(500));
        ESP_LOGI("Flush", "=== TRACE DUMP START ===");
        trace_flush();
        ESP_LOGI("Flush", "=== TRACE DUMP END ===");
    }
}

void taskKiller(void *pvParameters)
{
    vTaskDelay(pdMS_TO_TICKS(10000));
    ESP_LOGI("Killer", "Stopping tasks...");
    vTaskDelete(h2);
    vTaskDelete(h3);
    vTaskDelete(hPrinter);
    ESP_LOGI("Killer", "All tasks terminated");
    vTaskDelete(NULL);
}

/* ============================
 * app_main
 * ============================ */
extern "C" void app_main() {

    trace_init();
    ESP_LOGI("app_main", "Trace system initialized");

    queue = xQueueCreate(500, MSG_LEN);
    if (queue == NULL) {
        ESP_LOGI("app_main", "Failed to create queue");
        abort();
    }

    /* ---- GPIO INTERRUPT SETUP ---- */
    gpio_config_t io_conf = {
        .pin_bit_mask =
            (1ULL << BOTTOM_LEFT)  |
            (1ULL << BOTTOM_RIGHT) |
            (1ULL << TOP_LEFT),
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_NEGEDGE
    };
    gpio_config(&io_conf);

    gpio_install_isr_service(ESP_INTR_FLAG_IRAM);

    gpio_isr_handler_add((gpio_num_t)BOTTOM_LEFT,  button_isr, (void*)BOTTOM_LEFT);
    gpio_isr_handler_add((gpio_num_t)BOTTOM_RIGHT, button_isr, (void*)BOTTOM_RIGHT);
    gpio_isr_handler_add((gpio_num_t)TOP_LEFT,     button_isr, (void*)TOP_LEFT);


    ESP_LOGI("app_main", "Button ISRs installed");

   
    xTaskCreate(taskKiller, "Killer", 4096, NULL, 5, NULL);
    xTaskCreate(flushTask, "Flush", 8192, NULL, 1, &hFlush);
    xTaskCreate(Car, "Car", 4096, NULL, 2, &h2);
    xTaskCreate(Bike, "Bike", 4096, NULL, 2, &h3);
    xTaskCreate(sharedPrinter, "Printer", 4096, NULL, 3, &hPrinter);

    ESP_LOGI("app_main", "Starting scheduler");
    vTaskStartScheduler();

    ESP_LOGE("app_main", "Scheduler failed");
    abort();
}
