import subprocess

# ---------- vince_adreno.c ----------
p = 'artifacts/patchgen/vince_adreno_0216_after.c'
s = open(p, encoding='utf-8').read()


def rep(old, new):
    global s
    c = s.count(old)
    if c != 1:
        raise SystemExit('%s: replacement count %d for:\n%s' % (p, c, old[:240]))
    s = s.replace(old, new)


# Indexed dump: one word per line, so console interleaving cannot merge tokens.
rep("""static void
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
\tprintf("adreno:  ib[begin] pa %#llx dwords %u\\n", (unsigned long long)pa, dwords);
\tfor (uint32_t j = 0; j < n; j++) {
\t\tprintf("adreno:  ib[%u]=%#x\\n", j,
\t\t    reg_read(va, (uint32_t)(pa & 0xfffu) + j * 4u));
\t}
\tif (dwords > n) {
\t\tprintf("adreno:  ib[end] truncated at %u\\n", n);
\t}
}
""")

rep("""\tprintf("adreno:  ib1 %s at %u/%u:", what, at, dwords);
\tfor (uint32_t j = 0; j < n; j++) {
\t\tprintf(" %#x", reg_read(va, (uint32_t)(pa & 0xfffu) + (start + j) * 4u));
\t}
\tprintf("\\n");
""",
"""\tprintf("adreno:  ib1 %s at %u/%u\\n", what, at, dwords);
\tfor (uint32_t j = 0; j < n; j++) {
\t\tprintf("adreno:  ibw[%u]=%#x\\n", start + j,
\t\t    reg_read(va, (uint32_t)(pa & 0xfffu) + (start + j) * 4u));
\t}
""")

# Replace stray 0xffffffff words that land on a packet boundary.  Mesa only
# uses that value as CP_LOAD_STATE4 payload padding, never as a header; on a
# boundary it decodes as type 3 / opcode 0xff and wedges the CP.
rep("""/* A client IB while diagnosing submission; the error is usually deep in it. */
static void
dump_ib(uint64_t pa, uint32_t dwords)
{
\tdump_ib_words(pa, dwords);
\tdump_nested_ibs(pa, dwords);
}
""",
"""/*
 * A word 0xffffffff at a packet boundary decodes as a type-3 packet with
 * opcode 0xff and a 64K count.  Mesa only emits that value as padding
 * inside a CP_LOAD_STATE4 payload, so on a boundary it is stale data in a
 * reused buffer.  Replace it with a one-dword CP_NOP so the rest of the
 * stream can run; log every replacement (diagnostic build).
 */
static uint32_t
sanitize_ib(uint64_t pa, uint32_t dwords)
{
\tuint32_t n = MIN(dwords, 4096u);
\tvm_size_t bytes = (vm_size_t)((pa & 0xfffu) + (uint64_t)n * 4u);
\tvm_offset_t va = ml_io_map((vm_offset_t)(pa & ~0xfffull), (bytes + 0xfffu) & ~(vm_size_t)0xfffu);
\tuint32_t off = (uint32_t)(pa & 0xfffu);
\tuint32_t j = 0, fixed = 0;

\tif (va == 0) {
\t\treturn 0;
\t}
\twhile (j < n) {
\t\tuint32_t h = reg_read(va, off + j * 4u);

\t\tif ((h & 0xc0000000u) == 0) {
\t\t\tj += ((h >> 16) & 0x3fffu) + 1u;        /* type 0 */
\t\t} else if ((h & 0xf0000000u) == 0x40000000u) {
\t\t\tj += (h & 0x7fu) + 1u;                  /* type 4 */
\t\t} else if ((h & 0xf0000000u) == 0x70000000u) {
\t\t\tj += ((h & 0x3fffu) + 1u);              /* type 7 */
\t\t} else if (h == 0xffffffffu) {
\t\t\treg_write(va, off + j * 4u, 0x70108000u); /* pkt7(CP_NOP, 0) */
\t\t\tprintf("adreno: sanitize stray 0xffffffff at %u/%u\\n", j, n);
\t\t\tfixed++;
\t\t\tj++;
\t\t} else {
\t\t\tj++;
\t\t}
\t}
\treturn fixed;
}

/* A client IB while diagnosing submission; the error is usually deep in it. */
static void
dump_ib(uint64_t pa, uint32_t dwords)
{
\tdump_ib_words(pa, dwords);
\tdump_nested_ibs(pa, dwords);
}
""")

# Run sanitize on the first submits, after the dump (so both are visible).
rep("""\tif (submits_logged < 3) {
\t\tsubmits_logged++;
\t\tprintf("adreno: submit %d: %u IBs fence %u RPTR=%u WPTR=%u\\n",
\t\t\tsubmits_logged, count, gpu_fence, gr(A5_CP_RB_RPTR), rb_wptr);
\t\tfor (uint32_t k = 0; k < count && k < 8; k++) {
\t\t\tprintf("adreno:  ib %u pa %#llx dwords %u\\n", k,
\t\t\t\t(unsigned long long)addresses[k], words[k]);
\t\t\tdump_ib(addresses[k], words[k]);
\t\t}
\t}
""",
"""\tif (submits_logged < 3) {
\t\tsubmits_logged++;
\t\tprintf("adreno: submit %d: %u IBs fence %u RPTR=%u WPTR=%u\\n",
\t\t\tsubmits_logged, count, gpu_fence, gr(A5_CP_RB_RPTR), rb_wptr);
\t\tfor (uint32_t k = 0; k < count && k < 8; k++) {
\t\t\tprintf("adreno:  ib %u pa %#llx dwords %u\\n", k,
\t\t\t\t(unsigned long long)addresses[k], words[k]);
\t\t\tdump_ib(addresses[k], words[k]);
\t\t\tsanitize_ib(addresses[k], words[k]);
\t\t}
\t}
""")

open(p, 'w', encoding='utf-8').write(s)

# ---------- VinceGPU.cpp: log the first BO allocations ----------
p = 'artifacts/patchgen/VinceGPU_0216_after.cpp'
s = open(p, encoding='utf-8').read()

rep("""\tumap = memory->createMappingInTask(fTask, 0, kIOMapAnywhere);
""",
"""\t{
\t\tstatic uint32_t gem_logged;
\t\tif (gem_logged < 40) {
\t\t\tgem_logged++;
\t\t\tIOLog("VinceGPU: gem size %llu pa %#llx\\n",
\t\t\t    (unsigned long long)size, (unsigned long long)base);
\t\t}
\t}
\tumap = memory->createMappingInTask(fTask, 0, kIOMapAnywhere);
""")

open(p, 'w', encoding='utf-8').write(s)


def make_diff(before, after, path):
    d = subprocess.run(['git', 'diff', '--no-index', '--no-color', before, after],
                       capture_output=True, text=True).stdout
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
    return '\n'.join(fixed) + '\n'


data = make_diff('artifacts/patchgen/vince_adreno_0216_before.c',
                 'artifacts/patchgen/vince_adreno_0216_after.c', 'bsd/dev/vince_adreno.c')
data += make_diff('artifacts/patchgen/VinceGPU_0216_before.cpp',
                  'artifacts/patchgen/VinceGPU_0216_after.cpp', 'iokit/Kernel/arm/VinceGPU.cpp')
open('xnu/patches/0216-vince-gpu-stray-words.patch', 'w', newline='\n').write(data)
print('written')
