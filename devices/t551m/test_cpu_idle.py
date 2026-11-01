"""Shared CPU idle files reach every profile's real UI staging path."""
import json
import os
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch

TOP=Path(__file__).resolve().parents[2]


class CpuIdleStage(unittest.TestCase):
    def test_shared_stage_preserves_explicit_profile_and_installs_rpc(self):
        stage=runpy.run_path(str(TOP/'devices/t551m/ui.py'))['stage']
        real_run=runpy.run_path
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory)
            binary=base/'native-fixture';binary.write_bytes(b'offline native fixture')
            def dependency(path,*args,**kwargs):
                path=Path(path)
                if path.name in ('build-at-client.py','build-at-owner.py','build-sml-voltage.py'):
                    return {'build':lambda:binary}
                if path.name=='stage.py' and path.parent.name=='infoscreen':
                    return {'stage':lambda root:None}
                return real_run(str(path),*args,**kwargs)
            with patch.dict(stage.__globals__,PACKAGES={}), patch.object(runpy,'run_path',side_effect=dependency), patch.dict(os.environ,E5_UI_CACHE=str(base/'cache')):
                for profile in ('e5','t551m','m8','t512n','yuanhang41s','k1','lym10k','changxing60','y60'):
                    with self.subTest(profile=profile):
                        root=base/profile
                        config=root/'etc/unisoc-cpu-idle.json'
                        config.parent.mkdir(parents=True)
                        config.write_text('{"version":1,"enabled":false}\n')
                        network=root/'etc/unisoc-network-performance.json'
                        network.write_text('{"version":1,"algorithm":"bbr"}\n')
                        stage(root,profile)
                        stage(root,profile)
                        checker=root/'usr/libexec/unisoc-modem/sml-voltage-check'
                        self.assertEqual(checker.read_bytes(),binary.read_bytes())
                        self.assertEqual(checker.stat().st_mode&0o777,0o755)
                        self.assertEqual(json.loads(config.read_text()),{'version':1,'enabled':False})
                        self.assertTrue((root/'etc/rc.d/S99unisoc-cpu-idle').is_symlink())
                        self.assertEqual(json.loads(network.read_text()),{'version':1,'algorithm':'bbr'})
                        self.assertTrue((root/'etc/rc.d/S19unisoc-network-performance').is_symlink())
                        for name in ('usr/libexec/unisoc-modem/network-performance','usr/libexec/rpcd/unisoc-network-performance','etc/init.d/unisoc-network-performance'):
                            self.assertEqual((root/name).stat().st_mode&0o777,0o755)
                        for name in ('usr/libexec/unisoc-modem/cpu-idle','usr/libexec/unisoc-modem/cpu-idle.uc','usr/libexec/rpcd/unisoc-cpu-idle','etc/init.d/unisoc-cpu-idle'):
                            self.assertEqual((root/name).stat().st_mode&0o777,0o755)
                        self.assertEqual((root/'usr/libexec/unisoc-modem/cpu-idle.uc').read_bytes(),(TOP/'openwrt/luci-app-t551m/root/usr/libexec/unisoc-modem/cpu-idle.uc').read_bytes().replace(b'\r\n',b'\n'))
                        self.assertIn('/etc/unisoc-cpu-idle.json',(root/'lib/upgrade/keep.d/unisoc-cpu-idle').read_text())
                        self.assertTrue((root/'www/luci-static/resources/mu300/cpu-idle.js').is_file())
                        self.assertIn('unisoc-cpu-idle',json.loads((root/'usr/share/rpcd/acl.d/unisoc-cpu-idle.json').read_text()))


if __name__=='__main__':unittest.main()
