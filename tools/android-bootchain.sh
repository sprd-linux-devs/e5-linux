#!/system/bin/sh
# Synchronize the running Android slot to the opposite Linux slot.
# Never infer physical A/B roles from the model or historical filenames.
# check is read-only; sync backs up BOTH copies before any partition write.
# Never source this script: its lock and rollback traps must own their process.
set -u
umask 077
BY=/dev/block/by-name
BACKUPS=/data/adb/e5-bootchain
LOCK=/data/local/tmp/e5-bootchain.lock
PARTS='uboot sml teecfg trustos vbmeta'
changed=
backup=
locked=0
fail() { echo "BOOTCHAIN-ERROR: $*" >&2; exit 1; }
sha() { sha256sum "$1" | cut -d ' ' -f1; }
size() { blockdev --getsize64 "$1"; }
allowed() { case " $PARTS " in *" $1 "*) return 0 ;; *) return 1 ;; esac; }

# Validate the live AOSP block, including CRC, without Python on Android.
check_misc() {
    bytes=$(dd if="$BY/misc" bs=1 skip=2048 count=32 2>/dev/null | od -An -tu1 -v) || return 1
    set -- $bytes
    [ "$#" = 32 ] || return 1
    crc=4294967295; i=0; stored=0
    for byte in "$@"; do
        if [ "$i" -lt 28 ]; then
            crc=$((crc ^ byte)); bit=0
            while [ "$bit" -lt 8 ]; do
                if [ $((crc & 1)) = 1 ]; then crc=$(((crc >> 1) ^ 3988292384)); else crc=$((crc >> 1)); fi
                bit=$((bit + 1))
            done
        else stored=$((stored | (byte << ((i - 28) * 8)))); fi
        case "$i" in
            4) [ "$byte" = 66 ] || return 1 ;; 5) [ "$byte" = 67 ] || return 1 ;;
            6) [ "$byte" = 65 ] || return 1 ;; 7) [ "$byte" = 66 ] || return 1 ;;
            8) [ "$byte" = 1 ] || return 1 ;; 9) [ $((byte & 7)) = 2 ] || return 1 ;;
            12) am=$byte ;; 13|15) [ $((byte & 1)) = 0 ] || return 1 ;; 14) bm=$byte ;;
        esac
        i=$((i + 1))
    done
    [ $(((crc ^ 4294967295) & 4294967295)) = "$stored" ] || return 1
    if [ "$src" = a ]; then current=$am; opposite=$bm; else current=$bm; opposite=$am; fi
    [ $((current & 128)) = 128 ] && [ $((current & 15)) -gt 1 ] || return 1
    [ $((opposite & 15)) -le $((current & 15)) ] || return 1
}

settle() { sync && blockdev --flushbufs "$1"; }
put() {
    allowed "$1" || return 1
    [ "$(getprop ro.boot.slot_suffix)" = "_$src" ] || return 1
    [ "$(readlink -f "$BY/${1}_$dst")" = "$(cat "$backup/${1}_$dst.path")" ] || return 1
    dd if="$2" of="$BY/${1}_$dst" bs=1048576 conv=fsync,notrunc || return 1
    settle "$BY/${1}_$dst"
}
rollback() {
    bad=
    for part in $changed; do
        expected=$(cat "$backup/${part}_$dst.sha256")
        if put "$part" "$backup/${part}_$dst.img" && [ "$(sha "$BY/${part}_$dst")" = "$expected" ]; then
            echo "boot chain: restored ${part}_$dst"
        else bad="$bad $part"; fi
    done
    [ -z "$bad" ] || { echo "BOOTCHAIN-FAILED: restore failed:$bad; DO NOT boot Linux; backups: $backup" >&2; return 1; }
    echo "boot chain: previous Linux chain restored and verified; backups: $backup"
}
cleanup() {
    rc=$?
    trap - EXIT HUP INT TERM
    if [ -n "$changed" ]; then rollback || rc=2; fi
    [ "$locked" = 0 ] || rmdir "$LOCK"
    exit "$rc"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
case ${1:-} in check|sync) mode=$1 ;; *) fail 'usage: android-bootchain.sh check|sync' ;; esac
[ "$#" = 1 ] || fail 'unexpected arguments'
[ "$(id -u)" = 0 ] || fail 'root required'
command -v getprop >/dev/null 2>&1 || fail 'run from Android only'
case "$(getprop ro.boot.slot_suffix)" in
    _a) src=a; dst=b ;;
    _b) src=b; dst=a ;;
    *) fail 'Android slot unavailable; nothing written' ;;
esac
# These two actual stock firmwares boot the verified Linux image while
# reporting green. Keep this exception scoped to the tested model/board.
case "$(getprop ro.product.model)" in
    T512N) ;;
    'ZTE 7552N')
        [ "$(getprop ro.product.device)" = P720S20 ] || fail 'unknown Changxing60 board'
        PARTS="$PARTS dtbo vendor_boot" ;;
    'ZTE 7546N') [ "$(getprop ro.product.device)" = P720S11 ] || fail 'unknown 41S board' ;;
    CP23NV3)
        [ "$(getprop ro.product.device)" = CP23NV3 ] || fail 'unknown Y60 board'
        [ "$(getprop ro.boot.verifiedbootstate)" = orange ] || fail 'unlocked bootloader required'
        # Its base FDT lives in vendor_boot; keep it and DTBO in the same
        # recipient cohort, including when Android is running from slot B.
        PARTS="$PARTS dtbo vendor_boot" ;;
    *) [ "$(getprop ro.boot.verifiedbootstate)" = orange ] || fail 'unlocked bootloader required' ;;
esac
for part in misc boot_a boot_b l_agdsp_$src; do [ -b "$BY/$part" ] || fail "missing block device: $part"; done
mkdir "$LOCK" 2>/dev/null || fail 'another boot-chain operation is active (or its lock needs inspection)'
locked=1
check_misc || fail 'invalid CRC/BCAB, unsuccessful Android slot, verity error or pending opposite-slot OTA'
before_misc=$bytes

# Check all aliases together, including non-chain partitions: a broken by-name
# link must not redirect a write into Android, boot, misc, NV or userdata.
paths=' '
diff=
for part in $PARTS; do
    for slot in a b; do
        dev=$BY/${part}_$slot
        [ -b "$dev" ] || fail "missing block device: ${part}_$slot"
        real=$(readlink -f "$dev") || fail "cannot resolve $dev"
        case "$paths" in *" $real "*) fail "duplicate chain device: $dev" ;; esac
        paths="$paths$real "
        for alias in "$BY/"*; do
            [ "$alias" = "$dev" ] || [ "$(readlink -f "$alias")" != "$real" ] || fail "aliased partition: $dev and $alias"
        done
        count=$(size "$dev") || fail "cannot size $dev"
        case "$count" in ''|*[!0-9]*|0) fail "invalid size: $dev" ;; esac
        hash=$(sha "$dev") || fail "cannot read $dev"
        [ "${#hash}" = 64 ] || fail "short hash: $dev"
        eval "size_${part}_${slot}=\$count; hash_${part}_${slot}=\$hash"
    done
    eval 'asize=$size_'"$part"'_a; bsize=$size_'"$part"'_b; ahash=$hash_'"$part"'_a; bhash=$hash_'"$part"'_b'
    [ "$asize" = "$bsize" ] || fail "slot size mismatch: $part"
    [ "$ahash" = "$bhash" ] || diff="$diff $part"
done
echo "BOOTCHAIN-PLAN $src $dst$diff"
[ "$mode" = sync ] || exit 0
[ -n "$diff" ] || { echo "BOOTCHAIN-OK $src $dst (identical; nothing written)"; exit 0; }

mkdir -p "$BACKUPS" || fail 'cannot create backup parent'
backup=$(mktemp -d "$BACKUPS/$(date +%Y%m%d-%H%M%S).XXXXXX") || fail 'cannot allocate unique backup directory'
for part in $diff; do
    for slot in "$dst" "$src"; do
        eval 'expected=$hash_'"$part"'_'"$slot"
        dd if="$BY/${part}_$slot" of="$backup/${part}_$slot.img" bs=1048576 conv=fsync || fail 'backup read/write failed'
        [ "$(sha "$backup/${part}_$slot.img")" = "$expected" ] || fail 'backup verification failed'
        printf '%s\n' "$expected" > "$backup/${part}_$slot.sha256" || fail 'backup metadata failed'
        readlink -f "$BY/${part}_$slot" > "$backup/${part}_$slot.path" || fail 'backup device metadata failed'
        printf '%s  %s\n' "$expected" "${part}_$slot.img" >> "$backup/SHA256SUMS" || fail 'backup manifest failed'
    done
done
sync || fail 'backup sync failed'
# Detect concurrent OTA activity after backup, before the first write.
check_misc && [ "$bytes" = "$before_misc" ] || fail 'boot control changed during preparation'
for part in $PARTS; do
    for slot in a b; do
        eval 'expected=$hash_'"$part"'_'"$slot"
        [ "$(sha "$BY/${part}_$slot")" = "$expected" ] || fail 'chain changed during preparation'
    done
done
echo "boot chain: verified backups in $backup"
for part in $diff; do
    changed="$changed $part"
    expected=$(cat "$backup/${part}_$src.sha256")
    put "$part" "$backup/${part}_$src.img" && [ "$(sha "$BY/${part}_$dst")" = "$expected" ] || fail "write/readback failed: ${part}_$dst"
    echo "boot chain: ${part}_$dst <- ${part}_$src, verified"
done
changed=
echo "BOOTCHAIN-OK $src $dst$diff"
