#!/bin/bash
# Flash the 0194 sweetgl3 kernel and the HFS root image that contains the
# diagnostic sweetgl.dylib.  The phone must be in TWRP.  Leaves it in TWRP;
# reboot when ready to watch the boot.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
ADB="$ROOT/tools/platform-tools/adb.exe"
IMG="$ROOT/repos/ios-dig/artifacts/dig-boot-gpu-sweetgl3.img"
SIZE=17657856
export MSYS_NO_PATHCONV=1

"$ADB" devices | grep -q recovery || { echo "phone is not in TWRP" >&2; exit 1; }
"$ADB" push "$IMG" /cache/boot.img
"$ADB" shell "dd if=/cache/boot.img of=/dev/block/by-name/boot bs=1048576; sync; \
  dd if=/dev/block/by-name/boot bs=1048576 2>/dev/null | head -c $SIZE | sha256sum; \
  rm -f /cache/boot.img"

echo "[*] boot flashed; reflashing userdata (about 13 minutes)"
bash "$ROOT/tools/push-userdata-chunks.sh"
"$ADB" shell "dd if=/dev/zero of=/dev/block/by-name/misc bs=2048 count=1; sync"
echo "[+] done; phone is still in TWRP. Reboot to test."
