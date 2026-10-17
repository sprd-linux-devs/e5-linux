#!/bin/bash
# Build OpenWrt's modemmanager package with the E5's unisoc plugin.
#
#   openwrt/build-modemmanager.sh        -> out/openwrt/modemmanager-*.apk
#
# OpenWrt 25.12 ships ModemManager 1.24.0, the version device/debian_device_common/patches/
# modemmanager source patches are written against, so the Debian image and the
# OpenWrt one run the same plugin (docs/FINDINGS.md 37).  The patches go into
# the feed package's patches/ after OpenWrt's own (0001-0004, which they stack
# on cleanly), and patches/modemmanager-package-*.patch adjusts the package's
# OpenWrt glue (its hotplug helpers drop virtual netdevs, and sipa_eth0 is one).
#
# Built from OpenWrt's source tree at the release tag, in a container of the
# host's own architecture: the release SDK exists only as an x86_64 program,
# which Docker on an arm64 host can run only emulated -- far too slow (hours,
# for glib2 alone).  The buildroot builds its cross toolchain on any host, so
# it is set up exactly as the release was built -- the tag, the feeds pinned in
# the release's feeds.buildinfo, its config.buildinfo -- and the package comes
# out for the same toolchain (gcc, musl) as the repository's packages it is
# installed with.
#
# The tree lives in the Docker volume e5-openwrt-src and is kept between runs:
# the first run builds the host tools and the toolchain (tens of minutes), a
# later one only ModemManager.  `docker volume rm e5-openwrt-src` starts over.
#
# Configuration: no QMI, MBIM or QRTR (this modem speaks AT only, and without
# them the package does not pull libqmi/libmbim/libqrtr in); AT commands over
# D-Bus on, as in the Debian build (mmcli --command, e5-at).
#
# The release is OpenWrt's plus 900 (1.24.0-r11 -> r911): the repository's
# package never looks newer, so `apk upgrade` does not replace this one with a
# modemmanager that has no unisoc plugin.  Plus E5REV, the revision of the E5
# patches: raised whenever one of them changes, so that apk takes the rebuilt
# package for a new one (it does not reinstall a version it has).
set -euo pipefail
# 1: +IMSREGADDR/+SPNRINDICATE among the ignored unsolicited reports
# 2: context 1 is the modem's net port (sipa_eth8 for the second SIM card)
# 3: +SPSWDATA in the power-up from +CFUN: 0 (the port's card as the data card)
# 4: both cards up from +CFUN: 0, and +SPSWDATA before every dial (SIM card switch)
# 5: the work modes (+SPTESTMODEM) in that power-up, no stop on the other card's errors,
#    and the SIM slots (both cards listed; a switch through e5-sim)
# 6: rebuild legacy cached APKs and require a source/checksum manifest.
# 7: card-addressed SMS submit through the existing AT command owner.
# 8: native per-call SIM slot and dual-card voice tracking.
# 9: discard snapshots taken before a dial completed; retain undecodable calls.
# 10: skip absent SIM power-up and restore the selected AT context.
# 11: consume IMS PDN unsolicited reports instead of failing an outgoing call.
# 12: confirm transient empty call lists and adopt existing outgoing CP calls.
# 13: serialize hangup, settle before redial and ignore pre-hangup CLCC snapshots.
# 14: detached, owner-aware CEUS/CEMODE confirmation with bounded retries.
# 15: PAP/CHAP credentials through the shared Unisoc AT owner.
# 15: mobility-safe CGEV/SPPCODATA events and in-place bearer address renewal.
# 16: include shared APN, pre-dial replay and recovery glue in APK upgrades too.
# 17: replace the complete netifd snapshot so old addresses/DNS do not survive.
# 18: standalone mask conversion and retry a rejected address update safely.
# 20: isolate ambiguous dual-SIM CMTI indices and restore scoped SMS AT context.
# 21: keep compound SMS prompt transactions out of context restoration.
# 22: fail on invalid power/mode readback and failed activation prerequisites.
# 23: retry transient first registration/PDP/IP failures with cancellable backoff.
# 25: PS registration events resume offline data setup without losing autostart.
# 26: stock indexed call release; failed hangup remains visible and retryable.
# 27: stock ECIND SIM events through the existing MM owner; no SIM polling.
# 28: retry registration-cancelled setup; cycle PDP backoff through 1/3/5/7 s.
# 29: alphanumeric APN identities and all PDP ports in the selected SIM bank.
# 30: persistent per-slot RF permission, respected by cold/warm power-up.
# 31: exact SIPA rules compatible with MM's restricted non-udev matcher.
# 32: netifd availability wait for an explicitly disabled data SIM.
# 33: data teardown preserves RF by default; explicit disable_modem wins.
# 34: keep the logical modem enabled for the other SIM's voice/SMS when the
# data radio is off, without powering that disabled data radio back on.
E5REV=34
VER=${E5_WRT_VER:-25.12.5}
HERE="$(cd "$(dirname "$0")" && pwd)"
TOP="$(cd "$HERE/.." && pwd)"
WORK="$TOP/work/openwrt"
OUT="$TOP/out/openwrt"
URL=https://downloads.openwrt.org/releases/$VER/targets/armsr/armv8
mkdir -p "$WORK" "$OUT"

for f in config.buildinfo feeds.buildinfo; do
    curl -fsSL --retry 5 --retry-all-errors -o "$WORK/$f" "$URL/$f"
done

# the source patches, numbered after OpenWrt's own
rm -rf "$WORK/patches" && mkdir -p "$WORK/patches/src" "$WORK/patches/pkg"
TESTS="$TOP/device/openwrt_device_common/tests"
cp "$TESTS/voice-identity.py" "$WORK/voice-identity.py"
cp "$TESTS/sim-power.py" "$WORK/sim-power.py"
cp "$TESTS/voice-urc.py" "$WORK/voice-urc.py"
cp "$TESTS/voice-recovery.py" "$WORK/voice-recovery.py"
cp "$TESTS/data-priority-hook.py" "$WORK/data-priority-hook.py"
cp "$TESTS/modem-mobility.py" "$WORK/modem-mobility.py"
cp "$TESTS/sms-isolation.py" "$WORK/sms-isolation.py"
cp "$TESTS/sim-events.py" "$WORK/sim-events.py"
cp "$TESTS/voice-hangup.py" "$WORK/voice-hangup.py"
cp "$TESTS/modem-data-ports.py" "$WORK/modem-data-ports.py"
cp "$TESTS/modem-data-port-rules.py" "$WORK/modem-data-port-rules.py"
cp "$TESTS/sim-radio-parser.py" "$WORK/sim-radio-parser.py"
COMMON="$TOP/device/openwrt_device_common"
cp "$COMMON/files/modemmanager-unisoc-renew" "$WORK/modemmanager-unisoc-renew"
mkdir -p "$WORK/device/openwrt_device_common/shared" "$WORK/device/openwrt_device_common/overlay/usr/libexec"
cp "$COMMON/shared/network-startup.py" "$WORK/device/openwrt_device_common/shared/network-startup.py"
cp "$COMMON/shared/network-startup-defaults" "$WORK/device/openwrt_device_common/shared/network-startup-defaults"
cp "$COMMON/overlay/usr/libexec/e5-mm-report-ports" "$WORK/device/openwrt_device_common/overlay/usr/libexec/e5-mm-report-ports"
mkdir -p "$WORK/device/openwrt_device_common/overlay/etc/hotplug.d/wwan" "$WORK/device/openwrt_device_common/overlay/etc/init.d"
cp "$COMMON/overlay/etc/hotplug.d/wwan/26-e5-sipa-eth" "$WORK/device/openwrt_device_common/overlay/etc/hotplug.d/wwan/26-e5-sipa-eth"
cp "$COMMON/overlay/usr/libexec/e5-network-recovery" "$WORK/device/openwrt_device_common/overlay/usr/libexec/e5-network-recovery"
cp "$COMMON/overlay/etc/init.d/e5-network-recovery" "$WORK/device/openwrt_device_common/overlay/etc/init.d/e5-network-recovery"
n=900
for p in "$TOP"/device/debian_device_common/patches/modemmanager-[0-9][0-9]-*.patch; do
    cp "$p" "$WORK/patches/src/$n-e5-$(basename "$p" | sed 's/^modemmanager-//')"
    n=$((n + 1))
done
cp "$HERE"/patches/modemmanager-package-*.patch "$WORK/patches/pkg/"

# the container is the host's architecture (the buildroot cross-compiles for the target either way);
# E5_DOCKER=podman on a host without docker (SELinux wants the bind mounts relabelled, :z)
DOCKER=${E5_DOCKER:-docker}
case "$(uname -m)" in x86_64) PLAT=linux/amd64;; *) PLAT=linux/arm64;; esac
Z=; [ "$DOCKER" = podman ] && Z=,z
$DOCKER run --rm --platform $PLAT -v e5-openwrt-src:/build \
    -v "$WORK":/work:ro$Z -v "$OUT":/out${Z:+:z} -e VER="$VER" -e E5REV="$E5REV" \
    -e JOBS="${E5_JOBS:-$(sysctl -n hw.ncpu 2>/dev/null || nproc)}" \
    "${E5_MODEM_BUILD_IMAGE:-debian:trixie}" bash -euc '
export DEBIAN_FRONTEND=noninteractive
# Reuse a compatible prepared image when supplied, and bound mirror stalls.
# HTTPS is used only when trusted CA certificates are already available.
if [ -s /etc/ssl/certs/ca-certificates.crt ]; then
    sed -i "s@http://deb.debian.org/@https://deb.debian.org/@g" /etc/apt/sources.list.d/debian.sources
fi
apt_opts="-o Acquire::http::Pipeline-Depth=0 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 -o Acquire::Retries=3"
apt-get $apt_opts update -qq
apt-get $apt_opts install -y -qq --no-install-recommends build-essential ca-certificates clang file flex bison \
    gawk gettext git libncurses-dev libssl-dev python3 python3-setuptools rsync swig unzip wget \
    xz-utils zlib1g-dev zstd libglib2.0-dev pkg-config >/dev/null
# the buildroot refuses to run as root unless told otherwise; it lives in the
# volume, which is case-sensitive (a macOS bind mount is not)
export FORCE_UNSAFE_CONFIGURE=1
cd /build
[ -d openwrt/.git ] || git clone -q --depth 1 --branch v$VER https://git.openwrt.org/openwrt/openwrt.git openwrt
cd openwrt
# the feeds at the commits the release was built from
cp /work/feeds.buildinfo feeds.conf
# (a feed whose clone failed leaves only its index behind: update until every feed has its tree)
for try in 1 2 3 4 5; do
    missing=$(awk "/^src-/{print \$2}" feeds.conf | while read -r f; do [ -d feeds/$f/.git ] || echo $f; done)
    [ -z "$missing" ] && break
    echo "feeds to update: "$missing
    for f in $missing; do rm -rf feeds/$f feeds/$f.*; ./scripts/feeds update $f >/dev/null || true; done
done
[ -z "$missing" ] || { echo "feeds not cloned: $missing"; exit 1; }
./scripts/feeds install modemmanager python3 dbus-utils >/dev/null
P=feeds/packages/net/modemmanager
# the package directory back to the feed state, then the E5 changes on top
git -C feeds/packages checkout -q -- net/modemmanager
git -C feeds/packages clean -qfd -- net/modemmanager
install -Dm755 /work/modemmanager-unisoc-renew "$P/files/usr/sbin/modemmanager-unisoc-renew"
for p in /work/patches/pkg/*.patch; do patch -p1 -d $P < "$p"; done
# Match the rootfs stager: upgrading this APK must retain APN selection,
# boot replay, port discovery, initial EPS preservation and PDP retries.
# Package files have no board config, so only the shared glue is affected.
python3 /work/device/openwrt_device_common/shared/network-startup.py --root "$P/files" --profile e5
cp /work/patches/src/*.patch $P/patches/
rel=$(sed -n "s/^PKG_RELEASE:=//p" $P/Makefile)
sed -i "s/^PKG_RELEASE:=.*/PKG_RELEASE:=$((rel + 900 + E5REV))/" $P/Makefile
echo "modemmanager release $rel -> $((rel + 900 + E5REV)); patches:"; ls $P/patches/
# the release configuration, reduced to what is needed here
{
    # (not CONFIG_BUILDBOT: on the release builders it also builds LLVM for
    # BPF, which nothing here needs)
    grep -E "^CONFIG_(TARGET_|GCC_|LIBC|MUSL|BINUTILS|KERNEL_|USE_|PKG_|SIGNED)" /work/config.buildinfo || true
    echo "CONFIG_BPF_TOOLCHAIN_NONE=y"
    echo "# CONFIG_BPF_TOOLCHAIN_BUILD_LLVM is not set"
    echo "CONFIG_PACKAGE_modemmanager=m"
    echo "CONFIG_PACKAGE_modemmanager-rpcd=m"
    echo "CONFIG_MODEMMANAGER_WITH_NETIFD=y"
    echo "# CONFIG_MODEMMANAGER_WITH_MBIM is not set"
    echo "# CONFIG_MODEMMANAGER_WITH_QMI is not set"
    echo "# CONFIG_MODEMMANAGER_WITH_QRTR is not set"
    echo "CONFIG_MODEMMANAGER_WITH_AT_COMMAND_VIA_DBUS=y"
} > .config
make defconfig >/dev/null
grep -E "^CONFIG_(GCC_VERSION|LIBC_VERSION|TARGET_ARCH_PACKAGES)=|^(# )?CONFIG_MODEMMANAGER" .config
if [ ! -f staging_dir/.e5-toolchain-ok ]; then
    echo "== host tools and toolchain (first run)"
    make tools/install toolchain/install -j"$JOBS" >/build/log 2>&1 || { tail -60 /build/log; exit 1; }
    touch staging_dir/.e5-toolchain-ok
fi
# the kernel, for the kmod packages the dependencies ask for (ppp wants
# kmod-ppp); none of them is installed -- the E5 runs its vendor kernel
if [ ! -f staging_dir/.e5-kernel-ok ]; then
    echo "== kernel (first run)"
    make target/linux/compile -j"$JOBS" >/build/log 2>&1 || { tail -60 /build/log; exit 1; }
    touch staging_dir/.e5-kernel-ok
fi
echo "== modemmanager"
make package/modemmanager/clean >/dev/null 2>&1 || true
make package/modemmanager/compile -j"$JOBS" >/build/log 2>&1 || { tail -80 /build/log; exit 1; }
voice_source=$(find build_dir -path "*/modemmanager-*/src/mm-iface-modem-voice.c" -print -quit)
[ -n "$voice_source" ] || { echo "missing patched voice source" >&2; exit 1; }
python3 /work/voice-identity.py "$(dirname "$voice_source")"
python3 /work/sim-power.py "$(dirname "$voice_source")"
python3 /work/voice-urc.py "$(dirname "$voice_source")"
python3 /work/voice-recovery.py "$(dirname "$voice_source")"
python3 /work/data-priority-hook.py "$(dirname "$voice_source")"
python3 /work/modem-mobility.py "$(dirname "$voice_source")" /work/modemmanager-unisoc-renew
python3 /work/sms-isolation.py "$(dirname "$voice_source")"
python3 /work/sim-events.py "$(dirname "$voice_source")"
python3 /work/voice-hangup.py "$(dirname "$voice_source")"
python3 /work/modem-data-ports.py "$(dirname "$voice_source")"
python3 /work/modem-data-port-rules.py "$(dirname "$voice_source")"
python3 /work/sim-radio-parser.py "$(dirname "$voice_source")/plugins/unisoc/mm-broadband-modem-unisoc.c"
rm -f /out/modemmanager*.apk
find bin/packages -name "modemmanager*-r$((rel + 900 + E5REV)).apk" -exec cp {} /out/ \;
ls -la /out/modemmanager*.apk
'
python3 "$TOP/tools/openwrt-package-state.py" write "$VER"
