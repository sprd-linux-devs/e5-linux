#!/usr/bin/env python3
"""Execute both real firmware-selection loops with synthetic recipient files."""
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

TOP=Path(__file__).resolve().parents[2]


class FirmwareRetention(unittest.TestCase):
    def test_partition_and_legacy_image_update_keep_y60_audio_xml(self):
        for mode in ('partition','image'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary)
                files={'lib/firmware/y60-audio_route.xml':b'recipient route',
                       'lib/firmware/y60-audio_pga.xml':b'recipient gains',
                       'lib/firmware/wcnmodem.bin':b'own firmware',
                       'lib/firmware/codec.xml':b'own codec'}
                for name,data in files.items():
                    p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
                if mode=='partition':
                    source=(TOP/'openwrt/device-stage-part-update.sh').read_text()
                    start=source.index('for name in lib/firmware/')
                    loop=source[start:source.index('\ndone',start)+5]
                    script='firmware=\n'+loop+'\ntar -cf retained.tar $firmware\n'
                else:
                    source=(TOP/'openwrt/device-install-image.sh').read_text()
                    start=source.index('for f in lib/firmware/')
                    loop=source[start:source.index('done)',start)+4]
                    script='files=$('+loop+')\ntar -cf retained.tar $files\n'
                result=subprocess.run(['busybox','ash'],input=script,text=True,cwd=root,capture_output=True)
                self.assertEqual(result.returncode,0,result.stderr)
                with tarfile.open(root/'retained.tar') as archive:
                    self.assertEqual(set(archive.getnames()),set(files))
                    for name,data in files.items():self.assertEqual(archive.extractfile(name).read(),data)


if __name__=='__main__':unittest.main()
