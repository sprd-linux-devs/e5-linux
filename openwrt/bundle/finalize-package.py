#!/usr/bin/env python3
"""Add native Magisk TF entry to the desktop package, sharing one image/boot."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import runpy
import shlex
import shutil
import zipfile

HERE = Path(__file__).resolve().parent
MODELS = {'e5': 'E5', 't551m': 'T551M', 'm8': 'VIPME M8', 't512n': 'T512N', 'yuanhang41s':'ZTE 7546N', 'k1':'angelcare K1', 'lym10k': 'LYM-10K', 'changxing60': 'ZTE 7552N', 'y60': 'CP23NV3'}


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def add_android_switcher(package):
    source = HERE.parents[1] / 'tools/switch-apk'
    apk = source / 'op-system-switcher.apk'
    metadata = json.loads((source / 'op-system-switcher.json').read_text(encoding='utf-8'))
    files = [source / 'AndroidManifest.xml', *(source / 'src').rglob('*.java'), *(source / 'res').rglob('*')]
    expected = {p.relative_to(source).as_posix(): hashlib.sha256(p.read_bytes().replace(b'\r\n', b'\n')).hexdigest()
                for p in sorted(files) if p.is_file()}
    if metadata != {'source': expected, 'binary_sha256': digest(apk)}:
        raise ValueError('Android switcher APK is stale; rebuild tools/switch-apk/build.sh first')
    android = package / 'extras/android'; android.mkdir(parents=True, exist_ok=True)
    shutil.copy2(apk, android / apk.name)
    shutil.copy2(source / 'README.md', package / 'docs/ANDROID-SWITCHER.md')


def add_diff_studio(package):
    return runpy.run_path(str(HERE.parents[1] / 'tools/package-diff-studio.py'))['attach'](package)


def finalize(package, profile, bootctl):
    package, bootctl = Path(package), Path(bootctl)
    add_android_switcher(package)
    add_diff_studio(package)
    files = package / 'files'
    for name in ('OpenWrt-Installer.py', 'START-HERE.md', 'files/android-bootchain.sh',
                 'scripts/installer/boot-slots.py', 'scripts/installer/storage-api.py', 'scripts/installer/storage-lib.sh', 'scripts/installer/gpt-api.py', 'files/storage.sh',
                 'files/collect-device-files.sh', 'files/android-loop.sh', 'files/ext4-tools.tar', 'files/install-lock-tools.tar', 'files/busybox', 'scripts/tools/sprd-bt-config.py',
                 'scripts/tools/vbc-profile/vbc-profile.py'):
        if not (package / name).is_file():
            raise ValueError('missing package component: ' + name)
    runpy.run_path(str(HERE / 'flash.py'))['validate_installer_busybox'](files / 'busybox')
    (files / 'busybox').chmod(0o755)
    helper = bootctl.read_bytes()
    if helper[:6] != b'\x7fELF\x02\x01' or helper[18:20] != b'\xb7\x00':
        raise ValueError('e5-bootctl must be an ARM64 ELF executable')
    manifest = json.loads((files / 'device-profile.json').read_text())
    if manifest != {'profile': profile, 'android_models': [MODELS[profile]]}:
        raise ValueError('package profile mismatch')
    boot = json.loads((files / 'boot.json').read_text())
    if digest(files / 'boot.img') != boot['sha256'] or boot.get('overlay_files') != 0:
        raise ValueError('boot image mismatch or non-generic overlay')
    raw_hash = hashlib.sha256()
    size = 0
    with gzip.open(files / 'openwrt.ext4.gz', 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            size += len(chunk)
            raw_hash.update(chunk)
    if size <= 0 or size % 512:
        raise ValueError('root image must have a positive sector-aligned size')
    for name in ('magisk-tf-install.sh', 'magisk-firmware.py', 'android-tf.sh'):
        (files / name).write_bytes((HERE / name).read_bytes().replace(b'\r\n', b'\n'))
    shutil.copyfile(HERE / 'MU300-INSTALLER-LICENSE', package / 'docs/MU300-INSTALLER-LICENSE')
    target = files / 'e5-bootctl'
    if bootctl.resolve() != target.resolve():
        shutil.copyfile(bootctl, target)
    target.chmod(0o755)
    (package / 'customize.sh').write_bytes((HERE / 'magisk-customize.sh').read_bytes().replace(b'\r\n', b'\n'))
    (package / 'skip_mount').touch()
    release_path = files / 'RELEASE.json'
    private = json.loads(release_path.read_text()) if release_path.is_file() else {}
    module_version = private.get('image_version', '1.0')
    module_code = int(private.get('build_epoch', 1))
    (package / 'module.prop').write_text(
        f'id=e5_openwrt_tf_{profile}\nname={MODELS[profile]} OpenWrt TF Installer\n'
        f'version={module_version}\nversionCode={module_code}\nauthor=e5-linux contributors\n'
        'description=ERASES THE SELECTED TF PARTITION (or unpartitioned card) and deploys OpenWrt. Android userdata is preserved. Reboot manually.\n',
        encoding='utf-8', newline='\n')
    values = {'PROFILE': profile, 'ANDROID_MODEL': MODELS[profile],
              'DEFAULT_SSID': {'e5': 'E5', 't551m': 'T551M', 'm8': 'M8', 't512n': 'T512N', 'yuanhang41s':'Yuanhang41S', 'k1':'K1', 'lym10k':'LYM-10K', 'changxing60':'Changxing60', 'y60':'Y60'}[profile] + '-OpenWrt',
              'SLOT_ROLES_VERSION':str(boot.get('slot_roles_version',0)),
              'RAW_BYTES': str(size), 'RAW_SHA256': raw_hash.hexdigest(),
              'BOOT_BYTES': str((files / 'boot.img').stat().st_size), 'BOOT_SHA256': boot['sha256']}
    (files / 'tf-install.env').write_text(''.join(k + '=' + shlex.quote(v) + '\n' for k, v in values.items()), newline='\n')
    guide = (package / 'START-HERE.md').read_text(encoding='utf-8')
    if profile == 'y60':
        guide = (HERE.parents[1] / 'devices/y60/TESTING.zh-CN.md').read_text(encoding='utf-8') + '\n' + guide
    (package / 'START-HERE.md').write_text(guide.replace('@MODEL@', MODELS[profile]).replace('@PROFILE@', profile),
                                         encoding='utf-8', newline='\n')
    sums = files / 'SHA256SUMS'
    hashes = {p.relative_to(package).as_posix(): digest(p) for p in sorted(package.rglob('*'))
              if p.is_file() and p != sums and p.name != 'SHA256SUMS' and '__pycache__' not in p.parts}
    sums.write_text(''.join(v + '  ' + k + '\n' for k, v in hashes.items()), newline='\n')
    return hashes


def write_zip(package, out):
    """Magisk requires module.prop/customize.sh at ZIP root, without a wrapper."""
    package, out = Path(package), Path(out)
    write_member = runpy.run_path(str(HERE.parents[1] / 'installer/archive_tools.py'))['write_member']
    required = ('module.prop', 'customize.sh', 'START-HERE.md', 'files/SHA256SUMS')
    for name in required:
        if not (package / name).is_file():
            raise ValueError('unfinished package: ' + name)
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(package.rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts:
                write_member(archive, path, path.relative_to(package).as_posix())
    with zipfile.ZipFile(out) as archive:
        bad = archive.testzip()
        if bad:
            raise ValueError('ZIP CRC failure: ' + bad)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('package', type=Path)
    p.add_argument('--profile', choices=MODELS)
    p.add_argument('--bootctl', type=Path)
    p.add_argument('--zip-only', type=Path, help='archive an already finalized package')
    a = p.parse_args()
    if a.zip_only:
        write_zip(a.package, a.zip_only)
    else:
        if not a.profile or not a.bootctl:
            p.error('--profile and --bootctl are required unless --zip-only is used')
        finalize(a.package, a.profile, a.bootctl)
