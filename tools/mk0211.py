import sys

# ---- SweetFramebuffer.cpp: SwapEnd may arrive out-of-line ----
p = 'artifacts/patchgen/SweetFramebuffer_0211_after.cpp'
s = open(p, encoding='utf-8').read()


def rep(old, new):
    global s
    c = s.count(old)
    if c != 1:
        raise SystemExit('%s: replacement count %d for:\n%s' % (p, c, old[:200]))
    s = s.replace(old, new)


rep("""static uint32_t sweet_fb_swaps_logged;
""",
"""static uint32_t sweet_fb_swaps_logged;
static bool sweet_fb_swepend_logged;
""")

rep("""\tcase kSweetFBSwapEnd: {
\t\tuint8_t rec[SWEET_FB_SWAP_REC_SIZE];
\t\tif (args->structureInputDescriptor != NULL ||
\t\t    args->structureInputSize < SWEET_FB_SWAP_REC_SIZE) {
\t\t\tret = kIOReturnBadArgument;
\t\t\tbreak;
\t\t}
\t\tmemcpy(rec, args->structureInput, sizeof(rec));
\t\tfFB->swap(rec);
\t\tbreak;
\t}
""",
"""\tcase kSweetFBSwapEnd: {
\t\tuint8_t rec[SWEET_FB_SWAP_REC_SIZE];
\t\tbool ool = args->structureInputDescriptor != NULL;

\t\t/* 0x46c is over the inline limit, so CA may hand it to us OOL. */
\t\tif (ool) {
\t\t\tif (args->structureInputDescriptor->getLength() < SWEET_FB_SWAP_REC_SIZE ||
\t\t\t    args->structureInputDescriptor->readBytes(0, rec, sizeof(rec)) != sizeof(rec)) {
\t\t\t\tret = kIOReturnBadArgument;
\t\t\t\tbreak;
\t\t\t}
\t\t} else if (args->structureInput == NULL ||
\t\t    args->structureInputSize < SWEET_FB_SWAP_REC_SIZE) {
\t\t\tret = kIOReturnBadArgument;
\t\t\tbreak;
\t\t} else {
\t\t\tmemcpy(rec, args->structureInput, sizeof(rec));
\t\t}
\t\tif (!sweet_fb_swepend_logged) {
\t\t\tsweet_fb_swepend_logged = true;
\t\t\tIOLog("SWEET FB: SwapEnd via %s (%u bytes)\\n",
\t\t\t    ool ? "OOL descriptor" : "inline input",
\t\t\t    (unsigned)(ool ? args->structureInputDescriptor->getLength()
\t\t\t        : args->structureInputSize));
\t\t}
\t\tfFB->swap(rec);
\t\tbreak;
\t}
""")
open(p, 'w', encoding='utf-8').write(s)

# ---- VinceGPU.cpp: log every dropped empty IB, not just the first ----
p = 'artifacts/patchgen/VinceGPU_0211_after.cpp'
s = open(p, encoding='utf-8').read()

rep("""\tbool fLoggedSubmit;
\tbool fLoggedEmptyIb;
""",
"""\tbool fLoggedSubmit;
\tuint32_t fEmptyIbsLogged;
""")

rep("""\tfLoggedSubmit = false;
\tfLoggedEmptyIb = false;
""",
"""\tfLoggedSubmit = false;
\tfEmptyIbsLogged = 0;
""")

rep("""\t\tif (sweetIbEmpty(owner, address, count)) {
\t\t\tif (!fLoggedEmptyIb) {
\t\t\t\tfLoggedEmptyIb = true;
\t\t\t\tIOLog("VinceGPU: dropping empty IB %u (%u dwords)\\n", i, count);
\t\t\t}
\t\t\tcontinue;
\t\t}
""",
"""\t\tif (sweetIbEmpty(owner, address, count)) {
\t\t\tif (fEmptyIbsLogged < 16) {
\t\t\t\tfEmptyIbsLogged++;
\t\t\t\tIOLog("VinceGPU: dropping empty IB %u at %#llx (%u dwords)\\n",
\t\t\t\t    i, (unsigned long long)address, count);
\t\t\t}
\t\t\tcontinue;
\t\t}
""")

open(p, 'w', encoding='utf-8').write(s)
print('ok')
