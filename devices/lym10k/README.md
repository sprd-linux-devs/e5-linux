# 岭燕 LYM-10K 适配记录

## 原厂依据

Android 标识：`LYM-10K`，device `RY5G`，SoC 属性 `T765`，原厂 DT 为 UMS9621。
固件指纹：`linkintec/RY5G_80CN_FIH/RY5G:13/TP1A.220624.014/LYM-10K-V32:user/release-keys`。

本次只读分析用户提供的分区 dump、已解包的 vendor，以及
`lym-10k-AI-openwrt驱动.zip`。原始文件不修改，不随发布包分发。
解包与反汇编结果位于忽略目录 `work/lym10k-reference/stock/`。
本机连接的 ADB 设备是 E5，不是 LYM-10K；本次不操作该设备。

| 原厂证据 | SHA-256 / 位置 |
| --- | --- |
| vendor_boot 内的 hynitron_ts.ko | `98ac6b11ae7b152236f68aadedcfcbf98afe8d96b992eea9ec23be6662a00a18` |
| bq2560x-charger.ko | `1d5261d8a8dcc21e05b7e06a45d7a2c81059bb73889a95a32aaf73a66fdfd24f` |
| charger-manager.ko | `53ba4f5a37b4281e6626970812449d12c8ab0337a526b94922313e93030801b8` |
| 两槽 SML dump（均 157224 字节） | `25447f40532d7dcb2b86b343ae9cfc8fb14f8384011089d68d268f88c31e04c6` |
| DTBO 的 RY5G/RY5 配置 | entry 2/3；不假定开机一定选择 entry 2 |

## 已接入源码

- 独立 `lym10k` 机型：安装器、TF/Magisk、内置分区、更新、Diff Studio 型号映射、NV 保留路径和发布入口均识别 `LYM-10K`。
- 与 T512N 共用 `devices/common/handheld-stage.py`，网页、屏幕、短信、通话、AT owner、充电页面、USB 网卡、关机充电及低电量服务来自公共代码。
- 自动网络模式默认 134，SIM2 射频遵循 E5 仓库原有规则，不默认关闭。不继承 T551M 特有的 152 和 LTE 候选限制。
- 显示复用公共 DPU/DMA、GPIO 背光适配，保留原厂 DT 的 320×480 和时钟，不应用 T512N 专用的显示时钟变更。
- 调频、核心开关、温控接口按本机固件/DT 读取，不复制别的机型的 OPP、温度或电池参数。
- SMC 三簇开机调压已接入网页和屏幕公共后端，默认 0；完整原厂镜像与离线代码执行
  验证记录见 [CPU-POWER.zh-CN.md](CPU-POWER.zh-CN.md)。实机电源轨/稳定性仍待验证。

### 基带运行环境

原厂 `modem_control`、`cp_diskserver`、`refnotify` 都是 ARM32 ELF。
内核显式启用 `COMPAT` / `COMPAT_32BIT_TIME`，用户态沿用按 ELF class 选择
`/system/bin/linker` 和 `lib` 的公共加载器，不改 AT 所有权、拨号顺序或开机回放。
`modem_control` SHA256 为 `94b1a0bc5df7726852dfbec16a2c8ea1cb58b22a172951869e6c74ed969c1c0a`。
充电关机后长按开机的 NR/CH-only 副本原先按此样本核实；
2026-11-02 已改为实际 ELF／指令协议定位，不再绑定该固件哈希：
VA 0xa020 通过原厂字符串 0x210d 检查 `/dev/sctl_pm`，VA 0xa69e 调用它；
文件 0x96a2 的 `mov r4,r0` 与 0x96c0 的 `movs r0,63` 分别替换为清除判定和
仅选择 CP/CH 的 34。加载函数 VA 0x86b4 的掩码分支与既有 T551M 路径相同。
只生成临时副本，不修改原厂文件或运行中的 PM 固件。

### 触摸

原厂 `hynitron@15` 绑定 `hynitron,hyn_ts`，GPIO13 IRQ、GPIO14 低有效复位，
`hynitron,display-coords = <320 480>`。同一 DT 中也有 TLSC6x 候选节点，因此内核禁用
TLSC6x，避免两个驱动争用同一组 GPIO。

`lym10k-touch.c` 直接绑定真实节点，不在 probe 中修改 I2C 地址，不绕过另一芯片的检测。
报文依据原厂 `cst8xx_touch_report`（0x890）：从 0x00/0x05/0x0a 分别读取 5 字节，计数 byte2，
6 字节一条记录，处理最多两个触点；坐标为 12 位，事件/ID 使用原厂高位字段。
协议解码单独在 `touch-packet.h`，有实际编译执行的接触、抬起、双点、重复 ID、坏报文测试。
复位依据 `hyn_reset_proc`（0x24c）及 `hyn_resume`（0x20e0）：低 20 ms，高后等待 40 ms。
固件版本 A6 读取前保留原厂 `cst8xx_firmware_info` 的 100 ms 就绪等待，仅属于本机触摸探测。
系统休眠的 A5/03 来自原厂深睡分支。息屏仍使用公共 input inhibition，未经触摸重绑/卸载。

用户提供的二进制修补和三处开机守卫不进入发布源码；旧服务也不覆盖公共服务。
不向触摸控制器上传或烧写固件。

### 充电、电量、USB

原厂 DT 有 BQ2560x 0x6b、BQ25890 0x6a、HL7139 0x55 等候选节点。
实际焊接芯片及寄存器必须实机读取确认，不能仅凭 DT 候选断言全都存在。
目前 BQ2560x 路径根据原厂 `set_current`（0x2d08）区分 REG0B 0x11/0x12：
低位为 1 时采用 59/63/57.5 mA 分段，其他已支持变体采用 90/57 mA 编码。
读回换算也已核对本机 `bq2560x_charger_usb_get_property` 的 0x3dd8–0x3f20：
按 REG0B 低位选择 `code*63-4` / `code*90`，高段为 `(code-14)*115/2+805`。
使用本机 DT 的输入电流、JEITA、终止电压和容量表；不复制 T551M 的 DCP 提流配置。
未经支持的芯片 ID 会明确拒绝，不错误地套用某一条充电曲线。

常规 OTG、设备模式及 BC1.2 修复接入公共路径。主机＋外部供电现按用户要求启用，
仍是手动选择的实验模式；网页和屏幕通过内核能力属性自动展示该选项。
复用公共 MUSB 的本机升压互锁、外部 VBUS 检查及退出恢复，保留本机电流编码和 DT 策略。
此模式尚未在 LYM 实机验证，不把其他五款机型的成功当作本机验证。
电池 SOC/休眠也使用公共修复，不强制校准、不禁用 eMMC/CPU 休眠。

## 编译与验证

构建输入登记在 `tools/build-layout.json`，使用本机已有工作区与只读 overlay 源码视图：

```sh
sudo python3 tools/build-release.py run --workspace /home/kano/openwrt-build \
  --label lym10k-kernel -- python3 tools/build-profile-kernel.py \
  --workspace /home/kano/openwrt-build --profile lym10k --jobs 8
python3 devices/lym10k/test_port.py -v
```

日志在 `out/build-logs/`；独立对象在工作区 `objects/lym10k`，交付件在 `kernels/lym10k`。
不使用 ZIP 中固定 vermagic 的旧 ko，不改写 ext4 inode/数据块注入文件。
完整发布仍须通过 `tools/build-release.py check/package --profiles lym10k` 的校验；
当前已变更安装器 Python 后端，正式打包前需要重编原生安装器，不冒用旧 EXE。

2026-10-26 离线结果：

- 最终内核 `6.18.54-lym10k-bringup1` 及 267 个配套模块编译、BTF 和交付校验通过。
  触摸源码与本机独立 overlay 中实际编译的文件逐字节一致。
- 78 项 unittest 通过：机型/协议 5、公共原生运行时 1、安装器 LYM/K1 各 4、
  NV 恢复 3、发布入口 15、充电后基带启动 20、CPU 公共控制 25、TF 预检查 1。
  另有七款屏幕配置、T512N 原入口、LYM 探测模块依赖闭包（16 模块）检查通过。
- 以本机 dump 的 boot_b/misc 模板生成 `out/lym10k/boot.img` 成功，包含 45 个启动模块。
  dump 的 misc 指向 Android A，因此该离线模板的 Linux 槽为 B；安装时仍动态识别槽位。
  这只是离线启动镜像，不是已实测固件，也不是完整安装 ZIP。
- 构建任务：`20261026-114755-lym10k-kernel-final-14182`；
  boot 任务：`20261026-115107-lym10k-boot-31834`。日志位于 `out/build-logs/`。
- 未向任何连接设备部署；原厂 dump、IMEI 和 NV 均未修改。

## 尚待确认

### 2026-10-26 补充审查

- 已补内核 CI 的 `lym10k` matrix 与专用编译命令；本轮没有启动远程 CI。
- 原厂三份音频 XML 已通过现有转换器：audio_structure 67 模式、每模式 730 字节，
  dsp_vbc 72×1732、cvs 67×1084；蓝牙 pskey/rf 分别转换为 176/252 字节。
  这确认输入格式可用，不代表扬声器/麦克风/蓝牙已经实机通过。
- 检查原厂文件可确认安装器需要的音频、WCN、Wi-Fi board config 和蓝牙配置路径存在；
  未使用别的机型的固件、MAC 或 NV。蓝牙转换测试使用明确的虚拟 MAC。
- 屏幕驱动设置了 INPUT_PROP_DIRECT，公共息屏服务按该属性识别输入，
  不依赖 `tlsc6x_touch` 名称；因此新驱动已纳入已有触摸抑制/锁屏路径。
- `主机＋外部供电` 实验模式已按用户要求接入；普通自动/设备/主机角色沿用公共实现，
  默认不切换到实验模式。LYM 的并行充电与 USB 收发仍需实物扩展坞验证。
- 本轮启用后的内核任务为 `20261026-124031-lym10k-host-sink-32172`，
  配套 Image/模块、BTF、公共电量计与 NCM 校验通过；MUSB 回归 5 项通过，
  1 项 AW32257 专用测试因本机是 BQ2560x 跳过。USB 后端与 Chromium 页面回归通过。
  `out/lym10k/boot.img` 已重新生成（任务 `20261026-124234-lym10k-host-sink-boot-49841`），
  尚未刷入设备。没有将离线通过计为 LYM 的硬件验证。
- 发布前还需要重编 ModemManager APK（启动 hook 增加本机型使输入指纹变化），
  以及 Windows/macOS 安装器（机型识别源码变化）。只读发布检查会拒绝旧输入；
  本轮未跳过校验或重新打包。

- 真机冷启动、触摸与息屏唤醒、显示、按键、扬声器/听筒/麦克风、短信与通话。
- 实际 charger ID、充电插拔/输入电流/温度与 SOC、OTG、热点与蓝牙。
- 基带固件及 NV 由安装器从每台本机提取，未修改任何用户 IMEI/NV。
- SML 的完整签名镜像长度、校验和、调压分发/解码及 CPU/SRAM 更新已经离线核实并接入；
  实机 SMC 调用、实际电压和调压后稳定性尚未测量。
- 资料提到的息屏问题是否在当前公共实现下仍存在，必须实机复测；不照搬旧轮询守卫。

源码回归通过与内核编译成功均不等于硬件验证通过。状态暂为 bringup。
