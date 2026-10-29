/*
 * DIG-AL00 (MSM8940) 4 KiB Granule MMU Setup for ARM Cortex-A53
 *
 * Cortex-A53 natively supports 4 KiB (TG0=00) and 64 KiB (TG0=01).
 * 16 KiB granule is NOT supported in hardware.
 *
 * Page table hierarchy:
 * T0SZ=25 gives 39-bit VA space (512 GB).
 * Level 1 table: 512 entries x 1 GB
 * Level 2 table: 512 entries x 2 MB blocks
 *
 * Physical map of the Huawei Enjoy 6S (from the live device tree):
 *   0x00000000-0x1fffffff  MMIO (GIC, UART, SDHCI, GCC, GPU, SPMI, ...)
 *   0x20000000-0x7fffffff  RAM bank 1, 1.5 GiB, no carveouts (XNU DRAM)
 *   0x80000000-0x8fffffff  RAM bank 2 lower: shim, LK, payload ramdisk,
 *                          plus modem/TZ carveouts we never touch
 *   0x90000000-0x913fffff  splash framebuffer (20 MiB)
 *   0x91400000-0x9fffffff  reserved carveouts (sahara, hwlog, ram_oops, ...)
 *   0xa0000000-0xdfffffff  RAM bank 2 upper (1.5 GiB total bank)
 *
 * LK loads this shim at 0x80008000 and the payload ramdisk at 0x33000000
 * (verified from the running Android /chosen linux,initrd-start), so both
 * sides of bank 1 must be mapped write-back and executable.
 */
#include <stdint.h>
#include "mmu.h"

#define PG_SHIFT	12
#define PG_SIZE		(1UL << PG_SHIFT)		/* 4 KiB */
#define BLK_SHIFT	21
#define BLK_SIZE	(1UL << BLK_SHIFT)		/* 2 MiB level-2 block */
#define NENT		512				/* 512 entries = 4 KiB table */

#define ATTR_DEV	0	/* MAIR attr0 = 0x00 Device-nGnRnE */
#define ATTR_WB		1	/* MAIR attr1 = 0xff Normal WB RW-alloc */
#define ATTR_NC		2	/* MAIR attr2 = 0x44 Normal non-cacheable (write-combining) */
#define MAIR_VAL	0x44ff00UL

#define D_BLOCK		1UL
#define D_TABLE		3UL
#define D_PAGE		3UL
#define D_ATTR(i)	((uint64_t)(i) << 2)
#define D_SH_OUTER	(2UL << 8)
#define D_SH_INNER	(3UL << 8)
#define D_AF		(1UL << 10)
#define D_PXN		(1UL << 53)
#define D_UXN		(1UL << 54)

#define DEV_FLAGS	(D_ATTR(ATTR_DEV) | D_AF | D_PXN | D_UXN)
#define WB_FLAGS	(D_ATTR(ATTR_WB) | D_SH_INNER | D_AF | D_UXN)
#define NC_FLAGS	(D_ATTR(ATTR_NC) | D_SH_OUTER | D_AF | D_PXN | D_UXN)

/* TCR: T0SZ=25 (39-bit VA), IRGN0/ORGN0=WBWA, SH0=inner, TG0=00 (4K Granule), EPD1=1, IPS=36-bit */
#define TCR_VAL		(25UL | (1UL << 8) | (1UL << 10) | (3UL << 12) | (0UL << 14) | (1UL << 23) | (1UL << 32))

#define SCTLR_M		(1UL << 0)
#define SCTLR_A		(1UL << 1)
#define SCTLR_C		(1UL << 2)
#define SCTLR_I		(1UL << 12)
#define SCTLR_WXN	(1UL << 19)

#define rsr(r) ({ uint64_t _v; __asm__ volatile("mrs %0, " r : "=r"(_v)); _v; })
#define wsr(r, v) __asm__ volatile("msr " r ", %0" : : "r"((uint64_t)(v)))

extern char _head[], _end[];

/* Page table pool: L1 (1) + L2 (4) = 5 tables x 4KB = 20KB, pool of 16 tables (64KB) */
static uint64_t pt_pool[16 * NENT] __attribute__((aligned(4096)));

static void zero_table(uint64_t *t)
{
	for (int i = 0; i < NENT; i++)
		t[i] = 0;
}

int mmu_enable(struct mmu_info *info)
{
	uintptr_t img_lo = (uintptr_t)_head & ~(PG_SIZE - 1);
	uintptr_t img_hi = ((uintptr_t)_end + PG_SIZE - 1) & ~(PG_SIZE - 1);
	uintptr_t pool = (uintptr_t)pt_pool;

	uint64_t *l1 = (uint64_t *)pool;

	info->img_lo = img_lo;
	info->img_hi = img_hi;
	info->ttbr = pool;

	zero_table(l1);

	for (int i = 0; i < 4; i++) {
		uint64_t *l2_tbl = (uint64_t *)(pool + (1 + i) * PG_SIZE);
		zero_table(l2_tbl);
		l1[i] = (uintptr_t)l2_tbl | D_TABLE;

		uint64_t base_pa = (uint64_t)i * (1UL << 30);

		if (i == 0) {
			/* GB 0: 0x00000000-0x1fffffff MMIO, 0x20000000-0x3fffffff RAM bank 1 */
			for (int j = 0; j < 256; j++)
				l2_tbl[j] = (base_pa + (uint64_t)j * BLK_SIZE) | DEV_FLAGS | D_BLOCK;
			for (int j = 256; j < NENT; j++)
				l2_tbl[j] = (base_pa + (uint64_t)j * BLK_SIZE) | WB_FLAGS | D_BLOCK;
		} else if (i == 1) {
			/* GB 1: 0x40000000-0x7fffffff RAM bank 1 upper half */
			for (int j = 0; j < NENT; j++)
				l2_tbl[j] = (base_pa + (uint64_t)j * BLK_SIZE) | WB_FLAGS | D_BLOCK;
		} else if (i == 2) {
			/* GB 2: shim + ramdisk (WB), splash (NC), carveouts (DEV), bank 2 RAM (WB) */
			for (int j = 0; j < 128; j++)
				l2_tbl[j] = (base_pa + (uint64_t)j * BLK_SIZE) | WB_FLAGS | D_BLOCK;

			for (int j = 128; j < 144; j++)
				l2_tbl[j] = (base_pa + (uint64_t)j * BLK_SIZE) | NC_FLAGS | D_BLOCK;

			/* 0x92000000-0x925fffff: sahara/hwlog/ram_oops carveouts */
			for (int j = 144; j < 147; j++)
				l2_tbl[j] = (base_pa + (uint64_t)j * BLK_SIZE) | DEV_FLAGS | D_BLOCK;

			/* 0x92600000-0x9fffffff: free bank 2 RAM, used as the
			 * previous-boot early-console capture buffer at 0x98000000 */
			for (int j = 147; j < 256; j++)
				l2_tbl[j] = (base_pa + (uint64_t)j * BLK_SIZE) | WB_FLAGS | D_BLOCK;

			for (int j = 256; j < NENT; j++)
				l2_tbl[j] = (base_pa + (uint64_t)j * BLK_SIZE) | WB_FLAGS | D_BLOCK;
		} else {
			/* GB 3: 0xc0000000-0xdfffffff RAM bank 2 upper, rest unmapped holes */
			for (int j = 0; j < NENT; j++)
				l2_tbl[j] = (base_pa + (uint64_t)j * BLK_SIZE) | WB_FLAGS | D_BLOCK;
		}
	}

	/* Commit page table writes to memory */
	__asm__ volatile("dsb ish" ::: "memory");

	/* Invalidate TLB */
	__asm__ volatile("tlbi vmalle1is" ::: "memory");
	__asm__ volatile("dsb ish" ::: "memory");
	__asm__ volatile("isb" ::: "memory");

	/* Setup MAIR, TCR, TTBR0 */
	wsr("mair_el1", MAIR_VAL);
	wsr("tcr_el1", TCR_VAL);
	wsr("ttbr0_el1", pool);
	__asm__ volatile("isb" ::: "memory");

	/* Invalidate Instruction Cache */
	__asm__ volatile("ic ialluis" ::: "memory");
	__asm__ volatile("dsb ish" ::: "memory");
	__asm__ volatile("isb" ::: "memory");

	/* Enable MMU, D-Cache, I-Cache */
	uint64_t sctlr = rsr("sctlr_el1");
	sctlr |= SCTLR_M | SCTLR_C | SCTLR_I;
	wsr("sctlr_el1", sctlr);
	__asm__ volatile("isb" ::: "memory");

	return 0;
}
