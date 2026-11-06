"""LYM-10K board port, retaining factory DT current and display timing."""
from pathlib import Path
import runpy
import subprocess
import sys

HERE = Path(__file__).resolve().parent


def apply(kernel):
    kernel = Path(kernel).resolve()
    if (kernel / 'drivers/power/supply/board-charge-profile.h').exists():
        raise ValueError('Use an independent LYM-10K view, without donor DCP overrides')
    subprocess.run([sys.executable, str(HERE.parent / 't551m/prepare-kernel.py'),
                    str(kernel), '--preserve-board-current', '--base-charger-port'], check=True)
    for name in ('charger', 'touch'):
        runpy.run_path(str(HERE / (name + '.py')))['apply'](kernel)
    # Manual, opt-in data-host / power-sink mode. Keep this board's charger
    # encoding and DT current policy; the common path interlocks local boost.
    runpy.run_path(str(HERE.parent / 'common/musb-host-sink.py'))['apply'](
        kernel, charger='bq2560x')


if __name__ == '__main__':
    apply(sys.argv[1])
