# 无线更新与信息屏 eSIM 核查

## 无线配置

Diff 更新使用固定版本公共 OTA 引擎，现存 `etc/config/wireless` 不覆盖，
新增默认配置也保留用户文件；普通更新归档整个 `etc/config`，离线写入后
恢复原配置。真实引擎和离线更新脚本已使用自定义 SSID／密码回归，按原字节
保留；用户对其他系统文件的小修改仍允许更新并备份。未收紧 OTA 校验。

E5 的首次初始化脚本已有缺失标记时保留用户配置的判断。本次再覆盖 UCI
读／解析失败的情形：现有 wireless 非空但无法读取时停止初始化，不当作
空配置导入原安装密码。MU300／Pro 缺少初始化标记时重写用户配置的问题在
各自公共启动脚本修复。尚未复现独立于更新和首次初始化的 LuCI 保存失败。

验证入口：`openwrt/tests/wifi-diff-preserve.py`、
`openwrt/tests/wireless-defaults.py`、`boot/tests/part-update.py`。

## 信息屏 eSIM

网页后端使用 `/usr/lib/lpac` 和 `/usr/libexec/unisoc-modem/euicc`；
信息屏依赖探测将 `fs.access` 的执行模式误写成数字 `1`，而 ucode 接收
字符串 `x`。真实目标解释器确认前者返回空、后者返回可执行，因此组件齐全
仍会显示需要安装。现已使用正确模式，不增加隐藏安装或其他后端。

`openwrt/tests/euicc-screen-status.py` 用实际 ARM64 ucode/fs 测试组件齐全、
缺失和不可执行；`openwrt/tests/euicc-screen.py` 检查屏幕 RPC 调用链。
本轮未在 E5 实体屏或 eUICC 上执行下载、启停、删除等操作，未热部署。
