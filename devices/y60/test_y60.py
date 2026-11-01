#!/usr/bin/env python3
"""Offline evidence/driver-binding checks; no hardware access or builds."""
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import struct
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
INSPECT = runpy.run_path(str(HERE / 'inspect-stock.py'))
AUDIT = runpy.run_path(str(HERE / 'audit-drivers.py'))
TOUCH = runpy.run_path(str(HERE / 'touch.py'))


def fdt():
    names = b'compatible\0reg\0'
    payload = b'tlsc6x,chsc6540\0'
    block = struct.pack('>I', 1) + b'\0' * 4
    block += struct.pack('>III', 3, len(payload), 0) + payload
    block += b'\0' * (-len(block) % 4)
    block += struct.pack('>IIIIII', 3, 4, 11, 0, 2, 9)
    return (struct.pack('>10I', 0xd00dfeed, 56 + len(block) + len(names),
                        56, 56 + len(block), 40, 17, 16, 0, len(names), len(block)) +
            b'\0' * 16 + block + names)


def elf(external='i2c_smbus_write_byte_data'):
    # Same instruction bytes with a different relocation target MUST compare
    # different: hashing only .text would miss a changed hardware operation.
    shnames = b'\0.text\0.shstrtab\0.symtab\0.strtab\0.rela.text\0'
    names = b'\0probe\0' + external.encode() + b'\0'
    symbols = (b'\0' * 24 + struct.pack('<IBBHQQ', 1, 0x12, 0, 1, 0, 4) +
               struct.pack('<IBBHQQ', 7, 0x12, 0, 0, 0, 0))
    entries = [('', 0, b'', 0, 0, 0),
               ('.text', 1, b'\0\0\0\x94', 0, 0, 0),
               ('.shstrtab', 3, shnames, 0, 0, 0),
               ('.symtab', 2, symbols, 4, 1, 24),
               ('.strtab', 3, names, 0, 0, 0),
               ('.rela.text', 4, struct.pack('<QQq', 0, 2 << 32 | 283, 0), 3, 1, 24)]
    body = b''
    headers = []
    for name, kind, data, link, info, size in entries:
        headers.append(struct.pack('<IIQQQQIIQQ', shnames.index(name.encode() + b'\0'),
                                   kind, 0, 0, 64 + len(body), len(data), link, info, 1, size))
        body += data
    header = struct.pack('<16sHHIQQQIHHHHHH', b'\x7fELF\x02\x01\x01' + b'\0' * 9,
                         1, 183, 1, 0, 0, 64 + len(body), 0, 64, 0, 0, 64, 6, 2)
    return header + body + b''.join(headers)


class InspectionTests(unittest.TestCase):
    def test_boot_selection_ignores_earlier_placeholder(self):
        value=INSPECT['boot_selection'](b'androidboot.dtbo_idx=0\0'
            b'androidboot.dtbo_idx=5 lcd_name=LCD_ILI9488_RUIHENG_HUAXING_MIPI_HVGA '
            b'androidboot.serialno=PRIVATE')
        self.assertEqual(value['reported_dtbo_indices'], [0,5])
        self.assertEqual(value['last_reported_dtbo_index'],5)
        self.assertNotIn('PRIVATE', str(value))
        self.assertFalse(value['live_identity_verified'])

    def test_missing_boot_log_does_not_guess_overlay(self):
        self.assertIsNone(INSPECT['boot_selection'](b'')['last_reported_dtbo_index'])

    def test_zero_cells_are_numeric(self):
        self.assertEqual(INSPECT['display'](struct.pack('>II', 0, 0)), [0, 0])

    def test_reg_with_printable_address_is_numeric(self):
        self.assertEqual(INSPECT['display'](struct.pack('>II', 0, 0x20000000)), [0, 0x20000000])

    def test_strings_and_boolean(self):
        self.assertEqual(INSPECT['display'](b'one\0two\0'), ['one', 'two'])
        self.assertIs(INSPECT['display'](b''), True)

    def test_parse_touch_binding(self):
        nodes = INSPECT['fdt_nodes'](fdt())
        self.assertEqual(nodes['/']['compatible'], b'tlsc6x,chsc6540\0')
        self.assertEqual(nodes['/']['reg'], b'\0' * 4)

    def test_truncated_fdt(self):
        for cut in (0, 39, len(fdt()) - 1):
            with self.subTest(cut=cut), self.assertRaises(ValueError):
                INSPECT['fdt_nodes'](fdt()[:cut])

    def test_invalid_property_bounds(self):
        blob = bytearray(fdt())
        struct.pack_into('>I', blob, 68, 0xffffffff)
        with self.assertRaises(ValueError):
            INSPECT['fdt_nodes'](blob)

    def test_dtbo_bounds(self):
        for blob in (b'', b'\0' * 40,
                     struct.pack('>8I', 0xd7b7ab1e, 64, 32, 32, 2, 32, 4096, 0) + b'\0' * 32):
            with self.assertRaises(ValueError):
                INSPECT['dtbo_entries'](blob)

    def test_reject_output_in_backup_before_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / 'generated'
            with self.assertRaises(ValueError):
                INSPECT['inspect'](root, target)
            self.assertFalse(target.exists())


class ElfTests(unittest.TestCase):
    def test_relocation_targets_affect_identity(self):
        a = AUDIT['Elf'](elf()).symbol('probe')[1]
        b = AUDIT['Elf'](elf('regmap_update_bits_base')).symbol('probe')[1]
        self.assertEqual(a['code_sha256'], b['code_sha256'])
        self.assertNotEqual(a['relocation_sha256'], b['relocation_sha256'])
        self.assertEqual(a['external_calls'], ['i2c_smbus_write_byte_data'])

    def test_same_module_repeatable(self):
        self.assertEqual(AUDIT['Elf'](elf()).symbol('probe'), AUDIT['Elf'](elf()).symbol('probe'))

    def test_wrong_architecture(self):
        blob = bytearray(elf())
        struct.pack_into('<H', blob, 18, 62)
        with self.assertRaises(ValueError):
            AUDIT['Elf'](blob)

    def test_invalid_section_bounds(self):
        blob = bytearray(elf())
        struct.pack_into('<Q', blob, 40, len(blob) + 1)
        with self.assertRaises(ValueError):
            AUDIT['Elf'](blob)

    def test_missing_symbol_fails_explicitly(self):
        with self.assertRaisesRegex(ValueError, 'Required stock symbol missing'):
            AUDIT['Elf'](elf()).symbol('not_present')


class PreparedTouchTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('Y60_TEST_KERNEL'), 'Set Y60_TEST_KERNEL to existing prepared platform source')
    def test_real_source_binding_and_firmware_guards(self):
        source = Path(os.environ['Y60_TEST_KERNEL']) / 'drivers/input/touchscreen/tlsc6x'
        before = {name: (source / name).read_bytes()
                  for name in ('tlsc6x_main.c', 'firmware/tlsc6x_config.h')}
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'drivers/input/touchscreen/tlsc6x'
            (target / 'firmware').mkdir(parents=True)
            for name, data in before.items():
                (target / name).write_bytes(data)
            TOUCH['apply'](Path(tmp))
            first = (target / 'tlsc6x_main.c').read_bytes()
            self.assertEqual(first.count(b'.compatible = "tlsc6x,chsc6540"'), 1)
            TOUCH['apply'](Path(tmp))
            self.assertEqual(first, (target / 'tlsc6x_main.c').read_bytes())
            for macro in ('TLSC_AUTO_UPGRADE', 'TLSC_BUILDIN_BOOT'):
                (target / 'firmware/tlsc6x_config.h').write_bytes(before['firmware/tlsc6x_config.h'] +
                                                               b'\n#define ' + macro.encode() + b'\n')
                with self.assertRaisesRegex(ValueError, 'retain its own touch firmware'):
                    TOUCH['apply'](Path(tmp))
                self.assertEqual(first, (target / 'tlsc6x_main.c').read_bytes())
            (target / 'firmware/tlsc6x_config.h').write_bytes(before['firmware/tlsc6x_config.h'])
            (target / 'tlsc6x_main.c').write_bytes(first.replace(b'buf, 18)', b'buf, 16)'))
            with self.assertRaisesRegex(ValueError, 'touch protocol'):
                TOUCH['apply'](Path(tmp))
        for name, data in before.items():
            self.assertEqual(hashlib.sha256(data).digest(), hashlib.sha256((source / name).read_bytes()).digest())


@unittest.skipUnless(os.environ.get('Y60_STOCK_FIRST') and os.environ.get('Y60_STOCK_SECOND'),
                     'Set Y60_STOCK_FIRST/SECOND to extracted read-only evidence')
class StockEvidenceTests(unittest.TestCase):
    def test_stock_function_comparison_is_reproducible(self):
        value=AUDIT['audit'](os.environ['Y60_STOCK_FIRST'], os.environ['Y60_STOCK_SECOND'])
        self.assertEqual(value,json.loads((HERE/'driver-audit.json').read_text(encoding='utf-8')))

    def test_stock_eta_table_is_not_bq_encoding(self):
        path=Path(os.environ['Y60_STOCK_FIRST'])/'vendor_dlkm_a/lib/modules/eta6937-charger.ko'
        data,_=AUDIT['Elf'](path.read_bytes()).symbol('eta6937_iin_lim2_tbl')
        self.assertEqual(struct.unpack('<8I',data),
                         (300000,500000,800000,1200000,1500000,2000000,3000000,5000000))

    def test_requested_charge_policy_matches_both_selected_stock_batteries(self):
        for revision in ('20240108','other'):
            path=HERE.parents[1]/'work/y60'/revision/'merged-5.dtb'
            if not path.is_file():
                self.skipTest('Selected stock DT evidence is not available locally')
            battery=INSPECT['fdt_nodes'](path.read_bytes())['/battery']
            expected={
                'charge-full-design-microamp-hours':[3050000],
                'constant-charge-voltage-max-microvolt':[4340000],
                'voltage-min-design-microvolt':[3413000],
                'charge-dcp-current-microamp':[11500000,1150000],
                'charge-sdp-current-microamp':[500000,500000],
                'dcp-jeita-temp-table':[1000,1030,0,4400000,1150,1180,700000,4400000,
                                       1450,1420,1150000,4400000,1570,1550,700000,4100000],
            }
            for key,value in expected.items():
                with self.subTest(revision=revision,property=key):
                    self.assertEqual(INSPECT['display'](battery[key]),value)


@unittest.skipUnless(os.environ.get('Y60_TEST_COHORT'), 'Set Y60_TEST_COHORT to the built Y60 delivery directory')
class BuiltKernelTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(os.environ['Y60_TEST_COHORT'])

    def test_complete_module_release_and_native_touch_alias(self):
        release=(self.root/'kernel.release').read_text().strip()
        self.assertIn('-y60-',release)
        modules=list((self.root/'modules').glob('*.ko'))
        self.assertGreater(len(modules),40)
        for path in modules:
            with self.subTest(module=path.name):
                versions=re.findall(rb'\0vermagic=([^\0]*)',path.read_bytes())
                self.assertEqual(len(versions),1)
                self.assertEqual(versions[0].split()[0].decode(),release)
        touch=(self.root/'modules/tlsc6x.ko').read_bytes()
        self.assertTrue(any(b'tlsc6x,chsc6540' in alias for alias in re.findall(rb'\0alias=([^\0]*)',touch)))
        self.assertFalse((self.root/'modules/bq2560x-charger.ko').exists())

    def test_board_charger_config_and_cpu_init_order(self):
        config=(self.root/'config').read_text()
        for line in ('CONFIG_CHARGER_ETA6937_Y60=m','CONFIG_TOUCHSCREEN_TLSC6X=m'):
            self.assertIn(line,config.splitlines())
        for line in ('CONFIG_CHARGER_BQ2560X_SPRD=m','CONFIG_CHARGER_AW32257=m'):
            self.assertNotIn(line,config.splitlines())
        early=(self.root/'module-order.txt').read_text().splitlines()
        self.assertIn('eta6937-charger.ko',early)
        self.assertNotIn('sprd-cpufreq-v2-driver.ko',early)
        self.assertTrue((self.root/'Image').is_file())
        self.assertTrue((self.root/'modules.tar').is_file())

    def test_delivered_cpu_module_exposes_boot_voltage_abi(self):
        config = (self.root/'config').read_text().splitlines()
        self.assertIn('CONFIG_ARM_SPRD_CPUFREQ_V2=m', config)
        self.assertIn('CONFIG_SPRD_SIP_SVC=y', config)
        module = (self.root/'modules/sprd-cpufreq-v2-driver.ko').read_bytes()
        for interface in (b'voltage_offset_uv', b'scaling_voltage_domain',
                          b'scaling_voltage_offset', b'scaling_voltage_table'):
            self.assertIn(interface, module)


if __name__ == '__main__':
    unittest.main()
