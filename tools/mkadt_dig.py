#!/usr/bin/env python3
"""Build the Apple Device Tree (ADT) for Huawei Enjoy 6S (DIG-AL00, MSM8940).

Derived from ios-vince/tools/mkadt_vince.py with the address table replaced
by the live device tree of this phone (docs/硬件档案-DIG-AL00-20261029.md):

- DRAM base 0x20000000, 1.5 GiB contiguous and carveout-free (RAM bank 1).
  Bank 2 (0x80000000) is left to LK/modem/TZ; XNU never sees it as RAM.
- GICv2 Distributor @ 0x0b000000, CPU Interface @ 0x0b002000, virtual timer
  INTID 20 (PPI 4) -- identical to MSM8953.
- Framebuffer @ 0x90001000, 720x1280, 24-bpp RGB888, stride 2160
  (splash_region 0x90000000 + 20 MiB, FT8607 TCL panel).
- SDHCI eMMC controller @ 0x07824900 (same IP as vince).
- FocalTech FT5336 touch controller @ 0x38 on I2C-3 (0x78b7000).
- iPhone X identity for the iOS 16 userland (1125x2436 canvas).
"""
import hashlib
import os
import struct
import sys
import argparse

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLS_DIR)
import adt  # noqa: E402

# DIG-AL00 (MSM8940) hardware definitions
PHYS_BASE = 0x20000000          # RAM bank 1: 0x20000000-0x7fffffff, no carveouts
MEM_SIZE = 0x60000000           # 1.5 GiB

PANIC_LOG_SIZE = 0x100000       # 1 MiB panic log at the top of bank 1

# MPIDR of the CPU LK hands control to (cluster 1 core 0, measured on device)
BOOT_CPU_MPIDR = 0x100

# Non-zero SOC base for arm-io so pe_arm_get_soc_base_phys() returns non-zero
SOC_BASE = 0x01000000

# GICv2 (Qualcomm QGIC2) MMIO addresses -- same as vince
GICD, GICD_SIZE = 0x0b000000, 0x1000
GICC, GICC_SIZE = 0x0b002000, 0x1000

# Framebuffer: continuous splash left by LK (24-bit RGB888, stride 2160)
FB, FB_SIZE = 0x90001000, 720 * 1280 * 3
FB_W, FB_H, FB_STRIDE = 720, 1280, 720 * 3

# Storage: Qualcomm SDHCI eMMC host controller (0x7824900.sdhci)
SDHCI, SDHCI_SIZE = 0x07824900, 0x1000

TIMEBASE = 19200000             # 19.2 MHz Qualcomm XO clock
VTIMER_INTID = 20               # Virtual timer PPI (16 + 4)

DIG_ECID = 0x4449470000000001   # 'DIG' + 1
BOOT_MANIFEST_HASH = hashlib.sha384(b'dig boot manifest').digest()

D22AP_ADT = os.path.join(os.path.dirname(TOOLS_DIR), 'research', 'ipsw-x', 'd22ap.adt')


def d22ap_product(path=D22AP_ADT):
    """Extract /product properties from the iPhone X device tree if present."""
    if os.path.exists(path):
        root, _ = adt.parse(open(path, 'rb').read())
        for c in root.children:
            if dict((k, v) for k, f, v in c.props).get('name') == b'product\0':
                return [(k, v) for k, f, v in c.props if not f and k not in ('name', 'AAPL,phandle')]
    return None


u32 = lambda *v: struct.pack('<%dI' % len(v), *v)
u64 = lambda *v: struct.pack('<%dQ' % len(v), *v)
cstr = lambda s: s.encode() + b'\0'


def node(name, props=(), children=()):
    n = adt.Node()
    n.props = [('name', 0, cstr(name))] + [(k, 0, v) for k, v in props]
    n.children = list(children)
    return n


def build_dig_adt(seed=None, phys_base=None, mem_size=None):
    phys_base = PHYS_BASE if phys_base is None else phys_base
    mem_size = MEM_SIZE if mem_size is None else mem_size

    panic_base = phys_base + mem_size - PANIC_LOG_SIZE
    mem_size -= PANIC_LOG_SIZE

    seed = seed if seed is not None else os.urandom(64)
    phandle = iter(range(1, 1000))
    ph = lambda: ('AAPL,phandle', u32(next(phandle)))

    chosen = node('chosen', [
        ph(),
        ('dram-base', u64(phys_base)),
        ('dram-size', u64(mem_size)),
        ('random-seed', seed),
        ('debug-enabled', u32(1)),
        ('display-scale', u32(3)),
        ('display-rotation', u32(0)),
        ('unique-chip-id', u64(DIG_ECID)),
        ('chip-id', u32(0x8015)),  # Apple A11 Bionic (iPhone X)
        ('board-id', u32(0x16)),
        ('embedded-panic-log-size', u32(PANIC_LOG_SIZE)),
        ('firmware-version', cstr('dig-shim')),
        ('system-firmware-version', cstr('dig-shim')),
        ('boot-manifest-hash', BOOT_MANIFEST_HASH),
        ('crypto-hash-method', cstr('sha2-384')),
        ('certificate-production-status', u32(0)),
        ('effective-production-status-ap', u32(0)),
        ('certificate-security-mode', u32(1)),
        ('effective-security-mode-sep', u32(1)),
    ], [
        node('memory-map', [ph()]),
        node('asmb', [ph(), ('lp-sip0', u64(0x6f)), ('lp-sip1', u32(1))])
    ])

    # GICv2 interrupt controller node (named 'interrupt-controller' for pe_fiq.c)
    gic = node('interrupt-controller', [
        ph(),
        ('compatible', cstr('arm,cortex-a15-gic') + cstr('arm,gic-400') + b'\0'),
        ('reg', u64(GICD, GICD_SIZE, GICC, GICC_SIZE)),
        ('interrupt-controller', b''),
        ('#interrupt-cells', u32(3)),
        ('virtual-timer-intid', u32(VTIMER_INTID)),
    ])
    # Device nodes must name their interrupt controller: IODTFindInterruptParent
    # otherwise falls back to the DT parent, which has no #interrupt-cells and
    # makes IOKit warn on every mapping attempt.
    gic_ph = struct.unpack('<I', gic.prop('AAPL,phandle'))[0]

    # Alias for any lookup of /arm-io/gic
    gic_alias = node('gic', [
        ph(),
        ('compatible', cstr('arm,cortex-a15-gic') + cstr('arm,gic-400') + b'\0'),
        ('reg', u64(GICD, GICD_SIZE, GICC, GICC_SIZE)),
        ('interrupt-controller', b''),
        ('#interrupt-cells', u32(3)),
        ('virtual-timer-intid', u32(VTIMER_INTID)),
    ])

    # Watchdog node with no-pmu flag to prevent watchdogd panic
    wdt = node('wdt', [
        ph(),
        ('no-pmu', u32(1)),
    ])

    # Display subsystem node for backboardd / IOMobileFramebuffer
    disp0 = node('disp0', [
        ph(),
        ('device_type', cstr('display-subsystem')),
        ('compatible', cstr('dig,display') + cstr('sweet,display') + b'\0'),
        # IOMobileFramebuffer reads the canvas from this node. 720x1280 matches
        # the panel 1:1, so backboardd renders straight into panel memory.
        # (Presenting a real iPhone geometry instead removes the rdar bar but
        # needs the scaled present path, which is still being fixed.)
        ('canvas-width', u32(720)),
        ('canvas-height', u32(1280)),
    ])

    # SDHCI eMMC storage node
    sdhci_node = node('sdhci', [
        ph(),
        ('compatible', cstr('generic-sdhci') + cstr('qcom,sdhci-msm-v4') + b'\0'),
        ('reg', u64(SDHCI, SDHCI_SIZE)),
        ('interrupt-parent', u32(gic_ph)),
        ('interrupts', u32(0, 123, 4)),  # SPI 123
    ])

    # FocalTech FT5336 touchscreen (FT8607 panel controller), I2C-3 @ 0x38
    touch_node = node('touchscreen', [
        ph(),
        ('compatible', cstr('focaltech,5336') + b'\0'),
        ('i2c-address', u32(0x38)),
        ('i2c-bus', u32(3)),
        ('interrupt-parent', u32(gic_ph)),
        ('interrupts', u32(0, 65, 2)),  # GPIO 65 (ftech,irq-gpio)
    ])

    # Stub nubs for MobileGestalt's WifiAddress/BluetoothAddress lookups, as in
    # the vince port; without an IONetworkController lsd/SpringBoard wait forever.
    wlan = node('wlan', [
        ph(),
        ('device_type', cstr('wlan')),
        ('compatible', cstr('dig,wlan-stub')),
        ('local-mac-address', bytes([0x02, 0x44, 0x49, 0x47, 0x01, 0x01])),
    ])
    bluetooth = node('bluetooth', [
        ph(),
        ('device_type', cstr('bluetooth')),
        ('compatible', cstr('dig,bluetooth-stub')),
        ('local-mac-address', bytes([0x02, 0x44, 0x49, 0x47, 0x01, 0x02])),
    ])

    arm_io = node('arm-io', [
        ph(),
        ('device_type', cstr('dig-io')),
        ('compatible', cstr('dig-io') + cstr('arm-io') + b'\0'),
        ('#address-cells', u32(2)),
        ('#size-cells', u32(2)),
        ('ranges', u64(0, SOC_BASE, 0x100000000 - SOC_BASE)),
    ], [gic, gic_alias, wdt, disp0, sdhci_node, touch_node, wlan, bluetooth])

    # Framebuffer console node for early kprintf
    fbcon = node('dig-fbcon', [
        ph(),
        ('reg', u64(FB, FB_SIZE)),
        ('width', u32(FB_W)),
        ('height', u32(FB_H)),
        ('stride', u32(FB_STRIDE)),
    ])

    # Compatibility alias for the prebuilt ios-vince kernel: its 0003 patch
    # looks the console up by the node name "vince-fbcon" (or "sweet-fbcon").
    # Our own DIG kernel will look for "dig-fbcon"; keeping both costs nothing.
    fbcon_vince = node('vince-fbcon', [
        ph(),
        ('reg', u64(FB, FB_SIZE)),
        ('width', u32(FB_W)),
        ('height', u32(FB_H)),
        ('stride', u32(FB_STRIDE)),
    ])

    defaults = node('defaults', [
        ph(),
        ('no-effaceable-storage', u32(1)),
    ])

    # iPhone X style: gestures, no physical home button
    buttons = node('buttons', [
        ph(),
        ('button-names', cstr('volup') + cstr('voldown') + cstr('hold')),
        ('home-button-type', u32(2)),
        ('opposed-power-vol-buttons', u32(1)),
    ])

    # Stock DIG-AL00 DTB: 8x Cortex-A53, MPIDR 0x0-0x3 (cluster 0) and
    # 0x100-0x103 (cluster 1). LK boots us on cluster 1 core 0 (MPIDR 0x100,
    # measured on the device via the shim), so that node carries
    # state="running"; ml_parse_cpu_topology() uses it to pick the boot CPU.
    # The payload cmdline still says cpus=1, so only that CPU enters the
    # topology for now.
    cpu_nodes = []
    for core in range(8):
        mpidr = core if core < 4 else 0x100 + core - 4
        c = node(f'cpu{core}', [
            ph(),
            ('device_type', cstr('cpu')),
            ('compatible', cstr('qcom,cortex-a53') + cstr('ARM,v8') + b'\0'),
            ('reg', u32(mpidr)),
            ('cpu-id', u32(core)),
            ('cluster-id', u32(0 if core < 4 else 1)),
            ('cluster-type', u32(0)),
            ('die-cluster-id', u32(0)),
            ('cluster-core-id', u32(core % 4)),
            ('state', cstr('running' if mpidr == BOOT_CPU_MPIDR else 'stopped')),
            ('timebase-frequency', u32(TIMEBASE)),
            ('clock-frequency', u32(1400000000)),
            ('bus-frequency', u32(100000000)),
            ('memory-frequency', u32(800000000)),
            ('peripheral-frequency', u32(TIMEBASE)),
            ('fixed-frequency', u32(TIMEBASE)),
            ('cpu-model', cstr('cortex-a53')),
        ])
        cpu_nodes.append(c)

    cpus = node('cpus', [ph(), ('#address-cells', u32(1)), ('#size-cells', u32(0))], cpu_nodes)

    # Product identity: iPhone X (iPhone10,3 / D22AP)
    product_props = d22ap_product()
    if product_props:
        product = [node('product', [ph()] + product_props)]
    else:
        product = [node('product', [
            ph(),
            ('product-id', u32(0x1003)),
            ('product-name', cstr('iPhone X')),
            ('model-number', cstr('D22AP')),
            ('device-class', cstr('iPhone')),
        ])]

    # Panic log region: /pram reg = <panic_base, PANIC_LOG_SIZE>
    pram = node('pram', [ph(), ('reg', u64(panic_base, PANIC_LOG_SIZE))])

    root = node('device-tree', [
        ph(),
        ('compatible', cstr('D22AP') + cstr('iPhone10,3') + cstr('xiaomi,vince') + cstr('huawei,dig-al00') + cstr('qcom,msm8940') + cstr('AppleARM') + b'\0'),
        ('model', cstr('iPhone10,3')),
        ('target-type', cstr('dig')),
        ('target-sub-type', cstr('dig')),
        ('manufacturer', cstr('Apple Inc.')),
        ('device-id', u64(DIG_ECID)),
        ('timebase-frequency', u32(TIMEBASE)),
        ('#address-cells', u32(2)),
        ('#size-cells', u32(2)),
    ], [chosen, defaults, cpus, arm_io, fbcon, fbcon_vince, buttons, pram] + product)

    return root


def main():
    parser = argparse.ArgumentParser(description="Generate DIG-AL00 Apple Device Tree")
    parser.add_argument("output", help="Output .adt file path")
    parser.add_argument("--phys-base", type=lambda s: int(s, 0), default=PHYS_BASE,
                        help="XNU DRAM base (default 0x20000000; 0xa0000000 matches the vince kernel's PLKSEG assumption)")
    parser.add_argument("--mem-size", type=lambda s: int(s, 0), default=MEM_SIZE,
                        help="XNU DRAM size (default 0x60000000)")
    parser.add_argument("--dump", action="store_true", help="Print human readable tree")
    args = parser.parse_args()

    root = build_dig_adt(phys_base=args.phys_base, mem_size=args.mem_size)
    data = adt.serialize(root)
    with open(args.output, "wb") as f:
        f.write(data)

    print(f"[+] DIG-AL00 ADT successfully generated: {args.output} ({len(data)} bytes)")
    if args.dump:
        print(f"    Nodes serialized: {len(data)} bytes")


if __name__ == "__main__":
    main()
