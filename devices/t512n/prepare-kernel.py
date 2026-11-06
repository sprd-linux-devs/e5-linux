#!/usr/bin/env python3
"""Reuse the reviewed UMS9621 handheld port with T512N touch and stock DT policy."""
import argparse
from pathlib import Path
import runpy
import subprocess
import sys

HERE = Path(__file__).resolve().parent


def apply(kernel):
    kernel = Path(kernel).resolve()
    # A private tree avoids carrying the donor board's previous DCP override.
    if (kernel / 'drivers/power/supply/board-charge-profile.h').exists():
        raise ValueError('Use a separate T512N tree without the T551M current override')
    subprocess.run([sys.executable, str(HERE.parent / 't551m/prepare-kernel.py'),
                    str(kernel), '--preserve-board-current', '--base-charger-port'], check=True)
    runpy.run_path(str(HERE / 'charger.py'))['apply'](kernel)
    runpy.run_path(str(HERE / 'touch.py'))['apply'](kernel)
    runpy.run_path(str(HERE / 'display-clock.py'))['apply'](kernel)
    # Opt in after the model's own charger mapping; retain its current/JEITA tables.
    runpy.run_path(str(HERE.parent / 'common/musb-host-sink.py'))['apply'](kernel, charger='bq2560x')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kernel', type=Path)
    apply(parser.parse_args().kernel)
