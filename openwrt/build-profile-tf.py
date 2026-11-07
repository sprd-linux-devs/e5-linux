#!/usr/bin/env python3
"""Assemble a clean TF installer from tested package binaries and matching kernels.

Linux/WSL, root required. Inputs are explicit; no connected device is accessed.
The clean base must be firmware/credential-free. This is incremental assembly,
not a full OpenWrt SDK rebuild. Each output records source and input hashes.
"""
import argparse
import gzip
import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path
import runpy
import shutil
import subprocess
import tarfile
import time
import zipfile

TOP = Path(__file__).resolve().parents[1]
MODELS = {'e5': ['E5'], 't551m': ['T551M'], 'm8': ['VIPME M8'], 't512n': ['T512N'], 'yuanhang41s': ['ZTE 7546N'], 'k1': ['angelcare K1'], 'lym10k': ['LYM-10K'], 'changxing60': ['ZTE 7552N'], 'y60': ['CP23NV3']}


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def run(*args, **kwargs):
    subprocess.run([str(x) for x in args], check=True, **kwargs)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--profile', choices=MODELS, required=True)
    for name in ('base', 'defaults', 'kernel', 'stock-boot', 'misc-head', 'busybox', 'work', 'output', 'block-apk'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--apk-image', default='mu300-openwrt-base:25.12.5')
    p.add_argument('--wifi-apks', type=Path, default=TOP / 'work/wifi-sae')
    p.add_argument('--release-version', help='Optional explicit private release version')
    p.add_argument('--cc', default='aarch64-linux-gnu-gcc')
    a = p.parse_args()
    runpy.run_path(str(TOP / 'openwrt/bundle/flash.py'))['validate_installer_busybox'](a.busybox)
    wifi_build = runpy.run_path(str(TOP / 'openwrt/wifi-sae-state.py'))['inspect'](a.wifi_apks)
    wifi_args = ' '.join('/wifi-sae/' + n for n in sorted(wifi_build['apks']))
    if os.geteuid() != 0 or a.work.exists():
        p.error('Run as root with a new work directory')
    expected_id = runpy.run_path(str(TOP / 'tools/ci-release.py'))['block_build_id']()
    if Path(str(a.block_apk) + '.build-id').read_text().strip() != expected_id:
        raise ValueError('block-mount is not built from the current probe guard')
    if Path(str(a.block_apk) + '.sha256').read_text().split()[0] != digest(a.block_apk):
        raise ValueError('block-mount APK checksum mismatch')
    # A sanitized prebuilt base may carry an older daemon. Refresh it from
    # the source-verified APKs so a userspace fix cannot disappear in a repack.
    modem_state = runpy.run_path(str(TOP / 'tools/openwrt-package-state.py'))
    modem_build = modem_state['inspect']('25.12.5')
    if json.loads(modem_state['STATE'].read_text()) != modem_build:
        raise ValueError('ModemManager APKs are stale; rebuild them before packaging')
    modem_names = sorted(modem_build['apks'])
    if len(modem_names) != 2 or not all(re.fullmatch(r'modemmanager(?:-rpcd)?-1\.24\.0-r\d+\.apk', n) for n in modem_names):
        raise ValueError('Unexpected ModemManager package set')
    modem_args = ' '.join('/modem/' + n for n in modem_names)
    modem_daemon = next(n for n in modem_names if n.startswith('modemmanager-1'))
    a.work.mkdir(parents=True)
    root = a.work / 'root'
    release = runpy.run_path(str(TOP / 'upstream/check-container-support.py'))['check'](a.kernel)
    kernel_tags = ('-yuanhang41s-', '-yh41s-') if a.profile == 'yuanhang41s' else (f'-{a.profile}-',)
    if not any(tag in release for tag in kernel_tags):
        raise ValueError('Wrong kernel profile: ' + release)
    if b'e5.openwrt=' in (a.kernel / 'Image').read_bytes():
        raise ValueError('Trial kernel forces userdata boot; rebuild without e5.openwrt= for TF')
    prepare = runpy.run_path(str(TOP / 'devices/m8/prepare-root.py'))['prepare']
    prepare(a.base, root, a.defaults, profile=a.profile)
    for name in ('S22e5-modemd', 'K09e5-modemd'):
        link = root / 'etc/rc.d' / name
        if not link.is_symlink() or os.readlink(link) != '../init.d/e5-modemd' or not link.is_file():
            raise ValueError('CP assert recovery service is not enabled: ' + name)
    helpers = {}
    for n, target in (('logdw', 'opt/e5/bin/logdw'), ('e5-vibrate', 'usr/bin/e5-vibrate'),
                      ('e5-ctl-raw', 'opt/e5/e5-ctl-raw'), ('e5-modemd', 'usr/sbin/e5-modemd'),
                      ('e5-sim-probe', 'usr/libexec/e5-sim-probe')):
        src = TOP / ('openwrt/src/' + n + '.c')
        run(a.cc, '-static', '-Os', '-s', '-Wall', '-o', root / target, src)
        helpers[target] = {'source_sha256': digest(src), 'binary_sha256': digest(root / target)}
    target = 'usr/libexec/unisoc-modem/sml-voltage-check'
    helpers[target] = {'source_sha256': digest(TOP/'devices/common/sml-voltage-check.c'),
                       'binary_sha256': digest(root/target)}
    # Keep the pristine upstream first-boot hooks present in the clean base.
    # The common stager refreshes their repository-owned replacements.
    for kind in ('storage', 'network'):
        target = root / ('etc/modules.d/55-usb-host-' + kind)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((TOP / f'devices/t551m/usb-host-{kind}.modules').read_bytes().replace(b'\r\n', b'\n'))
        # Avoid loading the same list twice under old aliases.
        for old in (f'etc/modules.d/usb-host-{kind}', f'etc/modules.d/56-usb-host-{kind}'):
            (root / old).unlink(missing_ok=True)
    runpy.run_path(str(TOP / 'upstream/stage-root-modules.py'))['stage'](a.kernel, root)
    # apk handles the package database/dependencies; never copy just /sbin/block.
    run('docker', 'run', '--rm', '--platform', 'linux/arm64',
        '-v', f'{root}:/target', '-v', f'{a.block_apk.resolve()}:/input/block.apk:ro',
        '-v', f'{TOP / "out/openwrt"}:/modem:ro',
        '-v', f'{a.wifi_apks.resolve()}:/wifi-sae:ro',
        '--entrypoint', '/bin/sh', a.apk_image, '-ec',
        # Match the existing MU300 builder: transient index/download failures
        # retry in this staging tree, without restarting every model's package.
        'apk_retry() { attempt=1; while ! apk "$@"; do '
        '[ "$attempt" -lt 3 ] || return 1; attempt=$((attempt + 1)); '
        'echo "Retrying apk download (attempt $attempt/3)" >&2; sleep 3; done; }; '
        'apk --root /target --no-scripts --no-network add --allow-untrusted /input/block.apk ' + modem_args + ' ' + wifi_args + ' && '
        'mkdir /tmp/modem-verify && apk extract --allow-untrusted --destination /tmp/modem-verify /modem/' + modem_daemon + ' && '
        'cmp /target/usr/sbin/ModemManager /tmp/modem-verify/usr/sbin/ModemManager && '
        'ucode /target/usr/libexec/unisoc-modem/disable-channel-analysis /target && '
        # Incremental builds must also add newly mandatory packages to old bases.
        'apk_retry --root /target update >/dev/null && '
        'apk_retry --root /target --no-scripts add ttyd luci-app-ttyd luci-i18n-ttyd-zh-cn luci-i18n-ttyd-tr iw-full '
        'rpcd-mod-ucode ucode-mod-fs ucode-mod-ubus ucode-mod-uci ucode-mod-uloop ucode-mod-rtnl ucode-mod-nl80211 && '
        'sh /target/usr/libexec/e5-ttyd-bind /target && '
        'ln -sf ../init.d/ttyd /target/etc/rc.d/S99ttyd && '
        'ln -sf ../init.d/ttyd /target/etc/rc.d/K50ttyd && '
        'ucode /target/usr/libexec/unisoc-modem/disable-stock-upgrade /target')
    runpy.run_path(str(TOP / 'devices/t551m/network-startup.py'))['patch_root'](root, a.profile)
    runpy.run_path(str(TOP / 'tools/stage-flow-offload.py'))['stage'](root)
    # The SMS forward signs DingTalk webhooks with the openssl CLI and sends SMTP
    # through msmtp; the clean base carries the backend files without the packages.
    # (downloads.openwrt.org interrupts mid-index often enough that the same
    #  retry loop mu300-linux's builder uses belongs here too)
    run('docker', 'run', '--rm', '--platform', 'linux/arm64',
        '-v', f'{root}:/target', '--entrypoint', '/bin/sh', a.apk_image, '-ec',
        'ok=; for n in 1 2 3; do apk --root /target --no-scripts add openssl-util msmtp && '
        '{ ok=1; break; }; echo "apk download interrupted (attempt $n), retrying" >&2; sleep 3; done; '
        '[ -n "$ok" ]')
    forward = {}
    for pkg in ('openssl-util', 'msmtp'):
        match = re.search(rf'^P:{pkg}$\n^V:(\S+)$', (root / 'lib/apk/db/installed').read_text(), re.M)
        if not match:
            raise ValueError(f'the TF image has no {pkg}: the SMS forward needs it')
        forward[pkg] = match.group(1)
    (root / 'etc/e5/block-mount.build-id').write_bytes(Path(str(a.block_apk) + '.build-id').read_bytes())
    (root / 'etc/e5/wifi-sae.build-id').write_text(wifi_build['build_id'] + '\n')
    (root / 'etc/e5/wifi-sae.source-info').write_bytes((a.wifi_apks / 'source-info').read_bytes())
    # Do not execute target init scripts on the build host.
    fstab = (root / 'etc/init.d/fstab').read_text()
    for action, prefix in (('START', 'S'), ('STOP', 'K')):
        match = re.search(r'^' + action + r'=(\d+)$', fstab, re.M)
        if match:
            path = root / 'etc/rc.d' / (prefix + match[1].zfill(2) + 'fstab')
            if not path.is_symlink():
                path.symlink_to('../init.d/fstab')
    # Avoid host umasks/CRLF or stale Python bytecode in target scripts.
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in files:
            path = Path(directory) / name
            if path.is_symlink():
                os.lchown(path, 0, 0)
                continue
            data = path.read_bytes()
            if data.startswith(b'#!'):
                path.write_bytes(data.replace(b'\r\n', b'\n'))
                path.chmod(0o755)
            os.chown(path, 0, 0)
        for name in dirs:
            os.lchown(Path(directory) / name, 0, 0)
    # apk may create a temporary cache, which has no place in the image.
    for child in (root / 'tmp').iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
    epoch = int(time.time())
    rev = subprocess.check_output(['git', '-c', 'safe.directory=' + str(TOP), '-C', str(TOP), 'rev-parse', 'HEAD'], text=True).strip()
    release_info = runpy.run_path(str(TOP / 'tools/release-identity.py'))['identify'](
        TOP, a.profile, release, epoch=epoch, version=a.release_version)
    name = release_info['package_name']
    package = a.work / name
    files = package / 'files'
    files.mkdir(parents=True)
    shutil.copyfile(a.busybox, files / 'busybox')
    (files / 'busybox').chmod(0o755)
    shutil.copyfile(a.kernel / 'config', files / 'kernel.config')
    shutil.copyfile(a.kernel / 'modules.in-tree', files / 'modules.in-tree')
    init = a.work / 'init'
    init.write_bytes((TOP / 'boot/init').read_bytes().replace(b'\r\n', b'\n'))
    boot_order = a.kernel/'module-order.txt'
    ufs_args = []
    if a.profile == 'changxing60':
        helper = root/'usr/libexec/e5-ufs-id'
        shutil.copyfile(helper, files/'e5-ufs-id')
        ufs_args = ['--ufs-helper', helper]
        ordered = runpy.run_path(str(TOP/'devices/changxing60/stage.py'))['early_module_order'](a.kernel,release)
        boot_order = a.work/'release-module-order.txt'
        boot_order.write_text('\n'.join(ordered)+'\n')
    run('python3', TOP / 'boot/build-boot-image.py', '--stock-boot', a.stock_boot,
        '--misc-head', a.misc_head, '--kernel', a.kernel / 'Image.lk',
        '--modules', a.kernel / 'modules', '--module-order', boot_order,
        '--busybox', a.busybox, *ufs_args, '--init', init, '--cmdline',
        'e5.lkpad=0000000000' if a.profile in ('t512n', 'lym10k') else '', '--out', files / 'boot.img')
    boot = json.loads((files / 'boot.json').read_text())
    expected_command = ('e5.lkpad=0000000000 ' if a.profile in ('t512n', 'lym10k') else '') + 'e5.part_v=2'
    assert boot['overlay_files'] == 0 and boot['cmdline'] == expected_command
    (files / 'boot.misc-slot-b-trial.bin').rename(files / 'boot-misc-slot-b.bin')
    sources = {}
    # Includes uncommitted source fixes, so HEAD alone cannot misidentify a build.
    names = subprocess.check_output(['git', '-c', 'safe.directory=' + str(TOP), '-C', str(TOP),
                                     'ls-files', '--cached', '--others', '--exclude-standard', '-z']).decode().split('\0')
    for n in sorted(set(names)):
        if n.startswith(('boot/', 'devices/', 'magisk/', 'openwrt/', 'rootfs/overlay/', 'tools/', 'upstream/')) and (TOP / n).is_file():
            sources[n] = digest(TOP / n)
    (files / 'RELEASE.json').write_text(json.dumps(release_info, indent=2) + '\n')
    (root / 'etc/e5/release.json').write_text(json.dumps(release_info, indent=2) + '\n')
    info = {'private_version': release_info['private_version'], 'source_fingerprint': release_info['source_fingerprint'],
            'name': name, 'profile': a.profile, 'source_commit': rev,
            'build_epoch': epoch, 'kernel_release': release, 'openwrt': '25.12.5',
            'build_type': 'incremental assembly; tested package binaries, current sources, rebuilt initramfs',
            'docker_preinstalled': False, 'root_image_bytes': 2147483648,
            'boot_sha256': boot['sha256'], 'block_mount_sha256': digest(a.block_apk),
            'wifi_sae_packages': wifi_build,
            'forward_packages': forward,
            'hardware_validation': 'TF installer and final image not flashed; offline checks only',
            'kernel_manifest': json.loads((a.kernel / 'container-support.json').read_text()),
            'compiled_helpers': helpers,
            'modemmanager_sha256': digest(root / 'usr/sbin/ModemManager'),
            'modemmanager_packages': modem_build['apks'],
            'sources': sources}
    for dest in (root / 'etc/e5/build.json', files / 'BUILD.json'):
        dest.write_text(json.dumps(info, ensure_ascii=False, indent=2) + '\n')
    (root / 'etc/e5/image-version').write_text(release_info['image_version'] + '\n')
    (root / 'etc/e5/build-time').write_text(str(epoch) + '\n')
    feature = root / 'etc/e5/feature-port.json'
    if feature.exists():
        data = json.loads(feature.read_text())
        data.update(status='tf-package', hardware_validation=info['hardware_validation'])
        feature.write_text(json.dumps(data, indent=2) + '\n')
    audit(root, a.profile, release)
    image = a.work / 'openwrt.ext4'
    run('mke2fs', '-q', '-t', 'ext4', '-L', 'e5-openwrt', '-m', '1', '-d', root, image, '2048M')
    run('e2fsck', '-fn', image)
    with (files / 'openwrt.ext4.gz').open('wb') as out:
        run('gzip', '-1', '-c', image, stdout=out)
    runpy.run_path(str(TOP / 'openwrt/prepare-ext4-tools.py'))['build'](root, files / 'ext4-tools.tar')
    runpy.run_path(str(TOP / 'openwrt/prepare-ext4-tools.py'))['build_lock'](root, files / 'ext4-tools.tar', files / 'install-lock-tools.tar')
    runpy.run_path(str(TOP / 'openwrt/bundle/install-entrypoints.py'))['assemble'](package)
    extras = package / 'extras'; extras.mkdir()
    shutil.copy2(TOP / 'openwrt/bundle/【没刷op的别用，百分百变砖】op系统切换器.js', extras / 'openwrt-system-switch-plugin.js')
    for n in ('device-install-image.sh', 'device-flash-boot.sh', 'device-install-part.sh', 'device-stage-part-update.sh'):
        shutil.copy2(TOP / 'openwrt' / n, files / n)
    (files / 'part-write.sh').write_bytes((TOP / 'openwrt/bundle/part-write.sh').read_bytes().replace(b'\r\n', b'\n'))
    (files / 'nv-persistence.py').write_bytes((TOP / 'openwrt/luci-app-t551m/root/usr/lib/e5/nv_persistence.py').read_bytes().replace(b'\r\n', b'\n'))
    for src in ('openwrt/bundle/collect-device-files.sh', 'openwrt/overlay/usr/libexec/e5-gpt', 'tools/android-bootchain.sh', 'boot/storage.sh'):
        target = files / Path(src).name
        target.write_bytes((TOP / src).read_bytes().replace(b'\r\n', b'\n'))
        target.chmod(0o755)
    tools = package / 'scripts/tools'
    tools.mkdir(parents=True, exist_ok=True)
    for n in ('e5-telnet.py', 'e5-update.py', 'sprd-bt-config.py'):
        shutil.copy2(TOP / 'tools' / n, tools / n)
    shutil.copytree(TOP / 'tools/vbc-profile', tools / 'vbc-profile', ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy2(TOP / 'LICENSE', package / 'docs/LICENSE')
    (files / 'device-profile.json').write_text(json.dumps({'profile': a.profile, 'android_models': MODELS[a.profile]}) + '\n')
    (files / 'VERSION').write_text(name + ' (' + release + ')\n')
    run(a.cc, '-static', '-Os', '-s', '-Wall', '-Wextra', '-Werror',
        '-o', files / 'e5-bootctl', TOP / 'magisk/e5-linux-switch/bootctl.c')
    checks = runpy.run_path(str(TOP / 'openwrt/bundle/finalize-package.py'))['finalize'](
        package, a.profile, files / 'e5-bootctl')
    spec = importlib.util.spec_from_file_location('packaged_flash', package / 'OpenWrt-Installer.py')
    flash = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(flash)
    flash.check_package()
    assert flash.gz_usize(str(files / 'openwrt.ext4.gz')) == 2147483648
    a.output.mkdir(parents=True, exist_ok=True)
    archive = a.work / (name + '.zip')
    runpy.run_path(str(TOP / 'openwrt/bundle/finalize-package.py'))['write_zip'](package, archive)
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        for n, want in checks.items():
            with z.open(n) as stream:
                h = hashlib.sha256()
                while chunk := stream.read(1024 * 1024):
                    h.update(chunk)
            assert h.hexdigest() == want, n
    target = a.output / archive.name
    shutil.copyfile(archive, target)
    assert digest(target) == digest(archive)
    (a.output / (archive.name + '.sha256')).write_text(digest(target) + '  ' + target.name + '\n')
    shutil.copyfile(files / 'BUILD.json', a.output / (name + '.json'))
    print('RELEASE:', target, target.stat().st_size, flush=True)


def audit(root, profile, release):
    for name in ('usr/sbin/unisoc-ra-renew','etc/init.d/unisoc-ra-renew'):
        assert (root/name).read_bytes() == (TOP/'openwrt/overlay'/name).read_bytes().replace(b'\r\n',b'\n'), name
        assert os.access(root/name, os.X_OK), name
    for name in ('S98unisoc-ra-renew','K10unisoc-ra-renew'):
        assert os.readlink(root/'etc/rc.d'/name) == '../init.d/unisoc-ra-renew'
    assert (root / 'etc/e5/device-profile').read_text().strip() == profile
    assert json.loads((root / 'usr/share/unisoc-battery-history/profile.json').read_text())['family'] == 'e5'
    for name in ('usr/share/ucode/mu300/battery-history.uc',
                 'www/luci-static/resources/view/mu300/battery.js'):
        assert (root / name).is_file(), name
    for name in ('etc/init.d/unisoc-battery-history', 'usr/libexec/unisoc-modem/battery-history'):
        assert os.access(root / name, os.X_OK), name
    assert (root / 'etc/rc.d/S96unisoc-battery-history').is_symlink()
    assert (root / 'etc/rc.d/K12unisoc-battery-history').is_symlink()
    assert not (root / 'etc/e5/battery').exists(), 'Device battery history must not ship in releases'
    assert [p.name for p in (root / 'lib/modules').iterdir()] == [release]
    for directory in ('opt/e5/android', 'etc/dropbear', 'etc/ssh', 'root', 'tmp'):
        assert not any((root / directory).iterdir()), directory
    for name in ('etc/e5/install.conf', 'etc/e5/sd-root', 'etc/e5/contacts.json', 'etc/e5-sms',
                 'etc/unisoc-modem', 'etc/uhttpd.key', 'etc/uhttpd.crt', 'usr/bin/dockerd',
                 'usr/bin/docker', 'usr/bin/containerd', 'usr/bin/runc',
                 'usr/bin/xray', 'usr/bin/sing-box', 'usr/sbin/openvpn', 'usr/bin/tailscaled'):
        assert not (root / name).exists(), name
    assert all(p.name in ('regulatory.db', 'regulatory.db.p7s', 'rtl_nic') for p in (root / 'lib/firmware').iterdir())
    assert (root / 'etc/shadow').read_text().startswith('root::')
    assert (root / 'etc/machine-id').read_text() == ''
    # Sanitized incremental bases can still carry the reduced iw package.
    # That binary omits Supported Ciphers, so capability filtering stays inert.
    packages = (root / 'lib/apk/db/installed').read_text()
    assert re.search(r'^P:iw-full$', packages, re.M), 'Full iw capabilities are required'
    for package in ('rpcd-mod-ucode', 'ucode-mod-fs', 'ucode-mod-ubus',
                    'ucode-mod-uci', 'ucode-mod-uloop', 'ucode-mod-rtnl', 'ucode-mod-nl80211'):
        assert re.search(r'^P:' + re.escape(package) + r'$', packages, re.M), package
    for name in ('sbin/block', 'lib/libblkid-tiny.so', 'etc/init.d/fstab',
                 'lib/netifd/hostapd-unisoc.sh', 'usr/share/ucode/wifi/unisoc-sae.uc',
                 'etc/e5/wifi-sae.build-id',
                 'usr/sbin/ModemManager', 'usr/libexec/e5-infoscreen/session',
                 'usr/bin/openssl', 'usr/bin/msmtp', 'usr/bin/python3',
                 'opt/e5/t551m-atd', 'usr/libexec/e5-mm-state',
                 'usr/libexec/e5-background', 'usr/libexec/e5-background-cpus',
                 'usr/libexec/e5-charge-core.uc', 'usr/libexec/e5-usb-watch.uc',
                 'usr/libexec/unisoc-modem/device-usb', 'usr/libexec/unisoc-modem/usb-link.uc',
                 'usr/share/ucode/e5/dash.uc', 'usr/share/rpcd/ucode/e5status.uc'):
        assert (root / name).stat().st_size, name
    modem = (root / 'etc/config/unisoc_modem').read_text()
    # The selector is shared by every model. Keep the board's default
    # separate from an explicit 134/152 user override.
    assert re.search(r"^\s*option\s+auto_work_mode\s+['\"]?(default|134|152)['\"]?\s*$", modem, re.M)
    expected_mode = '152'
    assert re.search(r"^\s*option\s+auto_work_mode_default\s+['\"]?" + expected_mode + r"['\"]?\s*$", modem, re.M)
    if profile == 'm8':
        assert (root / 'etc/e5/receiver-volume-ceiling').read_text().strip() == '5'
    print('Clean root audit passed:', profile, flush=True)


if __name__ == '__main__':
    main()
