/*
 * Minimal DIG-AL00 handover test payload (not XNU).
 *
 * The shim copies this to phys_base 0xa0000000 and jumps to it with the MMU
 * and D-cache off. It writes a signature to 0x9e800000 (outside XNU DRAM,
 * survives a warm reset), paints a green band on the 720p framebuffer, then
 * asks PSCI to reset the SoC. The next shim boot reads the signature and
 * halts with "TINY payload executed OK" if the handover worked.
 *
 * Link at 0; all references are PC-relative or absolute movz/movk addresses.
 */
	.section .text
	.globl _start
_start:
	/* Replay the XNU entry's first instructions: OSLAR, DAIF, boot_args */
	msr	OSLAR_EL1, xzr
	msr	DAIFSet, #0xf
	ldr	x6, [x0, #0x8]		/* boot_args virtBase */
	ldr	x7, [x0, #0x10]		/* boot_args physBase */
	ldr	x8, [x0, #0x18]		/* boot_args memSize */

	/* signature "DIGTINY\0" = 0x00594e4954474944 at 0x9e800000 */
	movz	x0, #0x0000
	movk	x0, #0x9e80, lsl #16
	movz	x1, #0x4944
	movk	x1, #0x5447, lsl #16
	movk	x1, #0x4e49, lsl #32
	movk	x1, #0x0059, lsl #48
	str	x1, [x0]

	/* simulate the XNU stage-0 band: 144 bytes of 0xff at 0x9e900000 */
	movz	x9, #0x0000
	movk	x9, #0x9e90, lsl #16
	mov	w10, #0xff
	mov	x11, #144
3:
	strb	w10, [x9], #1
	subs	x11, x11, #1
	b.ne	3b

	/* green band: 64 rows of 720 RGB888 pixels at 0x90001000 */
	movz	x2, #0x1000
	movk	x2, #0x9000, lsl #16
	movz	x4, #0x1c00
	movk	x4, #0x2, lsl 16	/* 720*3*64 = 0x21c00 */
1:
	strb	wzr, [x2], #1		/* B */
	mov	w5, #0xff
	strb	w5, [x2], #1		/* G */
	strb	wzr, [x2], #1		/* R */
	subs	x4, x4, #3
	b.ne	1b
	dsb	sy

	/* PSCI SYSTEM_RESET (SMC conduit) */
	mov	w0, #0x0009
	movk	w0, #0x8400, lsl #16
	smc	#0

2:	wfi
	b	2b
