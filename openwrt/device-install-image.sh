#!/bin/sh
# Install (or update) OpenWrt's own root image, e5linux/openwrt.ext4 on
# userdata, which boot/init starts when it is chosen (e5-os openwrt) or is the
# only system there.  Runs on the device as root, in whatever Linux it runs:
# Debian, OpenWrt in the Debian image's /openwrt, or the standalone OpenWrt
# itself; openwrt/install-standalone.sh sends it.
#
#   device-install-image.sh IMAGE.ext4.gz|URL [--try|--switch]
#
# SD roots must use the PC installer's offline update protocol. This legacy
# image installer refuses TF updates: no alternate root is allocated anymore.
#
# The image is unpacked next to the installed one (openwrt.ext4.part) and
# renamed at the end.  The running standalone OpenWrt cannot be replaced under
# itself: its update goes to openwrt.ext4.new, which the initramfs swaps in at
# the next boot (the old one stays as openwrt.ext4.old until the next update).
#
# The new image keeps the configuration of an installed OpenWrt -- the running
# one, else the installed image, else the Debian image's /openwrt -- as
# openwrt/device-install.sh does (/etc/config, passwords, SSH keys, /etc/e5,
# the traffic records); packages added with apk are not carried over.  With no
# OpenWrt before it, it takes Debian's APN and hotspot for the first boot.
# Linux as the default boot and the misc blocks come along either way.
#
# --try boots OpenWrt once, --switch makes it the default; both reboot.
set -eu
SRC=${1:?image}
MODE=${2:-}
case "$MODE" in ''|--try|--switch) ;; *) echo "unknown option $MODE" >&2; exit 2 ;; esac

# Shared by both standalone installers. Never unlink a flock file: a waiter
# could then lock a different inode. FD 9 is held through cleanup and commit.
# BEGIN e5-upgrade-lock
lockdir=/run/e5-upgrade
[ "$(id -u)" = 0 ] || { echo 'upgrade requires root' >&2; exit 1; }
command -v flock >/dev/null 2>&1 || { echo 'flock is required for a safe upgrade' >&2; exit 1; }
(umask 077; mkdir "$lockdir") 2>/dev/null || true
[ ! -L "$lockdir" ] && [ -d "$lockdir" ] &&
    [ "$(stat -c '%u:%a' "$lockdir")" = 0:700 ] || {
    echo 'unsafe upgrade lock directory' >&2; exit 1;
}
lockfile=$lockdir/lock
[ ! -L "$lockfile" ] && { [ ! -e "$lockfile" ] || {
    [ -f "$lockfile" ] && [ "$(stat -c '%u:%h' "$lockfile")" = 0:1 ];
}; } || { echo 'unsafe upgrade lock file' >&2; exit 1; }
update_umask=$(umask)
umask 077
if [ "${E5_UPGRADE_LOCK_HELD:-}" = 1 ]; then
    [ "$(readlink /proc/$$/fd/8)" = "$lockfile" ] && flock -n 8 || {
        echo 'invalid inherited upgrade lock' >&2; exit 1;
    }
else
    exec 9>>"$lockfile"
    flock -n 9 || { echo 'another system upgrade is running' >&2; exit 1; }
fi
umask "$update_umask"
# END e5-upgrade-lock

# The configuration of the OpenWrt at $1 into the new root $2 (/etc/config,
# passwords, SSH keys, /etc/e5, the traffic records, the info screen's apps),
# the new image's own version files kept.
keep_config() {
    local from=$1 N=$2 f p phone
    echo "== keeping the configuration of $from"
    # Keep installed apps and their data, but retain this image's bundled phone
    # code. Otherwise an update silently restores the previous voice fixes/UI.
    phone=$(mktemp -d /tmp/e5-img.phone.XXXXXX)
    if [ -f "$N/etc/e5-infoscreen/plugins/phone/manifest.json" ]; then
        cp -a "$N/etc/e5-infoscreen/plugins/phone/." "$phone/"
    fi
    for f in image-version image-form build-time release.json; do
        cp "$N/etc/e5/$f" "/tmp/e5-img.$f" 2>/dev/null || rm -f "/tmp/e5-img.$f"
    done
    for p in etc/config etc/shadow etc/passwd etc/group etc/dropbear etc/e5 etc/e5linux \
             etc/uhttpd.crt etc/uhttpd.key etc/vnstat etc/e5-infoscreen etc/e5-sms \
             etc/unisoc-modem etc/e5-sounds etc/e5-cpu-voltage.json etc/bluetooth; do
        [ -e "$from/$p" ] || continue
        if [ -d "$from/$p" ] && [ -d "$N/$p" ]; then
            cp -a "$from/$p/." "$N/$p/"
        else
            rm -rf "$N/$p"
            cp -a "$from/$p" "$N/$p"
        fi
    done
    for f in image-version image-form build-time release.json; do
        rm -f "$N/etc/e5/$f"
        [ -f "/tmp/e5-img.$f" ] && mv "/tmp/e5-img.$f" "$N/etc/e5/$f"
    done
    if [ -f "$phone/manifest.json" ]; then
        mkdir -p "$N/etc/e5-infoscreen/plugins/phone"
        cp -a "$phone/." "$N/etc/e5-infoscreen/plugins/phone/"
    fi
    rm -rf "$phone"
    rm -f "$N/etc/e5/nv-update-original"
    if [ -e "$from/opt/e5/nv" ] || [ -L "$from/opt/e5/nv" ] || [ "${E5_NV_POLICY:-preserve}" = original ]; then
        local nvarchive nv_policy=${E5_NV_POLICY:-preserve}
        nvarchive=$(mktemp /opt/e5-img.nv.XXXXXX)
        # Executed by the current host's interpreter. The newly installed
        # shared implementation pauses live writers or reads an offline tree.
        if [ "${E5_NV_POLICY:-preserve}" = original ]; then
            [ -s "${E5_NV_ARCHIVE:-}" ] && cp "$E5_NV_ARCHIVE" "$nvarchive" || return 1
        else
            python3 "$N/usr/lib/e5/nv_persistence.py" archive --root "$from" > "$nvarchive" || {
                python3 "$N/usr/lib/e5/nv_persistence.py" factory-confirmed > "$nvarchive" || {
                    echo 'NV recovery not confirmed/available; old image retained' >&2; return 1;
                }
                nv_policy=original
            }
        fi
        tar -xf "$nvarchive" -C "$N" &&
        chmod 700 "$N/opt/e5/nv" &&
        python3 "$N/usr/lib/e5/nv_persistence.py" verify --root "$N" &&
        python3 "$N/usr/lib/e5/nv_persistence.py" update-backup --root "$N" || {
            echo "NV restore/readback failed; backup retained: $nvarchive" >&2; return 1;
        }
        if [ "$nv_policy" = original ] && [ -n "$running_image" ]; then
            printf 'NV-ORIGINAL-RECOVERY-V1 %s %s\n' "$(cat "$N/etc/e5/device-profile")" \
                "$(. /usr/lib/e5/storage.sh; disk=$(e5_storage_disk); e5_storage_identity "$disk")" > "$N/etc/e5/nv-update-original" || return 1
        fi
        rm -f "$nvarchive"
    fi
}

# The device's own files (firmware, the Android vendor subset) as a tar on
# stdout, read through a plain (non-recursive) bind of the root that has them --
# the Debian image for the directory form, / otherwise: the vendor chroot has
# /proc, /sys and /dev mounted inside it while the baseband runs, and a tar of
# the live tree walked into those.  Nothing (and false) when this system has none.
VIEW=/tmp/e5-img.view
device_files_tar() {
    local src=/ list rc=1
    [ -f /mnt/e5-disk/usr/lib/firmware/wcnmodem.bin ] && src=/mnt/e5-disk
    mkdir -p "$VIEW" && mount --bind "$src" "$VIEW"
    if [ -f "$VIEW/lib/firmware/wcnmodem.bin" ] && [ -x "$VIEW/opt/e5/android/vendor/bin/modem_control" ]; then
        list=$(cd "$VIEW" && for f in lib/firmware/wcnmodem.bin lib/firmware/gnssmodem.bin \
                   lib/firmware/wifi_board_config*.ini lib/firmware/tsx_data lib/firmware/l_agdsp_a.img \
                   lib/firmware/audio_structure lib/firmware/dsp_vbc lib/firmware/cvs \
                   lib/firmware/codec.xml \
                   lib/firmware/y60-audio_route.xml lib/firmware/y60-audio_pga.xml \
                   lib/firmware/aw87xxx_acf.bin lib/firmware/sprd \
                   lib/firmware/aw883xx_acf.bin lib/firmware/awinic_params.bin \
                   lib/firmware/sitronix_firmware_huaying.dump lib/firmware/sitronix \
                   lib/firmware/changxing60-audio_config.xml lib/firmware/changxing60-audio_route.xml \
                   lib/firmware/changxing60-audio_pga.xml lib/firmware/axs15205 \
                   lib/firmware/yuanhang41s-HiFi.conf lib/firmware/yuanhang41s-media-max \
                   lib/firmware/android-firmware-slot opt/e5/android; do
                   [ -e "$f" ] && echo "$f"; done)
        (cd "$VIEW" && tar -cf - $list) && rc=0
    fi
    umount "$VIEW"
    return $rc
}

# ------------------------------------------------------------ the SD card
card_update() {
    echo 'TF updates use OpenWrt-Installer.exe / update-openwrt from a new package; no alternate OTA partition is created.' >&2
    exit 1
}

# Work on the replacement file only. Replacing a grown image with the stock
# image otherwise silently restores its original (usually 2 GiB) capacity.
preserve_image_capacity() (
    set -eu
    image=$1 previous=$2 archive=$3
    [ -f "$previous" ] || exit 0
    [ ! -L "$previous" ] && [ -f "$image" ] && [ ! -L "$image" ] || {
        echo 'unsafe image path; existing system retained' >&2; exit 1;
    }
    target=$(stat -c %s "$previous") current=$(stat -c %s "$image")
    filesystem=${E5_IMAGE_FS_BYTES:-$target}
    case "$target:$current:$filesystem" in *[!0-9:]*|:*|*:) exit 1 ;; esac
    [ "$current" -gt 0 ] && [ "$target" -ge "$filesystem" ] && [ "$filesystem" -ge "$current" ] &&
        [ "$((target % 4096)):$((current % 4096)):$((filesystem % 4096))" = 0:0:0 ] || {
        echo 'new image does not fit existing capacity; existing system retained' >&2; exit 1;
    }
    [ "$target" != "$current" ] || exit 0
    work=
    trap '[ -z "$work" ] || rm -rf "$work"' EXIT
    if [ -f "$archive" ]; then
        work=$(mktemp -d /tmp/e5-image-tools.XXXXXX)
        tar -xf "$archive" -C "$work"
        (cd "$work" && sha256sum -c SHA256SUMS)
        ext4_tool() {
            name=$1; shift
            "$work/lib/ld-musl-aarch64.so.1" --library-path "$work/lib:$work/usr/lib" \
                "$work/usr/sbin/$name" "$@"
        }
    else
        command -v e2fsck >/dev/null && command -v resize2fs >/dev/null || {
            echo 'ext4 tools are required to preserve image capacity; existing system retained' >&2; exit 1;
        }
        ext4_tool() { name=$1; shift; command "$name" "$@"; }
    fi
    echo "== preserving image capacity: file=$target, filesystem=$filesystem bytes (offline)"
    ext4_tool e2fsck -pf "$image" || { rc=$?; [ "$rc" = 1 ] || exit "$rc"; }
    # Reserve the new file's space before publishing it; never resize the
    # mounted old image or the Android filesystem containing it.
    fallocate -l "$target" "$image" 2>/dev/null ||
        dd if=/dev/zero of="$image" bs=4096 seek=$((current / 4096)) \
            count=$(((target - current) / 4096)) conv=notrunc,fsync
    [ "$(stat -c %s "$image")" = "$target" ]
    ext4_tool resize2fs "$image" "$((filesystem / 1024))K"
    ext4_tool e2fsck -fn "$image"
)

D=/mnt/e5-data
DIR=$D/e5linux IMG=$D/e5linux/openwrt.ext4
PART=$IMG.part NEW_ROOT=/tmp/e5-img.new OLD_ROOT=/tmp/e5-img.old
[ -f /etc/e5/sd-root ] && [ -f /etc/openwrt_release ] && card_update

# userdata: the initramfs leaves it at /mnt/e5-data; one that predates that
# keeps it to itself, and the partition is mounted a second time (the same
# f2fs, not a copy)
if ! grep -qs " $D " /proc/mounts; then
    dev=
    for u in /sys/class/block/mmcblk*p*/uevent; do
        grep -qx PARTNAME=userdata "$u" 2>/dev/null && dev=/dev/$(basename "$(dirname "$u")")
    done
    [ -n "$dev" ] || { echo "no userdata partition" >&2; exit 1; }
    mkdir -p "$D"
    mount -t f2fs -o noatime "$dev" "$D"
    echo "== mounted userdata ($dev) at $D"
fi
mkdir -p "$DIR"

# the running root: the image itself when OpenWrt runs from it
running_image=
if [ -f /etc/openwrt_release ] && [ "$(cat /etc/e5/image-form 2>/dev/null)" = standalone ]; then
    running_image=1
fi

cleanup() {
    umount "$NEW_ROOT" 2>/dev/null || true
    umount "$OLD_ROOT" 2>/dev/null || true
    rm -f "$PART"
}
trap cleanup EXIT

avail=$(df -Pk "$D" | awk 'NR == 2 { print $4 }')
required_kib=1572864
if [ -f "$IMG" ]; then
    previous_bytes=$(stat -c %s "$IMG")
    case "$previous_bytes" in ''|*[!0-9]*) exit 1 ;; esac
    required_kib=$(( (previous_bytes + 1023) / 1024 + 524288 ))
fi
[ "$avail" -gt "$required_kib" ] || {
    echo "insufficient userdata space for a replacement image preserving capacity ($required_kib KiB required)" >&2; exit 1;
}
rm -f "$DIR/openwrt.ext4.old"

echo "== unpacking into $PART"
rm -f "$PART" "$PART.fail"
case "$SRC" in
    http://*|https://*) { wget -q -O - "$SRC" || touch "$PART.fail"; } | gunzip -c > "$PART" ;;
    *) gunzip -c "$SRC" > "$PART" ;;
esac
[ ! -e "$PART.fail" ] || { rm -f "$PART.fail"; echo "download failed" >&2; exit 1; }
preserve_image_capacity "$PART" "$IMG" "$(dirname "$SRC")/ext4-tools.tar"

mkdir -p "$NEW_ROOT" "$OLD_ROOT"
mount -t ext4 -o loop "$PART" "$NEW_ROOT"
[ -x "$NEW_ROOT/sbin/init" ] && [ -f "$NEW_ROOT/etc/openwrt_release" ] ||
    { echo "not an OpenWrt image" >&2; exit 1; }

# the OpenWrt whose configuration the new image keeps
from=
if [ -f /etc/openwrt_release ]; then
    from=/
elif [ -f "$IMG" ] && mount -t ext4 -o loop,ro "$IMG" "$OLD_ROOT" 2>/dev/null; then
    from=$OLD_ROOT
elif [ -d /openwrt/etc/config ]; then
    from=/openwrt
fi

N=$NEW_ROOT
if [ -n "$from" ]; then keep_config "$from" "$N" || exit 1; fi
umount "$OLD_ROOT" 2>/dev/null || true

if [ ! -f "$N/etc/e5/install.conf" ] && command -v nmcli >/dev/null 2>&1; then
    echo "== settings from Debian"
    # nmcli -g escapes ":" and "\\" in what it prints
    get() { nmcli "$@" 2>/dev/null | sed 's/\\\(.\)/\1/g' || true; }
    apn=$(get -g gsm.apn connection show Mobile)
    ssid=$(get -g 802-11-wireless.ssid connection show Hotspot)
    key=$(get -s -g 802-11-wireless-security.psk connection show Hotspot)
    chan=$(get -g 802-11-wireless.channel connection show Hotspot)
    q() { printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"; }
    mkdir -p "$N/etc/e5"
    (
        umask 077
        echo "# from the Debian image's NetworkManager profiles at install (openwrt/device-install-image.sh)"
        echo "E5_APN=$(q "$apn")"
        echo "E5_WIFI_SSID=$(q "${ssid:-E5-Linux}")"
        echo "E5_WIFI_KEY=$(q "$key")"
        echo "E5_WIFI_CHANNEL=$(q "${chan:-149}")"
    ) > "$N/etc/e5/install.conf"
    chmod 600 "$N/etc/e5/install.conf"
    echo "   apn=${apn:-(none)} ssid=${ssid:-E5-Linux} channel=${chan:-149} key=$([ -n "$key" ] && echo set || echo none)"
fi

# An image built without the device's files (E5_DEVICE_FILES=0) takes them
# from userdata's device-files.tar, which boot/init unpacks as well; made here
# from this system's own when there is none yet (device_files_tar).
DFT=$DIR/device-files.tar
if [ ! -f "$N/lib/firmware/wcnmodem.bin" ] && [ ! -f "$DFT" ]; then
    if device_files_tar > "$DFT.part"; then
        echo "== the device's files from this system -> $DFT"
        mv "$DFT.part" "$DFT"
    else
        rm -f "$DFT.part"
    fi
fi
if [ ! -f "$N/lib/firmware/wcnmodem.bin" ]; then
    if [ -f "$DFT" ]; then
        tar -xf "$DFT" -C "$N"
        sha256sum "$DFT" | cut -d' ' -f1 > "$N/etc/e5/device-files.stamp"
        echo "== the device's files unpacked into the image"
    else
        # (no modem and no Wi-Fi without them: better the old system than that)
        echo "the image has no firmware or vendor subset, and there is no $DFT: not installed" >&2
        exit 1
    fi
fi

mkdir -p "$N/etc/e5linux"
[ -f /etc/e5linux/default-boot ] && [ ! -f "$N/etc/e5linux/default-boot" ] &&
    cp /etc/e5linux/default-boot "$N/etc/e5linux/default-boot"
cp /run/e5linux/misc-bc-slot-a.bin /run/e5linux/misc-bc-slot-b-trial.bin "$N/etc/e5linux/" 2>/dev/null || true
ver=$(cat "$N/etc/e5/image-version" 2>/dev/null || echo "?")
umount "$NEW_ROOT"

if [ -n "$running_image" ]; then
    mv "$PART" "$IMG.new"
    echo "installed: $IMG.new ($ver), swapped in at the next boot"
else
    mv "$PART" "$IMG"
    echo "installed: $IMG ($ver)"
fi
sync

grep -qs openwrt-image /run/e5linux/init-features || {
    echo "the boot image in use predates OpenWrt images of their own: flash a newer one" >&2
    echo "(boot/flash-from-linux.sh) before booting it" >&2
    exit 0
}
case "$MODE" in
    --try)    echo openwrt > "$DIR/boot-os-next"; sync; reboot ;;
    --switch) rm -f "$DIR/boot-os-next"; echo openwrt > "$DIR/boot-os"; sync; reboot ;;
    '')       [ -n "$running_image" ] && echo "reboot to start it" ||
                  echo "boot it with: e5-os openwrt --once (one boot) or e5-os openwrt, then reboot" ;;
esac
