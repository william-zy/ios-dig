import sys

p = 'artifacts/patchgen/vince_adreno_0209_after.c'
s = open(p, encoding='utf-8').read()


def rep(old, new):
    global s
    c = s.count(old)
    if c != 1:
        raise SystemExit('replacement count %d for:\n%s' % (c, old[:200]))
    s = s.replace(old, new)


rep("""#define A5_CP_INTERRUPT_STATUS          0x0b18
#define A5_CP_HW_FAULT                  0x0b1a
#define A5_CP_PROTECT_STATUS            0x0b1c
""",
"""#define A5_CP_PFP_STAT_ADDR             0x0808
#define A5_CP_PFP_STAT_DATA             0x0809
#define A5_CP_INTERRUPT_STATUS          0x0b18
#define A5_CP_HW_FAULT                  0x0b1a
#define A5_CP_AHB_FAULT                 0x0b1b
#define A5_CP_PROTECT_STATUS            0x0b1c
#define A5_CP_IB1_BASE                  0x0b1f
#define A5_CP_IB1_BASE_HI               0x0b20
#define A5_CP_IB1_BUFSZ                 0x0b21
#define A5_CP_IB2_BASE                  0x0b22
#define A5_CP_IB2_BASE_HI               0x0b23
#define A5_CP_IB2_BUFSZ                 0x0b24
#define A5_RBBM_STATUS3                 0x0530
""")

rep("""void
vince_gpu_status(void)
{
\tprintf("adreno: RPTR=%u WPTR=%u RBBM=%#x INT0=%#x FAULT=%#x scratch=%#x\\n",
\t\tgr(A5_CP_RB_RPTR), rb_wptr, gr(A5_RBBM_STATUS), gr(A5_RBBM_INT_0_STATUS),
\t\tgr(A5_CP_HW_FAULT), gmem_r32(GPU_SCRATCH_OFF + 0x20));
}
""",
"""void
vince_gpu_status(void)
{
\tuint32_t stat = gr(A5_RBBM_INT_0_STATUS);
\tuint32_t cpint = gr(A5_CP_INTERRUPT_STATUS);
\tuint32_t opcode = 0;

\tif (cpint & 0x1u) {             /* CP_OPCODE_ERROR: PFP stat index 1 */
\t\tgw(A5_CP_PFP_STAT_ADDR, 0);
\t\t(void)gr(A5_CP_PFP_STAT_DATA);
\t\topcode = gr(A5_CP_PFP_STAT_DATA);
\t}
\tprintf("adreno: RPTR=%u WPTR=%u RBBM=%#x STATUS3=%#x INT0=%#x CPINT=%#x\\n",
\t\tgr(A5_CP_RB_RPTR), rb_wptr, gr(A5_RBBM_STATUS), gr(A5_RBBM_STATUS3),
\t\tstat, cpint);
\tprintf("adreno: FAULT=%#x AHB=%#x PROT=%#x opcode=%#x scratch=%#x\\n",
\t\tgr(A5_CP_HW_FAULT), gr(A5_CP_AHB_FAULT), gr(A5_CP_PROTECT_STATUS),
\t\topcode, gmem_r32(GPU_SCRATCH_OFF + 0x20));
\tprintf("adreno: IB1=%#llx/%u IB2=%#llx/%u RB_CNTL=%#x ME_CNTL=%#x\\n",
\t\t((unsigned long long)gr(A5_CP_IB1_BASE_HI) << 32) | gr(A5_CP_IB1_BASE),
\t\tgr(A5_CP_IB1_BUFSZ),
\t\t((unsigned long long)gr(A5_CP_IB2_BASE_HI) << 32) | gr(A5_CP_IB2_BASE),
\t\tgr(A5_CP_IB2_BUFSZ), gr(A5_CP_RB_CNTL), gr(A5_CP_PFP_ME_CNTL));
\t/* Fresh bits for the next submission. */
\tgw(A5_RBBM_INT_CLEAR_CMD, stat & ~0x2u);
}

/* First dwords of a client IB; only used while diagnosing submission. */
static void
dump_ib(uint64_t pa, uint32_t dwords)
{
\tvm_offset_t va = ml_io_map((vm_offset_t)(pa & ~0xfffull), 0x2000);
\tuint32_t n = MIN(dwords, 24u);

\tif (va == 0) {
\t\tprintf("adreno:  ib dump failed\\n");
\t\treturn;
\t}
\tprintf("adreno:  ib words:");
\tfor (uint32_t j = 0; j < n; j++) {
\t\tprintf(" %#x", reg_read(va, (uint32_t)(pa & 0xfffu) + j * 4u));
\t}
\tprintf("%s\\n", dwords > n ? " ..." : "");
}
""")

rep("""\trb_emit(pkt7(CP_EVENT_WRITE, 4));
\trb_emit(0x04);                          /* CACHE_FLUSH_TS */
""",
"""\trb_emit(pkt7(CP_EVENT_WRITE, 4));
\trb_emit(0x80000004u);                   /* CACHE_FLUSH_TS | IRQ */
""")

rep("""\t\tfor (uint32_t k = 0; k < count && k < 8; k++) {
\t\t\tprintf("adreno:  ib %u pa %#llx dwords %u\\n", k,
\t\t\t\t(unsigned long long)addresses[k], words[k]);
\t\t}
""",
"""\t\tfor (uint32_t k = 0; k < count && k < 8; k++) {
\t\t\tprintf("adreno:  ib %u pa %#llx dwords %u\\n", k,
\t\t\t\t(unsigned long long)addresses[k], words[k]);
\t\t\tdump_ib(addresses[k], words[k]);
\t\t}
""")

rep("""\t__asm__ volatile("dsb sy" ::: "memory");
\tgw(A5_CP_RB_WPTR, rb_wptr);

\treturn gpu_fence;
}
""",
"""\t/* Stale error bits from the previous submit would hide this one's. */
\t{
\t\tuint32_t stale = gr(A5_RBBM_INT_0_STATUS);
\t\tif (stale != 0) {
\t\t\tgw(A5_RBBM_INT_CLEAR_CMD, stale & ~0x2u);
\t\t}
\t}

\t__asm__ volatile("dsb sy" ::: "memory");
\tgw(A5_CP_RB_WPTR, rb_wptr);

\treturn gpu_fence;
}
""")

rep("""static bool
step11_post_zap(void)
""",
"""/*
 * Run a trivially valid IB through the same CP path a client IB takes.  If
 * the scratch word and the timestamp arrive, CP_INDIRECT_BUFFER_PFE and the
 * event write work, and a failing GPU submit is about its contents.
 */
static bool
ib_selftest(void)
{
\tconst uint32_t ib_off = GPU_SCRATCH_OFF + 0x1000;
\tuint32_t ib[9];
\tuint32_t n = 0, mem, ts;

\tib[n++] = pkt7(CP_MEM_WRITE, 3);
\tib[n++] = GPU_MEM_PA + GPU_SCRATCH_OFF + 0x24;
\tib[n++] = 0;
\tib[n++] = 0xc0ffee03u;
\tib[n++] = pkt7(CP_EVENT_WRITE, 4);
\tib[n++] = 0x80000004u;
\tib[n++] = GPU_MEM_PA + GPU_SCRATCH_OFF + 0x28;
\tib[n++] = 0;
\tib[n++] = 0x1234u;

\tgmem_w32(GPU_SCRATCH_OFF + 0x24, 0);
\tgmem_w32(GPU_SCRATCH_OFF + 0x28, 0);
\tfor (uint32_t j = 0; j < n; j++) {
\t\tgmem_w32(ib_off + j * 4u, ib[j]);
\t}

\tgw(A5_RBBM_INT_CLEAR_CMD, gr(A5_RBBM_INT_0_STATUS));
\trb_emit(pkt7(CP_INDIRECT_BUFFER_PFE, 3));
\trb_emit(GPU_MEM_PA + ib_off);
\trb_emit(0);
\trb_emit(n);
\tif (!rb_flush("IB selftest")) {
\t\tprintf("adreno: ib selftest: NOT consumed\\n");
\t\treturn false;
\t}
\tdelay(10000);
\tmem = gmem_r32(GPU_SCRATCH_OFF + 0x24);
\tts = gmem_r32(GPU_SCRATCH_OFF + 0x28);
\tprintf("adreno: ib selftest: mem=%#x ts=%#x INT0=%#x CPINT=%#x RPTR=%u\\n",
\t\tmem, ts, gr(A5_RBBM_INT_0_STATUS), gr(A5_CP_INTERRUPT_STATUS),
\t\tgr(A5_CP_RB_RPTR));
\treturn mem == 0xc0ffee03u && ts == 0x1234u;
}

static bool
step11_post_zap(void)
""")

rep("""\t\tprintf("adreno: step 11: Adreno 506 command processor is up (ring at PA %#x)\\n", GPU_MEM_PA + GPU_RB_OFF);
\t\tgpu_ready = true;
""",
"""\t\tprintf("adreno: step 11: Adreno 506 command processor is up (ring at PA %#x)\\n", GPU_MEM_PA + GPU_RB_OFF);
\t\t(void)ib_selftest();
\t\tgpu_ready = true;
""")

open(p, 'w', encoding='utf-8').write(s)
print('ok', len(s))
