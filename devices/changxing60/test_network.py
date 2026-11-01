"""Full RAM trials must retain normal hotspot routing, unlike a tiny probe."""
from pathlib import Path
import runpy
import unittest

HERE = Path(__file__).resolve().parent
network = runpy.run_path(str(HERE/'prepare-ram-root.py'))['full_network_defaults']


class Network(unittest.TestCase):
    def test_normal_first_boot_and_address_are_retained(self):
        text = network()
        for setting in ("network.lan.ip6assign='64'", "dhcp.lan.start='10'",
                        "dhcp.lan.limit='191'", "dhcp.lan.ra='server'",
                        "dhcp.lan.dhcpv6='server'", "auto_helper='0'",
                        "firewall.$zone.network='wan_6'", "network.wan.apn_auto='1'"):
            self.assertIn(setting, text)
        self.assertIn("network.lan.ipaddr='192.168.9.1/24'", text)
        self.assertNotIn('192.168.92.', text)
        self.assertIn("set network.wan.init_epsbearer='keep'", text)
        self.assertIn("dhcp.usb_host.mac='02:50:00:00:60:02'", text)
        self.assertIn("dhcp.usb_host.tag='cx60probe'", text)
        self.assertIn("dhcp.cx60probe.dhcp_option='3'", text)
        self.assertNotIn('dhcp.usbhost', text)
        self.assertNotIn("dhcp.lan.dhcp_option='3'", text)


if __name__ == '__main__': unittest.main()
