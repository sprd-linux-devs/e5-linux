#!/usr/bin/env python3
"""Run the ordinary updater's real config migration in temporary roots."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

TOP = Path(__file__).resolve().parents[2]
SOURCE = (TOP/'openwrt/device-install-image.sh').read_text()
FUNCTION = SOURCE[SOURCE.index('keep_config() {'):SOURCE.index("# The device's own files")]


@unittest.skipUnless(os.name == 'posix', 'POSIX updater')
class ConfigDirectories(unittest.TestCase):
    def test_android_sd_update_prepares_its_metadata_directory(self):
        source = (TOP/'rootfs/debian-update-android-device.sh').read_text()
        start = source.index('mkdir -p "$M/etc/e5"')
        code = source[start:source.index('\n[ "$(sha256sum ', start)]
        with tempfile.TemporaryDirectory() as d:
            # Only the metadata step: no mounting, block writes or reboot.
            result = subprocess.run(['sh', '-ec', 'sync() { :; }; umount() { :; };\n' + code],
                                    env={**os.environ, 'M': d}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((Path(d)/'etc/e5/sd-system').read_text(), 'debian\n')
            self.assertEqual((Path(d)/'etc/e5/sd-gen').read_text(), '1\n')

    def test_missing_config_parents_and_existing_user_data(self):
        shells = [['sh']]
        if shutil.which('busybox'):
            shells.append(['busybox', 'ash'])
        for shell in shells:
            for with_image_defaults in (False, True):
                with self.subTest(shell=shell, defaults=with_image_defaults), tempfile.TemporaryDirectory() as d:
                    root = Path(d); old = root/'old'; new = root/'new'; new.mkdir()
                    saved = {'etc/config/wireless': b'USER WIFI', 'etc/shadow': b'USER PASSWORD',
                             'etc/dropbear/key': b'USER SSH KEY',
                             'etc/e5-infoscreen/wallpapers/user.png': b'USER WALLPAPER',
                             'etc/e5-infoscreen/plugins/user-app/main.js': b'USER APP',
                             'etc/bluetooth/main.conf': b'USER BT'}
                    for name, data in saved.items():
                        p = old/name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(data)
                    if with_image_defaults:
                        for folder in (old, new):
                            for name in ('etc/e5/image-version', 'etc/e5-infoscreen/plugins/esim/manifest.json'):
                                p = folder/name; p.parent.mkdir(parents=True, exist_ok=True)
                                p.write_bytes(b'OLD' if folder == old else b'NEW IMAGE')
                    code = FUNCTION + '\nkeep_config "$OLD" "$NEW"\n'
                    result = subprocess.run([*shell, '-ec', code], env={**os.environ, 'OLD': str(old),
                                            'NEW': str(new), 'E5_NV_POLICY': 'preserve'}, capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    for name, data in saved.items():
                        self.assertEqual((new/name).read_bytes(), data)
                    if with_image_defaults:
                        self.assertEqual((new/'etc/e5/image-version').read_bytes(), b'NEW IMAGE')
                        self.assertEqual((new/'etc/e5-infoscreen/plugins/esim/manifest.json').read_bytes(), b'NEW IMAGE')


if __name__ == '__main__':
    unittest.main()
