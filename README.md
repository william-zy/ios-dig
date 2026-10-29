# ios-dig — msm8940 bringup 骨架

Huawei Enjoy 6S（DIG-AL00，Snapdragon 435 / MSM8940，8×Cortex-A53）的 ios-sweet 移植骨架，
以 [ios-vince](https://github.com/ios-sweet/ios-vince)（MSM8953）为模板，地址表全部取自本机
live 设备树（`docs/硬件档案-DIG-AL00-20261029.md`）。

> 目标：XNU-8796 + iPhone X iOS 16.7.16 userland。当前阶段只做 **shim + ADT + boot.img**，
> 即“屏幕上能出字”的第一里程碑；XNU 补丁移植尚未开始。

## 当前状态（2026-10-30）

| 项 | 状态 |
| --- | --- |
| `shim/` 适配 msm8940（RAM/FB/MMU/loader） | ✅ 已编译通过（clang 19 + lld 18/19，aarch64-none-elf） |
| `tools/mkadt_dig.py` + 校验 | ✅ 生成 10,780 B ADT，7 项检查全过 |
| `artifacts/dig-shim-boot.img` | ✅ 421,888 B，header v0 / page 2048，地址与 stock boot.img 完全一致 |
| DIG-AL00 单板 DTB 提取 | ✅ `dtb/dig-al00.dtb`（stock.dtb 7 个板型中的第 3 个，254,246 B） |
| 真机 shim 诊断 | ⏳ 未刷（镜像已就绪，步骤见下） |
| XNU 补丁移植 | ❌ 未开始（`xnu/patches/` 是 vince 178 补丁基线，对照表见 `PORTING.md`） |
| GPU（Adreno 505） | 📋 分析完成，结论见 `docs/GPU-移植分析.md` |

## 关键地址（来自 live DT）

| 项 | DIG-AL00 | 与 vince 对比 |
| --- | --- | --- |
| RAM（XNU DRAM） | **0x20000000 + 0x60000000**（bank1，1.5GB，无保留区） | vince 用 0xa0000000 |
| LK 实际 ramdisk | **0x33000000**（`/chosen` initrd-start） | 不同 |
| splash / FB | **0x90000000 + 20MB，图像在 +0x1000**，720×1280 RGB888，stride 2160 | 尺寸/步长不同 |
| GIC | GICD 0x0b000000 / GICC 0x0b002000，vtimer INTID 20 | ✅ 相同 |
| eMMC SDHCI | 0x07824900（+ core 0x07824000 / cmdq 0x07824e00） | ✅ 相同 |
| 面板 | FT8607 TCL 720p video，24bpp，4 lane | 不同（vince 1080p） |
| 触摸 | FocalTech FT5336 @0x38，I2C-3 (0x78b7000)，IRQ GPIO65 | 不同（vince Synaptics RMI4） |
| GPU | Adreno 505，kgsl 0x1c00000，SMMU 0x1c40000，chipid 0x05000500 | 同族 a5xx |
| GCC | 0x1800000（qcom,gcc-8940），GPU GDSC GX 0x5901c / CX **0x59044** | CX 偏移与 vince 不同 |

## 构建

```bash
cd repos/ios-dig

# 1. Apple Device Tree
python tools/mkadt_dig.py artifacts/dig.adt
python tools/verify_adt_dig.py artifacts/dig.adt

# 2. shim + boot.img（诊断镜像，ramdisk 用 ADT 占位）
python shim/build.py
# -> artifacts/dig-shim-boot.img

# 可选：在电脑上预览 720x1280 的 console 布局（输出 out/host.ppm）
cd shim && gcc -O1 -I. -o out/host_test console.c host_test.c && ./out/host_test && cd ..

# 3. 将来：XNU 内核 + payload 进 ramdisk
python tools/mkpayload_dig.py xnu/out/kernel.development.dig artifacts/dig.adt artifacts/dig.payload
python shim/build.py artifacts/dig.payload
```

工具链：`shim/build.py` 自动优先使用 `D:\android-ndk-r27c\...\bin` 的 clang/ld.lld
（mingw64 自带的 ld.lld 19.1.1 拒绝 `-T`，不要用）。

## 真机诊断（刷 recovery，可逆）

本机 LK 的 `fastboot boot` 对真实镜像会卡死（2026-10-29 实测），所以走 recovery 分区：

```bash
adb reboot bootloader
fastboot flash recovery repos/ios-dig/artifacts/dig-shim-boot.img
fastboot reboot
adb wait-for-device && adb reboot recovery      # 注意：fastboot reboot recovery 只会普通重启
```

预期屏幕（720×1280，深蓝底）：

```
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
```

- `FDT` 非 0、`LOADER` 能读到 ramdisk（而不是 "no initrd in /chosen"）→ LK 的 DTB/initrd 通路正常。
- 如果屏幕无输出：先确认 FB 是否在 0x90001000（改 `shim/console.h` 的 `FB_BASE` 为 0x90000000 再试一次）。
- 退出：长按电源键关机；要回 TWRP：关机后 **音量下 + 电源** 进 fastboot，
  `fastboot flash recovery roms/diego/twrp_3.3.1.0_diego.img`。

> 诊断镜像没有 payload，shim 会一直停在 READY 界面，这是预期行为。

## 下一步

1. **真机 shim 诊断**：`bash tools/test-shim.sh`（刷 recovery + 进 recovery），确认屏幕输出；
   回滚 `bash tools/restore-twrp.sh`（需先进 fastboot）。
2. **XNU 内核**：把 `xnu/patches/`（vince 基线）推到 GitHub，用 `.github/workflows/xnu-dig.yml`
   跑 macOS CI（`MACHINE_CONFIG=VINCE`，路线 A）；产物 `kernel.development.*` 下载到 `xnu/out/`。
3. **iPhone X product 节点**：从 IPSW 提取 `DeviceTree.d22ap.im4p` → `research/ipsw-x/d22ap.adt`，
   `mkadt_dig.py` 会自动优先使用它（否则用内置的 4 属性 fallback）。
4. **payload**：`python tools/mkpayload_dig.py xnu/out/kernel.development.dig artifacts/dig.adt artifacts/dig.payload`，
   再 `python shim/build.py artifacts/dig.payload`，得到带内核的 boot.img。
5. 按 `PORTING.md` 的里程碑顺序：eMMC/HFS+ → iOS userland → 触摸/按键 → GPU → Wi-Fi。

## 目录

```
repos/ios-dig/
├── shim/            # 引导 shim（start.S / mmu.c / console.c / fdt.c / loader.c / build.py）
├── tools/           # mkadt_dig / mkbootimg_dig / mkpayload_dig / verify_adt_dig / adt.py
├── dtb/             # dig-al00.dtb（单板）+ stock/ 下 7 个原厂板型 DTB
├── xnu/patches/     # vince 178 补丁基线（未改，见 PORTING.md）
├── docs/            # GPU 移植分析
└── artifacts/       # 构建产物
```
