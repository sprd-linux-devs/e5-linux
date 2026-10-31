#!/usr/bin/env python3
"""Apply shared fixes to a clean, pinned E5 kernel without T551M board patches."""
import argparse
from pathlib import Path
import runpy
import subprocess

SHARED = Path(__file__).resolve().parents[1] / 't551m'
COMMIT = '020b970e351e'


def apply(kernel):
    kernel = Path(kernel)
    head = subprocess.check_output(['git', '-C', str(kernel), 'rev-parse', 'HEAD'], text=True).strip()
    if not head.startswith(COMMIT):
        raise ValueError('Expected E5 kernel ' + COMMIT)
    runpy.run_path(str(SHARED.parent / 'common/display.py'))['apply'](kernel)
    runpy.run_path(str(Path(__file__).with_name('panel-dither.py')))['apply'](kernel)
    runpy.run_path(str(SHARED.parent / 'common/usb-ncm.py'))['apply'](kernel)
    runpy.run_path(str(SHARED.parent / 'common/boot-optimization.py'))['apply'](kernel)
    runpy.run_path(str(SHARED.parent / 'common/power.py'))['apply'](kernel)
    runpy.run_path(str(SHARED.parent / 'common/charger-capabilities.py'))['apply'](kernel)
    runpy.run_path(str(SHARED.parent / 'common/emmc.py'))['apply'](kernel)
    runpy.run_path(str(SHARED.parent / 'common/sd-power.py'))['apply'](kernel)
    runpy.run_path(str(SHARED.parent / 'common/eic.py'))['apply'](kernel)
    runpy.run_path(str(SHARED.parent / 'common/thermal.py'))['apply'](kernel)
    runpy.run_path(str(SHARED.parent / 'common/sipa.py'))['apply'](kernel)
    runpy.run_path(str(SHARED.parent / 'common/fuel-gauge.py'))['apply'](kernel)
    runpy.run_path(str(SHARED.parent / 'common/wifi-sae.py'))['apply'](kernel)
    runpy.run_path(str(SHARED.parent / 'common/wifi-stations.py'))['apply'](kernel)
    runpy.run_path(str(SHARED.parent / 'common/wcn-firmware.py'))['apply'](kernel)
    # A separate checkout is essential: the donor replaces the charger and
    # disables E5's touch firmware and amplifier. Never build E5 from that tree.
    for path in ('drivers/power/supply/bq2560x-charger.c',
                 'drivers/unisoc_platform/sprd_disp/t551m-backlight.h',
                 'drivers/power/supply/board-charge-profile.h'):
        if (kernel / path).exists():
            raise ValueError('T551M board adaptation found; use a clean E5 checkout: ' + path)
    replace_function = runpy.run_path(str(SHARED / 'prepare-kernel.py'))['replace_function']
    runpy.run_path(str(SHARED / 'usb_charger.py'))['apply'](
        kernel, replace_function, restore_board_current=False)
    runpy.run_path(str(SHARED / 'otg.py'))['apply'](kernel)
    runpy.run_path(str(SHARED / 'cpufreq.py'))['apply'](kernel)
    runpy.run_path(str(SHARED / 'wifi.py'))['apply'](kernel)
    runpy.run_path(str(Path(__file__).with_name('charger.py')))['apply'](kernel, replace_function)
    runpy.run_path(str(Path(__file__).resolve().parents[1] / 'common/musb-host-sink.py'))['apply'](kernel, charger='aw32257')
    path = kernel / 'drivers/unisoc_platform/sprdwcn/platform/sysfs.c'
    text = path.read_text()
    marker = 'Default firmware debug log off'
    if marker not in text:
        anchor = '\t\tsysfs_info.armlog_status = 1;\n#endif'
        if text.count(anchor) != 1:
            raise ValueError('Unexpected WCN firmware log default')
        text = text.replace(anchor, anchor + '\n\t/* ' + marker + '; explicitly enable through sysfs. */\n\tsysfs_info.armlog_status = 0;')
        path.write_text(text)
    runpy.run_path(str(SHARED.parent / 'common/power-probe.py'))['apply'](kernel)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kernel', type=Path)
    apply(parser.parse_args().kernel)
