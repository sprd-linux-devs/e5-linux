#!/usr/bin/env python3
"""Real SML code, relocated/new-version fixtures and incompatible ABI mutations.

Host checker only; no firmware execution, SMC, MMIO or device writes. Supply
SML_TEST_IMAGES as a JSON list of original files outside the repository inputs.
"""
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

HERE=Path(__file__).resolve().parent


class Algorithm(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.exe=Path(cls.tmp.name)/'checker'
        subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror','-fsanitize=undefined',
                        '-fno-sanitize-recover=all',str(HERE/'sml-voltage-check.c'),'-o',str(cls.exe)],check=True)
        cls.images=[Path(p).read_bytes() for p in json.loads(os.environ.get('SML_TEST_IMAGES','[]'))]
        if not cls.images:
            raise unittest.SkipTest('SML_TEST_IMAGES not provided; original firmware fixtures required')
        cls.reports=[]
        for image in cls.images:
            result=cls.call(image)
            if result.returncode:
                raise AssertionError('Original firmware ABI not recognized: '+result.stderr.decode())
            cls.reports.append(json.loads(result.stdout))

    @classmethod
    def call(cls, image):
        return subprocess.run([str(cls.exe),'-'],input=image,capture_output=True,timeout=5)

    @staticmethod
    def checksum(image):
        image=bytearray(image)
        size=struct.unpack_from('<I',image,0x30)[0]
        image[8:40]=hashlib.sha256(image[512:512+size]).digest()
        return image

    def test_all_original_images_recognized_by_linked_algorithm(self):
        for report in self.reports:
            self.assertEqual(report['abi'],'unisoc-dvfs-init-v1')
            self.assertIn(report['decoder_kind'],('loop','unrolled'))

    def test_signing_build_metadata_and_unused_tail_are_not_version_gates(self):
        for image in self.images:
            changed=bytearray(image)
            payload_end=512+struct.unpack_from('<I',changed,0x30)[0]
            signed_end=struct.unpack_from('<I',changed,0x50)[0]
            changed[payload_end:signed_end]=b'\xa5'*(signed_end-payload_end)
            changed+=b'\xff'*17
            self.assertNotEqual(hashlib.sha256(image).digest(),hashlib.sha256(changed).digest())
            self.assertEqual(self.call(changed).returncode,0)

    def test_new_payload_build_and_page_relocation_are_accepted_without_new_hashes(self):
        for image in self.images:
            old_payload=struct.unpack_from('<I',image,0x30)[0]
            old_signed=struct.unpack_from('<I',image,0x50)[0]
            # Relocate all PC-relative code/data by one page. This is a parser
            # fixture, not a runnable image: absolute boot pointers are not run.
            changed=bytearray(image[:512]+bytes(4096)+image[512:])
            struct.pack_into('<I',changed,0x30,old_payload+4096)
            struct.pack_into('<I',changed,0x50,old_signed+4096)
            changed=self.checksum(changed)
            result=self.call(changed)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_truncated_bad_lengths_and_corrupt_payload_are_rejected(self):
        for image in self.images:
            payload=struct.unpack_from('<I',image,0x30)[0]
            bad=[image[:511],image[:512+payload-1],b'not firmware']
            for offset,value in ((0x30,0xffffffff),(0x30,3),(0x50,0xffffffff),(0x50,511)):
                copy=bytearray(image);struct.pack_into('<I',copy,offset,value);bad.append(copy)
            copy=bytearray(image);copy[512]^=1;bad.append(copy)
            for changed in bad:self.assertNotEqual(self.call(changed).returncode,0)

    def test_decoder_selector_or_smc_dispatch_change_rejected_even_with_valid_checksum(self):
        for image,report in zip(self.images,self.reports):
            for offset in (report['decoder'],report['selector']+11*4,report['dispatch']+9*4):
                changed=bytearray(image);changed[512+offset]^=1
                changed=self.checksum(changed)
                self.assertNotEqual(self.call(changed).returncode,0,(report,offset))

    def test_broken_cpu_sram_link_rejected_with_valid_checksum(self):
        for image,report in zip(self.images,self.reports):
            payload=image[512:512+struct.unpack_from('<I',image,0x30)[0]]
            found=False
            for offset in range(12,len(payload)-4,4):
                word=struct.unpack_from('<I',payload,offset)[0]
                if word&0xfc000000!=0x94000000:continue
                imm=word&0x3ffffff
                if imm&(1<<25):imm-=1<<26
                if offset+imm*4!=report['selector']:continue
                if struct.unpack_from('<I',payload,offset-4)[0]!=0x9100c260:continue
                changed=bytearray(image)
                struct.pack_into('<I',changed,512+offset,word+1)  # branch to wrong routine entry
                changed=self.checksum(changed)
                self.assertNotEqual(self.call(changed).returncode,0)
                found=True;break
            self.assertTrue(found,'No actual paired adjustment call tested')

    def test_ambiguous_duplicate_arithmetic_is_not_guessed(self):
        for image,report in zip(self.images,self.reports):
            payload=struct.unpack_from('<I',image,0x30)[0]
            signed=struct.unpack_from('<I',image,0x50)[0]
            routine=image[512+report['selector']:512+report['selector']+108]
            changed=bytearray(image[:512+payload]+routine+image[512+payload:])
            struct.pack_into('<I',changed,0x30,payload+len(routine))
            struct.pack_into('<I',changed,0x50,signed+len(routine))
            self.assertNotEqual(self.call(self.checksum(changed)).returncode,0)


if __name__=='__main__':unittest.main()
