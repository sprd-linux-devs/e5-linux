#!/bin/sh
# Isolated container only. /tests/battery-events.uc replaces poweroff with a counter.
set -eu
mkdir -p /var/run/ubus /etc/e5 /run/mu300
printf 'e5\n' > /etc/e5/device-profile
printf 'u30air\n' > /run/mu300/device
ubusd &
bus_pid=$!
guard_pid=
trap 'test -z "$guard_pid" || kill "$guard_pid" 2>/dev/null || :; kill "$bus_pid" 2>/dev/null || :' EXIT
n=0
until ubus list >/dev/null 2>&1; do
    n=$((n + 1)); [ "$n" -lt 50 ]; sleep 1
done

ucode /tests/battery-events.uc &
guard_pid=$!
n=0
until [ -s /fixtures/reads ]; do
    n=$((n + 1)); [ "$n" -lt 50 ]; sleep 1
done
before=$(cat /fixtures/reads)
sleep 1
[ "$(cat /fixtures/reads)" = "$before" ]
[ ! -e /fixtures/offcount ]
printf '{"present":1,"capacity":20,"level_supported":true,"level":"Critical","status":"Charging","voltage":3800000}' > /fixtures/state.json
ACTION=change /sbin/hotplug-call power_supply
n=0
until [ -s /fixtures/offcount ]; do
    n=$((n + 1)); [ "$n" -lt 50 ]; sleep 1
done
ACTION=change /sbin/hotplug-call power_supply
sleep 1
[ "$(cat /fixtures/offcount)" = 1 ]
[ "$(cat /fixtures/reason)" = critical ]
kill "$guard_pid"
wait "$guard_pid"
guard_pid=
printf 'PASS: real hotplug -> ubus -> uloop, no idle reads, one mocked poweroff, SIGTERM exit\n'

rm /fixtures/offcount /fixtures/reads /fixtures/reason
printf '{"present":1,"capacity":1,"level_supported":false,"status":"Discharging","voltage":3220000}' > /fixtures/state.json
ucode /tests/battery-events.uc uvlo &
guard_pid=$!
n=0
until [ -s /fixtures/reads ]; do
    n=$((n + 1)); [ "$n" -lt 50 ]; sleep 1
done
for i in 1 2 3 4 5 6 7 8 9 10; do ACTION=change /sbin/hotplug-call power_supply; done
[ ! -e /fixtures/offcount ]
n=0
until [ -s /fixtures/offcount ]; do
    n=$((n + 1)); [ "$n" -lt 60 ]; sleep 1
done
[ "$(cat /fixtures/offcount)" = 1 ]
[ "$(cat /fixtures/reason)" = undervoltage ]
kill "$guard_pid"
wait "$guard_pid"
guard_pid=
printf 'PASS: real 800ms UVLO timers complete despite event bursts; no forced or real poweroff\n'

ucode /tests/battery-checkpoint-events.uc &
guard_pid=$!
n=0
until [ "$(cat /fixtures/checkpoint-ticks 2>/dev/null || echo 0)" -ge 3 ]; do
    n=$((n + 1)); [ "$n" -lt 10 ]; sleep 1
done
[ "$(cat /fixtures/checkpoint-reads)" = 1 ]
kill "$guard_pid"
wait "$guard_pid"
guard_pid=
[ -s /fixtures/checkpoint-stopped ]
[ "$(cat /fixtures/checkpoint-stopped)" -ge 4 ]
printf 'PASS: checkpoint timer shares the event loop, does not poll battery state, and saves on SIGTERM\n'
