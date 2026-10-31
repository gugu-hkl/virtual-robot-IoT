#pragma once

#include <stddef.h>
#include "esp_err.h"

esp_err_t oled_init(void);
esp_err_t oled_render(const char *const *lines, size_t line_count);
