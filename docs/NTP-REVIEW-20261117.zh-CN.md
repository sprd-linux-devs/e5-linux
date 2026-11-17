# 校时顺序同步

同步 MU300 的校时启动逻辑，使用 E5 自己的 `/opt/e5/bin/busybox` 和
`e5-ntpd`。原默认 pool 配置先用数字 IPv4/IPv6 端点尝试，最多 20 秒；
失败则回到原域名列表。没有修改 UCI 配置，不强开校时服务。

接入原生完整 rootfs、共用九机型 prepare-root 和 TF 打包入口。重复准备
不重复修改 sysntpd，用户自定义/DHCP 服务器、停用、权限与 jail 均保留。

按用户要求，E5 的 next-boot、试启动和回滚次数完全不变。SC2355 PCIe 的
WCN PR #8 不直接用于 E5 集成式无线；本次未调整 E5 无线驱动或基带。

6 项离线回归通过，并用实际 E5 base 的 sysntpd 核对首次及重复集成。
没有连接设备、更改时钟或进行实机验收。
