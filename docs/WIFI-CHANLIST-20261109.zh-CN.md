# E5 公共 Wi-Fi：切频段后的信道列表

参考 MU300 上游 [PR #432](https://github.com/dikeckaan/mu300-linux/pull/432)。
E5 原公共 hostapd 配置处理只有 DFS 检查，没有对 chanlist 按当前频段过滤；
如果 LuCI 的 2.4 GHz／自动信道仍带着 36／40／44／48 等 5 GHz 列表，ACS
无法找到可用信道。因此这里同样存在触发条件，不能因某一机型未报告就排除。

在 devices/t551m/network-startup.py 的公共 patch_wifi_capabilities 中加入
频段检查。历史目录名不代表只用于 T551M；共用的机型 staging／默认配置
处理会带入全部 E5 仓库机型。原机型差异和 ModemManager 路径不变。

- 按当前频段实际 wiphy 频率检查信道及范围端点，保留合法项；全部不匹配
  时删除临时生成配置里的列表，让 ACS 使用该频段。UCI 用户配置不被改写。
- 反向切频段同样处理；合法字符串／列表保持，畸形和倒序范围被过滤。
- 现有 DFS、频宽、法规与加密策略保留，不采用上游不同的 DFS／带宽策略。
- 旧 DFS-only 根可原入口幂等迁移；异常或重复调用点拒绝并保持原文件，
  不是仅向新装镜像塞入函数。补丁仍不引入驻留服务或轮询。

验证：4 项布局／迁移／失败不写入回归通过；额外用真实 OpenWrt 25.12.5
feed wifi-scripts 执行配置生成，覆盖 8 种 2g／5g 残留列表、范围、HT40／
VHT80、合法列表、DFS 与具备雷达检测能力的情形。另保留原目标根测试入口的
纯 ucode 检查。容器没有连接无线硬件，未修改或重启任何实机，未编译内核
或打包；以上不能替代硬件热点验收。

日志：out/build-logs/20261109-050339-wifi-chanlist-runtime-3748/command.log。

## 屏蔽不支持的 160 MHz 选项

按用户要求，在共用 LuCI 频率控件隐藏 VHT160／HE160／EHT160，以及等效的
80+80 选项；保留 20／40／80 和 N／AC／AX 模式。limit-wifi-widths 通过
构建、插件安装、uci-defaults 和现有 UI 服务启动执行，不增加轮询。仅修改
视图，不覆写无线 UCI；旧值用隐藏且禁用的占位保留，保存时按界面语言提示
选择支持的带宽，避免打开页面就清空或降档。原生主题和 Aurora 共用同一控件。
真实 LuCI 控件的选项、旧值、验证、幂等与异常不写入等 4 项离线回归通过；
日志 out/build-logs/20261109-051403-wifi-width-choices-4052/command.log。
