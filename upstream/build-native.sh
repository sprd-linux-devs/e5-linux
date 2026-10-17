#!/bin/bash
# Build the E5's mainline kernel (linux-lts-e5) on the host, cross-compiling from x86_64 with an aarch64
# toolchain -- build.sh's steps and outputs without docker (for a build host with no docker access).  The
# toolchain is looked up under work/toolchain/ (Bootlin aarch64--glibc--stable: gcc 15, like the Ubuntu
# 26.04 container of build.sh/Dockerfile).
#
#   E5_CROSS       the cross prefix (default: the first work/toolchain/*/bin/aarch64-*-linux-gnu-gcc's)
#   E5_KERNEL_TREE the kernel repository (default: linux-lts-e5 next to upstream/)
#   E5_OUTDIR      the object directory (default: work/build/<kernelversion>, kept between builds)
#   E5_RELEASE=1   the kernel of a flash package, as build.sh: no e5.openwrt=, into upstream/out-release
set -eo pipefail
command -v pahole >/dev/null || { echo 'BTF requires pahole (Ubuntu: apt install pahole)' >&2; exit 1; }
HERE="$(cd "$(dirname "$0")" && pwd)"
TOP="$(cd "$HERE/.." && pwd)"
K="${E5_KERNEL_TREE:-$TOP/linux-lts-e5}"
if [ -z "${E5_CROSS:-}" ]; then
    gcc=$(echo "$TOP"/work/toolchain/*/bin/aarch64-*-linux-gnu-gcc 2>/dev/null | cut -d' ' -f1)
    [ -x "$gcc" ] || { echo "no aarch64 cross gcc under work/toolchain/ (or set E5_CROSS)" >&2; exit 1; }
    E5_CROSS="${gcc%gcc}"
fi
X="$E5_CROSS"
# the host ccache wrapper (Fedora puts gcc behind ccache) dies on a stray ~/.cache/ccache file; keep its cache in the tree
mkdir -p "$TOP/work/ccache"
export CCACHE_DIR="$TOP/work/ccache"
echo "== cross gcc $("$X"gcc -dumpversion) ($X)"

cd "$K"
python3 "$TOP/device/linux_device_common/kernel/display.py" .
python3 "$TOP/device/linux_device_common/kernel/power.py" .
python3 "$TOP/device/linux_device_common/kernel/emmc.py" .
python3 "$TOP/device/linux_device_common/kernel/eic.py" .
python3 "$TOP/device/linux_device_common/kernel/thermal.py" .
python3 "$TOP/device/linux_device_common/kernel/sipa.py" .
python3 "$TOP/device/linux_device_common/kernel/wifi-tx.py" .
python3 "$TOP/device/linux_device_common/kernel/fuel-gauge.py" .
python3 "$TOP/device/linux_device_common/kernel/wifi-sae.py" .
python3 "$TOP/device/linux_device_common/kernel/wifi-stations.py" .
KV=$(make -s kernelversion)
O="${E5_OUTDIR:-$TOP/work/build/$KV}"
mkdir -p "$O"
echo "== linux-lts-e5 $KV, $(git log --oneline -1)"
[ -z "$(git status --porcelain --untracked-files=no)" ] || echo "   (the tree has uncommitted changes: the release gets -dirty)"

CFG=$HERE/e5-mainline.config DEST=$HERE/out
if [ -n "${E5_RELEASE:-}" ]; then
    CFG=$(mktemp) DEST=$HERE/out-release
    trap 'rm -f "$CFG"' EXIT
    sed 's/ e5\.openwrt=[A-Za-z0-9._-]*//' $HERE/e5-mainline.config > "$CFG"
    ! grep -q 'e5\.openwrt=' "$CFG" || { echo "e5.openwrt= is still in the release command line" >&2; exit 1; }
    echo "   (release: no e5.openwrt=, into out-release/)"
fi
make O="$O" ARCH=arm64 CROSS_COMPILE="$X" allnoconfig >/dev/null
./scripts/kconfig/merge_config.sh -m -O "$O" "$O/.config" "$CFG" >/dev/null
# PR #228: NFSv4.1 is a separate prerequisite only on kernels exposing it.
if grep -q '^config NFS_V4_1$' fs/nfs/Kconfig; then
    scripts/config --file "$O/.config" --enable NFS_V4_1
fi
make O="$O" ARCH=arm64 CROSS_COMPILE="$X" olddefconfig >/dev/null
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
        [ "$g" = "$v" ] || grep -qx "$k" $HERE/config-ignored.txt 2>/dev/null || bad="$bad\nNOT SET: $k want $v got ${g:-unset}";;
    esac
done < "$CFG"
[ -z "$bad" ] || { printf "config options not taken:$bad\n" >&2; exit 1; }

# on failure, the compiler's own messages (a plain grep for "error" also matches object names)
make O="$O" ARCH=arm64 CROSS_COMPILE="$X" -j"$(nproc)" Image modules > "$O/build.log" 2>&1 || {
    grep -n -E ": (fatal )?error: |-Werror|treated as errors|undefined reference|No such file|Killed|internal compiler error|\*\*\*" -A3 "$O/build.log" | head -80 || true
    echo "--- end of build.log:"; tail -25 "$O/build.log"
    exit 1
}
mkdir -p $DEST
cp "$O/arch/arm64/boot/Image" "$O/System.map" "$O/modules.builtin" "$O/modules.builtin.modinfo" $DEST/
cp "$O/.config" $DEST/config
python3 $HERE/wrap-image.py $DEST/Image $DEST/Image.lk
cat "$O/include/config/kernel.release" > $DEST/kernel.release
# the modules: flat for the boot image (boot/build-boot-image.py --modules), and as lib/modules/<release> for
# a root filesystem
rm -rf "$O/mod" $DEST/modules && mkdir -p $DEST/modules
make -s O="$O" ARCH=arm64 CROSS_COMPILE="$X" INSTALL_MOD_PATH="$O/mod" INSTALL_MOD_STRIP=1 modules_install
find "$O/mod/lib/modules" -name '*.ko' -exec cp {} $DEST/modules/ \;
tar -C "$O/mod" -cf $DEST/modules.tar lib/modules
python3 "$HERE/check-container-support.py" "$DEST" --record
echo "== modules: $(ls $DEST/modules | wc -l)"
echo "== $(cat $DEST/kernel.release): $(ls -la $DEST/Image.lk | awk '{print $5}') bytes"
