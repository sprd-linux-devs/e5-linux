
storage_update_id() {
    if [ "$(cat /sys/class/block/$1/device/type 2>/dev/null)" = SD ]; then
        cat /sys/class/block/$1/device/cid
    else
        e5_storage_identity "$1"
    fi
}
# Sourced by init: replace only the verified, unmounted internal or TF root.
part_update_pending() {
    [ ! -e /run/tf-update-conflict ] || return 1
    [ -s /run/part-update-pending ] || return 0
    local dev= node disk mp=/part-update-old ram=/run/part-update
    local KIND=part VERSION= CID= ROOT_BYTES= RAW_BYTES= RAW_SHA256= PROFILE= SOURCE_PROFILE= NV_POLICY=preserve kv actual want got producer writer rc1 rc2
    dev=$(cat /run/part-update-pending)
    node=${dev##*/}
    mkdir -p "$mp"
    mount -t ext4 -o ro,noload "$dev" "$mp" || return 0
    [ -f "$mp/.e5-update/request" ] || { umount "$mp"; return 0; }
    . /etc/part-progress.sh
    part_progress_start
    echo '1/5 checking offline update' > /run/part-status
    node=${dev##*/}; disk=$(e5_storage_root_disk "$node") || return 1
    for kv in $(cat "$mp/.e5-update/request"); do
        case "$kv" in
            KIND=*) KIND=${kv#*=} ;;
            VERSION=*) VERSION=${kv#*=} ;; CID=*) CID=${kv#*=} ;;
            ROOT_BYTES=*) ROOT_BYTES=${kv#*=} ;; RAW_BYTES=*) RAW_BYTES=${kv#*=} ;;
            RAW_SHA256=*) RAW_SHA256=${kv#*=} ;; PROFILE=*) PROFILE=${kv#*=} ;;
            SOURCE_PROFILE=*) SOURCE_PROFILE=${kv#*=} ;;
            NV_POLICY=original) NV_POLICY=original ;;
            *) umount "$mp"; part_fail 'unknown update request field'; return 1 ;;
        esac
    done
    case "$KIND" in
        part) grep -qx PARTNAME=e5root "/sys/class/block/$node/uevent" || { umount "$mp"; return 1; } ;;
        sd) [ "$(cat /sys/class/block/$disk/device/type)" = SD ] || { umount "$mp"; return 1; } ;;
        *) umount "$mp"; return 1 ;;
    esac
    case "$ROOT_BYTES:$RAW_BYTES" in *[!0-9:]*|:*|*:) umount "$mp"; part_fail 'invalid update size'; return 1 ;; esac
    case "$RAW_SHA256" in *[!0-9a-f]*|'') umount "$mp"; part_fail 'invalid image hash'; return 1 ;; esac
    SOURCE_PROFILE=${SOURCE_PROFILE:-$PROFILE}
    case "$SOURCE_PROFILE:$PROFILE" in *[!a-z0-9:-]*|:*|*:) umount "$mp"; part_fail 'invalid profile metadata'; return 1 ;; esac
    if [ "$VERSION" != 1 ] || [ "$CID" != "$(storage_update_id "$disk")" ] ||
       [ "$ROOT_BYTES" != "$(blockdev --getsize64 "$dev")" ] ||
       [ "$SOURCE_PROFILE" != "$(cat "$mp/etc/e5/device-profile")" ] ||
       [ ! -f "$mp/etc/e5/$KIND-root" ] || [ "$RAW_BYTES" -le 0 ] || [ "$RAW_BYTES" -gt "$ROOT_BYTES" ]; then
        umount "$mp"; part_fail 'update device/geometry verification'; return 1
    fi
    # Copy EVERY payload off the old root before unmounting/overwriting it.
    if [ "$NV_POLICY" = original ]; then
        actual=$(du -k "$mp/.e5-update/"* 2>/dev/null | awk '{s+=$1} END {print s}')
    else
        actual=$(du -k "$mp/.e5-update/"* "$mp/opt/e5/nv" "$mp/etc/e5-nv" 2>/dev/null | awk '{s+=$1} END {print s}')
    fi
    if [ "$(awk '/MemAvailable:/ {print $2}' /proc/meminfo)" -le "$((actual + 262144))" ]; then
        umount "$mp"; part_fail 'insufficient update RAM'; return 1
    fi
    mkdir -p "$ram"
    if [ "$NV_POLICY" = original ]; then
        . /etc/nv-preserve.sh
        [ "$(wc -l < "$mp/.e5-update/nv-original.sha256")" = 1 ] &&
            [ "$(awk '{print $2}' "$mp/.e5-update/nv-original.sha256")" = nv-original.tar ] &&
            (cd "$mp/.e5-update" && sha256sum -c nv-original.sha256) &&
            cp "$mp/.e5-update/nv-original.tar" "$ram/nv.tar" &&
            sha256sum "$ram/nv.tar" > "$ram/nv.tar.sha256" || {
            umount "$mp"; part_fail 'confirmed original NV archive invalid'; return 1;
        }
    elif [ -e "$mp/opt/e5/nv" ] || [ -L "$mp/opt/e5/nv" ]; then
        . /etc/nv-preserve.sh
        nv_archive_offline "$mp" "$ram/nv.tar" || {
            umount "$mp"; part_fail 'NV preservation failed; old root kept'; return 1;
        }
        # nv.tar is already in tmpfs and therefore already deducted from
        # MemAvailable. Budget only the files still to be copied, not NV twice.
        actual=$(du -k "$mp/.e5-update/"* | awk '{s+=$1} END {print s}')
        [ "$(awk '/MemAvailable:/ {print $2}' /proc/meminfo)" -gt "$((actual + 262144))" ] || {
            umount "$mp"; part_fail 'insufficient NV preservation RAM'; return 1;
        }
    fi
    cp "$mp/.e5-update/"* "$ram/" || { umount "$mp"; part_fail 'RAM payload copy'; return 1; }
    umount "$mp" || { part_fail 'old root still mounted'; return 1; }
    cd "$ram"
    # Never accept hash entries pointing outside the RAM payload directory.
    [ "$(wc -l < SHA256SUMS)" = 4 ] &&
        [ "$(awk '{print $2}' SHA256SUMS | sort | tr '\n' ' ')" = 'ext4-tools.tar firmware.tar openwrt.ext4.gz settings.tar ' ] &&
        sha256sum -c SHA256SUMS && gzip -t openwrt.ext4.gz &&
        tar -tf firmware.tar >/dev/null && tar -tf settings.tar >/dev/null && tar -tf ext4-tools.tar >/dev/null || {
        part_fail 'RAM payload checksums'; return 1;
    }
    actual=$(set -o pipefail; gzip -dc openwrt.ext4.gz | wc -c) || { part_fail 'image size'; return 1; }
    want=$(set -o pipefail; gzip -dc openwrt.ext4.gz | sha256sum | cut -d' ' -f1) || return 1
    [ "$actual" = "$RAW_BYTES" ] && [ "$want" = "$RAW_SHA256" ] || { part_fail 'image content'; return 1; }
    awk -v n="$(cat /sys/class/block/$node/dev)" '$3==n {found=1} END {exit !found}' /proc/self/mountinfo && {
        part_fail 'root partition still mounted'; return 1;
    }
    mkdir tools
    tar -xf ext4-tools.tar -C tools || { part_fail 'ext4 tools'; return 1; }
    echo '2/5 writing verified image (all payloads are in RAM)' > /run/part-status
    mkfifo image.pipe
    # The Y60 kernel need not enable TASK_IO_ACCOUNTING. Use the exact target
    # partition's sector counter in the shared heartbeat in that case.
    printf '%s %s\n' "$node" "$(awk '{print $7}' "/sys/class/block/$node/stat" 2>/dev/null)" > /run/part-disk
    gzip -dc openwrt.ext4.gz > image.pipe & producer=$!
    dd if=image.pipe of="$dev" bs=1048576 conv=fsync 2>/run/part-dd.err & writer=$!
    echo "$writer $RAW_BYTES" > /run/part-worker
    wait "$writer"; rc1=$?
    [ "$rc1" = 0 ] || kill "$producer" 2>/dev/null
    wait "$producer"; rc2=$?
    rm -f image.pipe /run/part-worker /run/part-disk
    [ "$rc1:$rc2" = 0:0 ] || { part_fail 'root write'; return 1; }
    echo '2/5 reading back and verifying written image (write and flush finished)' > /run/part-status
    got=$(set -o pipefail; head -c "$RAW_BYTES" "$dev" | sha256sum | cut -d' ' -f1) || return 1
    [ "$got" = "$want" ] || { part_fail 'root readback'; return 1; }
    echo '3/5 checking and expanding filesystem' > /run/part-status
    "$ram/tools/lib/ld-musl-aarch64.so.1" --library-path "$ram/tools/lib:$ram/tools/usr/lib" \
        "$ram/tools/usr/sbin/e2fsck" -pf "$dev" >/run/part-fsck.log 2>&1
    rc1=$?; case "$rc1" in 0|1) ;; *) part_fail 'new root fsck'; return 1 ;; esac
    part_grow_ext4 "$dev" "$((ROOT_BYTES / 512))" || { part_fail 'root capacity'; return 1; }
    echo '4/5 restoring settings and device firmware' > /run/part-status
    mkdir -p /part-update-new
    mount -t ext4 "$dev" /part-update-new || { part_fail 'new root mount'; return 1; }
    local new=/part-update-new name
    mkdir -p "$ram/new-version" "$ram/new-phone"
    for name in image-version image-form build-time build.json feature-port.json device-profile; do
        [ ! -f "$new/etc/e5/$name" ] || cp "$new/etc/e5/$name" "$ram/new-version/"
    done
    cp -a "$new/etc/e5-infoscreen/plugins/phone/." "$ram/new-phone/" || return 1
    tar -xf firmware.tar -C "$new" && tar -xf settings.tar -C "$new" || { part_fail 'restore archives'; return 1; }
    if [ -f "$ram/nv.tar" ]; then
        nv_restore_offline "$new" "$ram/nv.tar" || { part_fail 'NV restore/readback failed'; return 1; }
    fi
    cp -a "$ram/new-phone/." "$new/etc/e5-infoscreen/plugins/phone/"
    cp "$ram/new-version/"* "$new/etc/e5/"
    if [ "$KIND" = part ]; then
        rm -f "$new/etc/e5/sd-root" "$new/etc/e5/sd-trial"
        printf 'e5root /dev/%s\n' "$disk" > "$new/etc/e5/part-root"
        touch "$new/etc/e5/part-autoboot"
        echo 1 > "$new/etc/e5/part-trial"
    else
        # Restored sd-gen/sd-system keep existing multi-root cards selectable.
        # Updating never allocates another root or modifies the registry/GPT.
        rm -f "$new/etc/e5/part-root" "$new/etc/e5/part-autoboot" "$new/etc/e5/part-trial" "$new/etc/e5/sd-trial"
        [ -f "$new/etc/e5/sd-root" ] || { part_fail 'TF boot marker'; return 1; }
    fi
    [ -x "$new/sbin/init" ] && [ -s "$new/lib/firmware/wcnmodem.bin" ] &&
        [ "$PROFILE" = "$(cat "$new/etc/e5/device-profile")" ] || { part_fail 'restored system verification'; return 1; }
    (cd "$new" && find etc lib/firmware opt/e5 -type f -exec sha256sum '{}' ';') > "$ram/restored.sha256" || {
        part_fail 'restored file manifest'; return 1;
    }
    sync
    umount "$new" || { part_fail 'new root unmount'; return 1; }
    blockdev --flushbufs "$dev" || { part_fail 'root flush'; return 1; }
    mount -t ext4 -o ro,noload "$dev" "$new" || { part_fail 'read-only root check'; return 1; }
    (cd "$new" && sha256sum -c "$ram/restored.sha256" >/run/part-restore-check.log 2>&1) || {
        part_fail 'restored file readback'; return 1;
    }
    umount "$new" || { part_fail 'read-only root unmount'; return 1; }
    echo '5/5 update complete; restarting' > /run/part-status
    write_misc_bc /etc/misc-bc-slot-b-trial.bin part-update-rearm
    cmp -s /run/bc.bin /etc/misc-bc-slot-b-trial.bin || { part_fail 'boot control'; return 1; }
    part_stop
    log 'stage=part-update done'
    reboot -f
}
