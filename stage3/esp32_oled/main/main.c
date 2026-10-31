/* ESP32 Wi-Fi status terminal for the two Webots robots. */

#include <math.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>

#include "cJSON.h"
#include "esp_event.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/task.h"
#include "nvs_flash.h"
#include "sdkconfig.h"

#include "oled.h"

#define WIFI_CONNECTED_BIT BIT0
#define HTTP_BODY_CAPACITY 1536

static const char *TAG = "robot_oled";
static EventGroupHandle_t wifi_events;
static bool was_connected;

typedef struct {
    char data[HTTP_BODY_CAPACITY];
    size_t length;
    bool overflow;
} http_body_t;

static void show(const char *const *lines, size_t count)
{
    esp_err_t err = oled_render(lines, count);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "OLED update failed: %s", esp_err_to_name(err));
    }
}

static void show_message(const char *title, const char *message, const char *hint)
{
    const char *lines[] = {title, message, hint};
    show(lines, 3);
}

static void wifi_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg;
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        xEventGroupClearBits(wifi_events, WIFI_CONNECTED_BIT);
        ESP_LOGW(TAG, "Wi-Fi disconnected; reconnecting");
        esp_wifi_connect();
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *event = (ip_event_got_ip_t *)data;
        ESP_LOGI(TAG, "ESP32 IP: " IPSTR, IP2STR(&event->ip_info.ip));
        xEventGroupSetBits(wifi_events, WIFI_CONNECTED_BIT);
    }
}

static void wifi_start(void)
{
    wifi_events = xEventGroupCreate();
    ESP_ERROR_CHECK(wifi_events != NULL ? ESP_OK : ESP_ERR_NO_MEM);
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t init_config = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init_config));

    static esp_event_handler_instance_t wifi_handler;
    static esp_event_handler_instance_t ip_handler;
    ESP_ERROR_CHECK(esp_event_handler_instance_register(
        WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event, NULL, &wifi_handler));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(
        IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_event, NULL, &ip_handler));

    wifi_config_t wifi_config = {0};
    memcpy(wifi_config.sta.ssid, CONFIG_ROBOT_WIFI_SSID,
           strlen(CONFIG_ROBOT_WIFI_SSID));
    memcpy(wifi_config.sta.password, CONFIG_ROBOT_WIFI_PASSWORD,
           strlen(CONFIG_ROBOT_WIFI_PASSWORD));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));
}

static esp_err_t http_event(esp_http_client_event_t *event)
{
    if (event->event_id != HTTP_EVENT_ON_DATA) return ESP_OK;
    http_body_t *body = (http_body_t *)event->user_data;
    if (body == NULL || event->data_len < 0 ||
        body->length + (size_t)event->data_len >= sizeof(body->data)) {
        if (body != NULL) body->overflow = true;
        return ESP_FAIL;
    }
    memcpy(body->data + body->length, event->data, (size_t)event->data_len);
    body->length += (size_t)event->data_len;
    body->data[body->length] = '\0';
    return ESP_OK;
}

static bool json_number(const cJSON *object, const char *key, double *out)
{
    const cJSON *item = cJSON_GetObjectItemCaseSensitive(object, key);
    if (!cJSON_IsNumber(item) || !isfinite(item->valuedouble)) return false;
    *out = item->valuedouble;
    return true;
}

static void render_live(const cJSON *root)
{
    const cJSON *selected = cJSON_GetObjectItemCaseSensitive(root, "selected_robot");
    const cJSON *status = cJSON_GetObjectItemCaseSensitive(root, "status");
    const cJSON *status_id = cJSON_GetObjectItemCaseSensitive(status, "robot_id");
    const cJSON *position = cJSON_GetObjectItemCaseSensitive(status, "position_m");
    double x, y, velocity, rotation, age;

    if (!cJSON_IsString(selected) || !cJSON_IsObject(status) ||
        !cJSON_IsString(status_id) ||
        strcmp(selected->valuestring, status_id->valuestring) != 0 ||
        (strcmp(selected->valuestring, "a") != 0 &&
         strcmp(selected->valuestring, "b") != 0) ||
        !cJSON_IsObject(position) ||
        !json_number(position, "x", &x) ||
        !json_number(position, "y", &y) ||
        !json_number(status, "linear_m_s", &velocity) ||
        !json_number(status, "angular_rad_s", &rotation) ||
        !json_number(status, "data_age_s", &age)) {
        show_message("ROBOT DISPLAY", "BAD STATUS", "CHECK API");
        return;
    }

    char line0[24], line1[24], line2[24], line3[24], line4[24], line5[24];
    snprintf(line0, sizeof(line0), "ROBOT %c  ODOM", selected->valuestring[0] - 32);
    snprintf(line1, sizeof(line1), "X %+7.2f M", x);
    snprintf(line2, sizeof(line2), "Y %+7.2f M", y);
    snprintf(line3, sizeof(line3), "V %+7.2f M/S", velocity);
    snprintf(line4, sizeof(line4), "W %+7.2f RAD/S", rotation);
    snprintf(line5, sizeof(line5), "AGE %.1f S", age);
    const char *lines[] = {line0, line1, line2, line3, line4, line5};
    show(lines, 6);
}

static void render_json(const char *body)
{
    cJSON *root = cJSON_Parse(body);
    if (root == NULL) {
        show_message("ROBOT DISPLAY", "BAD JSON", "CHECK API");
        return;
    }
    const cJSON *state = cJSON_GetObjectItemCaseSensitive(root, "state");
    if (cJSON_IsString(state)) {
        if (strcmp(state->valuestring, "waiting") == 0) {
            show_message("ROBOT DISPLAY", "WAIT SELECT", "USE API DOCS");
        } else if (strcmp(state->valuestring, "switching") == 0) {
            show_message("ROBOT DISPLAY", "SWITCHING", "WAIT STATUS");
        } else if (strcmp(state->valuestring, "live") == 0) {
            render_live(root);
        } else {
            show_message("ROBOT DISPLAY", "BAD STATE", "CHECK API");
        }
    } else {
        show_message("ROBOT DISPLAY", "BAD STATE", "CHECK API");
    }
    cJSON_Delete(root);
}

static void render_http_error(int http_status, const char *body)
{
    char code_line[24];
    snprintf(code_line, sizeof(code_line), "HTTP %d", http_status);
    const char *message = "SERVER ERROR";
    cJSON *root = cJSON_Parse(body);
    if (root != NULL) {
        const cJSON *detail = cJSON_GetObjectItemCaseSensitive(root, "detail");
        const cJSON *code = cJSON_GetObjectItemCaseSensitive(detail, "code");
        if (cJSON_IsString(code)) {
            if (strcmp(code->valuestring, "data_stale") == 0) {
                message = "DATA STALE";
            } else if (strcmp(code->valuestring, "backend_unavailable") == 0) {
                message = "ROS OFFLINE";
            } else if (strcmp(code->valuestring, "invalid_status") == 0) {
                message = "BAD STATUS";
            }
        }
        cJSON_Delete(root);
    }
    show_message("ROBOT DISPLAY", message, code_line);
}

static void poll_server(void)
{
    static http_body_t body;
    memset(&body, 0, sizeof(body));
    esp_http_client_config_t config = {
        .url = CONFIG_ROBOT_STATUS_URL,
        .event_handler = http_event,
        .user_data = &body,
        .timeout_ms = 3000,
        .disable_auto_redirect = true,
    };
    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (client == NULL) {
        show_message("ROBOT DISPLAY", "HTTP INIT FAIL", "CHECK CONFIG");
        return;
    }
    esp_http_client_set_header(client, "Accept", "application/json");
    esp_err_t err = esp_http_client_perform(client);
    int http_status = esp_http_client_get_status_code(client);
    esp_http_client_cleanup(client);

    if (err != ESP_OK || body.overflow) {
        ESP_LOGW(TAG, "HTTP request failed: %s", esp_err_to_name(err));
        show_message("ROBOT DISPLAY", "SERVER OFFLINE", "CHECK WIFI/IP");
    } else if (http_status == 200) {
        render_json(body.data);
    } else {
        render_http_error(http_status, body.data);
    }
}

void app_main(void)
{
    ESP_ERROR_CHECK(oled_init());
    if (strlen(CONFIG_ROBOT_WIFI_SSID) == 0 ||
        strlen(CONFIG_ROBOT_WIFI_SSID) > 32 ||
        strlen(CONFIG_ROBOT_WIFI_PASSWORD) > 63 ||
        strncmp(CONFIG_ROBOT_STATUS_URL, "http://", 7) != 0) {
        ESP_LOGE(TAG, "Check Wi-Fi settings and HTTP URL in idf.py menuconfig");
        show_message("ROBOT DISPLAY", "SET CONFIG", "USE MENUCONFIG");
        return;
    }

    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);
    wifi_start();

    while (true) {
        EventBits_t bits = xEventGroupWaitBits(
            wifi_events, WIFI_CONNECTED_BIT, pdFALSE, pdTRUE,
            pdMS_TO_TICKS(1000));
        if ((bits & WIFI_CONNECTED_BIT) == 0) {
            show_message("ROBOT DISPLAY",
                         was_connected ? "WIFI LOST" : "WIFI CONNECT",
                         "WAIT HOTSPOT");
        } else {
            was_connected = true;
            poll_server();
        }
        vTaskDelay(pdMS_TO_TICKS(CONFIG_ROBOT_POLL_MS));
    }
}
