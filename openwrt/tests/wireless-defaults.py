#!/usr/bin/env python3
"""Run the actual first-boot shell entry with restored/custom wireless UCI."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/'overlay/etc/uci-defaults/91-e5-wireless'
MOCK=r'''#!/usr/bin/python3
import json,os,shlex,sys
from pathlib import Path
p=Path(os.environ['UCI_FIXTURE']);s=json.loads(p.read_text());a=sys.argv[1:]
if a and a[0]=='-q':a=a[1:]
op=a[0];v=s['values']
if op=='get':
 if a[1] not in v:sys.exit(1)
 print(v[a[1]]);sys.exit(0)
if op=='show':
 if s.get('fail')=='show':sys.exit(1)
 for k,x in v.items():
  if k.count('.')==1:print(k+'='+x)
 sys.exit(0)
if op=='changes':
 if s.get('pending'):print('wireless fixture has pending changes')
 sys.exit(0)
if op=='config':
 v.update({'wireless.radio0':'wifi-device','wireless.radio0.disabled':'1',
 'wireless.default_radio0':'wifi-iface','wireless.default_radio0.device':'radio0',
 'wireless.default_radio0.mode':'ap','wireless.default_radio0.disabled':'1',
 'wireless.default_radio0.ssid':'OpenWrt','wireless.default_radio0.encryption':'none'})
elif op in ('batch','set','commit'):
 if s.get('fail')==op:sys.exit(1)
 s['writes'].append(op)
 s['pending']=op!='commit'
 if op=='set':k,x=a[1].split('=',1);v[k]=x
 if op=='batch':
  for line in sys.stdin:
   parts=shlex.split(line)
   if parts:k,x=parts[1].split('=',1);v[k]=x
else:sys.exit(2)
p.write_text(json.dumps(s))
'''


def ap(ssid='Changed WiFi',key='changed-password',encryption='psk2+ccmp',disabled='0',mode='ap'):
    return {'wireless.radio0':'wifi-device','wireless.radio0.disabled':disabled,
            'wireless.default_radio0':'wifi-iface','wireless.default_radio0.device':'radio0',
            'wireless.default_radio0.mode':mode,'wireless.default_radio0.disabled':disabled,
            'wireless.default_radio0.ssid':ssid,'wireless.default_radio0.key':key,
            'wireless.default_radio0.encryption':encryption}


@unittest.skipUnless(sys.platform=='linux','shell fixture requires Linux')
class Defaults(unittest.TestCase):
    def execute(self,values,*,fail=None,stamp=False,settings=True,bad_settings=False,pending=False,retry=False):
        with tempfile.TemporaryDirectory(prefix='e5-wifi-defaults-') as temp:
            root=Path(temp);etc=root/'e5';etc.mkdir();bin_dir=root/'bin';bin_dir.mkdir()
            state=root/'state.json';state.write_text(json.dumps({'values':values,'writes':[],'fail':fail,'pending':pending}))
            for name in ('uci','wifi'):
                file=bin_dir/name;file.write_text(MOCK);file.chmod(0o755)
            marker=etc/'configured.wireless'
            wireless=root/'wireless';wireless.write_text('existing wireless bytes\n' if values else '')
            if stamp:marker.touch()
            if settings:
                (etc/'install.conf').write_text('exit 77\n' if bad_settings else
                    "E5_WIFI_SSID='安装热点'\nE5_WIFI_KEY='factory-password'\nE5_WIFI_CHANNEL=149\n")
            script=root/'91-wireless';script.write_text(SCRIPT.read_text().replace('/etc/e5',str(etc))
                .replace('/etc/config/wireless',str(wireless)))
            env=dict(os.environ,PATH=str(bin_dir)+':'+os.environ['PATH'],UCI_FIXTURE=str(state))
            # Match boot's conditional sourcing; plain set -e would not reliably
            # propagate failures in this context. The script must do it itself.
            result=subprocess.run(['sh','-c','(. "$1") && :','defaults',str(script)],
                                  env=env,capture_output=True,text=True)
            if retry:
                self.assertNotEqual(result.returncode,0)
                changed=json.loads(state.read_text());changed['fail']=None
                state.write_text(json.dumps(changed))
                result=subprocess.run(['sh','-c','(. "$1") && :','defaults',str(script)],
                                      env=env,capture_output=True,text=True)
            return result,json.loads(state.read_text()),marker.exists()

    def preserve(self,values,**kwargs):
        result,state,stamp=self.execute(values,**kwargs)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(state['values'],values);self.assertEqual(state['writes'],[])
        self.assertTrue(stamp)

    def test_existing_without_stamp(self):self.preserve(ap())
    def test_unicode_and_shell_characters(self):self.preserve(ap("中文 ' $ ` 热点",'strange $ ` password'))
    def test_disabled_custom_ap(self):self.preserve(ap(disabled='1'))
    def test_custom_named_openwrt(self):self.preserve(ap(ssid='OpenWrt'))
    def test_open_user_ap(self):self.preserve(ap(ssid='OpenWrt',key='',encryption='none'))
    def test_sta(self):self.preserve(ap(mode='sta'))
    def test_mesh(self):self.preserve(ap(mode='mesh',ssid='',key=''))
    def test_stamp_skips_settings(self):self.preserve(ap(),stamp=True,bad_settings=True)
    def test_custom_skips_settings(self):self.preserve(ap(),bad_settings=True)
    def test_additional_ap(self):
        values=ap(ssid='OpenWrt',key='',encryption='none',disabled='1')
        values.update({'wireless.custom':'wifi-iface','wireless.custom.mode':'ap',
                       'wireless.custom.ssid':'User second AP','wireless.custom.device':'radio0'})
        self.preserve(values)
    def install(self,values,**kwargs):
        result,state,stamp=self.execute(values,**kwargs)
        self.assertEqual(result.returncode,0,result.stderr);self.assertTrue(stamp)
        self.assertEqual(state['values']['wireless.default_radio0.ssid'],'安装热点')
        self.assertEqual(state['values']['wireless.default_radio0.key'],'factory-password')
        self.assertEqual(state['values']['wireless.radio0.disabled'],'0')
        self.assertEqual(state['writes'][-1],'commit')
    def test_absent_radio(self):self.install({})
    def test_empty_radio(self):self.install({'wireless.radio0':'wifi-device'})
    def test_generated_template(self):self.install(ap(ssid='OpenWrt',key='',encryption='none',disabled='1'))
    def test_generated_radio_without_disabled(self):
        values=ap(ssid='OpenWrt',key='',encryption='none',disabled='1')
        del values['wireless.radio0.disabled'];self.install(values)
    def test_pending_custom_changes_are_not_stamped(self):
        values=ap();result,state,stamp=self.execute(values,pending=True)
        self.assertNotEqual(result.returncode,0);self.assertFalse(stamp)
        self.assertEqual(state['values'],values);self.assertEqual(state['writes'],[])
    def test_unreadable_custom_config_is_not_reinitialized(self):
        values=ap();result,state,stamp=self.execute(values,fail='show')
        self.assertNotEqual(result.returncode,0);self.assertFalse(stamp)
        self.assertEqual(state['values'],values);self.assertEqual(state['writes'],[])
    def test_failed_commit_retry_does_not_stamp_staging(self):
        result,state,stamp=self.execute({'wireless.radio0':'wifi-device'},fail='commit',retry=True)
        self.assertNotEqual(result.returncode,0);self.assertFalse(stamp);self.assertTrue(state['pending'])
    def test_invalid_factory_settings_fail(self):
        result,state,stamp=self.execute({'wireless.radio0':'wifi-device'},bad_settings=True)
        self.assertNotEqual(result.returncode,0);self.assertFalse(stamp)
    def test_no_password_stays_disabled(self):
        result,state,stamp=self.execute({'wireless.radio0':'wifi-device'},settings=False)
        self.assertEqual(result.returncode,0,result.stderr);self.assertTrue(stamp)
        self.assertEqual(state['values']['wireless.radio0.disabled'],'1')
    def test_failures_do_not_stamp(self):
        for operation in ('batch','set','commit'):
            with self.subTest(operation=operation):
                result,state,stamp=self.execute({'wireless.radio0':'wifi-device'},fail=operation)
                self.assertNotEqual(result.returncode,0);self.assertFalse(stamp)


if __name__=='__main__':unittest.main()
