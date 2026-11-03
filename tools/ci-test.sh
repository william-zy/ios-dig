#!/usr/bin/env bash
# Download a finished xnu-dig CI kernel, pack it with the DIG ADT and build
# the recovery test image.
#
#   bash tools/ci-test.sh RUN_ID
#
# The workflow uploads the kernel as the artifact "xnu-kernel-dig".
set -euo pipefail
cd "$(dirname "$0")/.."

GH="../../tools/gh/bin/gh.exe"
RUN_ID="${1:?usage: ci-test.sh RUN_ID}"

mkdir -p xnu/out/ci
rm -rf xnu/out/ci/*
# Prefer the kernel-only artifact: the full one carries the dSYM and is ~62MB.
if ! "$GH" run download "$RUN_ID" -n xnu-kernel-min -D xnu/out/ci; then
    echo "[!] xnu-kernel-min not available, falling back to xnu-kernel-dig"
    "$GH" run download "$RUN_ID" -n xnu-kernel-dig -D xnu/out/ci
fi

KERNEL=$(find xnu/out/ci -type f -name 'kernel.development.vince' | head -1)
if [ -z "$KERNEL" ]; then
    echo "no kernel.development.* in the artifact; listing:"
    find xnu/out/ci -type f -maxdepth 3 -print
    exit 1
fi
echo "[*] kernel: $KERNEL ($(stat -c%s "$KERNEL") bytes)"

# The canvas drives backboardd's render target.  A stale 1125x2436 ADT makes
# iOS render off-screen and the panel stays black (this happened in Nov 2026).
python - <<'EOF'
import struct, sys
sys.path.insert(0, 'tools')
import adt
root, _ = adt.parse(open('artifacts/dig-0xa.adt', 'rb').read())
stack = [root]
while stack:
    node = stack.pop()
    if node.prop('canvas-width') is not None:
        w = struct.unpack('<I', node.prop('canvas-width'))[0]
        h = struct.unpack('<I', node.prop('canvas-height'))[0]
        break
    stack.extend(getattr(node, 'children', []))
else:
    sys.exit('artifacts/dig-0xa.adt has no canvas-width node')
assert (w, h) == (720, 1280), f'ADT canvas {w}x{h}, panel is 720x1280: the screen would stay black'
print(f'[*] ADT canvas {w}x{h} OK')
EOF

python tools/mkpayload_dig.py "$KERNEL" artifacts/dig-0xa.adt artifacts/dig-ci.payload
python shim/build.py artifacts/dig-ci.payload
echo "[+] ready: artifacts/dig-shim-boot.img"
