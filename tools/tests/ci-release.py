#!/usr/bin/env python3
"""CI input/release gates, without a device, uploads or production credentials."""
import importlib.util
import io
import json
import runpy
from pathlib import Path
import struct
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zlib

TOP = Path(__file__).resolve().parents[2]


def module(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), TOP / 'tools' / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


inputs = module('ci-inputs')
release = module('ci-release')


class ScreenNativeCI(unittest.TestCase):
    def test_sdk_is_used_before_ephemeral_cleanup_and_artifacts_cached(self):
        workflow=(TOP/'.github/workflows/release.yml').read_text(encoding='utf-8')
        self.assertLess(workflow.index('python3 devices/common/build-screen-native.py'),
                        workflow.index('docker volume rm e5-openwrt-src'))
        self.assertEqual(workflow.count('            out/native-screen/'),2)
        self.assertLess(workflow.index('python3 devices/t551m/test_screen_runtime.py -v'),
                        workflow.index('docker volume rm e5-openwrt-src'))
        self.assertIn("'devices/common/infoscreen/native/*.c'",workflow)
        self.assertIn("'devices/common/infoscreen/native/*.h'",workflow)
        runtime=(TOP/'openwrt/overlay/etc/init.d/e5-voice-audio').read_text()
        self.assertNotIn('python3',runtime)
        self.assertIn('/usr/libexec/e5-voice-native',runtime)


class Bootstrap(unittest.TestCase):
    def test_boot_strips_payload_and_preserves_avb(self):
        data = bytearray(64 << 20)
        data[:8] = b'ANDROID!'
        struct.pack_into('<I', data, 40, 4)
        data[4096:4120] = b'stock kernel to remove!!'
        data[8192:8448] = b'AVB0' + b'v' * 252
        data[-64:-60] = b'AVBf'
        struct.pack_into('>QQQ', data, len(data) - 52, 8192, 8192, 256)
        result = inputs.boot_template(bytes(data))
        self.assertNotIn(b'stock kernel', result)
        self.assertEqual(result[4096:4352], b'AVB0' + b'v' * 252)
        self.assertEqual(inputs.boot_template(result), result)

    def test_misc_strips_everything_outside_control(self):
        data = bytearray(b'x' * 4096)
        bc = bytearray(32)
        bc[4:8] = b'BCAB'
        struct.pack_into('<I', bc, 28, zlib.crc32(bc[:28]))
        data[0x800:0x820] = bc
        result = inputs.misc_template(data)
        self.assertEqual(result[0x800:0x820], bc)
        self.assertEqual(result[:0x800], bytes(0x800))

    def test_unsafe_archive_path_rejected_before_write(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'bad.tar.gz'
            with tarfile.open(path, 'w:gz') as archive:
                entry = tarfile.TarInfo('../outside'); entry.size = 1
                archive.addfile(entry, io.BytesIO(b'x'))
            with self.assertRaisesRegex(ValueError, 'path'):
                inputs.inspect(path)
            self.assertFalse((Path(temp).parent / 'outside').exists())

    def test_hash_checked_before_extracting(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'bad.tar.gz'; path.write_bytes(b'not an archive')
            args = type('Args', (), {'archive': path, 'sha256': '0' * 64, 'destination': Path(temp) / 'restore'})()
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                inputs.restore(args)
            self.assertFalse(args.destination.exists())

    def test_extra_package_rejected(self):
        with self.assertRaisesRegex(ValueError, 'exactly'):
            inputs.package_paths('P:cog\n\nP:libcogcore\n\nP:libwpewebkit\n\nP:vendor-firmware\n')


class RootAudit(unittest.TestCase):
    def audit(self, files):
        with tempfile.TemporaryDirectory() as temp:
            top = Path(temp)
            (top / 'work/openwrt').mkdir(parents=True)
            (top / 'upstream/out-release').mkdir(parents=True)
            (top / 'upstream/out-release/kernel.release').write_text('6.18-e5\n')
            (top / 'rootfs/overlay/opt/e5').mkdir(parents=True)
            for name in release.BLOCK_SOURCES:
                target = top / 'openwrt' / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((TOP / 'openwrt' / name).read_bytes())
            # The release audit also verifies the current SAE source marker.
            # Carry its real source inputs into this otherwise private tree.
            wifi = runpy.run_path(str(TOP / 'openwrt/wifi-sae-state.py'))
            for name in wifi['SOURCES']:
                (top / 'openwrt' / name).write_bytes((TOP / 'openwrt' / name).read_bytes())
            for name in ('vendor-start.sh', 'e5-modem-coldboot'):
                (top / 'rootfs/overlay/opt/e5' / name).write_bytes(b'startup fixture')
                files = {**files, 'opt/e5/' + name: b'startup fixture'}
            for name in ('openwrt/src/modem-loader-patch.c', 'devices/common/build-modem-loader.py'):
                target = top/name; target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((TOP/name).read_bytes())
            helper = top/'out/modem-loader/modem-loader-patch'
            helper.parent.mkdir(parents=True); helper.write_bytes(b'helper fixture')
            helper.with_suffix('.build.json').write_text(json.dumps({
                'inputs': {'source':release.file_digest(top/'openwrt/src/modem-loader-patch.c'),
                           'builder':release.file_digest(top/'devices/common/build-modem-loader.py')},
                'binary':release.file_digest(helper)}))
            files = {**files, 'opt/e5/modem-loader-patch':helper.read_bytes()}
            path = top / 'work/openwrt/e5-openwrt-25.12.5-generic-rootfs.tar.gz'
            with tarfile.open(path, 'w:gz') as archive:
                for name, data in files.items():
                    entry = tarfile.TarInfo(name); entry.size = len(data)
                    archive.addfile(entry, io.BytesIO(data))
            info = {'openwrt_version': '25.12.5', 'build_epoch': 123}
            with patch.object(release, 'TOP', top), patch.object(release.subprocess, 'check_output', return_value=''):
                release.audit_root(info)
            return info

    def files(self):
        wifi = runpy.run_path(str(TOP / 'openwrt/wifi-sae-state.py'))
        return {'usr/share/e5-infoscreen/VERSION': b'1.6.3',
                'etc/e5-infoscreen/plugins/phone/manifest.json': json.dumps({'version': '1.4'}).encode(),
                'etc/e5/build-time': b'123', 'lib/modules/6.18-e5/modem/sipc_wwan.ko': b'module',
                'etc/e5/block-mount.build-id': (release.block_build_id() + '\n').encode(),
                'etc/e5/wifi-sae.build-id': (wifi['build_id']() + '\n').encode(),
                'lib/netifd/hostapd-unisoc.sh': (TOP / 'openwrt/hostapd-unisoc.sh').read_bytes(),
                'usr/share/ucode/wifi/unisoc-sae.uc': (TOP / 'openwrt/hostapd-unisoc.uc').read_bytes(),
                'sbin/block': b'block', 'lib/libblkid-tiny.so': b'library', 'etc/init.d/fstab': b'init'}

    def test_same_release_and_epoch_pass(self):
        self.assertEqual(self.audit(self.files())['phone_version'], '1.4')

    def test_wrong_kernel_modules_rejected(self):
        files = self.files(); files['lib/modules/5.15/audio/card.ko'] = b'wrong kernel'
        with self.assertRaisesRegex(ValueError, 'modules'):
            self.audit(files)

    def test_wrong_build_time_rejected(self):
        files = self.files(); files['etc/e5/build-time'] = b'456'
        with self.assertRaisesRegex(ValueError, 'build time'):
            self.audit(files)

    def test_device_firmware_rejected(self):
        files = self.files(); files['lib/firmware/wcnmodem.bin'] = b'device firmware'
        with self.assertRaisesRegex(ValueError, 'device-specific'):
            self.audit(files)

    def test_unguarded_mount_package_rejected(self):
        files = self.files()
        files['etc/e5/block-mount.build-id'] = b'old-package\n'
        with self.assertRaisesRegex(ValueError, 'source mismatch'):
            self.audit(files)

    def test_missing_mount_package_payload_rejected(self):
        files = self.files()
        del files['sbin/block']
        with self.assertRaisesRegex(ValueError, 'block-mount payload missing'):
            self.audit(files)

    def test_stale_wifi_source_marker_rejected(self):
        files = self.files(); files['etc/e5/wifi-sae.build-id'] = b'old-sae\n'
        with self.assertRaisesRegex(ValueError, 'source mismatch'):
            self.audit(files)

    def test_missing_wifi_runtime_rejected(self):
        files = self.files(); del files['usr/share/ucode/wifi/unisoc-sae.uc']
        with self.assertRaisesRegex(ValueError, 'root source mismatch: missing=.*unisoc-sae'):
            self.audit(files)


if __name__ == '__main__':
    unittest.main()
