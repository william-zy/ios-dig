# Adreno 505 移植分析（DIG-AL00 / MSM8940）

> 结论先说：**你的“同架构 GPU 可以伪装”推测在这里成立，而且比黑苹果的 G1→G7 更简单**——
> a505 与 a506 共用同一套 a5xx 微码、同一个 CP_ME_INIT workaround、同样 136KB GMEM；
> 真正要改的只有 chipid、频率、以及“a505 根本不需要 zap shader”这一点。
> 证据来自本机 live DT + 华为开源内核 `repos/dig-vendor-kernel/`（MSM8940 的 3.18 厂商树）。

## 1. 硬件事实（live DT）

| 项 | Adreno 505（本机） | Adreno 506（vince） |
| --- | --- | --- |
| `qcom,chipid` | **0x05000500** | 0x05000600 |
| kgsl 寄存器 | 0x1c00000 + 0x40000 | 0x1c00000 + 0x40000 |
| SMMU | 0x1c40000（kgsl-smmu-v2） | 0x1c40000 |
| IRQ | 33 | 33 |
| GMEM | **136KB**（厂商 `gmem_size = SZ_128K + SZ_8K`） | 136KB |
| 最高频率 | **450MHz（speed-bin 0）/ 475MHz（bin 1）** | 650MHz |
| qfprom（GPU 保险丝） | **0xa0000 + 0x6fff**（kgsl 第二段 reg，`qcom,gpu-speed-bin = <0x6018 ...>`） | 0x78000 系 |
| zap shader | **不需要**（gpulist 无 `zap_name`） | `a506_zap` |

## 2. 厂商驱动给出的直接证据

`repos/dig-vendor-kernel/adreno-gpulist.h` 的 a505 条目：

```c
{
    .gpurev = ADRENO_REV_A505,
    .core = 5, .major = 0, .minor = 5, .patchid = ANY_ID,
    .features = ADRENO_PREEMPTION | ADRENO_64BIT,   /* 没有 CONTENT_PROTECTION */
    .pm4fw_name = "a530_pm4.fw",
    .pfpfw_name = "a530_pfp.fw",
    /* 没有 .zap_name */
    .gmem_size = (SZ_128K + SZ_8K),
    ...
}
```

a506 条目除了 `features` 多 `ADRENO_CONTENT_PROTECTION | ADRENO_CPZ_RETENTION`、
多一个 `.zap_name = "a506_zap"`、频率更高之外，其余（微码名、GMEM、protected regs、busy mask）完全相同。

`adreno_a5xx.c`：

```c
static int _me_init_ucode_workarounds(...)
{
    switch (ADRENO_GPUREV(adreno_dev)) {
    case ADRENO_REV_A510: return 0x00000001;
    case ADRENO_REV_A505:
    case ADRENO_REV_A506:
    case ADRENO_REV_A530: return 0x0000000B;   /* ← vince 0181 里的 word 0xb 对 a505 同样正确 */
    ...
}
```

退出 secure mode 的路径：

```c
if (ADRENO_FEATURE(adreno_dev, ADRENO_CONTENT_PROTECTION))
    a5xx_switch_to_unsecure_mode(...);          /* a506：PIL 载入 zap shader + CP_SET_SECURE_MODE 0 */
else
    kgsl_regwrite(&adreno_dev->dev,
                  A5XX_RBBM_SECVID_TRUST_CNTL, 0x0);   /* a505：一行寄存器写 */
```

## 3. 微码：用手机自己的 a530 文件，不要用 vince 内嵌的

本机 `/system/etc/firmware/` 实际文件（已拉到 `roms/diego/firmware-gpu/`）：

| 文件 | 大小 | 用途 |
| --- | --- | --- |
| `a530_pm4.fw` | 19,572 B | a505/a506 共用 PM4 微码（版本 0x5ff063） |
| `a530_pfp.fw` | 15,876 B | a505/a506 共用 PFP 微码 |
| `a530_gpmu.fw2` | 8,052 B | GPMU（a505 的 gpucore 没有 gpmufw_name，可不载） |
| `a530v1_*` / `a530v2/v3_*` | — | a530v1/v2/v3 专用，a505 不用 |

vince 0181 内嵌的是 `a530_pm4_fw` 19,652 B / `a530_pfp_fw` 16,820 B（首 dword 0，版本 0x5ff066），
与本机文件**不是同一版本**。移植时应把上表的两个文件转成 C 数组（保留首 4 字节头，
驱动照 vince 的做法从 offset 4 开始拷、长度减 4）。

## 4. 0181 的 11 步里具体改什么

| 步骤 | vince 0181 | DIG-AL00 改法 |
| --- | --- | --- |
| 1 GCC 时钟/GDSC 读 | GCC 0x1800000，GX 0x5901c，CX 0x5904c | GX 0x5901c ✅；**CX 改 0x59044**（live DT `gdsc@1859044`）；分支时钟偏移待 8937 驱动核对 |
| 2 QFPROM 速度档/chipid | QFPROM 0x78000 | **QFPROM 0xa0000**，速度档 fuse 0x6018；chipid 直接硬编码 0x05000500 |
| 3 CX GDSC 上电 | 0x5904c | 0x59044（或先跳过，靠 GX 上电后读寄存器验证） |
| 4 GX GDSC + clamp | 0x5901c / 0x5b00c | 相同（待确认 clamp 偏移） |
| 5 GCC 分支时钟 | 0x59020/24/28/30/34/40/44 + crypto 0x160xx | 偏移需按 8940 核对；crypto 时钟只有走 PIL 时才需要，a505 无 zap 可省 |
| 6 TZ restore_sec_cfg(18) | vince 需要 | **先跳过**：a505 无 content protection，厂商驱动没有这一步 |
| 7 a5xx_hw_init | mainline drm/msm 寄存器序列 | 原样；a505/a506 同 IP |
| 8 PM4/PFP + ring | `a530_pm4_fw` / `a530_pfp_fw` | 换成手机的两个文件（同版本号 0x5ff063） |
| 9 CP_ME_INIT + 首条命令 | workaround word 0xb | **0xb 不变**（厂商源码明确 a505 也是 0xb） |
| 10 zap shader | PIL 13 + TZ + CP_SET_SECURE_MODE 0 | **整段删除**，改为 `RBBM_SECVID_TRUST_CNTL = 0` |
| 11 secure 后命令 | — | 保留 |

`vince_gpu_parameter()` 的返回值也要改：

| 参数 | vince | DIG |
| --- | --- | --- |
| MSM_PARAM_GPU_ID | 506 | **505** |
| MSM_PARAM_CHIP_ID | 0x05000600 | **0x05000500** |
| MSM_PARAM_GMEM_SIZE | 136×1024 | 不变 |
| MSM_PARAM_MAX_FREQ | 650MHz | **450MHz**（或按 fuse 读 475MHz） |
| MSM_PARAM_GMEM_BASE | 0x100000 | 不变（驱动自选的 GPU 地址空间偏移） |

## 5. 关于“伪装成 a506”的两种做法

- **做法 1（推荐）**：按上表把驱动改成 a505。这是“用对型号”，不是伪装，风险最低。
- **做法 2（纯伪装）**：驱动一行不改，把 `MSM_PARAM_CHIP_ID` 报成 0x05000600，
  并保留 0181 的 a506 zap shader。风险：a505 没有 content protection，
  TZ 的 PIL 13 可能直接拒绝 a506 zap（签名/配置不匹配），第 10 步会失败；
  而且 a506 的 zap 会按 a506 的寄存器写，a505 的 RBBM 布局未必一致。
  **不建议**，但可以作为“驱动改不动时”的对照实验。

## 6. 黑苹果类比的边界

Ice Lake G1→G7 能成立，是因为同一代 iGPU 的 EU 数量/频率不同、指令集与驱动路径相同。
a505→a506 同理：同一代 a5xx、同一套微码、同一套寄存器初始化；差异在：
1. chipid 与 fuse（驱动读它决定参数）；
2. 频率/电压档（电源管理，不影响 3D 核心启动）；
3. secure boot 配置（a506 有 content protection，a505 没有）——这反而让 a505 **更简单**。

所以这里不需要“骗过硬件”，只需要把驱动里的三个常量（chipid、频率、zap 路径）改对。


## 7. 实测进展（2026-11-03，DIG-AL00）

驱动以 `0192-vince-dig-adreno-505.patch` 叠加在 vince 0181 上，boot arg：
`diggpu=1 adreno=N digscm=0/1 adreno_pause=2500`。

已确认（持久日志 `artifacts/log-gpu*.txt`）：

| 步骤 | 实测值 | 结论 |
| --- | --- | --- |
| step1 | `CX_GDSC=0x80000000 GX_GDSC=0x222001 AHB=0x80008000 GFX=0x80004ff0` | CX 已开，GX 关闭，两个 GPU 分支都 CLK_OFF |
| step2 | QFPROM 0x6018 = `0x3cd0 0x1000` | 0xa0000 基址正确，速度档 fuse 可读 |
| step3 | CX `0x80000000` | 已经开启 |
| step4 | GX 上电后 `0xa0222000`；GFX LDO CTRL 写 0x80000038 读回 `0x38`、STATUS=0 | GDSC 报 on，但 GFX LDO 的 bit31 不置位（status），GPU 电源仍可疑 |
| step5 | 候选源 `0x107/0x108`：`CMD=0x2 GFX=0x4ff1`（GFX CLK_OFF=0）；`0x507/0x1/0x307/0x207` 全部 `CMD=0x3`（update pending） | **GFX3D RCG 正确源是 0x107/0x108（GPLL0/8），不是 8953 的 0x507** |
| step5 | `AHB=0x90008001` 始终 CLK_OFF=1；GMEM CBCR 读回 0 | AHB 分支无法点亮，step6 第一次读 GPU 寄存器即同步外部中止（esr 0x96000010） |

待解决：
- AHB 分支的根时钟/父源：AHB CBCR 的 bit28/bit15 含义未确认；GMEM CBCR (0x59024) 读回 0。
- GX GDSC 的 periph-retain（bit14）已加入下一版测试。
- GFX LDO（0x185f000）的使能序列；vince 参考值 0x80000038 在 DIG 上 bit31 不置位。
- 若仍不行，需要从 stock 内核反汇编 msm_gfx_ldo / gdsc 序列，或核对 8937 的 OXILI AHB root。


## 8. 实测成功：Adreno 505 全流程点亮（probe11，2026-11-04）

### 8.1 最终可用的上电顺序（dig_mode）

1. **CX GDSCR = 0x59044**（不是 8953 的 0x5904c）：写 bit0 SW_COLLAPSE=0，轮询 bit31。
2. **先启动 gfx3d root**（`qcom,enable-root-clk`）：CFG=0x107（GPLL0/8），
   CMD bit0 update → 轮询清零 → CMD bit1 root enable，CMD 读回 0x2。
3. **BHS 控制 0x185f01c**：bit0=0、bit9=0、bit4=1（a505 纯 BHS，无 gfx-ldo 节点）；
   不要写 bit31。
4. **GX GDSCR = 0x5901c**：写 SW_COLLAPSE=0 → 轮询 bit31=1（0xa0222000）；
   再读 0x185f028 的 bit1 BHS_EN_REST_ACK（本次 10 ms 内未置位，但后续访问正常）。
5. 分支时钟：GFX3D CBCR(0x59020) bit0、OXILI_AHB(0x59028) bit0（CLK_OFF 清零为
   0x20008001）、GMEM(0x59024)、AON=**0x5904c**、TIMER(0x59040)、BIMC_GPU/GFX。
6. GPU 寄存器 0x1c00000 可读：RBBM_AHB_CNTL0=0x1、VBIF_VER=0x200c0000。
7. TZ `restore_sec_cfg(18)` 仍需要（返回 0）；a505 不需要 zap，step10 只清
   RBBM_SECVID_TRUST_CNTL。

### 8.2 微码与命令处理器

- 使用手机自己的 `a530_pm4.fw`(19572 B, 0x5ff063) / `a530_pfp.fw`(15876 B, 0x5ff087)，
  嵌入 `bsd/dev/dig_gpu_firmware.h`，由 `diggpu=1` 选择。
- 日志（`artifacts/log-gpu11.txt`）：

```
step 8: loading PM4 (19572 B) / PFP (15876 B) ... ME running
step 9: CP_MEM_WRITE -> 0xc0ffee01 (the GPU executed its first command), RPTR=13
step 10: a505 skips the zap shader; RBBM_SECVID_TRUST_CNTL cleared
step 11: CP_MEM_WRITE -> 0xc0ffee02; RBBM_STATUS=0x1 INT0=0 RPTR=17
step 11: Adreno 506 command processor is up
```

### 8.3 产物与回归

- 镜像：`repos/ios-dig/artifacts/dig-boot-gpu-probe11.img`
  SHA256 `4effa0faf52145104cd0da08e6ae6875d32a8001f0bccbcabbc335886c6fd5f3`；
  CI run 41696601004，commit `bba499a`。
- cmdline：`vincec0=1094 diggpu=1 adreno=11 digscm=1 adreno_pause=1000`。
- 该 probe11 镜像当时用的是 1125x2436 的错误 ADT，所以屏幕黑；内核 GPU 本身成功。

## 9. 黑屏渲染路径的根因（2026-11-04 晚修正）

### 9.1 根因：打包用了错误的 ADT（已实测确认）

- 之前的“新内核触发 3x 路径”结论是误判。黑屏镜像与正常镜像的内核日志
  CPU/时钟/FB 一致，真正的差异在 **boot.img 内嵌的 ADT**：
  - `dig-boot-8core.img`（正常）：ADT = `artifacts/dig.adt`，
    disp0 canvas **720x1280**（SHA256 `762d5fc6…`）。
  - 所有黑屏镜像（probe11/exactstable-cmd/c0v3/c0off/native0）：
    ADT = 旧的 `artifacts/dig-0xa.adt`，canvas **1125x2436**
    （SHA256 `89859c37…`）。
- backboardd 按 ADT canvas 建渲染目标：1125x2436；显示面 720x1280 需要
  `AppleM2ScalerCSCDriver` 缩放，而本移植没有该驱动，于是不 swap、黑屏。
- 把 `dig-0xa.adt` 换成 720x1280 后，**同一个含 0192 + 微码的内核** + 8 核 +
  `diggpu=1 adreno=11` 正常进桌面；Adreno 505 step1-11 全过，`VinceGPU` 注册。
  镜像：`artifacts/dig-boot-gpu-720.img`，SHA256 `afefb2db…`，
  日志 `artifacts/log-gpu720.txt`。

### 9.2 防呆与当前状态

- `tools/ci-test.sh` 硬性检查 ADT canvas = 720x1280；
  `tools/mkpayload_dig.py` 对错误 canvas 打印醒目警告；
  `tools/mkadt_dig.py` 默认 XNU 窗口改回 0xa0000000/0x40000000。
- 旧的 1125x2436 ADT 备份为 `artifacts/dig-0xa-1125.adt`，不要用于正常启动。
- 内核侧 GPU 已完成（第 8 节）；显示与 GPU 现在可以共存。
- 遗留：c0 四核在 0 MHz 在线（旧 0180 的 c0 mux 切换失败），Settings/About
  出现过一次用户态等待；正在用 `vincenoc0=1`（新版 0180）做对照。

### 9.3 下一步：用户态 GPU/显示

- `VinceGPU` 已加 SweetGPU 兼容的 scalar 接口（selector 10-16，patch 0193）：
  BO 分配/导入、IB 提交、fence 等待、info、CPU 缓存维护；ABI 与
  `repos/ios-sailfish/tools/sweetgl/sweet_drm.c` 一致。
- 还需构建 Mesa freedreno + `sweetgl.dylib`（iOS arm64），注入 HFS 根镜像的
  `/usr/lib/`，由 `sweetenv=backboardd:DYLD_INSERT_LIBRARIES=...` 加载。
- 参考 sailfish 的 `mesa-setup.sh`、`mesa.patch`、`eagl.c`；目标是 CA 的 GLES
  渲染器走 Mesa，GPU 双缓冲/缩放。
