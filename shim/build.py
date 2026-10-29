#!/usr/bin/env python3
"""Build the DIG-AL00 (msm8940) boot shim and pack dig-shim-boot.img.

Usage:
    python build.py [PAYLOAD]

Without PAYLOAD the shim is packed with a dummy ADT ramdisk so it can be
flashed alone to verify the framebuffer, GIC, timer and FDT plumbing on the
phone. With PAYLOAD (output of tools/mkpayload_dig.py) the payload becomes
the ramdisk and the shim hands over to XNU.
"""
import os
import sys
import subprocess
import shutil

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHIM_DIR = os.path.join(BASE_DIR, "shim")
OUT_DIR = os.path.join(SHIM_DIR, "out")
ARTIFACTS_DIR = os.path.join(BASE_DIR, "artifacts")
TOOLS_DIR = os.path.join(BASE_DIR, "tools")
DTB_PATH = os.path.join(BASE_DIR, "dtb", "dig-al00.dtb")

os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(ARTIFACTS_DIR, exist_ok=True)


def find_tool(name):
    # Prefer the NDK LLVM tools: the mingw64 ld.lld build rejects -T/-N.
    ndk_bin = os.environ.get("NDK_BIN", r"D:\android-ndk-r27c\toolchains\llvm\prebuilt\windows-x86_64\bin")
    for candidate in (os.path.join(ndk_bin, f"{name}.exe"), shutil.which(name)):
        if candidate and os.path.exists(candidate):
            return candidate
    winget_link = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Links", f"{name}.exe")
    if os.path.exists(winget_link):
        return winget_link
    pkg_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Packages")
    if os.path.exists(pkg_dir):
        for root, _, files in os.walk(pkg_dir):
            if f"{name}.exe" in files:
                return os.path.join(root, f"{name}.exe")
    return name


def build(payload_path=None):
    print("[*] Building DIG-AL00 Boot Shim...")
    clang = find_tool("clang")
    ld_lld = find_tool("ld.lld")
    llvm_objcopy = find_tool("llvm-objcopy")
    llvm_nm = find_tool("llvm-nm")

    print(f"    Compiler: {clang}")
    print(f"    Linker:   {ld_lld}")
    print(f"    Objcopy:  {llvm_objcopy}")

    cflags = [
        "-target", "aarch64-none-elf",
        "-O2", "-ffreestanding", "-nostdlib",
        "-fno-pic", "-mgeneral-regs-only", "-mstrict-align",
        "-fno-stack-protector", "-Wall", "-Wextra",
        "-I", SHIM_DIR
    ]

    sources = ["start.S", "shim.c", "console.c", "mmu.c", "fdt.c", "loader.c"]
    objs = []

    for src in sources:
        src_path = os.path.join(SHIM_DIR, src)
        obj_path = os.path.join(OUT_DIR, os.path.splitext(src)[0] + ".o")
        objs.append(obj_path)

        cmd = [clang] + cflags + ["-c", src_path, "-o", obj_path]
        print(f"[*] Compiling {src}...")
        res = subprocess.run(cmd)
        if res.returncode != 0:
            print(f"[!] Compilation failed for {src}")
            return False

    elf_path = os.path.join(OUT_DIR, "shim.elf")
    ld_script = os.path.join(SHIM_DIR, "shim.ld")
    ld_flags = ["-T", ld_script, "--build-id=none", "-N", "-o", elf_path] + objs

    print("[*] Linking shim.elf...")
    res = subprocess.run([ld_lld] + ld_flags)
    if res.returncode != 0:
        print("[!] Linking failed!")
        return False

    bin_path = os.path.join(OUT_DIR, "Image")
    print(f"[*] Generating binary: {bin_path}...")
    res = subprocess.run([llvm_objcopy, "-O", "binary", elf_path, bin_path])
    if res.returncode != 0:
        print("[!] Objcopy failed!")
        return False

    # Pad binary to _end symbol
    try:
        nm_out = subprocess.check_output([llvm_nm, elf_path], text=True)
        end_size = None
        for line in nm_out.splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[2] == "_end":
                end_size = int(parts[0], 16)
                break
        if end_size:
            with open(bin_path, "a+b") as f:
                cur_len = f.tell()
                if end_size > cur_len:
                    f.write(b"\0" * (end_size - cur_len))
            print(f"    [+] Padded shim binary to _end (0x{end_size:x} bytes)")
    except Exception as e:
        print(f"    [!] Warning during padding: {e}")

    final_shim = os.path.join(ARTIFACTS_DIR, "dig-shim.bin")
    shutil.copyfile(bin_path, final_shim)
    print(f"[+] Final DIG Shim Binary: {final_shim} ({os.path.getsize(final_shim)} bytes)")

    # Append the phone's own DIG-AL00 DTB (extracted from the stock boot.img)
    # so Huawei LK accepts the image. start.S advertises its offset at 0x2c.
    kernel_to_pack = final_shim
    if os.path.exists(DTB_PATH):
        shim_dtb_path = os.path.join(ARTIFACTS_DIR, "dig-shim-dtb.bin")
        with open(final_shim, "rb") as f_shim, open(DTB_PATH, "rb") as f_dtb, open(shim_dtb_path, "wb") as f_out:
            f_out.write(f_shim.read())
            f_out.write(f_dtb.read())
        kernel_to_pack = shim_dtb_path
        print(f"[+] Appended DIG-AL00 DTB: {shim_dtb_path} ({os.path.getsize(shim_dtb_path)} bytes)")
    else:
        print(f"[!] Missing DTB: {DTB_PATH}")

    # Generate the ADT if the build tools are available (dummy ramdisk below)
    adt_path = os.path.join(ARTIFACTS_DIR, "dig.adt")
    if not os.path.exists(adt_path):
        print("[*] Generating dig.adt...")
        subprocess.run([sys.executable, os.path.join(TOOLS_DIR, "mkadt_dig.py"), adt_path])

    if payload_path and os.path.exists(payload_path):
        ramdisk_path = payload_path
        print(f"[+] Using XNU payload as ramdisk: {payload_path}")
    elif os.path.exists(adt_path):
        ramdisk_path = adt_path
        print("[!] No payload given; packing ADT as dummy ramdisk (diagnostics image)")
    else:
        ramdisk_path = None

    bootimg_path = os.path.join(ARTIFACTS_DIR, "dig-shim-boot.img")
    sys.path.append(TOOLS_DIR)
    import mkbootimg_dig
    print("[*] Packing dig-shim-boot.img...")
    sha = mkbootimg_dig.pack_bootimg(
        kernel_path=kernel_to_pack,
        ramdisk_path=ramdisk_path,
        out_path=bootimg_path,
        cmdline="console=null",
        page_size=2048,
    )

    print(f"[SUCCESS] Built {bootimg_path} (SHA256: {sha})")
    return True


if __name__ == "__main__":
    payload = sys.argv[1] if len(sys.argv) > 1 else None
    sys.exit(0 if build(payload) else 1)
