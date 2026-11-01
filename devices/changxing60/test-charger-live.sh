#!/bin/sh
# Explicit one-boot test for the captured, unbound P720S20 charger case.
# Firmware modules, boot, GPT and NV are not replaced. No forced module unload.
set -eu
cd "$(dirname "$0")"
expected_old=8b07aba5ea446d2accbede8c18fc8869b6cc23d916b8c5769dfa6a9b44b4bff5
expected_btf=3b2dc34b0940d4c25c2d51b8a0bde816583aa991aacb570836c421b65b3ef5f5
fail() { echo "$*" >&2; exit 1; }
hash() { sha256sum "$1" | cut -d ' ' -f 1; }
[ "$(cat /etc/e5/device-profile)" = changxing60 ] || fail 'Wrong device profile'
release=$(uname -r)
[ "$release" = 6.18.54-changxing60-bringup4 ] || fail 'Kernel release differs; use a matching full update'
original=/lib/modules/$release/bq2560x-charger.ko
[ "$(hash "$original")" = "$expected_old" ] || fail 'Original module differs; do not replace this machine blindly'
[ -f /sys/kernel/btf/vmlinux ] || fail 'Running kernel BTF unavailable; cannot verify this test module'
[ "$(hash /sys/kernel/btf/vmlinux)" = "$expected_btf" ] || fail 'Running kernel BTF differs; this test module is for another build'
sha256sum -c SHA256SUMS || fail 'Test module checksum failed'
[ ! -L /sys/bus/i2c/devices/6-006b/driver ] || fail 'Charger already bound; retain the working state'
[ "$(cat /sys/module/bq2560x_charger/refcnt)" = 0 ] || fail 'Charger module has users; do not force unload'
log=/tmp/changxing60-charger-live-$(date +%s).log
echo "Before test" > "$log"
dmesg | tail -n 80 >> "$log"
rmmod bq2560x_charger || fail 'Could not unload the unbound module'
if ! insmod ./bq2560x-charger.ko; then
    insmod "$original" || true
    fail "Test module could not load; original module reload attempted. Log: $log"
fi
for n in 1 2 3 4 5 6 7 8 9 10; do
    [ ! -d /sys/class/power_supply/battery ] || break
    sleep 1
done
echo "After test" >> "$log"
dmesg | tail -n 140 >> "$log"
for d in /sys/class/power_supply/*; do
    [ -d "$d" ] || continue
    echo "--- $d" >> "$log"
    cat "$d/uevent" >> "$log" 2>&1 || true
done
cat "$log"
if [ -L /sys/bus/i2c/devices/6-006b/driver ] && [ -d /sys/class/power_supply/battery ]; then
    echo "Charger bound and battery node registered. Check actual charging and UI."
    echo "Temporary test only: restart restores the installed driver. Log: $log"
else
    fail "Charger/battery still unavailable; retain the state and send $log"
fi
