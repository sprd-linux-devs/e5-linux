#!/bin/sh
# If something leaves the board's USB gadget unbound, the board loses its network
# and its serial console at once.  This runs early and rebinds to the UDC if it is
# empty.
set -u
G=/sys/kernel/config/usb_gadget/linux
[ -d "$G" ] || exit 0
# E5/T551M expose musb-hdrc.1.auto; M8 exposes 25100000.dwc3. Prefer the
# profile override, then the first controller the kernel registered.
UDC=${E5_GADGET_UDC:-}
if [ -z "$UDC" ]; then
    for u in /sys/class/udc/*; do
        [ -e "$u" ] && { UDC=${u##*/}; break; }
    done
fi
[ -n "$UDC" ] || { echo "gadget-guard: no USB device controller" >&2; exit 0; }
cur=$(cat "$G/UDC" 2>/dev/null)
if [ -n "$cur" ]; then
    echo "gadget bound to $cur"
    exit 0
fi
echo "gadget unbound -- rebinding to $UDC"
echo "$UDC" > "$G/UDC" 2>/dev/null
sleep 2
echo "UDC=$(cat "$G/UDC")"
