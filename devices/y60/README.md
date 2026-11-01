# 金世纪 Y60 / 酷派 CP23NV3 离线适配

本适配没有本地 Y60 实机，使用原厂备份和测试者远程反馈推进。
首轮短信、显示/触摸、亮度、振动和充电已获用户基本通过反馈，音频及蓝牙仍待复测；
详见 [HARDWARE-TESTS.zh-CN.md](HARDWARE-TESTS.zh-CN.md)。不能把离线检查写成实机验收。
Y60 为显式选择的实验 profile，`tools/build-release.py --profiles all` 不自动包含它。

## 原厂依据

| 输入 | vendor build | 内核 |
| --- | --- | --- |
| 酷派金世纪y60_20240108带震动版本备份/Image | CP21.20240108.0S.GCY | 5.4.210-android12-9-g164a906d75ab |
| 酷派金世纪y60备份 | CP21.20240304.1S.GCY | 5.4.210-android12-9-g90405eed156b |

- Android 型号/设备名 `CP23NV3`，设计板名 `3292SG`，UMS9620。
  安装器的 board 属性是 `ro.product.device`，不能误用设计板名。
- 基础 FDT 在 vendor_boot；独立 dtb/init_boot 为零。两份基础 FDT 的 SHA256 为
  `d311506132acfd784dfb4056d1d1d370d084faa6c8732365d83d525ab5a8f6b8`。
- DTBO 有 11 项。两版真实启动日志最后选择 idx=5，面板是
  `LCD_ILI9488_RUIHENG_HUAXING_MIPI_HVGA`，320×480、16MHz，TLSC6540 触摸。
  其他 DTBO 含不同触摸/面板，不能按第一个 idx=0 占位值判断，更不能向全部批次强制 idx=5。
- 启动日志明确记录 `USB31 DRD Core`、`dwc3_hsphy_mode_setup`、`dwc3-gadget`；
  使用公共 UMS9620 DWC3 路径。原厂配置/DT 也保留 MUSB，此处不声称已验证所有批次的 USB 路径。
- 日志确认 boot v4 的 generic ramdisk 被加载，misc 的 0x800 处有有效 BCAB/CRC。
- eMMC、F2FS + FBE + metadata encryption。安装时仍动态识别父盘/身份/几何，
  不将备份的分区号、当前槽或容量写死。
- 本机 modem_control 是 AArch64 ELF，原厂 CP/SP/CH XML 为 qogirn6pro，
  固定/运行时/增量 NV 的来源由本机配置和公共隔离逻辑决定，不发放供体 NV。

原文件指纹见 `stock-evidence.json`；驱动对比见 `driver-audit.json`。
私有调查目录为 `work/y60/20240108`、`work/y60/other`，不作为固件/NV 发布输入。

## 独立硬件适配

### ETA6937

原厂 I²C6@0x6a，`eta,eta6937_chg`，不是 BQ/AW 充电芯片。
新 GPL 驱动沿用固定提交的 [Enceka 参考](https://github.com/Enceka/kernel_sprd_ums9158/blob/63b8011056a5060e274fc1dcc9051c94d9a7bab8/drivers/power/supply/eta6937-charger.c)，
并按本机两版模块反汇编核对 PMIC、NCE、OTG、寄存器编码和工作队列。
两版共 14 项关键函数/表的机器码与重定位目标一致；这不是整颗硬件的验收。

- UMP962x syscon 偏移从原厂 DT 取得；缺失的 GPIO/extcon 不强制绑定。
- 保留原厂 `otg-vbus` 子节点、BC1.2/OPA 次序、50ms 首次喂狗、500ms OTG 检查、15s 喂狗。
- 3050mAh、4340mV、fullbatt 4300mV、结束电流120mA、温区/OCV/映射来自本机 DT。
- 按用户要求，仅本机匹配电池的 DCP 输入、CC 和正常温区 CC 请求改为2.5A；
  ETA6937 实际输入档为2A、CC为2.45A，保留低温/高温降流及其他USB类型。
  详情见 [充电调整与验证边界](CHARGING-20261101.zh-CN.md)。
- 原厂 REG7 输入档为300/500/800/1200/1500/2000/3000/5000mA；DT DCP 请求
  `[11500000,1150000]`，实际CM按CC/输入读取，不能把异常的11.5A视为设备可用功率。
- **与原厂不同：**旧 KO 每次 feed_watchdog 都无条件覆盖成4440mV和固定电流，
  与4340mV DT冲突。移植版只写REG0喂狗位，保留CM/JEITA选择，不复制这段固定覆盖。
- I²C/PMIC失败不假报成功；充电/OTG取消、probe失败、卸载和PM路径均有清理。
  真实电流、满电、回充、温升、边充边OTG及关机充电待实机验证。

### 触摸、显示、音频与调压

- TLSC6540 compatible 补入已核对的 TLSC6x 报文实现；两个触点、18字节、12位坐标、
  TP_MAX_X/Y和GPIO属性一致。拒绝开启供体固件自动刷写。保留原机DT的ILI9488选择/时序。
- 独立 AW87xxx 外放和 HPL/EAR 听筒；安装时提取本机PA、codec、AS/CVS、路由和PGA。
  启动时生成自己的音频配置，媒体最大数字增益按PGA为34，AO增益按codec为6；
  不继承M8共用扬声器、30dB衰减或5档听筒限制。
- 两版 SML 完整payload与已核验K1一致，公共CPU后端只增加严格整镜像哈希，
  保留双槽同版、SoC、默认0mV和既有限制。见 [CPU-POWER.zh-CN.md](CPU-POWER.zh-CN.md)。
  不写SML、不改原厂OPP、不强制校准电量。

## 安装与打包接入

- 公共看板、实体屏幕、短信/电话、蓝牙、双卡射频、网络恢复、充电控制、调压、
  USB角色、隔离工作NV/升级保留、系统补丁已接入共享staging，无新增常驻兜底轮询。
- 桌面、Android及Magisk TF入口识别CP23NV3，默认热点Y60-OpenWrt，网关192.168.9.1。
- 动态Android/OpenWrt槽；仅向对侧同步本机BSP及DTBO/vendor_boot，不打包供体BSP/NV。
  不新增green/锁BL例外，未实测前不声称能绕过AVB。
- Windows/Android原生工具本地重编；Apple Silicon按已有授权使用共享工具仓库CI。
  每个平台按当前源码指纹校验，包根目录含APK和Diff Studio。
- 用户实测步骤和恢复注意事项见 [TESTING.zh-CN.md](TESTING.zh-CN.md)，会置于包根使用指南开头。

## 可复现入口

```sh
python3 tools/build-release.py run --workspace /home/kano/openwrt-build --profiles y60 \
  --label y60-kernel -- python3 tools/build-profile-kernel.py \
  --workspace /home/kano/openwrt-build --profile y60 --jobs 8
python3 tools/build-release.py package --workspace /home/kano/openwrt-build \
  --profiles y60 --label y60-test
```

只使用登记的`kernel-views/y60`独立overlay视图、`objects/y60`和`kernels/y60`。
不复制另一整棵源码/rootfs，不改其他机型prepared源码/对象。已编译
`6.18.54-y60-bringup1`与235个匹配模块，指纹见`build-evidence.json`。

调查工具：`inspect-stock.py`只读解析boot/FDT/DTBO；`extract-stock.py`只读挂载super，
只提取指定公开配置/驱动；`audit-drivers.py`比较ELF函数和重定位；`verify-sml.py`核对完整payload。

离线检查：20项原厂证据/驱动/模块检查、31项CPU后端、5项音频/固件转换/包身份检查、
5项双槽启动链/失败回滚、15项构建编排，以及实际ETA C回调/寄存器故障/工作队列/PM测试。
完整打包另检查rootfs、内核模块、原生工具指纹、清洁固件目录及ZIP全部校验。
**这些不等于Y60启动、触摸、音频、联网或充电已经通过实机验收。**
