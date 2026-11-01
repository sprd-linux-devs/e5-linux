#!/usr/bin/env python3
"""Prepare the shared UMS9620 platform, then this board's actual peripherals.

Use the existing source/object workspace; do not clone another kernel tree.
The source tree must start at the pinned base expected by devices/m8.
"""
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent


def apply(kernel):
    kernel = Path(kernel)
    full = runpy.run_path(str(HERE.parent / 'common/charger-hardware-full.py'))
    # Undo our final policy before replaying the common FGU patch stack.
    full['restore'](kernel)
    runpy.run_path(str(HERE.parent / 'm8/prepare-kernel.py'))['apply'](kernel, recipient='yuanhang41s')
    # Data/device and externally powered host can start without enabling boost.
    # Normal OTG still acquires the real DT regulator before sourcing VBUS.
    runpy.run_path(str(HERE.parent / 'common/dwc3-sink-start.py'))['apply'](kernel)
    for name in ('charger', 'display', 'spi', 'touch', 'audio', 'usb-policy', 'host-sink', 'display-imports'):
        runpy.run_path(str(HERE / (name + '.py')))['apply'](kernel)
    full['apply'](kernel)


if __name__ == '__main__':
    import sys
    apply(sys.argv[1])
