#!/usr/bin/env python3
"""Record/check the patched ModemManager APKs against their build inputs."""
import argparse
import hashlib
import json
from pathlib import Path

TOP = Path(__file__).resolve().parents[1]
OUT = TOP / 'out/openwrt'
STATE = OUT / 'e5-modemmanager-build.json'


def checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sources(version):
    files = [TOP / 'openwrt/build-modemmanager.sh', TOP / 'device/openwrt_device_common/tests/voice-identity.py',
             TOP / 'device/openwrt_device_common/tests/sim-power.py', TOP / 'device/openwrt_device_common/tests/sim-events.py', TOP / 'device/openwrt_device_common/tests/voice-urc.py',
             TOP / 'device/openwrt_device_common/tests/voice-recovery.py', TOP / 'device/openwrt_device_common/tests/voice-hangup.py', TOP / 'device/openwrt_device_common/tests/data-priority-hook.py',
             TOP / 'device/openwrt_device_common/tests/modem-mobility.py',
             TOP / 'device/openwrt_device_common/tests/modem-data-ports.py',
             TOP / 'device/openwrt_device_common/tests/modem-data-port-rules.py',
             TOP / 'device/openwrt_device_common/tests/sim-radio-parser.py',
             TOP / 'device/openwrt_device_common/files/modemmanager-unisoc-renew',
             TOP / 'device/openwrt_device_common/shared/network-startup.py',
             TOP / 'device/openwrt_device_common/shared/network-startup-defaults',
             TOP / 'device/openwrt_device_common/overlay/usr/libexec/e5-mm-report-ports',
             TOP / 'device/openwrt_device_common/overlay/etc/hotplug.d/wwan/26-e5-sipa-eth',
             TOP / 'device/openwrt_device_common/overlay/usr/libexec/e5-network-recovery',
             TOP / 'device/openwrt_device_common/overlay/etc/init.d/e5-network-recovery',
             Path(__file__).resolve()]
    files += sorted((TOP / 'device/debian_device_common/patches').glob('modemmanager-[0-9][0-9]-*.patch'))
    files += sorted((TOP / 'openwrt/patches').glob('modemmanager-package-*.patch'))
    return {'openwrt': version, 'files': {p.relative_to(TOP).as_posix(): checksum(p) for p in files}}


def inspect(version):
    apks = sorted(OUT.glob('modemmanager*.apk'))
    if not any(p.name.startswith('modemmanager-1') for p in apks) or not any(p.name.startswith('modemmanager-rpcd-') for p in apks):
        raise ValueError('patched ModemManager daemon or RPCD APK missing')
    return {'format': 1, 'sources': sources(version), 'apks': {p.name: checksum(p) for p in apks}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['write', 'check'])
    parser.add_argument('version')
    args = parser.parse_args()
    try:
        current = inspect(args.version)
        if args.action == 'write':
            STATE.write_text(json.dumps(current, indent=2) + '\n')
            print('Recorded patched ModemManager sources and APK checksums')
        else:
            if not STATE.is_file() or json.loads(STATE.read_text()) != current:
                raise ValueError('patched ModemManager APKs are stale or unverified; run openwrt/build-modemmanager.sh')
            print('Patched ModemManager APKs match current build inputs')
    except (ValueError, OSError) as error:
        parser.exit(1, 'Package check: ' + str(error) + '\n')
