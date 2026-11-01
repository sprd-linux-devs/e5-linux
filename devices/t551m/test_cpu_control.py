"""CPU settings validation, range transitions, rollback and boot persistence."""
import importlib.machinery
import importlib.util
import json
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[2] / 'openwrt/luci-app-t551m/root/usr/libexec/unisoc-modem/cpu-control'
loader = importlib.machinery.SourceFileLoader('cpu_control', str(SOURCE))
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)


def fake_voltage_module():
    header = bytearray(64)
    header[:6] = b'\x7fELF\x02\x01'
    header[18:20] = (183).to_bytes(2, 'little')
    return bytes(header) + b'\0parm=voltage_offset_uv:Boot offsets\0'


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
        compat = self.root / 'sys/firmware/devicetree/base/compatible'
        compat.parent.mkdir(parents=True, exist_ok=True)
        compat.write_bytes(b'sprd,ums9620\0')
        release = self.root / 'proc/sys/kernel/osrelease'
        release.parent.mkdir(parents=True, exist_ok=True)
        release.write_text('test')
        driver = self.control.voltage_driver()
        driver.parent.mkdir(parents=True, exist_ok=True)
        driver.write_bytes(fake_voltage_module())
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
        (self.root / 'sys/firmware/devicetree/base/compatible').write_bytes(b'other,soc\0')
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


class VoltageCapabilityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.control = module.Control(self.root)
        self.compatible = self.root/'sys/firmware/devicetree/base/compatible'
        self.compatible.parent.mkdir(parents=True)
        self.compatible.write_bytes(b'sprd,ums9620\0')
        release=self.root/'proc/sys/kernel/osrelease';release.parent.mkdir(parents=True)
        release.write_text('test')
        self.driver=self.control.voltage_driver();self.driver.parent.mkdir(parents=True)
        self.driver.write_bytes(fake_voltage_module())
        checker=self.root/'usr/libexec/unisoc-modem/sml-voltage-check'
        checker.parent.mkdir(parents=True);checker.write_bytes(b'native helper boundary fixture')
        self.images=[b'audited firmware fixture a',b'audited firmware fixture b']
        hashes=frozenset(hashlib.sha256(data).hexdigest() for data in self.images)
        for name in ('VERIFIED_VOLTAGE_FIRMWARE','VERIFIED_UMS9620_VOLTAGE_FIRMWARE'):
            patcher=patch.object(module,name,hashes);patcher.start();self.addCleanup(patcher.stop)
        for slot,device,data in (('a','mmcblk0p6',self.images[0]),('b','mmcblk0p7',self.images[1])):
            node=self.root/'sys/class/block'/device/'uevent';node.parent.mkdir(parents=True)
            node.write_text('PARTNAME=sml_'+slot+'\n')
            node=self.root/'dev'/device;node.parent.mkdir(exist_ok=True);node.write_bytes(data)

    def test_every_adapted_profile_uses_whitelist_fast_path_with_different_slot_versions(self):
        profile=self.root/'etc/e5/device-profile';profile.parent.mkdir(parents=True)
        for name in ('e5','t551m','m8','t512n','yuanhang41s','k1','lym10k','changxing60','y60'):
            profile.write_text(name)
            for soc in ('sprd,ums9620','sprd,ums9621'):
                self.compatible.write_bytes(('sprd,ums512-base\0'+soc+'\0').encode())
                (self.control.runtime/module.VOLTAGE_CAPABILITY_CACHE).unlink(missing_ok=True)
                with patch.object(module.subprocess,'run') as run:
                    self.assertTrue(self.control.voltage_supported(),(name,soc))
                    run.assert_not_called()

    def test_unknown_image_uses_algorithm_result_and_not_a_hash_rejection(self):
        data=b'unlisted version'
        (self.root/'dev/mmcblk0p7').write_bytes(data)
        from types import SimpleNamespace
        with patch.object(module.subprocess,'run',return_value=SimpleNamespace(returncode=0)) as run:
            self.assertTrue(self.control.voltage_supported())
            self.assertEqual(run.call_count,1)
            self.assertEqual(run.call_args.kwargs['input'],data)
            self.assertEqual(run.call_args.args[0][0],str(self.root/'usr/libexec/unisoc-modem/sml-voltage-check'))
        self.assertEqual((self.root/'dev/mmcblk0p7').read_bytes(),data)

    def test_algorithm_rejection_is_explained_without_any_firmware_write(self):
        data=b'incompatible firmware'
        (self.root/'dev/mmcblk0p7').write_bytes(data)
        from types import SimpleNamespace
        with patch.object(module.subprocess,'run',return_value=SimpleNamespace(returncode=1)):
            self.assertFalse(self.control.voltage_supported())
            self.assertEqual(self.control.voltage_unavailable_reason,module.VOLTAGE_ABI_UNKNOWN)
        self.assertEqual((self.root/'dev/mmcblk0p7').read_bytes(),data)

    def test_missing_helper_read_error_and_missing_partition_recover_without_negative_cache(self):
        node=self.root/'dev/mmcblk0p7';data=node.read_bytes();node.unlink()
        self.assertFalse(self.control.voltage_supported())
        self.assertEqual(self.control.voltage_unavailable_reason,module.VOLTAGE_READ_FAILED)
        node.write_bytes(data)
        self.assertTrue(self.control.voltage_supported())
        (self.control.runtime/module.VOLTAGE_CAPABILITY_CACHE).unlink()
        node.write_bytes(b'unknown new version')
        with patch.object(module.subprocess,'run',side_effect=FileNotFoundError('missing helper')):
            self.assertFalse(self.control.voltage_supported())
            self.assertEqual(self.control.voltage_unavailable_reason,module.VOLTAGE_CHECKER_UNAVAILABLE)
        self.assertFalse((self.control.runtime/module.VOLTAGE_CAPABILITY_CACHE).exists())

    def test_old_negative_caches_are_ignored(self):
        self.control.runtime.mkdir(parents=True)
        for name in ('voltage-supported','voltage-supported-v6','voltage-supported-v7','voltage-supported-v8'):
            (self.control.runtime/name).write_text('0')
        self.assertTrue(self.control.voltage_supported())

    def test_driver_becomes_ready_without_a_sticky_rejection(self):
        self.driver.unlink();self.assertFalse(self.control.voltage_supported())
        self.assertEqual(self.control.voltage_unavailable_reason,module.VOLTAGE_DRIVER_UNSUPPORTED)
        self.driver.write_bytes(fake_voltage_module());self.assertTrue(self.control.voltage_supported())

    def test_soc_match_is_a_complete_compatible_entry(self):
        for compatible in (b'other,sprd,ums9620\0',b'other,soc\0',b''):
            self.compatible.write_bytes(compatible);self.assertFalse(self.control.voltage_supported())
            self.assertEqual(self.control.voltage_unavailable_reason,module.VOLTAGE_SOC_UNSUPPORTED)

    def test_old_foreign_arch_or_parameterless_modules_cannot_offer_boot_voltage(self):
        for data in (b'',b'not ELF',fake_voltage_module().replace(b'voltage_offset_uv',b'old_parameter_uv'),
                     fake_voltage_module().replace((183).to_bytes(2,'little'),(62).to_bytes(2,'little'),1)):
            self.driver.write_bytes(data);self.assertFalse(self.control.voltage_supported())


if __name__=='__main__':unittest.main()
