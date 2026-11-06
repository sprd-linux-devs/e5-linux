"""Production ucode with private sysfs/UCI/RPC fixtures; no hardware writes."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from native_dashboard_fixture import Snapshot, TOP


class Dashboard(unittest.TestCase):
    def test_traffic_ledger_follows_view_or_actual_card_not_legacy_snapshot(self):
        first={'slot':0,'today_used':10,'month_used':20,'remaining':None,'plan_name':'first'}
        second={'slot':1,'today_used':12000000,'month_used':99000000,'remaining':501000000,'plan_name':'second'}
        self.s.write('run/unisoc-modem-traffic/view-sim0.json',json.dumps(first))
        self.s.write('run/unisoc-modem-traffic/view-sim1.json',json.dumps(second))
        self.s.write('run/unisoc-modem-traffic/view.json','{"stale":true}')
        self.s.write('sys/module/sipc_wwan/parameters/card','1')
        self.assertEqual(self.s.run(slot='1')['traffic'],second)
        self.assertEqual(self.s.run(slot='0')['traffic'],first)
        self.assertEqual(self.s.run()['traffic'],second)
        (self.root/'run/unisoc-modem-traffic/view-sim1.json').unlink()
        self.assertIsNone(self.s.run(slot='1')['traffic'])
        self.s.write('sys/module/sipc_wwan/parameters/card','unknown')
        self.assertIsNone(self.s.run()['traffic'])

    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.s=Snapshot(self.root)

    def test_equipment_queries_are_background_and_failed_reads_are_throttled(self):
        # E5's existing dual-SIM backend does not use MU300's sim_slots option.
        config=self.s.config/'unisoc_modem'
        config.write_text(config.read_text().replace(" option sim_slots '2'\n",''))
        self.s.write('proc/sys/kernel/random/boot_id','fixture-boot')
        self.s.write('run/t551m-at2/cmd.sock','socket')
        self.s.write('proc/net/unix','/run/t551m-at2/cmd.sock')
        self.s.run(slot='1')
        job=json.loads((self.root/'spawn.json').read_text())
        self.assertEqual(job['exe'],'/bin/sh')
        self.assertEqual(job['args'],['/usr/libexec/unisoc-modem/dashboard-equipment'])
        self.assertEqual(job['env']['MU300_EQUIPMENT_SLOTS'],'2')
        (self.root/'spawn.json').unlink()
        self.s.write('run/unisoc-modem-equipment/boot_id','fixture-boot')
        attempt=self.s.write('run/unisoc-modem-equipment/attempt','')
        os.utime(attempt,(self.s.now,self.s.now))
        self.s.run(slot='0')
        self.assertFalse((self.root/'spawn.json').exists(),'failed IMEI reads must not query on every page poll')
        os.utime(attempt,(1,1))
        self.s.run(slot='0')
        self.assertTrue((self.root/'spawn.json').exists(),'failed reads should eventually retry')

    def test_dual_equipment_cache_and_boot_isolation(self):
        self.s.write('run/unisoc-modem-equipment/boot_id','fixture-boot')
        self.s.write('run/unisoc-modem-equipment/imei0','866100000000408')
        self.s.write('run/unisoc-modem-equipment/imei1','866100000000409')
        result=self.s.run(slot='1')
        self.assertEqual(result['modem']['imeis'],['866100000000408','866100000000409'])
        self.s.write('run/unisoc-modem-equipment/imei1','ERROR')
        self.assertEqual(self.s.run(slot='1')['modem']['imeis'],['866100000000408',None])
        self.s.write('proc/sys/kernel/random/boot_id','other-boot')
        self.assertEqual(self.s.run()['modem']['imeis'],[None,None])

    def test_snapshot_and_per_sim_isolation(self):
        self.s.write('sys/class/power_supply/battery/capacity','9')
        self.s.write('sys/class/power_supply/battery/status','Charging')
        self.s.write('sys/class/power_supply/battery/voltage_now','3850000')
        self.s.write('run/unisoc-modem-traffic/view-sim1.json','{"sim":1}')
        a=self.s.run(slot='0');b=self.s.run(slot='1')
        self.assertEqual(a['wan']['apn'],'CMIOT5G')
        self.assertEqual(a['power']['capacity'],9)
        self.assertEqual(a['cpu']['total'],100)
        self.assertEqual(a['wifi']['ssid'],'FixtureWiFi')
        self.assertEqual(a['wifi']['up'],1)
        self.assertEqual(a['wan']['device'],'sipa_eth3')
        self.assertEqual(b['wan']['device'],'sipa_eth8')
        for key in ('apn','ip4','ip6','dns','proto'):self.assertIsNone(b['wan'][key],key)
        self.assertEqual(b['wan']['up'],0)
        self.assertEqual(b['traffic'],{'sim':1})

    def test_rates_sum_all_cids_without_cross_card_counting(self):
        for dev,rx in [('sipa_eth0',100),('sipa_eth1',200),('sipa_eth8',300),('sipa_eth15',400)]:
            self.s.write('sys/class/net/'+dev+'/ifindex','10')
            self.s.write('sys/class/net/'+dev+'/statistics/rx_bytes',str(rx))
            self.s.write('sys/class/net/'+dev+'/statistics/tx_bytes','50')
        # Fixture already has CID4 (sipa_eth3).
        a=self.s.run('rates','0');b=self.s.run('rates','1')
        self.assertEqual(a['ts'],123.4)
        self.assertEqual(a['net']['rx'],401)
        self.assertEqual(b['net']['rx'],700)
        self.s.write('sys/class/net/sipa_eth1/statistics/tx_bytes','bad')
        self.assertIsNone(self.s.run('rates','0')['net'])
        self.assertIn('error',self.s.run('rates','../etc'))

    def test_sms_signature_changes_on_atomic_save_without_reading_body(self):
        path=self.s.write('etc/e5-sms/inbox.json','SECRET SMS')
        a=self.s.run('sms_head')
        new=path.with_suffix('.new');new.write_text('SECRET NEW');new.replace(path)
        b=self.s.run('sms_head')
        self.assertNotEqual(a['signature'],b['signature'])
        self.assertNotIn('SECRET',json.dumps(b))

    def test_boot_scope_and_no_private_data(self):
        self.s.write('etc/e5linux/default-boot','linux')
        helper=self.s.write('opt/e5/e5-next-boot','#!/bin/sh\n');helper.chmod(0o755)
        self.s.write('run/e5linux/misc-bc-slot-b-trial.bin','record')
        self.assertTrue(self.s.run('boot')['can_set_default'])
        self.s.write('proc/cmdline','e5.openwrt=test.ext4')
        self.assertFalse(self.s.run('boot')['can_set_default'])
        self.s.write('proc/sys/net/netfilter/nf_conntrack_count','123')
        self.assertEqual(self.s.run()['conns'],123)
        with (self.s.config/'network').open('a') as f:f.write(" option password 'PRIVATE-PASSWORD'\n")
        self.assertNotIn('PRIVATE-PASSWORD',json.dumps(self.s.run()))

    def test_cache_process_lifetime_and_boot_identity(self):
        self.s.write('dev/wwan0at0','port')
        self.assertEqual(self.s.run()['modem']['alive'],1)
        self.s.write('proc/sys/kernel/random/boot_id','other-boot')
        self.assertEqual(self.s.run()['modem']['alive'],0)

    def test_cache_refresh_boundaries_and_existing_owner(self):
        for cage,sage,expected in [(0,0,None),(4,1,'fast'),(5,0,'full'),(5,5,'full')]:
            for name,age in [('cell',cage),('sig',sage)]:
                path=self.s.write('tmp/unisoc-modem/sim0/'+name+'.json','{}')
                os.utime(path,(self.s.now-age,self.s.now-age))
            spawn=self.root/'spawn.json';spawn.unlink(missing_ok=True)
            state=self.s.run('status','0')
            if expected:
                self.assertEqual(json.loads(spawn.read_text())['args'][-1],expected)
                self.assertEqual(state['refreshing'],1 if expected=='full' else 0)
            else:self.assertFalse(spawn.exists())
        self.s.write('tmp/unisoc-modem/sim0/collect.lck/pid','123')
        self.s.write('proc/123/cmdline','').write_bytes(b'/bin/sh\0/usr/libexec/unisoc-modem/cell\0')
        spawn.unlink(missing_ok=True)
        self.assertEqual(self.s.run('status','0')['refreshing'],1)
        self.assertFalse(spawn.exists())
        self.assertIn('error',self.s.run('status','bad'))

    def test_hostapd_associated_only_and_fresh_metric_cache(self):
        self.s.responses['hostapd.wlan0.get_clients']={'clients':{
            '02:AA:BB:CC:DD:01':{'assoc':True},
            '02:aa:bb:cc:dd:02':{'assoc':False},
            'ff:ff:ff:ff:ff:ff':{'assoc':True}}}
        info=self.s.run()['wifi']
        self.assertEqual(info['clients_n'],1)
        self.assertEqual(info['clients'][0]['mac'],'02:aa:bb:cc:dd:01')
        self.s.write('sys/class/net/wlan0/ifindex','5')
        import time
        self.s.write('run/unisoc-wifi-metrics/wlan0-5.json',json.dumps({
            'ts':time.monotonic(),'values':{'02:aa:bb:cc:dd:01':[
                '02:aa:bb:cc:dd:01','-54','433.3 Mbit/s','86.7 Mbit/s','']}}))
        info=self.s.run()['wifi']
        self.assertEqual(info['clients'][0]['signal'],-54)
        self.assertEqual(info['clients'][0]['tx'],'433.3 Mbit/s')
        # Expired optional metrics never turn into a new association.
        self.s.write('run/unisoc-wifi-metrics/wlan0-5.json','{"ts":0,"values":{}}')
        info=self.s.run()['wifi'];self.assertIsNone(info['clients'][0]['signal'])
        self.assertEqual(json.loads((self.root/'spawn.json').read_text())['args'][1],'--kick')

    def test_dns_deduplicates_top_level_v4_v6_and_ignores_inactive_fields(self):
        cases=[
            ({'dns-server':['58.20.127.238','58.20.127.170'],
              'inactive':{'dns-server':['192.0.2.99']}},None,'58.20.127.238, 58.20.127.170'),
            ({'dns-server':['58.20.127.238']},{'dns-server':['58.20.127.238','2001:db8::53','2001:db8::53']},'58.20.127.238, 2001:db8::53'),
            ({'dns-server':[]},{'dns-server':['2001:db8::53']},'2001:db8::53'),
            (None,{'dns-server':['2001:db8::53']},'2001:db8::53'),
            ({},{'inactive':{'dns-server':['192.0.2.99']}},None),
            ({'dns-server':None},{},None)]
        for wan,wan6,expected in cases:
            self.s.responses['network.interface.wan.status']=wan
            self.s.responses['network.interface.wan6.status']=wan6
            self.assertEqual(self.s.run()['wan']['dns'],expected)


if __name__=='__main__':unittest.main()
