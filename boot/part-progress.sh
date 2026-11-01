# Shared installation progress. No fabricated percentage for filesystem work.
part_seconds() { cut -d. -f1 /proc/uptime; }
part_progress_start() {
    part_start=$(part_seconds)
    touch /run/part-install.running
    echo 'Preparing installation' > /run/part-status
    (
        while [ -e /run/part-install.running ]; do
            msg="$(cat /run/part-status 2>/dev/null) | elapsed $(($(part_seconds) - part_start))s"
            if [ -s /run/part-worker ]; then
                read -r worker total < /run/part-worker
                written=$(awk '/^wchar:/ {print $2}' /proc/$worker/io 2>/dev/null)
                if [ -z "$written" ] && [ -s /run/part-disk ]; then
                    # Without per-process io accounting (no /proc/<pid>/io in
                    # this kernel) the disk's sectors-written counter, sampled
                    # against install-part.sh's baseline, is the same number.
                    read -r dname base < /run/part-disk
                    now=$(awk '{print $7}' "/sys/class/block/$dname/stat" 2>/dev/null)
                    case "$base:$now" in *[!0-9:]*|:*|*:) ;; *)
                        [ "$now" -lt "$base" ] || written=$(( (now - base) * 512 )) ;;
                    esac
                fi
                if [ "${total:-0}" -gt 0 ] && [ -n "$written" ]; then
                    [ "$written" -le "$total" ] || written=$total
                    msg="$msg | $((written / 1048576))/$((total / 1048576)) MiB ($((written * 100 / total))%)"
                fi
                worker_state=$(awk '/^State:/ {print $2}' "/proc/$worker/status" 2>/dev/null)
                worker_wait=$(cat "/proc/$worker/wchan" 2>/dev/null)
                msg="$msg | writer=$worker state=${worker_state:-?} wait=${worker_wait:-?}"
            fi
            if [ -s /run/part-check ]; then
                read -r check_pid check_log < /run/part-check
                check_state=$(awk "/^State:/ {print \$2}" "/proc/$check_pid/status" 2>/dev/null)
                check_wait=$(cat "/proc/$check_pid/wchan" 2>/dev/null)
                check_io=$(awk "/^read_bytes:/ {r=\$2} /^write_bytes:/ {w=\$2} END {if (NR) printf \"read=%.1fMiB write=%.1fMiB\", r/1048576, w/1048576}" "/proc/$check_pid/io" 2>/dev/null)
                check_tail=$(tail -c 1024 "$check_log" 2>/dev/null | tr "\r" "\n" |
                    awk "NF {line=\$0} END {print substr(line,1,140)}")
                msg="$msg | fsck pid=$check_pid state=${check_state:-?} wait=${check_wait:-?} $check_io"
                [ -z "$check_tail" ] || msg="$msg | $check_tail"
            fi
            printf '<3>E5-INSTALL: %s\n' "$msg" > /dev/kmsg
            # ttyGS0 may be the preferred console. Write the panel explicitly.
            [ ! -c /dev/tty0 ] || printf '\r\033[2K%s\n' "$msg" > /dev/tty0
            sleep 2
        done
    ) &
    part_beat=$!
}
part_stop() {
    rm -f /run/part-install.running /run/part-worker /run/part-disk /run/part-check /run/part-fsck.stdin
    [ -z "${part_beat:-}" ] || { kill "$part_beat" 2>/dev/null; wait "$part_beat" 2>/dev/null; }
    part_beat=
    return 0
}
part_fail() {
    echo "FAILED: $* (logs retained; do not retry blindly)" > /run/part-status
    log "stage=part-install FAILED: $*"
    touch /run/stay
    part_stop
    return 1
}
part_grow_ext4() {
    # Resize offline: online resize can be unavailable in the installation kernel.
    local dev=$1 sectors=$2 blocks low high shift actual
    blocks=$((sectors / 8))
    /usr/sbin/resize2fs -f "$dev" "$blocks" > /run/part-growfs.log 2>&1 || return 1
    low=$(od -An -tu4 -j 1028 -N 4 "$dev" | tr -d ' \n')
    high=$(od -An -tu4 -j 1360 -N 4 "$dev" | tr -d ' \n')
    shift=$(od -An -tu4 -j 1048 -N 4 "$dev" | tr -d ' \n')
    # Our root images use 4 KiB blocks. Do not report success on a 2 GiB FS.
    [ "$shift" = 2 ] && [ "$high" = 0 ] && [ "$low" = "$blocks" ]
}
