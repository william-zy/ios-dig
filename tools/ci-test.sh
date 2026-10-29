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

python tools/mkpayload_dig.py "$KERNEL" artifacts/dig-0xa.adt artifacts/dig-ci.payload
python shim/build.py artifacts/dig-ci.payload
echo "[+] ready: artifacts/dig-shim-boot.img"
