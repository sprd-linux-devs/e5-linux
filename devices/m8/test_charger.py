#!/usr/bin/env python3
"""Compile the M8 charger's revision-aware setters/getters (no device).

The stock Android register dump for the 0x11 unit is REG0B=0x11 and
REG02=0x88 at a 500 mA request: the standard 60 mA/LSB map. The reference
0x12 unit keeps the verified A6 piecewise map. This test applies the real
adapter to a scratch copy of the vendored driver and executes the generated
C functions against a simulated register bus.
"""
from pathlib import Path
import re
import runpy
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
SOURCE = HERE / 'port/drivers/power/supply/bq2560x-charger.c'
apply = runpy.run_path(str(HERE / 'charger.py'))['apply']

PRELUDE = r'''
#include <stdint.h>
#include <stdbool.h>
#include <errno.h>
#include <assert.h>
typedef uint8_t u8;
typedef uint32_t u32;
#define BQ2560X_REG_2 2
#define BQ2560X_REG_ICHG_MASK 63
#define min(a,b) ((a)<(b)?(a):(b))
struct bq2560x_charger_info { u8 chip_rev; u8 reg; int read_error; };
static int bq2560x_read(struct bq2560x_charger_info *info, int addr, u8 *val)
{ (void)addr; if (info->read_error) return -EIO; *val = info->reg; return 0; }
static int bq2560x_update_bits(struct bq2560x_charger_info *info, int addr,
                               u8 mask, u8 val)
{ (void)addr; info->reg = (info->reg & ~mask) | (val & mask); return 0; }
'''


def function(source, name):
    match = re.search(r'static int\s+' + name + r'\([^;{}]*\)\s*\{', source)
    if not match:
        raise AssertionError('Missing function ' + name)
    index = match.end()
    depth = 1
    while depth:
        depth += (source[index] == '{') - (source[index] == '}')
        index += 1
    return source[match.start():index]


def generated(body):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        supply = root / 'drivers/power/supply'
        supply.mkdir(parents=True)
        (supply / 'bq2560x-charger.c').write_bytes(SOURCE.read_bytes())
        (supply / 'Kconfig').write_text('')
        (supply / 'Makefile').write_text('')
        body(root, supply / 'bq2560x-charger.c')
        return (supply / 'bq2560x-charger.c').read_text()


def check(kernel_text):
    assert 'if ((val != 0x11 && val != 0x12) || client->addr != 0x6b)' in kernel_text
    assert 'u8 chip_rev;' in kernel_text
    assert 'info->chip_rev = val;' in kernel_text
    assert 'val == 0x11 ? "M8-0x11" : "M8-0x12"' in kernel_text
    assert 'ma / 60' in kernel_text
    assert '*cur = value * 60 * 1000' in kernel_text


def build_main():
    return PRELUDE + function(kernel_text, 'bq2560x_charger_set_current') + '\n' + \
        function(kernel_text, 'bq2560x_charger_get_current') + r'''
int main(void) {
    struct bq2560x_charger_info info = {.chip_rev = 0x11, .reg = 0};
    u32 current = 0;

    /* 0x11: stock 60 mA/LSB. 500 mA -> code 8; 8 * 60 mA. */
    assert(!bq2560x_charger_set_current(&info, 500000));
    assert((info.reg & BQ2560X_REG_ICHG_MASK) == 8);
    assert(!bq2560x_charger_get_current(&info, &current));
    assert(current == 480000);
    assert(!bq2560x_charger_set_current(&info, 3000000));
    assert((info.reg & BQ2560X_REG_ICHG_MASK) == 50);
    assert(!bq2560x_charger_get_current(&info, &current));
    assert(current == 3000000);
    assert(!bq2560x_charger_set_current(&info, 4000000));
    assert(current <= 4000000);

    /* 0x12: keep the verified A6 piecewise map. */
    info.chip_rev = 0x12;
    info.reg = 0;
    assert(!bq2560x_charger_set_current(&info, 500000));
    assert((info.reg & BQ2560X_REG_ICHG_MASK) == 5);
    assert(!bq2560x_charger_get_current(&info, &current));
    assert(current == 450000);
    assert(!bq2560x_charger_set_current(&info, 3047000));
    assert((info.reg & BQ2560X_REG_ICHG_MASK) == 53);
    assert(!bq2560x_charger_get_current(&info, &current));
    assert(current == 3047000);

    info.read_error = 1;
    current = 123;
    assert(bq2560x_charger_get_current(&info, &current) == -EIO);
    assert(current == 123);
    return 0;
}
'''


kernel_text = generated(lambda root, path: apply(root))
check(kernel_text)

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    (root / 'test.c').write_text(build_main())
    subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function',
                    str(root / 'test.c'), '-o', str(root / 'test')], check=True)
    subprocess.run([str(root / 'test')], check=True)

# K1 and every non-M8 caller keep the original 0x12-only gate.
k1 = generated(lambda root, path: apply(root, max_voltage_mv=4380, board='K1'))
assert 'if (val != 0x12 || client->addr != 0x6b)' in k1
assert '"K1-0x11"' not in k1
assert '"K1-0x12"' in k1
print('M8 charger revisions: 0x11 60 mA/LSB, 0x12 A6, K1 0x12-only, I/O error PASS')
