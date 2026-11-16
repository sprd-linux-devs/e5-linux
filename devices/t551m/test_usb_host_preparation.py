#!/usr/bin/env python3
"""A cached host patch must not prevent a new peripheral patch being saved."""
import argparse
from pathlib import Path
import runpy
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('kernel', type=Path)
args = parser.parse_args()
module = runpy.run_path(str(Path(__file__).with_name('usb_host.py')))
legacy = subprocess.check_output(
    ['git', '-c', 'safe.directory=' + str(args.kernel), '-C', str(args.kernel),
     'show', 'HEAD:drivers/usb/musb/musb_sprd.c'], text=True)


def peripheral(source):
    at = source.index('static int musb_sprd_otg_start_peripheral(')
    end = source.index('\n#if defined(CONFIG_USB_SPRD_OFFLOAD)', at)
    return source[at:end]


at = legacy.index('struct sprd_usb_udc {')
private = legacy[at:legacy.index('\n};', at) + 4] + '\n\n'
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    folder = root / 'drivers/usb/musb'
    folder.mkdir(parents=True)
    for name in ('musb_core.c', 'musb_gadget.c', 'musb_host.c', 'musb_sprd.c'):
        (folder / name).write_text((args.kernel / 'drivers/usb/musb' / name).read_text())
    module['apply'](root)
    path = folder / 'musb_sprd.c'
    current = path.read_text()
    assert 'musb_start(musb);' in current.split('static int musb_sprd_otg_start_host(', 1)[1]
    # Restore only the old peripheral path. Host initialization is already
    # current, matching a previously built cache rather than a clean tree.
    current = current.replace(peripheral(current), peripheral(legacy), 1)
    current = current.replace('struct musb_reg_info {', private + 'struct musb_reg_info {', 1)
    path.write_text(current)
    module['apply'](root)
    saved = path.read_text()
    assert 'struct sprd_usb_udc' not in saved, 'Peripheral fix was not written to the cache'
    assert module['gadget_udc_api'](saved) == saved
    module['apply'](root)
    assert path.read_text() == saved, 'Repeated preparation changed USB state-machine source'
print('PASS: cached host initialization cannot skip saving a new UDC repair; repeat preparation is stable')
