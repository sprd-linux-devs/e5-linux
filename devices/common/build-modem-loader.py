#!/usr/bin/env python3
"""Cache one static ARM64 recognizer for both ARM32 and ARM64 stock loaders."""
import hashlib
import json
import os
from pathlib import Path
import platform
import struct
import subprocess

TOP = Path(__file__).resolve().parents[2]


def build():
    source = TOP / 'openwrt/src/modem-loader-patch.c'
    output = TOP / 'out/modem-loader/modem-loader-patch'
    metadata = output.with_suffix('.build.json')
    compiler = os.environ.get('MODEM_LOADER_CC',
        'gcc' if platform.machine().lower() in ('aarch64', 'arm64') else 'aarch64-linux-gnu-gcc')
    inputs = {'source': hashlib.sha256(source.read_bytes()).hexdigest(),
              'builder': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'compiler': compiler}
    if output.is_file() and metadata.is_file():
        try:
            saved = json.loads(metadata.read_text())
            if saved == {'inputs': inputs, 'binary': hashlib.sha256(output.read_bytes()).hexdigest()}:
                return output
        except (OSError, ValueError):
            pass
    output.parent.mkdir(parents=True, exist_ok=True)

    def linux(path):
        if os.name == 'nt':
            return subprocess.check_output(['wsl', '-d', 'Ubuntu-22.04', '--exec',
                                            'wslpath', '-a', '-u', str(path)], text=True).strip()
        return str(path)

    temporary = output.with_suffix('.tmp')
    args = [compiler, '-std=c11', '-Os', '-Wall', '-Wextra', '-Werror', '-static', '-s',
            linux(source), '-o', linux(temporary)]
    if os.name == 'nt':
        args = ['wsl', '-d', 'Ubuntu-22.04', '--exec', *args]
    subprocess.run(args, check=True)
    data = temporary.read_bytes()
    if data[:6] != b'\x7fELF\x02\x01' or int.from_bytes(data[18:20], 'little') != 183:
        raise ValueError('Loader recognizer must be an ARM64 ELF executable')
    table = struct.unpack_from('<Q', data, 32)[0]
    stride, count = struct.unpack_from('<HH', data, 54)
    if any(struct.unpack_from('<I', data, table+i*stride)[0] == 3 for i in range(count)):
        raise ValueError('Loader recognizer must be statically linked')
    temporary.replace(output)
    output.chmod(0o755)
    metadata.write_text(json.dumps({'inputs': inputs, 'binary': hashlib.sha256(data).hexdigest()})+'\n')
    return output


if __name__ == '__main__':
    print(build())
