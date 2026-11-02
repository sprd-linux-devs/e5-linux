#!/bin/bash
# Build the e5-linux root filesystem inside an arm64 Debian container.
#
# rootfs/build-rootfs.sh is written for "a Linux build host".  On the Mac this
# project is developed on, that host is `docker run debian:trixie` on Apple
# Silicon, which is aarch64 *natively* -- so the package install runs at native
# speed instead of under qemu-aarch64.  That emulation is why the device used to
# do this install itself (rootfs/device-build.sh) and why apt's resolver timed
# out there.
#
# e5-chroot.sh (user namespace + qemu + binfmt_misc) cannot work here: qemu-user
# is a Linux ELF binary, so it does not run on macOS at all.  It is bind-mounted
# over for the duration of the run; the file in the tree is untouched.
#
#   rootfs/build-rootfs-container.sh [deps] [fetch] [install] [configure] [repair] [pack]
#
# With no argument it runs all of them.  The stages exist so a later step can be
# re-run without the ~40 minute apt pass:
#
#   ./build-rootfs-container.sh deps pack      # re-pack after an overlay change
#   ./build-rootfs-container.sh install        # only the package set changed
#
# The result is out/rootfs.ext4, 4 GiB by default (E5_IMG_MIB overrides it).
# E5_ROOTFS_VOLUME selects an independent build tree; use a new volume for a
# clean build. E5_ROOTFS_OUT is an output path relative to the repository.
# E5_MAINLINE=1 stages modules from E5_UPSTREAM_OUT (also repository-relative,
# default upstream/out-release) instead of the vendor 5.15 object tree.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
TOP="$(cd "$HERE/.." && pwd)"

# Reuse the host's existing static-helper cache. The Debian assembly container
# intentionally has no cross compiler; configure will verify/reuse this input.
case " ${*:-all} " in
    *" all "*|*" configure "*) python3 "$TOP/devices/common/build-modem-loader.py" >/dev/null ;;
esac

# The tree itself lives in a named Docker volume mounted over work/rootfs-build,
# not on the macOS bind mount: that one does not store file groups (measured:
# unix_chkpwd root:shadow came back root:root), so every dpkg-installed file with
# a non-root group -- dbus-daemon-launch-helper root:messagebus, unix_chkpwd,
# /etc/shadow -- lost it.  The volume is Linux ext4 inside the Docker VM, keeps
# everything, and persists between runs so the stages stay re-runnable.
# (It shadows any old host-side tree in work/rootfs-build: the first run after
# this change fetches and installs from scratch.)
exec docker run --rm --privileged \
    -e E5_IMG_MIB="${E5_IMG_MIB:-4096}" \
    -e E5_ROOTFS_OUT="/w/${E5_ROOTFS_OUT:-out/rootfs.ext4}" \
    -e E5_MAINLINE="${E5_MAINLINE:-}" \
    -e E5_UPSTREAM_OUT="/w/${E5_UPSTREAM_OUT:-upstream/out-release}" \
    -e E5_ANDROID_SUBSET="${E5_ANDROID_SUBSET:+/w/$E5_ANDROID_SUBSET}" \
    -v "$TOP":/w -v "${E5_ROOTFS_VOLUME:-e5-rootfs-build}":/w/work/rootfs-build -w /w debian:trixie \
    bash /w/rootfs/rootfs-in-container.sh "$@"
