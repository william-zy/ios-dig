import subprocess

p = 'artifacts/patchgen/VinceGPU_0212_after.cpp'
s = open(p, encoding='utf-8').read()


def rep(old, new):
    global s
    c = s.count(old)
    if c != 1:
        raise SystemExit('replacement count %d for:\n%s' % (c, old[:200]))
    s = s.replace(old, new)


# The early `goto out` in the BO loop must not bypass an initialized variable.
rep("""\tIOReturn ret = kIOReturnSuccess;
\tfor (uint32_t i = 0; i < nr_bos; i++) {
""",
"""\tIOReturn ret = kIOReturnSuccess;
\tuint32_t kept = 0;
\tfor (uint32_t i = 0; i < nr_bos; i++) {
""")

rep("""\t}
\tuint32_t kept = 0;
\tfor (uint32_t i = 0; i < nr_ibs; i++) {
""",
"""\t}
\tfor (uint32_t i = 0; i < nr_ibs; i++) {
""")

open(p, 'w', encoding='utf-8').write(s)

d = subprocess.run(['git', 'diff', '--no-index', '--no-color',
                    'artifacts/patchgen/VinceGPU_0211_after.cpp', p],
                   capture_output=True, text=True).stdout
path = 'iokit/Kernel/arm/VinceGPU.cpp'
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
data = '\n'.join(fixed) + '\n'
open('xnu/patches/0212-vince-submit-kept-decl.patch', 'w', newline='\n').write(data)
print('written', len(data))
