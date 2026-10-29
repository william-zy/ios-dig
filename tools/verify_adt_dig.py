#!/usr/bin/env python3
"""Verify a generated DIG-AL00 ADT against the hardware table.

Guards against copy-paste regressions from the vince/sweet ports: every
address here comes from docs/硬件档案-DIG-AL00-20261029.md.
"""
import sys
import os
import struct

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLS_DIR)
import adt  # noqa: E402

TRAPS = {
    "sweet_gicd": 0x17a00000,     # GICv3 on SM7150
    "sweet_fb": 0x9c000000,       # sweet splash
    "sweet_ufs": 0x01d84000,      # sweet UFS
    "vince_fb_w": 1080,           # vince panel
    "vince_fb_h": 2160,
}

DRAM_BASE = 0x20000000
DRAM_END = 0x80000000             # bank 1 ends here; carveouts start at 0x83100000
# Free DRAM windows on this phone (live DT reserved-memory map):
#   bank 1: 0x20000000-0x7fffffff (no carveouts)
#   bank 2 upper: 0x92500000-0xdfffffff (everything below 0x92500000 is reserved)
FREE_WINDOWS = [(0x20000000, 0x80000000), (0x92500000, 0xE0000000)]
FB_BASE = 0x90001000
FB_W, FB_H = 720, 1280
GICD, GICC = 0x0b000000, 0x0b002000
SDHCI = 0x07824900
TOUCH_ADDR, TOUCH_BUS = 0x38, 3


def verify_adt(adt_path):
    print(f"[*] Verifying DIG-AL00 ADT: {adt_path}")
    assert os.path.exists(adt_path), f"File not found: {adt_path}"

    with open(adt_path, "rb") as f:
        data = f.read()

    root, _ = adt.parse(data)
    props = {k.decode() if isinstance(k, bytes) else k: v for k, _, v in root.props}

    target_type = props.get("target-type", b"").rstrip(b"\0").decode()
    assert target_type == "dig", f"Target type mismatch: {target_type} != dig"
    print("  [PASS] Target type is 'dig'")

    arm_io = None
    chosen = None
    for c in root.children:
        c_name = dict((k.rstrip(b'\0').decode() if isinstance(k, bytes) else k, v)
                      for k, _, v in c.props).get("name", b"").rstrip(b'\0').decode()
        if c_name == "arm-io":
            arm_io = c
        elif c_name == "chosen":
            chosen = c

    assert arm_io is not None, "arm-io node missing"
    assert chosen is not None, "chosen node missing"

    chosen_props = dict((k.rstrip(b'\0').decode() if isinstance(k, bytes) else k, v)
                        for k, _, v in chosen.props)
    dram_base, = struct.unpack("<Q", chosen_props["dram-base"])
    dram_size, = struct.unpack("<Q", chosen_props["dram-size"])
    print(f"  [PASS] DRAM Base: 0x{dram_base:x}, Size: 0x{dram_size:x}")
    in_free = any(dram_base >= lo and dram_base + dram_size <= hi for lo, hi in FREE_WINDOWS)
    assert in_free, (f"DRAM 0x{dram_base:x}+0x{dram_size:x} is outside the free windows "
                     f"{[hex(x) for x in FREE_WINDOWS]}")
    print("  [PASS] DRAM stays inside a carveout-free window")

    seen = set()
    for dev in list(arm_io.children) + list(root.children):
        dev_props = dict((k.rstrip(b'\0').decode() if isinstance(k, bytes) else k, v)
                         for k, _, v in dev.props)
        name = dev_props.get("name", b"").rstrip(b"\0").decode()

        if name == "dig-fbcon":
            w, = struct.unpack("<I", dev_props["width"])
            h, = struct.unpack("<I", dev_props["height"])
            stride, = struct.unpack("<I", dev_props["stride"])
            fb_reg = struct.unpack("<2Q", dev_props["reg"])
            assert fb_reg[0] != TRAPS["sweet_fb"], "REGRESSION: FB uses sweet 0x9c000000!"
            assert fb_reg[0] == FB_BASE, f"FB reg mismatch: 0x{fb_reg[0]:x} != 0x{FB_BASE:x}"
            assert (w, h) == (FB_W, FB_H), f"FB dimensions {w}x{h} != {FB_W}x{FB_H}"
            assert stride == FB_W * 3, f"FB stride {stride} != {FB_W * 3}"
            print(f"  [PASS] Framebuffer verified: 0x{fb_reg[0]:x} ({w}x{h}, stride {stride})")
            seen.add("fb")

        elif name == "interrupt-controller":
            gic_reg = struct.unpack("<4Q", dev_props["reg"])
            assert gic_reg[0] != TRAPS["sweet_gicd"], "REGRESSION: GICD uses sweet GICv3 0x17a00000!"
            assert gic_reg[0] == GICD, f"GICD reg mismatch: 0x{gic_reg[0]:x} != 0x{GICD:x}"
            assert gic_reg[2] == GICC, f"GICC reg mismatch: 0x{gic_reg[2]:x} != 0x{GICC:x}"
            print(f"  [PASS] GICv2 verified: GICD=0x{gic_reg[0]:x}, GICC=0x{gic_reg[2]:x}")
            seen.add("gic")

        elif name == "sdhci":
            sdhci_reg = struct.unpack("<2Q", dev_props["reg"])
            assert sdhci_reg[0] != TRAPS["sweet_ufs"], "REGRESSION: Storage uses sweet UFS 0x01d84000!"
            assert sdhci_reg[0] == SDHCI, f"SDHCI reg mismatch: 0x{sdhci_reg[0]:x} != 0x{SDHCI:x}"
            print(f"  [PASS] SDHCI eMMC controller verified: 0x{sdhci_reg[0]:x}")
            seen.add("sdhci")

        elif name == "touchscreen":
            i2c_addr, = struct.unpack("<I", dev_props["i2c-address"])
            i2c_bus, = struct.unpack("<I", dev_props["i2c-bus"])
            assert i2c_addr == TOUCH_ADDR and i2c_bus == TOUCH_BUS, \
                f"Touchscreen mismatch: bus {i2c_bus}, addr 0x{i2c_addr:x}"
            print(f"  [PASS] FocalTech FT5336 verified: Bus {i2c_bus}, Addr 0x{i2c_addr:x}")
            seen.add("touch")

    missing = {"fb", "gic", "sdhci", "touch"} - seen
    assert not missing, f"Missing nodes: {missing}"

    print("[SUCCESS] All DIG-AL00 ADT checks passed with zero vince/sweet regressions!")
    return True


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "artifacts/dig.adt"
    verify_adt(path)
