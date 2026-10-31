#!/usr/bin/env python3
"""Prepare/build K1 using an explicit UMS9620 baseline and shared packaging."""
import argparse
import json
import os
from pathlib import Path
import runpy
import subprocess

HERE = Path(__file__).resolve().parent


def config(base):
    if 'CONFIG_SPRD_UMS9620_CLK=y' not in base or 'CONFIG_PINCTRL_SPRD_QOGIRN6PRO=y' not in base:
        raise ValueError('A tested UMS9620 baseline is required')
    values = {}
    for line in (base + '\n' + (HERE / 'kernel.config').read_text(encoding='utf-8')).splitlines():
        if line.startswith('CONFIG_') and '=' in line:
            key, value = line.split('=', 1)
            values[key] = value
        elif line.startswith('# CONFIG_') and line.endswith(' is not set'):
            values[line[2:-11]] = 'n'
    return ''.join(key + '=' + value + '\n' for key, value in values.items())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('kernel', 'build', 'base-config', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--jobs', type=int, default=8)
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error('--jobs must be positive')
    if os.name == 'nt':
        parser.error('Use Linux/WSL and an explicit K1 source/object workspace')
    kernel, build, out = (p.resolve() for p in (args.kernel, args.build, args.out))
    if len({kernel, build, out}) != 3 or Path('/') in (kernel, build, out):
        parser.error('Source, object and output directories must be distinct')
    wanted = config(args.base_config.read_text(encoding='utf-8'))
    previous = build / '.config'
    if previous.exists() and 'CONFIG_LOCALVERSION="-k1-' not in previous.read_text(encoding='utf-8'):
        parser.error('Object directory belongs to another profile; use a K1 directory')
    runpy.run_path(str(HERE / 'prepare-kernel.py'))['apply'](kernel)
    subprocess.run(['python3',str(HERE.parent/'common/test_power_probe.py'),
                    '--kernel',str(kernel)],check=True)
    for test in ('test_boot_soc.py', 'test_battery_periodic.py', 'test_capacity_remap.py'):
        subprocess.run(['python3', str(HERE.parent/'common'/test), str(kernel)], check=True)
    subprocess.run(['python3', str(HERE.parent / 'common/test_dwc3_host_sink.py')],
                   env=dict(os.environ, E5_TEST_KERNEL=str(kernel)), check=True)
    build.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    previous.write_text(wanted, encoding='utf-8')
    command = ['make', '-C', str(kernel), 'O=' + str(build), 'ARCH=arm64',
               'LLVM=1', 'LLVM_IAS=1', 'CROSS_COMPILE=aarch64-linux-gnu-']
    env = dict(os.environ, LOCALVERSION='')
    subprocess.run(command + ['olddefconfig'], env=env, check=True)
    subprocess.run(command + ['-j' + str(args.jobs), 'Image', 'modules'], env=env, check=True)
    runpy.run_path(str(HERE.parent / 'm8/package-kernel.py'))['package'](build, out, profile='k1')
    (out / 'device-profile.json').write_text(json.dumps({
        'profile': 'k1', 'android_models': ['angelcare K1']}) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
