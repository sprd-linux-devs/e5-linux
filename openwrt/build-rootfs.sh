#!/bin/bash
# Build the E5's OpenWrt tree: out/openwrt/e5-openwrt-<version>-rootfs.tar.gz
#
#   openwrt/build-modemmanager.sh      (once, and after a ModemManager patch changes)
#   openwrt/build-rootfs.sh
#
# The tree is OpenWrt's own armsr/armv8 root filesystem (arm64, musl) with the
# E5's parts added -- no kernel, no kmods: the E5 boots its vendor kernel from
# slot b's boot image, and the initramfs starts this tree from a directory of
# the Debian root image (/openwrt, see README.md).  Added:
#
#  * packages from OpenWrt's repository: the access point (wpad-basic-mbedtls,
#    wifi-scripts, iw), bash, util-linux mount, ip-full, LuCI's ModemManager
#    protocol, LuCI in Chinese (luci-i18n-*-zh-cn for what is installed),
#    PulseAudio with BlueZ; and from out/openwrt/ ModemManager, built with the
#    unisoc plugin by build-modemmanager.sh, and BlueZ, patched by
#    build-bluez.sh;
#  * the Argon theme for LuCI (jerrykuku/luci-theme-argon, its release's apk
#    packages, pinned by version and sha256 below) with its settings page;
#  * device/openwrt_device_common/overlay/: the procd services for the hardware, the first-boot
#    configuration, the ModemManager glue, the sysupgrade guard;
#  * from the Debian image's overlay (device/linux_device_common/overlay/opt/e5): the scripts both
#    systems share -- the baseband's vendor chroot, the regulatory database,
#    the USB gadget guard, e5-next-boot, e5-os, e5-at;
#  * a full static busybox (the boot image's own) for the applets OpenWrt's
#    leaves out, logdw (device/openwrt_device_common/src/logdw.c) for the vendor chroot's log, and
#    e5-vibrate (device/openwrt_device_common/src/e5-vibrate.c) for the motor, e5-ctl-raw
#    (device/openwrt_device_common/src/e5-ctl-raw.c) for the audio DSP's profile selects, and
#    e5-modemd (device/openwrt_device_common/src/e5-modemd.c) for the CP's resets;
#  * the speaker: the 24 vendor audio modules of the kernel build (out_linux)
#    in /lib/modules/<release>/audio, alsa-utils, the card's UCM profile
#    (device/linux_device_e5/overlay/usr/share/alsa/ucm2), e5-audio-dsp, and e5-volume;
#
# The firmware and the Android vendor subset are not in the tarball: they are
# the Debian root's, bound in at boot (overlay/lib/preinit/05_e5_debian_root).
#
# E5_STANDALONE=1 builds OpenWrt for a device without Debian instead:
# out/openwrt/e5-openwrt-<version>.ext4.gz, a root image of its own that
# boot/init starts from /data/e5linux/openwrt.ext4 (openwrt/install-standalone.sh
# puts it there).  What the tree would take from the Debian root is in the
# image then:
#
#  * the firmware pulled from the device (device/linux_device_common/overlay/lib/firmware:
#    rootfs/pull-wcn-firmware.sh, pull-audio-firmware.sh, and the Debian-signed
#    regulatory.db) -> /lib/firmware;
#  * the Android vendor subset (work/android-subset,
#    rootfs/extract-android-vendor.sh) -> /opt/e5/android;
#  * the modem's WWAN modules of the kernel build (out_linux: wwan.ko,
#    sipc_wwan.ko) -> /lib/modules/<release>/modem;
#  * Noto Sans CJK (Debian's fonts-noto-cjk) -> /usr/share/fonts/e5-noto, for
#    the info screen.
#
# E5_DEVICE_FILES=0 leaves the device's own files out (the firmware but the
# regulatory database, the vendor subset): e5-openwrt-<version>-generic.ext4.gz,
# the image to give to others (openwrt/make-flash-bundle.sh).  Those files
# are proprietary, and some carry the unit's identity (the BT address in the
# pskey, the serial number among the Android properties); each device pulls
# its own, which boot/init unpacks into the image from
# e5linux/device-files.tar on userdata.
#
# E5_ROOT_MODULES=<tar> adds another kernel's root modules (lib/modules/<release>/...: upstream/root-modules.sh,
# for the mainline kernel) next to the 5.15 ones; the image then runs on either kernel.
# E5_ROOT_MODULES_ONLY=1 uses only that archive, without a local 5.15 build.
#
# Docker is NOT preinstalled by default; matching kernel/container modules and
# the post-install setup helpers are retained for users to install it later.
# E5_DOCKER=1 explicitly preinstalls Docker for a mainline KVM/container kernel. The service
# starts on demand; the image defaults to 2048 MiB to leave room for containers.
# E5_IMAGE_MB sets the image's size (default 1024, or 2048 with Docker). Needs Docker with arm64
# (native on Apple silicon).
set -euo pipefail
VER=${E5_WRT_VER:-25.12.5}
HERE="$(cd "$(dirname "$0")" && pwd)"
TOP="$(cd "$HERE/.." && pwd)"
python3 "$TOP/tools/device-layout.py" check --system openwrt --model e5 >/dev/null
PRIVATE_OVERLAY="$TOP/work/device-files/e5/overlay"
if [ "${E5_DEVICE_FILES:-1}" != 0 ] && [ -d "$PRIVATE_OVERLAY" ]; then
    OVERLAY=$(python3 "$TOP/tools/device-layout.py" overlay --system openwrt --model e5 --private-overlay "$PRIVATE_OVERLAY")
else
    OVERLAY=$(python3 "$TOP/tools/device-layout.py" overlay --system openwrt --model e5)
fi
WORK="$TOP/work/openwrt"
OUT="$TOP/out/openwrt"
URL=https://downloads.openwrt.org/releases/$VER/targets/armsr/armv8
TARBALL=openwrt-$VER-armsr-armv8-rootfs.tar.gz
BUSYBOX=${E5_BUSYBOX:-$TOP/work/busybox/ext/usr/bin/busybox}
# the info screen, from its own repository, when it is there (E5_INFOSCREEN=
# empty leaves it out)
INFOSCREEN=${E5_INFOSCREEN-$TOP/ci/infoscreen}
[ -n "$INFOSCREEN" ] && [ -f "$INFOSCREEN/packages.txt" ] && [ -d "$INFOSCREEN/root" ] || INFOSCREEN=""
SCREEN_PLUGINS=${E5_INFOSCREEN_PLUGINS-$TOP/ci/infoscreen-plugins}
[ -n "$SCREEN_PLUGINS" ] && [ -d "$SCREEN_PLUGINS/plugins/phone" ] || SCREEN_PLUGINS=""
NAME=e5-openwrt-$VER-rootfs.tar.gz
STANDALONE=${E5_STANDALONE:-}
DEVICE_FILES=${E5_DEVICE_FILES:-1}
CONTAINERS=${E5_DOCKER:-0}
FEATURES=${E5_FEATURES:-0}
if [ "$FEATURES" = 1 ]; then
    [ -n "$INFOSCREEN" ] || { echo 'E5_FEATURES=1 requires the E5_INFOSCREEN base package' >&2; exit 1; }
    [ -n "${E5_ROOT_MODULES:-}" ] && [ "${E5_ROOT_MODULES_ONLY:-0}" = 1 ] || {
        echo 'E5_FEATURES=1 requires the matching device/linux_device_e5 mainline module archive' >&2; exit 1; }
fi
DEFAULT_IMAGE_MB=1024
[ "$CONTAINERS" != 1 ] || DEFAULT_IMAGE_MB=2048
IMAGE_MB=${E5_IMAGE_MB:-$DEFAULT_IMAGE_MB}
FIRMWARE=${E5_FIRMWARE:-$OVERLAY/lib/firmware}
ANDROID=${E5_ANDROID_SUBSET:-$TOP/work/android-subset}
KBUILD=${E5_KBUILD:-$TOP/out_linux}
mkdir -p "$WORK" "$OUT"
python3 "$TOP/tools/openwrt-package-state.py" check "$VER"
BLOCK_APK="$OUT/block-mount-guarded.apk"
E5_WRT_VER="$VER" sh "$HERE/build-block-mount.sh" "$BLOCK_APK"
WIFI_APKS="$TOP/work/wifi-sae"
UNISOC_WRT_VER="$VER" sh "$HERE/build-hostapd.sh" "$WIFI_APKS"

# the Argon theme: not in OpenWrt's feeds; its release's packages (arch all)
ARGON_URL=https://github.com/jerrykuku/luci-theme-argon/releases/download/v2.4.7
ARGON_APKS="c5f0e3a55ef96213884184be9aeaadc8586418986c4dde1ff1866be5e938aaef luci-theme-argon-2.4.7-r1.apk
506e2bc4bef7d40fab051bb38902f71a8af0356ebe765f01b1808f6d2ce8bf8f luci-app-argon-config-2.4.7-r1.apk
00163d6b9d7f1fccae84bd220c6f3c9a4f78fe063b1d12408127d36bfe38dd7e luci-i18n-argon-config-zh-cn-26.103.13761.3e099a3.apk"
mkdir -p "$WORK/extra"
rm -f "$WORK/extra/"*.apk.part
printf "%s\n" "$ARGON_APKS" | while read -r sum f; do
    [ -f "$WORK/extra/$f" ] || { curl -fsSL -o "$WORK/extra/$f.part" "$ARGON_URL/$f" && mv "$WORK/extra/$f.part" "$WORK/extra/$f"; }
    got=$(shasum -a 256 "$WORK/extra/$f" 2>/dev/null || sha256sum "$WORK/extra/$f")
    [ "${got%% *}" = "$sum" ] || { echo "checksum mismatch for $f" >&2; rm -f "$WORK/extra/$f"; exit 1; }
done
# (only the pinned ones go in)
EXTRA_LIST=$(printf "%s\n" "$ARGON_APKS" | awk '{print "/in/extra/" $2}' | tr '\n' ' ')

ls "$OUT"/bluez-daemon-*.apk >/dev/null 2>&1 || {
    echo "no BlueZ package in $OUT -- run openwrt/build-bluez.sh first" >&2; exit 1; }
ls "$OUT"/modemmanager-1*.apk >/dev/null 2>&1 || {
    echo "no ModemManager package in $OUT -- run openwrt/build-modemmanager.sh first" >&2; exit 1; }
[ -x "$BUSYBOX" ] || { echo "no static busybox at $BUSYBOX (E5_BUSYBOX=...)" >&2; exit 1; }

if [ ! -f "$WORK/$TARBALL" ]; then
    curl -fL -o "$WORK/$TARBALL.part" "$URL/$TARBALL"
    mv "$WORK/$TARBALL.part" "$WORK/$TARBALL"
fi
want=$(curl -fsSL "$URL/sha256sums" | sed -n "s/^\([0-9a-f]*\) \*$TARBALL$/\1/p")
have=$(shasum -a 256 "$WORK/$TARBALL" 2>/dev/null || sha256sum "$WORK/$TARBALL")
[ -n "$want" ] && [ "${have%% *}" = "$want" ] || { echo "checksum mismatch for $TARBALL" >&2; exit 1; }

# logdw, e5-vibrate, e5-ctl-raw and e5-modemd, static: OpenWrt has no compiler of its own
docker run --rm --platform linux/arm64 -v "$TOP/device/openwrt_device_common/src":/src:ro \
    -v "$TOP/device/openwrt_device_common/shared":/at-source:ro -v "$WORK":/out "${E5_TOOLS_BUILD_IMAGE:-alpine:3.22}" \
    sh -euc 'if ! command -v gcc >/dev/null; then apk add -q gcc musl-dev linux-headers >/dev/null; fi
        gcc -static -Os -s -o /out/logdw /src/logdw.c &&
        gcc -static -Os -s -Wall -o /out/e5-vibrate /src/e5-vibrate.c &&
        gcc -static -Os -s -Wall -o /out/e5-ctl-raw /src/e5-ctl-raw.c &&
        gcc -static -Os -s -Wall -o /out/e5-modemd /src/e5-modemd.c &&
        gcc -static -Os -s -Wall -Wextra -o /out/e5-sim-probe /src/e5-sim-probe.c &&
        gcc -std=c11 -static -Os -s -Wall -Wextra -Werror -o /out/t551m-at /at-source/at-client.c'
python3 "$TOP/device/openwrt_device_common/shared/build-at-client.py" --binary "$WORK/t551m-at"

# what a standalone image carries of the device's own (the Debian root's in the
# directory form); an empty directory each otherwise
SA="$WORK/standalone"
rm -rf "$SA" && mkdir -p "$SA/firmware" "$SA/android" "$SA/modem" "$SA/fonts" "$SA/audio"
# Another kernel's root modules, unpacked before the standalone staging pass.
RM="$WORK/root-modules"
rm -rf "$RM" && mkdir -p "$RM"
if [ -n "${E5_ROOT_MODULES:-}" ]; then
    tar -xf "$E5_ROOT_MODULES" -C "$RM"
    echo "root modules: $(ls "$RM/lib/modules" 2>/dev/null | tr '\n' ' ')($(find "$RM" -name '*.ko' | wc -l | tr -d ' ') modules)"
fi
if [ "$CONTAINERS" = 1 ]; then
    find "$RM/lib/modules" -name container-support.json -print -quit 2>/dev/null | grep -q . || {
        echo "E5_DOCKER=1 requires a verified mainline E5_ROOT_MODULES archive" >&2; exit 1; }
fi
# the vendor audio modules (e5-audio-dsp loads them), in every form: GPL, of
# this kernel build, nothing of a device's
if [ "${E5_ROOT_MODULES_ONLY:-0}" = 1 ]; then
    set -- "$RM"/lib/modules/*
    [ $# = 1 ] && [ -d "$1/audio" ] && [ -f "$1/modem/sipc_wwan.ko" ] || {
        echo "E5_ROOT_MODULES_ONLY needs exactly one release with audio and sipc_wwan modules" >&2; exit 1; }
    ROOT_REL=$(basename "$1")
    if [ "$FEATURES" = 1 ]; then
        case "$ROOT_REL" in
            *-e5-mobile[0-9]*) ;;
            *) echo 'E5_FEATURES requires the device/linux_device_e5 kernel, not donor board modules' >&2; exit 1 ;;
        esac
        [ -f "$1/aw32257_charger.ko" ] && [ -f "$1/audio/snd-soc-sprd-pa-aw87xxx.ko" ] || {
            echo 'E5 native charger/amplifier modules are missing' >&2; exit 1; }
    fi
    cp "$1/audio/"*.ko "$SA/audio/"
else
    find "$KBUILD/sound/soc/sprd" "$KBUILD/drivers/unisoc_platform/sprd_audio" -name '*.ko' -exec cp {} "$SA/audio/" \; 2>/dev/null
fi
n=$(ls "$SA/audio" | grep -c '\.ko$' || true)
[ "$n" = 24 ] || { echo "expected the 24 audio modules in $KBUILD, found $n (kernel/build-linux.sh)" >&2; exit 1; }
strings "$SA/audio/snd-soc-sprd-card.ko" | sed -n 's/^vermagic=\([^ ]*\).*/\1/p' | head -1 > "$SA/audio/release"
if [ -n "$STANDALONE" ]; then
    NAME=e5-openwrt-$VER-standalone-rootfs.tar.gz
    [ -f "$FIRMWARE/regulatory.db" ] || { echo "no $FIRMWARE/regulatory.db" >&2; exit 1; }
    if [ "$DEVICE_FILES" = 0 ]; then
        NAME=e5-openwrt-$VER-generic-rootfs.tar.gz
        # Debian's wireless-regdb, signed with the key this kernel trusts: no device's
        cp "$FIRMWARE/regulatory.db" "$FIRMWARE/regulatory.db.p7s" "$SA/firmware/"
    else
        for f in wcnmodem.bin sprd/marlin3lite_pskey.bin; do
            [ -f "$FIRMWARE/$f" ] || { echo "no $FIRMWARE/$f -- pull the firmware first (rootfs/pull-wcn-firmware.sh)" >&2; exit 1; }
        done
        [ -x "$ANDROID/vendor/bin/modem_control" ] ||
            { echo "no vendor subset at $ANDROID -- rootfs/extract-android-vendor.sh" >&2; exit 1; }
        cp -a "$FIRMWARE/." "$SA/firmware/"
        cp -a "$ANDROID/." "$SA/android/"
    fi
    if [ "${E5_ROOT_MODULES_ONLY:-0}" = 1 ]; then
        # The 6.18 config builds WWAN into the kernel; sipc_wwan is its module.
        cp "$RM/lib/modules/$ROOT_REL/modem/"*.ko "$SA/modem/"
        REL=$ROOT_REL
        [ "$(cat "$SA/audio/release")" = "$REL" ] || { echo "audio module release mismatch" >&2; exit 1; }
    else
        for f in drivers/net/wwan/wwan.ko drivers/unisoc_platform/modem/sipc/sipc_wwan.ko; do
            [ -f "$KBUILD/$f" ] || { echo "no $KBUILD/$f -- build the kernel first (kernel/build-linux.sh)" >&2; exit 1; }
            cp "$KBUILD/$f" "$SA/modem/"
        done
        REL=$(strings "$SA/modem/wwan.ko" | sed -n 's/^vermagic=\([^ ]*\).*/\1/p' | head -1)
        [ -n "$REL" ] || { echo "no vermagic in wwan.ko" >&2; exit 1; }
    fi
    echo "$REL" > "$SA/modem/release"
    echo "standalone: firmware $(du -sh "$SA/firmware" | cut -f1), vendor subset $(du -sh "$SA/android" | cut -f1), modules for $REL"
    # Noto Sans CJK from Debian's package, once
    if ! ls "$WORK/fonts/"NotoSansCJK-Regular.ttc >/dev/null 2>&1; then
        mkdir -p "$WORK/fonts"
        docker run --rm --platform linux/arm64 -v "$WORK/fonts":/out debian:trixie-slim sh -euc '
            cd /tmp && apt-get update -qq && apt-get download -qq fonts-noto-cjk &&
            dpkg-deb -x fonts-noto-cjk_*.deb x &&
            cp x/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc \
               x/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc /out/'
    fi
    cp "$WORK/fonts/"NotoSansCJK-*.ttc "$SA/fonts/"
fi

# (the standalone tree is only the image's source)
TAROUT=$OUT; [ -z "$STANDALONE" ] || TAROUT=$WORK
docker import --platform linux/arm64 "$WORK/$TARBALL" e5-openwrt-base:$VER >/dev/null
# Packages OpenWrt's repository dropped -- cog and WPE WebKit left 25.12.5's feed when it was regenerated on
# 2026-09-28 -- are taken from the last image that had them: their files, apk database entries and
# dependencies, out of that image's rootfs archive into $WORK/transplant once (kept there).  The build uses
# them only while the repository has none of them.
TP="$WORK/transplant"
if [ ! -f "$TP/installed" ] && [ -f "$WORK/e5-openwrt-$VER-generic-rootfs.tar.gz" ]; then
    python3 - "$WORK/e5-openwrt-$VER-generic-rootfs.tar.gz" "$TP" cog libcogcore libwpewebkit <<'PY'
import os, sys, tarfile
src, tp, names = sys.argv[1], sys.argv[2], set(sys.argv[3:])
t = tarfile.open(src)
members = {m.name.lstrip('./'): m for m in t.getmembers()}
db = t.extractfile(members['lib/apk/db/installed']).read().decode()
blocks = [b for b in db.split('\n\n') if b.strip()]
keep = [b for b in blocks if any(l == 'P:' + n for l in b.split('\n') for n in names)]
assert len(keep) == len(names), 'not all of %s in %s' % (sorted(names), src)
paths, provides, deps = [], set(names), set()
for b in keep:
    d = None
    for l in b.split('\n'):
        if l.startswith('F:'): d = l[2:]; paths.append(d)
        elif l.startswith('R:'): paths.append(d + '/' + l[2:])
        elif l.startswith('p:'): provides.update(x.split('=')[0] for x in l[2:].split())
        elif l.startswith('D:'): deps.update(x for x in l[2:].split())
os.makedirs(tp + '/root', exist_ok=True)
for p in paths:
    m = members.get(p)
    if m is not None and not m.isdir():
        t.extract(m, tp + '/root')
    elif m is not None:
        os.makedirs(tp + '/root/' + p, exist_ok=True)
open(tp + '/installed', 'w').write('\n\n'.join(keep) + '\n\n')
dep = sorted(x for x in deps if x.split('=')[0].split('<')[0].split('>')[0] not in provides and not x.startswith('!'))
open(tp + '/deps', 'w').write(' '.join(dep) + '\n')
open(tp + '/names', 'w').write('\n'.join(sorted(names)) + '\n')
print('transplant: %d packages, %d paths, deps: %s' % (len(keep), len(paths), ' '.join(dep)))
PY
fi
mkdir -p "$TP"

# (an empty directory stands for no info screen)
mkdir -p "$WORK/no-infoscreen"
echo "info screen: ${INFOSCREEN:-(none)}"
VERSION=$(git -C "$TOP" describe --always --dirty 2>/dev/null || echo dev)

docker run --rm --platform linux/arm64 \
    -v "$OVERLAY":/in/overlay:ro -v "$TOP/device/linux_device_common/overlay/opt/e5":/in/opt-e5:ro \
    -v "$TOP/device/openwrt_device_common/packages.list":/in/packages.list:ro \
    -v "$TOP":/in/feature-source:ro -e E5_FEATURES="$FEATURES" -e E5_UI_CACHE=/tmp/e5-ui-cache \
    -e E5_INFOSCREEN=/in/infoscreen -e E5_INFOSCREEN_PLUGINS=/in/infoscreen-plugins \
    -v "$OUT":/in/apk:ro -v "$BUSYBOX":/in/busybox:ro -v "$WORK/logdw":/in/logdw:ro \
    -v "$WORK/e5-vibrate":/in/e5-vibrate:ro -v "${INFOSCREEN:-$WORK/no-infoscreen}":/in/infoscreen:ro \
    -v "${SCREEN_PLUGINS:-$WORK/no-infoscreen}":/in/infoscreen-plugins:ro \
    -v "$WORK/e5-ctl-raw":/in/e5-ctl-raw:ro -v "$OVERLAY/usr/share/alsa":/in/alsa:ro \
    -v "$WORK/e5-modemd":/in/e5-modemd:ro \
    -v "$WORK/e5-sim-probe":/in/e5-sim-probe:ro \
    -v "$BLOCK_APK":/in/block-mount-guarded.apk:ro \
    -v "$BLOCK_APK.build-id":/in/block-mount.build-id:ro \
    -v "$WIFI_APKS":/in/wifi-sae:ro \
    -v "$SA":/in/sa:ro -e STANDALONE="$STANDALONE" -v "$RM":/in/root-modules:ro \
    -v "$WORK/extra":/in/extra:ro -e EXTRA_LIST="$EXTRA_LIST" -v "$TP":/in/transplant:ro \
    -v "$TAROUT":/out -e NAME="$NAME" -e VERSION="$VERSION" -e E5_BUILD_EPOCH="${E5_BUILD_EPOCH:-}" -e CONTAINERS="$CONTAINERS" \
    e5-openwrt-base:$VER /bin/sh -euc '
mkdir -p /var/lock /var/run /tmp
attempt=1
until apk update >/dev/null; do
    [ "$attempt" -lt 4 ] || exit 1
    echo "Retrying OpenWrt package indexes ($attempt/3)" >&2
    sleep $((attempt * 2))
    attempt=$((attempt + 1))
done
apk add --allow-untrusted /in/block-mount-guarded.apk >/dev/null
apk add e2fsprogs resize2fs f2fs-tools >/dev/null
# ModemManager first, from its local file (unsigned): its release is above the
# repository one, so what depends on it takes this one and apk upgrade keeps it
apk add --allow-untrusted /in/apk/modemmanager-1*.apk /in/apk/modemmanager-rpcd-*.apk >/dev/null
# BlueZ the same way, patched (openwrt/build-bluez.sh: the SDP MTU headphones need)
apk add --allow-untrusted /in/apk/bluez-libs-*.apk /in/apk/bluez-daemon-*.apk /in/apk/bluez-utils-5*.apk >/dev/null
# (dbus-utils: dbus-monitor, for e5-sms-notify)
# (alsa-utils: aplay and amixer for the speaker, e5-audio-dsp and e5-volume)
# (curl: the webhook of the SMS forward, /usr/libexec/e5-sms)
apk add --allow-untrusted /in/wifi-sae/*.apk >/dev/null
apk add $(sed -e "s/#.*//" -e "/^[[:space:]]*$/d" /in/packages.list) >/dev/null
# SMS email encoding and DingTalk signatures need the OpenSSL command itself.
command -v openssl >/dev/null
openssl version
[ "$(printf abc | openssl base64 -A)" = YWJj ]
[ "$(printf abc | openssl dgst -sha256 -hmac test -binary | openssl base64 -A)" = "15ZXmu0SPnt0PMr1sVCv+hIj4x7LqLiMnanM961eBZQ=" ]
# Bluetooth audio: PulseAudio built with BlueZ (the -avahi variant carries
# the bluetooth modules), run by /etc/init.d/e5-pulseaudio, not by its own
# init script (which forbids loading the modules a connecting device needs)
apk add pulseaudio-daemon-avahi pulseaudio-tools >/dev/null
# Reuse the tested Debian hostless FE_ST_VOICE backend for cellular audio.
apk add python3 >/dev/null
if [ "$CONTAINERS" = 1 ]; then
    # Do not run dockerd post-install scripts inside the build container.
    apk add --no-scripts docker dockerd iptables-nft ip6tables-nft resize2fs >/dev/null
fi
# attended sysupgrade flashes whole-disk images: that would overwrite the eMMC
# (removed before the translations below, whose package for it would hold it)
apk del luci-app-attendedsysupgrade attendedsysupgrade-common owut >/dev/null 2>&1 || true
if grep -q "^P:luci-app-attendedsysupgrade$" /lib/apk/db/installed; then
    echo "luci-app-attendedsysupgrade is still installed" >&2; exit 1
fi
# LuCI in Chinese: the base and each installed application'"'"'s translation
# (the language is chosen at first boot, 93-e5-luci)
apk add luci-i18n-base-zh-cn >/dev/null
for p in $(sed -En "s/^P:luci-(app|proto)-//p" /lib/apk/db/installed); do
    apk add "luci-i18n-$p-zh-cn" >/dev/null 2>&1 && echo "zh-cn: luci-i18n-$p-zh-cn"
done
# the Argon theme (its release'"'"'s packages, unsigned)
apk add --allow-untrusted $EXTRA_LIST >/dev/null
echo "argon: $(sed -n "/^P:luci-theme-argon$/{n;s/^V://p}" /lib/apk/db/installed)"
# the info screen'"'"'s packages (cage, cog, Mesa, ...), when there is one
if [ -f /in/infoscreen/packages.txt ]; then
    # (the transplant above: used when the repository has none of those packages)
    : > /tmp/tp
    if [ -f /in/transplant/names ]; then
        for p in $(cat /in/transplant/names); do apk search -e "$p" 2>/dev/null | grep -q . || echo "$p" >> /tmp/tp; done
    fi
    # (busybox grep: an empty -f list matches every line, so it filters only when there is one)
    grep -v "^#" /in/infoscreen/packages.txt > /tmp/pk
    if [ -s /tmp/tp ]; then grep -vxF -f /tmp/tp /tmp/pk > /tmp/pk2 || true; mv /tmp/pk2 /tmp/pk; fi
    [ -s /tmp/pk ] || { echo "no info screen packages to install" >&2; exit 1; }
    apk add $(cat /tmp/pk) >/dev/null
    echo "info screen packages: $(wc -l < /tmp/pk)"
    if [ -s /tmp/tp ]; then
        apk add $(cat /in/transplant/deps) >/dev/null
        cp -a /in/transplant/root/. /
        cat /in/transplant/installed >> /lib/apk/db/installed
        cat /in/transplant/names >> /etc/apk/world
        echo "transplanted from an earlier image: $(tr "\n" " " < /in/transplant/names)"
    fi
    # (the screen stands on these: an image without them is not one to ship)
    for p in cage cog libwpewebkit; do
        grep -qx "P:$p" /lib/apk/db/installed || { echo "the image has no $p: the info screen would not start" >&2; exit 1; }
    done
fi
# (apk info <name> describes the repository'"'"'s package; the installed one is here)
echo "modemmanager $(sed -n "/^P:modemmanager$/{n;s/^V://p}" /lib/apk/db/installed) installed"

R=/build/root; mkdir -p $R
# the live filesystem of this container (OpenWrt and the packages), without the runtime mounts
for e in /*; do
    case "$e" in /proc|/sys|/dev|/build|/in|/out|/tmp) continue ;; esac
    cp -a "$e" $R/
done
mkdir -p $R/proc $R/sys $R/dev $R/tmp $R/mnt/e5-disk $R/opt/e5/android $R/opt/e5/bin $R/etc/e5linux
mkdir -p $R/etc/e5
cp /in/block-mount.build-id $R/etc/e5/block-mount.build-id
cp /in/wifi-sae/build-id $R/etc/e5/wifi-sae.build-id
cp /in/wifi-sae/source-info $R/etc/e5/wifi-sae.source-info
for f in sbin/block lib/libblkid-tiny.so etc/init.d/fstab; do
    [ -s "$R/$f" ] || { echo "guarded block-mount payload missing: $f" >&2; exit 1; }
done
# Docker bind-mounts these into the container, so the copy has the build host versions
ln -sf /tmp/resolv.conf $R/etc/resolv.conf
printf "127.0.0.1\tlocalhost\n\n::1\tlocalhost ip6-localhost ip6-loopback\nff02::1\tip6-allnodes\nff02::2\tip6-allrouters\n" > $R/etc/hosts
printf "E5\n" > $R/etc/hostname

cp -a /in/overlay/. $R/
rm -f $R/.device-overlay.json
if [ "$CONTAINERS" = 1 ]; then
    python3 $R/usr/libexec/e5-container-setup --root $R
fi
screen=
if [ -d /in/infoscreen/root ]; then
    cp -a /in/infoscreen/root/. $R/
    find $R -name .DS_Store -exec rm -f {} +
    screen=e5-infoscreen
fi
# Phone is a separately maintained store application, preinstalled for this
# image. Core updates do not replace it; plugin updates use the app store.
if [ -n "$screen" ] && [ -f /in/infoscreen-plugins/plugins/phone/manifest.json ]; then
    mkdir -p $R/etc/e5-infoscreen/plugins
    cp -a /in/infoscreen-plugins/plugins/phone $R/etc/e5-infoscreen/plugins/
    chown -R 0:0 $R/etc/e5-infoscreen/plugins/phone
fi
for f in vendor-start.sh android-import-perms.sh e5-modem-coldboot android-run node-perms.sh regdb-load.sh gadget-guard.sh usb-watch.sh e5-next-boot e5-os e5-sd-registry e5-at e5-data-priority e5-audio-dsp e5-call-audio.py; do
    cp /in/opt-e5/$f $R/opt/e5/$f; chmod 755 $R/opt/e5/$f
done
cp /in/logdw $R/opt/e5/bin/logdw && chmod 755 $R/opt/e5/bin/logdw
cp /in/e5-vibrate $R/usr/bin/e5-vibrate && chmod 755 $R/usr/bin/e5-vibrate
cp /in/e5-ctl-raw $R/opt/e5/e5-ctl-raw && chmod 755 $R/opt/e5/e5-ctl-raw
cp /in/e5-modemd $R/usr/sbin/e5-modemd && chmod 755 $R/usr/sbin/e5-modemd
cp /in/e5-sim-probe $R/usr/libexec/e5-sim-probe && chmod 755 $R/usr/libexec/e5-sim-probe
# the card'"'"'s UCM profile: applied by e5-audio-dsp with amixer (OpenWrt has no alsaucm)
mkdir -p $R/usr/share/alsa && cp -a /in/alsa/ucm2 $R/usr/share/alsa/
cp /in/busybox $R/opt/e5/bin/busybox && chmod 755 $R/opt/e5/bin/busybox
# the applets the shared scripts use that OpenWrt'"'"'s busybox leaves out --
# the ones the full busybox really has
have=$(/in/busybox --list)
for a in mountpoint timeout setsid flock seq stat chroot od losetup telnetd cut tr basename dirname \
         find xargs head tail wc sort uniq awk readlink unzip; do
    chroot $R /bin/sh -c "command -v $a" >/dev/null 2>&1 && continue
    if printf "%s\n" "$have" | grep -qx "$a"; then
        ln -sf /opt/e5/bin/busybox $R/usr/bin/$a; echo "busybox applet: $a"
    else
        echo "WARNING: no $a in OpenWrt or the static busybox"
    fi
done
# device nodes as udev makes them on Debian: 0660 root:root unless a rule
# says otherwise.  procd creates the rest 0600, and the vendor daemons, which
# drop to uid system but keep group root, then cannot open theirs --
# modem_control failed on /dev/chsys and the CP never booted.
sed -i "s|\[ \"makedev\", \"/dev/%DEVNAME%\", \"0600\" \]|[ \"makedev\", \"/dev/%DEVNAME%\", \"0660\" ]|" $R/etc/hotplug.json
grep -q "\"/dev/%DEVNAME%\", \"0660\" \]" $R/etc/hotplug.json || { echo "hotplug.json: default node mode not found" >&2; exit 1; }
# LuCI: the modem'"'"'s revision one row per line (again at boot, /etc/init.d/e5-luci)
sh $R/usr/libexec/e5-luci-revision $R
sh $R/usr/libexec/e5-ttyd-bind $R
for c in e5-os e5-next-boot e5-at; do ln -sf /opt/e5/$c $R/usr/bin/$c; done
ln -sf /usr/libexec/e5-sms-notify $R/usr/bin/e5-sms-notify
# the USB serial console: in the image, not at first boot -- procd reads
# inittab before uci-defaults run, and the console is the way in when the
# network is not up
grep -q "^ttyGS0:" $R/etc/inittab || echo "ttyGS0::askfirst:/usr/libexec/login.sh" >> $R/etc/inittab
mv $R/sbin/sysupgrade $R/sbin/sysupgrade.openwrt
mv $R/usr/libexec/e5-sysupgrade $R/sbin/sysupgrade
# enable the services ("rc.common enable" wants ubus, which is not running here)
rm -f $R/etc/rc.d/*pulseaudio
# (the cage package'"'"'s own kiosk service: cog on http://localhost/, which is LuCI,
# shown at every boot before the info screen'"'"'s session takes the panel)
rm -f $R/etc/rc.d/*cage
for s in e5-hw e5-vendor e5-modemd e5-sipc-wwan e5-telnetd e5-boot-ok e5-sms-notify e5-charge e5-apn-auto e5-network-recovery e5-luci e5-audio e5-voice-audio e5-hfp e5-bt bluetoothd dbus modemmanager e5-usb-watch ttyd $screen; do
    n=$(sed -n "s/^START=//p" $R/etc/init.d/$s)
    ln -sf ../init.d/$s $R/etc/rc.d/S$n$s
done
ln -sf ../init.d/e5-modemd $R/etc/rc.d/K09e5-modemd
# no kernel of its own
rm -rf $R/lib/modules/* $R/boot
arel=$(cat /in/sa/audio/release)
mkdir -p $R/lib/modules/$arel/audio && cp /in/sa/audio/*.ko $R/lib/modules/$arel/audio/
cp -a /in/root-modules/. $R/ && chown -R 0:0 $R/lib/modules
if [ -n "$STANDALONE" ]; then
    # the device'"'"'s own files, where the directory form binds the Debian root'"'"'s
    cp -a /in/sa/firmware/. $R/lib/firmware/
    mkdir -p $R/opt/e5/android && cp -a /in/sa/android/. $R/opt/e5/android/
    # (bionic refuses a property area that is not root'"'"'s: docs/FINDINGS.md 13)
    chown -R 0:0 $R/opt/e5/android $R/lib/firmware
    rel=$(cat /in/sa/modem/release)
    mkdir -p $R/lib/modules/$rel/modem && cp /in/sa/modem/*.ko $R/lib/modules/$rel/modem/
    mkdir -p $R/usr/share/fonts/e5-noto && cp /in/sa/fonts/*.ttc $R/usr/share/fonts/e5-noto/
    rmdir $R/mnt/e5-disk
    mkdir -p $R/mnt/e5-data
    mkdir -p $R/etc/e5 && printf "standalone\n" > $R/etc/e5/image-form
fi
mkdir -p $R/etc/e5 && printf "%s\n" "$VERSION" > $R/etc/e5/image-version
# when the image was built (seconds since 1970, UTC): 高级 -> 系统 shows it
if [ -n "$E5_BUILD_EPOCH" ]; then printf "%s\n" "$E5_BUILD_EPOCH" > $R/etc/e5/build-time
else date -u +%s > $R/etc/e5/build-time; fi
if [ "$E5_FEATURES" = 1 ]; then
    python3 /in/feature-source/device/openwrt_device_e5/stage.py --root $R
elif [ -n "$screen" ]; then
    python3 /in/feature-source/device/openwrt_device_common/shared/ui.py --root $R --profile e5
fi
if [ -f $R/usr/libexec/unisoc-modem/disable-channel-analysis ]; then
    ucode $R/usr/libexec/unisoc-modem/disable-channel-analysis $R
fi
cd $R && tar -czf /out/$NAME .
ls -la /out/$NAME
'

[ -n "$STANDALONE" ] || exit 0
# the tree as an ext4 image (mke2fs -d: no loop device, no root on the host)
IMG=e5-openwrt-$VER.ext4
[ "$DEVICE_FILES" != 0 ] || IMG=e5-openwrt-$VER-generic.ext4
mkdir -p "$TOP/out/boot"
docker run --rm --platform linux/arm64 -v "$WORK":/w -v "$OUT":/out \
    -v "$HERE/prepare-ext4-tools.py":/prepare-ext4-tools.py:ro \
    -v "$TOP/boot/prepare-f2fs-tools.py":/prepare-f2fs-tools.py:ro -v "$TOP/out/boot":/boot-out \
    -e NAME="$NAME" -e IMG="$IMG" -e MB="$IMAGE_MB" alpine:3.22 sh -euc '
apk add -q e2fsprogs python3 binutils >/dev/null
rm -rf /tmp/r && mkdir /tmp/r && tar -xzf /w/$NAME -C /tmp/r
rm -f /w/$IMG
python3 /prepare-ext4-tools.py --root /tmp/r --out /out/ext4-tools.tar
python3 /prepare-f2fs-tools.py --root /tmp/r --out /boot-out/f2fs-tools
mke2fs -q -t ext4 -L e5-openwrt -m 1 -d /tmp/r /w/$IMG ${MB}M
e2fsck -fn /w/$IMG >/dev/null
gzip -1 -c /w/$IMG > /out/$IMG.gz.part && mv /out/$IMG.gz.part /out/$IMG.gz
rm -f /w/$IMG
echo "used: $(du -sh /tmp/r | cut -f1) of ${MB} MiB"
ls -la /out/$IMG.gz'
