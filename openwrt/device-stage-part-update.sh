#!/bin/sh
storage_update_id() {
    if [ "$(cat /sys/class/block/$1/device/type 2>/dev/null)" = SD ]; then
        cat /sys/class/block/$1/device/cid
    else
        e5_storage_identity "$1"
    fi
}
# Prepare only: the mounted root is never overwritten from the running system.
set -eu
. "${1:?upload directory}/storage.sh"
stage=${1:?upload directory}
case "${E5_NV_POLICY:-preserve}" in preserve|original) ;; *) exit 2 ;; esac
case "$stage" in /.e5-upload-*) token=${stage#/.e5-upload-} ;; *) exit 1 ;; esac
case "$token" in ''|*[!0-9a-f]*) exit 1 ;; esac
[ "${#token}" = 32 ] && [ ! -L "$stage" ]
if [ ! -f /etc/e5/part-root ] && [ ! -f /etc/e5/sd-root ]; then
    E5_IMAGE_SIZE=${E5_IMAGE_SIZE:?} E5_NV_ARCHIVE="$stage/nv.tar" sh "$stage/device-install-image.sh" "$stage/openwrt.ext4.gz"
    exit
fi
exec 9>/run/e5-part-update.lock
flock -n 9 || { echo 'another partition update is running' >&2; exit 1; }
[ ! -e /.e5-update/request ] || { echo 'an update is already pending' >&2; exit 1; }
[ ! -L /.e5-update ] || { echo 'unsafe update staging directory' >&2; exit 1; }
kind=part
[ ! -f /etc/e5/sd-root ] || kind=sd
dev=$(cat "/run/e5linux/$kind-root-dev")
node=${dev##*/}; disk=$(e5_storage_root_disk "$node")
[ -b "$dev" ]
if [ "$kind" = part ]; then
    grep -qx PARTNAME=e5root "/sys/class/block/$node/uevent"
else
    [ "$(cat /sys/class/block/$disk/device/type)" = SD ]
fi
[ "$(awk '$2=="/" {print $1}' /proc/mounts | tail -1)" = "$dev" ]
source_profile=${E5_UPDATE_SOURCE_PROFILE:-${E5_UPDATE_PROFILE:?}}
case "$source_profile:${E5_UPDATE_PROFILE:?}" in *[!a-z0-9:-]*|:*|*:) exit 1 ;; esac
[ "$(cat /etc/e5/device-profile)" = "$source_profile" ]
bytes=$(( $(cat "/sys/class/block/$node/size") * 512 ))
[ "${E5_IMAGE_SIZE:?}" -le "$bytes" ]
case "${E5_IMAGE_SHA256:?}" in *[!0-9a-f]*|'') exit 1 ;; esac
[ "${#E5_IMAGE_SHA256}" = 64 ]
gzip -t "$stage/openwrt.ext4.gz"
# Persistent staging lives on the selected root; Android userdata is untouched.
mkdir -p /.e5-update
chmod 700 /.e5-update
cp "$stage/openwrt.ext4.gz" "$stage/ext4-tools.tar" /.e5-update/
if [ "${E5_NV_POLICY:-preserve}" = original ]; then
    [ -s "$stage/nv.tar" ]
    cp "$stage/nv.tar" /.e5-update/nv-original.tar
    (cd /.e5-update && sha256sum nv-original.tar > nv-original.sha256)
fi
view=$(mktemp -d /tmp/e5-update-view.XXXXXX)
trap 'umount "$view" 2>/dev/null || :; rmdir "$view" 2>/dev/null || :' EXIT
mount --bind / "$view"
# Plain bind excludes the vendor chroot's live proc/sys/dev bind mounts.
cd "$view"
firmware=
for name in lib/firmware/wcnmodem.bin lib/firmware/gnssmodem.bin lib/firmware/wifi_board_config*.ini \
    lib/firmware/tsx_data lib/firmware/l_agdsp_a.img lib/firmware/audio_structure lib/firmware/dsp_vbc \
    lib/firmware/codec.xml \
    lib/firmware/y60-audio_route.xml lib/firmware/y60-audio_pga.xml \
    lib/firmware/cvs lib/firmware/aw87xxx_acf.bin lib/firmware/sprd \
    lib/firmware/aw883xx_acf.bin lib/firmware/awinic_params.bin \
    lib/firmware/sitronix_firmware_huaying.dump lib/firmware/sitronix \
    lib/firmware/changxing60-audio_config.xml lib/firmware/changxing60-audio_route.xml \
                   lib/firmware/changxing60-audio_pga.xml lib/firmware/axs15205 \
                   lib/firmware/yuanhang41s-HiFi.conf lib/firmware/yuanhang41s-media-max \
    lib/firmware/android-firmware-slot opt/e5/android; do
    [ ! -e "$name" ] || firmware="$firmware $name"
done
[ -s lib/firmware/wcnmodem.bin ] && [ -x opt/e5/android/vendor/bin/modem_control ]
tar -cf /.e5-update/firmware.tar $firmware
settings=
for name in etc/config etc/shadow etc/passwd etc/group etc/dropbear etc/e5 etc/e5linux \
    etc/uhttpd.crt etc/uhttpd.key etc/vnstat etc/e5-infoscreen etc/e5-sms etc/unisoc-modem \
    etc/e5-sounds etc/e5-cpu-voltage.json etc/bluetooth; do
    [ ! -e "$name" ] || settings="$settings $name"
done
# Preserve policy's NV archive already includes this entire history. Original
# recovery builds a fresh NV archive, so retain the old history in settings.
if { [ "${E5_NV_POLICY:-preserve}" = original ] || [ ! -d opt/e5/nv ]; } && [ -e etc/e5-nv ]; then
    settings="$settings etc/e5-nv"
fi
tar -cf /.e5-update/settings.tar $settings
cd /
umount "$view"; rmdir "$view"; trap - EXIT
cd /.e5-update
tar -tf settings.tar >/dev/null; tar -tf firmware.tar >/dev/null; tar -tf ext4-tools.tar >/dev/null
sha256sum openwrt.ext4.gz firmware.tar settings.tar ext4-tools.tar > SHA256SUMS
sha256sum -c SHA256SUMS
payload=$(du -k openwrt.ext4.gz firmware.tar settings.tar ext4-tools.tar | awk '{s+=$1} END {print s}')
nv_kib=0
if [ -f "$stage/nv.tar" ]; then nv_kib=$(du -k "$stage/nv.tar" | awk '{print $1}'); fi
# The desktop snapshot and running browser/services disappear on reboot. Do
# not compare their current MemAvailable with the *offline* payload budget.
# Early initramfs still checks its actual MemAvailable before any root write.
total_kib=$(awk '/MemTotal:/ {print $2}' /proc/meminfo)
required_kib=$((payload + nv_kib + 262144))
[ "$total_kib" -gt "$required_kib" ] || {
    echo "not enough physical memory for offline update: need ${required_kib} KiB, total ${total_kib} KiB; request not armed" >&2; exit 1;
}
cid=$(storage_update_id "$disk")
{
    echo VERSION=1; echo KIND="$kind"; echo CID="$cid"; echo ROOT_BYTES="$bytes"
    echo RAW_BYTES="$E5_IMAGE_SIZE"; echo RAW_SHA256="$E5_IMAGE_SHA256"
    echo PROFILE="$E5_UPDATE_PROFILE"
    if [ "$source_profile" != "$E5_UPDATE_PROFILE" ]; then echo SOURCE_PROFILE="$source_profile"; fi
    if [ "${E5_NV_POLICY:-preserve}" = original ]; then echo NV_POLICY=original; fi
} > request.ready
sync
echo '== staged offline root update (no partition changes); settings and firmware saved'
