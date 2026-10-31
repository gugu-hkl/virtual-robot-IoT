/* SSD1315/SSD1306-compatible 128x64 I2C OLED, 5x7 ASCII text. */

#include "oled.h"

#include <stdint.h>
#include <string.h>

#include "driver/i2c_master.h"
#include "sdkconfig.h"

#define WIDTH 128
#define HEIGHT 64
#define PAGE_COUNT (HEIGHT / 8)
#define MAX_LINES 6
#define LINE_HEIGHT 10
#define CHAR_WIDTH 6

static i2c_master_dev_handle_t display;
static uint8_t pixels[WIDTH * PAGE_COUNT];

/* Five columns per glyph; bit 0 is the top pixel. */
static const uint8_t digits[10][5] = {
    {0x3E, 0x51, 0x49, 0x45, 0x3E}, {0x00, 0x42, 0x7F, 0x40, 0x00},
    {0x42, 0x61, 0x51, 0x49, 0x46}, {0x21, 0x41, 0x45, 0x4B, 0x31},
    {0x18, 0x14, 0x12, 0x7F, 0x10}, {0x27, 0x45, 0x45, 0x45, 0x39},
    {0x3C, 0x4A, 0x49, 0x49, 0x30}, {0x01, 0x71, 0x09, 0x05, 0x03},
    {0x36, 0x49, 0x49, 0x49, 0x36}, {0x06, 0x49, 0x49, 0x29, 0x1E},
};

static const uint8_t letters[26][5] = {
    {0x7E, 0x11, 0x11, 0x11, 0x7E}, {0x7F, 0x49, 0x49, 0x49, 0x36},
    {0x3E, 0x41, 0x41, 0x41, 0x22}, {0x7F, 0x41, 0x41, 0x22, 0x1C},
    {0x7F, 0x49, 0x49, 0x49, 0x41}, {0x7F, 0x09, 0x09, 0x09, 0x01},
    {0x3E, 0x41, 0x49, 0x49, 0x7A}, {0x7F, 0x08, 0x08, 0x08, 0x7F},
    {0x00, 0x41, 0x7F, 0x41, 0x00}, {0x20, 0x40, 0x41, 0x3F, 0x01},
    {0x7F, 0x08, 0x14, 0x22, 0x41}, {0x7F, 0x40, 0x40, 0x40, 0x40},
    {0x7F, 0x02, 0x0C, 0x02, 0x7F}, {0x7F, 0x04, 0x08, 0x10, 0x7F},
    {0x3E, 0x41, 0x41, 0x41, 0x3E}, {0x7F, 0x09, 0x09, 0x09, 0x06},
    {0x3E, 0x41, 0x51, 0x21, 0x5E}, {0x7F, 0x09, 0x19, 0x29, 0x46},
    {0x46, 0x49, 0x49, 0x49, 0x31}, {0x01, 0x01, 0x7F, 0x01, 0x01},
    {0x3F, 0x40, 0x40, 0x40, 0x3F}, {0x1F, 0x20, 0x40, 0x20, 0x1F},
    {0x3F, 0x40, 0x38, 0x40, 0x3F}, {0x63, 0x14, 0x08, 0x14, 0x63},
    {0x07, 0x08, 0x70, 0x08, 0x07}, {0x61, 0x51, 0x49, 0x45, 0x43},
};

static const uint8_t blank[5] = {0};
static const uint8_t plus[5] = {0x08, 0x08, 0x3E, 0x08, 0x08};
static const uint8_t minus[5] = {0x08, 0x08, 0x08, 0x08, 0x08};
static const uint8_t period[5] = {0x00, 0x60, 0x60, 0x00, 0x00};
static const uint8_t colon[5] = {0x00, 0x36, 0x36, 0x00, 0x00};
static const uint8_t slash[5] = {0x20, 0x10, 0x08, 0x04, 0x02};
static const uint8_t question[5] = {0x02, 0x01, 0x51, 0x09, 0x06};

static const uint8_t *glyph(char c)
{
    if (c >= '0' && c <= '9') return digits[c - '0'];
    if (c >= 'a' && c <= 'z') c -= ('a' - 'A');
    if (c >= 'A' && c <= 'Z') return letters[c - 'A'];
    switch (c) {
        case ' ': return blank;
        case '+': return plus;
        case '-': return minus;
        case '.': return period;
        case ':': return colon;
        case '/': return slash;
        default: return question;
    }
}

static void draw_char(int x, int y, char c)
{
    const uint8_t *columns = glyph(c);
    for (int col = 0; col < 5; ++col) {
        for (int row = 0; row < 7; ++row) {
            if ((columns[col] & (1U << row)) != 0) {
                int px = x + col;
                int py = y + row;
                if (px >= 0 && px < WIDTH && py >= 0 && py < HEIGHT) {
                    pixels[(py / 8) * WIDTH + px] |= 1U << (py % 8);
                }
            }
        }
    }
}

esp_err_t oled_init(void)
{
    i2c_master_bus_config_t bus_config = {
        .i2c_port = I2C_NUM_0,
        .sda_io_num = CONFIG_ROBOT_OLED_SDA_GPIO,
        .scl_io_num = CONFIG_ROBOT_OLED_SCL_GPIO,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,
    };
    i2c_master_bus_handle_t bus;
    esp_err_t err = i2c_new_master_bus(&bus_config, &bus);
    if (err != ESP_OK) return err;

    i2c_device_config_t device_config = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = CONFIG_ROBOT_OLED_I2C_ADDRESS,
        .scl_speed_hz = 100000,
    };
    err = i2c_master_bus_add_device(bus, &device_config, &display);
    if (err != ESP_OK) return err;

    const uint8_t commands[] = {
        0x00, 0xAE, 0xD5, 0x80, 0xA8, 0x3F, 0xD3, 0x00,
        0x40, 0x8D, 0x14, 0x20, 0x02, 0xA1, 0xC8,
        0xDA, 0x12, 0x81, 0x7F, 0xD9, 0xF1, 0xDB,
        0x40, 0xA4, 0xA6, 0x2E, 0xAF,
    };
    err = i2c_master_transmit(display, commands, sizeof(commands), 1000);
    if (err != ESP_OK) return err;

    const char *lines[] = {"ROBOT DISPLAY", "STARTING"};
    return oled_render(lines, 2);
}

esp_err_t oled_render(const char *const *lines, size_t line_count)
{
    if (display == NULL) return ESP_ERR_INVALID_STATE;
    memset(pixels, 0, sizeof(pixels));
    if (line_count > MAX_LINES) line_count = MAX_LINES;

    for (size_t line = 0; line < line_count; ++line) {
        if (lines[line] == NULL) continue;
        for (size_t col = 0; lines[line][col] != '\0' && col < WIDTH / CHAR_WIDTH; ++col) {
            draw_char((int)(col * CHAR_WIDTH), (int)(line * LINE_HEIGHT), lines[line][col]);
        }
    }

    uint8_t frame[WIDTH + 1];
    frame[0] = 0x40;
    for (uint8_t page = 0; page < PAGE_COUNT; ++page) {
        uint8_t address[] = {0x00, (uint8_t)(0xB0 | page), 0x00, 0x10};
        esp_err_t err = i2c_master_transmit(display, address, sizeof(address), 1000);
        if (err != ESP_OK) return err;
        memcpy(&frame[1], &pixels[page * WIDTH], WIDTH);
        err = i2c_master_transmit(display, frame, sizeof(frame), 1000);
        if (err != ESP_OK) return err;
    }
    return ESP_OK;
}
