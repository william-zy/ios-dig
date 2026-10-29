#!/usr/bin/env bash
# Restore TWRP 3.3.1-0 to the recovery partition.
#
# The phone must be in fastboot (hold Volume Down + Power after a full power
# off, or run `adb reboot bootloader` if Android is still reachable).
set -euo pipefail
cd "$(dirname "$0")/.."

FASTBOOT="../../tools/platform-tools/fastboot.exe"
TWRP="../../roms/diego/twrp_3.3.1.0_diego.img"

[ -f "$TWRP" ] || { echo "missing $TWRP"; exit 1; }

"$FASTBOOT" devices
echo "[*] Restoring TWRP..."
"$FASTBOOT" flash recovery "$TWRP"
"$FASTBOOT" reboot
echo "[+] TWRP restored. Re-enter with: adb reboot recovery"
