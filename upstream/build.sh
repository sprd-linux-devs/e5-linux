#!/bin/bash
# Build the E5's mainline kernel (linux-lts-e5) in the e5-mainline-build container:
# upstream/out/Image, Image.lk (for LK), modules/ (flat) and modules.tar (lib/modules), config, System.map.
#
#   docker build -t e5-mainline-build upstream/     (once)
#   upstream/build.sh                                (from the host; runs itself in the container)
#
# E5_KERNEL_TREE  the kernel repository (default: linux-lts-e5 next to upstream/)
# E5_RELEASE=1    the kernel of a flash package (openwrt/make-flash-bundle.sh E5_MAINLINE=1): the command line
#                 without e5.openwrt=, so boot/init starts the installed openwrt.ext4 and it can be the default
#                 boot; into upstream/out-release/, so that the trial scripts (upstream/out/) never take it
# The objects stay in the docker volume e5-mainline-out (a bind mount would be slower), per kernel release.
set -eo pipefail
if [ -z "${E5_IN_CONTAINER:-}" ]; then
    HERE="$(cd "$(dirname "$0")" && pwd)"
    K="${E5_KERNEL_TREE:-$HERE/../linux-lts-e5}"
    K="$(cd "$K" && pwd)"
    exec docker run --rm -e E5_IN_CONTAINER=1 -e E5_RELEASE="${E5_RELEASE:-}" \
        -e TZ=CST-8 -e KBUILD_BUILD_TIMESTAMP="${KBUILD_BUILD_TIMESTAMP:-}" \
        -e E5_OUTPUT_UID="$(id -u)" -e E5_OUTPUT_GID="$(id -g)" \
        -v "$K":/src/linux -v e5-mainline-out:/out -v "$HERE":/work \
        -v "$HERE/../device/linux_device_common/kernel":/policy:ro \
        e5-mainline-build bash /work/build.sh "$@"
fi

# An empty variable overrides kbuild's default, so unset it for local builds.
[ -n "${KBUILD_BUILD_TIMESTAMP:-}" ] || unset KBUILD_BUILD_TIMESTAMP
cd /src/linux
python3 /policy/display.py .
python3 /policy/power.py .
python3 /policy/charger-capabilities.py .
python3 /policy/emmc.py .
python3 /policy/sd-power.py .
python3 /policy/eic.py .
python3 /policy/thermal.py .
python3 /policy/sipa.py .
python3 /policy/wifi-tx.py .
python3 /policy/fuel-gauge.py .
python3 /policy/wifi-sae.py .
python3 /policy/wifi-stations.py .
KV=$(make -s kernelversion)
O=/out/$KV
mkdir -p "$O"
echo "== linux-lts-e5 $KV, $(git log --oneline -1)"
[ -z "$(git status --porcelain --untracked-files=no)" ] || echo "   (the tree has uncommitted changes: the release gets -dirty)"

CFG=/work/e5-mainline.config DEST=/work/out
if [ -n "${E5_RELEASE:-}" ]; then
    CFG=/tmp/e5-mainline-release.config DEST=/work/out-release
    sed 's/ e5\.openwrt=[A-Za-z0-9._-]*//' /work/e5-mainline.config > "$CFG"
    ! grep -q 'e5\.openwrt=' "$CFG" || { echo "e5.openwrt= is still in the release command line" >&2; exit 1; }
    echo "   (release: no e5.openwrt=, into out-release/)"
fi
make O="$O" ARCH=arm64 allnoconfig >/dev/null
./scripts/kconfig/merge_config.sh -m -O "$O" "$O/.config" "$CFG" >/dev/null
# PR #228: NFSv4.1 is a separate prerequisite only on kernels exposing it.
if grep -q '^config NFS_V4_1$' fs/nfs/Kconfig; then
    scripts/config --file "$O/.config" --enable NFS_V4_1
fi
make O="$O" ARCH=arm64 olddefconfig >/dev/null
# options Kconfig did not take: known ones are listed in config-ignored.txt, any other stops the build
# (mu300-linux: a silently dropped option has cost a working feature before)
bad=
while IFS= read -r l; do
    case "$l" in CONFIG_*=*)
        k=${l%%=*} v=${l#*=}
        g=$(grep -E "^$k=" "$O/.config" | cut -d= -f2- || true)
        if [ "$v" = n ]; then
            grep -q "^$k=[ym]" "$O/.config" && bad="$bad\nNOT DISABLED: $k"
            continue
        fi
        [ "$g" = "$v" ] || grep -qx "$k" /work/config-ignored.txt 2>/dev/null || bad="$bad\nNOT SET: $k want $v got ${g:-unset}";;
    esac
done < "$CFG"
[ -z "$bad" ] || { printf "config options not taken:$bad\n" >&2; exit 1; }

# on failure, the compiler's own messages (a plain grep for "error" also matches object names)
make O="$O" ARCH=arm64 -j"$(nproc)" Image modules > "$O/build.log" 2>&1 || {
    grep -n -E ": (fatal )?error: |-Werror|treated as errors|undefined reference|No such file|Killed|internal compiler error|\*\*\*" -A3 "$O/build.log" | head -80 || true
    echo "--- end of build.log:"; tail -25 "$O/build.log"
    exit 1
}
mkdir -p $DEST
cp "$O/arch/arm64/boot/Image" "$O/System.map" "$O/modules.builtin" "$O/modules.builtin.modinfo" $DEST/
cp "$O/.config" $DEST/config
python3 /work/wrap-image.py $DEST/Image $DEST/Image.lk
cat "$O/include/config/kernel.release" > $DEST/kernel.release
# the modules: flat for the boot image (boot/build-boot-image.py --modules), and as lib/modules/<release> for
# a root filesystem
rm -rf "$O/mod" $DEST/modules && mkdir -p $DEST/modules
make -s O="$O" ARCH=arm64 INSTALL_MOD_PATH="$O/mod" INSTALL_MOD_STRIP=1 modules_install
find "$O/mod/lib/modules" -name '*.ko' -exec cp {} $DEST/modules/ \;
tar -C "$O/mod" -cf $DEST/modules.tar lib/modules
python3 /work/check-container-support.py "$DEST" --record
# Docker creates these files as root on Linux bind mounts. The host must be
# able to add root-modules.tar and package the outputs after this container exits.
if [ -n "${E5_OUTPUT_UID:-}" ] && [ -n "${E5_OUTPUT_GID:-}" ]; then
    chown -R "$E5_OUTPUT_UID:$E5_OUTPUT_GID" "$DEST"
fi
echo "== modules: $(ls $DEST/modules | wc -l)"
echo "== $(cat $DEST/kernel.release): $(ls -la $DEST/Image.lk | awk '{print $5}') bytes"
