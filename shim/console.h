#pragma once
#include <stdint.h>

/*
 * Huawei Enjoy 6S (DIG-AL00, MSM8940) continuous splash framebuffer.
 *
 * The live device tree reserves splash_region @ 0x90000000, size 0x1400000
 * (20 MiB). Qualcomm LK stores a 4 KiB splash header at the region base and
 * leaves the RGB888 image at +0x1000 (same layout as the MSM8953 vince port).
 * Panel: FT8607 TCL 720x1280, 24 bpp, stride 720*3 = 2160 bytes.
 */
#define FB_BASE		0x90001000UL
#define FB_W		720
#define FB_H		1280
#define FB_STRIDE	(FB_W * 3)	/* 2160 bytes, RGB888 24-bpp */

#define RED		0x00ff0000U
#define BLUE		0x000000a0U
#define WHITE		0x00ffffffU
#define YELLOW		0x00ffff00U
#define GREEN		0x0000ff00U

extern volatile uint8_t *con_fb;

void con_clear(uint32_t bg);
void con_skip(void);
void con_goto(int row);
void con_str(const char *label, const char *s);
void con_str_color(const char *label, const char *s, uint32_t color);
/* one raw line at column 0, no label column */
void con_raw_line(const char *s);
void con_hex(const char *label, uint64_t v);
/* label, then "a=xxxxxxxx b=xxxxxxxx" style pairs of 32-bit values */
void con_hex2(const char *label, const char *a, uint32_t va, const char *b, uint32_t vb);
