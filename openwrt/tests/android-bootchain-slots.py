"""Run real boot-chain check/sync/rollback on temporary regular files, both slots."""
from pathlib import Path
import os
import struct
import subprocess
import tempfile
import unittest
import zlib

TOP = Path(__file__).resolve().parents[2]


class Chain(unittest.TestCase):
    def exercise(self, android, fault=False, bad_crc=False, y60=False):
        linux = 'b' if android == 'a' else 'a'
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); by = root/'by'; by.mkdir(); stubs = root/'bin'; stubs.mkdir()
            parts = ['uboot','sml','teecfg','trustos','vbmeta']
            if y60: parts += ['dtbo','vendor_boot']
            for part in parts+['boot','l_agdsp']:
                for slot in ('a','b'): (by/(part+'_'+slot)).write_bytes((part+slot).encode()*128)
            (by/'userdata').write_bytes(b'ANDROID DATA')
            bc = bytearray(32); bc[:10] = ('_'+android).encode()+b'\0\0BCAB\x01\x02'
            bc[12], bc[14] = (0x9f,0x1e) if android == 'a' else (0x1e,0x9f)
            struct.pack_into('<I',bc,28,zlib.crc32(bc[:28]))
            if bad_crc: bc[29] ^= 1
            (by/'misc').write_bytes(b'P'*2048+bc+b'Q'*2016)
            before = {p.name:p.read_bytes() for p in by.iterdir()}
            text = (TOP/'tools/android-bootchain.sh').read_text()
            text = text.replace('BY=/dev/block/by-name','BY='+str(by)).replace('BACKUPS=/data/adb/e5-bootchain','BACKUPS='+str(root/'backups'))
            text = text.replace('LOCK=/data/local/tmp/e5-bootchain.lock','LOCK='+str(root/'lock')).replace('[ -b ','[ -f ')
            text = text.replace('size() { blockdev --getsize64 "$1"; }','size() { wc -c < "$1"; }')
            text = text.replace('settle() { sync && blockdev --flushbufs "$1"; }','settle() { :; }')
            text = text.replace('\nsync || fail', '\n: || fail')
            script = root/'chain.sh'; script.write_text(text)
            model = 'CP23NV3' if y60 else 'E5'
            (stubs/'getprop').write_text('#!/bin/sh\ncase "$1" in ro.boot.slot_suffix) echo _'+android+';; ro.product.model|ro.product.device) echo '+model+';; ro.boot.verifiedbootstate) echo orange;; esac\n')
            (stubs/'id').write_text('#!/bin/sh\necho 0\n')
            if fault:
                (stubs/'dd').write_text('#!/bin/sh\ncase " $* " in *" of='+str(by/('trustos_'+linux))+' "*)\n'
                    'if [ ! -e "'+str(root/'fault-fired')+'" ]; then touch "'+str(root/'fault-fired')+'"; /bin/dd "$@"; exit 1; fi;; esac\nexec /bin/dd "$@"\n')
            for p in stubs.iterdir(): p.chmod(0o755)
            env = dict(os.environ, PATH=str(stubs)+':'+os.environ['PATH'])
            result = subprocess.run(['sh',str(script),'check'],env=env,capture_output=True,text=True,timeout=15)
            if bad_crc:
                self.assertNotEqual(result.returncode,0)
                self.assertEqual(before,{p.name:p.read_bytes() for p in by.iterdir()}); return
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('BOOTCHAIN-PLAN '+android+' '+linux,result.stdout)
            self.assertEqual(before,{p.name:p.read_bytes() for p in by.iterdir()})
            result = subprocess.run(['sh',str(script),'sync'],env=env,capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,1 if fault else 0,result.stdout+result.stderr)
            for name, value in before.items():
                expected = before[name[:-1]+android] if not fault and any(name == p+'_'+linux for p in parts) else value
                self.assertEqual((by/name).read_bytes(),expected,name)
            if fault:
                self.assertTrue((root/'fault-fired').exists())
                self.assertIn('previous Linux chain restored',result.stdout)
            else:self.assertIn('BOOTCHAIN-OK '+android+' '+linux,result.stdout)

    def test_both_layouts_preserve_android_boot_misc_and_data(self):
        for slot in ('a','b'):
            with self.subTest(slot=slot): self.exercise(slot)

    def test_write_failure_restores_only_linux_chain(self):
        for slot in ('a','b'):
            with self.subTest(slot=slot): self.exercise(slot,fault=True)

    def test_bad_crc_stops_before_backups_or_writes(self):
        for slot in ('a','b'):
            with self.subTest(slot=slot): self.exercise(slot,bad_crc=True)

    def test_y60_base_fdt_and_overlays_follow_android_in_either_slot(self):
        for slot in ('a', 'b'):
            with self.subTest(slot=slot): self.exercise(slot, y60=True)

    def test_y60_sync_failure_restores_its_whole_cohort(self):
        for slot in ('a', 'b'):
            with self.subTest(slot=slot): self.exercise(slot, y60=True, fault=True)


if __name__ == '__main__': unittest.main()
