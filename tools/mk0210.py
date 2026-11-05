import sys

# ---- vince_adreno.c: a fence-only submit (no IBs) is legitimate ----
p = 'artifacts/patchgen/vince_adreno_0210_after.c'
s = open(p, encoding='utf-8').read()


def rep(old, new):
    global s
    c = s.count(old)
    if c != 1:
        raise SystemExit('%s: replacement count %d for:\n%s' % (p, c, old[:200]))
    s = s.replace(old, new)


rep("""\tif (!gpu_ready || count == 0) {
\t\treturn 0;
\t}
""",
"""\tif (!gpu_ready) {
\t\treturn 0;
\t}
""")
open(p, 'w', encoding='utf-8').write(s)

# ---- VinceGPU.cpp: drop all-zero IBs instead of letting the CP choke ----
p = 'artifacts/patchgen/VinceGPU_0210_after.cpp'
s = open(p, encoding='utf-8').read()

rep("""IOReturn
VinceGPUUserClient::sweetSubmit(const void *input, size_t length, uint64_t *sequence)
""",
"""/*
 * CA's first submit carries an indirect buffer that is still all zeroes (a
 * fence-only submit).  The CP does not treat a PM4 type 0 word as a NOP: it
 * raises CP_OPCODE_ERROR and the context never runs again, which is exactly
 * what kept the first frame from reaching the panel.  Drop those buffers and
 * submit only the fence.
 */
static bool
sweetIbEmpty(const struct gpu_buffer *b, uint64_t address, uint32_t dwords)
{
\tuint32_t buf[16];
\tuint64_t off = address - b->address;

\tfor (uint32_t i = 0; i < dwords; ) {
\t\tuint32_t n = dwords - i < 16 ? dwords - i : 16;
\t\tif (b->memory->readBytes(off + (uint64_t)i * 4u, buf, n * 4u) != n * 4u) {
\t\t\treturn false;
\t\t}
\t\tfor (uint32_t j = 0; j < n; j++) {
\t\t\tif (buf[j] != 0) {
\t\t\t\treturn false;
\t\t\t}
\t\t}
\t\ti += n;
\t}
\treturn true;
}

IOReturn
VinceGPUUserClient::sweetSubmit(const void *input, size_t length, uint64_t *sequence)
""")

rep("""\tfor (uint32_t i = 0; i < nr_ibs; i++) {
\t\tuint64_t address = (uint64_t)ibs[i].address_lo | ((uint64_t)ibs[i].address_hi << 32);
\t\tuint32_t count = ibs[i].size_words;
\t\tbool owned = false;

\t\tif (count == 0 || (address & 3) || count > GPU_BUFFER_MAX / 4) {
\t\t\tret = kIOReturnBadArgument;
\t\t\tgoto out;
\t\t}
\t\tfor (uint32_t j = 0; j < nr_bos && !owned; j++) {
\t\t\towned = contains(listed[j], address, (uint64_t)count * 4);
\t\t}
\t\tif (!owned) {
\t\t\tret = kIOReturnNotPermitted;
\t\t\tgoto out;
\t\t}
\t\taddresses[i] = address;
\t\twords[i] = count;
\t}
\tseq = vince_gpu_submit(addresses, words, nr_ibs);
\tif (seq == 0) {
\t\tIOLog("VinceGPU: submit %u IBs failed\\n", nr_ibs);
""",
"""\tuint32_t kept = 0;
\tfor (uint32_t i = 0; i < nr_ibs; i++) {
\t\tuint64_t address = (uint64_t)ibs[i].address_lo | ((uint64_t)ibs[i].address_hi << 32);
\t\tuint32_t count = ibs[i].size_words;
\t\tstruct gpu_buffer *owner = NULL;

\t\tif (count == 0 || (address & 3) || count > GPU_BUFFER_MAX / 4) {
\t\t\tret = kIOReturnBadArgument;
\t\t\tgoto out;
\t\t}
\t\tfor (uint32_t j = 0; j < nr_bos && owner == NULL; j++) {
\t\t\tif (contains(listed[j], address, (uint64_t)count * 4)) {
\t\t\t\towner = listed[j];
\t\t\t}
\t\t}
\t\tif (owner == NULL) {
\t\t\tret = kIOReturnNotPermitted;
\t\t\tgoto out;
\t\t}
\t\tif (sweetIbEmpty(owner, address, count)) {
\t\t\tif (!fLoggedEmptyIb) {
\t\t\t\tfLoggedEmptyIb = true;
\t\t\t\tIOLog("VinceGPU: dropping empty IB %u (%u dwords)\\n", i, count);
\t\t\t}
\t\t\tcontinue;
\t\t}
\t\taddresses[kept] = address;
\t\twords[kept] = count;
\t\tkept++;
\t}
\tseq = vince_gpu_submit(addresses, words, kept);
\tif (seq == 0) {
\t\tIOLog("VinceGPU: submit %u IBs failed\\n", kept);
""")

rep("""\tif (!fLoggedSubmit) {
\t\tfLoggedSubmit = true;
\t\tIOLog("VinceGPU: first submit %u IBs, %u BOs -> seq %u\\n", nr_ibs, nr_bos, seq);
\t}
""",
"""\tif (!fLoggedSubmit) {
\t\tfLoggedSubmit = true;
\t\tIOLog("VinceGPU: first submit %u IBs (%u empty), %u BOs -> seq %u\\n",
\t\t    kept, nr_ibs - kept, nr_bos, seq);
\t}
""")

rep("""\tbool fLoggedSubmit;
""",
"""\tbool fLoggedSubmit;
\tbool fLoggedEmptyIb;
""")

rep("""\tfLoggedSubmit = false;
""",
"""\tfLoggedSubmit = false;
\tfLoggedEmptyIb = false;
""")

open(p, 'w', encoding='utf-8').write(s)
print('ok')
