#!/usr/bin/env python3
"""Convert an a5xx firmware file into a C byte array header.

    python tools/fw2c.py roms/diego/firmware-gpu/a530_pm4.fw a530_pm4_fw out.h

The XNU Adreno bring-up driver (vince 0181) embeds the microcode as
`static const uint8_t NAME[]` plus `static const uint32_t NAME_size`, and
copies from offset 4 (the firmware's first dword is a header). For the
DIG-AL00 a505, use the phone's own /system/etc/firmware files:

    a530_pm4.fw   19,572 B   version 0x5ff063
    a530_pfp.fw   15,876 B

Do not reuse the a506 arrays embedded in the vince patch: they are a
different microcode version (19,652 / 16,820 B, version 0x5ff066).
"""
import sys


def convert(src, name, out_path):
    data = open(src, "rb").read()
    lines = [f"/* Generated from {src} ({len(data)} bytes) */",
             "#include <stdint.h>",
             "",
             f"static const uint8_t {name}[] __attribute__((aligned(4096))) = {{"]
    for i in range(0, len(data), 16):
        chunk = ", ".join(f"0x{b:02x}" for b in data[i:i + 16])
        lines.append(f"    {chunk},")
    lines.append("};")
    lines.append("")
    lines.append(f"static const uint32_t {name}_size = {len(data)};")
    lines.append("")
    open(out_path, "w", encoding="utf-8").write("\n".join(lines))
    print(f"[+] {out_path}: {name}, {len(data)} bytes")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(1)
    convert(sys.argv[1], sys.argv[2], sys.argv[3])
