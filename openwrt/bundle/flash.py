#!/usr/bin/env python3
"""OpenWrt Installer / 安装与维护助手。

  OpenWrt-Installer         choose the installation or maintenance action
  OpenWrt-Installer --tf    first install onto the **SD card**, from rooted
                            Android over adb: the first partition (or raw card) is
                            formatted and fully used for OpenWrt
  OpenWrt-Installer --data  EXPERIMENTAL userdata image; may damage Android F2FS
  OpenWrt-Installer --part  first install onto an internal eMMC partition,
                            without an SD card: the next boot shrinks userdata,
                            creates the partition and writes OpenWrt into it
  OpenWrt-Installer --update update, from the running e5-linux over the USB LAN
                            (OpenWrt settings kept; extra packages not migrated)
  OpenWrt-Installer --boot-openwrt from Android back to installed OpenWrt (adb)
  OpenWrt-Installer --check the checks and the device's files, from Android, and
                            nothing written (a dry run of the first install)

Options for the first install (asked for when not given):
  --apn APN            the carrier's APN (default: automatic, from the SIM)
  --ssid SSID          the hotspot's name (default: <device model>-OpenWrt)
  --wifi-key KEY       the hotspot's WPA2 key, 8-63 characters (default: random)
  -y                   no questions: the defaults, and yes to erasing the card

Runs on Windows, macOS and Linux with Python 3.8+ and adb (Android
platform-tools). start-installer.cmd/sh starts it. See README.md.
"""
import argparse
import gzip
import hashlib
import http.server
import io
import json
import os
from pathlib import Path
import random
import re
import runpy
import shutil
import shlex
import socket
import string
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import struct
import zlib
import uuid  # also bundled for the runtime two-stage installer in flash.exe
from types import SimpleNamespace
from decimal import Decimal, InvalidOperation, ROUND_CEILING

B = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__))
F = os.path.join(B, 'files')
SCRIPTS = os.path.join(B, 'scripts')
D = '/data/e5linux'
TMP = '/data/local/tmp'
GUI = None  # Structured observer; CLI remains independent.
SERIAL = None
ANDROID_SLOT = None
LINUX_SLOT = None

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


STEP = [0, 0]           # [this step, of how many]


def say(msg):
    # "[3/8] ..." while a run counts its steps (steps())
    if STEP[1]:
        STEP[0] += 1
        print(f'\n[{STEP[0]}/{STEP[1]}] ' + msg, flush=True)
    else:
        print('\n== ' + msg, flush=True)


def steps(n):
    STEP[0], STEP[1] = 0, n


def bar(frac, label, extra=''):
    """One line, redrawn: [#########.........]  45%  label  extra"""
    frac = max(0.0, min(1.0, frac))
    w = 28
    fill = int(frac * w)
    sys.stdout.write(f'\r   [{"#" * fill}{"." * (w - fill)}] {frac * 100:3.0f}%  {label}  {extra}   ')
    sys.stdout.flush()
    if frac >= 1.0:
        sys.stdout.write('\n')


class busy:
    """A running clock while something slow happens on the device."""
    def __init__(self, label):
        self.label = label
        self.done = threading.Event()
        self.failed = False

    def _run(self):
        t0 = time.time()
        spin = '|/-\\'
        i = 0
        while not self.done.wait(0.25):
            sys.stdout.write(f'\r   {spin[i % 4]} {self.label}  {int(time.time() - t0)} s   ')
            sys.stdout.flush()
            i += 1
        result = 'FAILED' if self.failed else 'OK'
        sys.stdout.write(f'\r   {result} {self.label}  {int(time.time() - t0)} s          \n')
        sys.stdout.flush()

    def __enter__(self):
        self.t = threading.Thread(target=self._run, daemon=True)
        self.t.start()
        return self

    def __exit__(self, *exc):
        self.failed = bool(exc[0])
        self.done.set()
        self.t.join()


def die(msg):
    if GUI:
        raise ValueError(msg)
    print('\n错误 / error: ' + msg, file=sys.stderr, flush=True)
    sys.exit(1)


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def gz_metadata(path):
    """Check gzip CRC and obtain size/hash of the complete unpacked image."""
    size = 0
    digest = hashlib.sha256()
    try:
        with gzip.open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(1 << 20), b''):
                size += len(chunk)
                digest.update(chunk)
    except (OSError, EOFError) as error:
        die(f'cannot decompress {os.path.basename(path)}: {error}')
    if not size:
        die(f'{os.path.basename(path)} contains an empty image')
    return size, digest.hexdigest()


def gz_usize(path):
    """Count the real gzip size; ISIZE wraps at 4 GiB."""
    return gz_metadata(path)[0]


def boot_json():
    with open(os.path.join(F, 'boot.json')) as f:
        return json.load(f)


def slot_api():
    helper = os.path.join(SCRIPTS, 'installer', 'boot-slots.py')
    if not os.path.isfile(helper):
        helper = os.path.join(os.path.dirname(__file__), 'boot-slots.py')
    return runpy.run_path(helper)


def storage_api():
    helper = Path(SCRIPTS) / 'installer/storage-api.py'
    if not helper.is_file():
        helper = Path(__file__).resolve().parents[2] / 'installer/backend/storage.py'
    return runpy.run_path(str(helper))


def storage_script():
    """Same READ-DESCRIPTOR implementation in Android, recovery and OpenWrt."""
    library = storage_api()['library']()
    profile = package_profile() or {}
    if profile.get('profile') != 'changxing60':
        return library + '\n'
    helper = Path(F) / 'e5-ufs-id'
    if not helper.is_file():
        raise ValueError('Package lacks UFS identity helper / 安装包缺少 UFS 身份工具')
    remote = TMP + '/e5-ufs-id-' + sha256(str(helper))[:16]
    push(str(helper), remote, 'UFS identity helper')
    su_checked('准备 UFS 身份读取工具 / preparing UFS identity reader', 'chmod 755 ' + remote)
    return 'export E5_UFS_ID_HELPER=' + shlex.quote(remote) + '\n' + library + '\n'


def current_slots():
    if ANDROID_SLOT not in ('a', 'b') or LINUX_SLOT not in ('a', 'b') or ANDROID_SLOT == LINUX_SLOT:
        raise ValueError('Android/Linux slots have not been identified')
    return ANDROID_SLOT, LINUX_SLOT


def bind_boot_image(image):
    android, linux = current_slots()
    if android == 'b' and boot_json().get('slot_roles_version', 0) < 1:
        raise ValueError('This package lacks dynamic-slot initramfs support; rebuild the package before installing from Android B')
    return slot_api()['bind_boot'](image, read_boot_control(), android)


def push_boot(work, remote):
    image = os.path.join(F, 'boot.img')
    original = boot_json()
    if sha256(image) != original['sha256']:
        raise ValueError('boot image does not match boot.json')
    with open(image, 'rb') as stream:
        payload = bind_boot_image(stream.read())
    local = os.path.join(work, 'boot-device.img')
    with open(local, 'wb') as stream:
        stream.write(payload)
    push(local, remote, 'boot.img')
    return dict(original, sha256=hashlib.sha256(payload).hexdigest(),
                android_slot=ANDROID_SLOT, linux_slot=LINUX_SLOT)


def package_profile():
    path = os.path.join(F, 'device-profile.json')
    if not os.path.isfile(path):
        return None  # Legacy E5 packages did not carry a profile manifest.
    with open(path, encoding='utf-8') as stream:
        value = json.load(stream)
    if value.get('profile') not in ('e5', 't551m', 'm8', 't512n', 'yuanhang41s', 'k1', 'lym10k', 'changxing60') or not value.get('android_models'):
        die('invalid package device profile')
    if value['profile'] == 'k1' and value['android_models'] != ['angelcare K1']:
        die('K1 package model identity differs')
    if value['profile'] == 'lym10k' and value['android_models'] != ['LYM-10K']:
        die('LYM-10K package model identity differs')
    return value


def default_hotspot_name():
    profile = package_profile()
    model = {'e5': 'E5', 't551m': 'T551M', 'm8': 'M8', 't512n': 'T512N', 'yuanhang41s': 'Yuanhang41S', 'k1': 'K1', 'lym10k': 'LYM-10K', 'changxing60': 'Changxing60'}[
        profile['profile'] if profile else 'e5']
    return model + '-OpenWrt'


def check_package():
    say('检查刷机包 / checking the package')
    bad = None
    with busy('校验文件 / verifying the files'), open(checksum_path()) as f:
        for line in f:
            want, name = line.split(None, 1)
            name = name.strip()
            if sha256(os.path.join(B, *name.split('/'))) != want:
                bad = name
                break
    if bad:
        die(f'{bad} is damaged: download the package again')
    with open(os.path.join(F, 'VERSION'), encoding='utf-8') as f:
        print('   ' + f.read().strip())


def checksum_path():
    modern = os.path.join(F, 'SHA256SUMS')
    return modern if os.path.isfile(modern) else os.path.join(B, 'SHA256SUMS')


# ------------------------------------------------------------------ adb

ADB = None
SU = None
ANDROID_BUSYBOX = None


def validate_installer_busybox(path):
    """The installer runs before OpenWrt: Android must need no ELF loader."""
    with open(path, 'rb') as stream:
        header = stream.read(64)
        if (len(header) != 64 or header[:7] != b'\x7fELF\x02\x01\x01'
                or struct.unpack_from('<HH', header, 16) != (2, 183)):
            raise ValueError('Installer BusyBox must be a static ARM64 ELF executable')
        offset = struct.unpack_from('<Q', header, 32)[0]
        entry_size, count = struct.unpack_from('<HH', header, 54)
        if entry_size != 56 or not 1 <= count <= 128 or offset < 64:
            raise ValueError('Invalid installer BusyBox program headers')
        stream.seek(offset)
        headers = stream.read(entry_size * count)
        if len(headers) != entry_size * count:
            raise ValueError('Truncated installer BusyBox program headers')
        types = [struct.unpack_from('<I', headers, n * entry_size)[0] for n in range(count)]
        if 1 not in types or any(t in (2, 3) for t in types):
            raise ValueError('Installer BusyBox must be static (no dynamic loader or libraries)')


def android_shell(script, arguments=''):
    if not ANDROID_BUSYBOX or not re.fullmatch(re.escape(TMP) + r'/e5-tools-[0-9a-f]{32}/busybox', ANDROID_BUSYBOX):
        raise ValueError('Android installer BusyBox has not been validated')
    return f'ASH_STANDALONE=1 {ANDROID_BUSYBOX} sh {script}' + (' ' + arguments if arguments else '')


def android_tools():
    """Stage the package's tools, independently of the Android root manager."""
    global ANDROID_BUSYBOX
    ANDROID_BUSYBOX = None
    local = os.path.join(F, 'busybox')
    try:
        validate_installer_busybox(local)
    except (OSError, ValueError) as error:
        die(f'{error}; download a complete installer package. Nothing was installed.')
    directory = f'{TMP}/e5-tools-{uuid.uuid4().hex}'
    path = directory + '/busybox'
    # adb uploads as shell; the random private directory becomes root-owned
    # before execution. Never chmod or execute another manager's tool directory.
    adb('shell', f'umask 077; mkdir {directory}', check=True)
    adb('push', local, path, check=True)
    want = sha256(local)
    probe = (f'for tool in sh chroot nsenter timeout sha256sum dd od blockdev '
             f'tar gzip losetup mount umount mktemp stat readlink; do '
             f'{path} --list | {path} grep -qx "$tool" || exit 1; done; '
             f'PATH=/nonexistent; hash=$(sha256sum {path}); '
             f'[ "${{hash%% *}}" = {want} ] || exit 1; echo E5_BUSYBOX_OK')
    out = su_checked('准备随包安装工具 / preparing bundled installer tools',
                     f'chown 0:0 {directory} {path}; chmod 700 {directory} {path}; '
                     f'[ "$(sha256sum {path} | cut -d " " -f1)" = {want} ]; '
                     f'ASH_STANDALONE=1 {path} sh -c ' + shlex.quote(probe))
    if 'E5_BUSYBOX_OK' not in out.splitlines():
        die('Bundled installer BusyBox is incompatible; no system or partition was installed.')
    ANDROID_BUSYBOX = path


def find_adb():
    global ADB
    names = ('tools/adb.exe', 'platform-tools/adb.exe') if sys.platform == 'win32' else (
        'tools/macos/adb', 'tools/adb', 'platform-tools/adb') if sys.platform == 'darwin' else (
        'tools/adb', 'platform-tools/adb')
    for c in (*[os.path.join(B, name) for name in names], shutil.which('adb')):
        if c and os.path.isfile(c):
            ADB = c
            return
    die('adb not found: install Android platform-tools and put adb in PATH '
        '(or unpack platform-tools next to this script)')


def adb(*args, check=False, capture=True, timeout=600):
    selected = ['-s', SERIAL] if SERIAL and args[0] != 'devices' else []
    if GUI and args[0] == 'reboot': GUI.reboot()
    r = subprocess.run([ADB, *selected, *args], stdout=subprocess.PIPE if capture else None,
                       stderr=subprocess.STDOUT if capture else None, timeout=timeout,
                       **({'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}))
    out = r.stdout.decode('utf-8', 'replace').replace('\r', '') if capture else ''
    if check and r.returncode != 0 and not (GUI and args[0] == 'reboot'):
        die(f'adb {" ".join(args[:2])} failed: {out.strip()[-300:]}')
    return out


def sh(cmd, timeout=600):
    return adb('shell', cmd, timeout=timeout)


def su(cmd, timeout=600):
    # Root authorization and applet selection are independent. Explicit
    # standalone ash keeps Android toybox and manager PATH out of installation.
    if ANDROID_BUSYBOX:
        cmd = android_shell('-c', shlex.quote(cmd))
    return adb('shell', f'{SU} -c ' + shlex.quote(cmd) if SU else cmd, timeout=timeout)


def su_checked(stage, cmd, timeout=600, effect=None):
    """Fail at the actual remote stage; adb success alone is insufficient.

    Do not print the command: settings commands can contain private values.
    The subshell's set -e catches earlier failures in a sequence too.
    """
    if GUI and effect:
        GUI.stage('transfer_install' if effect.startswith('root') else 'prepare')
        return GUI.action(effect, lambda: su_checked(stage, cmd, timeout))
    marker = '__E5_STAGE_STATUS__='
    # Commands such as head -c on a prepared partition end in NUL padding,
    # not a newline. Keep the completion record on its own line regardless.
    wrapped = f'(set -e; {cmd}); e5_stage_rc=$?; echo; echo {marker}$e5_stage_rc'
    try:
        out = su(wrapped, timeout=timeout)
    except subprocess.TimeoutExpired:
        die(f'{stage}: timed out after {timeout} seconds; check the device/adb connection')
    except OSError as error:
        die(f'{stage}: cannot run adb: {error}')
    matches = list(re.finditer(r'^' + marker + r'(\d+)\s*$', out, re.M))
    if not matches:
        die(f'{stage}: device returned no completion status (adb disconnected or su failed).\n'
            + out.strip()[-2000:])
    match = matches[-1]
    body = out[:match.start()].rstrip()
    status = int(match.group(1))
    if status:
        if 'E5_NV_PRESERVE_FAILED' in body:
            raise ValueError('E5_NV_PRESERVE_FAILED: '+body[-2000:])
        try:
            context = su('dmesg | grep -iE "mmc|sdhci|ext4|I/O error|read-only|crc|Buffer I/O" | tail -18', timeout=20)
        except (subprocess.TimeoutExpired, OSError):
            context = '(kernel diagnostics unavailable: device did not respond)'
        die(f'{stage}: failed (exit {status}).\n{body[-3000:]}\n'
            f'SD/filesystem kernel messages:\n{context.strip()[-3000:]}')
    return body


def push(local, remote, label):
    """In pieces, each checked: adb push has no resume."""
    if GUI:
        return GUI.push(lambda *args: adb(*args, check=True),
                        lambda cmd: su_checked('Transfer / 传输', cmd), local, remote)
    size = os.path.getsize(local)
    want = sha256(local)
    su(f'rm -f {remote}')
    # (16 MiB pieces: a finer bar, and a failed piece costs less)
    part = 16 << 20
    t0 = time.time()
    bar(0, label)
    n = 0
    with open(local, 'rb') as f, tempfile.TemporaryDirectory() as td:
        while True:
            data = f.read(part)
            if not data:
                break
            p = os.path.join(td, f'p{n:03d}')
            with open(p, 'wb') as o:
                o.write(data)
            rp = f'{TMP}/e5-part{n:03d}'
            for _ in range(3):
                adb('push', p, rp)
                if su(f'stat -c %s {rp}').strip() == str(len(data)):
                    break
            else:
                die(f'pushing {label} failed')
            su(f'cat {rp} >> {remote}; rm -f {rp}')
            os.remove(p)
            n += 1
            done = min(n * part, size)
            rate = done / max(time.time() - t0, 0.1) / 1048576
            bar(done / size, label, f'{done >> 20}/{size >> 20} MiB  {rate:.1f} MiB/s')
    with busy('校验 / verifying'):
        ok = su(f'sha256sum {remote}').split()[0:1] == [want]
    if not ok:
        die(f'{label} arrived damaged')


def od_hex(path_or_cmd):
    return su(f'dd if=/dev/block/by-name/misc bs=1 skip=2048 count=32 2>/dev/null | od -An -tx1 -v').replace(' ', '').replace('\n', '')


def arm_slot_b():
    if GUI: return GUI.action('misc-trial', _arm_slot_b)
    return _arm_slot_b()


def _arm_slot_b():
    # Derive metadata from this device, not the package author's misc snapshot.
    before = read_boot_control()
    android = ANDROID_SLOT or slot_api()['validate_control'](before)
    linux = 'b' if android == 'a' else 'a'
    current, target = (12, 14) if android == 'a' else (14, 12)
    trial = bytearray(before)
    trial[:4] = ('_' + linux).encode() + b'\0\0'
    trial[current] = (before[current] & 0xf0) | 14
    trial[target] = 0x2f
    trial[28:] = struct.pack('<I', zlib.crc32(trial[:28]))
    with tempfile.TemporaryDirectory() as work:
        local = os.path.join(work, 'trial.bin')
        with open(local, 'wb') as stream:
            stream.write(trial)
        push(local, f'{TMP}/e5-bc-b.bin', 'boot control')
    expected = hashlib.sha256(before).hexdigest()
    wanted = hashlib.sha256(trial).hexdigest()
    command = (
        'umask 077; mkdir -p /data/adb/e5-boot-control; '
        'backup=$(mktemp /data/adb/e5-boot-control/before.XXXXXX); '
        'dd if=/dev/block/by-name/misc of="$backup" bs=1 skip=2048 count=32; '
        f'[ "$(sha256sum "$backup" | cut -d " " -f1)" = {expected} ]; sync; '
        'if dd if=/data/local/tmp/e5-bc-b.bin of=/dev/block/by-name/misc '
        'bs=1 seek=2048 count=32 conv=notrunc,fsync && '
        f'[ "$(dd if=/dev/block/by-name/misc bs=1 skip=2048 count=32 2>/dev/null | sha256sum | cut -d " " -f1)" = {wanted} ]; '
        'then echo "Boot control backup: $backup"; '
        'else dd if="$backup" of=/dev/block/by-name/misc bs=1 seek=2048 count=32 conv=notrunc,fsync; '
        f'[ "$(dd if=/dev/block/by-name/misc bs=1 skip=2048 count=32 2>/dev/null | sha256sum | cut -d " " -f1)" = {expected} ] || '
        'echo "RESTORE FAILED: do not reboot; inspect misc and $backup"; exit 1; fi; '
        f'rm -f {TMP}/e5-bc-b.bin')
    print(su_checked(f'设置 {linux.upper()} 槽试启动 / arming slot {linux.upper()}', command))


def validate_boot_control(data):
    slot_api()['validate_control'](data, ANDROID_SLOT)
    return data


def read_boot_control():
    try:
        return validate_boot_control(bytes.fromhex(od_hex(None)))
    except ValueError as error:
        die(f'boot control check failed: {error}')


def bootchain(mode):
    if GUI and mode == 'sync': return GUI.action('bootchain-sync', lambda: _bootchain(mode))
    return _bootchain(mode)


def _bootchain(mode):
    if mode not in ('check', 'sync'):
        raise ValueError(mode)
    script = f'{TMP}/e5-android-bootchain.sh'
    push(os.path.join(F, 'android-bootchain.sh'), script, 'boot-chain checks')
    # Absolute validated path avoids Android toybox and root-manager PATH differences.
    result = su_checked('检查启动链 / checking boot chain' if mode == 'check' else
                        '备份并同步启动链 / backing up and syncing boot chain',
                        android_shell(script, mode), timeout=600)
    print(result)


def install_preflight():
    read_boot_control()
    android, linux = current_slots()
    image = os.path.join(F, 'boot.img')
    if os.path.getsize(image) != device_size('/dev/block/by-name/boot_' + linux):
        die('boot image/target boot partition size mismatch; nothing formatted')
    if sha256(image) != boot_json()['sha256']:
        die('boot image does not match boot.json')
    if android == 'b' and boot_json().get('slot_roles_version', 0) < 1:
        die('package initramfs does not support dynamic slots; rebuild before installing from Android B')
    bootchain('check')


def android_checks():
    global SU, SERIAL, ANDROID_BUSYBOX, ANDROID_SLOT, LINUX_SLOT
    SU = ANDROID_BUSYBOX = None
    ANDROID_SLOT = LINUX_SLOT = None
    say('连接设备 / looking for Android (USB debugging on)')
    devs = [l for l in adb('devices').splitlines()[1:] if l.strip().endswith('\tdevice')]
    if not SERIAL and len(devs) > 1 and sys.stdin.isatty() and not GUI:
        for index, line in enumerate(devs, 1):
            print(f'   {index}. device / 设备 ••••{line.split()[0][-4:]}')
        selected = ask('Select device number / 选择设备编号: ')
        if not selected.isdigit() or not 1 <= int(selected) <= len(devs):
            die('invalid device selection; use --serial SERIAL / 请选择有效设备，或使用 --serial 指定')
        SERIAL = devs[int(selected)-1].split()[0]
    if SERIAL: devs = [line for line in devs if line.split()[0] == SERIAL]
    if len(devs) != 1:
        die(f'need one selected device (found {len(devs)}); use --serial SERIAL and allow USB debugging / 请用 --serial 指定设备，并允许调试')
    # Engineering Android may already run adbd as root. Its AOSP su uses
    # positional UIDs, so probing only Magisk's `su -c` rejects a valid session.
    if sh('id -u').strip() == '0':
        SU = ''
    else:
        for s in ('su', '/debug_ramdisk/su', '/sbin/su'):
            if re.search(r'\buid=0\b', sh(f'{s} -c id')):
                SU = s
                break
    if SU is None:
        die('no root: grant Shell superuser access in Magisk or KernelSU/KSUNext')
    profile = package_profile()
    if profile:
        model = sh('getprop ro.product.model').strip()
        board = sh('getprop ro.product.device').strip()
        if GUI and hasattr(GUI, 'confirm_device_model'):
            GUI.confirm_device_model(profile, model, board)
        else:
            expected_board = {'changxing60': 'P720S20', 'k1': 'ums9157_2h10',
                              'yuanhang41s': 'P720S11', 'lym10k': 'RY5G'}.get(profile['profile'])
            if (model not in profile['android_models'] or
                    expected_board and board != expected_board):
                print('Model mismatch / 机型不匹配: package / 安装包 = ' + profile['profile'] +
                      '; device / 设备 = ' + model + ' (' + board + ')')
                print('Display, charging or boot may not work. / 屏幕、充电或启动可能不兼容。')
                if ask('Type yes to continue with this package / 输入 yes 仍使用此安装包: ').strip() != 'yes':
                    die('Model exception declined; nothing written / 未确认机型例外，尚未写入设备')
    suffix = sh('getprop ro.boot.slot_suffix').strip()
    if suffix not in ('_a', '_b'):
        die('Android slot is unavailable; nothing written')
    ANDROID_SLOT = suffix[1:]
    LINUX_SLOT = 'b' if ANDROID_SLOT == 'a' else 'a'
    if 'ok' not in su(f'[ -e /dev/block/by-name/boot_{LINUX_SLOT} ] && [ -e /dev/block/by-name/l_agdsp_{ANDROID_SLOT} ] && echo ok'):
        die('target boot or Android audio firmware partition missing')
    android_tools()
    print(f'   ok ({sh("getprop ro.product.model").strip()}, root via {SU or "adbd"})')


# ------------------------------------------------------ the device's files

def pull_device_files(work, out=None):
    """The firmware off Android, converted here; the vendor subset collected
    and everything packed on the device (collect-device-files.sh), into out
    (the install's device-files.tar by default)."""
    out = out or f'{D}/device-files.tar'
    if GUI:GUI.stage('firmware_extract')
    say('从这台设备提取固件和基带文件 / the firmware and baseband files of this device')
    st = f'{TMP}/e5pull'
    su(f'rm -rf {st}; mkdir -p {st}')
    board = (package_profile() or {}).get('profile') == 'yuanhang41s'
    changxing = (package_profile() or {}).get('profile') == 'changxing60'
    pskey = 'bt_configure_pskey.ini' if board else 'bt_configure_pskey.xpe.ini'
    rf = 'bt_configure_rf.ini' if board else 'bt_configure_rf.xpe.ini'
    amplifier = 'aw883xx_acf.bin' if board else 'aw87xxx_acf.bin'
    wanted = ['/odm/firmware/wcnmodem.bin', '/odm/firmware/gnssmodem.bin',
              '/odm/firmware/'+pskey, '/odm/firmware/'+rf,
              '/mnt/vendor/btmac.txt', '/vendor/firmware/'+amplifier,
              '/odm/etc/audio_params/sprd/audio_structure.xml',
              '/odm/etc/audio_params/sprd/codec.xml',
              '/odm/etc/audio_params/sprd/dsp_vbc.xml', '/odm/etc/audio_params/sprd/cvs.xml']
    if board:
        wanted += ['/vendor/firmware/sitronix_firmware_huaying.dump',
                   '/vendor/firmware/awinic_params.bin', '/odm/etc/audio_route.xml',
                   '/odm/etc/audio_params/sprd/audio_pga.xml']
    if changxing:
        wanted += ['/odm/etc/audio_config.xml', '/odm/etc/audio_route.xml', '/odm/etc/audio_params/sprd/audio_pga.xml', '/vendor/firmware/axs_firmware_easyquick.bin']
    wanted += ['/odm/firmware/' + n for n in su('ls /odm/firmware/').split()
               if n.startswith('wifi_board_config') and n.endswith('.ini')]
    for p in wanted:
        su(f'cp -f {p} {st}/ 2>/dev/null')
    # optional on some units (a dangling link on this one)
    su(f'cp -f /vendor/firmware/tsx_data {st}/ 2>/dev/null')
    su(f'dd if=/dev/block/by-name/l_agdsp_{ANDROID_SLOT} of={st}/l_agdsp_a.img bs=1M count=6 2>/dev/null; chmod -R a+r {st}')
    raw = os.path.join(work, 'raw')
    os.makedirs(raw)
    names = su(f'ls {st}').split()
    for i, n in enumerate(names):
        adb('pull', f'{st}/{n}', os.path.join(raw, n), check=True)
        bar((i + 1) / len(names), '固件 / firmware', n)
    su(f'rm -rf {st}')
    need = ['wcnmodem.bin', pskey, rf, 'btmac.txt',
            'l_agdsp_a.img', 'audio_structure.xml', 'dsp_vbc.xml', 'cvs.xml']
    if board:
        need += [amplifier,'sitronix_firmware_huaying.dump','audio_route.xml','audio_pga.xml']
    if changxing:
        need += ['audio_config.xml','audio_route.xml','audio_pga.xml','axs_firmware_easyquick.bin',amplifier,'codec.xml']
    for n in need:
        if not os.path.isfile(os.path.join(raw, n)):
            die(f'this device has no {n}: not an E5, or a different firmware')
    img = os.path.join(raw, 'l_agdsp_a.img')
    with open(img, 'rb') as f:
        head = f.read(11)
    if os.path.getsize(img) < 6291456 or not head.startswith(b'SharkL5_AUD'):
        die('the audio DSP image (l_agdsp_a) is not the expected one')

    fw = os.path.join(work, 'lib', 'firmware')
    os.makedirs(os.path.join(fw, 'sprd'))
    for n in os.listdir(raw):
        if n in ('wcnmodem.bin', 'gnssmodem.bin', amplifier, 'tsx_data', 'l_agdsp_a.img', 'codec.xml') or \
                (board and n in ('sitronix_firmware_huaying.dump','awinic_params.bin','audio_route.xml','audio_pga.xml')) or \
                (n.startswith('wifi_board_config') and n.endswith('.ini')):
            shutil.copy(os.path.join(raw, n), fw)
    if changxing:
        for name in ('audio_config.xml','audio_route.xml','audio_pga.xml'):
            shutil.copyfile(Path(raw)/name, Path(fw)/('changxing60-'+name))
        target = Path(fw)/'axs15205'; target.mkdir()
        shutil.copyfile(Path(raw)/'axs_firmware_easyquick.bin', target/'easyquick.bin')
    tools = os.path.join(SCRIPTS, 'tools')
    bt = (os.path.join(tools, 'sprd-bt-config.py'), os.path.join(raw, pskey),
          os.path.join(raw, rf), os.path.join(raw, 'btmac.txt'), os.path.join(fw, 'sprd'))
    vbc = (os.path.join(tools, 'vbc-profile', 'vbc-profile.py'), os.path.join(raw, 'dsp_vbc.xml'),
           os.path.join(raw, 'audio_structure.xml'), os.path.join(raw, 'cvs.xml'), '-o', fw)
    if GUI:
        GUI.run_tool(*bt)
        GUI.run_tool(*vbc)
    else:
        subprocess.run(python_tool(*bt), check=True)
        subprocess.run(python_tool(*vbc), check=True, stdout=subprocess.DEVNULL)
    for n in ('sprd/marlin3lite_pskey.bin', 'sprd/marlin3lite_rf.bin', 'audio_structure', 'dsp_vbc', 'cvs'):
        if not os.path.isfile(os.path.join(fw, *n.split('/'))):
            die(f'converting the firmware made no {n}')
    if board:
        generator = os.path.join(tools,'yuanhang41s-audio-routes.py')
        ucm, gain = runpy.run_path(generator)['generate'](
            Path(raw)/'audio_route.xml', Path(raw)/'audio_pga.xml', Path(tools)/'yuanhang41s-HiFi.base.conf')
        Path(fw,'yuanhang41s-HiFi.conf').write_text(ucm,encoding='utf-8',newline='\n')
        Path(fw,'yuanhang41s-media-max').write_text(str(gain)+'\n',encoding='utf-8',newline='\n')

    def root(t):
        t.uid = t.gid = 0
        t.uname = t.gname = 'root'
        t.mode = (t.mode | 0o644) if t.isfile() else (t.mode | 0o755)
        return t
    fwtar = os.path.join(work, 'firmware.tar')
    with tarfile.open(fwtar, 'w', format=tarfile.GNU_FORMAT) as t:
        t.add(os.path.join(work, 'lib'), 'lib', filter=root)
        if board:
            item = tarfile.TarInfo('lib/firmware/sitronix/st7123.bin')
            item.type = tarfile.SYMTYPE; item.linkname = '../sitronix_firmware_huaying.dump'; item.mode = 0o777
            t.addfile(item)
        android, _ = current_slots()
        for name, data in slot_api()['role_files'](read_boot_control(), android).items():
            item = tarfile.TarInfo(name); item.uid = item.gid = 0; item.mode = 0o644; item.size = len(data)
            t.addfile(item, io.BytesIO(data))
    adb('push', fwtar, f'{TMP}/e5-firmware.tar', check=True)
    adb('push', os.path.join(F, 'collect-device-files.sh'), f'{TMP}/e5-collect.sh', check=True)
    with busy('在手机上打包 vendor 文件 / packing the vendor files on the phone'):
        res = su(f'mkdir -p {os.path.dirname(out)}; sh {TMP}/e5-collect.sh {out} {TMP}/e5-firmware.tar; rm -f {TMP}/e5-collect.sh')
    if 'E5-COLLECT-OK' not in res:
        die('collecting the device files failed: ' + res.strip()[-300:])
    return res.split('E5-COLLECT-OK')[-1].strip()


# ------------------------------------------------------------------ modes

def python_tool(*argv):
    """A command that runs one of the package's helper scripts.

    Frozen (flash.exe) there is no Python on the machine, so the executable
    re-enters itself: --run-tool executes the bundled script with its own
    interpreter and passes the remaining arguments through.
    """
    if getattr(sys, 'frozen', False):
        return [sys.executable, '--run-tool', *argv]
    return [sys.executable, argv[0], *argv[1:]]


def ask(prompt, default=''):
    try:
        v = input(prompt).strip()
    except EOFError:
        v = ''
    return v or default


def confirm(prompt, word='yes'):
    """A typed confirmation: anything but the word is a no."""
    try:
        v = input(prompt).strip()
    except EOFError:
        v = ''
    return v.lower() == word


def choose_install_action(a):
    print('''
OpenWrt Installer / 安装助手
  1. Install to TF card / TF 卡首次安装（清空第一分区，无分区则整卡）
  2. Install to internal storage / 缩容 userdata 安装
  3. Reinstall internal system / 覆盖重装已有内置系统
  4. Resume internal installation / 继续加密 data 的两阶段安装
  5. Boot OpenWrt once / 临时启动已安装的 OpenWrt（启动异常可修复，无需重装）
  6. Update OpenWrt / 更新已运行的 OpenWrt
  7. Install to userdata image [EXPERIMENTAL] / userdata 镜像安装【实验性：可能损坏 Android F2FS，仅未加密 data】
  0. Exit / 退出
''')
    choice = ask('Choose / 请选择 [0]: ', '0')
    modes = {'1': 'tf', '2': 'part', '3': 'reinstall_part',
             '5': 'boot_openwrt', '6': 'update', '7': 'data'}
    if choice == '0':
        return False
    if choice == '4':
        path = ask('Transaction JSON / 续装 transaction.json 路径: ').strip('"')
        if not path:
            return False
        a.resume_part = path
    elif choice in modes:
        setattr(a, modes[choice], True)
    else:
        die('unknown menu choice / 无效选项')
    return True


def device_sd():
    """The removable card's block device: the mmcblk device that is not the one
    Android's partitions live on (userdata, misc).  "Removable" cannot be asked
    of this controller -- both mmcblk devices report 0 -- so it is told apart by
    what it carries."""
    emmc = su_checked('识别内部存储 / identifying internal storage', storage_script()+'e5_storage_disk').strip()
    if not re.fullmatch(r'mmcblk[0-9]+|sd[a-z]+',emmc):
        die('cannot establish internal storage')
    devs = [d for d in su('for d in /sys/class/block/mmcblk*; do n=${d##*/}; '
                          'case $n in *p[0-9]*|*boot*) continue;; esac; '
                          f'[ $n = {emmc} ] && continue; echo $n; done').split()
            if d.startswith('mmcblk')]
    if len(devs) != 1:
        die('expected one SD card, found %d (%s): is a card in the slot?'
            % (len(devs), ' '.join(devs) or 'none'))
    return '/dev/block/' + devs[0]


def device_size(dev):
    out = su_checked(f'读取容量 / reading capacity of {dev}', 'blockdev --getsize64 %s' % dev).strip()
    if not out.isdigit() or int(out) <= 0:
        die(f'cannot determine the capacity of {dev}: {out!r}')
    return int(out)


def sd_device_numbers(dev):
    name = dev.rsplit('/', 1)[-1]
    out = su_checked('读取 SD 分区设备号 / reading SD device numbers',
                     f'for p in /sys/class/block/{name} /sys/class/block/{name}p*; do '
                     '[ -f "$p/dev" ] && cat "$p/dev"; done; true')
    numbers = {line.strip() for line in out.splitlines() if re.fullmatch(r'\d+:\d+', line.strip())}
    if not numbers:
        die(f'cannot read SD block device numbers for {dev}; refusing to change its partition table')
    return numbers


def unmount_android_sd(dev):
    """After erase confirmation, ask vold to release only this card's volumes."""
    numbers = sd_device_numbers(dev)
    volumes = su_checked('检查 Android SD 卷 / checking Android SD volumes', 'sm list-volumes all')
    for line in volumes.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[0].split(':', 1)[-1].replace(',', ':') in numbers and fields[1] == 'mounted':
            volume = fields[0]
            if not re.fullmatch(r'(public|private):\d+,\d+', volume):
                continue
            su_checked(f'卸载 Android SD 卷 / unmounting {volume}', f'sm unmount {volume}')
    # mountinfo uses major:minor, while vold names volumes major,minor.
    remaining = []
    for line in su_checked('检查 SD 卸载结果 / checking SD mounts',
                           'cat /proc/self/mountinfo /proc/1/mountinfo').splitlines():
        fields = line.split()
        if len(fields) >= 5 and fields[2] in numbers:
            remaining.append(fields[4])
    if remaining:
        die(f'{dev} is still mounted at {", ".join(remaining)}. '
            'Unmount the SD volume in Android storage settings (leave the card inserted) '
            'and retry. The partition table was not changed.')
    name = dev.rsplit('/', 1)[-1]
    holders = su_checked('检查 SD 映射占用 / checking SD device-mapper holders',
                         f'for p in /sys/class/block/{name}/holders/* /sys/class/block/{name}p*/holders/*; do '
                         '[ ! -e "$p" ] || echo "$p"; done; true').strip()
    if holders:
        die(f'{dev} still has active mapped devices: {holders}. No partition was changed.')


def install_sd(a):
    """The default first install: OpenWrt onto the SD card.

    The existing first partition is used in full; an unpartitioned card uses
    its whole device. No GPT changes or alternate OTA roots are made. Only the
    selected target is erased. Firmware and root readback precede boot writes.
    """
    steps(9)
    find_adb()
    android_checks()
    bj = boot_json()
    install_preflight()
    sd = device_sd()
    push(os.path.join(F, 'android-tf.sh'), f'{TMP}/e5-android-tf.sh', 'TF helper')
    part = su_checked('选择 TF 目标 / selecting TF target',
                      f'sh {TMP}/e5-android-tf.sh target {sd}').strip()
    if part not in (sd, sd + 'p1'):
        die('unexpected TF target: ' + part)
    capacity = device_size(part)
    if GUI: GUI.validate_plan(part, capacity=capacity)
    img = os.path.join(F, 'openwrt.ext4.gz')
    raw_size, raw_sha = gz_metadata(img)
    needed = raw_size
    if capacity < max(needed, 2 << 30):
        die(f'SD capacity is insufficient: {sd} has {capacity / (1 << 20):.1f} MiB; '
            f'the image requires {needed / (1 << 20):.1f} MiB '
            '(minimum supported card: 2048 MiB). Nothing was written.')
    readonly = su_checked('检查 SD 只读状态 / checking card write protection',
                          f'cat /sys/class/block/{sd.rsplit("/", 1)[-1]}/ro').strip()
    if readonly != '0':
        die(f'{sd} is read-only (ro={readonly}); cannot install. Nothing was written.')

    apn, ssid, key = a.apn, a.ssid if a.ssid is not None else default_hotspot_name(), a.wifi_key
    if not a.y:
        if apn is None:
            apn = ask('APN [自动识别 / automatic, from the SIM]: ')
        ssid = ask(f'热点名称 / hotspot name [{ssid}]: ', ssid)
        if not key:
            key = ask('热点密码 / hotspot key, 8-63 characters [random]: ')
    apn = apn or ''
    if not key:
        key = ''.join(random.SystemRandom().choice('abcdefghjkmnpqrstuvwxyz23456789') for _ in range(10))
    if not 8 <= len(key) <= 63 or "'" in key or "'" in ssid or "'" in apn:
        die("the hotspot key must have 8-63 characters, and no ' anywhere")

    say(f'准备 SD 卡 / preparing the card ({sd})')
    print(f'   {part}  {capacity / (1 << 30):.2f} GiB; no OTA space reserved')
    if not a.y:
        print('   OpenWrt 会清空所选 TF 目标并使用其全部容量；不修改分区表。')
        print('   All data on the selected TF target is erased; its partition table is unchanged.')
        if not confirm('   输入 yes 继续 / type yes to continue: '):
            die('aborted: nothing was written, the card is untouched')

    with tempfile.TemporaryDirectory() as work:
        # Complete firmware conversion and upload all payloads BEFORE erasing
        # the card. A missing vendor file must not destroy a working SD install.
        size = pull_device_files(work, f'{TMP}/e5-device-files.tar')
        push(img, f'{TMP}/openwrt.ext4.gz', 'openwrt.ext4.gz')
        bj = push_boot(work, f'{TMP}/e5-boot.img')
        push(os.path.join(F, 'ext4-tools.tar'), f'{TMP}/e5-tf-ext4-tools.tar', 'ext4 tools')
        su_checked('检查 TF 工具 / checking TF tools', 'command -v blockdev >/dev/null')
        unmount_android_sd(sd)
        bootchain('sync')
        # Revalidate selection and geometry after vold releases the card.
        selected = su_checked('重新检查 TF / rechecking TF target',
                              f'sh {TMP}/e5-android-tf.sh target {sd}').strip()
        if selected != part or device_size(part) != capacity:
            die('TF target changed after preflight; no image was written')

        say('写入 OpenWrt / OpenWrt -> the card')
        with busy('解压到 SD 卡 / unpacking onto the card'):
            su_checked('解压并写入 SD / decompressing image onto card',
                       f'gzip -dc {TMP}/openwrt.ext4.gz > {part}; sync', timeout=1800, **({'effect': 'root-tf-write'} if GUI else {}))
        with busy('回读校验完整 SD 镜像 / verifying complete SD image'):
            su_checked('SD 镜像回读校验 / SD image readback verification',
                       f'blockdev --flushbufs {part}; '
                       f'[ "$(head -c {raw_size} {part} | sha256sum | cut -d " " -f1)" = {raw_sha} ]',
                       timeout=900)
        su(f'rm -f {TMP}/openwrt.ext4.gz')
        with busy('检查并扩容到 TF 目标全部容量 / checking and growing TF filesystem'):
            su_checked('扩容 TF / growing TF filesystem',
                       f'sh {TMP}/e5-android-tf.sh grow {part} {TMP}/e5-tf-ext4-tools.tar '
                       f'{TMP}/e5-tf-tools-{uuid.uuid4().hex}', timeout=1800, **({'effect': 'root-tf-grow'} if GUI else {}))

        say('这台设备的文件和首次启动设置 / this device\'s files and the first boot\'s settings')
        conf = os.path.join(work, 'install.conf')
        with open(conf, 'w', encoding='utf-8', newline='\n') as f:
            f.write('# the flash package (flash.py), for OpenWrt\'s first boot\n'
                    f"E5_APN='{apn}'\nE5_WIFI_SSID='{ssid}'\nE5_WIFI_KEY='{key}'\n"
                    "E5_WIFI_CHANNEL='149'\nE5_DEFAULT_BOOT='linux'\n")
        mark = os.path.join(work, 'sd-root')
        with open(mark, 'w', newline='\n') as f:
            f.write('e5-openwrt-sd %s %s\n' % (time.strftime('%Y-%m-%d'), bj['sha256'][:12]))
        adb('push', conf, f'{TMP}/e5-install.conf', check=True)
        adb('push', mark, f'{TMP}/e5-sd-root', check=True)
        m = f'{TMP}/e5sd'
        su(f'umount {m} 2>/dev/null')
        su_checked('挂载 SD 根分区 / mounting root partition',
                   f'mkdir -p {m}; mount -t ext4 {part} {m}')
        with busy('在卡上写设置和设备文件 / writing the settings and the device files'):
            su_checked('写入设置和设备固件 / writing settings and device firmware',
               f'mkdir -p {m}/etc/e5; '
               f'mv {TMP}/e5-install.conf {m}/etc/e5/install.conf; '
               f'chmod 600 {m}/etc/e5/install.conf; '
               f'mv {TMP}/e5-sd-root {m}/etc/e5/sd-root; '
               f'tar -xf {TMP}/e5-device-files.tar -C {m}; '
               f'sha256sum {TMP}/e5-device-files.tar | cut -c1-64 > {m}/etc/e5/device-files.stamp; '
               'sync', timeout=900)
        checksums = f'{TMP}/e5-sd-files.sha256'
        su_checked('记录固件校验 / hashing installed firmware',
                   f'chroot {m} /bin/busybox find /lib/firmware /opt/e5/android -type f '
                   f'-exec /bin/busybox sha256sum {{}} \\; > {checksums}; test -s {checksums}', timeout=900)
        # Reopen after a real unmount; noload avoids writing journal state while
        # verifying. Do not arm B based only on files in the writable mount.
        su_checked('只读重新挂载 SD / reopening card read-only',
                   f'sync; umount {m}; blockdev --flushbufs {part}; mount -t ext4 -o ro,noload {part} {m}')
        # Resolve absolute symlinks in the image's root, not Android's root.
        su_checked('检查镜像用户空间 / checking image userspace', f'chroot {m} /bin/busybox true')
        su_checked('回读校验固件 / verifying firmware after remount',
                   f'chroot {m} /bin/busybox sha256sum -c < {checksums}', timeout=900)
        missing = []
        for name in ('sbin/init', 'lib/firmware/wcnmodem.bin', 'opt/e5/android/vendor/bin/modem_control',
                     'etc/e5/install.conf', 'etc/e5/sd-root'):
            test = f'if ! chroot {m} /bin/busybox test -s /{name}; then echo missing-or-empty:/{name}; '
            if name in ('sbin/init', 'opt/e5/android/vendor/bin/modem_control'):
                test += f'elif ! chroot {m} /bin/busybox test -x /{name}; then echo not-executable:/{name}; '
            result = su_checked(f'检查 SD 文件 / checking /{name}', test + 'fi')
            if result:
                missing.append(result)
        if missing:
            details = su(f'df -h {m}; df -i {m}; mount | grep {m}; '
                         f'ls -ld {m}/sbin/init {m}/lib/firmware {m}/opt/e5/android/vendor/bin/modem_control')
            su(f'umount {m}')
            die(f'SD content verification failed on {part}:\n' + '\n'.join(missing) + '\n' + details)
        su_checked('卸载并同步 SD / unmounting card', f'sync; umount {m}')
        su(f'rm -f {TMP}/e5-device-files.tar {checksums}')
        print(f'   OpenWrt and {size} bytes of device files are on the card')
        print(f'   TF filesystem uses {capacity / (1 << 30):.2f} GiB; updates use the PC installer')

        say(f'写入启动镜像 / boot image -> boot_{LINUX_SLOT}')
        with busy(f'写入并校验 boot_{LINUX_SLOT} / writing and verifying boot_{LINUX_SLOT}'):
            su_checked(f'写入 boot_{LINUX_SLOT} / writing boot_{LINUX_SLOT}',
                       f'dd if={TMP}/e5-boot.img of=/dev/block/by-name/boot_{LINUX_SLOT} bs=4M; sync', **({'effect': 'boot-image'} if GUI else {}))
            ok = su(f'sha256sum /dev/block/by-name/boot_{LINUX_SLOT}').split()[0:1] == [bj['sha256']]
        if not ok:
            die('target Linux boot did not verify; Android stays as it is')
        su(f'rm -f {TMP}/e5-boot.img')

    # The boot target, explicit: e5linux/boot-os on userdata is a few bytes, and
    # it is what makes a later `--data` install win over the card again.  The root
    # filesystem itself is not on userdata. Require recording the selector
    # before arming B, rather than leaving an older userdata image selected.
    su_checked('记录 SD 启动目标 / saving SD boot target',
               f'mkdir -p {D}; rm -f {D}/boot-os-next; echo sd > {D}/boot-os; sync')
    arm_slot_b()

    say('安装完成，请手动重启进入 OpenWrt / installed; reboot manually to enter OpenWrt')
    print(f'''
  第一次启动约 2 分钟 / the first boot takes about 2 minutes.
  OpenWrt 在 SD 卡上 / OpenWrt is on the SD card ({part}).
  热点 / hotspot:  {ssid}   密码 / key:  {key}
  管理 / admin:    http://192.168.9.1  (LuCI, root / root -- 请改密码 / change it)
  回 Android:      屏幕 高级 -> 系统 -> 下次启动 Android, or: e5-next-boot android; reboot
  若启动失败，设备会在两次尝试后自动回到 Android。
  If the boot fails, the E5 falls back to Android after two tries.''')

DATA_RESERVE = 1 << 30
DATA_FIRMWARE_BUDGET = 512 << 20
DATA_ALIGNMENT = 1 << 20


def userdata_free():
    avail = su_checked('读取 userdata 可用空间 / reading userdata free space',
                       'df -k /data | tail -1').split()
    if len(avail) < 4 or not avail[3].isdigit():
        die('cannot read free space on /data')
    return int(avail[3]) * 1024


def ensure_userdata_space(selected, free, uploads):
    if selected + DATA_RESERVE + DATA_FIRMWARE_BUDGET + uploads > free:
        die('userdata free space is insufficient for the new image, temporary payloads and '
            '1 GiB Android reserve. Existing images are not deleted. Nothing was armed.')


def choose_userdata_size(a, raw_size, free, uploads):
    minimum = ((raw_size + DATA_ALIGNMENT - 1) // DATA_ALIGNMENT) * DATA_ALIGNMENT
    maximum = ((free - DATA_RESERVE - DATA_FIRMWARE_BUDGET - uploads) // DATA_ALIGNMENT) * DATA_ALIGNMENT
    print(f'   userdata 可用 / free: {free / (1 << 30):.2f} GiB; '
          f'镜像范围 / image range: {minimum / (1 << 30):.2f}–{maximum / (1 << 30):.2f} GiB')
    print('   保留至少 1 GiB 给 Android，并预留上传/固件空间；已有系统镜像不计作可回收空间。')
    if maximum < minimum:
        die('not enough userdata space for the image and safety reserve')
    value = getattr(a, 'image_size', None)
    if value is None and not a.y:
        value = ask(f'镜像大小（GiB，可输入 4 或 6.5）/ image size '
                    f'[{minimum / (1 << 30):g}]: ', str(minimum / (1 << 30)))
    if value is None:
        return minimum
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount <= 0:
            raise ValueError()
        selected = int((amount * (1 << 30) / DATA_ALIGNMENT).to_integral_value(rounding=ROUND_CEILING)) * DATA_ALIGNMENT
    except (InvalidOperation, ValueError, OverflowError):
        die('image size must be a positive number in GiB, for example 4 or 6.5')
    if not minimum <= selected <= maximum:
        die(f'image size is outside the permitted range ({minimum / (1 << 30):g}–'
            f'{maximum / (1 << 30):.3f} GiB)')
    ensure_userdata_space(selected, free, uploads)
    return selected


def stage_userdata_image(raw_size, selected):
    if raw_size % DATA_ALIGNMENT or selected % DATA_ALIGNMENT:
        die('userdata image sizes must be aligned to MiB')
    raw_mib, selected_mib = raw_size // DATA_ALIGNMENT, selected // DATA_ALIGNMENT
    if not 0 < raw_mib <= selected_mib <= 2147483647:
        die('userdata image size is outside the supported MiB range')
    script = os.path.join(F, 'userdata-image.sh')
    push(os.path.join(F, 'nv-persistence.py'), f'{TMP}/e5-nv-persistence.py', 'NV preservation')
    push(os.path.join(F, 'android-loop.sh'), f'{TMP}/e5-android-loop.sh', 'android-loop.sh')
    push(script, f'{TMP}/e5-userdata-image.sh', 'userdata-image.sh')
    command = f'E5_NV_TOKEN={uuid.uuid4().hex} sh {TMP}/e5-userdata-image.sh {raw_size} {selected} {raw_mib} {selected_mib}'
    try:
        su_checked('检查工作 NV / checking working NV', command+' --nv-check', timeout=600)
    except (ValueError, SystemExit) as error:
        if 'E5_NV_PRESERVE_FAILED' not in str(error): raise
        original_nv_recovery(str(error))
        command = 'E5_NV_POLICY=original '+command
        su_checked('准备原机 NV / preparing original NV', command+' --nv-check', timeout=600)
    su_checked('扩容和只读检查 userdata 镜像 / resizing and verifying userdata image',
               command+' --nv-ready', timeout=1800,
               **({'effect':'root-userdata-image'} if GUI else {}))


def original_nv_recovery(reason):
    """Validate/read this Android unit's originals; typed consent before use.

    Binary transfer bypasses log-printing text helpers. Nothing is written to
    the NV partitions and an absent old installer record is not a blocker.
    """
    nv = runpy.run_path(os.path.join(F, 'nv-persistence.py'))
    profile = package_profile()
    if not profile or ANDROID_SLOT not in ('a','b'): die('Cannot identify original NV model/slot')
    mapping = su_checked('识别原机 NV / identifying original NV',
        storage_script() + "disk=$(e5_storage_disk); for u in /sys/class/block/*/uevent; do n=${u%/uevent}; n=${n##*/}; [ \"$(e5_storage_parent \"$n\")\" = \"$disk\" ] || continue; "
        "awk -F= '/^PARTNAME=/{n=$2}/^DEVNAME=/{d=$2}END{print n, d}' \"$u\"; done")
    paths = {}
    for line in mapping.splitlines():
        parts = line.split()
        if len(parts)!=2 or parts[0] not in nv['NAMES']: continue
        name, dev = parts
        if name in paths or not re.fullmatch(r'(?:mmcblk[0-9]+p|sd[a-z]+)[1-9][0-9]*',dev): die('Ambiguous original NV map')
        paths[name] = '/dev/block/'+dev
    if set(paths)!=set(nv['NAMES']): die('Original NV partition map is incomplete')
    base = Path(GUI.backup_base()) if GUI else Path.home()/'e5-backups'
    directory = base/'nv-recovery'/(time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8])
    directory.mkdir(parents=True, mode=0o700)
    metadata = directory/'source/etc/e5'; metadata.mkdir(parents=True)
    (metadata/'device-profile').write_text(profile['profile'])
    (metadata/'modem-slot').write_text(ANDROID_SLOT)
    devices = {}
    for name, path in paths.items():
        script = 'test -b '+path+' && cat '+path
        local = directory/'source'/name
        count = su_checked('读取原机 NV 容量 / reading original NV capacity',
                           'cat /sys/class/block/'+path.rsplit('/',1)[-1]+'/size').strip()
        if not count.isdigit() or int(count) <= 0:
            die('Invalid original NV partition capacity / 原机 NV 分区容量无效: '+name)
        size = int(count)*512
        if GUI:
            # Metadata reads are deliberately capped at 16 MiB. NV partitions
            # are larger (50 MiB on P720S20): stream a size-bound, hash-checked
            # dd/ADB pull into the PC file, never return the whole bank as bytes.
            from backend.binary_io import pull_binary
            if GUI.adb.serial != SERIAL: die('Original NV transport device differs')
            pull_binary(GUI.adb.call, GUI.adb.shell, script, local, expected_size=size)
        else:
            command = android_shell('-c', shlex.quote(script)) if ANDROID_BUSYBOX else script
            command = f'{SU} -c '+shlex.quote(command) if SU else command
            pending = local.with_name(local.name+'.partial')
            with pending.open('xb') as output:
                result = subprocess.run([ADB,*(['-s',SERIAL] if SERIAL else []),'exec-out',command],
                    stdout=output,stderr=subprocess.PIPE,timeout=180,
                    **({'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}))
                output.flush(); os.fsync(output.fileno())
            if result.returncode: die('Original NV read failed: '+name)
            if pending.stat().st_size != size: die('Incomplete original NV read: '+name)
            pending.replace(local)
        local.chmod(0o600)
        try: nv['validate'](local,name)
        except nv['NVError']:
            die('本机原始 NV 校验失败，不能作为恢复来源；未覆盖系统 / Original NV validation failed; nothing overwritten')
        devices[name] = local
    # Android may still update runtime NV. Reject a moving source rather than
    # presenting an inconsistent snapshot as a valid original.
    for name,path in paths.items():
        expected = nv['digest'](devices[name])
        got = su_checked('校验原机 NV / validating original NV','sha256sum '+path).split()[0]
        if expected != got: die('Original NV changed while reading; retry without overriding validation')
    archive = directory/'original-nv.tar'
    with archive.open('xb') as output:
        archive.chmod(0o600); nv['factory_archive'](directory/'source',output,devices)
        output.flush(); os.fsync(output.fileno())
    accepted = GUI.confirm_nv_recovery(reason) if GUI else ask(
        '工作 NV 无法保留。使用本机原始 NV 将丢失 OpenWrt NV 修改；原始分区不变。'
        'Use original Android NV and discard OpenWrt NV changes? Type yes: ') == 'yes'
    if not accepted: die('NV recovery declined; nothing overwritten')
    push(str(archive),f'{TMP}/e5-nv-original.tar','validated original NV')


def install(a):
    # checks, device files, OpenWrt, settings, boot image, reboot
    steps(6)
    find_adb()
    android_checks()
    check_userdata_image_source()
    bj = boot_json()
    install_preflight()
    img = os.path.join(F, 'openwrt.ext4.gz')
    raw_size = gz_usize(img)
    selected = choose_userdata_size(a, raw_size, userdata_free(),
                                    os.path.getsize(img) + os.path.getsize(os.path.join(F, 'boot.img')))
    tools = os.path.join(F, 'ext4-tools.tar')
    if not os.path.isfile(tools):
        die('missing ext4-tools.tar: use the updated userdata installer package')
    su_checked('检查已有安装和待提交升级 / checking existing install and pending upgrade',
               f'test ! -L {D}; test ! -L {D}/openwrt.ext4; '
               f'test ! -e {D}/openwrt.ext4.part; test ! -L {D}/openwrt.ext4.part; '
               f'test ! -e {D}/openwrt.ext4.new; test ! -L {D}/openwrt.ext4.new')
    if not a.y:
        say("安装到 userdata（旧方式）/ installing to the phone's storage (userdata)")
        print(f'   OpenWrt 镜像 / image: {selected / (1 << 30):.2f} GiB, /data/e5linux/openwrt.ext4')
        print('   不格式化 userdata；安装完成后手动重启。已有镜像会保留为备份。')
        print('   userdata is not formatted; an existing image is kept as a backup. Reboot manually.')
        if not confirm('   确认上述计划，输入 yes 继续 / confirm this plan, type yes to continue: '):
            die('aborted: nothing was written')

    apn, ssid, key = a.apn, a.ssid if a.ssid is not None else default_hotspot_name(), a.wifi_key
    if not a.y:
        if apn is None:
            apn = ask('APN [自动识别 / automatic, from the SIM]: ')
        ssid = ask(f'热点名称 / hotspot name [{ssid}]: ', ssid)
        if not key:
            key = ask('热点密码 / hotspot key, 8-63 characters [random]: ')
    apn = apn or ''
    if not key:
        key = ''.join(random.SystemRandom().choice('abcdefghjkmnpqrstuvwxyz23456789') for _ in range(10))
    if not 8 <= len(key) <= 63 or "'" in key or "'" in ssid or "'" in apn:
        die("the hotspot key must have 8-63 characters, and no ' anywhere")

    with tempfile.TemporaryDirectory() as work:
        firmware = f'{TMP}/e5-data-device-files.tar'
        size = pull_device_files(work, firmware)
        print(f'   device-files.tar: {size} bytes')
        push(img, f'{TMP}/openwrt.ext4.gz', 'openwrt.ext4.gz')
        bj = push_boot(work, f'{TMP}/e5-boot.img')
        push(tools, f'{TMP}/e5-ext4-tools.tar', 'ext4-tools.tar')
        # Recheck after uploads/firmware collection, so Android concurrent writes
        # cannot turn the initial capacity estimate into a partial installation.
        ensure_userdata_space(selected, userdata_free(), 0)

        say(f'写入 OpenWrt / OpenWrt -> {D}/openwrt.ext4')
        with busy('创建、扩容并检查镜像 / creating, resizing and checking image'):
            stage_userdata_image(raw_size, selected)
        # The completed image was mounted read-only and checked before any
        # boot-chain write. No original Android/NV partition is formatted.
        bootchain('sync')

        say('首次启动设置 / the first boot\'s settings')
        conf = os.path.join(work, 'install.conf')
        with open(conf, 'w', encoding='utf-8', newline='\n') as f:
            f.write('# the flash package (flash.py), for OpenWrt\'s first boot\n'
                    f"E5_APN='{apn}'\nE5_WIFI_SSID='{ssid}'\nE5_WIFI_KEY='{key}'\n"
                    "E5_WIFI_CHANNEL='149'\nE5_DEFAULT_BOOT='linux'\n")
        adb('push', conf, f'{TMP}/e5-install.conf', check=True)
        su_checked('提交用户态镜像 / committing userdata image',
                   f'backup={D}/previous.$(date +%Y%m%d-%H%M%S).$$; '
                   f'if [ -e {D}/openwrt.ext4 ]; then mkdir "$backup"; '
                   f'mv {D}/openwrt.ext4 "$backup/openwrt.ext4"; '
                   f'for n in device-files.tar openwrt-install.conf; do '
                   f'[ ! -e {D}/$n ] || cp -p {D}/$n "$backup/$n"; done; fi; '
                   f'mv {D}/openwrt.ext4.part {D}/openwrt.ext4; '
                   f'mv {firmware} {D}/device-files.tar; '
                   f'mv {TMP}/e5-install.conf {D}/openwrt-install.conf; '
                   f'chmod 600 {D}/openwrt.ext4 {D}/device-files.tar {D}/openwrt-install.conf; sync')

    say(f'写入启动镜像 / boot image -> boot_{LINUX_SLOT}')
    with busy(f'写入并校验 boot_{LINUX_SLOT} / writing and verifying boot_{LINUX_SLOT}'):
        su_checked(f'写入 boot_{LINUX_SLOT} / writing boot_{LINUX_SLOT}',
                   f'dd if={TMP}/e5-boot.img of=/dev/block/by-name/boot_{LINUX_SLOT} bs=4M conv=fsync; sync',
                   **({'effect':'boot-image'} if GUI else {}))
        ok = su(f'sha256sum /dev/block/by-name/boot_{LINUX_SLOT}').split()[0:1] == [bj['sha256']]
    if not ok:
        die('target Linux boot did not verify; Android stays as it is')
    su(f'rm -f {TMP}/e5-boot.img')
    su_checked('记录 userdata 启动目标 / saving userdata boot target',
               f'rm -f {D}/boot-os-next; echo openwrt > {D}/boot-os; sync')
    arm_slot_b()

    say('安装完成，请手动重启进入 OpenWrt / installed; reboot manually to enter OpenWrt')
    print(f'''
  第一次启动约 2 分钟 / the first boot takes about 2 minutes.
  热点 / hotspot:  {ssid}   密码 / key:  {key}
  管理 / admin:    http://192.168.9.1  (LuCI, root / root -- 请改密码 / change it)
  回 Android:      屏幕 高级 -> 系统 -> 下次启动 Android, or: e5-next-boot android; reboot
  若启动失败，设备会在两次尝试后自动回到 Android。
  If the boot fails, the E5 falls back to Android after two tries.''')


def check_userdata_image_source():
    """Android can read decrypted /data while initramfs cannot. Refuse early."""
    state = sh('getprop ro.crypto.state').strip()
    kind = sh('getprop ro.crypto.type').strip()
    mounts = su_checked('检查 userdata 镜像的启动条件 / checking plaintext userdata', 'cat /proc/mounts')
    source = next((line.split()[0] for line in mounts.splitlines()
                   if len(line.split()) > 2 and line.split()[1] == '/data'), '')
    if (state != 'unencrypted' or kind in ('file', 'block') or not source.startswith('/dev/block/')
            or source.startswith(('/dev/block/dm-', '/dev/mapper/'))):
        die('userdata image requires confirmed unencrypted, unmapped /data; '
            'use TF or independent internal installation instead. No image or boot was written.')


def part_userdata_policy(a):
    """A requested wipe must be explicit, and encryption never implies consent."""
    state = sh('getprop ro.crypto.state').strip()
    kind = sh('getprop ro.crypto.type').strip()
    mounts = su_checked('检查 data 加密 / checking data encryption', 'cat /proc/mounts')
    data_source = next((line.split()[0] for line in mounts.splitlines()
                        if len(line.split()) > 2 and line.split()[1] == '/data'), '')
    encrypted = state == 'encrypted' or kind in ('file', 'block')
    metadata = data_source.startswith(('/dev/block/dm-', '/dev/mapper/'))
    encrypted = encrypted or metadata
    wipe = bool(getattr(a, 'format_userdata', False)) or encrypted
    if encrypted:
        print(f'   检测到 data 加密 / data encryption: {kind or state or "mapped block device"}; '
              '本次安装必须格式化 userdata / formatting userdata is required.')
    elif not a.y and not wipe:
        wipe = confirm('   是否格式化 userdata？这会清空 Android 所有用户数据 / '
                       'format userdata and erase ALL Android user data [no]: ', word='yes')
    if wipe:
        print('   警告 / WARNING: Android 应用、账号、照片及内部存储文件将被清空。')
        print('   ALL Android apps, accounts, photos and internal storage files will be erased.')
        # -y is the existing unattended installer confirmation, not permission
        # for a newly detected destructive operation.
        if a.y and not getattr(a, 'format_userdata', False):
            die('encrypted userdata requires --format-userdata as explicit erase consent; -y alone is insufficient')
    if wipe:
        print('   两阶段安装：重建分区 → 原厂 recovery 清空数据 → Android 重新授权 → 安装 OpenWrt。')
    a.format_userdata = wipe
    return wipe


def part_target(a, raw_size):
    """The userdata node and the sizes an internal-partition install wants."""
    probe = su_checked('读取分区 / reading the partition table', storage_script() +
        'disk=$(e5_storage_disk); n=$(e5_storage_part userdata "$disk"); '
        'echo "data $n $(cat /sys/class/block/$n/size)"; '
        'n=$(e5_storage_part e5root "$disk") && echo "part $n"; '
        'df -k /data | tail -1')
    node = data_sectors = ''
    existing = None
    used_mib = 0
    for line in probe.splitlines():
        fields = line.split()
        if len(fields) >= 3 and fields[0] == 'data':
            node, data_sectors = fields[1], fields[2]
        elif len(fields) >= 2 and fields[0] == 'part':
            existing = fields[1]
        elif len(fields) >= 4 and fields[3].isdigit():
            used_mib = int(fields[2]) // 1024
    if existing:
        die(f'the internal partition {existing} (e5root) already exists; run this installer with '
            '--reinstall-part to write a new system into it (userdata and the partition table stay, '
            'nothing is erased)')
    if not node or not data_sectors.isdigit() or int(data_sectors) == 0:
        die('userdata is not in the partition table of this device')
    udata_mib = int(data_sectors) // 2048
    image_mib = (raw_size + (1 << 20) - 1) // (1 << 20)
    minimum = image_mib + 256
    maximum = udata_mib - (0 if getattr(a, 'format_userdata', False) else used_mib) - 2048
    if maximum < minimum:
        die(f'not enough room: userdata is {udata_mib} MiB with {used_mib} MiB used, '
            f'the image needs a {minimum} MiB partition')
    value = getattr(a, 'part_size', None)
    if value is None and not a.y:
        value = ask(f'内置分区大小（GiB）/ partition size [{((image_mib + 1024) / 1024):.2f}, '
                    f'max {maximum / 1024:.2f}]: ', f'{(image_mib + 1024) / 1024:.2f}')
    if value is None:
        part_mib = min(maximum, ((image_mib + 1024 + 1023) // 1024) * 1024)
    else:
        try:
            amount = Decimal(str(value))
            if not amount.is_finite() or amount <= 0:
                raise ValueError()
            part_mib = int((amount * (1 << 30) / (1 << 20)).to_integral_value(rounding=ROUND_CEILING))
        except (InvalidOperation, ValueError, OverflowError):
            die('the partition size must be a positive number in GiB, for example 4 or 6.5')
    if not minimum <= part_mib <= maximum:
        die(f'partition size outside the permitted range ({minimum / 1024:.2f}–{maximum / 1024:.2f} GiB)')
    return node, udata_mib, used_mib, part_mib


def install_part(a):
    """Install OpenWrt onto its own eMMC partition, in space taken from
    userdata -- without an SD card.  This side only chooses the sizes, stages
    the payloads and arms the boot: the F2FS shrink and the partition table
    change happen on the next boot (boot/install-part.sh in the initramfs),
    where userdata is unmounted and only raw tools touch it."""
    steps(6)
    find_adb()
    android_checks()
    bj = boot_json()
    install_preflight()
    img = os.path.join(F, 'openwrt.ext4.gz')
    raw_size = gz_usize(img)
    wipe = part_userdata_policy(a)
    node, udata_mib, used_mib, part_mib = part_target(a, raw_size)
    if GUI: GUI.validate_plan('userdata shrink', wipe=wipe, capacity=part_mib*(1 << 20))
    data_mib = udata_mib - part_mib
    grow = int(a.grow_fs is not False)
    if not a.y:
        say("安装到内置分区 / installing to an internal partition")
        print(f'   userdata: {udata_mib / 1024:.2f} -> {data_mib / 1024:.2f} GiB, ' +
              ('清空 Android 用户数据 / erase Android user data' if wipe else 'Android 的文件保留'))
        print(f'   新分区 e5root / new partition: {part_mib / 1024:.2f} GiB（镜像 {raw_size >> 20} MiB）')
        print('   缩容与写入在下次启动由引导镜像完成。')
        print('   The shrink and the writing happen on the next boot, from the boot image;')
        print('   ' + ('userdata WILL BE FORMATTED.' if wipe else 'userdata is not formatted.') +
              ' Reboot manually when done.')
        grow = part_growth(a)
        print('   系统分配 / system allocation: ' +
              ('整个分区 / the whole partition' if grow else "镜像大小 / the image's size, about 2 GiB"))
        if not confirm('   确认上述计划，输入 yes 继续 / confirm this plan, type yes to continue: '):
            die('aborted: nothing was written')

    apn, ssid, key = a.apn, a.ssid if a.ssid is not None else default_hotspot_name(), a.wifi_key
    if not a.y:
        if apn is None:
            apn = ask('APN [自动识别 / automatic, from the SIM]: ')
        ssid = ask(f'热点名称 / hotspot name [{ssid}]: ', ssid)
        if not key:
            key = ask(f'热点密码 / hotspot key, 8-63 characters [random]: ')
    apn = apn or ''
    if not key:
        key = ''.join(random.SystemRandom().choice('abcdefghjkmnpqrstuvwxyz23456789') for _ in range(10))
    if not 8 <= len(key) <= 63 or "'" in key or "'" in ssid or "'" in apn:
        die("the hotspot key must have 8-63 characters, and no ' anywhere")

    if wipe:
        part_two_stage('start', a, node, part_mib, data_mib, grow, raw_size, apn, ssid, key)
        return

    with tempfile.TemporaryDirectory() as work:
        firmware = f'{TMP}/e5-data-device-files.tar'
        size = pull_device_files(work, firmware)
        print(f'   device-files.tar: {size} bytes')
        push(img, f'{TMP}/e5-part-install.img.gz', 'openwrt.ext4.gz')
        bj = push_boot(work, f'{TMP}/e5-boot.img')
        conf = os.path.join(work, 'part-install.settings')
        with open(conf, 'w', encoding='utf-8', newline='\n') as f:
            f.write("E5_APN='%s'\nE5_WIFI_SSID='%s'\nE5_WIFI_KEY='%s'\n"
                    "E5_WIFI_CHANNEL='149'\nE5_DEFAULT_BOOT='linux'\n" % (apn, ssid, key))
        adb('push', conf, f'{TMP}/part-install.settings', check=True)
        say(f'落位安装载荷 / staging the install -> {D}')
        su_checked('落位安装载荷 / staging the install',
                   f'umask 077; mkdir -p {D}; '
                   f'mv {TMP}/e5-part-install.img.gz {D}/part-install.img.gz; '
                   f'mv {firmware} {D}/device-files.tar; '
                   f'mv {TMP}/part-install.settings {D}/part-install.settings; '
                   f'printf "PART_MIB={part_mib}\\nDATA_MIB={data_mib}\\nGROW_FS={grow}\\nFORMAT_DATA={int(wipe)}\\n" > {D}/part-install.conf.tmp; '
                   f'mv {D}/part-install.conf.tmp {D}/part-install.conf; '
                   f'chmod 600 {D}/part-install.conf {D}/part-install.settings {D}/device-files.tar; sync')

    bootchain('sync')
    say(f'写入启动镜像 / boot image -> boot_{LINUX_SLOT}')
    with busy(f'写入并校验 boot_{LINUX_SLOT} / writing and verifying boot_{LINUX_SLOT}'):
        su_checked(f'写入 boot_{LINUX_SLOT} / writing boot_{LINUX_SLOT}',
                   f'dd if={TMP}/e5-boot.img of=/dev/block/by-name/boot_{LINUX_SLOT} bs=4M conv=fsync; sync',
                   **({'effect':'boot-image'} if GUI else {}))
        ok = su(f'sha256sum /dev/block/by-name/boot_{LINUX_SLOT}').split()[0:1] == [bj['sha256']]
    if not ok:
        die('target Linux boot did not verify; Android stays as it is')
    su(f'rm -f {TMP}/e5-boot.img')
    su_checked('记录分区启动目标 / recording the partition boot target',
               f'rm -f {D}/boot-os-next; echo part > {D}/boot-os; sync')
    arm_slot_b()

    say('安装已就绪，请手动重启 / staged; reboot manually')
    print(f'''
  首次开机需要离线检查、缩容、建分区和写入，通常数分钟；数据较多或闪存较慢时会更久。
  这不是普通开机，请保持供电，不要中断；缩容安装完成后会自动重启一次，再进入 OpenWrt。
  The next boot shrinks userdata, creates the e5root partition and writes
  OpenWrt into it, then restarts once into it -- about a few minutes.
  热点 / hotspot:  {ssid}   密码 / key:  {key}
  管理 / admin:    http://192.168.9.1  (LuCI, root / root -- 请改密码 / change it)
  回 Android:      e5-next-boot android（或删掉 {D}/boot-os）后重启；首启是试启动，
  失败会回到 Android。If the first boot fails, the next one falls back.''')


def part_growth(a):
    if a.grow_fs is not None:
        return int(a.grow_fs)
    if a.y:
        return 1
    answer = ask('   完全使用空间：扩满所选分区（选 no 则保留镜像约 2 GiB 容量）/ '
                 'use the whole partition [yes]: ', 'yes').lower()
    if answer in ('yes', 'y'):
        return 1
    if answer in ('no', 'n'):
        return 0
    die('enter yes or no / 请输入 yes 或 no')


def part_two_stage(action, *args):
    try:
        helper = os.path.join(SCRIPTS, 'installer', 'part-two-stage.py')
        if not os.path.isfile(helper):
            helper = os.path.join(B, 'part-two-stage.py')
        runpy.run_path(helper)[action](globals(), *args)
    except (ValueError, OSError) as error:
        die(str(error))


def check(a):
    steps(3)
    find_adb()
    android_checks()
    install_preflight()
    print('   free on /data: ' + su('df -k /data | tail -1').split()[3] + ' KiB')
    # packed as for an install, to see that it works, and deleted again: a
    # check leaves nothing on the device
    with tempfile.TemporaryDirectory() as work:
        size = pull_device_files(work, f'{TMP}/e5-check-device-files.tar')
    su(f'rm -f {TMP}/e5-check-device-files.tar')
    print(f'   device-files.tar: {size} bytes (a trial, deleted again)')
    say('检查完成，未修改分区 / checked; no partitions changed (temporary staging files only)')


def boot_openwrt(a):
    helper = os.path.join(SCRIPTS, 'installer', 'boot-control.py')
    if not os.path.isfile(helper):
        helper = os.path.join(B, '..', '..', 'installer', 'backend', 'boot_image.py')
    def read(command):
        # Only 4096/512-byte header metadata, never a partition backup.
        return bytes.fromhex(su(command+' | od -An -tx1 -v'))
    return runpy.run_path(helper)['boot_installed_e5'](globals(), read)


def local_ip(host):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((host, 80))
        return s.getsockname()[0]
    finally:
        s.close()


def update(a):
    if GUI: return GUI.update_e5(a)
    host = os.environ.get('E5_HOST', '192.168.9.1')
    try:
        ip = local_ip(host)
    except OSError:
        ip = ''
    if not ip.startswith('192.168.9.') and not ip.startswith('192.168.77.'):
        die("no address on the E5's USB LAN (192.168.9.x): is it connected and running OpenWrt?")
    pw = os.environ.get('E5_TELNET_PASS')
    if pw is None and (a.y or not sys.stdin.isatty()):
        pw = 'root'     # (-y: the default, not asked)
    if pw is None:
        import getpass
        pw = getpass.getpass('Device root password / 设备 root 密码 [root]: ') or 'root'
    boot_json()  # validate the package before connecting
    size, image_hash = gz_metadata(os.path.join(F, 'openwrt.ext4.gz'))
    env = dict(os.environ, E5_TELNET_PASS=pw)
    helper = python_tool(os.path.join(SCRIPTS, 'tools', 'e5-update.py'))
    say(f'更新 / updating {host} (SSH upload)')
    result = subprocess.run(helper + ['--package', B, '--host', host,
                            '--raw-size', str(size), '--raw-sha256', image_hash], env=env)
    if result.returncode:
        die('the update did not finish; see the failed step above')
    say('载荷已校验，设备正在重启执行更新 / verified, rebooting to apply update')



def main():
    global SERIAL
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument('--menu', action='store_true', help='choose an installation or maintenance action')
    g.add_argument('--tf', action='store_true', help='first install onto the existing TF first partition (whole card only if unpartitioned); erases that target')
    g.add_argument('--update', action='store_true')
    g.add_argument('--boot-openwrt', action='store_true')
    g.add_argument('--check', action='store_true')
    g.add_argument('--verify-package', action='store_true', help='verify package files without accessing a device')
    g.add_argument('--data', action='store_true',
                   help='EXPERIMENTAL userdata image: may damage Android F2FS; unencrypted data only')
    g.add_argument('--part', action='store_true',
                   help="install to an internal eMMC partition, without an SD card; "
                        "the next boot shrinks userdata and creates it")
    g.add_argument('--resume-part', metavar='TRANSACTION_JSON',
                   help='continue the encrypted-data installation after Android setup/root authorization')
    g.add_argument('--reinstall-part', action='store_true',
                   help='rewrite an existing internal partition system: userdata, its filesystem and '
                        'the partition table stay, e5root and the Linux boot slot are replaced (no wipe, no stage one)')
    ap.add_argument('--apn')
    ap.add_argument('--serial', help='bind all ADB operations to this device')
    ap.add_argument('--ssid', help='hotspot name; defaults to the package device model plus -OpenWrt')
    ap.add_argument('--wifi-key')
    ap.add_argument('--image-size', help='userdata image size in GiB (e.g. 4 or 6.5); requires --data')
    ap.add_argument('--part-size', help='internal partition size in GiB (e.g. 4 or 6.5); requires --part')
    growth = ap.add_mutually_exclusive_group()
    growth.add_argument('--grow-fs', dest='grow_fs', action='store_true',
                        help='use the whole internal partition (default)')
    growth.add_argument('--no-grow-fs', dest='grow_fs', action='store_false',
                        help='keep the initial image filesystem size instead of filling the partition')
    ap.set_defaults(grow_fs=None)
    ap.add_argument('--format-userdata', action='store_true',
                    help='erase ALL Android user data before internal-partition installation; requires --part')
    ap.add_argument('-y', action='store_true')
    ap.add_argument('--no-pause', action='store_true', help='do not wait for Enter on exit')
    ap.add_argument('--pause', action='store_true', help='wait for Enter on exit')
    a = ap.parse_args()
    SERIAL = a.serial
    if (a.menu or not any((a.tf, a.data, a.part, a.reinstall_part, a.resume_part,
                          a.update, a.boot_openwrt, a.check, a.verify_package))) and not choose_install_action(a):
        return False
    if a.image_size is not None and not a.data:
        ap.error('--image-size requires --data / install-userdata')
    if a.part_size is not None and not a.part:
        ap.error('--part-size requires --part / install-part')
    if a.grow_fs is not None and not a.part:
        ap.error('--grow-fs/--no-grow-fs requires --part / install-part')
    if a.format_userdata and not a.part:
        ap.error('--format-userdata requires --part / install-part')
    if a.reinstall_part and (a.part or a.format_userdata):
        ap.error('--reinstall-part keeps userdata and the partition table; it is not --part')
    if sys.version_info < (3, 8):
        die('Python 3.8 or newer is needed')
    check_package()
    if a.verify_package:
        print('Package verified / 安装包校验通过，未连接设备。')
    elif a.resume_part:
        part_two_stage('resume', a)
    elif a.reinstall_part:
        part_two_stage('reinstall', a)
    elif a.update:
        update(a)
    elif a.boot_openwrt:
        boot_openwrt(a)
    elif a.check:
        check(a)
    elif a.data:
        print('EXPERIMENTAL / 实验性功能：userdata 镜像模式可能破坏 Android 的 F2FS 文件系统。\n'
              "This mode may damage Android's F2FS filesystem. Prefer TF or an independent internal partition.")
        install(a)          # the legacy userdata-image method
    elif a.part:
        install_part(a)     # an internal partition; the boot image finishes it
    else:
        install_sd(a)
    return True


def run_cli():
    started = time.monotonic()
    rc, outcome = 0, 'SUCCESS / 成功'
    try:
        if main() is False:
            outcome = 'CANCELLED / 已取消'
    except KeyboardInterrupt:
        rc, outcome = 130, 'CANCELLED / 已中断，请检查当前安装阶段后再操作'
    except SystemExit as error:
        rc = error.code if isinstance(error.code, int) else 1
        if not rc:
            return 0  # argparse help
        if not isinstance(error.code, int):
            print(str(error.code), file=sys.stderr, flush=True)
        outcome = 'FAILED / 失败；请保留上方错误与备份，不要盲目重跑分区步骤'
    except Exception as error:
        rc, outcome = 1, 'FAILED / 失败'
        print('\n错误 / error: ' + str(error), file=sys.stderr, flush=True)
    print('\n' + '=' * 60)
    print(f'[{outcome}]  {time.monotonic() - started:.1f} s', flush=True)
    print('=' * 60, flush=True)
    if '--no-pause' not in sys.argv and ('--pause' in sys.argv or sys.stdin.isatty()):
        try:
            input('按 Enter 关闭 / Press Enter to close...')
        except (EOFError, KeyboardInterrupt):
            pass
    return rc


if __name__ == '__main__':
    # A frozen build has no Python beside it: the executable re-enters itself
    # to run the package's helper scripts with its bundled interpreter.
    if len(sys.argv) > 2 and sys.argv[1] == '--run-tool':
        _tool = sys.argv[2]
        sys.argv = [os.path.basename(_tool), *sys.argv[3:]]
        runpy.run_path(_tool, run_name='__main__')
        sys.exit(0)
    sys.exit(run_cli())
