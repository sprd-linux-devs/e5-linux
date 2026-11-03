"""Apply the tracked MM integration to the local verified shell input only."""
from pathlib import Path
import subprocess
import tempfile

TOP=Path(__file__).resolve().parents[2]
base=Path('/home/kano/openwrt-build/base/e5/lib/netifd/proto/modemmanager.sh')
with tempfile.TemporaryDirectory(prefix='e5-roaming-package-') as temporary:
    root=Path(temporary)
    script=root/'files/lib/netifd/proto/modemmanager.sh'
    script.parent.mkdir(parents=True)
    script.write_bytes(base.read_bytes())
    subprocess.run(['patch','--batch','-p1','-i',str(TOP/'openwrt/patches/modemmanager-package-roaming-policy.patch')],cwd=root,check=True)
    subprocess.run(['sh','-n',str(script)],check=True)
    text=script.read_text()
    assert 'allow_roaming=$(/usr/libexec/unisoc-modem/roaming allow)' in text
    assert 'append_param "allow-roaming=${allow_roaming}"' in text
    assert 'AT+CFUN' not in text[text.index('# setup allow-roaming parameter'):text.index('# setup allow-roaming parameter')+650]
    print('PASS: MM package patch applies; shell syntax and native bearer permission retained')
