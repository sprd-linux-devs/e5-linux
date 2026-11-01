"""Y60-only TLSC6540 binding for the existing TLSC6x packet driver.

The two CP23NV3 stock modules read 18 bytes at register 0, with two
six-byte contacts starting at byte 3. GPIO names and TP_MAX_X/Y also
match. This is source preparation, not evidence of a working touchscreen.
No stock firmware blobs or another board's configuration are installed.
"""
from pathlib import Path
import re


def apply(kernel):
    directory = Path(kernel) / 'drivers/input/touchscreen/tlsc6x'
    path = directory / 'tlsc6x_main.c'
    source = path.read_text(encoding='utf-8')
    config = (directory / 'firmware/tlsc6x_config.h').read_text(encoding='utf-8')
    for name in ('TLSC_AUTO_UPGRADE', 'TLSC_BUILDIN_BOOT'):
        if re.search(r'^\s*#\s*define\s+' + name + r'\b', config, re.M):
            raise ValueError('Y60 must retain its own touch firmware: ' + name)
    if re.search(r'^\s*tlsc6x_do_update_ifneed\s*\(', source, re.M):
        raise ValueError('Disable the donor automatic firmware updater first')
    # Fail on a different packet implementation rather than attaching solely
    # because a driver has a similar name. The full binary evidence is in
    # driver-audit.json and README.md; these anchors guard preparation drift.
    for anchor in ('tlsc6x_i2c_read(this_client, buf, 1, buf, 18)',
                   'buf[6 * i + 3]', 'buf[6 * i + 5]',
                   '"tlsc6x,irq-gpio"', '"tlsc6x,reset-gpio"',
                   '"TP_MAX_X"', '"TP_MAX_Y"'):
        if anchor not in source:
            raise ValueError('Review the Y60 touch protocol before rebinding: ' + anchor)
    if '"tlsc6x,chsc6540"' not in source:
        anchor = 'static const struct of_device_id tlsc6x_of_match[] = {'
        if source.count(anchor) != 1:
            raise ValueError('Unexpected TLSC6x match table')
        source = source.replace(anchor, anchor +
            '\n\t{ .compatible = "tlsc6x,chsc6540" },', 1)
    path.write_text(source, encoding='utf-8')
