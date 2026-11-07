#!/usr/bin/env python3
"""Archive verified native tools for a source-pinned installer input release."""
import gzip
import json
import os
from pathlib import Path
import runpy
import sys
import tarfile

TOP = Path(__file__).resolve().parents[1]


def main():
    if not os.environ.get('OPENWRT_BUILD_WORKSPACE'):
        raise ValueError('Use tools/build-release.py run')
    workspace = Path(os.environ['OPENWRT_BUILD_WORKSPACE'])
    api = runpy.run_path(str(TOP/'tools/build-release.py'))
    api['verify_installer_pin']()
    commit = api['installer_lock']()['installer_commit']
    sys.path.insert(0, str(TOP/'installer'))
    gui = runpy.run_path(str(TOP/'installer/package_gui.py'))
    mobile = runpy.run_path(str(TOP/'installer/package_android.py'))
    output = workspace/'cache/openwrt-tools-publish'/commit[:7]
    output.mkdir(parents=True, exist_ok=True)
    assets = {}
    for platform in ('windows-x64', 'macos-arm64', 'android-aarch64'):
        root = api['installer_artifact'](platform, workspace).resolve()
        if platform == 'android-aarch64':
            apk, metadata = mobile['artifact'](root)
            files = [apk, metadata]
        else:
            metadata = gui['validate_artifact'](root, platform, gui['sources']())
            files = [metadata]+[root/n for n in json.loads(metadata.read_text())['files']]
        target = output/('installer-'+platform+'-'+commit[:7]+'.tar.gz')
        with target.open('xb') as stream, gzip.GzipFile(filename='', fileobj=stream, mode='wb', mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode='w', dereference=False) as archive:
                for path in sorted(files):
                    info = archive.gettarinfo(str(path), arcname=path.relative_to(root).as_posix())
                    info.uid = info.gid = info.mtime = 0
                    info.uname = info.gname = ''
                    if info.isfile():
                        with path.open('rb') as source:
                            archive.addfile(info, source)
                    else:
                        archive.addfile(info)
        assets[platform] = {'file': target.name, 'sha256': gui['digest'](target), 'bytes': target.stat().st_size}
    record = {'installer_commit': commit, 'assets': assets}
    (output/'inputs.json').write_text(json.dumps(record, indent=2)+'\n')
    (output/'SHA256SUMS').write_text(''.join(v['sha256']+'  '+v['file']+'\n' for v in assets.values()))
    print(json.dumps({'output': str(output), **record}, indent=2))


if __name__ == '__main__':
    main()
