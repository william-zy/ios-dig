#!/usr/bin/env bash
# Flash the DIG-AL00 diagnostic shim to the recovery partition and boot it.
#
#   bash tools/test-shim.sh
#
# The phone must be in Android with USB debugging authorized. The shim has no
# payload, so it will halt on the READY screen: that is the expected result.
# Long-press power to leave it, then run tools/restore-twrp.sh from fastboot.
set -euo pipefail
cd "$(dirname "$0")/.."

ADB="../../tools/platform-tools/adb.exe"
FASTBOOT="../../tools/platform-tools/fastboot.exe"
IMG="artifacts/dig-shim-boot.img"

[ -f "$IMG" ] || { echo "missing $IMG; run: python shim/build.py"; exit 1; }

echo "[*] Checking adb device..."
"$ADB" devices

echo "[*] Rebooting to bootloader..."
"$ADB" reboot bootloader

echo "[*] Waiting for fastboot..."
for i in $(seq 1 30); do
    if "$FASTBOOT" devices | grep -q fastboot; then break; fi
    sleep 1
done
"$FASTBOOT" devices

echo "[*] Flashing $IMG to recovery..."
"$FASTBOOT" flash recovery "$IMG"

echo "[*] Rebooting..."
"$FASTBOOT" reboot

echo "[*] Waiting for Android, then rebooting into recovery (the shim)..."
"$ADB" wait-for-device
sleep 5
"$ADB" reboot recovery

cat <<'EOF'

Expected on the 720x1280 screen:

  PROJECT iOS-SWEET -> DIG-AL00 Port
  DEVICE  Huawei Enjoy 6S (MSM8940)
  CPU     8x Cortex-A53 ARMv8.0-A
  FDT     00000000xxxxxxxx
  MMU     4 KiB Granule Active (TTBR0)
  GIC     ARM GICv2 MMIO Ready
  TIMER   Virtual Timer Active (PPI 20)
  STATUS  Checking payload in ramdisk...
  LOADER  no DIGXNU payload in ramdisk
  READY   Shim diagnostics PASS! Halting.

The shim halts here (no payload). Long-press power to shut down.
To restore TWRP: hold Volume Down + Power to enter fastboot, then run
  bash tools/restore-twrp.sh
EOF
