#!/usr/bin/env python3
"""Prepare an independent Y60 view of the shared UMS9620 baseline.

Preserve the bootloader-selected original DT/DTBO. No donor battery, panel,
touch firmware, BSP image or M8 userspace audio-volume policy is installed.
"""
from pathlib import Path
import runpy

HERE=Path(__file__).resolve().parent


def apply(kernel):
    kernel=Path(kernel)
    runpy.run_path(str(HERE.parent/'m8/prepare-kernel.py'))['apply'](
        kernel, recipient='y60', charger_adapter=runpy.run_path(str(HERE/'charger.py'))['apply'])
    runpy.run_path(str(HERE/'touch.py'))['apply'](kernel)
    runpy.run_path(str(HERE/'audio.py'))['apply'](kernel)
    # Shared Linux-DRM binding/lifetime fixes, without TI65132B, SPI touch,
    # or the newer phones' board-specific bias/PA initialisation.
    for relative in ('common/display-pipeline.py', 'common/display-dsi-fifo.py',
                     'common/display-bindings.py', 'common/display-resume-planes.py',
                     'common/dwc3-host-policy.py', 'common/dwc3-host-sink.py'):
        runpy.run_path(str(HERE.parent/relative))['apply'](kernel)


if __name__=='__main__':
    import sys
    apply(sys.argv[1])
