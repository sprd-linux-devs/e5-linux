#!/usr/bin/env python3
"""Prepare source-verified native installers under the shared workspace lock."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import sys
import tarfile
import urllib.request

TOP = Path(__file__).resolve().parents[1]


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for data in iter(lambda: stream.read(1 << 20), b''):
            digest.update(data)
    return digest.hexdigest()


def fetch(record, destination):
    if not record['url'].startswith('https://'):
        raise ValueError('Installer inputs require HTTPS')
    if destination.is_symlink():
        raise ValueError('Installer download is a symlink')
    if destination.exists():
        if not destination.is_file() or sha(destination) != record['sha256']:
            raise ValueError('Installer download checksum mismatch; inspect '+str(destination))
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    pending = destination.with_name(destination.name+'.partial')
    if pending.is_symlink():
        raise ValueError('Installer download partial is a symlink')
    with urllib.request.urlopen(record['url'], timeout=60) as source, pending.open('wb') as output:
        shutil.copyfileobj(source, output)
    if sha(pending) != record['sha256']:
        raise ValueError('Downloaded installer checksum mismatch; partial retained')
    pending.rename(destination)
    return destination


def prepare(workspace):
    api = runpy.run_path(str(TOP/'tools/build-release.py'))
    api['verify_installer_pin']()
    lock = api['installer_lock']()
    sys.path.insert(0, str(TOP/'installer'))
    gui = runpy.run_path(str(TOP/'installer/package_gui.py'))
    android = runpy.run_path(str(TOP/'installer/package_android.py'))
    for platform, key in (('windows-x64', 'installer_windows'), ('macos-arm64', 'installer_macos'), ('android-aarch64', 'installer_android')):
        record = lock['assets'][key]
        root = api['installer_artifact'](platform, workspace)
        default = api['installer_artifact'](platform, workspace, use_override=False)
        receipt = root.with_name(root.name+'.input.json')
        if root != default:
            if not root.is_dir():
                raise ValueError('Explicit installer input is missing: '+str(root))
        elif root.exists():
            if root.is_symlink() or not receipt.is_file() or json.loads(receipt.read_text()) != record:
                raise ValueError('Installer input is unowned or stale: '+str(root))
        else:
            archive = fetch(record, workspace/'cache/openwrt-tools-downloads'/record['url'].rsplit('/', 1)[1])
            pending = root.with_name(root.name+'.extracting')
            root.parent.mkdir(parents=True, exist_ok=True)
            pending.mkdir(exist_ok=False)
            if not hasattr(tarfile, 'data_filter'):
                raise ValueError('Update Python to a security-maintained version with tarfile.data_filter')
            with tarfile.open(archive) as source:
                source.extractall(pending, filter='data')
            if platform == 'android-aarch64':
                android['artifact'](pending)
            else:
                gui['validate_artifact'](pending, platform, gui['sources']())
            pending.rename(root)
            receipt.write_text(json.dumps(record)+'\n')
        if platform == 'android-aarch64':
            android['artifact'](root)
        else:
            gui['validate_artifact'](root, platform, gui['sources']())
        print('Verified '+platform+': '+str(root), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    args = parser.parse_args()
    if os.name != 'posix':
        raise SystemExit('Run through tools/build-release.py prepare-installers in WSL/Linux')
    if os.environ.get('OPENWRT_BUILD_WORKSPACE') != str(args.workspace.resolve()) or not os.environ.get('E5_BUILD_LAYOUT'):
        raise SystemExit('Use tools/build-release.py prepare-installers to hold the workspace lock')
    prepare(args.workspace.resolve())
