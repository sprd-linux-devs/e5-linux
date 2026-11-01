#!/usr/bin/env python3
"""Audit this exact stock SML and execute only its pure-RAM routines offline.

Requires the existing local arm64 Docker image; never downloads an image,
connects to a device, changes NV, or issues an SMC/MMIO operation.
"""
import argparse
import hashlib
from pathlib import Path
import runpy
import shutil
import struct
import subprocess
import tempfile
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
TOP = HERE.parents[1]
CPU = TOP/'openwrt/luci-app-t551m/root/usr/libexec/unisoc-modem/cpu-control'
BASE = 0xb0000000


def branch(blob, address):
    word = struct.unpack_from('<I', blob, address - BASE + 512)[0]
    if word & 0xfc000000 != 0x94000000:
        raise ValueError('Expected BL at ' + hex(address))
    immediate = word & 0x3ffffff
    if immediate & 0x2000000:
        immediate -= 0x4000000
    return address + immediate * 4


def verify(path):
    data = Path(path).read_bytes()
    # This offline binary audit checks the routines below, not a model hash
    # allowlist. Signed image lengths and its payload checksum come from DHTB.
    if len(data)<512 or data[:8]!=b'DHTB\x01\0\0\0':
        raise ValueError('Expected a complete DHTB image')
    payload_size = struct.unpack_from('<I',data,0x30)[0]
    image_size = struct.unpack_from('<I',data,0x50)[0]
    if not 0<payload_size<=image_size-512 or not image_size<=len(data)<=1048576:
        raise ValueError('Truncated or invalid DHTB image lengths')
    payload=data[512:512+payload_size]
    if hashlib.sha256(payload).digest() != data[8:40]:
        raise ValueError('Factory DHTB payload checksum mismatch')
    table = data[0x13e50:0x13e50 + 13]
    target = 0xb000d3a8 + struct.unpack('b', table[11:12])[0] * 4
    if target != 0xb000d448 or branch(data, target) != 0xb0007300:
        raise ValueError('SMC 0x8200060b no longer reaches the audited DVFS_INIT')
    if branch(data, 0xb0007540) != 0xb0006248:
        raise ValueError('DVFS_INIT no longer reaches the audited flag decoder')
    for address in (0xb0004d44, 0xb0004d50, 0xb00051f0,
                    0xb00051fc, 0xb0005628, 0xb0005634):
        if branch(data, address) != 0xb0004068:
            raise ValueError('CPU/SRAM adjustment call changed')
    print('Full signed image, DHTB payload checksum, SMC dispatch and paired table calls PASS', flush=True)
    return data[:image_size]


def verify_backend(image):
    """Exercise API/save/boot with fake sysfs and real audited SML bytes."""
    cpu = runpy.run_path(str(CPU))
    with tempfile.TemporaryDirectory(prefix='lym10k-cpu-api-') as directory:
        root = Path(directory)
        for name, data in (
            ('etc/e5/device-profile', b'lym10k\n'),
            ('sys/firmware/devicetree/base/compatible', b'sprd,ums9621\0'),
            ('proc/sys/kernel/osrelease', b'offline-fixture'),
            ('lib/modules/offline-fixture/sprd-cpufreq-v2-driver.ko', b'fixture'),
        ):
            target = root/name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        banks = []
        for slot, dev in (('a', 'mmcblk0p6'), ('b', 'mmcblk0p7')):
            target = root/'sys/class/block'/dev/'uevent'
            target.parent.mkdir(parents=True)
            target.write_text('PARTNAME=sml_' + slot + '\n')
            target = root/'dev'/dev
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(image + bytes([0 if slot == 'a' else 255])*(1024*1024-len(image)))
            banks.append(target)
        control = cpu['Control'](root)
        for policy, domain in (('policy0', 0), ('policy6', 1), ('policy7', 2)):
            target = control.cpu/policy
            target.mkdir(parents=True)
            for name, value in {
                'related_cpus': '0 1 2 3 4 5' if domain == 0 else str(domain + 5),
                'scaling_driver': 'sprd-cpufreq-v2',
                'scaling_available_frequencies': '600000 1500000',
                'scaling_available_governors': 'schedutil performance powersave',
                'scaling_governor': 'schedutil', 'scaling_min_freq': '600000',
                'scaling_max_freq': '1500000', 'cpuinfo_min_freq': '600000',
                'cpuinfo_max_freq': '1500000', 'cpuinfo_cur_freq': '600000',
                'scaling_voltage_domain': str(domain), 'scaling_voltage_offset': '0',
                'scaling_voltage_table': '600000 600000\n1500000 900000',
            }.items():
                (target/name).write_text(value + '\n')
        before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in banks]
        state = control.snapshot()
        assert state['voltage_boot_writable'] and all(p['voltage_boot_writable'] for p in state['policies'])
        assert not state['voltage_writable']  # The SML tables are initialized once per boot.
        for policy, offset in (('policy0', -12500), ('policy6', 3125), ('policy7', 0)):
            control.set_item(policy + '_voltage_next', str(offset))
        assert control.voltage_profile() == [-12500, 3125, 0]
        assert control.snapshot()['voltage_reboot_required']
        hidden = root/'hidden'
        hidden.mkdir()
        for path in control.cpu.glob('policy*'):
            path.rename(hidden/path.name)
        def simulated_insmod(args, **kwargs):
            assert args[0] == 'insmod' and args[-1] == 'voltage_offset_uv=-12500,3125,0'
            for path in hidden.iterdir():
                path.rename(control.cpu/path.name)
        with patch.object(cpu['subprocess'], 'run', side_effect=simulated_insmod) as call:
            control.boot()
            assert call.call_count == 1
        assert control.voltage_armed.is_file()
        control.disarm_voltage()
        assert not control.voltage_armed.exists()
        assert before == [hashlib.sha256(p.read_bytes()).hexdigest() for p in banks]
    print('Shared CPU API: three-domain settings, persistence and simulated boot parameters PASS; SML unchanged', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sml', type=Path, required=True)
    parser.add_argument('--image', default='mu300-openwrt-base:25.12.5')
    args = parser.parse_args()
    data = verify(args.sml)
    verify_backend(data)
    if not shutil.which('aarch64-linux-gnu-gcc') or not shutil.which('docker'):
        raise ValueError('Requires local AArch64 GCC and Docker for offline ARM execution')
    subprocess.run(['docker', 'image', 'inspect', args.image], check=True, stdout=subprocess.DEVNULL)
    with tempfile.TemporaryDirectory(prefix='lym10k-sml-') as directory:
        folder = Path(directory)
        folder.chmod(0o755)  # The cap-dropped emulator may have another UID.
        (folder/'sml.bin').write_bytes(data)
        subprocess.run(['aarch64-linux-gnu-gcc', '-static', '-O2', '-Wall', '-Werror',
                        str(HERE/'test-sml-runtime.c'), '-o', str(folder/'check')], check=True)
        subprocess.run(['docker', 'run', '--rm', '--pull=never', '--platform', 'linux/arm64',
                        '--network', 'none', '--read-only', '--cap-drop', 'ALL',
                        '--security-opt', 'no-new-privileges', '-v', str(folder)+':/test:ro',
                        '--entrypoint', '/test/check', args.image, '/test/sml.bin'], check=True)


if __name__ == '__main__':
    main()
