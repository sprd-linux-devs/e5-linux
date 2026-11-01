"""CPU settings validation, range transitions, rollback and boot persistence."""
import importlib.machinery
import importlib.util
import json
import hashlib
import struct
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[2] / 'openwrt/luci-app-t551m/root/usr/libexec/unisoc-modem/cpu-control'
loader = importlib.machinery.SourceFileLoader('cpu_control', str(SOURCE))
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)


class CPUControlTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.control = module.Control(self.root)
        self.policy = self.control.cpu / 'policy0'
        self.policy.mkdir(parents=True)
        for name, value in {
            'related_cpus':'0 1 2 3 4 5', 'scaling_driver':'sprd-cpufreq-v2',
            'scaling_available_frequencies':'600000 900000 1200000 1500000',
            'scaling_available_governors':'schedutil performance powersave',
            'scaling_governor':'schedutil', 'scaling_min_freq':'600000',
            'scaling_max_freq':'1500000', 'cpuinfo_min_freq':'600000',
            'cpuinfo_max_freq':'1500000', 'cpuinfo_cur_freq':'900000',
            'scaling_voltage_table':'600000 600000\n900000 650000',
        }.items():
            (self.policy / name).write_text(value + '\n')
        self.zone = self.control.thermal / 'thermal_zone7'
        self.zone.mkdir(parents=True)
        (self.zone / 'type').write_text('soc-thmzone')
        (self.zone / 'temp').write_text('45000')
        cdev = self.control.thermal / 'cooling_device0'
        cdev.mkdir()
        (cdev / 'type').write_text('cpufreq-0')
        (cdev / 'cur_state').write_text('0')
        (cdev / 'max_state').write_text('3')
        (self.zone / 'cdev0').symlink_to(cdev, target_is_directory=True)
        (self.zone / 'cdev0_trip_point').write_text('1')
        for index, (kind, temp) in enumerate([('passive',70000),('passive',85000),('critical',110000)]):
            (self.zone / f'trip_point_{index}_type').write_text(kind)
            (self.zone / f'trip_point_{index}_temp').write_text(str(temp))
            (self.zone / f'trip_point_{index}_hyst').write_text('1000')

    def tearDown(self):
        self.tmp.cleanup()

    def test_readback_and_no_custom_voltage(self):
        state=self.control.snapshot()
        self.assertEqual(state['policies'][0]['current'],900000)
        self.assertFalse(state['voltage_writable'])
        self.assertEqual(state['policies'][0]['voltages'][1],{'khz':900000,'uv':650000})
        self.assertFalse(state['zones'][0]['trips'][2]['writable'])
        self.assertFalse(state['zones'][0]['trips'][0]['throttles_cpu'])
        self.assertTrue(state['zones'][0]['trips'][1]['throttles_cpu'])

    def test_thermal_cap_does_not_replace_saved_request(self):
        (self.policy / 'scaling_max_freq').write_text('900000')
        (self.policy / 'scaling_requested_max_freq').write_text('1500000')
        state = self.control.snapshot()
        self.assertEqual(state['policies'][0]['max'], 1500000)
        self.assertEqual(state['policies'][0]['effective_max'], 900000)
        self.control.set_item('persist', True)
        self.assertEqual(json.loads(self.control.config.read_text())['policies'][0]['max'], 1500000)
        self.control.write(self.policy / 'scaling_max_freq', 1500000)

    def test_hotplug_preserves_offline_cluster_frequency_profile(self):
        self.control.set_item('persist', True)
        saved = json.loads(self.control.config.read_text())
        (self.policy / 'affected_cpus').write_text('')
        state = self.control.snapshot()
        self.assertFalse(state['policies'][0]['writable'])
        self.assertEqual(state['policies'][0]['cpus'], '0 1 2 3 4 5')
        # Applying thermal/persistence settings cannot erase offline requests.
        self.control.apply({}, True)
        self.assertEqual(json.loads(self.control.config.read_text())['policies'], saved['policies'])
        with self.assertRaisesRegex(ValueError, 'offline'):
            self.control.apply({'policies':[{'id':'policy0','min':600000}]})

    def test_all_validation_before_writes(self):
        before=self.control.settings(self.control.snapshot())
        for changes in [
            {'policies':[{'id':'policy0','max':1230000}]},
            {'policies':[{'id':'policy0','min':1500000,'max':600000}]},
            {'policies':[{'id':'policy0','governor':'schedutil;reboot'}]},
            {'policies':[{'id':'../../etc/passwd','max':600000}]},
            {'policies':[{'id':'policy0','voltage':500000}]},
            {'policies':[{'id':'policy0','min':True}]},
            {'policies':[{'id':'policy0','max':900000}], 'thermal':[{'zone':'soc-thmzone','trip':2,'temp':90000}]},
            {'thermal':[{'zone':'soc-thmzone','trip':0,'temp':90000}]},
            {'thermal':[{'zone':'soc-thmzone','trip':0,'temp':39000}]},
            {'thermal':[{'zone':'soc-thmzone','trip':1,'temp':105000}]},
        ]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.control.apply(changes)
            self.assertEqual(self.control.settings(self.control.snapshot()),before)

    def test_crossing_ranges(self):
        self.control.apply({'policies':[{'id':'policy0','min':600000,'max':900000}]})
        original=self.control.write
        def checked(path,value):
            if path.name=='scaling_min_freq':
                self.assertLessEqual(int(value),int((self.policy/'scaling_max_freq').read_text()))
            if path.name=='scaling_max_freq':
                self.assertGreaterEqual(int(value),int((self.policy/'scaling_min_freq').read_text()))
            original(path,value)
        self.control.write=checked
        self.control.apply({'policies':[{'id':'policy0','min':1200000,'max':1500000}]})
        self.control.apply({'policies':[{'id':'policy0','min':600000,'max':900000}]})

    def test_write_failure_rolls_back(self):
        initial=self.control.settings(self.control.snapshot())
        original=self.control.write
        def reject(path,value):
            if path.name=='scaling_governor' and value=='performance':
                raise OSError('Firmware rejected change')
            original(path,value)
        self.control.write=reject
        with self.assertRaises(OSError):
            self.control.apply({'policies':[{'id':'policy0','min':900000,'max':1200000,'governor':'performance'}]},True)
        self.assertEqual(self.control.settings(self.control.snapshot()),initial)
        self.assertFalse(self.control.config.exists())

    def test_delayed_kernel_readback(self):
        with patch.object(module, 'read', side_effect=['1500000', '1500000', '900000']):
            self.control.write(self.policy / 'scaling_max_freq', 900000)
        with patch.object(module, 'read', return_value='1500000'), \
             patch.object(module.time, 'monotonic', side_effect=[0, 1]):
            with self.assertRaisesRegex(ValueError, 'Kernel did not accept'):
                self.control.write(self.policy / 'scaling_max_freq', 900000)

    def test_save_restore_and_rejected_boot(self):
        initial=self.control.settings(self.control.snapshot())
        self.control.set_item('policy0_max','900000')
        self.assertFalse(self.control.config.exists())
        self.control.set_item('persist',True)
        saved=json.loads(self.control.config.read_text())
        self.assertEqual(saved['policies'][0]['max'],900000)
        self.control.set_item('thermal_zone7_trip0',60)
        self.assertEqual(json.loads(self.control.config.read_text())['thermal'][0]['temp'],60000)
        self.control.set_item('reset',None)
        self.assertEqual(self.control.settings(self.control.snapshot()),initial)
        self.assertFalse(self.control.config.exists())
        saved['policies'][0]['cpus']='0 1'
        module.atomic_json(self.control.config,saved)
        with self.assertRaises(ValueError):
            self.control.boot()
        self.assertFalse(self.control.config.exists())
        self.assertTrue(self.control.config.with_suffix('.rejected.json').exists())
        self.assertIn('topology',module.read(self.control.runtime/'boot-error'))

    def test_unbound_thermal_zone_is_not_editable(self):
        (self.zone/'cdev0').unlink()
        self.assertFalse(self.control.snapshot()['zones'][0]['trips'][0]['writable'])
        with self.assertRaises(ValueError):
            self.control.set_item('thermal_zone7_trip0',60)

    def enable_voltage(self):
        (self.policy / 'scaling_voltage_domain').write_text('0')
        (self.policy / 'scaling_voltage_offset').write_text('0')
        self.control.runtime.mkdir(parents=True, exist_ok=True)
        (self.control.runtime / module.VOLTAGE_CAPABILITY_CACHE).write_text('1')

    def test_voltage_is_saved_for_boot_and_does_not_fake_readback(self):
        self.enable_voltage()
        result = self.control.set_item('policy0_voltage_next', '-3125')
        self.assertTrue(result['voltage_reboot_required'])
        self.assertEqual(result['policies'][0]['voltage_next'], -3125)
        self.assertEqual(result['policies'][0]['voltage_offset'], 0)
        self.assertEqual(result['policies'][0]['voltages'][0]['uv'], 600000)
        self.assertFalse(self.control.config.exists())
        self.control.set_item('reset', None)
        self.assertEqual(self.control.voltage_profile(), [0, 0, 0])

    def test_voltage_bounds_and_unknown_firmware_rejected_before_writes(self):
        self.enable_voltage()
        for value in [True, -51000, 26000, -3000, '3125', None]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.control.apply({'policies':[{'id':'policy0','max':900000,'voltage_next':value}]})
            self.assertEqual(module.read(self.policy/'scaling_max_freq'), '1500000')
        (self.control.runtime / module.VOLTAGE_CAPABILITY_CACHE).write_text('0')
        with self.assertRaisesRegex(ValueError, 'unavailable'):
            self.control.set_item('policy0_voltage_next', '-3125')
        self.assertFalse(self.control.voltage_config.exists())

    def test_voltage_save_failure_rolls_back_live_limits_and_both_profiles(self):
        self.enable_voltage()
        original = module.atomic_json
        def fail_after_replace(path, data):
            original(path, data)
            if path == self.control.voltage_config:
                raise OSError('Simulated directory fsync failure')
        with patch.object(module, 'atomic_json', side_effect=fail_after_replace):
            with self.assertRaisesRegex(OSError, 'fsync'):
                self.control.apply({'policies':[{'id':'policy0','max':900000,'voltage_next':-3125}]}, True)
        self.assertEqual(module.read(self.policy/'scaling_max_freq'), '1500000')
        self.assertFalse(self.control.config.exists())
        self.assertFalse(self.control.voltage_config.exists())

    def fake_boot(self):
        release = self.root / 'proc/sys/kernel/osrelease'
        release.parent.mkdir(parents=True, exist_ok=True)
        release.write_text('test')
        driver = self.root / 'lib/modules/test/sprd-cpufreq-v2-driver.ko'
        driver.parent.mkdir(parents=True, exist_ok=True)
        driver.touch()
        hidden = self.policy.with_name('hidden')
        self.policy.rename(hidden)
        def load(args, **kwargs):
            hidden.rename(self.policy)
            return None
        return patch.object(module.subprocess, 'run', side_effect=load)

    def test_boot_arms_before_driver_load_and_shutdown_disarms(self):
        self.enable_voltage()
        self.control.set_item('policy0_voltage_next', '-3125')
        with self.fake_boot() as run:
            self.control.boot()
            self.assertEqual(run.call_args.args[0][-1], 'voltage_offset_uv=-3125,0,0')
        self.assertTrue(self.control.voltage_armed.exists())
        self.control.disarm_voltage()
        self.assertFalse(self.control.voltage_armed.exists())

    def test_unclean_boot_disarms_saved_voltage(self):
        self.enable_voltage()
        self.control.set_item('policy0_voltage_next', '-3125')
        module.atomic_json(self.control.voltage_armed, {'offsets':[-3125,0,0]})
        with self.fake_boot() as run:
            state = self.control.boot()
            self.assertEqual(run.call_args.args[0][-1], 'voltage_offset_uv=0,0,0')
        self.assertIn('Unclean', state['voltage_error'])
        self.assertFalse(self.control.voltage_config.exists())
        self.assertTrue(self.control.voltage_config.with_suffix('.rejected.json').exists())
        self.assertFalse(self.control.voltage_armed.exists())

    def test_charger_boot_uses_factory_voltage_without_erasing_profile(self):
        self.enable_voltage()
        self.control.set_item('policy0_voltage_next', '-3125')
        path = self.root / 'sys/firmware/devicetree/base/chosen/bootargs'
        path.parent.mkdir(parents=True)
        path.write_text('sprdboot.mode=charger\0')
        with self.fake_boot() as run:
            self.control.boot()
            self.assertEqual(run.call_args.args[0][-1], 'voltage_offset_uv=0,0,0')
        self.assertEqual(self.control.voltage_profile(), [-3125,0,0])
        self.assertFalse(self.control.voltage_armed.exists())


class VoltageFirmwareTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.control = module.Control(self.root)
        self.compatible = self.root / 'sys/firmware/devicetree/base/compatible'
        self.compatible.parent.mkdir(parents=True)
        self.compatible.write_bytes(b'sprd,ums512-base\0sprd,ums9621\0')
        for slot, dev in [('a', 'mmcblk0p6'), ('b', 'mmcblk0p7')]:
            path = self.root / 'sys/class/block' / dev / 'uevent'
            path.parent.mkdir(parents=True)
            path.write_text('PARTNAME=sml_' + slot + '\n')
            image = self.root / 'dev' / dev
            image.parent.mkdir(exist_ok=True)
            image.write_bytes(slot.encode() * 1024 * 1024)

    def check_hashes(self, hashes):
        with patch.object(module.hashlib, 'sha256') as sha:
            sha.return_value.hexdigest.side_effect = hashes
            result = self.control.voltage_supported()
            self.assertEqual(sha.call_count, 2)
            self.assertTrue(all(len(call.args[0]) == 1024 * 1024 for call in sha.call_args_list))
            return result

    def lym_fixture(self):
        payload, certificate = b'fixture executable tables' * 32, b'fixture certificate'
        image = bytearray(512 + len(payload) + len(certificate))
        image[:8] = b'DHTB\x01\x00\x00\x00'
        struct.pack_into('<I', image, 0x30, len(payload))
        struct.pack_into('<I', image, 0x50, len(image))
        image[8:40] = hashlib.sha256(payload).digest()
        image[512:] = payload + certificate
        identity = dict(compatible='sprd,ums9621', size=len(image),
                        payload_size=len(payload), sha256=hashlib.sha256(image).hexdigest())
        profile = self.root / 'etc/e5/device-profile'
        profile.parent.mkdir(parents=True)
        profile.write_text('lym10k\n')
        return bytes(image), identity

    def lym_pair(self, a, b):
        for dev, data in [('mmcblk0p6', a), ('mmcblk0p7', b)]:
            (self.root / 'dev' / dev).write_bytes(data)
        (self.control.runtime / module.VOLTAGE_CAPABILITY_CACHE).unlink(missing_ok=True)

    def test_lym_complete_signed_image_accepts_only_unused_tail_differences(self):
        image, identity = self.lym_fixture()
        with patch.dict(module.VERIFIED_SIZED_VOLTAGE_FIRMWARE, lym10k=identity):
            for a, b in ((image, image),
                         (image + bytes(1024 * 1024-len(image)),
                          image + b'\xff' * (1024 * 1024-len(image)))):
                self.lym_pair(a, b)
                self.assertTrue(self.control.voltage_supported())

    def test_lym_header_payload_certificate_and_truncation_are_not_ignored(self):
        image, identity = self.lym_fixture()
        changed = []
        for offset in (0, 4, 0x30, 0x50, 512, len(image)-1):
            data = bytearray(image)
            data[offset] ^= 1
            changed.append(bytes(data))
        changed += [image[:-1], image + bytes(1024 * 1024 + 1 - len(image))]
        with patch.dict(module.VERIFIED_SIZED_VOLTAGE_FIRMWARE, lym10k=identity):
            for bad in changed:
                with self.subTest(length=len(bad)):
                    self.lym_pair(image, bad)
                    self.assertFalse(self.control.voltage_supported())

    def test_lym_known_image_does_not_enable_other_profile_or_soc(self):
        image, identity = self.lym_fixture()
        with patch.dict(module.VERIFIED_SIZED_VOLTAGE_FIRMWARE, lym10k=identity):
            self.lym_pair(image, image)
            (self.root/'etc/e5/device-profile').write_text('t551m\n')
            self.assertFalse(self.control.voltage_supported())
            for compatible in (b'sprd,ums9620\0', b'other,sprd,ums9621\0'):
                self.lym_pair(image, image)
                (self.root/'etc/e5/device-profile').write_text('lym10k\n')
                self.compatible.write_bytes(compatible)
                self.assertFalse(self.control.voltage_supported())

    def test_lym_missing_slot_and_old_negative_cache(self):
        image, identity = self.lym_fixture()
        self.lym_pair(image, image)
        self.control.runtime.mkdir(parents=True)
        (self.control.runtime/'voltage-supported-v6').write_text('0')
        with patch.dict(module.VERIFIED_SIZED_VOLTAGE_FIRMWARE, lym10k=identity):
            self.assertTrue(self.control.voltage_supported())
            (self.control.runtime/module.VOLTAGE_CAPABILITY_CACHE).unlink()
            (self.root/'dev/mmcblk0p7').unlink()
            self.assertFalse(self.control.voltage_supported())

    def test_each_verified_firmware_pair_is_supported(self):
        for digest in module.VERIFIED_VOLTAGE_FIRMWARE:
            with self.subTest(digest=digest):
                (self.control.runtime / module.VOLTAGE_CAPABILITY_CACHE).unlink(missing_ok=True)
                self.assertTrue(self.check_hashes([digest, digest]))

    def test_mixed_verified_slots_are_rejected(self):
        self.assertFalse(self.check_hashes(sorted(module.VERIFIED_VOLTAGE_FIRMWARE)))

    def test_m8_firmware_requires_its_soc_and_matching_slots(self):
        digest = next(iter(module.VERIFIED_UMS9620_VOLTAGE_FIRMWARE))
        self.assertFalse(self.check_hashes([digest, digest]))
        self.compatible.write_bytes(b'sprd,ums512-base\0sprd,ums9620\0')
        (self.control.runtime / module.VOLTAGE_CAPABILITY_CACHE).unlink()
        self.assertTrue(self.check_hashes([digest, digest]))
        (self.control.runtime / module.VOLTAGE_CAPABILITY_CACHE).unlink()
        known = next(iter(module.VERIFIED_VOLTAGE_FIRMWARE))
        self.assertFalse(self.check_hashes([known, known]))

    def test_unknown_or_mismatched_slot_is_rejected(self):
        known = next(iter(module.VERIFIED_VOLTAGE_FIRMWARE))
        for hashes in [('unknown', 'unknown'), (known, 'unknown')]:
            (self.control.runtime / module.VOLTAGE_CAPABILITY_CACHE).unlink(missing_ok=True)
            self.assertFalse(self.check_hashes(hashes))

    def test_missing_slot_is_rejected(self):
        (self.root / 'dev/mmcblk0p7').unlink()
        with patch.object(module.hashlib, 'sha256') as sha:
            sha.return_value.hexdigest.return_value = next(iter(module.VERIFIED_VOLTAGE_FIRMWARE))
            self.assertFalse(self.control.voltage_supported())

    def test_soc_match_is_a_complete_compatible_entry(self):
        self.compatible.write_bytes(b'other,sprd,ums9621\0')
        with patch.object(module.hashlib, 'sha256') as sha:
            self.assertFalse(self.control.voltage_supported())
            sha.assert_not_called()

    def test_old_negative_cache_is_rechecked_and_new_cache_is_used(self):
        self.control.runtime.mkdir(parents=True)
        (self.control.runtime / 'voltage-supported').write_text('0')
        (self.control.runtime / 'voltage-supported-v3').write_text('0')
        (self.control.runtime / 'voltage-supported-v5').write_text('0')
        digest = next(iter(module.VERIFIED_VOLTAGE_FIRMWARE))
        self.assertTrue(self.check_hashes([digest, digest]))
        with patch.object(module.hashlib, 'sha256') as sha:
            self.assertTrue(self.control.voltage_supported())
            sha.assert_not_called()

    def test_t512n_firmware_is_not_accepted_on_ums9620(self):
        digest = 'b0beb84a18b4d823bf62ec1ea36a46b960b5ea0a54433d449d8a007968879075'
        self.assertTrue(self.check_hashes([digest, digest]))
        self.compatible.write_bytes(b'sprd,ums512-base\0sprd,ums9620\0')
        (self.control.runtime / module.VOLTAGE_CAPABILITY_CACHE).unlink()
        self.assertFalse(self.check_hashes([digest, digest]))

    def test_41s_requires_ums9620_and_identical_verified_sml_slots(self):
        digest = 'cdfd5fb2186f00ab18e6aca37ee54053704a1e6252dc415aeed190d6892db71b'
        self.assertFalse(self.check_hashes([digest, digest]))
        self.compatible.write_bytes(b'sprd,ums9620\0')
        (self.control.runtime / module.VOLTAGE_CAPABILITY_CACHE).unlink()
        self.assertTrue(self.check_hashes([digest, digest]))
        (self.control.runtime / module.VOLTAGE_CAPABILITY_CACHE).unlink()
        other = '31425dab4aca8450757ac4207de419d06643b7204776fc7e8da5aab1d68814df'
        self.assertFalse(self.check_hashes([digest, other]))

    def test_k1_requires_ums9620_and_identical_verified_sml_slots(self):
        digest = 'efc2e6cf3a83a1dbbedecbea12673a7320520632b7b3f59c9072276f9b24d5eb'
        self.assertFalse(self.check_hashes([digest, digest]))
        self.compatible.write_bytes(b'sprd,ums9620\0')
        cache = self.control.runtime / module.VOLTAGE_CAPABILITY_CACHE
        cache.unlink()
        self.assertTrue(self.check_hashes([digest, digest]))
        for other in ('8207aa5789cbfc5e0e9520c0c34b15b4ae4048f445f4e48bfb802b394a60f99e',
                      '31425dab4aca8450757ac4207de419d06643b7204776fc7e8da5aab1d68814df'):
            cache.unlink()
            self.assertFalse(self.check_hashes([digest, other]))

    def test_changxing60_ufs_requires_own_matching_sml_and_soc(self):
        digest = 'de9b51aa6381d0af921ae5e1ba6499aff8e99e88c92c53259d62a9106c29553a'
        self.assertFalse(self.check_hashes([digest, digest]))
        self.compatible.write_bytes(b'sprd,ums9620\0')
        cache = self.control.runtime / module.VOLTAGE_CAPABILITY_CACHE
        cache.unlink()
        # Use UFS-style SCSI partition names: no MMC-specific discovery.
        for old, new in (('mmcblk0p6', 'sda6'), ('mmcblk0p7', 'sda7')):
            (self.root / 'dev' / old).rename(self.root / 'dev' / new)
            (self.root / 'sys/class/block' / old).rename(self.root / 'sys/class/block' / new)
        self.assertTrue(self.check_hashes([digest, digest]))
        cache.unlink()
        self.assertFalse(self.check_hashes([digest, 'unknown']))

    def test_y60_both_stock_versions_require_matching_slots_and_ums9620(self):
        first='7755b6ae0282e308eab179710401bfc2a16f86e3658936cdf79ee581fda0a3a9'
        second='355cf12fa6fa336c013ac94ace426bceb094ed5c27b95995e7ba1628c6d0348b'
        self.assertFalse(self.check_hashes([first,first]))
        self.compatible.write_bytes(b'sprd,ums9620\0')
        cache=self.control.runtime/module.VOLTAGE_CAPABILITY_CACHE
        for pair,allowed in (([first,first],True),([second,second],True),
                             ([first,second],False),([first,'unknown'],False)):
            cache.unlink(missing_ok=True)
            self.assertEqual(self.check_hashes(pair),allowed)


if __name__=='__main__':
    unittest.main()
