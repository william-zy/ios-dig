#!/usr/bin/env python3
"""Pack an Android boot image (header v0) for Huawei Enjoy 6S (DIG-AL00).

The addresses below were read back from the phone's own stock boot.img
(roms/diego/backup/boot.img, header v0, 2048-byte pages):

    kernel_addr  0x80008000
    ramdisk_addr 0x81000000
    tags_addr    0x80000100
    second_addr  0x80f00000
    page_size    2048

LK may relocate the ramdisk anyway (the running system reports
linux,initrd-start = 0x33000000), so the shim always trusts /chosen.
"""
import argparse
import hashlib
import os
import struct


def round_up(n, page_size):
    return (n + page_size - 1) // page_size * page_size


def pack_bootimg(kernel_path, ramdisk_path, out_path, dtb_path=None,
                 cmdline="console=null", page_size=2048):
    with open(kernel_path, "rb") as f:
        kernel = f.read()

    if ramdisk_path and os.path.exists(ramdisk_path):
        with open(ramdisk_path, "rb") as f:
            ramdisk = f.read()
    else:
        ramdisk = b""

    dtb = b""
    if dtb_path and os.path.exists(dtb_path):
        with open(dtb_path, "rb") as f:
            dtb = f.read()

    base = 0x80000000
    kernel_addr = base + 0x00008000
    ramdisk_addr = base + 0x01000000
    tags_addr = base + 0x00000100
    second_addr = base + 0x00f00000

    magic = b"ANDROID!"
    kernel_size = len(kernel)
    ramdisk_size = len(ramdisk)
    second_size = len(dtb) if dtb else 0
    header_version = 0
    os_version = (6 << 25) | (0 << 22)  # Android 6.0 stand-in (stock is 0)

    cmdline_bytes = cmdline.encode("utf-8")[:512].ljust(512, b"\0")
    name_bytes = b"dig-xnu".ljust(16, b"\0")

    sha = hashlib.sha1()
    sha.update(kernel)
    sha.update(struct.pack("<I", kernel_size))
    sha.update(ramdisk)
    sha.update(struct.pack("<I", ramdisk_size))
    sha.update(dtb if dtb else b"")
    sha.update(struct.pack("<I", second_size))
    id_hash = sha.digest().ljust(32, b"\0")

    header = struct.pack(
        "<8s10I16s512s32s1024s",
        magic,
        kernel_size,
        kernel_addr,
        ramdisk_size,
        ramdisk_addr,
        second_size,
        second_addr,
        tags_addr,
        page_size,
        header_version,
        os_version,
        name_bytes,
        cmdline_bytes,
        id_hash,
        b"\0" * 1024,
    )

    with open(out_path, "wb") as f:
        f.write(header.ljust(page_size, b"\0"))
        if kernel_size > 0:
            f.write(kernel.ljust(round_up(kernel_size, page_size), b"\0"))
        if ramdisk_size > 0:
            f.write(ramdisk.ljust(round_up(ramdisk_size, page_size), b"\0"))
        if second_size > 0:
            f.write(dtb.ljust(round_up(second_size, page_size), b"\0"))

    total_size = os.path.getsize(out_path)
    sha256 = hashlib.sha256(open(out_path, "rb").read()).hexdigest()
    print(f"[+] Boot image packed: {out_path} ({total_size} bytes)")
    print(f"    Kernel: {kernel_size} B, Ramdisk: {ramdisk_size} B, Pagesize: {page_size}")
    print(f"    SHA256: {sha256}")
    return sha256


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pack DIG-AL00 Android boot.img")
    parser.add_argument("--kernel", required=True, help="Kernel binary")
    parser.add_argument("--ramdisk", default=None, help="Ramdisk / payload binary")
    parser.add_argument("--dtb", default=None, help="DTB binary")
    parser.add_argument("--out", required=True, help="Output boot.img")
    parser.add_argument("--cmdline", default="console=null", help="Kernel command line")
    args = parser.parse_args()

    pack_bootimg(args.kernel, args.ramdisk, args.out, args.dtb, args.cmdline)
