idf_component_register(
    SRCS "main.c" "oled.c"
    INCLUDE_DIRS "."
    PRIV_REQUIRES freertos esp_wifi esp_netif esp_event nvs_flash esp_http_client esp_driver_i2c
)
