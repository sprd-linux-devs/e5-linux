#!/usr/bin/env python3
"""Create a clean M8 userspace from tested, sanitized OpenWrt package binaries."""
import argparse
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import tarfile

TOP = Path(__file__).resolve().parents[2]
source_bytes = runpy.run_path(str(TOP / 'devices/staging.py'))['source_bytes']


def ensure_ttyd_config(root):
    root = Path(root)
    config = root / 'etc/config/ttyd'
    if (root / 'usr/bin/ttyd').is_file() and not (config.exists() or config.is_symlink()):
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text("config ttyd\n option interface '@lan'\n option command '/bin/login'\n")
        config.chmod(0o644)


def prepare(base, root, defaults, profile='m8'):
    if profile not in ('e5', 't551m', 'm8', 't512n', 'yuanhang41s', 'k1', 'lym10k', 'changxing60', 'y60'):
        raise ValueError('Unknown device profile')
    base, root = base.resolve(), root.resolve()
    if os.name == 'nt' or root.exists() or base == Path('/'):
        raise ValueError('Use Linux/WSL, a clean release base and a new destination')
    if not (base / 'etc/openwrt_release').is_file():
        raise ValueError('Not an OpenWrt release root')
    for name in ('etc/e5/install.conf', 'etc/e5/contacts.json', 'etc/e5-sms',
                 'etc/unisoc-modem', 'etc/e5linux/default-boot', 'etc/uhttpd.key'):
        if (base / name).exists():
            raise ValueError('Source is not sanitized: ' + name)
    if any((base / 'opt/e5/android').iterdir()):
        raise ValueError('Source contains another device vendor files')
    skip = {'dev', 'proc', 'sys', 'run', 'tmp', 'var', 'mnt', 'root', 'lib/modules',
            'opt/e5/android', 'etc/config', 'etc/e5', 'etc/e5linux',
            'etc/e5-infoscreen', 'etc/ssh', 'etc/dropbear', 'etc/bluetooth/keys',
            'etc/crontabs', 'etc/ethers', 'etc/hostname', 'etc/machine-id',
            'etc/urandom.seed', 'etc/board.json', 'etc/uhttpd.crt', 'etc/shadow-', 'etc/passwd-'}
    def ignore(directory, names):
        rel = Path(directory).relative_to(base)
        return [n for n in names if (rel / n).as_posix() in skip]
    shutil.copytree(base, root, symlinks=True, ignore=ignore)
    def put(name, data, mode=0o644):
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.is_symlink():
            p.unlink()
        p.write_bytes(data if isinstance(data, bytes) else data.encode())
        p.chmod(mode)
    for name in ('dev', 'proc', 'sys', 'run', 'tmp', 'root', 'mnt/e5-data',
                 'opt/e5/android', 'etc/e5', 'etc/e5linux', 'etc/dropbear', 'etc/ssh', 'etc/crontabs'):
        (root / name).mkdir(parents=True, exist_ok=True)
    (root / 'var').symlink_to('/tmp')
    (root / 'tmp').chmod(0o1777)
    (root / 'root').chmod(0o700)
    with tarfile.open(defaults) as archive:
        for item in archive:
            if profile in ('t512n', 'yuanhang41s', 'k1', 'lym10k', 'changxing60', 'y60') and item.name == 'etc/config/unisoc_modem':
                # A clean T512N build takes fresh shared defaults, never a
                # prebuilt donor's auto_work_mode or LTE capability override.
                continue
            if (item.isfile() and '..' not in Path(item.name).parts and
                    (item.name.startswith('etc/config/') or item.name in ('etc/hosts', 'etc/ethers'))):
                put(item.name, archive.extractfile(item).read(), item.mode)
    # The sanitized base excludes all UCI files. A defaults archive predating
    # ttyd can therefore leave an installed package without its configuration;
    # apk add sees it as installed and will not recreate the missing conffile.
    # Match the package defaults, and preserve any explicit defaults supplied.
    ensure_ttyd_config(root)
    for p in (TOP / 'openwrt/overlay').rglob('*'):
        if p.is_file() and '__pycache__' not in p.parts:
            name = p.relative_to(TOP / 'openwrt/overlay').as_posix()
            executable = name.startswith(('etc/init.d/', 'etc/uci-defaults/', 'etc/hotplug.d/',
                                          'usr/libexec/', 'usr/sbin/', 'usr/bin/', 'sbin/', 'bin/'))
            put(name, source_bytes(p),
                0o755 if executable else 0o644)
    put('etc/config/network', "config interface 'loopback'\n option device 'lo'\n option proto 'static'\n option ipaddr '127.0.0.1'\n option netmask '255.0.0.0'\n\nconfig device\n option name 'br-lan'\n option type 'bridge'\n option bridge_empty '1'\n\nconfig interface 'lan'\n option device 'br-lan'\n option proto 'static'\n option ipaddr '192.168.9.1'\n option netmask '255.255.255.0'\n")
    put('etc/config/system', "config system\n option hostname 'OpenWrt'\n option timezone 'CST-8'\n option zonename 'Asia/Shanghai'\n")
    put('etc/config/wireless', '')
    put('etc/config/e5-infoscreen', (root / 'usr/share/e5-infoscreen/default.config').read_bytes())
    # New credentials and machine identity; never copy a donor device's secrets.
    # Incremental bases already contain the stock backup implementation.
    # Refresh the shared guard too, rather than retaining an older guard.
    if not (root / 'sbin/sysupgrade.openwrt').is_file():
        raise ValueError('Clean base lacks the original sysupgrade backup implementation')
    put('sbin/sysupgrade', source_bytes(TOP / 'openwrt/overlay/usr/libexec/e5-sysupgrade'), 0o755)
    # Common first-boot hook sets root/root; no donor password hashes.
    password = ''
    lines = []
    for line in (base / 'etc/shadow').read_text().splitlines():
        fields = line.split(':')
        fields[1] = password if fields[0] == 'root' else '!'
        lines.append(':'.join(fields))
    put('etc/shadow', '\n'.join(lines) + '\n', 0o600)
    put('etc/hostname', {'e5': 'E5', 't551m': 'T551M', 'm8': 'VIPME-M8', 't512n': 'T512N', 'yuanhang41s': 'Yuanhang-41S', 'k1': 'Angelcare-K1', 'lym10k': 'LYM-10K', 'changxing60': 'Changxing-60', 'y60': 'Coolpad-Y60'}[profile] + '\n')
    put('etc/machine-id', '')
    for p in (TOP / 'rootfs/overlay/opt/e5').iterdir():
        if p.is_file():
            put('opt/e5/' + p.name, source_bytes(p), 0o755)
    for p in (TOP / 'rootfs/overlay/usr/share/alsa').rglob('*'):
        if p.is_file():
            put('usr/share/alsa/' + p.relative_to(TOP / 'rootfs/overlay/usr/share/alsa').as_posix(), source_bytes(p))
    stage_path = 'devices/t551m/configure-rootfs.py' if profile == 't551m' else f'devices/{profile}/stage.py'
    runpy.run_path(str(TOP / stage_path))['stage'](root)
    for path in (root / 'etc/uci-defaults/90-e5',):
        hostname = {'e5': 'E5', 't551m': 'T551M', 'm8': 'VIPME-M8', 't512n': 'T512N', 'yuanhang41s': 'Yuanhang-41S', 'k1': 'Angelcare-K1', 'lym10k': 'LYM-10K', 'changxing60': 'Changxing-60', 'y60': 'Coolpad-Y60'}[profile]
        path.write_text(path.read_text().replace("hostname='E5'", "hostname='" + hostname + "'"))
    put('etc/e5/image-form', 'standalone\n')
    put('etc/e5/image-version', profile + '-tf\n')
    runpy.run_path(str(TOP / 'installer/stage-ota.py'))['stage'](root)
    runpy.run_path(str(TOP / 'tools/stage-ra-renew.py'))['stage'](root)
    # The base ships kernel Docker support only, not a Docker installation.
    if (root / 'usr/bin/dockerd').exists():
        raise ValueError('Unexpected preinstalled Docker')
    if any((root / 'opt/e5/android').iterdir()) or any((root / 'etc/dropbear').iterdir()):
        raise ValueError('Unexpected device data in new root')
    print('Prepared clean', profile, 'root:', root)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True, type=Path)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--defaults', required=True, type=Path)
    args = parser.parse_args()
    prepare(args.base, args.root, args.defaults)
