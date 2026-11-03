# 按 SIM 保存的数据漫游权限

网络锁定页增加与 VoLTE/频段锁定同款的「数据漫游」区域，默认
关闭，保存到 `unisoc_modem.main.allow_roaming0/1`。页面选卡仍用
E5 的 `M.simSlot()`，不照搬 MU300 的另一个前端选卡接口。
APN 中的漫游 IP 协议与本开关独立。

## E5 原生数据框架

使用 ModemManager 已有的 `allow-roaming=yes/no` bearer 参数，
由当前内核 SIPC card 选择相应 SIM 权限。仅修改 unisoc-sipc 的
设置，其余 MM 插件保留原有 WAN 配置；没有加入厂商漫游 AT，
不触碰初始化 EPS、RF/IMS/通话/短信。

`modemmanager-package-roaming-policy.patch` 将按卡权限接入既有
netifd connect 参数。现有 `e5-network-recovery` 加入权限事件：
禁止漫游时暂停数据；允许漫游或回到本地网络后恢复可用性。
当前卡的权限改变时重建数据 bearer，使新的原生参数生效；
切换上网 SIM 本身不额外触发第二轮重连。手动 ifdown、PIN、
缺卡、射频关闭等既有限制仍有效。

RPC 读取的是权限和 MM 缓存的实际注册状态，非上网卡状态未知
时返回 null，不编造「本地」或「漫游」。模组尚未出现时仍可
保存权限。uci 保存和事件通知失败分别返回语义化错误。

## 当前驻网显示

成功实时信号不再继承旧元数据错误，旧信号不能覆盖较新的错误；
真实失败清理旧 dBm/RSRQ/SINR，技术详情不作为网络制式标题。
仅有 C5GREG 回复也不再被判定为「AT 完全无应答」。保留 E5
原有 nr6/nr7 采集与 AT 所有权，没有引入 MU300 的后台进程。

## 构建与验证

新增 helper/RPC/ACL/default 与前端属于现有 LuCI 公共构建路径；
新的 MM package shell 补丁由既有 build-modemmanager.sh 收录。
下次出包须重建这份有变更的 MM 包，不能只换前端或复用旧指纹。
内核/模块没有因此修改。

5 项适配器测试、18 项现有恢复及新增权限事件回归、原有 busy
测试和 MM 补丁应用/语法测试通过。18 组语言/主题/宽度下检查
开关、加载、错误和只读权限。单元测试使用合成注册/传输替身。
本轮未部署到 E5 家族实机，也未实测真实漫游运营商，不能把
U30 Pro 的实机结果当作这些机型的硬件验收。
