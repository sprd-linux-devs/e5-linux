# 远航41S充电芯片批次识别（2026-11-01）

## 实机报告确认的故障

用户提供 `yuanhang41s-power.txt`，内核为
`6.18.54-yuanhang41s-bringup1 #28 SMP Fri Oct 30 02:21:24 +08 2026`。
原充电模块 SHA-256：
`75ee3b29ff4e6de9713247d203a275423dfc065ce81508c54df74ac83beb706f`。

- `6-006b` 的 DT compatible 为 `ti,bq2560x_chg`，模块已加载但设备未绑定。
- 用户只读 SMBus 检测得到 `0x6b REG0B=0x11`：PN=2、sub_id=0。
  `0x1a` 返回 EIO。不能因为旧样机用了0x1a，就修改地址去强行绑定。
- 只有 `sc27xx-fgu` 电源节点，没有充电器和 CM 的 `battery` 节点。
- FGU 的原始 SOC 从477变到450，库仑计、电压、电流均有更新。
  该值使用千分比单位，分别为47.7%和45%；并非450%或缓存完全冻结。
- USB3 同时记录 Type-C resources unavailable、延迟探测。充电器提供的
  VBUS regulator 尚未注册可能影响它，但尚未实测，不能声称 USB 已修好。

原适配只允许 SGM41513（PN0），因此这台机器被明确排除；这不是用户
缺少安装模块，也不是单凭加载顺序就能消除的故障。

## 本机原厂证据

参考已采集的远航41S Android固件 `20240508.225723`：
`reference/vendor_dlkm/lib/modules/sqc_bq2560x.ko`，106246字节，SHA-256：
`ba6dde2ad1009c49ae81891ad59cdb0a354f9bb15c12371c37d357296127c310`。
没有把畅行60的芯片列表和寄存器扩展直接搬来。

- Probe 0xd10；0xe90读REG0B，0xe9c/0xea0按4位PN和bit2解析。
- 0xf4c–0xfb4 的分派只包含 PN0 SGM41513、PN1 SGM41513A、
  PN2/sub0 BQ25601、PN2/sub1 SGM41511、PN9 SY6974。
  `.rodata` 跳转表前10字节为 `02 28 2b 00 00 00 00 00 00 33`，
  基准地址0xee0，表项乘4。原厂没有畅行60的PN12/13分支。
- Probe在原地址重试读取，失败后才在0xfe0–0x1004选择0x1a。
- `sqc_mp_set_ichg` 0x2b1c 在0x2b5c按实际地址区分：0x1a使用分段编码，
  原地址使用60mA线性步进、上限3000mA。`get_current` 0x43a8亦如此。
- `sqc_mp_set_ieoc` 0x3074 在0x30a8区分地址，0x6b为60mA线性步进，
  不能使用SGM41513的REG0D终止电流配置。

## 修复及边界

`charger.py` 注入 `charger-identify.c`，按本机原厂PN识别后才进入初始化。
仅在I/O失败时尝试原厂备用地址；EPROBE_DEFER保留，未知PN拒绝，不抢占
其他I2C客户端。备用地址通过I2C core预留，原DT客户端和调节器归属保持不变。

电流设置/读取按实际地址选编码；新0x6b批次使用线性电流及终止电流编码，
不写它没有证据支持的SGM扩展寄存器。保留旧0x1a批次已经使用的分段处理。
本次不改电池容量、OCV、JEITA、温控、满电电压或用户限充设置。

`test_charger.py` 执行实际识别及已准备驱动的C函数，覆盖全部256个ID、
原/备用地址、EIO/ENXIO/EREMOTEIO、延迟探测、地址占用、未知芯片、
5000档充电电流、1600档终止电流、I/O错误、重复准备及IRQ归属。
另通过既有满电端点和profile回归。完整Image及配套模块已使用登记的
远航41S源码/对象目录编译；任务记录见 `out/build-logs/`。

这些是离线测试和编译，不是本报告机器的硬件验收。本次没有连接或写入
这台远程机器；其充电恢复、USB资源恢复和长时电量显示均仍需实测。
临时模块须匹配其运行内核的BTF，不能只凭uname相同便加载。
