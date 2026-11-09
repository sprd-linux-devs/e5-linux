"""The DFS adaptation accepts old and WPA3-updated wifi-scripts generators."""
from pathlib import Path
import runpy
import tempfile
import unittest

MODULE = runpy.run_path(str(Path(__file__).parent/'t551m/network-startup.py'))
patch_wifi_capabilities = MODULE['patch_wifi_capabilities']


class GeneratorPatch(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.path=self.root/'usr/share/ucode/wifi/hostapd.uc'
        self.path.parent.mkdir(parents=True)

    def source(self,ciphers=True):
        return ("import {\n\twiphy_info, wiphy_band\n} from 'wifi.common';\n"
                "function device_capabilities(config) {\n"
                "\tlet phy = wiphy_info(config.phy);\n"
                "\tlet band = wiphy_band(phy, config.band);\n"+
                ("\tphy_features.cipher_gcmp256 = WLAN_CIPHER_SUITE_GCMP_256 in (phy.cipher_suites ?? []);\n" if ciphers else '')+
                "}\nfunction generate(config) {\n\tset_device_defaults(config);\n}\n")

    def test_both_layouts_collect_radar_and_frequencies_once(self):
        for ciphers in [True,False]:
            with self.subTest(ciphers=ciphers):
                self.path.write_text(self.source(ciphers))
                patch_wifi_capabilities(self.root)
                text=self.path.read_text()
                self.assertEqual(text.count('phy_features.radar_detect ='),1)
                self.assertEqual(text.count('phy_capabilities.freqs ='),1)
                self.assertEqual(text.count('\tdevice_no_dfs(config);'),1)
                self.assertEqual(text.count('function device_chanlist_band(config)'),1)
                self.assertEqual(text.count('\tdevice_chanlist_band(config);'),1)
                self.assertLess(text.index('\tdevice_chanlist_band(config);'),text.index('\tdevice_no_dfs(config);'))
                self.assertIn('config.channel = 36;',text)
                self.assertNotIn("config.htmode =",text)
                self.assertEqual('cipher_gcmp256' in text,ciphers)
                patch_wifi_capabilities(self.root)
                self.assertEqual(text,self.path.read_text())

    def test_existing_dfs_only_root_gains_band_guard_once(self):
        self.path.write_text(self.source())
        patch_wifi_capabilities(self.root)
        expected=self.path.read_text()
        old=expected.replace(MODULE['CHANLIST_BAND'],'').replace('\tdevice_chanlist_band(config);\n','')
        self.path.write_text(old)
        patch_wifi_capabilities(self.root)
        self.assertEqual(expected,self.path.read_text())
        patch_wifi_capabilities(self.root)
        self.assertEqual(expected,self.path.read_text())

    def test_existing_policy_with_missing_call_is_rejected_without_write(self):
        self.path.write_text(self.source())
        patch_wifi_capabilities(self.root)
        invalid=self.path.read_text().replace('\tdevice_no_dfs(config);\n','')
        self.path.write_text(invalid)
        with self.assertRaises(ValueError):patch_wifi_capabilities(self.root)
        self.assertEqual(invalid,self.path.read_text())

    def test_unrecognized_layout_stays_unchanged(self):
        text=self.source().replace('let band = wiphy_band(phy, config.band);','unknown_band_lookup();')
        self.path.write_text(text)
        with self.assertRaises(ValueError):patch_wifi_capabilities(self.root)
        self.assertEqual(text,self.path.read_text())


if __name__=='__main__':unittest.main()
