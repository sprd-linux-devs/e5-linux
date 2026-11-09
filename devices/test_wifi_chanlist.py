"""Run the actual E5 source transform and feed Wi-Fi generator without hardware.

E5_WIFI_TEST_IMAGE selects an existing ARM64 OpenWrt Docker image. Only a
temporary container and small synthetic fixtures are used, never a prepared root.
"""
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import tempfile
import unittest
import uuid

TOP = Path(__file__).resolve().parents[1]
IMAGE = os.environ.get('E5_WIFI_TEST_IMAGE')
MODULE = runpy.run_path(str(TOP/'devices/t551m/network-startup.py'))


@unittest.skipUnless(IMAGE and shutil.which('docker'), 'E5_WIFI_TEST_IMAGE required')
class GeneratorRuntime(unittest.TestCase):
    def test_real_generator_and_existing_root_migration(self):
        name='e5-wifi-chanlist-'+uuid.uuid4().hex[:8]
        with tempfile.TemporaryDirectory(prefix='e5-wifi-chanlist-') as temporary:
            fixture=Path(temporary)
            (fixture/'cases').mkdir();(fixture/'out').mkdir()
            try:
                subprocess.run(['docker','run','-d','--platform','linux/arm64','--name',name,
                    '-v',str(fixture)+':/fixture','-v',str(TOP/'devices/fixtures/wifi-scripts')+':/fx:ro',
                    IMAGE,'sleep','300'],check=True,stdout=subprocess.DEVNULL)
                def execute(script):
                    r=subprocess.run(['docker','exec',name,'/bin/sh','-ec',script],capture_output=True,text=True,timeout=180)
                    self.assertEqual(r.returncode,0,r.stdout+r.stderr)
                    return r.stdout
                execute('apk update >/dev/null; apk add wifi-scripts >/dev/null 2>&1')
                root=fixture/'root';target=root/'usr/share/ucode/wifi/hostapd.uc'
                target.parent.mkdir(parents=True)
                source=execute('cat /usr/share/ucode/wifi/hostapd.uc')
                target.write_text(source)
                MODULE['patch_wifi_capabilities'](root)
                expected=target.read_bytes()
                MODULE['patch_wifi_capabilities'](root)
                self.assertEqual(expected,target.read_bytes())
                # A retained DFS-only root must migrate through the same entry.
                target.write_text(target.read_text().replace(MODULE['CHANLIST_BAND'],'').replace('\tdevice_chanlist_band(config);\n',''))
                MODULE['patch_wifi_capabilities'](root)
                self.assertEqual(expected,target.read_bytes())
                cases={
                    '2g-stale':('2g','auto','HT20','36 40 44 48',False),
                    '2g-mixed':('2g','auto','HT40',['1 6','36','1-11','1-36'],False),
                    '2g-valid':('2g','auto','HT20','1 6 11',False),
                    '2g-invalid':('2g','auto','HT20',['1-6-11','11-1','0x6','6'],False),
                    '5g-stale':('5g','auto','VHT80','1 6 11',False),
                    '5g-valid':('5g','auto','VHT80','36 40 44 48',False),
                    '5g-dfs':('5g',60,'VHT80',None,False),
                    '5g-radar':('5g',60,'VHT80',None,True),
                }
                for case,(band,channel,mode,channels,radar) in cases.items():
                    freqs=[]
                    for c in (36,40,44,48,52,56,60,64,149,153,157,161,165):
                        f={'freq':5000+5*c}
                        if 52<=c<=64:f.update(radar=True,no_ir=True)
                        freqs.append(f)
                    comb={'maxnum':3,'num_channels':2}
                    if radar:comb['radar_detect_widths']=63
                    wiphy={'extended_features':[0]*16,'cipher_suites':[], 'interface_combinations':[comb],
                        'wiphy_bands':[{'freqs':[{'freq':2407+5*c} for c in range(1,14)],'ht_capa':0x1fe},
                            {'freqs':freqs,'ht_capa':0x1fe,'vht_capa':0x339071b2}]}
                    config={'band':band,'channel':str(channel),'htmode':mode,'country':'CN'}
                    if channels is not None:config['channels']=channels
                    data={'phy':'phy0','phy_suffix':'','vif_phy_suffix':'','config':config,
                        'interfaces':{'ap0':{'config':{'mode':'ap','ssid':'E5-TEST','encryption':'psk2',
                            'key':'12345678','ifname':'wlan0','network':['lan']},'bridge':'br-lan','vlans':{},'stas':{}}}}
                    (fixture/'cases'/f'{case}.wiphy.json').write_text(json.dumps(wiphy))
                    (fixture/'cases'/f'{case}.data.json').write_text(json.dumps(data))
                execute(r'''
cp /fixture/root/usr/share/ucode/wifi/hostapd.uc /usr/share/ucode/wifi/hostapd.uc
mkdir -p /var/lock /var/run /tmp /fake/wifi
sed -e "s/^export function wiphy_info(phy) {/function nl_wiphy_info(phy) {/" /usr/share/ucode/wifi/common.uc > /fake/wifi/common.uc
grep -q "^function nl_wiphy_info" /fake/wifi/common.uc
echo 'export function wiphy_info(phy) { return json(fs.readfile(getenv("FAKE_WIPHY"))); };' >> /fake/wifi/common.uc
for f in /fixture/cases/*.data.json; do
    n=$(basename "$f" .data.json)
    FAKE_DATA=$f FAKE_WIPHY=/fixture/cases/$n.wiphy.json FAKE_CC=CN \
        ucode -L "/fake/*.uc" -L "/usr/share/ucode/*.uc" /fx/run.uc > /fixture/out/$n.conf 2>&1 || { cat /fixture/out/$n.conf; exit 1; }
done
''')
                def conf(case):
                    text=(fixture/'out'/f'{case}.conf').read_text()
                    return text,dict(line.split('=',1) for line in text.splitlines() if '=' in line and not line.startswith('#'))
                for case in ('2g-stale','5g-stale'):
                    _,c=conf(case);self.assertEqual(c['channel'],'0');self.assertNotIn('chanlist',c)
                _,c=conf('2g-mixed');self.assertEqual(c['chanlist'],'1 6 1-11');self.assertIn('HT40',c['ht_capab'])
                text,c=conf('2g-valid');self.assertEqual(c['chanlist'],'1 6 11');self.assertNotIn('channel list:',text)
                _,c=conf('2g-invalid');self.assertEqual(c['chanlist'],'6')
                _,c=conf('5g-valid');self.assertEqual(c['chanlist'],'36 40 44 48');self.assertEqual(c['acs_exclude_dfs'],'1')
                for case,channel in (('5g-dfs','36'),('5g-radar','60')):
                    _,c=conf(case);self.assertEqual(c['channel'],channel);self.assertEqual(c['vht_oper_chwidth'],'1')
            finally:
                subprocess.run(['docker','rm','-f',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=20)


if __name__=='__main__':unittest.main()
