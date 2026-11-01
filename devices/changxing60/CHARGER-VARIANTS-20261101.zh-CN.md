# 畅行60充电芯片批次：原厂识别与编码

## 现场证据

远程用户的畅行60运行 `6.18.54-changxing60-bringup4 #42`，
`bq2560x-charger.ko` SHA256 为
`8b07aba5ea446d2accbede8c18fc8869b6cc23d916b8c5769dfa6a9b44b4bff5`，
与当时本地正式交付件一致。不是根据旧 rootfs 的 release.json 猜测驱动版本。

驱动已注册，但 DT 客户端 `6-006b` 未绑定；charger-manager 长期延迟探测，
明确报找不到 `bq2560x_charger`。只有 `sc27xx-fgu`，没有 CM 的 `battery`。
FGU 库仑计在变化，SOC 从180降至167；这是十分之一百分比的内部值，
不能将它当成167%，也不能据此认定计量冻结。网页/屏幕及充电上限服务
缺少它们需要的 CM 供电节点。

用户用 I2C_SMBUS_BYTE_DATA 只读 REG0B：总线6地址0x6b返回 EIO，
0x1a返回0x00，PN=0、sub-ID bit2=0。原先本地样机是0x6b、REG0B=0x14。
两种批次的硬件应答不同已经确认；新驱动绑定和充电仍需该远程机器实测。

## 本机型原厂依据

参考畅行60原厂 `20240919.212928` 提取的
`dumps/changxing60-stock/reference/vendor_dlkm/lib/modules/sqc_bq2560x.ko`，
SHA256：`be9728f5a0162d0c09d6b8c77383fcdafee25a8fdf2de1d609f01d565901079d`。
没有拿41S的整板策略代替这份证据。

- `bq2560x_charger_probe` 0xdf8：0xf4c–0xfb4首先读DT地址REG0B，读失败后
  将实际访问地址改为0x1a重读。`bq2560x_read_no_record` 0x29e4有两次
  5–5.5ms的错误重试，正常应答不等待。
- 0x1014–0x1118：PN为REG0B[6:3]，bit2为子类型。跳转表、名称字符串和
  0xA7额外身份读取对应下表。
- `sqc_mp_set_ichg` 0x3fd0：按实际地址选择；0x1a使用SGM41513分段电流表，
  其他地址60mA/码；PN12/13上限3780mA，其他线性型号3000mA。
  `bq2560x_charger_get_current` 0x57c4确认了同一分段回读表。
- `bq2560x_charger_set_termina_cur` 0x31f4：0x1a还需要REG0D bit0选择量程，
  再写REG03低4位。130mA在该批次为REG03低位0xA、REG0D bit0=1；
  不能照搬0x6b的低位0x1（线性60mA步进）。
- CV写入0x3df8、回读0x3ef4、输入限流0x4444、回充0x470c、OVP 0x4f80，
  以及OTG 0x6948/0x27b4使用共同基础字段；没有把供体SGM41542的
  0x0F附加电压/输入偏移写入这些芯片。

| 原厂PN | 原厂识别名称 |
| --- | --- |
| 0 | SGM41513 |
| 1 | SGM41513A |
| 2、bit2=0 | BQ25601 |
| 2、bit2=1 | SGM41511；REG A7=5时为UPM6910H |
| 9 | SY6974 |
| 12 | SGM41516 |
| 13 | SGM41516D |

这是静态适配范围。当前有现场身份依据的是0x6b/0x14和0x1a/0x00，
其他原厂已命名分支没有本地整板实测，不能写成硬件验收通过。
未知PN仍明确退出，不能仅因地址有应答就随便写充电寄存器。

## 实现及边界

`charger.py` 在畅行60专属准备路径接入 `charger-identify.c`、
`charger-variants.h`。复用的41S `charge-current.h` 只是上述独立核对一致的
SGM41513电流编解码，不引用其整板电压、温控、USB或电池配置。

识别前不写充电寄存器；仅对I2C地址无应答类错误做原厂限定重试/0x1a查找，
其他错误保留。使用devm I2C dummy client独占替代地址，避免直接修改原客户端
地址后漏掉地址冲突及资源清理。DT原节点、regulator所属设备和PMIC依赖保留。

电池容量、CV、JEITA、冷热停充、上限控制、手动主机受电策略不作新的更改，
保留已有用户指定DCP 2.5A预算；它不是对每个供电口强制2.5A，也不保证实际功率。
不向FGU写百分比，不用假battery节点掩盖芯片未绑定。
其他机型不选择这个准备器，因此本次不会改变其芯片选择。

## 验证

- `test_charger.py`：执行实际识别与寄存器函数，覆盖全部命名PN、未知PN、
  6b/1a成功、EIO/ENXIO/EREMOTEIO、依赖延迟、地址占用、双地址失败，
  两类充电电流、终止量程、CV全范围、状态全256种值及读写错误。
- `test_profile.py`：12项机型配置、模块顺序、显示/UFS隔离回归。
- 完整内核/模块编译通过；构建入口执行FGU保留、SOC平滑、锁存、JEITA、
  probe依赖和NCM等公共回归。
- 对同一prepared源码执行7项DWC3主机/外部供电测试及硬件满电端点测试，
  均通过。以上均是离线验证，未连接或写入远程用户机器。
