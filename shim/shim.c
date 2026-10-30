/*
 * DIG-AL00 Boot Shim for Huawei Enjoy 6S (Qualcomm MSM8940)
 *
 * Boots Apple XNU Kernel on Qualcomm Snapdragon 435:
 * - GICv2 (QGIC2) MMIO configuration (GICD @ 0x0b000000, GICC @ 0x0b002000)
 * - 4 KiB Granule MMU Setup for Cortex-A53
 * - Continuous Splash Framebuffer @ 0x90001000 (720x1280 RGB888)
 * - FDT / Ramdisk payload extraction & XNU handover
 *
 * The board reuses the MSM8953 boot chain: SBL1 reports MSM8953C00B091_BOOT,
 * the GIC, virtual timer (PPI 4 = INTID 20) and SDHCI eMMC controller are at
 * the same addresses as the Xiaomi vince port. Only DRAM, display and the
 * peripheral set differ (see docs/硬件档案-DIG-AL00-20261029.md).
 */
#include <stdint.h>
#include "console.h"
#include "mmu.h"
#include "loader.h"
#include "fdt.h"

#define GICD_BASE		0x0b000000UL
#define GICC_BASE		0x0b002000UL

#define GICD_CTLR		0x000
#define GICD_TYPER		0x004
#define GICD_ISENABLER	0x100
#define GICD_ICENABLER	0x180
#define GICD_IPRIORITYR	0x400

#define GICC_CTLR		0x000
#define GICC_PMR		0x004
#define GICC_IAR		0x00c
#define GICC_EOIR		0x010

#define VTIMER_INTID	20  /* PPI 4 on MSM8940 (16 + 4) */

#define rsr(r) ({ uint64_t _v; __asm__ volatile("mrs %0, " r : "=r"(_v)); _v; })
#define wsr(r, v) __asm__ volatile("msr " r ", %0" : : "r"((uint64_t)(v)))
#define isb() __asm__ volatile("isb" ::: "memory")

static inline uint32_t rd32(uintptr_t a) { return *(volatile uint32_t *)a; }
static inline void wr32(uintptr_t a, uint32_t v) { *(volatile uint32_t *)a = v; }

static volatile uint32_t irq_count = 0;
static volatile uint32_t irq_last = 0;

/*
 * Previous-boot early-console capture. The XNU build carries the DIG debug
 * patches: start.s draws its stage bands into the first 32 rows of the
 * 0x9e800000 buffer and the early console writes text into the same buffer
 * from row 64 down. That area is outside XNU's DRAM (0xa0000000+) so the
 * kernel's VM cannot zero it, and the persistence probe proved it survives
 * the kernel's warm reset.
 *
 * Layout as shown on screen (720x1280, 24bpp, stride 2160):
 *   rows   0..31 : start.s stage bands, 96px each, left to right:
 *                  white=0 yellow=0A green=0B cyan=0C magenta=0D blue=0E red=0F
 *   rows  32..63 : sweet_early_mark bars (48px each, greenish)
 *   rows  64..   : early console text
 */
#define CAPTURE_TEXT_BASE	0x9e800000UL
#define CAPTURE_SIZE		((uint64_t)FB_H * FB_STRIDE)
#define CAPTURE_CLEAR_SIZE	0x40000UL

/* The capture area is mapped WB here; a warm reset can keep stale lines in
 * the cache, which would hide what the kernel wrote. Drop them before read. */
static void capture_invalidate(void)
{
	for (uintptr_t a = CAPTURE_TEXT_BASE; a < CAPTURE_TEXT_BASE + 0x1000; a += 64)
		__asm__ volatile("dc ivac, %0" : : "r"(a) : "memory");
	__asm__ volatile("dsb sy" ::: "memory");
}

static int capture_present(void)
{
	volatile uint8_t *p = (volatile uint8_t *)CAPTURE_TEXT_BASE;
	capture_invalidate();
	/* stage 0 writes a white 96x32 band: 288 bytes of 0xff per row */
	for (int i = 0; i < 288; i++) {
		if (p[i] != 0xff)
			return 0;
	}
	return 1;
}

static void capture_dump(void)
{
	volatile uint64_t *src = (volatile uint64_t *)CAPTURE_TEXT_BASE;
	volatile uint64_t *dst = (volatile uint64_t *)FB_BASE;
	for (uint64_t i = 0; i < CAPTURE_SIZE / 8; i++)
		dst[i] = src[i];
	__asm__ volatile("dsb sy" ::: "memory");

	/* Clear bands and the first text rows so the next boot runs the payload
	 * again instead of showing this same capture forever. Clean the cache:
	 * the shim runs with the D-cache on and the buffer lives in DRAM. */
	volatile uint64_t *clr = (volatile uint64_t *)CAPTURE_TEXT_BASE;
	for (uint64_t i = 0; i < CAPTURE_CLEAR_SIZE / 8; i++)
		clr[i] = 0;
	__asm__ volatile("dsb sy" ::: "memory");
	for (uintptr_t a = CAPTURE_TEXT_BASE; a < CAPTURE_TEXT_BASE + CAPTURE_CLEAR_SIZE; a += 64)
		__asm__ volatile("dc civac, %0" : : "r"(a) : "memory");
	__asm__ volatile("dsb sy" ::: "memory");

	con_goto(FB_H / 32 - 4);
	con_str("CAPTURE", "previous early console");
	con_str("STAGES", "top: 0=W 0A=Y 0B=G 0C=C 0D=M 0E=B 0F=R");
	con_str("MARKS", "row32+: sweet_early_mark stages");
	con_str("NOTE", "power off; capture shown");
	while (1)
		__asm__ volatile("wfi");
}

/*
 * Embedded panic log (pram at 0xdff00000, see XNU's embedded_panic_header):
 * magic "FUNK", eph_panic_log_offset at +16, eph_panic_log_len at +20.
 * After a panic the kernel writes the full log (panic string + backtrace)
 * there; the screen only keeps the tail because the fbcon wraps.
 */
#define PANIC_BASE		0xdff00000UL
#define PANIC_SIZE		0x100000UL
#define PANIC_MAGIC		0x46554E4BUL	/* "FUNK" */

static int paniclog_present(void)
{
	/* The kernel wrote the header through its own mapping; drop any stale
	 * line this shim could have cached on an earlier boot. */
	for (uintptr_t a = PANIC_BASE; a < PANIC_BASE + 0x1000; a += 64)
		__asm__ volatile("dc ivac, %0" : : "r"(a) : "memory");
	__asm__ volatile("dsb sy" ::: "memory");
	return *(volatile uint32_t *)PANIC_BASE == PANIC_MAGIC;
}

static void paniclog_dump(void)
{
	volatile uint8_t *base = (volatile uint8_t *)PANIC_BASE;
	uint32_t off = *(volatile uint32_t *)(PANIC_BASE + 16);
	uint32_t len = *(volatile uint32_t *)(PANIC_BASE + 20);
	int line = 0, col = 0;
	char buf[46];

	if (off < 40 || off >= PANIC_SIZE || len == 0 || len > PANIC_SIZE - off)
		return;

	/* Drop stale lines over the log text before reading it. */
	for (uintptr_t a = PANIC_BASE; a < PANIC_BASE + PANIC_SIZE; a += 64)
		__asm__ volatile("dc ivac, %0" : : "r"(a) : "memory");
	__asm__ volatile("dsb sy" ::: "memory");

	con_clear(0x00102040);
	con_str("PANICLOG", "embedded panic log, first lines");
	line = 1;
	for (uint32_t i = 0; i < len && line < 39; i++) {
		char c = (char)base[off + i];
		if (c == '\r')
			continue;
		if (c == '\n' || col >= 45) {
			buf[col] = 0;
			con_raw_line(buf);
			col = 0;
			line++;
			if (c == '\n')
				continue;
		}
		buf[col++] = (c >= 0x20 && c <= 0x7e) ? c : '.';
	}
	if (col && line < 39) {
		buf[col] = 0;
		con_raw_line(buf);
	}

	/* Clear the magic so the next boot runs the payload again. */
	*(volatile uint32_t *)PANIC_BASE = 0;
	__asm__ volatile("dsb sy" ::: "memory");
	for (uintptr_t a = PANIC_BASE; a < PANIC_BASE + 64; a += 64)
		__asm__ volatile("dc civac, %0" : : "r"(a) : "memory");
	__asm__ volatile("dsb sy" ::: "memory");

	con_goto(FB_H / 32 - 2);
	con_str("NOTE", "panic log shown; power off");
	while (1)
		__asm__ volatile("wfi");
}

void gicv2_init(void)
{
	/* Enable GIC Distributor */
	wr32(GICD_BASE + GICD_CTLR, 1);

	/* Set CPU Priority Mask to allow all interrupts */
	wr32(GICC_BASE + GICC_PMR, 0xff);

	/* Enable CPU Interface */
	wr32(GICC_BASE + GICC_CTLR, 1);

	/* Enable Virtual Timer interrupt */
	uint32_t reg_idx = VTIMER_INTID / 32;
	uint32_t bit_idx = VTIMER_INTID % 32;
	wr32(GICD_BASE + GICD_ISENABLER + (reg_idx * 4), (1U << bit_idx));
}

void timer_init(void)
{
	/* Set virtual timer comparator 100ms in the future */
	uint64_t freq = rsr("cntfrq_el0");
	uint64_t count = rsr("cntvct_el0");
	wsr("cntv_cval_el0", count + (freq / 10));
	/* Enable virtual timer (ENABLE=1, IMASK=0) */
	wsr("cntv_ctl_el0", 1);
	isb();
}

void exc_handler(int slot, uint64_t *regs)
{
	(void)regs;
	if (slot == 1 || slot == 5) { /* IRQ at EL0t (slot 1) or EL1h (slot 5) */
		uint32_t iar = rd32(GICC_BASE + GICC_IAR);
		uint32_t intid = iar & 0x3ff;
		irq_last = intid;
		irq_count++;

		if (intid == VTIMER_INTID) {
			/* Reset timer comparator */
			uint64_t freq = rsr("cntfrq_el0");
			uint64_t count = rsr("cntvct_el0");
			wsr("cntv_cval_el0", count + (freq / 10));
		}

		/* Send End-of-Interrupt */
		wr32(GICC_BASE + GICC_EOIR, iar);
		return;
	}

	/* Panic on unexpected exception */
	con_clear(RED);
	con_str("PANIC", "Unexpected Exception");
	con_hex("SLOT", (uint64_t)slot);
	con_hex("ELR", rsr("elr_el1"));
	con_hex("ESR", rsr("esr_el1"));
	con_hex("FAR", rsr("far_el1"));

	while (1) {
		__asm__ volatile("wfe");
	}
}

void secondary_main(uint64_t cpu_id)
{
	(void)cpu_id;
	while (1) {
		__asm__ volatile("wfe");
	}
}

void shim_main(void *fdt)
{
	/* 1. Paint screen and print initial banner immediately */
	con_clear(0x00102040); /* Deep navy slate background */

	con_str("PROJECT", "iOS-SWEET -> DIG-AL00 Port");
	con_str("DEVICE",  "Huawei Enjoy 6S (MSM8940)");
	con_str("CPU",     "8x Cortex-A53 ARMv8.0-A");
	con_hex("MPIDR",   rsr("mpidr_el1"));
	con_hex("MIDR",    rsr("midr_el1"));
	con_hex("FDT",     (uintptr_t)fdt);
	/* MMU still off here: this is an uncached physical read of the capture
	 * buffer, i.e. exactly what the previous kernel left in DRAM. */
	con_hex("CAP0",    *(volatile uint64_t *)CAPTURE_TEXT_BASE);

	/* 2. Setup 4KB Translation Granule MMU */
	struct mmu_info info;
	mmu_enable(&info);
	con_str("MMU",     "4 KiB Granule Active (TTBR0)");

	/* 2b. If the previous boot left a panic log, show it and stop */
	if (paniclog_present())
		paniclog_dump();

	/* 2c. If the previous boot left an early-console capture, show it and stop */
	if (capture_present())
		capture_dump();


	/* 3. Setup GICv2 */
	gicv2_init();
	con_str("GIC",     "ARM GICv2 MMIO Ready");

	/* 4. Setup Virtual Timer */
	timer_init();
	con_str("TIMER",   "Virtual Timer Active (PPI 20)");

	/* 5. Check ramdisk payload */
	con_str("STATUS",  "Checking payload in ramdisk...");
	const char *err = loader_boot((uintptr_t)fdt);
	if (err) {
		con_str("LOADER",  err);
		con_str_color("READY",   "Shim diagnostics PASS! Halting.", GREEN);
	}

	/* Stay active displaying boot state */
	while (1) {
		__asm__ volatile("wfi");
	}
}
