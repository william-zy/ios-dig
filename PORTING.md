# vince → DIG-AL00 补丁移植对照表

`xnu/patches/` 目前是 **ios-vince 178 补丁的原样基线**（未改）。本文列出每一处需要动的地方，
按“先能开机、再能显示、最后外设”的顺序排列。地址依据：
`docs/硬件档案-DIG-AL00-20261029.md`（live DT）与 `repos/dig-vendor-kernel/`（华为开源 3.18 内核）。

## 0. 机器配置（先做）

vince 的 178 个补丁里有 38 个用 `#if defined(ARM64_BOARD_CONFIG_VINCE)` 做条件编译，
其中 0090（4K 页 MMU）一个文件就有 63 处。两条路线：

- **路线 A（推荐，改动最小）**：`MACHINE_CONFIG=VINCE` 直接复用。MSM8940 与 MSM8953 同为
  8×Cortex-A53 ARMv8.0-A，cache line 6、4K 页、PSCI 全部相同。先让 shim + 内核跑起来，
  再逐步把 vince 专用驱动换成 DIG。
- **路线 B（最终形态）**：在 0004 里增加 `DIG` 配置：
  `MACHINE_FLAGS_ARM64_DIG = -DARM64_BOARD_CONFIG_DIG -march=armv8-a+crc+crypto -mcpu=cortex-a53`，
  并把 38 个补丁的 `VINCE` 守卫机械替换/扩展为 `DIG`（`#if defined(VINCE) || defined(DIG)`），
  同时把 `vince_adreno.c` 等文件改名为 `dig_*`。

建议先用 A 跑通第一版内核，再用 B 收尾。

## 1. 必须改的地址/参数

| 补丁 | vince 值 | DIG-AL00 值 | 说明 |
| --- | --- | --- | --- |
| 0003 帧缓冲 console | 注释里的 0x90001000 / 1080×2160 / 3240 | **0x90001000 / 720×1280 / 2160** | 实际代码从 ADT 的 `reg/width/height/stride` 读取，ADT 已给对；只需改注释与 fallback |
| 0004 机器配置 | `-mcpu=cortex-a53` | 相同（见 §0） | A53 指令集一致 |
| 0090 4K 页 MMU | FB NC 映射 0x90000000 + 8MB；stage mark 行 2128 | FB 仍是 0x90000000 + 8MB（够覆盖 720p 的 2.76MB）；stage mark 行号改小即可 | 4K 页/pmap 逻辑与 SoC 无关，直接复用 |
| 0091 eMMC root | SDHCI 0x07824900；GCC SDCC1 RCG 偏移按 8953 | SDHCI 相同；**GCC 偏移要按 8940 核对**（qcom,gcc-8940，见 §3） | 卡是 32GB Samsung eMMC |
| 0096 24bpp 打包 | 1080×2160 影子 | 720×1280（从 boot_args 读，代码自适应；注释/常量核对） | 24bpp → 32bpp 影子逻辑不变 |
| 0099 输入 | Synaptics RMI4 @0x20 / I2C-3 | **FocalTech FT5336 @0x38 / I2C-3 (0x78b7000)** | 需要新驱动（见 §4） |
| 0114/0115/0180 CPU 频率 | 2016MHz → 1400MHz（0180） | 原生 1400MHz；0180 可保留 | 8×A53，两个 cluster |
| 0116/0117 fb 缩放/填充 | 1125×2436 → 1000×2160，bar 40 | 1125×2436 → **约 592×1280，bar 64**（公式自适应，核对 touch 映射常量） | 720:1280 = 9:16，iPhone X 是 19.5:9，会上下留黑边 |
| 0127 电池/RTC | PMI8994/8952 系 | 本机 PMIC 走 SPMI（qcom,spmi-pmic-arb @0x200f000），需按 DT 节点核对 | 后期 |
| 0181 GPU | Adreno 506（chipid 0x05000600，650MHz，a506 zap） | **Adreno 505（chipid 0x05000500，450/475MHz，无 zap）** | 见 `docs/GPU-移植分析.md`，实际改动很小 |
| 0119–0178 Wi-Fi/BT | WCN3680 系 / a80211 | WCN3615（pronto 0xa000000，IRQ 145/146） | 最后做 |

## 2. 内存与启动（shim 已处理）

- XNU DRAM 用 **bank1 0x20000000–0x7fffffff**（1.5GB，无 carveout）。ADT 里
  `dram-base=0x20000000`，`dram-size=0x5ff00000`（顶部 1MB 留给 panic log，`/pram`）。
- LK 把 ramdisk（我们的 payload）放在 **0x33000000**（实测 `/chosen`），落在 XNU DRAM 内部。
  loader 先把内核段拷到 0x20000000+，再进 XNU；此后这块内存被 XNU 复用是安全的。
- shim 的 4K 页表已按 bank1/bank2/splash/carveout 分区映射（`shim/mmu.c`），
  0x20000000–0x7fffffff 全部 WB，0x90000000–0x91ffffff 为 NC。
- boot.img 用 header v0 / page 2048，地址与 stock 完全一致：
  kernel 0x80008000、ramdisk 0x81000000、tags 0x80000100、second 0x80f00000。
  DTB 追加在 shim 的 `_end`（0x25000），Image header 0x2c 指向它（Huawei LK 与 vince 的 ABL 同源）。

## 3. GCC / 时钟（0091、0181 都要用）

live DT 的 `qcom,gcc@1800000`（compatible `qcom,gcc-8940`）关键 GDSC：

| 域 | 地址 | GCC 偏移 | vince 偏移 |
| --- | --- | --- | --- |
| gdsc_oxili_gx | 0x185901c | 0x5901c | 0x5901c ✅ |
| gdsc_oxili_cx | 0x1859044（节点名 @185904c，以 reg 为准） | **0x59044** | 0x5904c ⚠ |

结论：**8940 的 GCC 不是 8953 的逐字节副本**。GFX3D 时钟分支（CBCR）偏移需要从
`clock-gcc-8937/8940` 驱动核对（本仓库的华为开源树只带了 `clock-gcc-8953.c`，8937 的驱动缺失）。
在核对之前：
- 0181 的 GX GDSC 写 0x5901c 可用；
- CX GDSC 不要照抄 0x5904c，先按 0x59044 试，或干脆跳过 CX 上电（GX 上电后读 GPU 寄存器验证）。
- eMMC 的 SDCC1 RCG 偏移同理，先读寄存器确认再写。

## 4. 触摸：FocalTech FT5336

live DT：`ftech@38`，`compatible=focaltech,5336`，I2C-3 `0x78b7000`，
`ftech,irq-gpio = <0xa7 0x41 0x2008>`（GPIO 65，下降沿），`ftech,reset-gpio = <0xa7 0x40 0x0>`（GPIO 64），
面板坐标 0x2d0×0x500（720×1280），最多 10 点。

vince 的 0099 是 Synaptics RMI4 协议（0x20），不能直接用。需要写一个最小 FocalTech 驱动：
- QUP I2C 基址 0x78b7000（与 vince 的 I2C-3 相同，QUP 编程模型相同）；
- 上电/复位序列：reset GPIO 拉低 5ms、拉高 5ms、等待 200ms（`ftech,reset-sequence` 类）；
- 读 ID（0xA3 寄存器）确认 0x53/0x36 系；
- 读 0x02 起的触摸报文（FT5336 标准格式：0x02 = 点数，0x03.. 每点 6 字节：X/Y/weight/misc）；
- 以 HID digitizer 事件上报，逻辑坐标映射到 iOS 的 1125×2436 画布（见 0116 的 scale-to-fit 公式）。

## 5. GPU：a505 就是“伪装成 a506”的最简单案例

详见 `docs/GPU-移植分析.md`。一句话：a505 与 a506 同属 a5xx，微码同为 `a530_pm4.fw`/`a530_pfp.fw`，
GMEM 同为 136KB，CP_ME_INIT workaround 同为 0xB；差别只有 chipid、最高频率和 **a505 不需要 zap shader**
（厂商驱动直接写 `A5XX_RBBM_SECVID_TRUST_CNTL=0` 退出 secure mode）。所以 0181 的 11 步里，
第 10 步的 PIL/zap 整段可以删掉，换成一行寄存器写；其余步骤基本原样可用。

## 6. 建议的里程碑顺序

1. **shim 诊断**（本仓库已就绪）：屏幕出字，确认 FB/GIC/timer/FDT/initrd。
2. **XNU 空转**：用 vince 补丁 + MACHINE_CONFIG=VINCE 编一版内核，payload 进 ramdisk，
   看 XNU 的 kprintf 是否出现在 720p 屏幕上（0003/0090/0096 的地址先改对）。
3. **eMMC + HFS+ root**：0091 + 0094/0095，确认 SDHCI 和 GCC SDCC1 时钟。
4. **iOS userland**：launchd/backboardd/SpringBoard，CPU 渲染。
5. **触摸/按键**：FT5336 + GPIO 91 volup + PMIC 电源键。
6. **GPU**：0181 改 a505（无 zap）。
7. **Wi-Fi/BT**：WCN3615，最后。
