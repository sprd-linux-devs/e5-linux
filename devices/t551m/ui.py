#!/usr/bin/env python3
"""Stage the T551M dashboard and checksum-pinned Aurora packages into a root."""
import argparse
import hashlib
import os
import runpy
from pathlib import Path
import shutil
import tarfile
import tempfile
import urllib.request

TOP = Path(__file__).resolve().parents[2]
source_bytes = runpy.run_path(str(TOP / 'devices/staging.py'))['source_bytes']
PACKAGES = {
    'luci-theme-aurora-1.4.0-r20260920.apk':
        ('luci-theme-aurora', '1.4.0', '05f9015e0a4e2859f6a153f69e472f2984481490d4ce6db19b8a41bba7264f1e'),
    'luci-app-aurora-config-1.2.5-r20260920.apk':
        ('luci-app-aurora-config', '1.2.5', 'e290ef9465615d92b5d8baaeacb68a0b5f59edcc647895fa691fc2a3c81b6669'),
    'luci-i18n-aurora-config-zh-cn-26.262.58276.362887a.apk':
        ('luci-app-aurora-config', '1.2.5', '65de0bfda210c1e13df54749627342aea555fa9a01b363f4263ddba7d257b46b'),
    'luci-i18n-aurora-config-tr-26.262.58276.362887a.apk':
        ('luci-app-aurora-config', '1.2.5', '2d11e934ec9d3efd4af4b6a8adc3ed10d2e9ea8c1b417cf55fe153ad1df66a3a'),
}


def stage(root, profile='t551m'):
    if profile not in ('t551m', 'e5', 'm8', 't512n', 'yuanhang41s', 'k1', 'lym10k', 'changxing60', 'y60'):
        raise ValueError('Unknown device profile: ' + profile)
    root = Path(root)
    # Also stage into archive-only roots; the defaults hook patches package
    # files after installation when they are not present in the staging root.
    for source, destination in [('network-startup.py', 'opt/e5/t551m-network-startup'),
                                ('charge-mode.py', 'usr/libexec/e5-charge-mode'),
                                ('charge-mode-service', 'etc/init.d/e5-charge-mode'),
                                ('wifi-address-defaults', 'etc/uci-defaults/99-t551m-wifi-address'),
                                ('network-startup-defaults', 'etc/uci-defaults/98-t551m-network-startup')]:
        target = root / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(Path(__file__).with_name(source).read_bytes().replace(b'\r\n', b'\n'))
        target.chmod(0o755)
    runpy.run_path(str(Path(__file__).with_name('network-startup.py')))['patch_root'](root, profile)
    plugin = TOP / 'openwrt/luci-app-t551m'
    # Hot-update archives must carry the native incoming-message dispatch too.
    sms = root / 'usr/libexec/e5-sms'
    sms.parent.mkdir(parents=True, exist_ok=True)
    sms.write_bytes((TOP / 'openwrt/overlay/usr/libexec/e5-sms').read_bytes().replace(b'\r\n', b'\n'))
    sms.chmod(0o755)
    for srcdir, dest in [('root', root), ('htdocs', root / 'www'),
                         ('lmo', root / 'usr/lib/lua/luci/i18n')]:
        for src in (plugin / srcdir).rglob('*'):
            if not src.is_file() or '__pycache__' in src.parts:
                continue
            target = dest / src.relative_to(plugin / srcdir)
            target.parent.mkdir(parents=True, exist_ok=True)
            # Preserve user settings and traffic history on subsequent builds.
            if srcdir == 'root' and 'etc/config/' in target.as_posix() and target.exists():
                continue
            target.write_bytes(source_bytes(src) if srcdir != 'lmo' else src.read_bytes())
            if profile == 'e5' and src.relative_to(plugin / srcdir).as_posix() == 'etc/config/unisoc_modem':
                # B38 omission belongs to the T551M firmware, not the shared UI.
                target.write_bytes(target.read_bytes().replace(b"'1,3,5,8,34,39,40,41'", b"'1,3,5,8,34,38,39,40,41'"))
            if profile in ('m8', 't512n', 'yuanhang41s', 'k1', 'lym10k', 'changxing60', 'y60') and src.relative_to(plugin / srcdir).as_posix() == 'etc/config/unisoc_modem':
                # Discover this modem's capabilities; no donor band allowlist.
                target.write_bytes(b''.join(line for line in target.read_bytes().splitlines(keepends=True)
                                           if b'option lte_supported_bands ' not in line))
            executable = srcdir == 'root' and any(part in src.parts for part in ('init.d', 'hotplug.d', 'libexec', 'uci-defaults'))
            target.chmod(0o755 if executable else 0o644)
            if srcdir == 'root' and src.relative_to(plugin / srcdir).as_posix() == 'etc/config/unisoc_apn':
                target.chmod(0o600)
    # Fresh archive roots only receive the modem config in the loop above.
    cipher_patch = TOP / 'devices/wifi-ciphers.py'
    target = root / 'usr/libexec/e5-wifi-cipher-ui'
    target.write_bytes(source_bytes(cipher_patch))
    target.chmod(0o755)
    runpy.run_path(str(cipher_patch))['patch'](root)
    target = root / 'etc/uci-defaults/99-e5-wifi-ciphers'
    target.write_text('#!/bin/sh\nexec /usr/libexec/e5-wifi-cipher-ui --root /\n', encoding='utf-8')
    target.chmod(0o755)
    # Apply the profile defaults there too, not only to existing installations.
    runpy.run_path(str(Path(__file__).with_name('network-startup.py')))['patch_root'](root, profile)
    cache = Path(os.environ.get('E5_UI_CACHE', str(TOP / 'work/t551m/aurora')))
    packages = root / 'opt/e5/ui-packages'
    packages.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    checksums = []
    for name, (repo, version, digest) in PACKAGES.items():
        path = cache / name
        if not path.exists():
            data = urllib.request.urlopen(f'https://github.com/eamonxg/{repo}/releases/download/v{version}/{name}', timeout=60).read()
            if hashlib.sha256(data).hexdigest() != digest:
                raise ValueError('Downloaded Aurora package hash mismatch: ' + name)
            path.write_bytes(data)
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('Cached Aurora package hash mismatch: ' + name)
        shutil.copyfile(path, packages / name)
        (packages / name).chmod(0o644)
        checksums.append(digest + '  ' + name)
    (packages / 'SHA256SUMS').write_bytes(('\n'.join(checksums) + '\n').encode())
    target = root / 'etc/uci-defaults/98-t551m-ui'
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(Path(__file__).with_name('ui-defaults'), target)
    target.chmod(0o755)
    target = root / 'opt/e5/t551m-ui-compat'
    shutil.copyfile(Path(__file__).with_name('ui-compat.py'), target)
    target.chmod(0o755)
    for source, destination in [
        (TOP / 'openwrt/overlay/usr/libexec/e5-mm-state', 'usr/libexec/e5-mm-state'),
        (TOP / 'openwrt/overlay/usr/libexec/e5-background', 'usr/libexec/e5-background'),
        (TOP / 'openwrt/overlay/usr/libexec/e5-background-cpus', 'usr/libexec/e5-background-cpus'),
        (TOP / 'openwrt/overlay/usr/libexec/e5-charge', 'usr/libexec/e5-charge'),
        (TOP / 'openwrt/overlay/usr/libexec/e5-charge-core.uc', 'usr/libexec/e5-charge-core.uc'),
        (TOP / 'openwrt/overlay/usr/libexec/e5-usb-watch', 'usr/libexec/e5-usb-watch'),
        (TOP / 'openwrt/overlay/usr/libexec/e5-usb-watch.uc', 'usr/libexec/e5-usb-watch.uc'),
        (TOP / 'openwrt/overlay/etc/init.d/e5-hw', 'etc/init.d/e5-hw'),
        (TOP / 'openwrt/overlay/etc/init.d/e5-sipc-wwan', 'etc/init.d/e5-sipc-wwan'),
        (TOP / 'rootfs/overlay/opt/e5/regdb-load.sh', 'opt/e5/regdb-load.sh'),
        (TOP / 'openwrt/overlay/etc/init.d/e5-mm-state', 'etc/init.d/e5-mm-state'),
        (TOP / 'openwrt/overlay/etc/init.d/e5-network-recovery', 'etc/init.d/e5-network-recovery'),
        (TOP / 'openwrt/overlay/etc/init.d/e5-sms-notify', 'etc/init.d/e5-sms-notify'),
        (TOP / 'openwrt/overlay/etc/hotplug.d/usb/80-e5-usb-watch', 'etc/hotplug.d/usb/80-e5-usb-watch'),
        (TOP / 'openwrt/overlay/etc/hotplug.d/udc/80-e5-usb-watch', 'etc/hotplug.d/udc/80-e5-usb-watch'),
        (TOP / 'openwrt/overlay/etc/hotplug.d/extcon/80-e5-usb-watch', 'etc/hotplug.d/extcon/80-e5-usb-watch'),
        (Path(__file__).with_name('at-service'), 'etc/init.d/t551m-at'),
        (Path(__file__).with_name('ui-cleanup.py'), 'opt/e5/t551m-ui-cleanup'),
        (TOP / 'rootfs/overlay/opt/e5/e5-at', 'opt/e5/e5-at'),
        (TOP / 'rootfs/overlay/opt/e5/e5-data-priority', 'opt/e5/e5-data-priority'),
        (TOP / 'openwrt/overlay/usr/libexec/e5-volume', 'usr/libexec/e5-volume'),
        (TOP / 'openwrt/overlay/usr/libexec/e5-sms', 'usr/libexec/e5-sms'),
        (TOP / 'openwrt/overlay/etc/init.d/e5-pulseaudio', 'etc/init.d/e5-pulseaudio'),
    ]:
        target = root / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes().replace(b'\r\n', b'\n'))
        target.chmod(0o755)
    # The property mirror and HFP use the same pinned, already tracked wheel.
    # Keep the archive byte-for-byte; never newline-normalize binary inputs.
    vendor = root / 'usr/lib/e5/vendor'
    vendor.mkdir(parents=True, exist_ok=True)
    for name in ('dbus_next-0.2.3-py3-none-any.whl', 'dbus-next.LICENSE'):
        shutil.copyfile(TOP / 'openwrt/overlay/usr/lib/e5/vendor' / name, vendor / name)
    client = runpy.run_path(str(Path(__file__).with_name('build-at-client.py')))['build']()
    shutil.copyfile(client, root / 'opt/e5/t551m-at')
    (root / 'opt/e5/t551m-at').chmod(0o755)
    owner = runpy.run_path(str(Path(__file__).with_name('build-at-owner.py')))['build']()
    shutil.copyfile(owner, root / 'opt/e5/t551m-atd')
    (root / 'opt/e5/t551m-atd').chmod(0o755)
    voltage_checker = runpy.run_path(str(TOP/'devices/common/build-sml-voltage.py'))['build']()
    voltage_target = root/'usr/libexec/unisoc-modem/sml-voltage-check'
    shutil.copyfile(voltage_checker, voltage_target)
    voltage_target.chmod(0o755)
    runpy.run_path(str(Path(__file__).with_name('ui-cleanup.py')))['cleanup'](root)
    runpy.run_path(str(TOP / 'devices/common/infoscreen/stage.py'))['stage'](root)
    policy = TOP / 'tools/release-ui-policy.py'
    target = root / 'opt/e5/release-ui-policy'
    shutil.copyfile(policy, target)
    target.chmod(0o755)
    runpy.run_path(str(policy))['cleanup'](root)
    # S10boot runs uci-defaults after rcS has expanded its startup file list.
    # Pre-create these links in offline Linux roots for the very first boot.
    if os.name != 'nt':
        old_cpu_link = root / 'etc/rc.d/S18e5-cpu'
        if old_cpu_link.is_symlink():
            old_cpu_link.unlink()
        for name, priority in [('e5-mm-state', '30'), ('unisoc-ttl', '97'), ('unisoc-cpu-cores', '99'), ('unisoc-cpu-idle', '99'), ('unisoc-network-performance', '19'), ('e5-cpu', '13'), ('t551m-at', '81'), ('unisoc-modem-ui', '95'), ('unisoc-traffic', '96'), ('unisoc-sms-forward', '96')]:
            link = root / f'etc/rc.d/S{priority}{name}'
            link.parent.mkdir(parents=True, exist_ok=True)
            if not link.is_symlink():
                link.symlink_to('../init.d/' + name)
        for name, priority in [('e5-cpu', '89'), ('t551m-at', '09'), ('unisoc-traffic', '01'), ('unisoc-sms-forward', '01')]:
            link = root / f'etc/rc.d/K{priority}{name}'
            if not link.is_symlink():
                link.symlink_to('../init.d/' + name)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument('--root', type=Path)
    group.add_argument('--archive', type=Path)
    args = ap.parse_args()
    if args.root:
        stage(args.root)
    else:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stage(root)
            with tarfile.open(args.archive, 'w:gz') as archive:
                for path in sorted(root.rglob('*')):
                    if path.is_symlink():
                        archive.add(path, arcname=str(path.relative_to(root)), recursive=False)
                    elif path.is_file():
                        info = archive.gettarinfo(str(path), str(path.relative_to(root)))
                        info.mode = 0o755 if any(p in path.parts for p in ('init.d', 'hotplug.d', 'libexec', 'uci-defaults')) or path.name in ('t551m-at', 't551m-atd', 'e5-at', 'e5-data-priority', 't551m-ui-compat', 't551m-network-startup') else 0o644
                        if path.relative_to(root).as_posix() == 'etc/config/unisoc_apn':
                            info.mode = 0o600
                        info.uid = info.gid = 0
                        info.uname = info.gname = 'root'
                        with path.open('rb') as stream:
                            archive.addfile(info, stream)
