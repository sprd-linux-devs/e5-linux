#!/usr/bin/env python3
"""Version-independent selective startup using private ELF/channel fixtures."""
import errno
import importlib.machinery
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from test_modem_loader import build_host, compiler, fixture

TOP = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader('coldboot', str(TOP/'rootfs/overlay/opt/e5/e5-modem-coldboot'))
spec = importlib.util.spec_from_loader(loader.name, loader)
cold = importlib.util.module_from_spec(spec); loader.exec_module(cold)
CHARGER = 'console=tty0 modem=shutdown sprdboot.mode=charger'


class Policy(unittest.TestCase):
    def test_normal_boot_and_online_cp_unchanged(self):
        with patch.object(cold.os, 'open') as opening:
            self.assertFalse(cold.requires_cold_start('modem=shutdown sprdboot.mode=normal'))
            opening.assert_not_called()
        with patch.object(cold.os, 'open', return_value=42), patch.object(cold.os, 'close') as closing:
            self.assertFalse(cold.requires_cold_start(CHARGER))
            closing.assert_called_once_with(42)

    def test_only_explicitly_offline_charger_boot_is_selected(self):
        for code in (errno.ENODEV, errno.ENOENT):
            with patch.object(cold.os, 'open', side_effect=OSError(code, 'fixture')):
                self.assertTrue(cold.requires_cold_start(CHARGER))
        with patch.object(cold.os, 'open', side_effect=OSError(errno.EBUSY, 'fixture')):
            with self.assertRaisesRegex(ValueError, 'offline'):cold.requires_cold_start(CHARGER)
        with self.assertRaisesRegex(ValueError, 'boot state'):
            cold.requires_cold_start('modem=booting sprdboot.mode=charger')

    def test_normal_boot_does_not_require_a_loader_or_helper(self):
        with patch.object(cold, 'requires_cold_start', return_value=False):
            self.assertEqual(cold.prepare(Path('/nonexistent'), ''), '/vendor/bin/modem_control')


@unittest.skipUnless(compiler(), 'host C compiler unavailable')
class Copy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='e5-loader-test-')
        cls.helper = Path(cls.tmp.name)/'helper'
        build_host(cls.helper)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='e5-coldboot-')
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root/'vendor/bin').mkdir(parents=True)
        self.source = self.root/'vendor/bin/modem_control'
        self.source.write_bytes(fixture()[0])
        self.target = self.root/'tmp/e5-coldboot/modem_control'
        self.addCleanup(patch.stopall)
        patch.object(cold, 'requires_cold_start', return_value=True).start()
        patch.object(cold, 'PATCHER', str(self.helper)).start()

    def test_private_copy_and_source_preserved_across_firmware_variants(self):
        for options in ({}, {'frame':True, 'stack':24}, {'base':0x500000, 'nop':True}):
            data = fixture(**options)[0]
            self.source.write_bytes(data)
            self.assertEqual(cold.prepare(self.root, CHARGER), '/tmp/e5-coldboot/modem_control')
            self.assertEqual(self.source.read_bytes(), data)
            self.assertTrue(self.target.stat().st_mode & 0o111)
            self.assertNotEqual(self.target.read_bytes(), data)

    def test_invalid_abi_keeps_previous_published_copy(self):
        cold.prepare(self.root, CHARGER)
        previous = self.target.read_bytes()
        self.source.write_bytes(b'unknown / invalid binary')
        with self.assertRaisesRegex(ValueError, 'ELF'):cold.prepare(self.root, CHARGER)
        self.assertEqual(self.target.read_bytes(), previous)
        self.assertEqual(list(self.target.parent.glob('.modem_control.*')), [])

    def test_missing_helper_and_timeout_do_not_publish_partial_copy(self):
        cold.prepare(self.root, CHARGER)
        previous = self.target.read_bytes()
        with patch.object(cold, 'PATCHER', str(self.root/'missing')):
            with self.assertRaises(OSError):cold.prepare(self.root, CHARGER)
        with patch.object(cold.subprocess, 'run', side_effect=subprocess.TimeoutExpired('fixture', 15)):
            with self.assertRaises(subprocess.TimeoutExpired):cold.prepare(self.root, CHARGER)
        self.assertEqual(self.target.read_bytes(), previous)
        self.assertEqual(list(self.target.parent.glob('.modem_control.*')), [])

    def test_symlink_staging_rejected(self):
        real = self.root/'elsewhere'; real.mkdir()
        self.target.parent.parent.mkdir()
        self.target.parent.symlink_to(real, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'):cold.prepare(self.root, CHARGER)
        self.assertEqual(list(real.iterdir()), [])


if __name__ == '__main__':unittest.main()
