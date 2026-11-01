#!/usr/bin/env python3
"""Compare selected public driver code from two extracted Y60 stock backups.

Reads only the named kernel modules, never loads them, never visits NV.
Equal code includes relocation targets; different compiler output is NOT
treated as proof of different runtime behavior.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct


class Elf:
    def __init__(self, data):
        self.data = data
        if (len(data) < 64 or len(data) > 8 << 20 or
                data[:7] != b'\x7fELF\x02\x01\x01'):
            raise ValueError('Expected bounded little-endian ELF64 module')
        if struct.unpack_from('<HH', data, 16) != (1, 183):
            raise ValueError('Expected AArch64 ET_REL module')
        offset = struct.unpack_from('<Q', data, 40)[0]
        size, count, strings = struct.unpack_from('<HHH', data, 58)
        if size != 64 or not 1 <= count <= 4096 or strings >= count:
            raise ValueError('Invalid section table')
        self.span(offset, size * count)
        self.sections = [struct.unpack_from('<IIQQQQIIQQ', data, offset + i * size)
                         for i in range(count)]
        for section in self.sections:
            if section[1] != 8:  # NOBITS has no backing file bytes.
                self.span(section[4], section[5])
        names = self.section(strings)
        self.names = [self.string(names, s[0]) for s in self.sections]
        self.symbols = {}
        self.tables = {}
        for index, section in enumerate(self.sections):
            if section[1] != 2:
                continue
            if section[9] != 24 or section[5] % 24 or section[6] >= count:
                raise ValueError('Invalid symbol table')
            table = []
            names = self.section(section[6])
            for pos in range(0, section[5], 24):
                name, info, _, shndx, value, length = struct.unpack_from(
                    '<IBBHQQ', data, section[4] + pos)
                row = dict(name=self.string(names, name), type=info & 15,
                           section=shndx, offset=value, size=length)
                table.append(row)
                if shndx not in (0, 0xfff1) and row['name']:
                    self.symbols[row['name']] = row
            self.tables[index] = table

    def span(self, offset, length):
        if offset < 0 or length < 0 or offset > len(self.data) - length:
            raise ValueError('ELF data out of bounds')
        return self.data[offset:offset + length]

    @staticmethod
    def string(table, offset):
        end = table.find(b'\0', offset)
        if not 0 <= offset < len(table) or end < 0:
            raise ValueError('Invalid ELF string')
        return table[offset:end].decode('utf-8')

    def section(self, index):
        if not 0 <= index < len(self.sections):
            raise ValueError('Invalid ELF section')
        s = self.sections[index]
        return self.span(s[4], s[5])

    def symbol(self, name):
        if name not in self.symbols:
            raise ValueError('Required stock symbol missing: ' + name)
        s = self.symbols[name]
        if s['type'] not in (1, 2) or not s['size']:
            raise ValueError('Expected sized function/object: ' + name)
        data = self.section(s['section'])
        if s['offset'] > len(data) - s['size']:
            raise ValueError('Symbol outside its section')
        raw = data[s['offset']:s['offset'] + s['size']]
        relocations = []
        for section in self.sections:
            if section[1] != 4 or section[7] != s['section']:
                continue
            if (section[9] != 24 or section[5] % 24 or
                    section[6] not in self.tables):
                raise ValueError('Invalid RELA section')
            table = self.tables[section[6]]
            for pos in range(0, section[5], 24):
                at, info, addend = struct.unpack_from('<QQq', self.data, section[4] + pos)
                if not s['offset'] <= at < s['offset'] + s['size']:
                    continue
                if info >> 32 >= len(table):
                    raise ValueError('Invalid relocation symbol')
                target = table[info >> 32]
                label = target['name']
                if not label and target['type'] == 3:
                    if target['section'] >= len(self.names):
                        raise ValueError('Invalid relocation section symbol')
                    label = self.names[target['section']]
                relocations.append([at - s['offset'], info & 0xffffffff, label, addend])
        identity = raw + json.dumps(relocations, separators=(',', ':')).encode()
        return raw, dict(bytes=len(raw), code_sha256=hashlib.sha256(raw).hexdigest(),
                         relocation_sha256=hashlib.sha256(identity).hexdigest(),
                         external_calls=sorted({r[2] for r in relocations
                                                if r[1] in (282, 283)}))


DRIVERS = {
    'eta6937-charger.ko': (
        'eta6937_charger_probe', 'eta6937_charger_usb_set_property',
        'eta6937_charger_usb_get_property', 'eta6937_charger_enable_otg',
        'eta6937_charger_disable_otg', 'eta6937_charger_otg_work',
        'eta6937_charger_feed_watchdog_work', 'eta6937_charger_feed_watchdog',
        'eta6937_iin_lim2_tbl'),
    'tlsc6540.ko': ('touch_event_thread_handler', 'tlsc6x_tp_reset_active',
                    'tlsc6x_tpd_reset_force', 'tlsc6x_probe', 'tlsc6x_resume_work'),
}


def audit(first, second):
    report = dict(hardware_validated=False, drivers={})
    for filename, names in DRIVERS.items():
        paths = [Path(root) / 'vendor_dlkm_a/lib/modules' / filename
                 for root in (first, second)]
        if any(not path.is_file() or path.stat().st_size > 8 << 20 for path in paths):
            raise ValueError('Expected small extracted stock modules, not a device or image')
        data = [path.read_bytes() for path in paths]
        images = [Elf(blob) for blob in data]
        rows = {}
        for name in names:
            a, b = [image.symbol(name) for image in images]
            row = dict(first=a[1], second=b[1],
                       code_and_relocations_equal=(a[1]['relocation_sha256'] ==
                                                   b[1]['relocation_sha256']))
            if name == 'eta6937_iin_lim2_tbl':
                if len(a[0]) != 32 or len(b[0]) != 32:
                    raise ValueError('Unexpected ETA input current table size')
                row['first_microamps'] = list(struct.unpack('<8I', a[0]))
                row['second_microamps'] = list(struct.unpack('<8I', b[0]))
            rows[name] = row
        report['drivers'][filename] = dict(
            sha256=[hashlib.sha256(blob).hexdigest() for blob in data], symbols=rows)
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('first', type=Path)
    p.add_argument('second', type=Path)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    for root in (args.first, args.second):
        if args.output.resolve().is_relative_to(root.resolve()):
            p.error('Output must be outside the read-only stock input')
    result = audit(args.first, args.second)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({driver: {name: row['code_and_relocations_equal']
                              for name, row in item['symbols'].items()}
                      for driver, item in result['drivers'].items()}, indent=2))
