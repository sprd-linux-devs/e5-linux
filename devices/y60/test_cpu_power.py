#!/usr/bin/env python3
"""Y60 shared voltage API and boot parameters, independent of SML builds.

The kernel/sysfs and insmod boundary are simulated. Optional original images
exercise that even differing SML versions are never read/written by the backend.
No SMC, hardware voltage or device is accessed.
"""
import hashlib
import json
import os
from pathlib import Path
import runpy
import tempfile
import shutil
import subprocess
import unittest
from unittest.mock import patch

TOP = Path(__file__).resolve().parents[2]
CPU = runpy.run_path(str(TOP/'openwrt/luci-app-t551m/root/usr/libexec/unisoc-modem/cpu-control'))
Control = CPU['Control']


class StockVoltage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.native_tmp=tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.native_tmp.cleanup)
        cls.checker=Path(cls.native_tmp.name)/'checker'
        subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror',
                        str(TOP/'devices/common/sml-voltage-check.c'),'-o',str(cls.checker)],check=True)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.control = Control(self.root)
        self.images = [Path(os.environ[key]).read_bytes() if os.environ.get(key)
                       else bytes([index+1])*1024
                       for index,key in enumerate(('Y60_SML_FIRST','Y60_SML_SECOND'))]
        self.put('etc/e5/device-profile', 'y60\n')
        self.put('sys/firmware/devicetree/base/compatible', b'sprd,ums9620\0')
        self.put('proc/sys/kernel/osrelease', 'test-y60\n')
        fixture = runpy.run_path(str(TOP/'devices/t551m/test_cpu_control.py'))['fake_voltage_module']()
        self.put('lib/modules/test-y60/sprd-cpufreq-v2-driver.ko', fixture)
        self.put('usr/libexec/unisoc-modem/sml-voltage-check', self.checker.read_bytes())
        (self.root/'usr/libexec/unisoc-modem/sml-voltage-check').chmod(0o755)
        # Default synthetic data exercise API boundaries; supplied original SML
        # takes the actual production whitelist or native algorithm path.
        if not os.environ.get('Y60_SML_FIRST'):
            globals_=Control.voltage_supported.__globals__
            p=patch.dict(globals_, VERIFIED_UMS9620_VOLTAGE_FIRMWARE=frozenset(
                hashlib.sha256(image).hexdigest() for image in self.images))
            p.start();self.addCleanup(p.stop)
        for domain, name in enumerate(('policy0', 'policy4', 'policy7')):
            # Synthetic supported limits isolate the firmware/persistence path.
            for key, value in {
                'related_cpus': str(domain), 'scaling_driver': 'sprd-cpufreq-v2',
                'scaling_available_frequencies': '600000 900000',
                'scaling_available_governors': 'schedutil performance',
                'scaling_governor': 'schedutil', 'scaling_min_freq': '600000',
                'scaling_max_freq': '900000', 'scaling_voltage_domain': str(domain),
                'scaling_voltage_offset': '0',
                'scaling_voltage_table': '600000 600000\n900000 650000',
            }.items():
                self.put('sys/devices/system/cpu/cpufreq/'+name+'/'+key, value+'\n')
        self.pair(self.images[0], self.images[0])

    def put(self, name, value):
        path = self.root/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value if isinstance(value, (bytes, bytearray)) else value.encode())

    def pair(self, first, second):
        (self.control.runtime/CPU['VOLTAGE_CAPABILITY_CACHE']).unlink(missing_ok=True)
        for slot, device, image in (('a', 'mmcblk0p6', first), ('b', 'mmcblk0p7', second)):
            self.put('sys/class/block/'+device+'/uevent', 'PARTNAME=sml_'+slot+'\n')
            self.put('dev/'+device, image)

    def test_each_actual_stock_pair_exposes_all_domains_to_both_ui_apis(self):
        for image in self.images:
            with self.subTest(sha256=hashlib.sha256(image).hexdigest()):
                self.pair(image, image)
                before = [image, image]
                state = self.control.snapshot()
                self.assertTrue(state['voltage_boot_writable'])
                self.assertIsNone(state['voltage_unavailable_reason'])
                self.assertEqual([p['voltage_domain'] for p in state['policies']], [0, 1, 2])
                self.assertTrue(all(p['voltage_boot_writable'] for p in state['policies']))
                # Screen's set_item and dashboard's apply share this backend.
                self.control.set_item('policy0_voltage_next', '-3125')
                self.control.apply({'policies': [
                    {'id':'policy4', 'voltage_next':-6250},
                    {'id':'policy7', 'voltage_next':3125}]})
                self.assertEqual(self.control.voltage_profile(), [-3125, -6250, 3125])
                self.assertEqual([p['voltage_offset'] for p in self.control.snapshot()['policies']], [0, 0, 0])
                self.assertEqual([ (self.root/'dev'/d).read_bytes() for d in ('mmcblk0p6','mmcblk0p7')], before)

    def boot(self, mode=''):
        self.put('sys/firmware/devicetree/base/chosen/bootargs', mode+'\0')
        visible = self.control.cpu
        hidden = visible.with_name('hidden-test-policies')
        visible.rename(hidden)
        def load(args, **kwargs):
            self.assertEqual(args[:2], ['insmod', str(self.root/'lib/modules/test-y60/sprd-cpufreq-v2-driver.ko')])
            hidden.rename(visible)
        with patch.object(Control.load_driver.__globals__['subprocess'], 'run', side_effect=load) as run:
            self.control.boot()
            return run.call_args.args[0][-1]

    def test_saved_y60_offsets_reach_driver_only_at_normal_boot(self):
        self.control.apply({'policies':[{'id':'policy4','voltage_next':-6250}]})
        self.assertEqual(self.boot(), 'voltage_offset_uv=0,-6250,0')
        self.assertTrue(self.control.voltage_armed.exists())
        self.control.disarm_voltage()
        self.assertEqual(self.boot('sprdboot.mode=charger'), 'voltage_offset_uv=0,0,0')
        self.assertEqual(self.control.voltage_profile(), [0,-6250,0])
        self.assertFalse(self.control.voltage_armed.exists())

    def test_different_stock_versions_and_unlisted_signature_use_the_same_voltage_abi(self):
        self.pair(self.images[0],self.images[1])
        self.assertTrue(self.control.snapshot()['voltage_boot_writable'])
        if not os.environ.get('Y60_SML_FIRST'):
            self.skipTest('Original SML required for native algorithm fallback')
        import struct
        modified=bytearray(self.images[0])
        payload_end=512+struct.unpack_from('<I',modified,0x30)[0]
        modified[payload_end]^=1  # signature/build variation, DVFS code unchanged
        self.pair(self.images[0],bytes(modified))
        self.assertTrue(self.control.snapshot()['voltage_boot_writable'])
        self.control.set_item('policy0_voltage_next','-3125')
        self.assertEqual(self.control.voltage_profile(),[-3125,0,0])
        # Broken arithmetic is rejected even though its DHTB checksum is valid.
        bad=bytearray(modified);bad[512:]=bytes(len(bad)-512)
        size=struct.unpack_from('<I',bad,0x30)[0]
        bad[8:40]=hashlib.sha256(bad[512:512+size]).digest()
        self.pair(self.images[0],bad)
        self.assertFalse(self.control.snapshot()['voltage_boot_writable'])

    def test_missing_kernel_interface_explains_why_controls_are_hidden(self):
        for file in self.control.cpu.glob('*/scaling_voltage_domain'):
            file.unlink()
        state = self.control.snapshot()
        self.assertTrue(state['available'])
        self.assertFalse(state['voltage_boot_writable'])
        self.assertIn('interface is missing', state['voltage_unavailable_reason'])

    def test_transient_sml_discovery_uses_factory_voltage_and_keeps_pending_profile(self):
        self.control.set_item('policy0_voltage_next','-3125')
        (self.control.runtime/CPU['VOLTAGE_CAPABILITY_CACHE']).unlink()
        data=(self.root/'dev/mmcblk0p7').read_bytes()
        (self.root/'dev/mmcblk0p7').unlink()
        self.assertEqual(self.boot(),'voltage_offset_uv=0,0,0')
        self.assertEqual(self.control.voltage_profile(),[-3125,0,0])
        self.assertFalse(self.control.voltage_armed.exists())
        (self.root/'dev/mmcblk0p7').write_bytes(data)
        self.assertTrue(self.control.snapshot()['voltage_boot_writable'])
        self.assertTrue(self.control.snapshot()['voltage_reboot_required'])

    def test_old_module_uses_factory_init_without_unknown_parameter_or_profile_loss(self):
        self.control.set_item('policy0_voltage_next','-3125')
        driver = self.control.voltage_driver()
        driver.write_bytes(driver.read_bytes().split(b'\0parm=')[0])
        self.assertEqual(self.boot(),str(driver))  # insmod with no offset argument
        self.assertEqual(self.control.voltage_profile(),[-3125,0,0])
        self.assertFalse(self.control.voltage_armed.exists())
        self.assertIn('interface is missing',self.control.snapshot()['voltage_error'])

    def test_interrupted_helper_install_keeps_saved_voltage_for_next_boot(self):
        self.control.set_item('policy0_voltage_next','-3125')
        self.pair(self.images[0],b'unlisted firmware build')
        (self.root/'usr/libexec/unisoc-modem/sml-voltage-check').unlink()
        self.assertEqual(self.boot(),'voltage_offset_uv=0,0,0')
        self.assertEqual(self.control.voltage_profile(),[-3125,0,0])
        self.assertFalse(self.control.voltage_config.with_suffix('.rejected.json').exists())
        self.assertIn('checker is not ready',self.control.snapshot()['voltage_error'])


if __name__ == '__main__':
    unittest.main()
