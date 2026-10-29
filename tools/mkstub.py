#!/usr/bin/env python3
"""Pack all XNU segments plus a stub entry for the copy/entry test.

  python tools/mkstub.py KERNEL STUB ADT OUT

The stub runs at 0xfffffff008a00000 (PA 0xa2a00000) instead of XNU's entry,
so the loader's full segment copy is exercised and the stub can dump the
bytes at XNU's entry address for the next shim boot to display.
"""
import os
import struct
import sys

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLS_DIR)
import mkpayload_dig as mp  # noqa: E402
import adt  # noqa: E402

PAGE = 0x1000
STUB_VA = 0xfffffff008a00000


def build(kernel_path, stub_path, adt_path, out_path):
    buf = bytearray(open(kernel_path, "rb").read())
    m = mp.parse_macho(buf)
    nfix = mp.apply_chained_fixups(buf, m)
    segs = [s for s in m["segs"] if s["vmsize"]]
    text = m["segs"][0]
    assert text["name"] == "__TEXT" and text["fileoff"] == 0

    virt_base = text["vmaddr"] & ~(0x2000000 - 1)
    pieces = [(s["vmaddr"], s["vmsize"], buf[s["fileoff"]:s["fileoff"] + s["filesize"]])
              for s in segs]

    stub = open(stub_path, "rb").read()
    pieces.append((STUB_VA, len(stub), stub))

    kernel_end = max(vm + vs for vm, vs, _ in pieces)
    kernel_end = (kernel_end + PAGE - 1) & ~(PAGE - 1)

    adt_blob = open(adt_path, "rb").read()
    root, _ = adt.parse(adt_blob)
    chosen = next(c for c in root.children if c.name == "chosen")
    phys_base, mem_size = struct.unpack("<Q", chosen.prop("dram-base"))[0], \
        struct.unpack("<Q", chosen.prop("dram-size"))[0]

    hdr_size = mp.SEG_TABLE + 32 * len(pieces)
    out = bytearray(hdr_size)
    table = []
    for vmaddr, vmsize, data in pieces:
        off = len(out)
        out += data
        out += b"\0" * (-len(out) & 0xf)
        table.append((vmaddr, vmsize, off, len(data)))
    adt_off = len(out)
    out += adt_blob
    out += b"\0" * (-len(out) & 0xf)

    struct.pack_into("<8sII", out, 0, b"DIGXNU\0\0", 1, len(pieces))
    struct.pack_into("<7Q", out, 0x10, virt_base, STUB_VA, adt_off, len(adt_blob),
                     kernel_end, phys_base, mem_size)
    cl = b"stub"
    out[mp.CMDLINE:mp.CMDLINE + len(cl)] = cl
    for i, t in enumerate(table):
        struct.pack_into("<4Q", out, mp.SEG_TABLE + 32 * i, *t)

    open(out_path, "wb").write(out)
    print(f"[+] stub payload: {out_path} ({len(out):,} bytes)")
    print(f"    fixups {nfix}, virt_base {hex(virt_base)}, stub_va {hex(STUB_VA)}")
    print(f"    kernel_end {hex(kernel_end)}, phys {hex(phys_base)}, mem {hex(mem_size)}")


if __name__ == "__main__":
    if len(sys.argv) != 5:
        print(__doc__)
        sys.exit(1)
    build(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
