#!/usr/bin/env python3
"""Restore vendor charging policy and retain verified SOC across shutdown."""
from pathlib import Path
import subprocess
import tempfile

PATCH = Path(__file__).with_name('fuel-gauge-state.patch')
STOCK_POLICY = Path(__file__).with_name('charger-stock-policy.patch')
SAVE_DIAGNOSTICS = Path(__file__).with_name('fuel-gauge-save-diagnostics.patch')
STOCK_LATCHES = Path(__file__).with_name('fuel-gauge-stock-latches.patch')
CHARGER_LIFETIME = Path(__file__).with_name('charger-lifetime.patch')
CAPACITY_ARITHMETIC = Path(__file__).with_name('charger-capacity-arithmetic.patch')
JEITA_STATE = Path(__file__).with_name('charger-jeita-state.patch')
SET_LATCH = Path(__file__).with_name('fuel-gauge-set-latch.patch')
SAVE_READY = Path(__file__).with_name('fuel-gauge-save-ready.patch')
BOOT_OCV = Path(__file__).with_name('fuel-gauge-boot-ocv.patch')
CAPACITY_REMAP = Path(__file__).with_name('charger-capacity-remap.patch')

# Migrate the former 41S-only insertion in existing prepared caches. This exact
# block is removed only in staging; unknown variants still fail patch checks.
LEGACY_BOOT_OCV = '''\t/* P720S11 stock boot-OCV consistency, sc27xx_fgu +0x1ec. */
\t{
\t\tint live_ocv_mv;
\t\ts64 delta_uv;
\t\tret = sprd_fgu_get_vbat_ocv(data, &live_ocv_mv);
\t\tif (ret)
\t\t\treturn;
\t\tdelta_uv = (s64)pocv_uv - (s64)live_ocv_mv * 1000;
\t\tif (delta_uv > 300000 || delta_uv < -300000) {
\t\t\tdev_warn(data->dev, "Boot calib: stale POCV %d, live OCV %d mV\\n",
\t\t\t\t pocv_uv, live_ocv_mv);
\t\t\treturn;
\t\t}
\t}

'''


def apply(kernel):
    kernel = Path(kernel).resolve()
    patches = (PATCH, STOCK_POLICY, SAVE_DIAGNOSTICS, STOCK_LATCHES,
               CHARGER_LIFETIME, CAPACITY_ARITHMETIC, JEITA_STATE, SET_LATCH, SAVE_READY,
               BOOT_OCV, CAPACITY_REMAP)
    paths = set(line[6:] for patch in patches for line in patch.read_text().splitlines()
                if line.startswith('+++ b/'))
    with tempfile.TemporaryDirectory(prefix='e5-fgu-') as directory:
        stage = Path(directory)
        for name in paths:
            target = stage/name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((kernel/name).read_bytes())
        core = stage/'drivers/power/supply/sprd_fuel_gauge_core.c'
        source = core.read_text()
        if 'P720S11 stock boot-OCV consistency' in source:
            if source.count(LEGACY_BOOT_OCV) != 1:
                raise ValueError('Unrecognized legacy boot-OCV check; source left unchanged')
            core.write_text(source.replace(LEGACY_BOOT_OCV, '', 1))
        args = ['git', 'apply', '--whitespace=nowarn']
        # Unstack already applied patches in reverse order, then validate and
        # apply the complete stack in staging before changing the build tree.
        for patch in reversed(patches):
            if subprocess.run(args + ['--reverse', '--check', str(patch)], cwd=stage,
                              capture_output=True).returncode == 0:
                subprocess.run(args + ['--reverse', str(patch)], cwd=stage, check=True)
        for patch in patches:
            result = subprocess.run(args + ['--check', str(patch)], cwd=stage,
                                    capture_output=True, text=True)
            if result.returncode:
                raise ValueError('Fuel-gauge source differs from supported revision: ' + result.stderr.strip())
            subprocess.run(args + [str(patch)], cwd=stage, check=True)
        for name in paths:
            target = kernel/name
            content = (stage/name).read_bytes()
            if target.read_bytes() != content:
                target.write_bytes(content)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kernel', type=Path)
    apply(parser.parse_args().kernel)
