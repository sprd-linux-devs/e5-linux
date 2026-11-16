#!/usr/bin/env python3
"""Exercise profile boundaries and repeat staging on a real offline E5 root."""
import hashlib
from pathlib import Path
import runpy
import sys

HERE = Path(__file__).resolve().parent
root = Path(sys.argv[1])
stage = runpy.run_path(str(HERE / 'stage.py'))['stage']


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# These settings/assets must not be replaced by anything from the donor.
protected = ['etc/shadow', 'etc/config/network', 'etc/config/wireless',
             'etc/config/e5-infoscreen', 'etc/e5linux/default-boot',
             'opt/e5/e5-audio-dsp', 'opt/e5/android/vendor/bin/modem_control']
before = {name: digest(root / name) for name in protected}
stage(root)
assert before == {name: digest(root / name) for name in protected}
config = (root / 'etc/config/unisoc_modem').read_text()
assert "lte_supported_bands '1,3,5,8,34,38,39,40,41'" in config
assert 'snd-soc-sprd-pa-aw87xxx' in (root / 'opt/e5/e5-audio-dsp').read_text()
assert not (root / 'etc/e5/t551m-persistent').exists()
assert (root / 'etc/modules.d/e5-torch').read_text().split() == ['e5-aw3641-torch']
vendor = (root / 'opt/e5/vendor-start.sh').read_text()
assert vendor.index('nr_fixnv*|nr_runtimenv*') < vendor.index('[ -n "$n" ] && ln')
assert 'for p in nr_modem nr_phy;' in vendor
assert 'for p in nr_modem nr_phy nr_deltanv' not in vendor
assert 'mount --bind /run/e5-bootconfig.android "$A/proc/bootconfig"' in vendor
assert 'androidboot.slot_suffix' in vendor
assert '/opt/e5/t551m-nv-prepare || return 1' in (root / 'etc/init.d/e5-vendor').read_text()
for path in (root / 'etc/rc.d').iterdir():
    if path.is_symlink():
        assert path.exists(), 'Dangling service: ' + str(path)
marker = root / 'etc/e5/device-profile'
marker.write_text('t551m\n')
try:
    stage(root)
    raise AssertionError('Other device profile was overwritten')
except ValueError as error:
    assert 'another board' in str(error)
finally:
    marker.write_text('e5\n')
assert before == {name: digest(root / name) for name in protected}
print('PASS: repeated staging, E5 amplifier/firmware/config/auth/TF policy preserved, NV aliases guarded, foreign-board refusal')
