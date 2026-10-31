#!/usr/bin/env python3
from pathlib import Path
import runpy
import tempfile
import unittest

BOARD = Path(__file__).parent


class Profile(unittest.TestCase):
    def test_early_battery_suppliers_and_symbol_dependencies(self):
        resolver=runpy.run_path(str(BOARD.parent/'common/bringup-probe.py'))['module_order']
        requested=(BOARD/'module-order.txt').read_text().split()
        with tempfile.TemporaryDirectory() as directory:
            modules=Path(directory)
            for name in requested:
                depends='sprd-charger-manager' if name=='ump96xx_fuel_gauge.ko' else ''
                (modules/name).write_bytes(b'\0vermagic=test SMP\0depends='+depends.encode()+b'\0')
            result=resolver(modules,requested,'test')
            for provider,consumer in (('sprd_battery_info.ko','sprd-charger-manager.ko'),
                    ('sprd-charger-manager.ko','ump96xx_fuel_gauge.ko'),
                    ('ump96xx_fuel_gauge.ko','bq2560x-charger.ko')):
                self.assertLess(result.index(provider),result.index(consumer))
            (modules/'ump96xx_fuel_gauge.ko').unlink()
            with self.assertRaisesRegex(ValueError,'ump96xx_fuel_gauge'):
                resolver(modules,requested,'test')

    def test_release_configuration_keeps_platform_and_removes_old_trial_root(self):
        configure=runpy.run_path(str(BOARD/'build-kernel.py'))['config']
        base='CONFIG_SPRD_UMS9620_CLK=y\nCONFIG_PINCTRL_SPRD_QOGIRN6PRO=y\nCONFIG_CMDLINE="rdinit=/init e5.openwrt=old.ext4"\nCONFIG_LOCALVERSION="-m8"\nCONFIG_HOTPLUG_CPU=y\n'
        result=configure(base)
        self.assertIn('CONFIG_LOCALVERSION="-yuanhang41s-bringup1"',result)
        self.assertIn('CONFIG_HOTPLUG_CPU=y',result)
        self.assertIn('CONFIG_CMA_SIZE_MBYTES=64',result)
        self.assertNotIn('e5.openwrt=',result)
        with self.assertRaises(ValueError):configure('CONFIG_SPRD_UMS9621_CLK=y\n')

    def test_vibrator_driver_autoload_is_persistent_and_scoped(self):
        stage = runpy.run_path(str(BOARD / 'stage.py'))['stage_vibrator']
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('etc/e5', 'etc/modules.d'):
                (root / name).mkdir(parents=True)
            marker = root / 'etc/e5/device-profile'
            marker.write_text('yuanhang41s\n')
            modules = root / 'etc/modules.d/41-yuanhang41s'
            modules.write_text('sprd_power_manager\nsprd_wlan_combo\n')
            stage(root); stage(root)
            self.assertEqual(modules.read_text().splitlines(),
                             ['sprd_power_manager','sprd_wlan_combo','sc27xx-vibra'])
            marker.write_text('m8\n')
            with self.assertRaises(ValueError): stage(root)

    def test_bluetooth_autoload_is_persistent_and_keeps_user_name(self):
        stage = runpy.run_path(str(BOARD / 'stage.py'))['stage_bluetooth']
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('etc/e5', 'etc/modules.d', 'etc/bluetooth'):
                (root / name).mkdir(parents=True)
            marker = root / 'etc/e5/device-profile'
            marker.write_text('yuanhang41s\n')
            modules = root / 'etc/modules.d/41-yuanhang41s'
            modules.write_text('wcn_bsp\nsprd_wlan_combo\n')
            config = root / 'etc/bluetooth/main.conf'
            config.write_text('Name = E5\n')
            stage(root)
            stage(root)
            self.assertEqual(modules.read_text().splitlines(),
                             ['wcn_bsp', 'sprd_wlan_combo', 'sprdbt_tty'])
            self.assertEqual(config.read_text(), 'Name = Yuanhang41S\n')
            config.write_text('Name = My headset host\n')
            stage(root)
            self.assertEqual(config.read_text(), 'Name = My headset host\n')
            marker.write_text('m8\n')
            with self.assertRaises(ValueError):
                stage(root)


if __name__ == '__main__':
    unittest.main()
