# 本地构建与打包规范

本机 Agent 的完整操作指南见 [AGENT-BUILD.zh-CN.md](AGENT-BUILD.zh-CN.md)。
Windows/固件在本机完成；Apple Silicon App 可按用户授权使用上游 macOS CI 原生重编，下载后仍须通过源码指纹校验。

本文件是本地多机型构建的入口；`docs/RELEASE.md` 另行说明 GitHub Actions。
不再用 `work/` 下日期命名的 worker、复制旧 worker 或字符串替换执行旧脚本。
本规范不启动构建、不迁移目录、不清除历史文件，也不改变设备安装流程。

## 固定位置

| 内容 | 位置与规则 |
| --- | --- |
| 仓库源码 | 当前 E5 Git 工作区，不再额外复制整个仓库 |
| 共用屏幕源码 | `devices/common/infoscreen/`，所有屏幕机型共用；设备端路径和既有服务名保持不变 |
| Linux 构建工作区 | 本机既有 `/home/kano/openwrt-build`，不迁往 C 盘 |
| 内核源码、对象 | 复用工作区的既有缓存；本次不重建或迁移各机型缓存 |
| 干净公共 rootfs | 工作区 `base/e5` 一份；不得使用含用户配置的实机 root |
| 内核配套交付件 | `tools/build-layout.json` 中各机型的 `kernel` 路径 |
| 打包临时根目录 | 工作区 `package-work/e5-release/<profile>/assembly` |
| 通用临时文件 | 工作区 `tmp/e5-release-*`，每步结束自动删除；不创建日期命名源码/root 缓存 |
| 任务日志、状态 | 仓库 `out/build-logs/<task>/`，最近任务 `out/build-state/latest.json` |
| 正式产物 | 仓库 `out/releases/<task>/`，全部机型校验通过才成为正式目录 |
| 版本固定的安装器缓存 | `{workspace}/artifacts/openwrt-tools/<installer_commit 前7位>/{windows,macos-arm64,android}` |
| 本机原生编译输出 | `installer/artifacts/windows`、`installer/artifacts/macos-arm64`、`installer/artifacts/android`；通过既有环境变量显式选择 |
| 排查资料、设备备份 | 仍在既有 `work/`、`dumps/`，不参与自动清理 |

`tools/build-layout.json` 是受版本控制的路径登记表，支持 `{repo}` 与 `{workspace}`。
路径对应现有输入，不把某台电脑的盘符硬编码进执行器。另一环境可显式传入
`--config /absolute/path/build-layout.local.json`，禁止随机搜索并挑一个旧包代替缺失输入。
内核交付件可以暂留旧位置；规范化流程不等于复制一份缓存到“新标准目录”。

## 分阶段执行

所有下列 Linux 命令在仓库根目录执行；本机先进入 `wsl -d Ubuntu-22.04`，
然后 `cd /mnt/d/Git/e5-linux`。工具默认工作区为当前 Linux 用户的
`~/openwrt-build`；使用 root/sudo 时明确指定 `--workspace /home/kano/openwrt-build`。

### 1. 只看计划和验证输入

安装器版本和三平台归档摘要由 `tools/installer-inputs.lock.json` 固定，
缓存路径由 `tools/build-layout.json` 的 `{installer_revision}` 自动展开。
它与 Pro 使用同一公共安装器及共享缓存，不复制 SDK、源码或根文件系统。
首次准备预编译工具：

```sh
python3 tools/build-release.py prepare-installers --workspace /home/kano/openwrt-build --label installer-inputs
```

此操作仅下载／校验锁定的工具，不编译固件、不连接设备。`plan`／`check` 保持只读。
安装器子模块提交、归档版本、文件摘要或源码指纹不一致时停止；不会回退旧缓存。
`OPENWRT_GUI_ARTIFACT`、`OPENWRT_GUI_MACOS_ARTIFACT` 和
`OPENWRT_GUI_ANDROID_ARTIFACT` 仍可显式选择本机产物，且必须通过同样的源码／文件校验。
发布器会将选定路径传给组包及安装器刷新子进程。

```sh
python3 tools/build-release.py plan --profiles all
python3 tools/build-release.py check --profiles e5 t551m m8 t512n yuanhang41s k1
```

两者不创建构建目录，不复制 rootfs、不下载、不编译、不连接设备。
`check` 核验输入存在、软件包源码/哈希、两个安装器的源码指纹与文件哈希、
各机型内核和完整模块配套。缺失或过期即停止，不自动选另一份缓存。
复用内核仍需确认内核相关源码没有变更：已有 `container-support.json` 只能
证明交付件配套，不能证明当前源码已经编译进去。

### 2. 仅在相应源码变化时编译

编译命令通过固定入口执行，复用现有原生构建器，统一互斥、日志和状态：

```sh
python3 tools/build-release.py run --label modem -- bash openwrt/build-modemmanager.sh
python3 tools/build-release.py run --label wifi -- bash openwrt/build-hostapd.sh
python3 tools/build-release.py run --label block-mount -- bash openwrt/build-block-mount.sh
```

内核同样用 `run --label <model>-kernel -- <该机型原有命令>`。对应入口为：

| 机型 | 现有构建入口 |
| --- | --- |
| E5 | `devices/e5/build-kernel.sh` |
| T551M | `devices/t551m/build-kernel.sh`，发行构建设置 `T551M_RELEASE=1` |
| T512N | `devices/t512n/build-kernel.sh`，发行构建设置 `T512N_RELEASE=1` |
| M8 | `devices/m8/build-probe.sh`，完整配套由 `devices/m8/package-kernel.py` 生成 |
| 远航 41S | `devices/yuanhang41s/build-kernel.py` |
| K1 | `devices/k1/build-kernel.py` |
| 岭燕 LYM-10K（bring-up） | `devices/lym10k/build-kernel.sh`，`LYM10K_RELEASE=1` |

各构建器原有的 source、objects、baseline、output 参数仍需显式设置，指向
已经核对过的缓存；`run` 负责调度、日志，不会替你猜基线或重置源码。
某个共享对象目录目前属于哪个机型，必须先核对其 `.config` 和
`include/config/kernel.release`。源码打过其他机型补丁时也不能直接改配置硬编。
目前没有自动、安全切换所有模型源码基线的实现，禁止冒充“一键全量重编”。

对于只留有远航 41S 源码缓存的这台 WSL，E5、T551M、M8、T512N、LYM-10K 现在可以使用
`tools/build-profile-kernel.py`。它在现有缓存上建立 overlayfs 只读底层与各机型
独立的补丁层，不复制整个源码，不修改原有 41S 文件，也不复用 41S 的对象目录。
底层的版本和状态由 `tools/build-layout.json` 登记，修改过的源码及新增文件在
私有视图中恢复到指定 Git 基线，通过干净检查后才调用上表原有准备器／构建器。
Git 对象库共用，索引、补丁层、对象和模块交付件按机型分开；构建退出时卸载视图。

K1 和远航41S 已有独立的原生源码／对象缓存，登记在 `tools/build-layout.json`
的 `native_kernel_builds`。它们分别使用 `k1/linux-cache`＋`k1/build`、
`sources/e5-kernel`＋`objects/e5-family`；后者的名字虽然含 e5-family，
现有 `.config` 和 release 必须是远航41S，不能当其他机型的共享对象目录。
两者的完整平台基线均为已验证的 `kernels/m8/config`，输出仍取各 profile 的 kernel 路径。
通过 `build-release.py run` 调用各自的 `devices/<profile>/build-kernel.py`，
显式传入登记的 `--kernel`、`--build`、`--base-config`、`--out`；不建立新源码副本。
远航41S 构建会重放自己的准备流程，之后使用 overlay 视图前需按下述规则核对底层指纹。

```sh
sudo python3 tools/build-release.py run --workspace /home/kano/openwrt-build \
  --label e5-kernel -- python3 tools/build-profile-kernel.py \
  --workspace /home/kano/openwrt-build --profile e5 --jobs 8
```

固定补丁层位于 `kernel-views/<profile>/upper`，对象目录为 `objects/<profile>`。
如果底层源码发生改变，或发现未登记的对象、已挂载的视图或错误所有权，命令会停止，
不会清空缓存强行套用。所有模型任务仍需使用同一把构建锁；不能在视图挂载期间
运行其他工具修改其底层。41S 与 K1 继续使用原有已准备缓存和上表构建入口。
如果底层指纹变化但当前全部变动路径均被已有私有文件或 whiteout 完整遮蔽，
可先通过同一锁入口执行下面的显式核对。它逐路径核对遮蔽关系、版本、所有权、
私有 Git 索引和未挂载状态，记录旧/新指纹；只更新登记，不改源码/对象，不编译。
任何未遮蔽的新路径仍会停止。核对通过后再执行正常模型构建，不使用旧编译件冒充新修复。

```sh
sudo python3 tools/build-release.py run --workspace /home/kano/openwrt-build \
  --label e5-source-review -- python3 tools/build-profile-kernel.py \
  --workspace /home/kano/openwrt-build --profile e5 --review-shadowed-lower
```

`python3 tools/tests/kernel-overlay.py` 在临时 Git 夹具及真实 overlayfs 上验证隔离、
复挂与底层变更拒绝，不写模型缓存，不连接设备；需要 Linux root 挂载权限。

Windows x64 与 Apple Silicon 安装器继续在对应原生环境运行
`python installer/build.py`。两端构建各一次，所有机型合包共用这两份 artifact；
不逐机型重复编译 GUI，不在 Linux 上伪造 macOS 构建。保留原有源码指纹校验。

### 3. 组装发布包

```sh
sudo python3 tools/build-release.py package --workspace /home/kano/openwrt-build --profiles all
```

也可用 `--profiles e5 t551m` 选择机型。该命令：

1. 先验证所有选中机型及 Windows/macOS 输入，发现问题在复制 rootfs 前停止。
2. 取得工作区互斥锁；按机型串行组装，同一时刻只新增一个打包 root。
3. 调用既有 `openwrt/build-profile-tf.py`，保留设备、隐私、模块和安装包校验。
4. 再核对 ZIP CRC、重复文件、每个文件 SHA-256，确保一份 boot 和一份系统镜像。
5. 每个机型成功后删除本任务持有的 staging，不累计每个日期的一份 rootfs。
6. 全部机型通过、源码指纹未变后，将 `.building-<task>` 原子改名为正式目录。
   内附 `BUILD-RUN.json`，记录源码、任务、日志、文件大小和 SHA-256。

每个正式 ZIP 固定包含 `OpenWrt-Diff-Studio.exe`、Apple Silicon 的
`OpenWrt-Diff-Studio.app` 和 Python 入口。`tools/package-diff-studio.py` 在最终校验前装入，
复用已验证的原生 GUI，保持 Mac APP 内部签名内容不变；与安装器共用 `tools` 中的后端，
不另复制整套运行环境。`diff-tool.json` 只登记补丁工具需要的文件，导出更新器时不会带入
boot、rootfs 或 ADB。最终 ZIP 校验同时检查这份工具清单；后续打包不再另行手动补塞。

组装过程中仍会编译原有的少量静态辅助程序；不会重编内核、ModemManager、
hostapd 或 GUI。正式目录本身包含唯一 ZIP，不另保留整份解压发布目录。

### 4. 查看状态与处理失败

仅安装器脚本／随包工具变化，固件与 boot 不变时，可快速刷新上一份已验证发布：

```sh
python3 tools/build-release.py refresh-installers --workspace /home/kano/openwrt-build \
  --profiles all --source-release /absolute/repo/out/releases/<verified-task>
```

该路径通过同一把工作区锁，只接受带已验证 `BUILD-RUN.json` 的本地正式发布，
先核对全部输入 ZIP／哈希；生成独立安装锁工具增补包并流式替换安装脚本、两平台原生安装器及 Diff Studio，不解压 rootfs，
不重编内核。GUI／后端有变化时必须先完成原生构建，刷新入口只消费已通过源码指纹校验的交付件。
移除旧清单中已被新运行环境淘汰的文件，不累计旧依赖，不增加第二份后端。
新 ZIP 名带 `-installer-g<提交>`，固件版本及 ext4 工具包保持不变，兼容原有续装记录，
`files/INSTALLER-REVISION.json` 记录宿主工具修订和原镜像哈希。旧发布不修改；
全部新 ZIP 校验通过后才发布。固件／boot 变化仍必须使用普通 `package` 路径。

```sh
python3 tools/build-release.py status
sudo python3 tools/build-release.py clean-staging --workspace /home/kano/openwrt-build --profiles t551m
```

每一步的命令、起止时间、状态与日志在 `status.json`。运行时打印日志路径，
可以用 `tail -f <日志>` 查看进度。失败明确记录为 failed，不宣称产物齐全。
保留的 `.building-*` 是未发布现场，不可提供给用户。

失败后先看日志；确认不需要现场再运行 `clean-staging`。它只删除固定目录内
带匹配所有权标记的打包 staging，拒绝符号链接、越界路径及仍有挂载的目录。
源码、对象、下载缓存、安装备份、其他工具旧 staging 和历史发布包都不在其范围。
需要整理旧目录时单独列清单处理，不能把 `docker prune` 或删除缓存当日常步骤。

`run`、`package`、`clean-staging` 使用同一把锁，防止清理与构建并行。旧脚本直接
执行无法被这把锁管住，所以本地构建必须经过此入口；CI 在独立 runner 继续原流程。

畅行60（`changxing60`，P720S20 UFS 4Kn）已接入相同构建入口；内核仍用登记的 `tools/build-profile-kernel.py --profile changxing60`，正式包用 `--profiles changxing60`。Windows/Mac 安装器必须包含新的存储库；见 [安装接入与验收边界](CHANGXING60-INSTALL.zh-CN.md)。


## 公共安装器子模块

installer/ 现在固定引用 https://github.com/kanoqwq/openwrt-tools 的提交。新检出先执行 git submodule update --init --recursive。共享源码、Android 及独立工具构建方法见 installer/docs/BUILD.zh-CN.md；E5/MU300 的 NV、UFS 身份和启动流程继续分开处理。请先在子模块提交，再在父仓库更新 gitlink；不要重新复制一整份安装器。

两个父仓库可通过 OPENWRT_GUI_ARTIFACT 与 OPENWRT_GUI_MACOS_ARTIFACT 复用同一份已校验交付件，无需各编译一次；首次拆分后旧 GUI 指纹应正常拒绝，不能修改旧 build.json 绕过。tools/release-index.py、tools/build-release-index.py、tools/package-diff-studio.py 保留为兼容入口，实际代码由子模块提供。


## 根目录 Android 安装器

完整打包及 refresh-installers 均由公共 installer/package_android.py 校验已签名 ARM64 release APK 的源码、ABI 与哈希，发布包根目录固定放 OpenWrt-Tools.apk，构建清单为 docs/GUI-BUILD-android.json，使用说明为 docs/ANDROID-INSTALLER.md。不要把 APK 塞进 tools 或再复制一份。

本机与两个桌面交付件一样复用 E5 的 Android 构建：WSL 设置 OPENWRT_GUI_ANDROID_ARTIFACT=/mnt/d/Git/e5-linux/installer/artifacts/android；Windows 使用 D:/Git/e5-linux/installer/artifacts/android。过期时只重编 Android，不修改 build.json。

Mac 原生构建使用公共安装器仓库的 macos.yml，手动 dispatch 即可；不再在 E5 仓库新建 build/macos-* 快照分支。下载后仍核对公共 sources()。
