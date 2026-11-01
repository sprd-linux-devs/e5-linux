#!/usr/bin/env python3
"""Read-only USB/charging report for a connected, externally powered hub.

Run via Wi-Fi while host-sink is selected and the hub remains attached:
    python3 collect-usb-host-sink.py > /tmp/usb-host-sink.txt
Or detach from SSH, test the hub, reconnect USB and retrieve the printed log:
    python3 collect-usb-host-sink.py --background --duration 180
No mode switches, I2C transactions, debugfs mounts or hardware writes.
"""
import argparse
import errno
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import time

PATTERN = re.compile(r'usb|xhci|typec|extcon|bc1|bq256|vbus|regulator|defer|otg|phy|SGM', re.I)


def read(path, binary=False):
    try:
        raw = Path(path).read_bytes()
        return raw if binary else raw.decode(errors='replace').replace('\0', ' ').strip()
    except OSError as error:
        return 'unavailable: ' + str(error)


def fields(path, names):
    values = []
    for name in names:
        candidate = path/name
        if candidate.is_file():
            values.append(name + '=' + read(candidate))
    if values:
        print(str(path), ' -> ', str(path.resolve()), '\n  ' + '\n  '.join(values), flush=True)


def snapshot():
    print('\n=== SNAPSHOT', time.strftime('%Y-%m-%d %H:%M:%S'), '===', flush=True)
    for base, names in (
        ('/sys/class/extcon', ('name', 'state')),
        ('/sys/class/typec', ('data_role', 'power_role', 'port_type', 'orientation', 'power_operation_mode')),
        ('/sys/class/usb_role', ('role',)),
        ('/sys/class/udc', ('state', 'current_speed', 'maximum_speed')),
        ('/sys/class/power_supply', ('uevent',)),
        ('/sys/class/regulator', ('name', 'state', 'status', 'num_users', 'microvolts', 'type')),
        ('/sys/bus/usb/devices', ('product', 'manufacturer', 'bDeviceClass', 'bInterfaceClass',
                                  'idVendor', 'idProduct', 'speed', 'authorized', 'devpath')),
    ):
        print('---', base, flush=True)
        for path in sorted(Path(base).glob('*')):
            if base == '/sys/class/regulator' and not re.search(r'usb|vbus', read(path/'name'), re.I):
                continue
            if base == '/sys/class/power_supply':
                keep = ('NAME', 'STATUS', 'ONLINE', 'USB_TYPE', 'CAPACITY',
                        'VOLTAGE_NOW', 'CURRENT_NOW', 'INPUT_CURRENT_LIMIT')
                data = [line for line in read(path/'uevent').splitlines()
                        if line.partition('=')[0] in {'POWER_SUPPLY_'+key for key in keep}]
                print(path.name + ': ' + ' | '.join(data), flush=True)
                continue
            fields(path, names)
    print('--- PLATFORM USB POLICY', flush=True)
    for path in sorted(Path('/sys/bus/platform/devices').glob('*')):
        fields(path, ('usb_role_policy', 'usb_role', 'usb_host_sink_supported',
                      'typec_cc_polarity_role', 'typec_cc_vendor'))
        if re.search(r'usb|dwc3|ssphy|xhci', path.name, re.I):
            fields(path, ('power/runtime_status', 'power/control'))
    print('--- I2C CHARGER BINDING', flush=True)
    for path in sorted(Path('/sys/bus/i2c/devices').glob('*-*')):
        if 'bq256' not in read(path/'name'):
            continue
        print(path, read(path/'name'), 'driver=' +
              (str((path/'driver').resolve()) if (path/'driver').is_symlink() else 'UNBOUND'))
    print('--- USB DEBUG MODE (if already available)', flush=True)
    for path in sorted(Path('/sys/kernel/debug/usb').glob('*/mode')):
        print(path, read(path))
    print('--- xHCI PORT STATUS (read only)', flush=True)
    for path in sorted(Path('/sys/kernel/debug/usb/xhci').glob('*/ports/*/portsc')):
        print(path, read(path), flush=True)
    print('--- DEFERRED PROBES\n' + read('/sys/kernel/debug/devices_deferred'), flush=True)


def main(duration=None, interval=3):
    print('USB host + external power diagnostics (read-only)', flush=True)
    print(os.uname(), flush=True)
    for name in ('/etc/e5/device-profile', '/etc/e5/release.json', '/proc/uptime'):
        print(name, '\n' + read(name), flush=True)
    print('=== USB / CHARGER MODULES ===', flush=True)
    for line in read('/proc/modules').splitlines():
        if re.search(r'bq256|dwc3|xhci|typec|bc1p2|ssphy|extcon|usb|ax88179|r8152', line, re.I):
            print(line)
    print('=== LOADED MODULE IDENTITIES ===', flush=True)
    for path in sorted(Path('/sys/module').glob('*')):
        if re.search(r'bq256|dwc3|bc1p2|ssphy|sc27xx_typec', path.name, re.I):
            fields(path, ('srcversion', 'version', 'refcnt', 'taint'))
    print('=== INSTALLED FILE HASHES (a temporary module may differ) ===', flush=True)
    for path in Path('/lib/modules/'+os.uname().release).rglob('*.ko'):
        if not re.search(r'bq256|dwc3|bc1p2|ssphy|sc27xx.typec', path.name, re.I):
            continue
        raw = read(path, binary=True)
        if isinstance(raw, bytes):
            print(hashlib.sha256(raw).hexdigest(), path)
    kernel_btf = Path('/sys/kernel/btf/vmlinux')
    if kernel_btf.is_file():
        raw = read(kernel_btf, binary=True)
        if isinstance(raw, bytes):
            print('KERNEL_BTF_SHA256', hashlib.sha256(raw).hexdigest())
    fd = None
    if duration is not None:
        try:
            fd = os.open('/dev/kmsg', os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
            os.lseek(fd, 0, os.SEEK_END)
        except OSError as error:
            if fd is not None:
                os.close(fd)
                fd = None
            print('Live kernel log unavailable:', error, flush=True)
    deadline = time.monotonic() + (duration if duration is not None else 4)
    try:
        while True:
            if fd is not None:
                drain_kernel_log(fd)
            snapshot()
            if duration is not None and fd is None:
                command_log('dmesg', 80)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(interval if duration is not None else 2, remaining))
    finally:
        if fd is not None:
            drain_kernel_log(fd)
            os.close(fd)
    for command in ('dmesg', 'logread'):
        command_log(command)
    print('\n=== FINISHED: collector exited automatically ===', flush=True)


def drain_kernel_log(fd):
    # Each reader has its own cursor. Reading does not clear the kernel log.
    for _ in range(2048):
        try:
            raw = os.read(fd, 65536)
        except BlockingIOError:
            break
        except OSError as error:
            if error.errno == errno.EPIPE:  # Kernel ring overwrote an old record.
                continue
            print('Kernel log read:', error, flush=True)
            break
        if not raw:
            break
        message = raw.decode(errors='replace')
        if PATTERN.search(message):
            print('KMSG', message.rstrip(), flush=True)


def command_log(command, limit=200):
    print('\n=== ' + command + ' (USB-related tail) ===', flush=True)
    try:
        result = subprocess.run([command], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, errors='replace', timeout=10)
        selected = [line for line in result.stdout.splitlines() if PATTERN.search(line)]
        print('\n'.join(selected[-limit:]), flush=True)
    except (OSError, subprocess.TimeoutExpired) as error:
        print(command, error, flush=True)


def cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--background', action='store_true', help='Detach from SSH and record to /tmp')
    parser.add_argument('--watch', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--duration', type=int, default=180, help='Seconds to record (1-300, default 180)')
    args = parser.parse_args()
    if not 1 <= args.duration <= 300:
        parser.error('--duration must be between 1 and 300 seconds')
    if args.background:
        output = Path('/tmp')/('usb-host-sink-'+time.strftime('%Y%m%d-%H%M%S')+'-'+str(os.getpid())+'.txt')
        # Separate session and closed SSH descriptors keep the child running
        # after unplugging USB. The parent never changes USB configuration.
        with output.open('xb') as stream:
            process = subprocess.Popen([sys.executable, '-u', str(Path(__file__).resolve()),
                '--watch', '--duration', str(args.duration)],
                stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT,
                cwd='/', start_new_session=True, close_fds=True)
        for _ in range(30):
            if output.stat().st_size or process.poll() is not None:
                break
            time.sleep(0.1)
        if process.poll() not in (None, 0):
            raise SystemExit('Collector failed; inspect '+str(output))
        print('Background capture started / 后台采集已启动: PID', process.pid)
        print('Log / 日志:', output)
        print('You may disconnect USB now. Auto-stop in', args.duration, 'seconds / 现在可拔线测试，限时自动结束。')
        return
    main(args.duration if args.watch else None)


if __name__ == '__main__':
    cli()
