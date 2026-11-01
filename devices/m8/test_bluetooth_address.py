import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('bt_address', Path(__file__).with_name('bluetooth-address.py'))
bt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)


class AddressRecovery(unittest.TestCase):
    def test_y60_valid_imported_identity_does_not_block_attach_or_need_android_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = root / 'etc/e5/device-profile'
            firmware = root / 'lib/firmware/sprd/marlin3lite_pskey.bin'
            profile.parent.mkdir(parents=True)
            firmware.parent.mkdir(parents=True)
            profile.write_text('y60\n')
            original = bytes(range(20)) + bytes.fromhex('010000000002') + bytes(range(150))
            firmware.write_bytes(original)
            self.assertFalse(bt.prepare(root))
            self.assertEqual(firmware.read_bytes(), original)

    def test_y60_bad_identity_still_requires_its_own_android_adapter_address(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = root / 'etc/e5/device-profile'
            firmware = root / 'lib/firmware/sprd/marlin3lite_pskey.bin'
            profile.parent.mkdir(parents=True)
            firmware.parent.mkdir(parents=True)
            profile.write_text('y60\n')
            original = bytes(176)
            firmware.write_bytes(original)
            with self.assertRaisesRegex(ValueError, 'address format'):
                bt.prepare(root)
            self.assertEqual(firmware.read_bytes(), original)

    def test_only_adapter_address_is_recovered_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = root / 'etc/e5/device-profile'
            firmware = root / 'lib/firmware/sprd/marlin3lite_pskey.bin'
            config = root / 'mnt/e5-data/misc/bluedroid/bt_config.conf'
            for path in (profile, firmware, config):
                path.parent.mkdir(parents=True, exist_ok=True)
            profile.write_text('m8\n')
            original = bytes(range(20)) + bytes(6) + bytes(range(150))
            firmware.write_bytes(original)
            config.write_text('[Adapter]\nAddress = 40:45:da:12:34:56\n'
                              '[11:22:33:44:55:66]\nLinkKey = must-not-copy\n')
            self.assertTrue(bt.prepare(root))
            result = firmware.read_bytes()
            self.assertEqual(result[:20], original[:20])
            self.assertEqual(result[20:26], bytes.fromhex('563412da4540'))
            self.assertEqual(result[26:], original[26:])
            config.unlink()
            self.assertFalse(bt.prepare(root))
            self.assertEqual(result, firmware.read_bytes())

    def test_placeholder_and_multicast_addresses_rejected(self):
        for value in ('', '00:00:00:00:00:00', 'ff:ff:ff:ff:ff:ff',
                      '41:45:da:12:34:56', '40:45:da:12:34:zz'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                bt.parse_address(value)


if __name__ == '__main__':
    unittest.main()
