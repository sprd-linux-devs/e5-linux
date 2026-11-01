#!/usr/bin/env python3
"""Compile-check the Y60 charger against registered existing platform headers.

This is an API/object check, not a Y60 kernel build or a deployable KO. The
reference profile's source, config, objects and Image are never repurposed.
Run through tools/build-release.py run for the normal workspace lock/log.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

TOP = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workspace', type=Path, required=True)
    p.add_argument('--config', type=Path, default=TOP/'tools/build-layout.json')
    p.add_argument('--report', type=Path, required=True)
    args = p.parse_args()
    if os.name == 'nt':
        p.error('Use the existing WSL build environment')
    workspace = args.workspace.resolve()
    report_path=args.report.resolve()
    if not any(report_path.is_relative_to(root.resolve())
               for root in (TOP/'work',TOP/'out/build-logs')):
        p.error('Keep the API investigation report under work/ or out/build-logs/')
    layout = json.loads(args.config.read_text(encoding='utf-8'))
    name = layout['driver_api_checks']['y60']['reference_native']
    reference = layout['native_kernel_builds'][name]
    expand = lambda path: Path(path.format(workspace=workspace, repo=TOP)).resolve()
    source, objects = expand(reference['source']), expand(reference['objects'])
    release = (objects/'include/config/kernel.release').read_text().strip()
    if '-'+name+'-' not in release:
        raise ValueError('Reference object cache belongs to another model: '+release)
    revision = subprocess.check_output(['git','-c','safe.directory='+str(source),'-C',
                                        str(source),'rev-parse','HEAD'], text=True).strip()
    if revision != layout['local_kernel_build']['revision']:
        raise ValueError('Unexpected reference kernel revision')
    if source == objects or not (objects/'include/generated/autoconf.h').is_file():
        raise ValueError('Registered reference headers are not prepared')
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()
    inputs = [objects/'.config', objects/'include/config/kernel.release',
              objects/'Module.symvers']
    before = {str(path): digest(path) for path in inputs}
    report = dict(kind='API/object check only; not deployable', reference_profile=name,
                  reference_release=release, reference_revision=revision,
                  driver_sha256=digest(HERE/'eta6937-charger.c'), hardware_validated=False)
    subprocess.run(['python3', str(HERE/'test-charger.py')], check=True)
    with tempfile.TemporaryDirectory(prefix='e5-release-y60-driver-', dir=workspace/'tmp') as temp:
        directory = Path(temp)
        for origin in (HERE/'eta6937-charger.c', HERE.parent/'common/power-probe.h'):
            (directory/origin.name).write_bytes(origin.read_bytes())
        (directory/'Makefile').write_text('obj-m := eta6937-charger.o\n')
        subprocess.run(['make','-C',str(source),'O='+str(objects),'M='+str(directory),
                        'ARCH=arm64','LLVM=1','LLVM_IAS=1','CROSS_COMPILE=aarch64-linux-gnu-',
                        'eta6937-charger.o'],check=True,env=dict(os.environ, LOCALVERSION=''))
        result = directory/'eta6937-charger.o'
        report['object_sha256'] = digest(result)
        report['object_bytes'] = result.stat().st_size
    if before != {str(path):digest(path) for path in inputs}:
        raise ValueError('Reference kernel configuration or module ABI changed during API check')
    report_path.parent.mkdir(parents=True,exist_ok=True)
    report_path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__ == '__main__':
    main()
