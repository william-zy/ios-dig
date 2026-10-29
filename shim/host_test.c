/* Render the shim console layout on the host:
 *   gcc -O1 -I. -o out/host_test console.c host_test.c && ./out/host_test
 * Writes out/host.ppm (720x1280 RGB888), the same bytes the shim paints.
 */
#include <stdio.h>
#include <stdint.h>
#include "console.h"

static uint8_t host_fb[FB_H * FB_STRIDE];

int main(void)
{
	con_fb = host_fb;
	con_clear(0x00102040);

	con_str("PROJECT", "iOS-SWEET -> DIG-AL00 Port");
	con_str("DEVICE",  "Huawei Enjoy 6S (MSM8940)");
	con_str("CPU",     "8x Cortex-A53 ARMv8.0-A");
	con_hex("FDT",     0x00000000bff00000ULL);
	con_str("MMU",     "4 KiB Granule Active (TTBR0)");
	con_str("GIC",     "ARM GICv2 MMIO Ready");
	con_str("TIMER",   "Virtual Timer Active (PPI 20)");
	con_str("STATUS",  "Checking payload in ramdisk...");
	con_str("LOADER",  "no DIGXNU payload in ramdisk");
	con_str_color("READY", "Shim diagnostics PASS! Halting.", GREEN);

	FILE *f = fopen("out/host.ppm", "wb");
	if (!f)
		return 1;
	fprintf(f, "P6 %d %d 255\n", FB_W, FB_H);
	for (int y = 0; y < FB_H; y++) {
		for (int x = 0; x < FB_W; x++) {
			const uint8_t *p = host_fb + (size_t)y * FB_STRIDE + (size_t)x * 3;
			unsigned char px[3] = { p[2], p[1], p[0] }; /* PPM is RGB, FB is BGR */
			fwrite(px, 1, 3, f);
		}
	}
	fclose(f);
	return 0;
}
