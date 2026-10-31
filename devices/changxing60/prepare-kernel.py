#!/usr/bin/env python3
"""P720S20 UFS bring-up, using the shared 41S/M8 UMS9620 platform.

The initial probe loads only display/USB; touch and power diagnostics are
explicit make-probe options. No 41S SGM41513 address remap, ST7123 firmware
or AW883xx amplifier is inherited.
"""
from pathlib import Path
import runpy

HERE=Path(__file__).resolve().parent


def apply(kernel):
    kernel=Path(kernel)
    full=runpy.run_path(str(HERE.parent/'common/charger-hardware-full.py'))
    full['restore'](kernel)
    runpy.run_path(str(HERE.parent/'m8/prepare-kernel.py'))['apply'](
        kernel,recipient='changxing60',
        charger_adapter=runpy.run_path(str(HERE/'charger.py'))['apply'])
    for path in ('common/ufs.py','common/display-pipeline.py','common/display-dsi-fifo.py','common/dwc3-sink-start.py',
                 'common/display-bindings.py','common/display-resume-planes.py','changxing60/display-ready.py',
                 'yuanhang41s/display.py','yuanhang41s/spi.py','yuanhang41s/display-imports.py',
                 'changxing60/touch.py','changxing60/spi-timing.py',
                 'changxing60/spi-do-stay.py','changxing60/spi-fifo.py',
                 'changxing60/spi-interval.py','changxing60/spi-rx-clear.py','changxing60/audio.py',
                 'changxing60/audio-dapm.py'):
        runpy.run_path(str(HERE.parent/path))['apply'](kernel)
    # Own DT has the legacy UMP96xx CC controller, the combined UMS9620 PHY
    # and a real BQ boost regulator. Reuse the shared manual/host-sink ABI,
    # without importing the 41S TCPM or its charger register table.
    for path in ('common/dwc3-host-policy.py', 'common/dwc3-host-sink.py'):
        runpy.run_path(str(HERE.parent/path))['apply'](kernel)
    full['apply'](kernel)


if __name__=='__main__':
    import sys
    apply(sys.argv[1])
