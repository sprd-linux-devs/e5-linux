#!/bin/bash
# Stage 3: turn the installed Debian tree into an e5-linux system.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="${E5_ROOT:-$HERE/../work/rootfs-build/rootfs}"

echo "=== overlay ==="
# The base image is usrmerge: /lib is a symlink to usr/lib, and cp refuses to
# replace a symlink with the overlay's real lib/ directory (the firmware files in
# it).  Merge those entries under /usr instead -- on the running system that is
# the same path.  Device-built trees whose tar pass materialised the symlinks
# take the plain branch.
for entry in "$HERE/overlay"/*; do
    [ -e "$entry" ] || continue
    name=$(basename "$entry")
    if [ -L "$ROOT/$name" ] && [ -d "$entry" ]; then
        # Debian's wireless-regdb ships /usr/lib/firmware/regulatory.db as an
        # alternatives symlink, and a tree that never ran update-alternatives has
        # it dangling; cp then refuses to write through it ("not writing through
        # dangling symlink"), so clear the dangling links we are about to replace.
        (cd "$entry" && find . \( -type f -o -type l \) -print) | while read -r f; do
            dest="$ROOT/usr/$name/${f#./}"
            if [ -L "$dest" ] && [ ! -e "$dest" ]; then rm -f "$dest"; fi
        done
        cp -a "$entry/." "$ROOT/usr/$name/"
    else
        cp -a "$entry" "$ROOT/"
    fi
done

# Windows checkouts may not retain the new helper's executable bit.
chmod 755 "$ROOT/opt/e5/e5-data-priority"
MODEM_LOADER_PATCH=$(python3 "$HERE/../devices/common/build-modem-loader.py")
cp "$MODEM_LOADER_PATCH" "$ROOT/opt/e5/modem-loader-patch"
chmod 755 "$ROOT/opt/e5/modem-loader-patch"

echo "=== locale ==="
bash "$HERE/e5-chroot.sh" '
    grep -q "^en_US.UTF-8" /etc/locale.gen || echo "en_US.UTF-8 UTF-8" >> /etc/locale.gen
    echo "LANG=en_US.UTF-8" > /etc/default/locale
    locale-gen >/dev/null 2>&1 || true
    ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime
    echo "e5-linux" > /etc/hostname
'

echo "=== user ==="
bash "$HERE/e5-chroot.sh" '
    set -e
    if ! id e5 >/dev/null 2>&1; then
        # netdev is not in the fresh base tree (a package postinst creates it on
        # a full system), and useradd refuses a group that does not exist.
        getent group netdev >/dev/null || groupadd -r netdev
        useradd -m -s /bin/bash -G sudo,video,render,input,audio,netdev e5
    fi
    echo "e5:123456" | chpasswd
    echo "root:root" | chpasswd
    # The device has a touchscreen and no keyboard, so autologin is the only way
    # in; a password that must be typed would make it unreachable.
    # rm first: the file is 0440, and a build host that maps root onto the host
    # user (Docker Desktop bind mounts) cannot reopen it for writing
    rm -f /etc/sudoers.d/10-e5
    printf "e5 ALL=(ALL) NOPASSWD:ALL\n" > /etc/sudoers.d/10-e5
    chmod 0440 /etc/sudoers.d/10-e5
'

echo "=== services ==="
bash "$HERE/e5-chroot.sh" '
    set -e
    # SDDM, after all.  Its Wayland *greeter* cannot draw on this image
    # (kwin_wayland went with KDE, x11-user was never installed), but the session
    # does not go through the greeter: /etc/sddm/wayland-session execs the session
    # directly and the sddm config in the image carries the WLR_RENDERER=gles2 that
    # phoc needs on this panel.  Autologin takes it from there, both on the
    # display and on the keypad.
    #
    # A getty-based session was tried instead for a day and is a trap: without
    # that env phoc spins at 90% CPU, the session never appears to input, and the
    # physical keys look dead -- they are not, they just never reach the UI.
    systemctl --root=/ enable sddm.service >/dev/null 2>&1 || echo "warn: sddm enable failed"
    # This board has no RTC: without something setting the clock the device comes
    # up years behind and apt refuses the mirror ("Not live until ...").  The
    # bearer is up a couple of minutes into the boot, which is soon enough.
    systemctl --root=/ enable systemd-timesyncd.service >/dev/null 2>&1 || echo "warn: timesyncd enable failed"
    systemctl --root=/ enable e5-boot-ok.service >/dev/null 2>&1 || echo "warn: e5-boot-ok enable failed"
    systemctl --root=/ enable e5-zram.service >/dev/null 2>&1 || echo "warn: zram enable failed"
    # The LAN -- br0, usb0 and the hotspot on 192.168.9.1, 192.168.77.1 kept as a
    # second address -- is built by e5-net-bridge.service with ip, and the busybox
    # telnetd that is the only way into a device with no usable keypad rides on it.
    # systemd-networkd is not involved any more (its rtnl requests time out on this
    # SoC; etc/systemd/network/*.network mark every link Unmanaged=yes).
    systemctl --root=/ enable e5-bt-attach.service >/dev/null 2>&1 || echo "warn: bt-attach enable failed"
    # The baseband: the vendor modem_control chroot boots the CP, the two vendor
    # helpers persist the modem NV data, and ModemManager is the one owner of
    # the AT channel for the whole boot -- its unisoc plugin, on the WWAN port
    # e5-sipc-wwan loads (docs/FINDINGS.md 37).  A single owner is what the SIPC
    # channel and the CP command queue both require; e5-sipc-wwan carries
    # Conflicts= against unisoc-cpd and the older owners, which stay installed
    # as the fallback, not enabled.
    #
    # e5-regdb-load feeds cfg80211 the regulatory database for the 5 GHz
    # hotspot (the NetworkManager "Hotspot" connection,
    # enabled below), e5-telnetd is the way in on a device with no usable keypad,
    # and e5-gadget-guard keeps the USB gadget alive.  These used to be enabled by
    # hand on a device that was already installed, which is why a fresh install
    # once had no hotspot at all.  e5-fixups is the port of mu300-fixups:
    # it restores the cap_net_raw on ping and links e5-next-boot/mobile-data/e5-at into
    # /usr/local/bin, which is what makes `sudo e5-next-boot android` work.
    for s in e5-vendor e5-cp_diskserver e5-refnotify \
             e5-net-bridge e5-sipc-wwan \
             e5-regdb-load e5-telnetd e5-gadget-guard e5-usb-watch e5-fixups; do
        systemctl --root=/ enable $s.service >/dev/null 2>&1 || echo "warn: $s enable failed"
    done
    # Wi-Fi: NetworkManager owns wlan0 only (etc/NetworkManager/conf.d/50-e5.conf)
    # -- the hotspot, an AP port of br0, and whatever network Phosh joins.  Its
    # wait-online unit is a no-op (a drop-in in the overlay).
    systemctl --root=/ enable NetworkManager.service >/dev/null 2>&1 || echo "warn: NetworkManager enable failed"
    systemctl --root=/ enable ModemManager.service >/dev/null 2>&1 || echo "warn: ModemManager enable failed"
    # The sound card: e5-audio loads the 24 vendor audio modules, boots the AGDSP
    # off l_agdsp_a and sets the speaker route before session PipeWire can
    # probe the card (the 2026-09-19 resets were exactly that probe landing on a
    # DSP with no firmware).  Enabling fails softly when the unit is absent, and
    # the service itself refuses to start the DSP without the card registered.
    systemctl --root=/ enable e5-audio.service >/dev/null 2>&1 || echo "warn: e5-audio enable failed (no unit staged?)"
    systemctl --global enable e5-capture.service >/dev/null 2>&1 || echo "warn: capture broker enable failed"
    systemctl --root=/ enable serial-getty@ttyGS0.service >/dev/null 2>&1 || echo "warn: getty enable failed"
    systemctl set-default graphical.target >/dev/null 2>&1 || true
    echo "enabled:"; ls /etc/systemd/system/graphical.target.wants/ /etc/systemd/system/multi-user.target.wants/ 2>/dev/null | head -30
'

echo "=== audio modules ==="
# Stage the vendor audio modules (sound/soc/sprd + drivers/unisoc_platform/sprd_audio,
# =m in e5_rongyue_defconfig) into the image so /opt/e5/e5-audio-dsp can modprobe
# them at boot.  They deliberately stay out of the initramfs (boot/module-order.extra
# documents why): loading them is the first step of the controlled DSP bring-up, not
# a boot requirement, and the initramfs path is what put a dead-DSP card in front of
# pipewire in the 2026-09-19 sessions.
#
# The modules come straight from the kernel output tree (out_modules carries only
# what the initramfs loads, which does not include them); depmod makes modules.dep
# for modprobe, whose dependency resolution is what orders sprd-dmaengine-pcm after
# snd_soc_sprd_card (it needs the symbols the card exports -- boot/module-order.txt
# derives the same order for the initramfs from nm output).
OL="$HERE/../out_linux"
if [ -n "${E5_MAINLINE:-}" ]; then
    KOUT=${E5_UPSTREAM_OUT:-$HERE/../upstream/out-release}
    REL=$(cat "$KOUT/kernel.release")
    [ -s "$KOUT/modules.tar" ] || { echo "no mainline modules.tar in $KOUT" >&2; exit 1; }
    # Keep every module (including KMS/Panfrost dependencies) from this build.
    # Move the audio/modem modules to the locations the device scripts expect,
    # then build a single index; no 5.15 module is staged in this branch.
    rm -rf "$ROOT/usr/lib/modules/$REL"
    tar -xf "$KOUT/modules.tar" -C "$ROOT/usr" lib/modules
    for link in build source; do rm -f "$ROOT/usr/lib/modules/$REL/$link"; done
    grep -v '^#' "$HERE/../upstream/root-modules.txt" | while read -r entry; do
        [ -n "$entry" ] || continue
        src=$(find "$ROOT/usr/lib/modules/$REL/kernel" -name "$(basename "$entry")" -type f)
        [ -f "$src" ] || { echo "missing mainline module $entry" >&2; exit 1; }
        mkdir -p "$ROOT/usr/lib/modules/$REL/$(dirname "$entry")"
        mv "$src" "$ROOT/usr/lib/modules/$REL/$entry"
    done
    if command -v depmod >/dev/null 2>&1; then
        depmod -b "$ROOT" -e -F "$KOUT/System.map" "$REL"
    else
        python3 "$HERE/../boot/gen-modules-dep.py" "$ROOT/usr/lib/modules/$REL" > "$ROOT/usr/lib/modules/$REL/modules.dep"
    fi
    echo "staged mainline modules for $REL"
elif [ -d "$OL" ] && [ -f "$OL/include/generated/utsrelease.h" ]; then
    REL=$(sed -n 's/^#define UTS_RELEASE "\(.*\)"$/\1/p' "$OL/include/generated/utsrelease.h")
    AMOD="$ROOT/usr/lib/modules/$REL/audio"
    rm -rf "$AMOD"; mkdir -p "$AMOD"
    n=0
    find "$OL/sound/soc/sprd" "$OL/drivers/unisoc_platform/sprd_audio" -name '*.ko' -type f 2>/dev/null |
    while read -r f; do
        cp "$f" "$AMOD/"; n=$((n + 1)); echo "  $(basename "$f")"
    done
    # The same for the WWAN AT port of the baseband, which e5-sipc-wwan
    # modprobes when ModemManager is to own the modem (it must not be loaded
    # while unisoc-cpd holds the channel, so not from the initramfs either).
    MMOD="$ROOT/usr/lib/modules/$REL/modem"
    rm -rf "$MMOD"; mkdir -p "$MMOD"
    for f in "$OL/drivers/net/wwan/wwan.ko" "$OL/drivers/unisoc_platform/modem/sipc/sipc_wwan.ko"; do
        if [ -f "$f" ]; then cp "$f" "$MMOD/"; echo "  $(basename "$f")"
        else echo "  warn: no $(basename "$f") in out_linux; e5-sipc-wwan will fail" >&2; fi
    done
    n=$(ls "$AMOD" | wc -l)
    if [ "$n" -gt 0 ]; then
        for f in modules.builtin modules.builtin.modinfo; do
            [ -f "$OL/$f" ] && cp "$OL/$f" "$ROOT/usr/lib/modules/$REL/$f"
        done
        # host depmod parses ELF modinfo sections without executing them, so it
        # works on the arm64 modules from any host; the python fallback is
        # stage-modules.sh's rule for hosts without kmod.
        if command -v depmod >/dev/null 2>&1; then
            depmod -b "$ROOT" "$REL" 2>&1 | head -3 || true
        else
            python3 "$HERE/../boot/gen-modules-dep.py" "$ROOT/usr/lib/modules/$REL" > "$ROOT/usr/lib/modules/$REL/modules.dep"
        fi
        echo "staged $n audio modules for $REL"
    else
        echo "  warn: no audio .ko under out_linux (build the kernel first); e5-audio-dsp will have nothing to load" >&2
    fi
else
    echo "  warn: no out_linux kernel build; skipping audio module staging" >&2
fi

if [ -n "${E5_ANDROID_SUBSET:-}" ]; then
    echo "=== device's Android vendor subset ==="
    [ -x "$E5_ANDROID_SUBSET/vendor/bin/modem_control" ] || {
        echo "no modem_control in $E5_ANDROID_SUBSET" >&2; exit 1;
    }
    mkdir -p "$ROOT/opt/e5/android"
    cp -a "$E5_ANDROID_SUBSET/." "$ROOT/opt/e5/android/"
    chown -R 0:0 "$ROOT/opt/e5/android"
fi

# A standalone image must have the same permissions the old initramfs-overlay
# path restored at every boot: autologin and NetworkManager need these before
# either service starts.
bash "$HERE/e5-chroot.sh" 'set -e; chown -R e5:e5 /home/e5; if [ -f /home/e5/.bash_profile ]; then chmod 0644 /home/e5/.bash_profile; fi; chmod 0600 /usr/lib/NetworkManager/system-connections/*.nmconnection'

echo "=== sessions available ==="
ls "$ROOT"/usr/share/wayland-sessions/ 2>/dev/null || echo "(none)"

echo "=== cleanup ==="
bash "$HERE/e5-chroot.sh" 'apt-get -o APT::Sandbox::User=root clean >/dev/null 2>&1 || true; rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*.deb'
rm -f "$ROOT/qemu-aarch64-static"
# informational only: the tree still has /proc and /sys bind-mounted here, where du
# races with the kernel's own fd symlinks and exits non-zero -- under `set -e` that
# used to end the build one line before "CONFIGURE-DONE"
du -sh "$ROOT" 2>/dev/null || true
echo "CONFIGURE-DONE"
