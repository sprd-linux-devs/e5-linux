# 远航 41S 关机充电画面与继续开机

## 已确认的原因

实机为 ZTE 7546N / P720S11，Android B、OpenWrt A。此次 DT bootargs 明确为
`androidboot.mode=charger modem=shutdown`，门控记录 `normal: power-key`，
说明长按继续开机本身已经生效。

1. 公共充电画面只接受 320×480、stride 1280。实际 fb0 为 720×1600、
   stride 2880、32 位 XRGB8888，初始化报 `unsupported charging framebuffer
   geometry`，门控继续运行但没有画面。
2. 本机原厂 loader 未加入公共冷启动助手的精确版本表。助手拒绝启动，
   日志为 `unsupported modem_control build`，并非 AT 搜网或拨号失败。

## 原厂加载器依据

本机 `/vendor/bin/modem_control` 为 82688 字节 ARM64 ELF，SHA-256：

`e76433bb853bfc5557e6397ab568666cabe8acf0ef12056783b822564df0dd75`

反汇编确认：

- `0xc900` 的启动判断首先探测 `/dev/sctl_pm`；PM 已运行不能证明 NR/CH
  已运行。`0xd1b8` 调用它，`0xd1bc` 保存返回值。
- `0xd200` 设置加载掩码 63，`0xd204` 调用 `load_modem_img(0xa540)`。
  其 bit0 包含 PM 的停止/加载，bit1 与 bit5 对应 CP 与 CH。
- 仅对助手生成的私有副本，将 `0xd1bc` 的 `mov w19,w0` 改为 `mov w19,wzr`；
  将 `0xd200` 的加载掩码改为 34（CP|CH），保留运行中的 PM。

原始 ELF 保持不变。正常启动、CP 已在线、非 charger 启动仍走原路径；未知
版本仍拒绝修改。没有改变 NV 工作副本、AT 所有权、回放与拨号顺序。

## 公共修复与部署

- `devices/t551m/charge-screen.py` 按 fbdev 尺寸对共享素材等比例整数放大并
  居中，保留黑色留边；原 320×480 路径逐字节不变。校验像素格式、stride、
  虚拟页边界与缓冲大小，支持行 padding 及 yoffset。
- 41S 使用 2 倍画面，内容 640×960，左右各 40、上下各 320 像素留边。
  保留 15 秒息屏、短按亮屏、1.5 秒长按继续开机和拔线关机逻辑。
- 当时的 `e5-modem-coldboot` 加入本机固件精确哈希及指令校验，实机 helper 已原子
  替换，沿用现有 vendor 重试启动，没有手动重排或重启基带服务。
- 公共 stage/configure 已引用两个文件，后续打包自动包含。本轮未重编内核
  或制作发布包。

2026-11-02：精确哈希／偏移表已取消，改为根据本机 ELF 指令和调用关系
识别相同协议；本文哈希与地址仅记录历史样本，见
[公共识别规则](../../docs/MODEM-LOADER-ABI-20261102.zh-CN.md)。

## 验证与边界

- 充电画面 6 项、门控 11 项、四种加载器冷启动助手 20 项测试通过。
- 实际 ELF 补丁只改变三个字节，均位于上述两条指令。原文件哈希不变；
  私有副本 SHA-256 为
  `46d71d4d0fce488a095a86841e491f16dc9e558c4b736a5157101567a5919773`。
- 部署后，原先失败的 charger 启动中自动出现 ModemManager 模组对象，WAN
  为 up，并取得 SIM2 的蜂窝 IPv4 地址。
- 实机暂时停止屏幕服务，实际充电画面 6 秒绘制 38 帧，fb0 读回与输出逐字节
  一致。DRM 确认 fbcon 的 720×1600 XR24 缓冲正在 dispc0 输出，CRTC 为
  enable=1、active=1；测试后屏幕服务恢复运行。
- 没有刷写 boot、Android、misc 或 NV，没有更改分区、充电限值或校准数据。
- 以上不冒充人工看屏。下一次真实关机插电、长按后完整启动及拔线关机的物理
  闭环尚未重测，不能记为本轮已通过。

反汇编与回执在忽略目录 `work/yuanhang41s-charger-20261020/`，不提交私有
固件及运行日志。

## Windows 仅有 IPv6 的后续排查

同一台 41S 关机充电后长按开机，Windows USB 网卡只有 IPv6 和
169.254/16 自动地址。现场核对发现该网卡 IPv4 `Dhcp=Disabled`，对应
注册表 `EnableDHCP=0`；设备 br-lan 的 IPv4、dnsmasq 地址池和 USB 桥接均正常。

仅在 Windows 恢复这块网卡的 DHCP 后，获得 `192.168.9.54/24`，地址来源为
Dhcp，网关 ping 0–1 ms，IPv4 管理页 HTTP 200。没有改设备端配置、重置
gadget 或重启服务；电脑默认外网路径仍为原 WLAN。没有确认 DHCP 被关闭的
来源，也不把本次恢复当作已经穷尽所有充电启动 USB 时序问题。
