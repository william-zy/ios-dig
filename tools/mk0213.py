import subprocess

# ---- vince_adreno.c: full IB dump + bounded timeout spam ----
p = 'artifacts/patchgen/vince_adreno_0213_after.c'
s = open(p, encoding='utf-8').read()


def rep(old, new):
    global s
    c = s.count(old)
    if c != 1:
        raise SystemExit('%s: replacement count %d for:\n%s' % (p, c, old[:240]))
    s = s.replace(old, new)


rep("""/* First dwords of a client IB; only used while diagnosing submission. */
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
""",
"""/* A client IB while diagnosing submission; the error is usually deep in it. */
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
""")

# The client retries a timed-out fence with a 0 ms timeout, which produced
# ~500 identical status lines.  Always keep error bits; suppress idle repeats.
rep("""void
vince_gpu_status(void)
{
\tuint32_t stat = gr(A5_RBBM_INT_0_STATUS);
\tuint32_t cpint = gr(A5_CP_INTERRUPT_STATUS);
\tuint32_t opcode = 0;

\tif (cpint & 0x1u) {             /* CP_OPCODE_ERROR: PFP stat index 1 */
""",
"""void
vince_gpu_status(void)
{
\tstatic uint32_t status_calls;
\tuint32_t stat = gr(A5_RBBM_INT_0_STATUS);
\tuint32_t cpint = gr(A5_CP_INTERRUPT_STATUS);
\tuint32_t opcode = 0;
\tbool keep = stat != 0 || cpint != 0 || ++status_calls <= 8;

\tif (!keep && (status_calls % 60) != 0) {
\t\tgw(A5_RBBM_INT_CLEAR_CMD, stat & ~0x2u);
\t\treturn;
\t}
\tif (cpint & 0x1u) {             /* CP_OPCODE_ERROR: PFP stat index 1 */
""")
open(p, 'w', encoding='utf-8').write(s)

# ---- VinceGPU.cpp: flag any buffer freed while its fence is outstanding ----
p = 'artifacts/patchgen/VinceGPU_0213_after.cpp'
s = open(p, encoding='utf-8').read()

rep("""void
VinceGPUUserClient::freeBuffer(struct gpu_buffer *b)
{
\tif (b->memory != NULL) {
""",
"""void
VinceGPUUserClient::freeBuffer(struct gpu_buffer *b)
{
\tif (b->memory != NULL && b->used && !vince_gpu_done(b->lastFence)) {
\t\tIOLog("VinceGPU: freeing BO at %#llx still used by fence %u\\n",
\t\t    (unsigned long long)b->address, b->lastFence);
\t}
\tif (b->memory != NULL) {
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


data = make_diff('artifacts/patchgen/vince_adreno_0213_before.c',
                 'artifacts/patchgen/vince_adreno_0213_after.c', 'bsd/dev/vince_adreno.c')
data += make_diff('artifacts/patchgen/VinceGPU_0213_before.cpp',
                  'artifacts/patchgen/VinceGPU_0213_after.cpp', 'iokit/Kernel/arm/VinceGPU.cpp')
open('xnu/patches/0213-vince-gpu-ib-full-dump.patch', 'w', newline='\n').write(data)
print('written', len(data))
