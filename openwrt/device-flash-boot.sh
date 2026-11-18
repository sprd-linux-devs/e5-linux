#!/bin/sh
# Write an e5-linux boot image into the identified Linux slot (Debian or
# OpenWrt, either form) and arm that slot for the next boot -- what
# boot/flash-from-linux.sh does over telnet, as one script the flash package
# (openwrt/make-flash-bundle.sh) runs on the device.
#
#   device-flash-boot.sh URL SHA256_OF_HEAD_AND_FOOTER HEAD_MB
#
# Transport HEAD_MB MiB followed by the matching 64-byte AVB footer. Write
# the prefix and footer separately, retaining the intervening persistent log.
# A write that does not verify arms nothing: LK keeps booting what it booted,
# and a half-written boot_b only costs its two tries before Android.
set -eu
URL=${1:?url} WANT=${2:?sha256} MB=${3:?MiB}
HERE=$(CDPATH= cd "$(dirname "$0")" && pwd)
[ -r "$HERE/storage.sh" ] || { echo 'Shared storage helper missing; nothing written' >&2; exit 1; }
. "$HERE/storage.sh"

part() {
    node=$(e5_storage_part "$1" "${2:-}") || return 1
    printf '/dev/%s\n' "$node"
}
BC_B=/run/e5linux/misc-bc-slot-b-trial.bin
[ "$(wc -c < "$BC_B" 2>/dev/null)" = 32 ] || {
    echo 'Incomplete Linux boot control; nothing written' >&2; exit 1;
}
case "$(dd if="$BC_B" bs=1 count=2 2>/dev/null)" in
    _a) linux_slot=a ;; _b) linux_slot=b ;;
    *) echo 'Linux slot unavailable; nothing written' >&2; exit 1 ;;
esac
BC_A=/run/e5linux/misc-bc-slot-a.bin
case "$linux_slot:$(dd if="$BC_A" bs=1 count=2 2>/dev/null)" in
    a:_b|b:_a) ;;
    *) echo 'Android/Linux boot roles conflict; nothing written' >&2; exit 1 ;;
esac
declared=$(cat /etc/e5/linux-slot 2>/dev/null || true)
[ -z "$declared" ] || [ "$declared" = "$linux_slot" ] || {
    echo 'Linux slot metadata conflicts; nothing written' >&2; exit 1;
}
MISC=$(cat /run/e5linux/misc-dev 2>/dev/null || part misc) || {
    echo 'Internal misc partition unavailable or ambiguous; nothing written' >&2; exit 1;
}
MISC=$(readlink -f "$MISC")
disk=$(e5_storage_parent "$MISC") && e5_storage_kind "$disk" >/dev/null || {
    echo 'misc is not on a supported internal eMMC/UFS disk; nothing written' >&2; exit 1;
}
BOOTB=$(part "boot_$linux_slot" "$disk") || {
    echo "boot_$linux_slot unavailable or ambiguous on $disk; nothing written" >&2; exit 1;
}
[ -b "$BOOTB" ] && [ -b "$MISC" ] || { echo "Linux boot or misc not found" >&2; exit 1; }
case "$MB" in ''|*[!0-9]*) echo 'Invalid boot prefix size; nothing written' >&2; exit 1 ;; esac
[ "$MB" -ge 1 ] && [ "$MB" -le 56 ] || { echo 'Invalid boot prefix size; nothing written' >&2; exit 1; }
SECTORS=$(cat "${E5_STORAGE_SYS:-/sys/class/block}/${BOOTB##*/}/size")
case "$SECTORS" in ''|*[!0-9]*) echo 'Invalid boot partition size; nothing written' >&2; exit 1 ;; esac
FOOTER_AT=$((SECTORS * 512 - 64))
[ "$FOOTER_AT" -ge "$((MB * 1048576))" ] || { echo 'Boot prefix overlaps footer; nothing written' >&2; exit 1; }

echo "== writing boot_$linux_slot ($BOOTB)"
T=/tmp/e5-boot-head.img
case "$URL" in
    http://*|https://*) wget -q -O "$T" "$URL" ;;
    /*) cp "$URL" "$T" ;;
    *) echo 'boot source must be an absolute file or HTTP URL' >&2; exit 1 ;;
esac
[ "$(sha256sum "$T" | cut -d' ' -f1)" = "$WANT" ] || { rm -f "$T"; echo "download hash mismatch" >&2; exit 1; }
[ "$(wc -c < "$T")" = "$((MB * 1048576 + 64))" ] || {
    echo 'Boot update requires a matching prefix and AVB footer; nothing written' >&2; exit 1;
}
HEAD_WANT=$(dd if="$T" bs=1M count="$MB" 2>/dev/null | sha256sum | cut -d' ' -f1)
FOOTER_WANT=$(dd if="$T" bs=1M skip="$MB" count=1 2>/dev/null | sha256sum | cut -d' ' -f1)
[ "$(dd if="$T" bs=1M skip="$MB" count=1 2>/dev/null | head -c 4)" = AVBf ] || {
    echo 'Invalid AVB footer; nothing written' >&2; exit 1;
}
dd if="$T" of="$BOOTB" bs=1M count="$MB" conv=notrunc,fsync 2>/dev/null
dd if="$T" bs=1M skip="$MB" count=1 2>/dev/null |
    dd of="$BOOTB" bs=1 seek="$FOOTER_AT" count=64 conv=notrunc,fsync 2>/dev/null
rm -f "$T"
sync
got=$(dd if="$BOOTB" bs=1M count="$MB" 2>/dev/null | sha256sum | cut -d' ' -f1)
[ "$got" = "$HEAD_WANT" ] || { echo "Linux boot verify failed; slot not armed" >&2; exit 1; }
got=$(dd if="$BOOTB" bs=1 skip="$FOOTER_AT" count=64 2>/dev/null | sha256sum | cut -d' ' -f1)
[ "$got" = "$FOOTER_WANT" ] || { echo 'Linux boot footer verify failed; slot not armed' >&2; exit 1; }
echo "   verified"

# the block the running initramfs recorded: the new image's is the same, for
# the same stock header (boot/build-boot-image.py)
[ -f "$BC_B" ] || { echo "no $BC_B" >&2; exit 1; }
dd if="$BC_B" of="$MISC" bs=1 seek=2048 conv=notrunc 2>/dev/null
sync
echo "== slot $linux_slot armed"
