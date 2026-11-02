# angelcare K1

独立 bring-up profile，复用 M8 的 UMS9620 平台实现。当前样机已完成 10 GiB
内置分区安装，蜂窝联网、热点、屏幕触控、通话/短信及 CPU 调压已有验证记录，
电荷量计算修复也已实机部署。USB 手动角色接口、最新公共 SIPA 修复及遗漏的
UI 更新已补齐并部署，尚非所有硬件及长期稳定性都已验证的正式固件。最新状态见
[功能复核与遗漏清单](FEATURE-AUDIT-20261020.zh-CN.md)；下面早期 RAM 测试保留为历史证据。

## 原厂基线

本次设备为 `angelcare K1` / `ums9157_2h10`，固件 `AngelCare.K1.YUAN.YD.T1.0`，Android 13、内核 5.4.210（2024-08-07）。系统构建 `aa08072233`，vendor 构建 `aa08080151`。

| 配置 | K1 |
| --- | --- |
| SoC / 平台 | T157 / UMS9620 |
| 显示 | ILI9488，`lcd_ili9488_ruiheng_mipi_hvga`，320×480 |
| 触控 | TLSC6x，保留本机固件 |
| 电池 | 本机 DT：3100 mAh，终止电压上限 4380 mV |
| 充电 | 原厂 BQ2560x，REG0E[7:1]，8 mV 步进；4380 向下取整为 4376 mV |
| 无线 | Marlin3lite / SC2355，提取本机固件及配置 |
| 启动 | boot v4、A/B；当前 Android 槽由公共安装流程检测 |

原厂配置、DT 和模块的证据及哈希见 [只读比对报告](../../docs/ANGELCARE-K1-ASSESSMENT-20261020.zh-CN.md)。userdata 加密状态由安装器逐台检测，不在 profile 中固定；Android 槽也不固定为 A。

## 代码与构建入口

- `profile.json`：独立型号及原厂板级参数。
- `prepare-kernel.py`：复用 M8 平台，通过充电适配钩子选择 K1 电压上限，保留本机面板、JEITA/OCV、PDO 和触控固件。
- `stage.py`：共享 userspace、看板、屏幕、隔离 NV 和启动服务，设置 K1 身份；不导入 M8 专用音量校准。
- `build-kernel.py`：显式指定源码、对象目录、完整 UMS9620 配置和输出目录；复用模块配套及容器功能校验。

构建要求 Linux/WSL、LLVM、AArch64 binutils、`modinfo` 和 Python 3。源码使用独立、干净的 `linux-lts-e5` `020b970e351e` 工作区；完整平台配置取自已验证的 UMS9620/M8 构建配置，不能使用原厂 5.4 配置或 E5/T551M 配置替代。`kernel.config` 只提供 K1 增量。

```sh
python3 devices/k1/build-kernel.py \
  --kernel /path/to/clean-k1-linux-lts-e5 \
  --build /path/to/k1-build \
  --base-config /path/to/tested-ums9620.config \
  --out /path/to/k1-kernel --jobs 8
```

此命令会修改指定源码工作区并编译，不能指向其他机型正在使用的目录。K1 输出使用独立 `-k1-` kernel release；打包器拒绝误用 M8 内核或混合模块。

内核输出必须使用区分大小写的 Linux 文件系统。该内核包含 `xt_RATEEST.ko` / `xt_rateest.ko` 等大小写不同的模块，Windows 普通目录会覆盖它们；公共导出器现在会在复制前拒绝这种目标。本次有效构建为 `6.18.54-k1-bringup1`，完整配套模块 234 个，通过共享模块一致性及容器功能检查。

后续系统组装沿用 `openwrt/build-profile-tf.py --profile k1`，输入完整 K1 内核输出、干净 rootfs 基线、本机启动镜像与其余既有必需参数（参见脚本 `--help`）。公共打包路径生成 K1 型号清单、热点默认名和 Magisk 配置，GUI/CLI/Magisk 继续共用安装逻辑，不复制设备端载荷。安装器会同时检查型号与 Android 板型，并保护当前 Android 槽。

不使用 `devices/m8/flash-probe.py` 等旧 M8 专用、固定槽位的试启动工具安装 K1。`collect.py`、`make-probe.py`、`flash-probe.py` 使用共享备份、探测与部署实现：绑定本机 eMMC 身份、动态槽位、完整原厂备份和镜像哈希，部署前回读启动链；先校验非 Android 槽镜像，再写 misc，进入内核后立即恢复并回读 Android 回退控制。重复部署记录不能重放。已有探测镜像只能通过显式 `--previous-image` 和实际分区哈希核验继续下一轮。

`prepare-ram-root.py` / `make-probe.py --ram-handoff` 仅用于开发期完整用户态试运行。独立 tmpfs 根、NV 工作副本及本机 vendor 全部在内存中，原始 NV 先设只读；不挂载 userdata/TF，不自动拨号，不执行短信发送。保留 Android 回退，用户态约 7 分钟重启，另有独立静态看门狗。完整 RAM 根必须先加载真实内核的完整硬件模块顺序，再启动 vendor 和屏幕服务；最小探测的 16 个模块不能替代它。它不作为普通安装入口。

## 实机验证

2026-10-20，同一台原厂 `AngelCare.K1.YUAN.YD.T1.0`，Android B / Linux A（本次检测结果）：

| 范围 | 结果 |
| --- | --- |
| 原厂启动相关备份 | 约 400 MiB，25 个文件，设备与电脑 SHA256 核对 |
| 最小内核探测 | 6.18.54 启动，USB NCM / 串口正常，用户确认 ILI9488 彩条 |
| 完整 OpenWrt RAM 根 | OpenWrt 25.12.5 / procd 启动，串口确认根为 tmpfs，未挂载 userdata/TF |
| 看板 / 触控 | 补齐 GPU 模块后用户确认显示和触控正常 |
| 充电 | 探测时 Charging，USB 输入 500 mA、充电 450 mA，REG0E=0x82 对应 4376 mV；未测充满截止及温升 |
| 首轮 RAM 无线 | 本机 WCN 固件加载，Wi-Fi PHY 注册并报告 2.4/5 GHz；该轮未测 AP、联网或配对 |
| 修正版 RAM 的 USB | 自动获得 192.168.29.2，SSH root/root 连接并复核同一台 K1；无电脑网卡/路由修改 |
| 修正版 RAM 的基带 | ModemManager 识别 V1.0.1-B7；报告 sim-missing，用户确认未插 SIM，未做插卡注册/拨号 |
| 修正版 RAM 的 Wi-Fi / 蓝牙 | 实际扫描 21 个 AP；2.4 GHz / channel 6 / HT20 / WPA2 热点进入 AP-ENABLED，随后关闭；蓝牙 hci0 注册，未配对 |
| 原始 NV | 完整 RAM 试运行多次复核：9 分区均只读且哈希未变，工作设备均为内存文件的 loop |
| 回退 | 三轮均自动回到 Android B，开机完成、su 可用，20 个启动相关分区及 misc 控制回读通过 |
| 内核故障 | 三轮持久化日志完整，未发现 BUG / Oops / panic / CPU WARNING |

首轮完整 RAM 启动只用了最小探测模块，曾出现 EGL 初始化失败、基带不就绪和 USB DHCP 未完成。已补上仅限 RAM 探测的 S07 完整模块阶段、依赖及版本核验、提前原始 NV 只读保护，并为本探测主机配置 DHCP 广播租约；修正版实机自动启动 GPU、Wi-Fi 和基带服务，USB DHCP/SSH 已连通。网络侧只做扫描和测试 AP 启用，没有让电脑连接热点或自动拨号；不能据此声称蜂窝联网、Wi-Fi 吞吐或蓝牙配对已验证。

## 离线验证

2026-10-20：

| 范围 | 结果 |
| --- | --- |
| K1 profile / 真实 staging / 充电 C / 备份、部署与 RAM 恢复保护 | 26 项通过（Linux） |
| K1 GUI/CLI 机型校验、A/B × 加密状态、包兼容 | 4 项通过，包含在下述安装器套件中 |
| Windows 安装器完整套件 | 214 项，无失败，11 项因 Linux 工具不可用跳过 |
| M8 回归 | 17 项，无失败，1 项需显式指定原生内核源码而跳过 |
| M8 默认充电适配输出对照 | 驱动 C、Kconfig、Makefile 与修改前逐字节一致 |
| 公共 AT 路由 / APN 回归 | 3 / 20 项通过 |
| Magisk TF 预检 | 通过，包含 K1 Android A/B、未解锁拒绝，以及现有机型 |
| 屏幕共享资产组装 | 六个 profile 通过 |

充电测试编译并运行实际适配器生成的 C getter/setter，仅模拟 I²C，验证 K1/M8 各自上限、向下取整、bit0 保留及 I²C 错误传播。K1 userspace 测试执行实际共享 staging，仅跳过远程 Aurora 下载和 AT 二进制编译，不执行设备服务。

```sh
python3 -m unittest discover -s devices/k1 -p 'test_*.py' -v
python3 -m unittest discover -s installer/tests -v
python3 -m unittest discover -s devices/m8 -p 'test_*.py' -v
python3 -m unittest discover -s devices/t551m -p test_at_routing.py -v
python3 -m unittest discover -s devices/t551m -p test_apn.py -v
python3 openwrt/tests/native-tf-preflight.py
python3 openwrt/tests/screen-profiles.py
```

自动化测试使用模拟 ADB、临时普通文件和隔离目录，不访问或格式化设备。硬件结果只限上表：仍需验证蜂窝初始化/联网、USB DHCP 与双角色、Wi-Fi AP、蓝牙、音频、完整充放电，以及实际 TF/内置安装和更新。CPU 非零电压偏移继续要求公共后端的已验证 SML 固件哈希，没有为 K1 放宽校验。本次未编译 Windows GUI，也未生成发布安装包。

## 2026-10-20 后续安装与通话验证

随后已生成独立 Windows 测试包，修复两阶段准备请求的交接后，用户完成了 10 GiB 内置安装。SSH 先核对 K1 profile 和原机 eMMC 身份，再只读复核分区及 ext4 超级块：e5root 分配与文件系统均为 `10737418240` 字节，Android userdata 分区为 `12939427840` 字节。不是仅确认能够开机，实际根文件系统已扩至计划容量。

用户反馈普通通话无声、免提有声。本机 `AngelCare.K1.YUAN.YD.T1.0` 的 Android B ODM 路由显示：`devices/handset/on` 使用 AOL/AOR、DA AOR、`AOL EAR Sel=AOL` 与 `Earpiece Function=1`，不使用公共默认的 EAR_HPL。K1 和 M8 的声学结构不能互换；K1 profile 的 `audio_receiver_wiring=aol` 经 staging 写为 `/etc/e5/receiver-wiring`，公共通话后端据此选择 AO 听筒路由。M8 的共享扬声器配置、其他机型的 HPL 默认路由保留。

普通模式继续使用本机 Handset DSP/codec 标定，免提继续使用本机 Handsfree 标定。AO 接线选择 `dacs_playback_volume`，不会误用 HPL 的 `dacl_playback_volume`；此 K1 WB1 的 Handset/Handsfree AO 增益分别为 6/2，DAC 增益均为 0。不添加 M8 的低音量衰减或音量上限，不改媒体 UCM、麦克风、通话控制或蓝牙路径。两个更新载荷收集入口补充保留本机 `codec.xml`。

原厂 XML 通过原机 super 元数据的 SHA256 校验和受限只读传输取得，再在电脑上只读挂载 ODM 提取；未重启 Android，也未写入原厂分区。`audio_route.xml` SHA256 为 `943f4cb58e5c7b3e755a9a567ebe66c2921f91a499e80ab670cb7c7d16897f40`；本机 `codec.xml` 为 `73714ae148e60199a4c2cd03e3807545dba538f3130f365962264a3a44315393`。原始文件仅保存在 git 忽略的 `work/k1-audio-20261020/`。

K1 自动化现为 30 项通过，包括 4 项通话路由、切换、静音/音量、回滚及旧机型默认行为测试；公共 voice-state、voice-volume、voice-controls、OpenWrt voice-audio、更新固件保留检查通过。M8 17 项无失败（1 项内核输入跳过），41S 音频 6 项通过。实机在无通话时备份并替换共享通话后端和 K1 路由配置，仅重启通话音频服务，服务就绪且无错误。随后用户手动通话并明确确认“普通和免提都正常了”；实机日志也记录普通/WB 使用 receiver+aol、切换免提使用 speaker+aol，后者 AO2/DACS0 回读符合原厂标定。此项是用户确认的声学验证；蓝牙实际通话、所有音量档位、长期稳定性仍未验证。未重新构建安装包。

## 重启基础检查与无卡冷启动

用户进一步确认双向通话/静音/音量及短信正常。带卡重启后的只读检查确认蜂窝 home/attached/connected，实际 DNS 查询及外网 HTTP 204 通过；管理页 HTTP 200、USB 链路、5 GHz channel 149/80 MHz AP、通话服务和持久化 AOL 配置正常。约 1.83 GiB 可用内存，充电状态、电量与温度属性可读，本轮未见 BUG/WARNING/Oops/panic/OOM。这里只验证当前状态，不代表完成热点吞吐、USB 重插、充放电全周期或待机功耗测试。

随后无卡重启时出现“无模组”。该次实机日志首先显示充电冷启动分支拒绝未知 `modem_control`：SHA256 `43a3bc8c4730b87431d4fc8d90a3652b2458ef8bc9f59772685d4016cc7819a3`。这与普通的 MM `failed/sim-missing` 不同：原厂加载器未执行，NR AT 通道不可用，MM 没有模组对象。不能仅据此判定为 SIM 热插拔事件缺失。

已按本机原厂 ELF 反汇编补齐共享 `e5-modem-coldboot` 的 K1 精确 profile：`0xcf08` 调用 `0xc650`，后者先检测 `/dev/sctl_pm`；`0xcf0c` 保存的返回值参与 `modem=shutdown` 启动门控。私有副本将这个结果置零，并在 `0xcf50` 将加载掩码从 63 改为 34。`load_modem_img` 位于 `0xa290`，bit0 的 PM 停止/加载/启动分支不被选择，bit1 NR/CP 与 bit5 CH 保留。原程序只改变 3 个字节，原厂文件不修改；仍要求完整 SHA、ELF 架构、原指令、charger+shutdown 和 AT 通道确实离线。E5/T551M 原有 profile 不变，未知二进制继续拒绝。

2026-11-02 更新：上述 profile／完整哈希门槛已删除，生产 helper 改为按本机
ELF 指令和加载调用关系自动定位。上文地址及哈希仅记录当时样本，规则见
[公共识别说明](../../docs/MODEM-LOADER-ABI-20261102.zh-CN.md)。

15 项公共冷启动测试通过（含三个 profile 的边界、原文件保留、已有 CP 不重启及拒绝未知指令）；另对实际 K1 ELF 核对修改范围和掩码。实机部署前后 9 个原厂 NV 分区的只读/哈希及隔离 loop 校验通过。只更新 helper，由原有 procd 继续已请求的启动，没有额外电台复位或重启机器。当前同一无卡启动已导出 V1.0.1-B7 模组，MM 明确进入 `failed/sim-missing`，热插拔监听初始化成功。此阶段只验证冷启动；后续插卡结果见下文。证据保存在 git 忽略的 `work/k1-sim-hotplug-20261020/`。

### 无卡后插卡恢复

物理插卡复现了公共解析器的独立缺陷：先收到 `+ECIND: 3,100`、CPIN 返回 busy，随后 `+ECIND: 3,0,0,1` 被旧解析器因字段数丢弃。卡实际上已 READY，但 MM 保留无卡状态。共享补丁接受严格校验的数值尾字段，继续经原 AT owner 确认 CPIN，不添加轮询、射频复位或槽位推断；同类 MU300 解析器同步修正，MU300 仅完成离线验证。

仅更新本机 ModemManager 至 `1.24.0-r944` 后，用户保持无卡，再插回原槽，实机约 20 秒内自动从 failed/sim-missing 恢复至 home、PS attached、connected，netifd WAN 自动变为 up。绑定蜂窝 `sipa_eth0` 的外网 HTTP 测试返回 204；用户确认已识别或联网。插卡之后未重启设备、重启服务、手动重新探测或拨号。网络配置未变，通话服务可用、NV 校验通过；DEBUG 已恢复 INFO。仅确认本台 K1 的本次无卡后同槽插卡，尚未验证带业务拔卡、双槽及长期反复插拔。完整依据和回归见 [SIM 事件记录](../../docs/SIM-EVENTS-20261016.zh-CN.md#2026-10-20k1-扩展就绪通知)。

### 偶发接听后界面及音频丢失

连接蓝牙时用户反馈一次实体键接听后电话已接通，但界面消失、音频异常，随后两次正常。日志确认 MM 在接听完成错误时提前把对象设为 terminated/error，基带却继续报告来电 ACTIVE。共用 MM 后端增加错误分支保护，由原有按卡 CLCC 确认状态；不自动重试接听，不以隐藏界面错误代替后端修复。`1.24.0-r945` 已编译、通过配套回归并更新本机，服务/联网及 NV 检查通过；偶发错误尚未在修复版实机再次触发，不能称为硬件复测已通过。详见 [通话错误记录](../../docs/VOICE-ACCEPT-FAILURE-20261020.zh-CN.md)。

## CPU 开机调压（2026-10-20）

已核验 K1 自身原厂 SML 的 DVFS 接口，加入精确完整哈希检查，网页与屏幕
调压入口均已在本机开放。三个域、21 个频点临时 +3.125 mV 后正常重启逐项
验证；恢复原配置再重启，21 个值全部回到原厂，联网和热点自动恢复。
当前保留原厂 0 mV，没有留下测试加压。范围、证据及未测边界见
[CPU 调压记录](CPU-POWER.zh-CN.md)。不因 K1 而放宽其他固件或混合槽检查。
现有测试包仍需下次组装才能包含本次后端更新。

## 后续用户确认与电池核查

用户确认已实测偶发接听异常的修复。电池参数和实际阈值停充/恢复已核查。
charge_counter 的公共 64 位计算修复已编入 K1 并部署完整配套内核/模块；
重启后满电读数从错误的 1 µAh 恢复为 3100000 µAh，限充、联网、热点和
屏幕服务复查通过，保留原有配置。完整充放电周期等未测边界详见
[电池功能核查](BATTERY-CHECK-20261020.zh-CN.md)。
