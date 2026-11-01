#!/usr/bin/env python3
"""Refresh shared features in a clean M8 offline userspace root."""
import argparse
import json
import os
from pathlib import Path
import runpy

TOP = Path(__file__).resolve().parents[2]


def validate_radio_defaults(config):
    # Automatic-mode selection is shared by all boards now. Keep an explicit
    # user choice; only a donor's LTE capability allowlist remains forbidden.
    if 'lte_supported_bands' in config.read_text():
        raise ValueError('Donor radio defaults found in M8 root')


def stage(root, *, profile='m8'):
    identities = {'m8': ('VIPME M8', 'VIPME-M8'), 'k1': ('angelcare K1', 'Angelcare-K1'),
                  'changxing60': ('中兴畅行60', 'Changxing-60'),
                  'y60': ('金世纪 Y60', 'Coolpad-Y60')}
    if profile not in identities:
        raise ValueError('Unsupported UMS9620 handheld profile')
    root = Path(root).resolve()
    if os.name == 'nt' or root == Path('/'):
        raise ValueError('Use Linux/WSL with an offline M8 root')
    marker = root / 'etc/e5/device-profile'
    if marker.exists() and marker.read_text().strip() != profile:
        raise ValueError('Refusing to convert an existing device profile')
    for name in ('etc/init.d/e5-vendor', 'etc/init.d/e5-sipc-wwan',
                 'usr/libexec/e5-infoscreen/session', 'usr/share/rpcd/ucode/e5-infoscreen.uc'):
        if not (root / name).is_file():
            raise ValueError('Missing shared base component: ' + name)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(profile + '\n')
    runpy.run_path(str(TOP / 'devices/wifi-common.py'))['stage'](root)
    runpy.run_path(str(TOP / 'devices/modem-recovery.py'))['stage'](root)
    runpy.run_path(str(TOP / 'devices/battery-guard.py'))['stage'](root)
    (root / 'etc/e5/device-model').write_text(identities[profile][0] + '\n')
    (root / 'etc/e5/device-hostname').write_text(identities[profile][1] + '\n')
    # This board has one physical loudspeaker for both phone and handsfree.
    # Shared voice code selects its wiring/calibration without a model check.
    if profile == 'm8':
        (root / 'etc/e5/receiver-output').write_text('speaker\n')
        (root / 'etc/e5/call-low-volume-attenuation-db').write_text('30\n')
        (root / 'etc/e5/receiver-volume-ceiling').write_text('5\n')
    shared = runpy.run_path(str(TOP / 'devices/e5/stage.py'))
    copy, link = shared['copy'], shared['link']
    for name in ('etc/init.d/e5-board-identity', 'etc/uci-defaults/97-e5-hostname'):
        copy(root, TOP / 'openwrt/overlay' / name, name)
    link(root, 'S11e5-board-identity', 'e5-board-identity')
    for p in (TOP / 'rootfs/overlay/opt/e5').iterdir():
        if p.is_file():
            copy(root, p, 'opt/e5/' + p.name)
    runpy.run_path(str(TOP / 'devices/t551m/ui.py'))['stage'](root, profile=profile)
    shared['stage_nv'](root)
    copy(root, TOP / 'devices/m8/bluetooth-address.py', 'usr/libexec/m8-bluetooth-address')
    keys = root / 'etc/bluetooth/keys'
    keys.mkdir(parents=True, exist_ok=True)
    keys.chmod(0o700)
    bt_config = root / 'etc/bluetooth/main.conf'
    if bt_config.is_file():
        bt_config.write_text(bt_config.read_text().replace('Name = E5\n', 'Name = OpenWrt\n'))
    bt = root / 'etc/init.d/e5-bt'
    text = bt.read_text()
    if '/usr/libexec/m8-bluetooth-address' not in text:
        anchor = '\t[ -e /dev/ttyBT0 ] || return 0'
        if text.count(anchor) != 1:
            raise ValueError('Unexpected Bluetooth startup')
        bt.write_text(text.replace(anchor, anchor + '\n\t/usr/libexec/m8-bluetooth-address || return 1'))
    for name, target in (
        ('charge-mode.py', 'usr/libexec/e5-charge-mode'),
        ('charge-screen.py', 'usr/libexec/e5-charge-screen'),
        ('charge-art.zip', 'usr/share/e5-charge/art.zip'),
        ('charge-mode-service', 'etc/init.d/e5-charge-mode'),
        ('usb-service', 'etc/init.d/t551m-usb'),
        ('usb-host-storage.modules', 'etc/modules.d/usb-host-storage'),
        ('usb-host-network.modules', 'etc/modules.d/usb-host-network'),
    ):
        copy(root, TOP / 'devices/t551m' / name, target,
             0o644 if name.endswith(('.zip', '.modules')) else 0o755)
    link(root, 'S14e5-charge-mode', 'e5-charge-mode')
    link(root, 'S25t551m-usb', 't551m-usb')
    (root / 'usr/share/e5-infoscreen/ADAPTATION').write_text(profile + '-mobile-v1\n')
    # Discover LTE capabilities on this modem, without a donor allowlist.
    config = root / 'etc/config/unisoc_modem'
    validate_radio_defaults(config)
    (root / 'etc/e5/feature-port.json').write_text(json.dumps({
        'profile': profile, 'schema': 1, 'status': 'bringup',
        'hardware_validation': 'in progress; not a release image',
        'staged_features': ['aurora', 'dashboard', 'dual-sim', 'traffic', 'sms',
                            'at-workers', 'pre-dial-replay', 'mobile-screen',
                            'phone-hfp', 'cpu-controls', 'usb-controls',
                            'charger-boot', 'isolated-nv', 'notification-sounds'],
    }, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    stage(parser.parse_args().root)
