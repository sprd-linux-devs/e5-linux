#!/usr/bin/python3
"""Recover this device's BT address when factory btmac.txt contains zeros."""
import configparser
import os
from pathlib import Path
import re


def parse_address(value):
    if not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', value):
        raise ValueError('Invalid Bluetooth address format')
    address = bytes.fromhex(value.replace(':', ''))
    if address in (bytes(6), b'\xff' * 6) or address[0] & 1:
        raise ValueError('Invalid Bluetooth unicast address')
    return address


def prepare(root=Path('/')):
    if (root / 'etc/e5/device-profile').read_text().strip() not in ('m8', 'k1', 'changxing60', 'y60'):
        raise ValueError('M8-family profile required')
    path = root / 'lib/firmware/sprd/marlin3lite_pskey.bin'
    data = bytearray(path.read_bytes())
    if len(data) != 176:
        raise ValueError('Unexpected Marlin3Lite PSKEY layout')
    # The existing collector writes device_addr (six HCI-order bytes) at 20.
    current = ':'.join(f'{v:02x}' for v in reversed(data[20:26]))
    try:
        parse_address(current)
        return False
    except ValueError:
        pass
    config = configparser.ConfigParser(interpolation=None, strict=False)
    config.read(root / 'mnt/e5-data/misc/bluedroid/bt_config.conf')
    # Only the local adapter identity is used. Do not copy paired-device keys.
    address = parse_address(config.get('Adapter', 'Address', fallback='').strip())
    data[20:26] = address[::-1]
    temporary = path.with_suffix('.tmp')
    with temporary.open('wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.chmod(path.stat().st_mode & 0o777)
    temporary.replace(path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    print('Bluetooth: restored local adapter address from this device Android settings')
    return True


if __name__ == '__main__':
    prepare()
