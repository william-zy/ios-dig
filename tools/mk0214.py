import subprocess

p = 'artifacts/patchgen/vince_adreno_0214_after.c'
s = open(p, encoding='utf-8').read()


def rep(old, new):
    global s
    c = s.count(old)
    if c != 1:
        raise SystemExit('replacement count %d for:\n%s' % (c, old[:240]))
    s = s.replace(old, new)


# ---- track the last submitted IBs so a timeout can be localized ----
rep("""static vm_offset_t gmem_va = 0;
static uint32_t rb_wptr = 0;
""",
"""static vm_offset_t gmem_va = 0;
static uint32_t rb_wptr = 0;

/* IBs of the most recent submit, for the IB1_BUFSZ window in a timeout. */
#define IB_TRACK 8
static uint64_t ib_track_pa[IB_TRACK];
static uint32_t ib_track_words[IB_TRACK];
static uint32_t ib_track_count;
""")

# ---- split the dump into a reusable word dumper and add nested IBs ----
rep("""/* A client IB while diagnosing submission; the error is usually deep in it. */
static void
dump_ib(uint64_t pa, uint32_t dwords)
{
\tuint32_t n = MIN(dwords, 512u);
\tvm_size_t bytes = (vm_size_t)((pa & 0xfffu) + (uint64_t)n * 4u);
\tvm_offset_t va = ml_io_map((vm_offset_t)(pa & ~0xfffull), (bytes + 0xfffu) & ~(vm_size_t)0xfffu);

\tif (va == 0) {
\t\tprintf("adreno:  ib dump failed\\n");
\t\treturn;
\t}
\tprintf("adreno:  ib words (%u of %u):", n, dwords);
\tfor (uint32_t j = 0; j < n; j++) {
\t\tprintf(" %#x", reg_read(va, (uint32_t)(pa & 0xfffu) + j * 4u));
\t}
\tprintf("%s\\n", dwords > n ? " ..." : "");
}
""",
"""static void
dump_ib_words(uint64_t pa, uint32_t dwords)
{
\tuint32_t n = MIN(dwords, 512u);
\tvm_size_t bytes = (vm_size_t)((pa & 0xfffu) + (uint64_t)n * 4u);
\tvm_offset_t va = ml_io_map((vm_offset_t)(pa & ~0xfffull), (bytes + 0xfffu) & ~(vm_size_t)0xfffu);

\tif (va == 0) {
\t\tprintf("adreno:  ib dump failed (pa %#llx)\\n", (unsigned long long)pa);
\t\treturn;
\t}
\tprintf("adreno:  ib words (%u of %u):", n, dwords);
\tfor (uint32_t j = 0; j < n; j++) {
\t\tprintf(" %#x", reg_read(va, (uint32_t)(pa & 0xfffu) + j * 4u));
\t}
\tprintf("%s\\n", dwords > n ? " ..." : "");
}

/* Same, but starting at a dword offset: used for the CP's stop position. */
static void
dump_ib_window(uint64_t pa, uint32_t dwords, uint32_t at, const char *what)
{
\tuint32_t start = at > 8 ? at - 8 : 0;
\tuint32_t n = MIN(dwords - start, 24u);
\tvm_size_t bytes = (vm_size_t)((pa & 0xfffu) + (uint64_t)(start + n) * 4u);
\tvm_offset_t va = ml_io_map((vm_offset_t)(pa & ~0xfffull), (bytes + 0xfffu) & ~(vm_size_t)0xfffu);

\tif (va == 0) {
\t\treturn;
\t}
\tprintf("adreno:  ib1 %s at %u/%u:", what, at, dwords);
\tfor (uint32_t j = 0; j < n; j++) {
\t\tprintf(" %#x", reg_read(va, (uint32_t)(pa & 0xfffu) + (start + j) * 4u));
\t}
\tprintf("\\n");
}

/* An IB can contain indirect buffers; dump one level of those too. */
static void
dump_nested_ibs(uint64_t pa, uint32_t dwords)
{
\tuint32_t n = MIN(dwords, 512u);
\tvm_size_t bytes = (vm_size_t)((pa & 0xfffu) + (uint64_t)n * 4u);
\tvm_offset_t va = ml_io_map((vm_offset_t)(pa & ~0xfffull), (bytes + 0xfffu) & ~(vm_size_t)0xfffu);
\tuint32_t off = (uint32_t)(pa & 0xfffu);
\tuint32_t j = 0;

\tif (va == 0) {
\t\treturn;
\t}
\twhile (j < n) {
\t\tuint32_t h = reg_read(va, off + j * 4u);

\t\tif ((h & 0x70000000u) == 0x70000000u) {
\t\t\tuint32_t cnt = h & 0x3fffu;
\t\t\tuint32_t op = (h >> 16) & 0x7fu;

\t\t\tif (op == CP_INDIRECT_BUFFER_PFE && cnt >= 3 && j + 4 <= n) {
\t\t\t\tuint64_t np = reg_read(va, off + (j + 1) * 4u) |
\t\t\t\t    ((uint64_t)reg_read(va, off + (j + 2) * 4u) << 32);
\t\t\t\tuint32_t nw = reg_read(va, off + (j + 3) * 4u);

\t\t\t\tif (nw >= 1 && nw <= 4096) {
\t\t\t\t\tprintf("adreno:  nested ib at %u: pa %#llx dwords %u\\n",
\t\t\t\t\t    j, (unsigned long long)np, nw);
\t\t\t\t\tdump_ib_words(np, nw);
\t\t\t\t}
\t\t\t}
\t\t\tj += cnt + 1;
\t\t} else if ((h & 0xc0000000u) == 0x40000000u) {
\t\t\tj += (h & 0x7fu) + 1;
\t\t} else {
\t\t\tj++;
\t\t}
\t}
}

/* A client IB while diagnosing submission; the error is usually deep in it. */
static void
dump_ib(uint64_t pa, uint32_t dwords)
{
\tdump_ib_words(pa, dwords);
\tdump_nested_ibs(pa, dwords);
}
""")

# ---- record the IB list of each submit ----
rep("""\tstatic int submits_logged;

\tfor (i = 0; i < count; i++) {
""",
"""\tstatic int submits_logged;

\tib_track_count = MIN(count, (uint32_t)IB_TRACK);
\tfor (i = 0; i < ib_track_count; i++) {
\t\tib_track_pa[i] = addresses[i];
\t\tib_track_words[i] = words[i];
\t}

\tfor (i = 0; i < count; i++) {
""")

# ---- timeout: all PFP stats + IB1 stop windows ----
rep("""\tprintf("adreno: IB1=%#llx/%u IB2=%#llx/%u RB_CNTL=%#x ME_CNTL=%#x\\n",
\t\t((unsigned long long)gr(A5_CP_IB1_BASE_HI) << 32) | gr(A5_CP_IB1_BASE),
\t\tgr(A5_CP_IB1_BUFSZ),
\t\t((unsigned long long)gr(A5_CP_IB2_BASE_HI) << 32) | gr(A5_CP_IB2_BASE),
\t\tgr(A5_CP_IB2_BUFSZ), gr(A5_CP_RB_CNTL), gr(A5_CP_PFP_ME_CNTL));
""",
"""\t{
\t\tuint64_t ib1 = ((uint64_t)gr(A5_CP_IB1_BASE_HI) << 32) | gr(A5_CP_IB1_BASE);
\t\tuint32_t bufsz = gr(A5_CP_IB1_BUFSZ);
\t\tuint32_t pfp[8];

\t\tfor (uint32_t i = 0; i < 8; i++) {
\t\t\tgw(A5_CP_PFP_STAT_ADDR, i);
\t\t\t(void)gr(A5_CP_PFP_STAT_DATA);
\t\t\tpfp[i] = gr(A5_CP_PFP_STAT_DATA);
\t\t}
\t\tprintf("adreno: IB1=%#llx/%u IB2=%#llx/%u RB_CNTL=%#x ME_CNTL=%#x\\n",
\t\t    (unsigned long long)ib1, bufsz,
\t\t    ((unsigned long long)gr(A5_CP_IB2_BASE_HI) << 32) | gr(A5_CP_IB2_BASE),
\t\t    gr(A5_CP_IB2_BUFSZ), gr(A5_CP_RB_CNTL), gr(A5_CP_PFP_ME_CNTL));
\t\tprintf("adreno: PFPSTAT=%#x %#x %#x %#x %#x %#x %#x %#x\\n",
\t\t    pfp[0], pfp[1], pfp[2], pfp[3], pfp[4], pfp[5], pfp[6], pfp[7]);
\t\tfor (uint32_t i = 0; i < ib_track_count; i++) {
\t\t\tif (ib_track_pa[i] == ib1 && bufsz <= ib_track_words[i]) {
\t\t\t\tdump_ib_window(ib1, ib_track_words[i],
\t\t\t\t    ib_track_words[i] - bufsz, "if-bufsz-is-left");
\t\t\t\tdump_ib_window(ib1, ib_track_words[i], bufsz, "if-bufsz-is-fetched");
\t\t\t}
\t\t}
\t}
""")

open(p, 'w', encoding='utf-8').write(s)

d = subprocess.run(['git', 'diff', '--no-index', '--no-color',
                    'artifacts/patchgen/vince_adreno_0213_after.c', p],
                   capture_output=True, text=True).stdout
path = 'bsd/dev/vince_adreno.c'
fixed = []
for l in d.splitlines():
    if l.startswith('diff --git '):
        fixed.append('diff --git a/%s b/%s' % (path, path))
    elif l.startswith('--- '):
        fixed.append('--- a/%s' % path)
    elif l.startswith('+++ '):
        fixed.append('+++ b/%s' % path)
    else:
        fixed.append(l)
open('xnu/patches/0214-vince-gpu-ib1-window.patch', 'w', newline='\n').write('\n'.join(fixed) + '\n')
print('written')
