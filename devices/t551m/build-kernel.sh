#!/bin/bash
# Linux host/WSL. Keep source and objects on a native Linux filesystem.
# T551M_RELEASE=1 omits the forced userdata path for TF/partition installers.
set -euo pipefail
# Shared config disables automatic SCM suffixes; suppress the fallback '+' too.
export LOCALVERSION=
HERE=$(cd "$(dirname "$0")" && pwd)
TOP=$(cd "$HERE/../.." && pwd)
K=${T551M_KERNEL:?Set T551M_KERNEL to a linux-lts-e5 checkout}
O=${T551M_BUILD:?Set T551M_BUILD to the object directory}
DEST=${T551M_OUT:-$TOP/out/t551m/kernel}
command -v pahole >/dev/null || { echo 'BTF requires pahole (Ubuntu: apt install pahole)' >&2; exit 1; }
mkdir -p "$O" "$DEST/modules"
python3 "$HERE/prepare-kernel.py" "$K" --host-sink
python3 "$HERE/test_charger.py" "$K/drivers/power/supply/bq2560x-charger.c"
python3 "$HERE/test_charge_profile.py"
python3 - "$TOP/upstream/e5-mainline.config" "$O/t551m.config" "${T551M_RELEASE:-0}" <<'PY'
import pathlib, sys
s = pathlib.Path(sys.argv[1]).read_text()
s = s.replace('CONFIG_LOCALVERSION="-e5"', 'CONFIG_LOCALVERSION="-t551m-otg10"')
s += '\n' + (pathlib.Path(sys.argv[1]).parents[1] / 'devices/t551m/cpufreq/config').read_text()
s += '\n# T551M ships 32-bit ARM Android modem executables.\nCONFIG_COMPAT=y\nCONFIG_COMPAT_32BIT_TIME=y\n'
s += '\n# USB host storage and common removable-disk formats.\nCONFIG_SCSI=m\nCONFIG_BLK_DEV_SD=m\nCONFIG_USB_STORAGE=m\nCONFIG_USB_UAS=m\nCONFIG_EXFAT_FS=m\nCONFIG_NTFS3_FS=m\nCONFIG_NLS_UTF8=m\n'
s += '\n# Host-side USB Ethernet (Realtek, ASIX, CDC and RNDIS).\nCONFIG_USB_USBNET=m\nCONFIG_USB_RTL8152=m\nCONFIG_USB_NET_AX8817X=m\nCONFIG_USB_NET_AX88179_178A=m\nCONFIG_USB_NET_CDCETHER=m\nCONFIG_USB_NET_CDC_NCM=m\nCONFIG_USB_NET_RNDIS_HOST=m\nCONFIG_USB_NET_SMSC75XX=m\nCONFIG_USB_NET_SMSC95XX=m\n'
s = s.replace(' e5.openwrt=openwrt-mainline.ext4',
              '' if sys.argv[3] == '1' else ' e5.openwrt=openwrt-t551m.ext4')
s = s.replace('CONFIG_CHARGER_AW32257=m', 'CONFIG_CHARGER_AW32257=n\nCONFIG_CHARGER_BQ2560X_SPRD=m')
s = s.replace('CONFIG_SND_SOC_UNISOC_PA_AW87XXX=m', 'CONFIG_SND_SOC_UNISOC_PA_AW87XXX=n')
pathlib.Path(sys.argv[2]).write_text(s)
PY
cd "$K"
make_args=(O="$O" ARCH=arm64 LLVM=1 LLVM_IAS=1 CROSS_COMPILE=aarch64-linux-gnu-)
make "${make_args[@]}" allnoconfig
scripts/kconfig/merge_config.sh -m -O "$O" "$O/.config" "$O/t551m.config"
# PR #228: NFSv4.1 is a separate prerequisite only on kernels exposing it.
if grep -q '^config NFS_V4_1$' fs/nfs/Kconfig; then
    scripts/config --file "$O/.config" --enable NFS_V4_1
fi
make "${make_args[@]}" olddefconfig
python3 - "$O/t551m.config" "$O/.config" "$TOP/upstream/config-ignored.txt" <<'PY'
import pathlib, sys
def config(p):
    return dict(line.split('=',1) for line in pathlib.Path(p).read_text().splitlines() if line.startswith('CONFIG_') and '=' in line)
wanted, actual = config(sys.argv[1]), config(sys.argv[2])
ignore_path = pathlib.Path(sys.argv[3])
ignored = ignore_path.read_text().splitlines() if ignore_path.exists() else []
bad = [k for k,v in wanted.items() if actual.get(k, 'n') != v and k not in ignored]
if bad: raise SystemExit('Config not accepted: ' + ', '.join(bad))
PY
make "${make_args[@]}" -j"${JOBS:-8}" Image modules > "$O/build.log" 2>&1 || { tail -80 "$O/build.log"; exit 1; }
cp "$O/arch/arm64/boot/Image" "$DEST/"
cp "$O/.config" "$DEST/config"
cp "$O/System.map" "$O/modules.builtin" "$O/modules.builtin.modinfo" "$DEST/"
cp "$O/include/config/kernel.release" "$DEST/kernel.release"
python3 "$TOP/upstream/wrap-image.py" "$DEST/Image" "$DEST/Image.lk"
make "${make_args[@]}" INSTALL_MOD_PATH="$O/staged" INSTALL_MOD_STRIP=1 modules_install
release=$(cat "$DEST/kernel.release")
find "$DEST/modules" -maxdepth 1 -type f -name '*.ko' -delete
find "$O/staged/lib/modules/$release" -name '*.ko' -exec cp {} "$DEST/modules/" \;
tar -C "$O/staged" -cf "$DEST/modules.tar" "lib/modules/$release"
sed 's/aw32257_charger.ko/bq2560x-charger.ko/' "$TOP/upstream/module-order.txt" > "$DEST/module-order.txt"
git rev-parse HEAD > "$DEST/source-commit"
sha256sum "$DEST/Image.lk" "$DEST/modules.tar" > "$DEST/SHA256SUMS"
python3 "$TOP/upstream/check-container-support.py" "$DEST" --record
python3 "$TOP/upstream/stage-root-modules.py" "$DEST"
