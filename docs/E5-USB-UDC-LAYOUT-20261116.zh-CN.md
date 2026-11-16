# E5 USB 数据失效：UDC 私有布局检查

## 现场与范围

2026-11-16，用户报告荣悦 E5 在未连接外设时放置后，再接电脑只能充电，
接 OTG 只能供电、不枚举；正常重启后恢复。本轮最初另一条同网段连接实际
为远航 41S，身份检查拒绝继续；随后通过 E5 USB 网卡的 IPv6 链路本地地址
确认目标为 `e5`，未变更电脑路由或 Wi-Fi。

重启后的机器运行 `6.18.54-e5-mobile4 #25`，固件标识
`e5-r20261114.162532-g3409d23c-s3fe04745`，当前策略 auto，USB NCM
configured/high-speed。故障已经随用户重启消失，本轮没有捕获故障时的
Type-C、PHY、runtime PM 或 IRQ 快照。保留的前次 console 中可见约
3428—3615 秒的多条 `UDC had already started`；该报错本身不能证明唯一根因。

## 已确认的独立缺陷

固定内核 `020b970e351eee3887e6caaf2d653926e7086e44` 的 vendor
`musb_sprd_otg_start_peripheral()` 使用自行复制的 `struct sprd_usb_udc`
强制转换 `gadget->udc`，然后直接写 `vbus=false`。当前 UDC core 的私有
结构已经在 `dev` 前增加 `gadget_release`，两者布局不一致。

对本机对应 E5 vmlinux 的 BTF/pahole 只读检查：

| 字段 | vendor 复制结构 | UDC core 实际结构 |
| --- | ---: | ---: |
| dev | 16 | 24 |
| list | 792 | 800 |
| vbus | 808 | 816 |

因此旧写操作落在真实 `list.prev` 的第一个字节，既没有清除真实 VBUS，
又破坏内部链表。另一个问题是直接调用 `ops->pullup(0)` 绕过了 core 的
`gadget->connected` 状态和 disconnect 回调，导致下一次公开 connect
可能直接返回成功而不重新启用上拉；该路径也有实际 core C 函数负对照。
两个问题均是源码可证实的
缺陷，但尚不能将它们直接等同于这次“无外设放置后失效”的完整因果链。

修复位于公共 MUSB 适配器 `devices/t551m/usb_host.py`：

- 删除 vendor 私有 UDC 结构及转换。
- 使用 `usb_udc_vbus_handler(gadget, false)` 发布真实断开状态。
- 使用同步的 `usb_gadget_disconnect(gadget)`，在角色关闭供电和放下 PM
  引用前完成断开，保留原有 gadget work 刷新、请求释放和角色顺序。
- 不修改 UDC core，不改 Type-C、BC1.2、充电限流、OTG 升压或用户策略。

接口语义同时对照了内核本机源码及
[Linux UDC core](https://kernel.googlesource.com/pub/scm/linux/kernel/git/torvalds/linux.git/+/1f7267d8043e394933b0ed06070bfa7921d7c830/drivers/usb/gadget/udc/core.c)。

E5、T551M、T512N、LYM-10K 共用该 MUSB 适配器。其他 DWC3 机型没有因此
获得或需要套用这份 MUSB 修改；不能把 E5 验证等同于它们的实测。

## 验证与剩余工作

**构建接入更正：** 下述首轮 `#26` 构建和部署不能作为 UDC 修复已进入
镜像的证据。扩查其他机型时发现，`usb_host.py` 原来只在主机函数缺少
`musb_start()` 时写回整个 glue 文件；已有主机补丁的缓存跳过了本轮新增
的 peripheral 修改。对象反汇编仍有偏移 808 的旧写操作。用户本轮插拔
结果是该首轮镜像的实际结果，不能冒充修正版的硬件验证。

现已将 glue 写回移到该条件之外。新增缓存重放测试，在主机已修的源码上
恢复旧 peripheral 后重新应用，必须将新修复保存且重复应用不变。
`test_usb_udc_api.py` 默认还要求**输入源码本身已修复**；仅在显式
`--adapt-legacy` 时才允许在内存中转换旧源码用于负对照。正式构建不传
该选项，避免再次把测试临时转换结果误当实际编译输入。

新增 `test_usb_udc_api.py`，提取实际 detach 分支和 UDC core 的公开 API
函数，用旧写操作作负对照，稳定复现链表被修改。修复后的十轮断开、
延迟 VBUS 工作、已 soft-stop/deactivate 的状态及后续重新连接通过；
address/undefined sanitizers 无异常，重复应用补丁一致。测试接入已有
`tools/build-profile-kernel.py` 的 MUSB 回归列表。

本轮 E5 内核和完整模块已通过既有工作区和受锁构建器编译，任务
`20261116-092025-e5-usb-udc-api-20261116-80742` 完成。既有 gadget/session、
主机启动/退出、外供主机、NCM、AW32257 充电/OTG、电量和内核配套检查通过。
外供主机测试组有一项非本机相关跳过，不计为通过。T551M、T512N、LYM-10K
缓存源码分别通过新 UDC C 回归，尚未重编或实机验证这三款。

用户随后授权本轮 E5 Linux B 刷写及正常重启。试验镜像保留 84 条非模块
CPIO 记录、用户启动参数及诊断区，替换 45 个内嵌模块和 293 个根目录模块
路径；boot 前 56 MiB、footer 和根模块已逐一回读校验，Android A 完整摘要
未变。电脑保留旧 boot/模块备份，机器的 `/lib/modules/` 另保留旧模块。
正常重启进入 `#26 SMP Mon Nov 16 17:20:45 +08 2026`，重新核验新 boot
前缀/footer、全部 293 个模块路径和 Android A 摘要通过；USB NCM 为
configured/high-speed、电脑管理连接恢复，电池状态为 Charging。未出现
未知符号、无效模块、BTF 错配或新的 UDC already-started 报错。

空闲后恢复的长期实机验证仍待进行，不通过禁用
休眠、定时重启 USB、解绑控制器或修改充电策略掩盖症状。摄像头适配已按
用户要求暂缓，未为摄像头加载驱动或修改设备树。

## 首次插拔反馈与外供坞区分

用户随后反馈“OTG 只有供电、不识别”。读取本轮完整 logread，确认
784.15 秒电脑断开后，MUSB 正常退出 peripheral，784.78 秒 glue/PHY
完成 runtime suspend；841.44 秒接回电脑后重新启动 gadget，NCM 网络恢复。
因此这轮没有再卡在旧的首次 host 等待 glue 休眠路径。

中间 805.88 秒的接入只收到 `ATTACHED_SNK`，没有 `EXTCON_USB_HOST` 或
host-start 事件。用户进一步确认实际接的是外部供电扩展坞；拔掉坞的外部
电源后，普通 OTG 已能识别。不能把这次自动模式下的受电身份直接当成
主机启动失败，也不能因此回滚已经证实的 UDC 修复。

当前这类外供坞需要使用已有的“主机＋充电”手动策略；其恢复范围和防反灌
条件见 `E5-HOST-SINK-VBUS-20261113.zh-CN.md`。没有通过“检测到 VBUS 就
强制 host”去改变自动模式，避免影响电脑 USB 网络和普通充电器连接。
用户随后明确选择“主机＋充电”，使用同一只带外供的扩展坞，确认“识别和
充电都正常”。本轮电脑网络恢复、无外供 OTG 枚举、明确外供主机策略三项
均有实际结果；长时间无外设放置后的重复验证仍不能用这次短时测试替代。

## 更正构建及全机型扩查

修正缓存写回后，受锁任务 `20261116-095452-musb-udc-four-models-99638`
完整编译 E5、T551M、T512N、LYM-10K 的各自 Image 和配套模块，全部完成。
四款的实际准备源码均不存在 `struct sprd_usb_udc`，目标文件反汇编的
peripheral-stop 分支均调用 `usb_udc_vbus_handler` 和
`usb_gadget_disconnect`，不再保留旧的偏移 808 写操作。缓存重放、实际
输入已修断言、USB 生命周期及各机型充电/电量回归通过。

| 机型 | 控制器路径 | 本轮结论 |
| --- | --- | --- |
| E5 | SPRD MUSB | 同一缺陷；更正版完整编译并已授权部署，启动核验通过，外设复测待反馈 |
| T551M | SPRD MUSB | 同一缺陷；公共修复、完整编译和离线回归通过，无本轮实机验证 |
| T512N | SPRD MUSB | 同上 |
| LYM-10K | SPRD MUSB | 同上 |
| M8 | DWC3 | 未发现这处私有 UDC 布局访问；既有 DWC3 外供主机回归 8 项通过 |
| K1 | DWC3 | 同上，8 项通过 |
| Y60 | DWC3 | 同上，8 项通过 |
| 畅行60 | DWC3 | 同上，8 项通过 |
| 远航41S | DWC3 | 未发现这处访问；相关回归 7 项通过、1 项布局不适用而跳过 |

DWC3 原生/准备缓存与公共角色适配均只读审查，回归使用各自实际源码，
没有把 MUSB 控制器修改移植到这些机型，也没有因此重编未变化的 DWC3 内核。
“未发现这处缺陷”不表示已验证这些机型所有 USB 外设和长期恢复场景。

## 更正版已部署

用户明确授权更正版再次刷写和正常重启。使用独立的
`corrected-candidate` 记录保留 `#26` 的 boot、完整模块和回读基线；
没有覆盖首轮记录。新 boot 完整镜像 SHA-256 为
`987179a7aef03db55276d5fb4c4ef4ede018e83c50cf58a2be7955d98bffcdd1`。

仅写 Linux B boot 的前 56 MiB/footer 并替换该 release 的 293 个模块
路径，保留 84 条非模块 initramfs 记录、45 个匹配内嵌模块、诊断区及用户
配置。部署前后 Android A 完整摘要未变；未改 GPT、userdata、NV 或 IMEI。

正常重启进入 `#27 SMP Mon Nov 16 17:55:14 +08 2026`，新 boot 前缀、
footer、所有根目录模块路径和 Android A 摘要重新回读通过。USB NCM
configured/high-speed、电脑管理连接及 Charging 状态正常，未见未知符号、
模块无效、BTF 错配或 UDC already-started 报错。外设插拔和长期空闲验证
仍须以这版的后续实机结果为准，不沿用 `#26` 的结果。

用户随后在 `#27` 上完成无外设空闲后的普通 OTG、带外供扩展坞的
“主机＋充电”、恢复自动后直连电脑三项验证，明确反馈“三项都正常”。
取回本轮日志后停止本次启动、独立进程组中的临时采集；没有保留新的常驻
轮询或 USB 复位任务。长时间空闲的重复稳定性仍待后续使用观察。
