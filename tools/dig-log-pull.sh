#!/bin/sh
# Read the DIG persistent console log (xnu patch 0189) from a phone booted into
# TWRP: the last 4 MiB + 512 bytes of userdata hold a "SWEETLOG" header block
# followed by the log bytes, written in order by vince_mmc.c.
#
#   tools/dig-log-pull.sh OUT.txt
#
# Only reads. The area is far past the 16 GiB HFS image, so it never touches it.
set -eu

out=${1:?usage: dig-log-pull.sh OUT.txt}
command -v adb >/dev/null 2>&1 || { echo "Error: adb not found in PATH" >&2; exit 1; }

ADB=${ADB:-adb}
dev=$($ADB shell 'for d in /dev/block/by-name/userdata /dev/block/bootdevice/by-name/userdata; do [ -e $d ] && readlink -f $d && break; done' 2>/dev/null | tr -d '\r')
[ -n "$dev" ] || { echo "userdata block device not found (is the phone in TWRP?)" >&2; exit 1; }

bytes=$($ADB shell blockdev --getsize64 "$dev" | tr -d '\r')
# 4 MiB of data plus one 512-byte header block, rounded to 4 KiB reads.
skip=$((bytes / 4096 - 1025))
$ADB exec-out "dd if=$dev bs=4096 skip=$skip count=1025 2>/dev/null" > "$out.bin"

python3 - "$out.bin" "$out" <<'PY'
import struct, sys

raw = open(sys.argv[1], 'rb').read()
off = raw.find(b'SWEETLOG')
if off < 0:
    sys.exit('no SWEETLOG header in the last 4 MiB: the kernel log thread never wrote '
             '(check sweetlog=1 and mmcrw=1)')
ver, size, total, seq = struct.unpack_from('<IIQQ', raw, off + 8)
start = off + 512
data = raw[start:start + size]
data = data[:total]
open(sys.argv[2], 'wb').write(data)
print(f'header at {off}, version {ver}, area {size} bytes, {total} written, seq {seq}')
print(f'wrote {len(data)} bytes to {sys.argv[2]}')
PY

rm -f "$out.bin"
