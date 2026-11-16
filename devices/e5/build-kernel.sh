#!/bin/bash
# Linux/WSL; use a separate clean E5 source/object tree, never the T551M build.
set -euo pipefail
# Shared config disables automatic SCM suffixes; suppress the fallback '+' too.
export LOCALVERSION=
HERE=$(cd "$(dirname "$0")" && pwd)
TOP=$(cd "$HERE/../.." && pwd)
K=${E5_KERNEL_TREE:?Set E5_KERNEL_TREE to a clean linux-lts-e5 checkout}
O=${E5_OUTDIR:?Set E5_OUTDIR to a separate E5 object directory}
DEST=${E5_FEATURE_OUT:-$TOP/out/e5/kernel}
command -v pahole >/dev/null
mkdir -p "$O" "$DEST/modules"
python3 "$HERE/prepare-kernel.py" "$K"
python3 - "$TOP" "$O/features.config" <<'PY'
from pathlib import Path
import sys
top, output = map(Path, sys.argv[1:])
text = (top / 'upstream/e5-mainline.config').read_text()
text = text.replace('CONFIG_LOCALVERSION="-e5"', 'CONFIG_LOCALVERSION="-e5-mobile4"')
text = text.replace(' e5.openwrt=openwrt-mainline.ext4', '')
text += '\n' + (top / 'devices/t551m/cpufreq/config').read_text()
text += '\nCONFIG_LEDS_E5_AW3641=m\n'
for key in ('SCSI', 'BLK_DEV_SD', 'USB_STORAGE', 'USB_UAS', 'EXFAT_FS', 'NTFS3_FS',
            'NLS_UTF8', 'USB_USBNET', 'USB_RTL8152', 'USB_NET_AX8817X',
            'USB_NET_AX88179_178A', 'USB_NET_CDCETHER', 'USB_NET_CDC_NCM',
            'USB_NET_RNDIS_HOST', 'USB_NET_SMSC75XX', 'USB_NET_SMSC95XX'):
    text += '\nCONFIG_' + key + '=m'
output.write_text(text + '\n')
PY
cd "$K"
args=(O="$O" ARCH=arm64 LLVM=1 LLVM_IAS=1 CROSS_COMPILE=aarch64-linux-gnu-)
make "${args[@]}" allnoconfig
scripts/kconfig/merge_config.sh -m -O "$O" "$O/.config" "$O/features.config"
# PR #228: NFSv4.1 is a separate prerequisite only on kernels exposing it.
if grep -q '^config NFS_V4_1$' fs/nfs/Kconfig; then
    scripts/config --file "$O/.config" --enable NFS_V4_1
fi
make "${args[@]}" olddefconfig
python3 - "$O/features.config" "$O/.config" "$TOP/upstream/config-ignored.txt" <<'PY'
from pathlib import Path
import sys
def config(path):
    return dict(line.split('=', 1) for line in Path(path).read_text().splitlines()
                if line.startswith('CONFIG_') and '=' in line)
wanted, actual = map(config, sys.argv[1:3])
ignored = Path(sys.argv[3]).read_text().splitlines() if Path(sys.argv[3]).exists() else []
bad = [key for key, value in wanted.items() if actual.get(key, 'n') != value and key not in ignored]
if bad:
    raise SystemExit('Kernel options not accepted: ' + ', '.join(bad))
for key in ('CONFIG_CHARGER_AW32257', 'CONFIG_SND_SOC_UNISOC_PA_AW87XXX'):
    assert actual[key] == 'm', 'E5 native driver must remain enabled: ' + key
assert 'e5.openwrt=' not in actual['CONFIG_CMDLINE']
PY
make "${args[@]}" -j"${JOBS:-8}" Image modules > "$O/build.log" 2>&1 || { tail -80 "$O/build.log"; exit 1; }
cp "$O/arch/arm64/boot/Image" "$O/System.map" "$O/modules.builtin" "$O/modules.builtin.modinfo" "$DEST/"
cp "$O/.config" "$DEST/config"
cp "$O/include/config/kernel.release" "$DEST/kernel.release"
python3 "$TOP/upstream/wrap-image.py" "$DEST/Image" "$DEST/Image.lk"
make "${args[@]}" INSTALL_MOD_PATH="$O/staged" INSTALL_MOD_STRIP=1 modules_install
release=$(cat "$DEST/kernel.release")
find "$DEST/modules" -maxdepth 1 -type f -name '*.ko' -delete
find "$O/staged/lib/modules/$release" -name '*.ko' -exec cp {} "$DEST/modules/" \;
tar -C "$O/staged" -cf "$DEST/modules.tar" "lib/modules/$release"
cp "$TOP/upstream/module-order.txt" "$DEST/module-order.txt"
git rev-parse HEAD > "$DEST/source-commit"
python3 "$TOP/upstream/check-container-support.py" "$DEST" --record
python3 "$TOP/upstream/stage-root-modules.py" "$DEST"
sha256sum "$DEST/Image.lk" "$DEST/modules.tar" "$DEST/root-modules.tar" > "$DEST/SHA256SUMS"
