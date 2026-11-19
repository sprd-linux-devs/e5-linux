#!/system/bin/sh
set -eu
ROOTFS=${1:?rootfs.gz} BOOT=${2:?boot.img} MISC=${3:?misc.bin} EXPECT=${4:?rootfs sha} SIZE=${5:?rootfs bytes} RELEASE=${6:?kernel release}
T=/data/local/tmp/e5-debian-update; M=$T/m; mkdir -p "$M"
cleanup(){ umount "$M" 2>/dev/null || :; rm -rf "$T"; }
trap cleanup EXIT
target= target_gen=
for p in /dev/block/mmcblk1p*; do
 [ -b "$p" ] || continue
 umount "$M" 2>/dev/null || :
 mount -t ext4 -o ro,noload "$p" "$M" 2>/dev/null || continue
 [ "$(cat "$M/etc/e5/sd-system" 2>/dev/null || :)" = debian ] || { umount "$M"; continue; }
 g=$(cat "$M/etc/e5/sd-gen" 2>/dev/null || echo 0); case "$g" in ''|*[!0-9]*) g=0 ;; esac
 [ -n "$target" ] && [ "$g" -ge "$target_gen" ] || { target=$p; target_gen=$g; }
 umount "$M"
done
[ -n "$target" ] || { echo 'no Debian SD slot found' >&2; exit 1; }
[ "$(blockdev --getsize64 "$target")" -ge "$SIZE" ] || exit 1
echo "updating inactive Debian slot $target"
gzip -dc "$ROOTFS" | dd of="$target" bs=4M conv=fsync
[ "$(dd if="$target" bs=4M count=$((SIZE / 4194304)) 2>/dev/null | sha256sum | cut -d' ' -f1)" = "$EXPECT" ] || exit 1
mount -t ext4 "$target" "$M"
mkdir -p "$M/etc/e5"
g=$(cat "$M/etc/e5/sd-gen" 2>/dev/null || echo 0); case "$g" in ''|*[!0-9]*) g=0 ;; esac
g=$((g + 1)); echo debian > "$M/etc/e5/sd-system"; echo "$g" > "$M/etc/e5/sd-gen"; echo 1 > "$M/etc/e5/sd-trial"; sync; umount "$M"
[ "$(sha256sum "$BOOT" | cut -d' ' -f1)" = "$(cat "$BOOT.sha256")" ] || exit 1
dd if="$BOOT" of=/dev/block/by-name/boot_b bs=4M conv=fsync
dd if="$MISC" of=/dev/block/by-name/misc bs=1 seek=2048 conv=notrunc
for u in /sys/class/block/mmcblk1p*/uevent; do
 [ "$(sed -n 's/^PARTNAME=//p' "$u")" = e5boot ] || continue
 mount -t ext4 -o rw "/dev/$(basename "$(dirname "$u")")" "$M"
 echo "$RELEASE" > "$M/kernel-release"; echo debian > "$M/default"; rm -f "$M/next"; sync; umount "$M"; break
done
echo ANDROID-DEBIAN-UPDATE-READY
