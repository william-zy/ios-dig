#!/usr/bin/env python3
"""Pack the tiny handover-test payload for the DIG shim.

  python tools/mktiny.py shim/out/tiny.bin artifacts/dig-0xa.adt artifacts/dig-tiny.payload

The payload has one segment at virt_base 0 / phys_base 0xa0000000, so the
shim's loader copies the code to 0xa0000000 and jumps to it. The ADT is
appended only because the loader copies it before the handover.
"""
import os
import struct
import sys

BOOT_LINE_LENGTH = 608
CMDLINE = 0x48
SEG_TABLE = CMDLINE + BOOT_LINE_LENGTH  # 0x2a8


def build(code_path, adt_path, out_path):
    code = open(code_path, "rb").read()
    adt_blob = open(adt_path, "rb").read()

    nsegs = 1
    hdr_size = SEG_TABLE + 32 * nsegs
    code_off = hdr_size
    code_padded = code + b"\0" * (-len(code) & 0xf)
    adt_off = code_off + len(code_padded)
    kernel_end = 0x100000  # arbitrary, aligned; ADT goes at phys_base + this

    out = bytearray(hdr_size)
    out += code_padded
    out += adt_blob
    out += b"\0" * (-len(out) & 0xf)

    struct.pack_into("<8sII", out, 0, b"DIGXNU\0\0", 1, nsegs)
    struct.pack_into("<7Q", out, 0x10, 0, 0, adt_off, len(adt_blob), kernel_end,
                     0xa0000000, 0x3ff00000)
    cl = b"tiny"[:BOOT_LINE_LENGTH - 1]
    out[CMDLINE:CMDLINE + len(cl)] = cl
    struct.pack_into("<4Q", out, SEG_TABLE, 0, len(code), code_off, len(code))

    open(out_path, "wb").write(out)
    print(f"[+] tiny payload: {out_path} ({len(out)} bytes, code {len(code)} B)")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(1)
    build(sys.argv[1], sys.argv[2], sys.argv[3])
