"""Exercise the E5 permission adapter without AT, NV or device I/O."""
import json
from pathlib import Path
import runpy
import subprocess
import unittest
from unittest.mock import patch

TOP=Path(__file__).resolve().parents[2]
scope=runpy.run_path(str(TOP/'openwrt/luci-app-t551m/root/usr/libexec/unisoc-modem/roaming'))
run=scope['run'];g=run.__globals__

class Roaming(unittest.TestCase):
    def setUp(self):
        self.saved={};self.calls=[];self.state='home'
        def command(args):
            self.calls.append(args)
            if args[0]=='mmcli':return json.dumps({'modem':{'3gpp':{'registration-state':self.state}}})
            if args[:2]==['uci','set']:
                key,value=args[2].split('=',1);self.saved[key]=value
            return ''
        def allowed(slot):return self.saved.get('unisoc_modem.main.allow_roaming'+slot)=='1'
        self.p=patch.dict(g,command=command,selected=lambda:'0',allowed=allowed);self.p.start();self.addCleanup(self.p.stop)

    def test_default_off_and_inactive_sim_has_no_invented_registration(self):
        self.assertEqual(run('get',{'slot':'0'}),dict(ok=1,slot=0,enabled=0,roaming=0,blocked=0))
        self.assertIsNone(run('get',{'slot':'1'})['roaming'])

    def test_save_is_per_sim_not_apn_roaming_protocol(self):
        self.state='roaming'
        self.assertEqual(run('get',{'slot':'0'})['blocked'],1)
        result=run('set',{'slot':'0','enabled':'1'})
        self.assertEqual(result['blocked'],0)
        self.assertEqual(run('get',{'slot':'1'})['enabled'],0)
        self.assertEqual(run('get',{'slot':'0'})['enabled'],1)
        self.assertEqual(self.saved,{'unisoc_modem.main.allow_roaming0':'1'})
        self.assertTrue(any(c[:3]==['ubus','send','mu300.roaming-policy'] for c in self.calls))
        self.assertFalse(any(c[0].startswith('AT') for c in self.calls))

    def test_native_connect_permission_for_selected_slot(self):
        self.assertEqual(run('allow',{}),'0');self.assertEqual(run('policy',{}),'0 0')
        run('set',{'slot':'0','enabled':'1'})
        self.assertEqual(run('allow',{}),'1')

    def test_invalid_values_cannot_write_config(self):
        for slot,enabled in [('2','1'),('0','yes'),('0',True)]:
            with self.assertRaises(ValueError):run('set',{'slot':slot,'enabled':enabled})
        self.assertFalse(self.saved)

    def test_policy_configurable_before_modem_export(self):
        with patch.dict(g,selected=lambda:(_ for _ in ()).throw(OSError())):
            self.assertEqual(run('set',{'slot':'0','enabled':'1'})['enabled'],1)
            self.assertIsNone(run('get',{'slot':'0'})['roaming'])

if __name__=='__main__':unittest.main()
