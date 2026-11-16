#!/usr/bin/env python3
"""Build a standalone torch module against the registered E5 kernel cohort."""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import subprocess

TOP = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', required=True, type=Path)
    args = parser.parse_args()
    subprocess.run(['python3', str(TOP / 'devices/e5/test_torch.py')], check=True)
    config = json.loads((TOP / 'tools/build-layout.json').read_text())
    expand = lambda text: Path(text.format(workspace=args.workspace, repo=TOP))
    profile = config['profiles']['e5']
    source = expand(config['local_kernel_build']['source'])
    objects = args.workspace / 'objects/e5'
    output = expand(profile['torch_objects'])
    module_source = expand(profile['torch_source'])
    release = (objects / 'include/config/kernel.release').read_text().strip()
    kernel = expand(profile['kernel'])
    assert release == (kernel / 'kernel.release').read_text().strip()
    assert (objects / 'vmlinux').is_file() and (objects / 'Module.symvers').is_file()
    assert (objects / 'arch/arm64/boot/Image').read_bytes() == (kernel / 'Image').read_bytes(), 'E5 object/output cohort mismatch'
    view = runpy.run_path(str(TOP / 'tools/build-profile-kernel.py'))['source_view']
    with view(args.workspace, source, 'e5', config['local_kernel_build']['revision']) as tree:
        subprocess.run(['make', '-C', str(tree), 'O=' + str(objects),
                        'M=' + str(module_source), 'MO=' + str(output),
                        'ARCH=arm64', 'LLVM=1', 'LLVM_IAS=1',
                        'CROSS_COMPILE=aarch64-linux-gnu-', '-j4', 'modules'], check=True)
    module = output / 'e5-aw3641-torch.ko'
    assert module.is_file()
    sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    receipt = dict(kernel_release=release, image_sha256=sha(kernel / 'Image'),
                   module_sha256=sha(module), source_sha256=sha(module_source / 'e5-aw3641-torch.c'))
    (output / 'build.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(dict(module=str(module), **receipt)))


if __name__ == '__main__':
    main()
