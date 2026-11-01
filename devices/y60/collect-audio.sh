#!/bin/sh
# Read-only Y60 audio diagnostics. No playback, calls, mixer writes or NV.
set -u
profile=$(cat /etc/e5/device-profile 2>/dev/null)
[ "$profile" = y60 ] || { echo 'Not a Y60 installation'; exit 2; }
export PATH=/usr/sbin:/usr/bin:/sbin:/bin:/opt/e5/bin
section() { printf '\n== %s ==\n' "$1"; }
section kernel
uname -a
section 'audio tools and startup state'
for tool in python3 amixer alsaucm aplay btattach; do command -v "$tool" || true; done
uci -q get e5-audio.main.enabled || true
uci -q get e5-bluetooth.main.enabled || true
ls -l /run/e5-audio.ready /run/e5-audio-dsp.started /etc/rc.d/*e5-audio /etc/rc.d/*e5-bt 2>/dev/null
section 'sound cards and PCM endpoints'
cat /proc/asound/cards /proc/asound/pcm 2>/dev/null
section 'Y60 audio staging and calibration files'
for f in /etc/e5/receiver-wiring /etc/e5/media-hardware-max; do
    printf '%s: ' "$f"; cat "$f" 2>/dev/null || true
done
ls -l /etc/rc.d/S18e5-y60-audio /usr/lib/e5/y60_audio.py \
    /lib/firmware/aw87xxx_acf.bin /lib/firmware/y60-audio_route.xml \
    /lib/firmware/y60-audio_pga.xml /lib/firmware/codec.xml \
    /lib/firmware/audio_structure /lib/firmware/dsp_vbc /lib/firmware/cvs 2>/dev/null
section 'effective userspace routes'
cat /usr/share/e5/voice-routes.json 2>/dev/null
cat /usr/share/alsa/ucm2/sprdphone-sc273/HiFi.conf 2>/dev/null
section 'ALSA mixer readback'
card=$(awk '/sprdphone/ {print $1; exit}' /proc/asound/cards 2>/dev/null)
if [ -n "$card" ]; then
    amixer -c "$card" contents 2>&1
fi
section 'amplifier device and firmware status'
for d in /sys/bus/i2c/devices/*-0058; do
    [ -d "$d" ] || continue
    ls -ld "$d" "$d/driver" 2>/dev/null
    for f in name profile; do
        [ ! -r "$d/$f" ] || { printf '%s: ' "$d/$f"; cat "$d/$f"; }
    done
done
section 'audio kernel messages'
dmesg | grep -iE 'asoc|snd|aw87|audio|agdsp|codec|ext.pa|hook_general_spk' | tail -n 250
section 'audio service errors'
logread 2>/dev/null | grep -iE 'y60.audio|y60_audio|e5.audio|e5-voice|pulseaudio|UCM|mixer|Missing Y60|Invalid Y60|Unexpected Y60' | tail -n 120
section 'Bluetooth attachment and setup errors'
ls -ld /dev/ttyBT0 /sys/class/bluetooth /sys/class/bluetooth/hci* 2>/dev/null
ls -l /lib/firmware/sprd/marlin3lite_pskey.bin /lib/firmware/sprd/marlin3lite_rf.bin 2>/dev/null
logread 2>/dev/null | grep -iE 'e5-bt|btattach|bluetooth|M8-family profile required' | tail -n 100 |
    sed -E 's/([[:xdigit:]]{2}:){5}[[:xdigit:]]{2}/<BT-address>/g'
true
