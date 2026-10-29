/*
 * Stub entry for the full-XNU-copy test (two-stage signature).
 *
 * Stage 1: write "DIGSTU2" at 0x9e800800 (stub started).
 * Stage 2: read the first 8 bytes of the XNU entry at 0xa147e700, store
 *          them at 0x9e800000, then write "DIGSTU3" at 0x9e800808.
 *
 * The shim prints ENTRY if it sees DIGSTU3, or "started but did not
 * complete" if it only sees DIGSTU2. Expected entry value:
 * 0xd503201f14000661 (b _start_first_cpu + NOP).
 */
	.section .text
	.globl _start
_start:
	/* stage 1: "DIGSTU2\0" at 0x9e800800 */
	movz	x3, #0x0800
	movk	x3, #0x9e80, lsl 16
	movz	x4, #0x4944
	movk	x4, #0x5347, lsl 16
	movk	x4, #0x5554, lsl 32
	movk	x4, #0x0032, lsl 48
	str	x4, [x3]
	dsb	sy

	/* read XNU entry at 0xa147e700, store at 0x9e800000 */
	movz	x1, #0xe700
	movk	x1, #0xa147, lsl 16
	ldr	x2, [x1]
	movz	x0, #0x0000
	movk	x0, #0x9e80, lsl 16
	str	x2, [x0]

	/* stage 2: "DIGSTU3\0" at 0x9e800808 */
	movz	x3, #0x0808
	movk	x3, #0x9e80, lsl 16
	movk	x4, #0x0033, lsl 48
	str	x4, [x3]
	dsb	sy

1:	wfi
	b	1b
