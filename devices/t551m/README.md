# T551M OpenWrt 适配

本目录针对已 root、bootloader 解锁的 T551M（TYT，UMS9621）。它使用原机
`dtb_b` / `dtbo_b` / `vendor_boot_b`，以原机 `boot_b` 为模板生成 Linux 启动镜像。
不要直接使用 E5 发布包的启动镜像或启动控制块。

本批功能、修复及验证记录见 [2026-10-10 修复记录](../../docs/CHANGELOG-2026-10-10.zh-CN.md)。

## 硬件差异

| 部件 | 原机观测及适配 |
|---|---|
| SoC | UMS9621，8 核，Linux 下约 1.5 GiB 内存 |
| Android/vendor | ARM 32 位；启用 `COMPAT`、`COMPAT_32BIT_TIME`，按 ELF class 选择 linker/lib |
| 屏幕 | ILI94887 Easyquick，DRM 模式 320×480（LK 标记 480×320），使用原机 DT 面板命令 |
| 背光 | `sprd,qogirn6l-backlight`，GPIO 10，16 级脉冲控制，不是 E5 的 PWM |
| 触摸 | I²C 3-002e，TLSC6x；禁止自动烧写 E5 内置触摸固件 |
| 充电 | I²C 6-006b，已核实 REG0B=0x11、0x12 两批；按原机驱动分别编码，不能据模块名套用 TI/SGM 电流编码 |
| Wi-Fi/BT | Marlin3 lite，使用本机 WCN 固件、板级校准、蓝牙地址及配置 |
| 音频 | 原机 GPIO 功放 hook；移除 E5 AW87xxx 硬依赖，禁止强制解绑声卡 |

充电采用原机 DT 的电源类型与电池温度策略：SDP 输入 500 mA。
已确认本机 A/B 槽的充电配置不同：B 槽 DCP/CDP 为 1 A，用户修改过的 A 槽为 3 A。
A 槽配置是用户此前在 Android 下调整 DTBO 的结果，不是原厂默认值。
适配层仅将匹配原机电池完整参数的 B 槽 DCP 常温档对齐到 A 槽的 3 A，
CDP 和未知电源沿用传入的 DT。输入寄存器为
`100 mA + REG00[4:0] × 100 mA`，最高可设置 3.2 A，不支持写入 4 A。
电池端恢复原厂 A6 分段编码（最高请求 3047 mA）和 4.4 V 终止电压上限，
温控降流、输入电压动态限流及其他原厂保护保留。寄存器配置值不代表实测输入电流；
充电器、线材、电池电量、温度及系统负载都会影响读数。PD、高压快充
尚未验证；OTG 及主机＋外部供电的新增批次实测见下方适配记录。
原机电池温度、容量表仍来自 DT。

原机 `bq2560x-charger.ko` 的 `set_limit_current`（0x1170）确认输入为 100 mA
步长、3.2 A 范围。`set_current`（0x2d08）在 REG0B=0x12 分支使用：
不超过 1170 mA 时 `mA / 90`，更高时 `(mA - 805) / 57 + 14`，请求最大
3047 mA。原厂 getter（0x3eec）对码值大于 13 使用 57.5 mA 步长并向下取整
到整数 mA；例如 3 A 请求写码值 52，读回 2990 mA。不能套用 TI/SGM 的 60 mA
公式。原厂二进制只在本地分析，不放入发布包。

551MCM08 原厂固件的另一批机器实测 REG0B=0x11。其原厂驱动依据低两位
选择 A5 编码，500 mA 请求应写码值 8、读回 500 mA；不能使用上述 A6 表。
适配记录及原厂证据见 [T551M 充电批次](../../docs/T551M-CHARGER-VARIANTS.zh-CN.md)。
两种硬件在读取 ID 后分别选择编码，未知芯片仍不写寄存器。DCP 输入沿用匹配
电池配置的 3 A 请求；0x11 电池端按原厂上限量化到 2875 mA。

`python3 devices/t551m/test_charger.py <生成的 bq2560x-charger.c>` 在 Linux
编译实际驱动函数并使用模拟寄存器，覆盖输入上下边界与防溢出、USB/充电器档位、
看门狗恢复限流、全段电流编码、读回、终止电压和总线错误，不向实机强写高电流。
2026-10-08 更新后重启验证：SDP 输入仍为 500 mA，电池端设置读回 450 mA
（500 mA 请求按原厂 90 mA 步长量化），REG04=0x88 对应 4.4 V，故障寄存器
REG09=0，电池温度 36.9°C、状态 Charging/Good，蜂窝恢复联网。7 项模拟测试
通过。此轮设备连接电脑 USB，尚无更新后外接充电器的大电流实测结果。

## 调亮度时黑屏闪烁

初版 `t551m-backlight.h` 每次跨档都先拉低 GPIO、等待 50 ms，再从零发脉冲，
导致 UI 调亮度时短暂黑屏。原机 `sprd_pwm_backlight_update` 的反汇编确认了
16 档循环计数器：已点亮时只发送 `(新档位 - 旧档位 + 16) % 16` 个脉冲。
适配现改为同样的增量更新；仅首次初始化或从熄屏恢复时执行 50 ms 复位，
相同硬件档位不操作 GPIO。仍使用原机 DT 的 0–255 到 16 档映射和 100 µs 脉宽。

`python3 devices/t551m/test_backlight.py` 在 GPIO 计数器模型上运行实际 C 更新函数，
验证全部 256 种亮屏档位转换、16 次熄屏恢复、零亮度和非法档位。亮屏调光路径
不得调用休眠，最长单次低电平为 100 µs，脉冲序列最多 3 ms。
2026-10-08 实机在更新启动镜像并重启后，写入相同的 64→192→64→255 亮度序列，
sysfs 写入耗时从 54–57 ms 降至 1.0–2.6 ms，设置读回正常，最后恢复原亮度。
这是驱动路径和时序验证；远程未做光学闪烁测量。

## 关机充电画面

`S14e5-charge-mode` 在硬件初始化后、网络和厂商基带服务之前，同步检查原始
DT `chosen/bootargs` 中的 `sprdboot.mode=charger`（也支持 `androidboot.mode`）。
Linux `/proc/cmdline` 已替换，不能用它判断 LK 的充电启动原因。
充电启动时关闭触控，通过 fbdev 显示独立的充电动画、实时电量和状态。
15 秒后关闭背光，短按电源键再显示 15 秒，持续按住电源键 1.5 秒
才继续正常 OpenWrt 启动；恢复触控时遵循用户主动关闭触控的设置。
热点、拨号、基带厂商进程和屏幕应用均在等待结束后才启动。
拔掉充电线并连续确认 0.5 秒后关闭画面、保持触控禁用，同步磁盘并尝试将根文件系统
及镜像所在 userdata 挂载改为只读，然后执行 `poweroff -f`，直接走内核设备关闭和
PMIC 断电流程。失败会记录原因并重试，不恢复画面或继续启动网络。
此路径只用于 S14 内的充电等待；正常系统菜单仍使用常规关机流程。
关机前调用 `e5-next-boot --rearm`，尊重已有默认系统设置，避免正常充电关机因未到
S99 耗尽 Linux 试启动次数。不会将 TF 系统试运行标记为成功。

这是 Linux 最小充电启动，画面直接写入帧缓冲，不启动桌面、浏览器或 Web 服务。
充电及温控保护由内核继续管理，并非拔掉电源后的
物理断电状态；进入 Linux 前的 bootloader 画面不受此服务控制。
正常/重启启动不进入等待，手动 `start` 此服务也不会把运行中的系统变成充电模式。
输入、背光或充电检测硬件缺失时记录错误并继续正常启动，避免无法操作的黑屏。
没有更改启动介质选择、TF 卡启动或原始 NV。画面不接收触控；读取真实的电池
capacity/status，充满时显示完成，暂停时停止闪电动画。缺少显示能力时退回黑屏
等待，不因为画面故障启动热点和基带。字体和文字贴图在构建机预渲染，设备端只用
Python 标准库；`build-charge-art.py --latin <字体> --cjk <中文字体>` 可重建
`charge-art.zip`（构建机需 Pillow，字体文件不打包）。
测试：`python3 devices/t551m/test_charge_mode.py` 和 `test_charge_screen.py`（Linux）。

2026-10-09 实机从菜单同路径 `poweroff` 进入充电启动，确认电池为 Charging、
帧缓冲动画持续变化，15 秒后背光为 0，触控全程 inhibited；短按只重新显示画面，
长按模拟事件持续 1.5 秒后才继续 rcS。等待期间没有 modem_control、ModemManager、
netifd、hostapd 或屏幕浏览器进程。实际帧缓冲截图显示实时 98% 电量。
一次性按键测试服务验证后已删除，发布镜像不含自动开机测试。
随后普通 `reboot` 实测为 `sprdboot.mode=normal`，直接完整启动，不进入充电等待；
蜂窝联网和电脑经 USB 上网恢复，九个原始 NV 分区仍只读且与本次启动准备时一致。

随后修复拔线卡死：旧实现从尚未完成的 S14 启动任务调用普通 `poweroff`，再无限
等待且不关闭画面。procd 的启动和关闭路径使用同一 rcS 队列，不应在这个同步等待
阶段依赖常规关机完成（参见 [rcS.c](https://github.com/openwrt/procd/blob/master/rcS.c)
和 [inittab.c](https://github.com/openwrt/procd/blob/master/inittab.c)）。
9 项充电门控测试和 2 项画面测试通过，包含拔线去抖/重新插线/未知检测值、关闭
画面后才关机，以及命令失败或超时后不恢复正常启动。
实机一次性测试仅模拟线缆检测值，其余运行真实 S14、文件系统处理和内核关机：
关机前背光为 0、触控 inhibited，基带/网络服务未启动；随后 boot_id 改变，LK 报告
`pwroffcause="write pwroff"` 并因 USB 仍插着重新进入充电等待。测试脚本自行移除，
不是发布功能。这个结果验证了充电阶段确实能执行关机，物理拔线后的保持断电仍待验证。

### 长按开机后的基带冷启动

信息屏菜单执行 `poweroff`。USB 插着时，PMIC 关机后可能立即再次启动，LK 报告
`sprdboot.mode=charger modem=shutdown`，此时 PM 已运行，NR/CH 尚未启动。
T551M 的 `modem_has_been_boot()` 先检查 `/dev/sctl_pm`，因此原始 loader 会误判
基带已启动；原 E5 冷启动辅助程序又只支持 ARM64，导致 T551M 一直退出重试。

共享 `e5-modem-coldboot` 支持本机 ARM32/Thumb loader；当时取样文件的 SHA-256 为
`317eb996768a1978aa6b983a0d856cee47458b3bc72fa17ff88bc97f9df52109`。
从 `.gnu_debugdata` 符号和反汇编核对：`modem_has_been_boot` 位于 VA `0xa020`，
`load_modem_img` 位于 `0x86b4`。只在充电启动且 CP 通道不可用时，生成临时副本：

- 文件偏移 `0x96a2`（VA `0xa6a2`）：`mov r4,r0` 改为 `movs r4,0`，忽略 PM 已在线的返回值。
- 文件偏移 `0x96c0`（VA `0xa6c0`）：`movs r0,63` 改为 `movs r0,34`，仅加载 NR/CH。

保留 `modem=shutdown` 判断，跳过 PM 的停止、加载和启动，原 loader 文件和原始 NV
均不修改。2026-11-02 已取消哈希白名单与固定偏移，按本机 ELF、指令、
memcmp 的 PLT 重定位和加载掩码自动定位；正常启动及 CP 已在线时使用原 loader。
见 [公共识别规则](../../docs/MODEM-LOADER-ABI-20261102.zh-CN.md)。
测试：`python3 rootfs/tests/modem-coldboot.py`（两种架构共 10 项）。

2026-10-08 实机验证：先在已经出现“无模组”的 charger 启动中重启厂商服务，
日志出现 `load_type = 0x22`、`start load ch image`、`start load cp image`，
ModemManager 恢复识别。随后执行与菜单相同的 `poweroff`，USB 供电下再次以
charger 模式启动，补丁自动生效，模组和 SIM 恢复识别。两次验证的九个原始 NV
哈希均未变化、保持只读，工作副本校验全部通过；默认/下次启动仍为 Linux。
该历史回归验证了模组启动，不代表已经完成运营商注册和数据联网测试。
启用上述关机充电后，这个冷启动修复会在长按电源键、继续启动厂商服务时执行。

## NV 隔离

`e5-vendor` 在启动任何厂商进程前执行 `nv-prepare.py`：

1. 按 GPT 的分区名称找到四份 fixnv、两份 runtimenv、两份 deltanv 及 calinv，
   通过 `BLKROSET` 将原机分区设为只读，并用 `BLKROGET` 验证。
2. 首次启动将数据复制到 OpenWrt 内的 `/opt/e5/nv/` 作为工作数据；这不是备份流程。
   校验固定 NV 的头和校验和，仅运行时 NV 允许全零初始状态。同槽位的主备工作副本
   在启动前全量一致化：优先有效主副本，主副本无效时使用有效备用副本；两份均无效则拒绝启动。
3. 将工作文件挂接为 loop 块设备，重定向厂商进程使用的分区链接。
   必须保留块设备语义：`cp_diskserver` 使用 `O_TRUNC`，直接指向普通文件会截断其尾部。
4. 保存工作副本来源的原分区 SHA-256。Android 运行后，fixnv/runtimenv 来源可能变化；
   已存在且校验有效的隔离副本继续使用，不自动导入变化，也不改写来源记录。
   工作副本缺失、校验失败，或不能校验的 calinv/deltanv 来源变化时仍拒绝启动。
   工作副本的恢复不跨 A/B 槽；同组两份均失效时拒绝启动厂商进程。
5. 关机时在厂商 NV 写入事务之间停止进程，等待退出，刷新并卸载工作 loop，再继续关机。

此策略避免继承 E5 将 B 槽 NV 重定向到 A 槽的行为。Linux 下的校准写入只保存在
OpenWrt 镜像中，不同步回 Android。只读标记在重启后消失，Android 可正常使用原分区。
未对其他 root 程序构成安全沙箱；不要手动解除只读标记或绕过启动服务直接运行厂商进程。
启动后运行 `/opt/e5/t551m-nv-verify` 可只读复核原分区自本次准备完成后未变化、
只读状态、loop 映射和工作数据校验和。每次准备将当前来源哈希记录在 `/run`，
与持久化的工作副本来源记录分开，因此不会掩盖启动后的原分区变化。
若明确需要导入 Android 中的新配置，在厂商进程已停止、NV loop 均未挂接时，
可显式执行 `/opt/e5/t551m-nv-prepare --refresh`，重新校验并刷新发生变化的工作副本；
原机分区仍保持只读。普通 Android → OpenWrt 切换不需要执行刷新。

2026-10-09 实机曾因 Android 更新 A 槽 fixnv 和 runtimenv，导致旧的来源哈希检查
在 S20 中止，厂商进程未启动、WWAN/AT 端口均未建立。回放等待 AT 超时是后续症状。
修复后沿用校验有效的隔离副本，保留来源记录和原分区写保护。
随后实机重启通过：九个原分区自启动准备后哈希未变且全部只读，工作设备校验通过，
启动前回放与射频开启后复核成功，蜂窝正常联网。

### 工作副本失效原因及修复验证

已通过实机系统调用跟踪复现：`cp_diskserver` 从主副本读入 NV，以增量扇区写入主备，
并向两者写入同一个全量校验值。一次实际更新仅写入头部及偏移 `1250304` 附近的扇区，
两份原本不同的尾部未被覆盖，导致备用副本即使没有断电、没有重启，也会校验失败。
不能只检查两份各自有效，还必须在厂商进程启动前使同组两份工作数据一致。

`reconcile_pair()` 使用校验通过的同组副本作全量原子替换；不修改校验字段来掩盖内容错误，
不复制到原机分区，存在活动厂商进程或待替换文件仍被 loop 使用时拒绝操作。
`nv-stop.py` 和 `K10e5-vendor` 补上了关机事务边界等待与 loop 刷新。

`python3 devices/t551m/test_nv.py` 覆盖增量写入、不同但有效的主备数据、单份失效恢复、
双份失效拒绝以及活动 loop 拒绝替换。实机验证包含厂商再次写入后的校验、服务停止／启动
和正常重启；以 `t551m-nv-verify` 复核原机哈希和工作副本。

此前试启动曾出现固定 NV 校验失败，随后由机主恢复并同步 A/B。本版本基于恢复后的数据
验证，不能将故障后采集的数据当作出厂备份。设备专属数据、密码、运行日志均不进入 Git。

## 实机验证范围（未插 SIM）

| 项目 | 已观察结果 |
|---|---|
| OpenWrt | 25.12.5，内核 6.18.54，8 核及约 1.5 GiB RAM |
| USB 管理 | NCM、DHCP 192.168.9.2、SSH 登录正常 |
| LuCI | 192.168.9.1，登录成功，HTTP 200 |
| 基带 | AT 通道及 ModemManager 识别正常，版本 W24.26.4_P9；无卡状态 sim-missing |
| NV | 原机九个分区只读且哈希不变；厂商写入后的 loop 工作副本通过校验 |
| Wi-Fi | 已启动 T551M-OpenWrt AP，尚未用外部客户端测试吞吐 |
| 电池 | 正常检测温度、电量及 Charging；450 mA 充电、500 mA 输入限制生效 |
| 屏幕／触摸 | DRM 面板、GPIO 背光、TLSC6x 输入设备初始化成功；未人工验证画面和触摸坐标 |
| 音频 | 声卡注册及 DSP 服务启动；实际播放与通话未验证 |

未插卡时不把 `sim-missing` 判作基带故障。蜂窝注册、拨号、NAT 上网、短信和通话
必须在插卡后另行实测，当前不宣称已完成这些验证。

## 构建与试启动

在 Windows 上使用 ADB，内核在 WSL/Linux 的原生文件系统构建。设备备份和固件是
私人文件，保存在忽略目录中，不应上传 Git。所有路径可按本地目录调整。

```powershell
python tools/t551m-collect.py --serial DEVICE_SERIAL --out dumps/t551m-original
python devices/t551m/collect-files.py --serial DEVICE_SERIAL --out work/t551m/device-files
```

内核源为 [linux-lts-e5](https://github.com/Enceka/linux-lts-e5/tree/020b970e351e)，
充电源固定为 [Unisoc GPL 驱动](https://github.com/Enceka/kernel_sprd_ums9158/blob/63b8011056a5060e274fc1dcc9051c94d9a7bab8/drivers/power/supply/bq2560x-charger.c)，
准备脚本校验其 SHA-256，再应用 T551M 接口及寄存器适配。原机私有模块只用于本地
核对硬件行为，不进入交付包。

```sh
git clone --depth 1 -b e5-6.18 https://github.com/Enceka/linux-lts-e5.git ~/t551m/linux-lts-e5
# prepare-kernel.py 要求 HEAD 为 020b970e351e；分支前进后需检出该提交。
T551M_KERNEL=$HOME/t551m/linux-lts-e5 T551M_BUILD=$HOME/t551m/build \
  bash devices/t551m/build-kernel.sh
python3 devices/t551m/make-boot.py --backup dumps/t551m-original \
  --kernel out/t551m/kernel --busybox work/t551m/busybox \
  --out out/t551m/probe.img --probe
```

需要 clang/LLVM、aarch64 binutils、make、flex、bison、libssl/libelf、lz4、kmod。
BusyBox 必须为静态 arm64 版本。`--probe` 使用短时 initramfs：启动后恢复 Android A
槽，测试基本硬件，再自动重启。`trial.py` 校验设备型号、解锁状态、A 槽、原始备份、
设备树及 vendor boot 哈希、镜像和 misc CRC；只写 `boot_b` 与 misc 中的 32 字节控制块。

```powershell
python devices/t551m/trial.py --serial DEVICE_SERIAL --backup dumps/t551m-original `
  --image out/t551m/probe.img --reboot
```

OpenWrt 用户空间基于 E5 `build-20261006-150150-fd89c05` 发布包中 25.12.5 根镜像。
原发布 TAR 的 SHA-256：
`952354f557b431e260ccedd7d114fc0ed111bd35f08438c5422cc3ec3478f8dd`。
在 Linux 上解压根镜像的副本，loop 挂载，提取本机 `device-files.tar`，执行：

```sh
python3 devices/t551m/configure-rootfs.py MOUNTPOINT \
  --kernel out/t551m/kernel --credentials out/t551m/access.json
```

卸载后用 e2fsprogs ≥1.47 检查镜像，再复制到 Android
`/data/e5linux/openwrt-t551m.ext4`，核对两端 SHA-256。本机固件包同时放在
`/data/e5linux/device-files.tar`，供 initramfs 在加载 WCN 前读取。
不带 `--probe` 再运行 `make-boot.py`，生成完整 OpenWrt 启动镜像，使用同一个
`trial.py` 试启动。内核和根目录模块必须来自同一次构建。

试用根镜像默认回 Android，带 5 分钟超时服务。在 USB 控制台确认可管理后执行
`touch /tmp/t551m-keep` 可以取消本次超时。`tools/t551m-console.py 'COMMAND'`
通过 pyserial 自动识别 USB ACM，可用于网络尚未起来的诊断。完整系统管理地址为
`192.168.9.1`，随机 SSH/热点口令保存在本地 `out/t551m/access.json`。

## 持久默认启动

`make-boot.py --persistent` 生成允许保存默认选择的启动镜像；
`configure-rootfs.py --persistent` 设置匹配的根镜像，移除五分钟试用超时，
安装 T551M 专用的默认启动控制并设置 `linux`。
二者必须配套使用，现有设备只更新配置时还需停止、禁用 `t551m-trial` 服务。
在运行的 OpenWrt 中执行 `/opt/e5/e5-next-boot linux` 后重启。

持久版本仍使用 `openwrt-t551m.ext4` 作为设备上的根镜像名称。构建产物分别是
`openwrt-persistent-boot.img` 和 `openwrt-t551m-persistent.ext4.gz`。
每次成功启动由 `e5-boot-ok` 重新设置 B 槽尝试次数；启动失败仍可回到 Android A 槽。
用 `/opt/e5/e5-next-boot status` 检查 `default boot` 和 `next boot` 均为 `linux`。

## 启动等待优化

`boot/init` 对明确指定 `e5.openwrt=<镜像>` 的内置存储启动，先从 userdata
只读加载设备固件，成功后省去原来的十轮 TF 固件搜索等待。挂载失败、固件包缺失
或损坏时仍会回退到 TF 卡。未指定内置镜像的启动仍保持 TF 固件优先和完整检测窗口；
TF 系统注册、选择、试启动失败回退及 `switch_root` 流程不变。

2026-10-08 同机日志对照：内核启动至进入 OpenWrt 从 21.56s 变为 11.60s，
`modem_control` 进程启动从 35.65s 变为 25.14s。本次更新后以系统重启验证，
不是完整断电冷启动统计，也不把进程启动时间当成基带注册或上网就绪时间。

`python3 boot/tests/early-firmware.py` 在 Linux 的 BusyBox ash 下使用模拟挂载和设备，
覆盖内置镜像快速路径、TF 优先、卡延迟出现、无卡完整等待、固件包缺失/损坏、
userdata 挂载失败回退及已内嵌固件。构建产物对比确认只有 init 的早期固件选择变动，
内核、模块、SD 注册脚本和后续启动流程一致；未进行实际 TF 卡启动测试。

## 搜网至联网优化

`network-startup.py` 将 T551M 的 `sipc_wwan` 加载参数设为 `tx_gap_ms=50`，
保留发送间隔与原有 AT 单一持有者，将拨号通道原来逐条 300 ms 的等待缩短。
终端 nr2 和看板 nr6/nr7 的通道分工不变。SIM 检测、缺卡跳过和选择逻辑仍保留。

原镜像的 `network.wan.init_epsbearer=default` 会在 MM 完成注册后设置初始 EPS
APN，引起 `CFUN=4`、重写配置、`CFUN=1`，再搜一次网。新增 `keep` 选项保留
初始 EPS 配置，正常 `simple-connect` 仍携带 WAN 的 APN、认证和 IP 类型。
LuCI 的 Initial EPS Bearer 列表也提供这个选项。首次迁移只将原来的 `default`
改成 `keep`；显式 `custom`、空值以及迁移后的用户选择不覆盖。
需要专用初始 APN 的网络仍可选择 `default/custom`。

`ui.py` 和根镜像构建流程会安装补丁及一次性配置迁移；也兼容仅打包 UI 文件、
目标机启动后才有完整 ModemManager/LuCI 文件的情况。
`test_network_startup.py` 使用实际协议脚本验证 keep/default/custom/空值分支、
配置迁移幂等、SIM 加载参数、页面选项及包结构变化时拒绝静默误改。

2026-10-08 同机重启对照：内核启动至 WAN 获得地址、路由和 DNS 由约 98s
缩短为约 54–56s（两次优化后重启）；MM 初始化由 21.56s 缩短为 8.71s，
enable 阶段由 11.53s 缩短为 3.80s，优化后没有注册成功再进入飞行模式的过程。
第二次已恢复 INFO 日志，约 54s 联网，并通过 `sipa_eth0` 向外网发送 3 次 ping，
全部成功。无线网络条件会影响耗时，这是重启样本而非所有网络/断电冷启动的固定保证。

诊断中也观察到 MM 既有 CSQ unsolicited 正则会把单独到达的 `+CSQ` 行当作
通知，在稍后 OK 到达时使直接 `Modem.Command` 查询得到空串；CEREG 同样由
注册通知处理器消费。它们不适合作为原始响应完整性压力测试的判据，本轮没有
修改这些解析器。终端/看板依旧走独立 AT 服务；控制通道验证使用 CPIN、CFUN、
SPTESTMODE、CGATT，并检查基带进程和 WAN 状态。
100 ms 间隔下，上述四种只读查询共 1000 次全部返回预期内容，中位 107.37 ms、
最大 433.91 ms；后台业务仍会排队。基带进程未重启，WAN 保持在线。

## Wi-Fi 启动交接

启动提速后发现 WCN 的异步固件请求与 `switch_root` 清理 initramfs 发生竞争：
本机在 11.59s 切换根目录，11.64s 请求 `wcnmodem.bin` 得到 ENOENT，驱动随后
锁定到不可用的 Android 分区回退路径，导致 Wi-Fi PHY 和 wlan0 均未注册。
`early_wcn_ready` 在切根前等待 PHY 注册；已就绪/未加载 WCN 的系统不等待，
真实硬件故障最多等待 15 秒，仍允许管理系统启动。TF 固件来源与根目录选择流程保持不变。
`boot/tests/wcn-handoff.py` 覆盖异步就绪、立即就绪、无模块、超时及交接先后顺序。

厂商驱动也会向 netifd 报告全零的 PHY MAC，造成 hostapd 使用全零 BSSID，
与实际接口地址不一致。`wifi-address-defaults` 在首次启动时仅针对这一情况，
将有效接口地址保存为 AP 的 UCI MAC；保留显式配置，拒绝全零、多播或格式错误的地址。
`test_wifi_address.py` 覆盖地址检查、已有配置保留、未就绪重试和全零配置修复。

2026-10-09 实机：两次启动分别等待 WCN 4s/5s，之后切根，无固件缺失。
第一次恢复 PHY 后 AP 出现一次 CMD_DEL_STATION 超时，重载 Wi-Fi 后恢复；
修正 BSSID 后再次重启，AP 自动进入 ENABLED，保持 5GHz/149/VHT80。
电脑扫描到广播，WPA2 连接成功并取得 DHCP 地址，设备确认客户端 authorized，
测试后恢复电脑原有 Wi-Fi。蜂窝联网约 59–60s，外网 ping 3/3 成功。
这是包含 Wi-Fi 初始化等待后的更新计时，取代前面仅验证蜂窝的 54–56s 样本。

## Aurora 看板与 AT 稳定性

已移植 `mu300-linux-clean-tf-7.2` 的 Aurora 主题、主题配置插件与完整 LuCI 看板。
构建入口自动暂存四个哈希固定的 APK，并在首次启动安装、替换 Argon。
详见 [看板适配说明](../../openwrt/luci-app-t551m/README.md)。

`atd.c` 的原生服务保留 E5 现有常驻多通道分工：

| 通道 | 用途与持有者 |
|---|---|
| nr0/nr3 | 内核读取双卡 URC；不再启动第二个通知读取者 |
| nr1 | ModemManager 拨号、短信事务 |
| nr2 | 独立常驻进程，处理终端 AT、控制命令 |
| nr6/nr7 | 两个独立常驻进程，组成看板采集池 |

看板每轮占用一个池槽，后台刷新与实时查询可以并行，超出两个的采集请求立即让出。
采集器故障切换只访问另一个已打开的采集通道，不挤占 nr2；每个通道独立串行、独立超时。
与 MU300 的区别是 T551M 保留现有 MM 网络/短信，所以将交互通道从 nr1 移到空闲 nr2。
使用 root 专属 Unix socket 和内核 flock，避免 FIFO 重建、回复文件轮询和 PID 锁竞争；
每个通道两次写入至少间隔 100ms。
常驻服务 `/opt/e5/t551m-atd` 和命令入口 `/opt/e5/t551m-at` 均为静态 arm64 C 程序；
原 Python 实现仅保留为移植前的回归对照，不再部署，也不作为失败回退。客户端
只连接 socket，不打开串口；避免每条命令启动 Python 的开销。响应带传输状态并以连接关闭分帧，
客户端收到完整终止码后才输出，截断响应不会被当作成功。
完整响应后不再增加一秒排空等待。超时后不重试、不重开通道、不发送下一条指令，
直到旧指令的最终响应到达，或已有的 `CFUN?`、`CSQ` 两步只读探针各自收到明确载荷及成功终止码。
探针失败仍保留原描述符；只有 I/O 错误或内核 WWAN 端口消失/重新生成才允许服务重新连接。
排队请求设有截止时间，超时排队的写操作不会事后执行。

普通 `e5-at` 和看板使用新入口。原有显式 `SPACTCARD` 双卡短信操作与
MM 实现的虚拟 `E5SMS` 保留原入口，避免更改其字符集、存储选择及发送事务。
不要手工反复重启 `t551m-at` 服务：展锐 SIPC 端口在 CP 运行中重开可能失效。

2026-10-23 的原生化、常驻看板、启动与内核移植及验证范围见
[移植报告](../../docs/E5-NATIVE-BACKPORT-20261023.zh-CN.md)。下面的历史时延数据
是当时版本的实机记录，不能当作这次原生 C 版本的新实测成绩。

初版单通道对照（2026-10-08，同机连续 25 次 `AT+CSQ`）：旧入口 3 次缺少完整结果，
中位 326.2ms、P95 1598.7ms、最大 1600.8ms；新入口全部成功，
中位 300.1ms、P95 300.7ms、最大 301.3ms。4 路并发共 12 条不同只读查询全部匹配。
这是有限样本下的实测，不代表所有网络环境或长时间运行的性能保证。
测试期间已插 SIM，MM 显示 LTE home/connected，九个原始 NV 分区哈希与只读状态通过复核。
上面的“未插 SIM”表格记录的是初期验证范围。

多通道版本同日实测：nr6/nr7 同时完成 10 轮采集时，nr2 连续 30 条查询全部成功，
中位 300.1ms、P95 303.0ms、最大 304.2ms；`/proc/*/fd` 确认三个通道各只有一个持有者。
重启自动启动三个 procd 实例，蜂窝重新进入 LTE home/connected。

100ms 与原生客户端版本同日实测：连续查询中位从 300.12ms 降至 100.05ms（降低 66.7%）；
空闲单次查询中位从 136.36ms 降至 2.57ms（每组 15 次）。nr6/nr7 并行完成 10 轮采集时，
nr2 的 30 条查询中位 100.1ms、P95 100.4ms、最大 103.6ms，全部成功。
三通道各 900 条、合计 2700 条注册/信号/运营商只读查询全部返回对应完整响应，零错误；
nr2 中位 100.10ms、P95 100.73ms，nr7 中位 100.10ms、P95 100.65ms。
nr6 与后台采集共用队列，中位 100.11ms、P95 200.23ms；排队负载仍会影响单次延迟。
测试结束仍为 LTE home/connected，三个持有进程未重启，九个原始 NV 分区哈希及只读保护复核通过。
浏览器实际点击 AT 终端发送 `AT+CFUN?` 共 15 次，页面记录的端到端中位 98ms、最大 113ms，
全部收到完整结果，未出现 JavaScript 错误（含 LuCI RPC 与网络开销，与上面的 CLI 口径不同）。

`ui.py` 自动运行 `build-at-client.py`，需要 `aarch64-linux-gnu-gcc` 及其静态 libc；
Windows 默认在 WSL `Ubuntu-22.04` 构建，Linux 直接调用交叉编译器，也可用 `T551M_CC` 指定。
生成的二进制与哈希缓存位于被 Git 忽略的 `out/t551m/`，源码改变后自动重建。

`test_at.py` 使用伪终端验证碎片响应、终止码、迟到响应隔离、请求校验和 SIM 寻址；
`test_at_client.py` 用本机 gcc 与模拟 socket 验证原生客户端的分帧、错误和截断响应；
`test_ui.py` 验证 T551M 小区字段、缺少 PHY 时的合法 JSON、短信本地删除和发送参数安全传递。
未通过测试操作实际发送/删除短信或改写网络锁定配置。

移除重复的旧 E5 短信页面及未使用的 MU300 转发程序；新短信页保留双卡筛选、来源标记和发送卡选择。
转发成为独立页面，复用原有双卡转发后端与配置。旧状态总览隐藏菜单并跳转新看板。
信息屏、蓝牙、网络管理、系统日志和底层短信服务保留。原 Argon 主题及配置包已删除；
Bootstrap 是 LuCI 元包依赖的备用主题，默认界面只使用 Aurora。
补全原仓库信息屏设置页缺失的 UCI 读取 ACL；保留其已有写权限和屏幕设置。

## 网络锁定与开机回放（2026-10-09）

锁定设置由 `lock-control` 执行，RPC 返回独立任务 ID，网页轮询该任务的成功或错误；
不再通过浏览器时间与设备缓存时间比较判断完成。设置检查 AT 结果及实际读回，
手动操作重建连接后再次核验，成功后才保存。模式切换仅改变当前 SIM，保留另一卡与主卡字段。
按钮状态刷新后也会清除残留的旋转图标。

`network-startup.py` 在 ModemManager 的启动 wrapper 中安装同步钩子：
AT 就绪 → 回放并核验 → 启动 ModemManager → 首次射频初始化与拨号。
`unisoc-modem-ui` 的后台任务只在射频开启后核验，不再回放或重启射频；
`lock replay late` 被拒绝。每次开机只尝试一次，失败明确记录，不在拨号后补做。
关闭“开机自动应用”保留保存值并停止下次回放；模组本身保留的设置不会因此恢复默认。
WAN 未配置模式覆盖时，netifd 沿用当前 AT 模式，不再默认发送不受支持的
ModemManager `--set-allowed-modes=any`。显式配置的 WAN 模式处理路径保留。

部分设置在 CFUN=0 时没有最终 OK。仅启动前的这类超时允许通过 AT owner 的
两条带明确字段的只读探测恢复通信分帧，再核验目标值；不重发设置命令、不重开通道。
普通 AT ERROR 或不匹配的读回仍算失败。`SPENDC=2` 的关闭状态读回为 `+ENDC: 0`。
NR 能力响应中的数量字段不再作为 n6；LTE 能力列表由平台配置提供，
本机当前固件将 B38 从写入后的掩码剔除，因此配置中不提供 B38。

实机验证：自动模式与仅 4G 双向切换约 6.1/7.5 秒；LTE 小区锁定与解锁约 6.1/6.8 秒。
重启时约 uptime 42.49 秒开始回放，12.96 秒完成，之后才出现首次射频初始化；
射频启动后复核成功，约 uptime 76 秒连接成功，无第二次关闭/开启流程。
读回确认仅 4G、EN-DC 关闭、两个已保存 LTE 小区均生效，外网 ping 成功。
保存的频段列表仅剔除固件实际拒绝的 B38；原始配置留存于本地诊断日志。
本次未直接读写原始 NV 分区。5G SA/NSA 切换只覆盖模拟测试，未在实机驻网测试。

回归入口：`test_locks.py`、`test_boot_replay.py`、`test_at.py`，以及
`node devices/t551m/test_locks_frontend.js`。前端测试覆盖失败提示、跨时钟完成判断与旋转图标清理。

## 触控屏与锁屏

已适配手机式状态栏、底部导航、跟手上滑锁屏、界面定制和网页壁纸设置。
锁屏与看板共用日/月流量数据；息屏在内核输入层禁用触控，亮屏按用户设置恢复。
配置入口、验证范围及维护方式见 [屏幕界面说明](infoscreen/README.md)。

## 提示音与媒体音量

`e5-volume` 同时设置 PulseAudio 的 `speaker` 和蓝牙输出，解决界面档位变化而扬声器
仍为 100% 的问题。使用 PulseAudio 时，扬声器硬件增益限制为原有上限 39，
由软件执行一条音量曲线，0 档同时静音软件输出和硬件；直接 ALSA 播放保留原硬件曲线。
播放前与 PulseAudio 启动就绪后重新应用当前 UCI 档位。`ui.py` 同步安装这两个脚本。

实机以低幅度测试音采集 `speaker.monitor`：3 / 7 / 15 档的 PCM RMS 分别约
5.59 / 68.79 / 706.67，0 档为 0；音频服务重启后恢复当时的 4 档（26%）。
这里验证的是媒体输出数据，不是环境麦克风的声压测量。通话音量使用独立语音路径。
`openwrt/tests/volume.py` 覆盖扬声器/蓝牙同步、静音与直接 ALSA 分支，不操作真实硬件。

## USB 充电与快速拔插

2026-10-09 USB-C 充电器与电流表实测：DCP 识别成功，但输入限流确实为
1 A、电池充电设置读回 990 mA。两次不充电均对应 Type-C `ATTACHED_SRC`，
USB-HOST=1、VBUS 约 0.132 V。USB2 修复版临时固定 UFP 后恢复充电，但会阻止 OTG。
后续检查确认：供应商遗留属性 `dr-mode=peripheral` 不等于 Linux 标准的
`dr_mode`，MUSB 移植原本就需要保持 OTG 模式才能正常提供 USB 设备功能。
`otg.py` 现恢复 DRP，仅在关联控制器明确使用标准 `dr_mode=peripheral` 时固定 UFP。

无 PD 策略引擎时，`usb-role.h` 在首次 Source 检测后先尝试 500 ms Sink，
避免 USB-C 充电器快速拔插时被误当成 OTG 外设。检测到充电器后保持受电；
否则恢复 DRP，允许真正的 OTG 外设连接，探测状态在拔出或超时后清理。
等待期间不发布 Host 事件、不打开升压供电；已启用 PD 策略引擎时不介入。

用户修改的 A 槽 DTBO 将 USB `vddvbus-supply` 连接到充电芯片的 `otg-vbus`；
B 槽缺少此连接。适配层注册真实充电芯片供电映射，MUSB 不再接受虚拟电源，
并在没有 PD 引擎时负责打开和关闭 OTG 5 V 升压。保留其他 PD 布线标志供 PHY 使用。
USB 存储/SCSI/UAS、exFAT、NTFS3 作为模块构建；存储驱动在启动时加载，
接入 U 盘后可自动识别，适配不自动挂载或修改用户磁盘。USB HID 驱动已内置。

`charge-profile.h` 只在 3832 mAh / 4.4 V 电池参数、DCP 1 A 配置和四行
JEITA 表均精确匹配时恢复 DCP 3 A 常温档；其他电池配置不改写。
低温 580 mA、高温 1 A、停止充电阈值、回差、电压和 SDP/CDP/未知电源策略保留。
`test_charge_profile.py` 验证这些边界。修正仅在 OpenWrt 内核内存生效，
不改写 A/B 的 DT、DTBO 或 NV 分区。

`prepare-kernel.py` 调用 `usb_charger.py` 修正 Type-C 与 BC1.2 的事件处理：
插入、拔出中断同时挂起时先清理旧连接，再按硬件最终状态报告新连接；
在调用可能睡眠的通知回调前确认中断，避免把期间到来的新事件清掉。
未运行 PD 策略引擎时，将 CC 交还硬件管理，不额外产生 20 ms 的强制断开脉冲。
BC1.2 保留快速拔插中的断开事件，清理上一根线的识别缓存，并丢弃换线期间完成的旧检测结果。
正常系统与关机充电共用这些内核驱动。

`python3 devices/t551m/test_usb_charger.py /path/to/prepared/kernel` 将生成后的
C 事件处理函数放入模拟寄存器和工作队列环境，覆盖合并中断、连续拔插、检测期间换线，
以及充电优先探测、OTG 延迟接入、中间断开、探测取消/超时和 PD 旁路。
这不能代替 USB-C 充电器、电流表和线材组合的实测。

充电输入寄存器范围最高为 3.2 A；输入限流、实际 USB 输入电流与电池充电电流是不同数值。
保留电源类型、JEITA 温度、输入压降及充电终止策略，电脑 SDP 连接仍按 500 mA 管理。
实测电流需同时核对充电器额定输出、识别类型、输入电压及电池温度。

`6.18.54-t551m-usb2` 已刷入并重启验证：启动日志读回 DCP 电流/输入上限均为
3000000 uA，Type-C 采用 UFP，电脑 SDP 输入仍为 500000 uA。
103 个模块哈希、蜂窝 WAN、Wi-Fi、屏幕、USB 网络及 KVM/Docker 功能回归通过。
用户随后确认 USB2 版充电恢复正常。采集到的 25 次 DCP 快照中，输入上限为 3 A，
电池充电设置读回 2990 mA，电池端实测电流最高约 1.736 A，VBUS 为 4.632–4.659 V。
这些数据不能推断实际 USB 输入已达到 3 A。恢复 OTG 后仍需外设与充电器的物理插拔回归。

`6.18.54-t551m-otg` 已刷入并重启：Type-C 读回 DRP，`vddvbus` 映射到真实
`otg-vbus`，USB 存储/SCSI/UAS 模块自动加载。112 个模块哈希与权限、启动镜像、
蜂窝 WAN、Wi-Fi、屏幕、USB 网络和 SDP 500 mA 充电校验通过；KVM 实际客体执行、
Docker 容器限制/联网/防火墙重载/存储回归通过。Docker 测试后恢复停止且禁用自启。
这组启动检查不替代 OTG 外设的供电与枚举实测，外设及 C-C 快速拔插待用户复测。

用户随后确认 OTG 外设可用；日志记录到实际开启 5 V 升压、USB 高速设备枚举，
拔出后升压关闭并恢复电脑 USB 设备连接。

### 网页设备管理与 USB 网卡

`6.18.54-t551m-otg2` 为 Type-C 驱动增加 `usb_role_policy`（auto/device/host）
和只读 `usb_role`（实际连接角色）。手动选择只改变 CC 策略，必须检测到真实的
受电外设才允许开启 OTG 升压；不直接伪造 ID/VBUS 事件。策略切换的短暂 CC 断开
只发生在用户主动切换时，正常充电拔插不使用此流程。未启用主机开机自启时默认 DRP 自动识别。

看板 `device-usb` 已替换原占位实现：先返回切换请求，再异步应用并回读；界面区分
所选策略、实际角色与错误结果。USB 网络设备端仍固定 NCM，协议选择没有假装可用。
内核增加 r8152、ASIX、CDC ECM/NCM、RNDIS、SMSC 驱动及启动加载配置，镜像安装
OpenWrt 的 `r8152-firmware`。新接入的 USB 以太网卡可自动保存到 LAN 网桥；
已保存端口在重新插入或 LAN 重建时重新连接。不接管 gadget 网卡、USB Wi-Fi，
以及已分配给 WAN/其他网桥的接口。关闭自动加入后，保留已保存端口及其重连行为。
仅热插拔/接口事件触发，无持续后台轮询。

`test_device_usb.py` 覆盖设备识别、网桥归属、自动加入/手动加入、重复事件不重复写配置、
异步切换错误和过期任务；`test_device_usb_browser.py` 覆盖手机/桌面布局与交互。
实机已验证 136 个模块哈希/权限、真实网页登录与按钮可用、手动 host→auto 往返，
USB 网络和串口恢复；电脑连接下主机策略不误开升压，自动恢复后继续 SDP 500 mA 充电。
实物 RTL8153（0bda:8153）已匹配 r8152，创建 eth0 并自动保存、连接到 br-lan。
OTG2 实测约 67 秒 carrier 为 0；后续 MII 只读诊断确认 PHY 已协商到千兆全双工，
电脑网口同样显示 1 Gbps，但主机端收发计数均为 0。此内核移植的 SPRD DMA 后端
没有完整接入上游 MUSB 主机调度器：分配的通道阻止 PIO 接收和初始发送，导致
EP0 枚举正常而中断/批量传输停住，网卡无法上报链路、DHCP 无法通行。

`6.18.54-t551m-otg3` 在主机通道分配前为 SPRD 控制器选择现有 PIO 路径；
设备端 DMA 与其他控制器的主机 DMA 不变。OTG3 已通过启动、136 个模块、蜂窝 WAN、
热点、屏幕和电脑 USB 网络/充电检查，但以太网实物复测仍为 carrier=0。
临时接收跟踪确认中断掩码正常、每 32 ms 确实接收 2 字节，441 次 PIO FIFO 读取
却全部为 `00 00`，无法传递 PHY 已联网的通知；仅使用 PIO 不足以解决问题。

`6.18.54-t551m-otg4` 通过 `usb_host.py` / `musb-sprd-host.h` 接回此移植中
已有的 SPRD DMA 后端：先编程 RX 描述符，再启动端点请求；TX 开启对应 DMA 模式，
完成后使用主机调度器继续队列，并连接等时接收的后续回调。参考
[展锐开源主机驱动](https://github.com/strongtz/linux-sprd/blob/master/drivers/usb/musb/musb_host.c)。
描述符交接期间保留 TX FIFO 和 bulk toggle；负数/零返回均按失败清理，
回调释放锁后重新取得队列指针，避免使用已被回调移除的队列。
`test_host_dma.py` 编译实际生成代码，以模拟寄存器验证描述符启动顺序、
端点/偏移地址、短包和零长度尾包标志、后续回调及错误清理，并启用 ASan/UBSan。
2026-10-09 OTG4 实物验证：RTL8153 自动加入 br-lan，carrier=1，协商速率
1000 Mbps；电脑通过 DHCP 获得 LAN 地址，5 次 ping 全部成功、延迟不超过 1 ms。
SSH 固定绑定电脑有线地址，双向各传输 16 MiB 随机数据，长度与 SHA-256 全部一致；
测试前后网卡 RX/TX 错误均为 0，RX dropped 保持原有的 3、未增加。
DNS 查询及绑定该有线地址的 HTTPS 外网访问成功（HTTP 200），确认 LAN 经蜂窝 WAN
转发可用。这是收发完整性验证，不是千兆吞吐测试；OTG4 的反复物理拔插尚未复测。
实机、持久启动镜像及离线 rootfs 均已同步此版本，临时诊断不随系统常驻。

## USB 协议与内核工具支持（USB5）

`6.18.54-t551m-usb5` 起增加 NCM、ECM、RNDIS 的真实 gadget 配置。网页设备管理和
屏幕设置 → USB 共用 `device-usb` 后端，显示实际角色、当前协议、已保存的启动选择。
保存协议不打断当前连接，下次启动应用；可选永久或仅一次，后者成功应用后才消耗。
普通服务重载不会再次消耗一次性选择。默认 NCM，三个协议均保留 ACM 串口、MAC 地址
和原网桥归属；切换失败会尝试恢复原协议，并显示错误。RNDIS 提供 Windows OS
描述符，三个协议使用独立产品 ID，避免主机缓存混淆。ECM 主要用于 Linux/macOS。

屏幕增加自动／设备／主机策略、开机主机策略、共享协议、期限及 USB 网卡自动加入
LAN 设置。主页显示电脑连接或 OTG 外设名称，沿用原有状态刷新；息屏不更新隐藏 DOM，
没有新增轮询服务。这里的“当前角色”来自 Type-C 驱动，不用用户选择代替实际连接。
扩展坞内的外设逐项显示，不再只取第一个设备；USB 以太网卡根据实际注册的网络接口
标注，支持多级集线器、厂商自定义 USB 类和缺失产品名称的设备。网卡连接提示不依赖
网线链路或 DHCP，拔出后随下一次状态刷新清除；USB Wi-Fi 不误标为以太网卡。

`6.18.54-t551m-usb7` 修正 OTG 切回充电时的 BC1.2 时序：主机供电和 D+/D− 下拉尚未
退出时暂不发布充电检测结果；完成退出后重新触发硬件检测，丢弃 OTG 期间锁存的结果。
MUSB 状态机允许旧主机先退出，避免等待充电检测而阻塞退出。重测先确认供电连续稳定，
再复位 BC1.2 检测通路，避免在 boost 刚关闭时用 REDET 脉冲把检测卡在未完成状态。重测
不增加常驻轮询，不强制把 SDP 改成 DCP，原有电流、温度和电压策略保留。
屏幕仅在 USB 数据连接建立后提示连接电脑；接充电器或只有供电时不显示首页连接提示。
回归测试：`test_usb_charger.py`、`test_usb_charge_redetect.py`、
`test_usb_charge_transition.py`、`test_usb_charge_restart.py`（参数为准备后的内核源码目录）。

内核开启 DWARF 工具链默认格式、内核和模块 BTF、动态 Ftrace、函数图、系统调用
追踪、Kprobes/Uprobes、Perf、ARM PMU、eBPF JIT/events/stream parser。
默认没有启用追踪事件、函数追踪会话或加载 BPF 程序，非特权 BPF 保持默认关闭。
新增按需模块包括 FQ/HTB/TBF/NETEM、常见 tc 分类和动作、IFB、IPVTAP、Geneve、
socket 诊断；已有 CAKE、BBR、WireGuard、KVM、Docker 配置保留。
构建机需要 `pahole`（本次 WSL 使用 1.25；Ubuntu 可 `apt install pahole`），
Docker 构建环境也安装此依赖。DWARF 留在构建目录，发布模块去掉调试节但保留 BTF。
当前内核及所有模块必须配套更新，避免 split BTF 与内核不匹配。

参考 mu300-linux [`986e5d0`](https://github.com/dikeckaan/mu300-linux/commit/986e5d09226c089a1139210614cfae58c3697844)
启用 `NO_HZ_IDLE`，保留已有 `HIGH_RES_TIMERS`；不改变用户态轮询、不启用自动挂起。
参考 [`f0323bf`](https://github.com/dikeckaan/mu300-linux/commit/f0323bfbcde677e05e0090c409db71f9cd1a4ca4)
使 WCN 固件调试日志默认关闭，保留 sysfs 手动开启；本机是集成 WCN，并无上游 PCIe
恢复时强开日志的调用，因此不套用 PCIe/WoWLAN/看门狗的休眠补丁。
上游自动关闭热点、降低射频模式及 CPU 限速策略会改变现有功能，本次不启用。
上游待机功耗表仍未测量；减少定时唤醒不等于已验证续航提升。

2026-10-09 实测：156 个配套模块及持久启动镜像哈希通过，内核 BTF 5,033,485 字节，
96 个已加载模块提供 BTF。`tools/bpf-smoke.c` 成功加载并 JIT 执行私有测试程序，
结束释放程序，无网络挂载；KVM 小型访客执行与 MMIO 退出通过。热点、蜂窝 WAN、屏幕
和电脑 USB 的 SDP 500 mA 充电通过。NCM→ECM→RNDIS→NCM 往返成功；Windows
RNDIS 自动 DHCP，双向各 16 MiB SHA-256 一致、收发错误为 0，HTTPS 转发返回 200。
ECM 已验证枚举、网桥与串口保留，尚未在 Linux/macOS 主机测试数据收发。
真实网页 RPC 保存一次性 RNDIS 后，重启确实以 RNDIS 枚举，自动获取 IP，
一次性启用标志被消耗；同一启动中再次执行 boot 操作仍保持 RNDIS；再重启自动回到 NCM。
测试结束恢复默认 NCM 选择，网页实机登录、三种协议可选及手机/桌面布局通过。

## 恢复系统

KVM、Docker 的构建参数、按需启动和实机验证见
[KVM 与 Docker](../../docs/CONTAINERS.zh-CN.md)。

从 OpenWrt 执行 `/opt/e5/e5-next-boot android` 后 `reboot`。
若 Linux 没有到达用户空间，未标记成功的 B 槽试启动会耗尽次数后回 A 槽。
进入 Android 后可以用原始 `boot_b.img` 恢复 B 槽；不要把整份旧 misc 覆盖回去，
因为启动控制之外的数据可能已变化。`boot_a`、原机 DT、AVB、GPT 和系统分区不由
本适配刷写工具改动。
