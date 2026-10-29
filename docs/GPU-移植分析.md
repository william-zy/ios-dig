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
