#!/usr/bin/python3
"""Shared NV preservation/import and explicitly confirmed validated NV writeback.

Standalone archive helpers remain usable in old roots without the web modules.
"""
import argparse
import array
import contextlib
import errno
try:
    import fcntl
except ImportError:  # Host-side Android recovery validates regular files only.
    fcntl = None
import hashlib
import gzip
import io
import json
import os
from pathlib import Path
import re
import secrets
import signal
import shutil
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
import time

PAIRS = (('nr_fixnv1_a', 'nr_fixnv2_a'), ('nr_fixnv1_b', 'nr_fixnv2_b'),
         ('nr_runtimenv1', 'nr_runtimenv2'))

PROFILES = {'e5', 't551m', 'm8', 't512n', 'yuanhang41s', 'k1', 'lym10k', 'changxing60', 'y60'}
NAMES = ('nr_fixnv1_a', 'nr_fixnv2_a', 'nr_fixnv1_b', 'nr_fixnv2_b',
         'nr_runtimenv1', 'nr_runtimenv2', 'nr_deltanv_a', 'nr_deltanv_b', 'calinv')
METHODS = {'status': {}, 'preview': {'direction': ''},
           'sync': {'direction': '', 'token': '', 'confirmation': '', 'conflict_ack': False},
           'backups': {}, 'delete_backup': {'id': '', 'confirmation': ''},
           'compress_backup': {'id': '', 'confirmation': ''},
           'manual_backup': {}, 'prepare_download': {'id': ''}}


class NVError(RuntimeError):
    pass


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


@contextlib.contextmanager
def snapshot_reader(path):
    """New snapshots are gzip; raw paths remain readable for existing journals."""
    path = Path(path)
    compressed = path.with_name(path.name+'.gz')
    selected = compressed if compressed.exists() else path
    if any(p.is_symlink() for p in (selected, *selected.parents)): raise NVError('nv_unsafe_path')
    with (gzip.open(selected, 'rb') if selected == compressed else selected.open('rb')) as stream:
        yield stream


def verify_snapshot(path, expected, size):
    h = hashlib.sha256(); count = 0
    with snapshot_reader(path) as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            count += len(block)
            if count > size: raise NVError('nv_backup_failed')
            h.update(block)
    if count != size or h.hexdigest() != expected: raise NVError('nv_backup_failed')


def save_snapshot(source, destination):
    """Stream a byte-exact gzip snapshot; verify decompressed bytes before use."""
    source, destination = Path(source), Path(destination)
    safe_directory(destination.parent)
    compressed = destination.with_name(destination.name+'.gz')
    before = digest(source); size = storage_size(source)
    temporary = destination.with_name('.snapshot-'+secrets.token_hex(8))
    zipped_path = temporary.with_name(temporary.name+'.gz')
    try:
        with source.open('rb') as src, zipped_path.open('xb') as output:
            os.chmod(zipped_path, 0o600)
            with gzip.GzipFile(filename='', mode='wb', fileobj=output, compresslevel=3, mtime=0) as zipped:
                shutil.copyfileobj(src, zipped, 1 << 20)
            output.flush(); os.fsync(output.fileno())
        verify_snapshot(temporary, before, size)
        if digest(source) != before: raise NVError('nv_snapshot_changed')
        os.link(zipped_path, compressed)  # exclusive, atomically published
        zipped_path.unlink(); flush_directory(destination.parent)
    finally: zipped_path.unlink(missing_ok=True)
    return before


def restore_snapshot(source, destination, expected, size):
    verify_snapshot(source, expected, size)
    with snapshot_reader(source) as src, Path(destination).open('xb') as dst:
        os.chmod(destination, 0o660); shutil.copyfileobj(src, dst, 1 << 20)
        dst.flush(); os.fsync(dst.fileno())
    if digest(destination) != expected: raise NVError('nv_backup_failed')


def compact_previous(backup):
    """Drop only duplicate, verified old-working files after import commits.

The gzip snapshots are independent immutable copies. Never hard-link a live NV
file; vendor writes would then mutate its backup as well.
"""
    backup = Path(backup); previous = backup/'previous-working'
    if not previous.exists(): return
    saved = read_json(backup/'record.json')
    if saved.get('storage') != 'gzip': return
    paths = list(previous.iterdir())
    if any(p.is_symlink() or not p.is_file() for p in paths): raise NVError('nv_unsafe_path')
    for path in paths:
        if path.name in NAMES:
            expected = saved['work'][path.name]
            if digest(path) != expected: raise NVError('nv_backup_failed')
            verify_snapshot(backup/'work'/path.name, expected, path.stat().st_size)
        else:
            # Preserve provenance and any other small working-directory records.
            target = backup/'work'/path.name
            if target.with_name(target.name+'.gz').exists():
                verify_snapshot(target, digest(path), path.stat().st_size)
            else: save_snapshot(path, target)
    # All bytes can be independently recovered before removing any duplicate.
    for path in paths: path.unlink()
    previous.rmdir(); flush_directory(backup)


def flush_directory(path):
    if os.name == 'nt': return  # host staging; Windows has no O_DIRECTORY
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)


def storage_size(path):
    path = Path(path)
    if stat.S_ISBLK(path.stat().st_mode):
        with path.open('rb') as stream:
            return struct.unpack('Q', fcntl.ioctl(stream, 0x80081272, bytes(8)))[0]
    return path.stat().st_size


def atomic_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name('.' + path.name + '.' + secrets.token_hex(8))
    try:
        with temp.open('x', encoding='utf-8') as stream:
            os.chmod(temp, 0o600)
            json.dump(value, stream, sort_keys=True)
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temp, path)
        flush_directory(path.parent)
    finally: temp.unlink(missing_ok=True)


def read_json(path, default=None):
    try: return json.loads(Path(path).read_text())
    except FileNotFoundError: return default


def safe_directory(path):
    path = Path(path)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise NVError('nv_unsafe_path')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)


@contextlib.contextmanager
def maintenance_lock(root, *, snapshot=False):
    """Same inode locks as full/diff upgrades; never remove a lock file."""
    with contextlib.ExitStack() as stack:
        for name in ('run/e5-part-update.lock', 'run/e5-upgrade/lock'):
            path = Path(root)/name
            if path.parent != Path(root)/'run': safe_directory(path.parent)
            else: path.parent.mkdir(parents=True, exist_ok=True)
            if path.is_symlink() or path.exists() and (not path.is_file() or path.stat().st_nlink != 1):
                raise NVError('nv_unsafe_path')
            held = stack.enter_context(path.open('a'))
            os.chmod(path, 0o600)
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # A failed preparation can leave request.ready without ever arming an
        # update. Read-only snapshots are needed to retry that preparation;
        # they still hold both real mutexes and never bypass an armed request.
        if ((Path(root)/'.e5-update/request').exists() or
                not snapshot and (Path(root)/'.e5-update/request.ready').exists()):
            raise NVError('nv_busy')
        yield


def validate(path, name):
    """Same stock NV checksum variants as t551m-nv-prepare, including overflow.

    Delta/calinv formats are opaque: their hashes are tracked, not claimed
    checksum-valid or accepted as writable calibration item containers.
    """
    path = Path(path)
    if not name.startswith(('nr_fixnv', 'nr_runtimenv')):
        return 'opaque'
    with path.open('rb') as stream:
        header = stream.read(16)
        if len(header) != 16: raise NVError('nv_invalid_header')
        magic, size, expected, version = struct.unpack('<4I', header)
        if name.startswith('nr_runtimenv') and (magic, size, expected, version) == (0, 0, 0, 0):
            if any(any(block) for block in iter(lambda: stream.read(1024 * 1024), b'')):
                raise NVError('nv_invalid_runtime')
            return 'uninitialized'
        capacity = storage_size(path)
        if magic != 0x4e56 or size <= 0 or size % 2 or size > capacity - 512:
            raise NVError('nv_invalid_header')
        stream.seek(512); data = stream.read(size)
        if len(data) != size: raise NVError('nv_invalid_size')
        words = array.array('H', data)
        if sys.byteorder != 'little': words.byteswap()
        total = sum(words); checksums = []
        for number in (total, total & 0xffffffff):
            while number >> 16: number = (number & 0xffff) + (number >> 16)
            checksums.append(number ^ 0xffff)
        if expected not in checksums: raise NVError('nv_invalid_checksum')
    return 'valid'


def working(root):
    root = Path(root); store = root/'opt/e5/nv'
    if any(p.is_symlink() for p in (store, *store.parents)) or (store/'factory-sha256.json').is_symlink():
        raise NVError('nv_unsafe_path')
    origin = read_json(store/'factory-sha256.json', {})
    if (not isinstance(origin, dict) or set(origin) != set(NAMES) or
            any(not isinstance(v, str) or not re.fullmatch('[0-9a-f]{64}', v) for v in origin.values())):
        raise NVError('nv_origin_unavailable')
    values = {}
    for name in NAMES:
        path = store/name
        if path.is_symlink() or not path.is_file(): raise NVError('nv_work_unavailable')
        values[name] = {'sha256': digest(path), 'validation': validate(path, name), 'size': path.stat().st_size}
    return origin, values


@contextlib.contextmanager
def quiesced(root):
    """Reuse the deployed transaction-aware writer pause for a live snapshot."""
    stopped = []
    if Path(root) != Path('/'):
        yield
        return
    import runpy
    prepare = Path('/opt/e5/t551m-nv-prepare')
    helper = Path('/opt/e5/t551m-nv-stop')
    if not prepare.exists():
        yield
        return
    nv = runpy.run_path(str(prepare)); pids = nv['vendor_pids']()
    try:
        if pids:
            stop = runpy.run_path(str(helper))
            for pid in pids:
                identity = Path('/proc')/str(pid)/'stat'
                start = identity.read_text().rsplit(')', 1)[1].split()[19]
                # Preserve an already-stopped task's state.
                state = identity.read_text().rsplit(')', 1)[1].split()[0]
                if state in ('T', 't'): continue
                with contextlib.redirect_stdout(sys.stderr): stop['freeze_idle'](pid)
                stopped.append((pid, start))
        for path, loop in nv['attached_loops']().items():
            with loop.open('rb') as stream: os.fsync(stream.fileno())
            with path.open('rb') as stream: os.fsync(stream.fileno())
        yield
    finally:
        for pid, start in stopped:
            try:
                identity = (Path('/proc')/str(pid)/'stat').read_text().rsplit(')', 1)[1].split()[19]
                if identity == start: os.kill(pid, signal.SIGCONT)
            except (FileNotFoundError, ProcessLookupError): pass


def archive(root, output):
    with quiesced(root):
        return archive_quiet(root, output)


def factory_archive(root, output, devices=None):
    """A fresh-install snapshot from THIS unit's originals, never raw writes.

    No working-file checks are relaxed. Recovery uses a separately validated
    source and a new provenance manifest after explicit per-operation consent.
    devices is restricted to offline host fixtures/Android binary readback.
    """
    root = Path(root)
    if (root/'opt/e5/nv-import.json').exists() or (root/'etc/e5-nv/writeback.json').exists():
        raise NVError('nv_recovery_pending')
    manager = Manager(root, devices)
    profile, slot = manager.identity()
    sources = manager.map()
    hashes = {}
    spool = root/'opt/e5-nv-staging'; safe_directory(spool)
    with tempfile.TemporaryDirectory(prefix='original-', dir=spool) as temporary:
        staged = Path(temporary); store = staged/'opt/e5/nv'; store.mkdir(parents=True, mode=0o700)
        (staged/'etc/e5').mkdir(parents=True)
        (staged/'etc/e5/device-profile').write_text(profile)
        for name in NAMES:
            source = sources[name]; validate(source, name); checksum = digest(source)
            with source.open('rb') as src, (store/name).open('xb') as dst:
                os.chmod(store/name, 0o660); shutil.copyfileobj(src, dst)
                dst.flush(); os.fsync(dst.fileno())
            if digest(store/name) != checksum or digest(source) != checksum:
                raise NVError('nv_snapshot_changed')
            hashes[name] = checksum
        if any(digest(sources[n]) != hashes[n] for n in NAMES): raise NVError('nv_snapshot_changed')
        for primary, redundant in PAIRS: shutil.copyfile(store/primary, store/redundant)
        atomic_json(store/'factory-sha256.json', hashes)
        atomic_json(staged/'etc/e5-nv/last-sync.json', {
            'direction': 'from-original', 'reason': 'confirmed-install-recovery',
            'time': int(time.time()), 'ok': True, 'reboot_required': False,
            'firmware_slot': slot})
        archive_quiet(staged, output)


def confirmed_factory_archive(root, output):
    """Interactive legacy shell path; a headless process never assumes yes."""
    spool = Path(root)/'opt/e5-nv-staging'; safe_directory(spool)
    with tempfile.TemporaryFile(dir=spool) as candidate:
        factory_archive(root, candidate)
        try:
            with open('/dev/tty', 'r') as reader, open('/dev/tty', 'w') as writer:
                writer.write('Working NV could not be preserved. Use this unit\'s original Android NV?\n'
                          '工作 NV 无法保留。改用本机原始 NV 将放弃 OpenWrt NV 修改，原机分区不变。\n'
                          'Type yes / 输入 yes: ')
                writer.flush()
                if reader.readline(32).strip() != 'yes': raise NVError('nv_confirmation_required')
        except OSError as error:
            raise NVError('nv_confirmation_required') from error
        candidate.seek(0); shutil.copyfileobj(candidate, output)


def archive_quiet(root, output):
    """Offline snapshot to stdout, before replacing a filesystem. No raw IO."""
    root = Path(root)
    if (root/'opt/e5/nv-import.json').exists() or (root/'etc/e5-nv/writeback.json').exists():
        raise NVError('nv_recovery_pending')
    profile = (root/'etc/e5/device-profile').read_text().strip()
    if profile not in PROFILES: raise NVError('nv_profile_unknown')
    store = root/'opt/e5/nv'
    if store.is_symlink(): raise NVError('nv_unsafe_path')
    if not store.exists(): return False
    origin, values = working(root)
    members = []
    for base in ('opt/e5/nv', 'etc/e5-nv'):
        directory = root/base
        if not directory.exists(): continue
        if directory.is_symlink(): raise NVError('nv_unsafe_path')
        for path in sorted(directory.rglob('*')):
            if path.is_symlink() or not (path.is_dir() or path.is_file()):
                raise NVError('nv_unsafe_path')
            if path.is_file() and path.name != '.preserved.json': members.append(path)
    hashes = {p.relative_to(root).as_posix(): digest(p) for p in members}
    metadata = json.dumps({'format': 1, 'profile': profile, 'files': hashes, 'working': values}).encode()
    with tarfile.open(fileobj=output, mode='w|') as tar:
        for path in members:
            tar.add(path, arcname=path.relative_to(root).as_posix(), recursive=False)
            if digest(path) != hashes[path.relative_to(root).as_posix()]: raise NVError('nv_snapshot_changed')
        entry = tarfile.TarInfo('opt/e5/nv/.preserved.json'); entry.size = len(metadata); entry.mode = 0o600
        tar.addfile(entry, io.BytesIO(metadata))
    if any(digest(p) != hashes[p.relative_to(root).as_posix()] for p in members):
        raise NVError('nv_snapshot_changed')
    return True


def backup_work(root):
    root = Path(root); origin, values = working(root)
    state = root/'etc/e5-nv'; safe_directory(state)
    backups = state/'backups'; safe_directory(backups)
    target = backups/('update-'+time.strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(6))
    target.mkdir(mode=0o700)
    for name in (*NAMES, 'factory-sha256.json'):
        source = root/'opt/e5/nv'/name; destination = target/name
        save_snapshot(source, destination)
    atomic_json(target/'record.json', {'kind': 'update-preservation', 'time': int(time.time()), 'files': values,
                'storage': 'gzip', 'complete': True, 'raw_bytes': sum(v['size'] for v in values.values())})
    return target


def recover_import(root):
    """Resolve only our journaled directory switch before normal NV startup."""
    root = Path(root); journal = root/'opt/e5/nv-import.json'
    if not journal.exists(): return
    if journal.is_symlink(): raise NVError('nv_unsafe_path')
    record = read_json(journal)
    relative = record.get('backup', '')
    if not re.fullmatch(r'etc/e5-nv/backups/[0-9]{8}-[0-9]{6}-[0-9a-f]{12}', relative):
        raise NVError('nv_import_journal_invalid')
    backup = root/relative
    if any(p.is_symlink() for p in (backup, *backup.parents)): raise NVError('nv_unsafe_path')
    store = root/'opt/e5/nv'
    saved = read_json(backup/'record.json')
    if not isinstance(saved, dict): raise NVError('nv_import_recovery_failed')
    if not store.exists():
        previous = backup/'previous-working'
        if previous.is_symlink() or not previous.is_dir(): raise NVError('nv_import_recovery_failed')
        if not saved or any(digest(previous/n) != saved['work'][n] for n in NAMES):
            raise NVError('nv_import_recovery_failed')
        os.rename(previous, store)
    origin, local = working(root)
    source = saved.get('source', {})
    expected = {n: source.get(next((p for p, r in PAIRS if r == n), n), {}).get('sha256') for n in NAMES}
    finished = all(local[n]['sha256'] == expected[n] for n in NAMES)
    if not finished and any(local[n]['sha256'] != saved.get('work', {}).get(n) for n in NAMES):
        raise NVError('nv_import_recovery_failed')
    fd = os.open(store.parent, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)
    atomic_json(root/'etc/e5-nv/last-sync.json', {'direction': 'from-original', 'time': int(time.time()),
        'backup': '/'+relative, 'ok': finished, 'recovered': True,
        'error': '' if finished else 'nv_interrupted_recovered', 'reboot_required': False,
        'boot_id': Manager(root).boot_id()})
    journal.unlink(); flush_directory(journal.parent)
    if finished:
        try: compact_previous(backup)
        except (OSError, NVError): pass  # Space cleanup must not block modem boot.


def verify_preserved(root):
    root = Path(root); metadata = read_json(root/'opt/e5/nv/.preserved.json')
    if not metadata or metadata.get('format') != 1: raise NVError('nv_preservation_missing')
    if metadata['profile'] != (root/'etc/e5/device-profile').read_text().strip():
        raise NVError('nv_profile_mismatch')
    for name, checksum in metadata['files'].items():
        if (not name.startswith(('opt/e5/nv/', 'etc/e5-nv/')) or '..' in Path(name).parts
                or Path(name).is_absolute()): raise NVError('nv_unsafe_path')
        path = root/name
        if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file() or digest(path) != checksum:
            raise NVError('nv_preservation_mismatch')
    working(root)
    return True


class Manager:
    def __init__(self, root=Path('/'), devices=None):
        self.root = Path(root); self.store = self.root/'opt/e5/nv'
        self.state = self.root/'etc/e5-nv'; self.ram = self.root/'run/e5-nv'
        self.devices = devices

    def map(self):
        if self.devices is not None:
            if self.root == Path('/'): raise NVError('nv_fixture_forbidden')
            return self.devices
        result = {}
        kind = self.root/'etc/e5/storage-kind'
        ufs = kind.exists() and kind.read_text().strip() == 'ufs'
        if ufs:
            import runpy
            try:
                entries = runpy.run_path(str(self.root/'usr/lib/e5/block_storage.py'))['entries'](self.root)
            except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                raise NVError('nv_layout_unknown') from error
        else:
            entries = (self.root/'sys/class/block').glob('mmcblk0p*/uevent')
        for entry in entries:
            fields = dict(line.split('=', 1) for line in entry.read_text().splitlines() if '=' in line)
            name = fields.get('PARTNAME'); dev = fields.get('DEVNAME', '')
            if name not in NAMES: continue
            pattern = r'sd[a-z]+[1-9][0-9]*' if ufs else r'mmcblk0p[1-9][0-9]*'
            if name in result or dev != entry.parent.name or not re.fullmatch(pattern, dev): raise NVError('nv_layout_unknown')
            path = self.root/'dev'/dev
            if path.is_symlink() or not stat.S_ISBLK(path.stat().st_mode): raise NVError('nv_layout_unknown')
            with path.open('rb') as stream:
                if struct.unpack('i', fcntl.ioctl(stream, 0x125e, bytes(4)))[0] != 1:
                    raise NVError('nv_original_not_protected')
            result[name] = path
        if set(result) != set(NAMES): raise NVError('nv_layout_unknown')
        return result

    def identity(self):
        profile = (self.root/'etc/e5/device-profile').read_text().strip()
        if profile not in PROFILES: raise NVError('nv_profile_unknown')
        policy_path = self.root/'etc/e5/modem-slot'
        policy = policy_path.read_text().strip() if policy_path.exists() else None
        if policy is not None and policy not in ('a', 'b', 'current'):
            raise NVError('nv_slot_unknown')

        def slots_in(names):
            slots = set()
            for name in names:
                path = self.root/name
                if path.exists():
                    slots.update(re.findall(
                        r'(?:^|\s)(?:androidboot|sprdboot)\.slot_suffix\s*=\s*"?_([ab])"?(?=\s|$)',
                        path.read_text()))
            return slots

        # These are the inputs actually bound into modem_control's chroot by
        # vendor-start.sh. Linux's own cmdline/bootconfig can name the opposite
        # slot and must not substitute for a missing modem-slot on old installs.
        slots = slots_in(('run/e5-cmdline.android', 'run/e5-bootconfig.android',
                          'opt/e5/android/proc/cmdline', 'opt/e5/android/proc/bootconfig'))
        if policy in ('a', 'b'):
            slots.add(policy)
        firmware_path = self.root/'lib/firmware/android-firmware-slot'
        if not slots and policy is None and firmware_path.exists():
            value = firmware_path.read_text().strip()
            if value not in ('a', 'b'): raise NVError('nv_slot_unknown')
            slots.add(value)
        if not slots and policy == 'current':
            slots = slots_in(('proc/cmdline', 'proc/bootconfig'))
        if len(slots) > 1: raise NVError('nv_slot_conflict')
        if not slots: raise NVError('nv_slot_unknown')
        return profile, slots.pop()

    def inspect(self, local_state=None):
        profile, slot = self.identity()
        origin, local = local_state if local_state is not None else working(self.root)
        source = {}; opaque_changed = False
        for name, path in self.map().items():
            if storage_size(path) != local[name]['size']: raise NVError('nv_layout_unknown')
            valid = validate(path, name); checksum = digest(path)
            source[name] = {'sha256': checksum, 'validation': valid}
            if valid == 'opaque' and checksum != origin[name]: opaque_changed = True
        conflict = any(local[n]['sha256'] != origin[n] and source[n]['sha256'] != origin[n]
                       and local[n]['sha256'] != source[n]['sha256'] for n in NAMES)
        return {'profile': profile, 'firmware_slot': slot, 'origin': origin, 'local': local,
                'source': source, 'conflict': conflict, 'opaque_changed': opaque_changed}

    def boot_id(self):
        try: return (self.root/'proc/sys/kernel/random/boot_id').read_text().strip()
        except FileNotFoundError: return ''

    def active_job(self):
        job = read_json(self.ram/'job.json', {})
        if self.root == Path('/') and job.get('state') in ('queued', 'running'):
            pid = job.get('pid')
            if not isinstance(pid, int):
                request = str(self.ram/('request-'+str(job.get('id', ''))+'.json')).encode()
                for command in Path('/proc').glob('[0-9]*/cmdline'):
                    try:
                        argv = command.read_bytes().split(b'\0')
                        if b'worker' in argv and request in argv:
                            pid = int(command.parent.name)
                            job = {**job, 'pid': pid, 'start_ticks':
                                   (command.parent/'stat').read_text().rsplit(')', 1)[1].split()[19]}
                            break
                    except (FileNotFoundError, ProcessLookupError): pass
                if not isinstance(pid, int):
                    latest = read_json(self.ram/'job.json', {})
                    if latest != job: return latest
                    return {**job, 'state': 'failed', 'error': 'nv_worker_interrupted'}
            if isinstance(pid, int):
                try:
                    current = (Path('/proc')/str(pid)/'stat').read_text().rsplit(')', 1)[1].split()[19]
                    if str(job.get('start_ticks')) != current: raise FileNotFoundError()
                except (FileNotFoundError, ProcessLookupError):
                    job = {**job, 'state': 'failed', 'error': 'nv_worker_interrupted'}
        return job

    def preview_matches(self, saved, current):
        # Ordinary runtime NV writes are expected while a confirmation dialog
        # is open. Fixed/opaque working data and every original remain bound.
        if any(saved[key] != current[key] for key in ('profile', 'firmware_slot', 'origin', 'source')):
            return False
        return all(saved['local'][n] == current['local'][n]
                   for n in NAMES if not n.startswith('nr_runtimenv'))

    def phase(self, value):
        job = read_json(self.ram/'job.json', {})
        if job.get('state') == 'running': atomic_json(self.ram/'job.json', {**job, 'phase': value})

    def status(self):
        job = self.active_job()
        if job.get('state') in ('queued', 'running'):
            return {'ok': True, 'busy': True, 'job': job, 'can_import': False, 'can_export': False}
        work_valid = False
        last = read_json(self.state/'last-sync.json', {})
        try:
            local = working(self.root); work_valid = True
            data = self.inspect(local)
            if last.get('boot_id') and last['boot_id'] != self.boot_id():
                last['reboot_required'] = False
            same = all(data['local'][n]['sha256'] == data['source'][n]['sha256'] for n in NAMES)
            details = {}; export_reason = ''
            try:
                from nv_writeback import overview, device_identity
                details = overview(self, data); device_identity(self)
                export_reason = details.get('writeback_reason', '')
            except (OSError, ValueError) as error:
                export_reason = str(error) if str(error).startswith('nv_') else 'nv_layout_unsupported'
            pending = (self.state/'writeback.json').exists() or (self.root/'opt/e5/nv-import.json').exists()
            return {'ok': True, 'initialized': True, 'validated': True,
                    'work_validated': True, 'original_validated': True, 'profile': data['profile'],
                    'firmware_slot': data['firmware_slot'], 'same': same, 'conflict': data['conflict'],
                    'can_import': not data['opaque_changed'] and not pending,
                    'import_reason': 'nv_recovery_pending' if pending else 'nv_opaque_source_changed' if data['opaque_changed'] else '',
                    'can_export': not export_reason and not pending,
                    'export_reason': 'nv_recovery_pending' if pending else export_reason,
                    'last_sync': last, 'job': job,
                    'backup_path': '/etc/e5-nv/backups', **details}
        except (OSError, ValueError, NVError) as error:
            identities = {}
            try:
                from nv_writeback import read_imeis
                identities = read_imeis(self)
            except (OSError, ValueError, NVError): pass
            reason = str(error) if isinstance(error, NVError) else 'nv_state_unavailable'
            return {'ok': True, 'initialized': self.store.exists(), 'validated': False,
                    'work_validated': work_valid, 'original_validated': False, 'last_sync': last,
                    'can_import': False, 'can_export': False, 'reason': reason,
                    'import_reason': reason, 'export_reason': reason, 'imei': identities}

    def preview(self, direction):
        if direction not in ('from-original', 'to-original'): raise NVError('nv_invalid_direction')
        if self.active_job().get('state') in ('queued', 'running'): raise NVError('nv_busy')
        if (self.state/'writeback.json').exists() or (self.root/'opt/e5/nv-import.json').exists():
            raise NVError('nv_recovery_pending')
        data = self.inspect()
        details = {}
        if direction == 'from-original':
            if data['opaque_changed']: raise NVError('nv_opaque_source_changed')
        else:
            from nv_writeback import preview_writeback
            try: details = preview_writeback(self, data)
            except ValueError as error: raise NVError(str(error)) from error
        token = secrets.token_hex(24)
        atomic_json(self.ram/'preview.json', {'token': token, 'direction': direction, 'time': time.monotonic(), 'state': data,
                    'writeback_contract': details.get('writeback_contract'), 'writeback_scope': details.get('writeback_scope')})
        return {'ok': True, 'token': token, 'conflict': data['conflict'], 'reboot_required': True,
                'direction': direction, 'firmware_slot': data['firmware_slot'], **details}

    def sync(self, data):
        if data.get('confirmation') != 'yes': raise NVError('nv_confirmation_required')
        direction = data.get('direction')
        if direction not in ('from-original', 'to-original'): raise NVError('nv_invalid_direction')
        safe_directory(self.ram)
        with maintenance_lock(self.root), (self.ram/'lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            saved = read_json(self.ram/'preview.json', {})
            if not secrets.compare_digest(str(saved.get('token', '')), str(data.get('token', ''))) or not saved.get('token'):
                raise NVError('nv_preview_expired')
            if saved.get('direction') != direction or time.monotonic() - saved['time'] > 300 or not self.preview_matches(saved['state'], self.inspect()):
                raise NVError('nv_preview_expired')
            if direction == 'to-original':
                from nv_writeback import CONTRACT
                if saved.get('writeback_contract') != CONTRACT: raise NVError('nv_preview_expired')
            if saved['state']['conflict'] and data.get('conflict_ack') is not True: raise NVError('nv_conflict')
            if direction == 'to-original':
                from nv_writeback import preview_writeback
                try:
                    plan = preview_writeback(self, self.inspect())
                    if saved.get('writeback_scope') != plan['writeback_scope']: raise NVError('nv_preview_expired')
                    unchanged = plan['writeback_files'] == 0
                except ValueError as error: raise NVError(str(error)) from error
                if unchanged:
                    # Already byte-identical files need no cellular stop.
                    self.ram.joinpath('preview.json').unlink(missing_ok=True)
                    return {'ok': True, 'direction': direction, 'unchanged': True,
                            'skipped_files': plan['writeback_blocked'],
                            'reboot_required': False, 'time': int(time.time())}
            selected = plan['writeback_scope'] if direction == 'to-original' else NAMES
            required = (2 if direction == 'to-original' else 3) * sum(saved['state']['local'][n]['size'] for n in selected) + (1 << 20)
            if shutil.disk_usage(self.store).free < required: raise NVError('nv_backup_space')
            backup = self.state/'backups'/(time.strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(6))
            safe_directory(self.state)
            safe_directory(self.state/'backups')
            backup.mkdir(parents=True, mode=0o700)
            committed = False
            try:
                if self.store.stat().st_dev != backup.stat().st_dev: raise NVError('nv_layout_unknown')
                # A deferred charging-mode start must not reopen loops halfway
                # through the import. Shared nv-prepare honors this RAM marker.
                atomic_json(self.ram/'import-active', {'backup': str(backup), 'boot_id': self.boot_id()})
                # Existing service hooks quiesce the writer and flush/detach NV.
                # Do not issue SFUN or alter saved radio/replay preferences.
                self.phase('stop')
                subprocess.run(['/etc/init.d/e5-vendor', 'stop'], check=True, timeout=60)
                if self.root == Path('/'):
                    import runpy
                    if runpy.run_path('/opt/e5/t551m-nv-prepare')['vendor_pids']():
                        raise NVError('nv_writer_busy')
                if any((self.root/'sys/class/block').glob('loop*/loop/backing_file')):
                    for path in (self.root/'sys/class/block').glob('loop*/loop/backing_file'):
                        if path.read_text().strip().startswith(str(self.store)+'/'): raise NVError('nv_writer_busy')
                final = self.inspect()
                if not self.preview_matches(saved['state'], final): raise NVError('nv_preview_expired')
                if direction == 'to-original':
                    from nv_writeback import writeback
                    # Runtime naturally changes while the confirmation is open.
                    # Capture its FINAL flushed state after the existing stop.
                    outcome = writeback(self, {**saved, 'state': final}, self.phase, backup=backup)
                    atomic_json(self.state/'last-sync.json', outcome)
                    self.ram.joinpath('preview.json').unlink(missing_ok=True)
                    return outcome
                devices = self.map()
                self.phase('backup')
                for name in NAMES:
                    for label, path in (('work', self.store/name), ('source', devices[name])):
                        target = backup/label/name
                        checksum = save_snapshot(path, target)
                        if label == 'source' and checksum != saved['state']['source'][name]['sha256']:
                            raise NVError('nv_preview_expired')
                atomic_json(backup/'factory-sha256.json', saved['state']['origin'])
                flush_directory(backup/'work'); flush_directory(backup/'source')
                atomic_json(backup/'record.json', {'kind': 'import', 'complete': True, 'storage': 'gzip',
                            'raw_bytes': 2*sum(saved['state']['local'][n]['size'] for n in NAMES),
                            'source': saved['state']['source'], 'work': {n: digest(self.store/n) for n in NAMES}})
                # Stage a COMPLETE replacement, even if Android's hashes have
                # not changed. --refresh only updates changed source hashes and
                # would otherwise silently retain OpenWrt calibration changes.
                candidate = backup/'import'
                self.phase('stage')
                candidate.mkdir(mode=0o700)
                for name in NAMES:
                    restore_snapshot(backup/'source'/name, candidate/name,
                                     saved['state']['source'][name]['sha256'], saved['state']['local'][name]['size'])
                    if self.root == Path('/'): os.chown(candidate/name, 1000, 1000)
                    validate(candidate/name, name)
                # Reuse the verified primary-first redundant-copy rule. Only
                # isolated candidate files are reconciled, never raw partitions.
                for primary, redundant in PAIRS:
                    shutil.copyfile(candidate/primary, candidate/redundant)
                    if self.root == Path('/'): os.chown(candidate/redundant, 1000, 1000)
                atomic_json(candidate/'factory-sha256.json',
                            {n: saved['state']['source'][n]['sha256'] for n in NAMES})
                for name in NAMES:
                    expected = saved['state']['source'][next((p for p, r in PAIRS if r == name), name)]['sha256']
                    if digest(candidate/name) != expected: raise NVError('nv_preservation_mismatch')
                # Each staged file has a verified checksum and flushed bytes.
                for name in (*NAMES, 'factory-sha256.json'):
                    with (candidate/name).open('rb') as stream: os.fsync(stream.fileno())
                # Both locations are on the root filesystem. Keep the old
                # directory intact for immediate rollback if commit fails.
                old = backup/'previous-working'
                self.phase('commit')
                journal = self.root/'opt/e5/nv-import.json'
                atomic_json(journal, {'backup': backup.relative_to(self.root).as_posix()})
                os.rename(self.store, old)
                try:
                    flush_directory(backup); flush_directory(self.store.parent)
                    os.rename(candidate, self.store)
                    fd = os.open(self.store.parent, os.O_RDONLY | os.O_DIRECTORY)
                    try: os.fsync(fd)
                    finally: os.close(fd)
                    committed = True
                    journal.unlink()
                except Exception:
                    if not self.store.exists():
                        os.rename(old, self.store)
                        flush_directory(self.store.parent); flush_directory(backup)
                    raise
                self.ram.joinpath('preview.json').unlink(missing_ok=True)
                outcome = {'direction': 'from-original', 'time': int(time.time()),
                           'backup': str(backup).removeprefix(str(self.root)) if self.root != Path('/') else str(backup),
                           'reboot_required': True, 'ok': True, 'boot_id': self.boot_id()}
                atomic_json(self.state/'last-sync.json', outcome)
                try: compact_previous(backup)
                except (OSError, NVError):
                    # Import already committed. Keep duplicates on cleanup
                    # failure; never call a successful NV import a failed one.
                    outcome['backup_compaction_pending'] = True
                    atomic_json(self.state/'last-sync.json', outcome)
                return outcome
            except Exception as error:
                # Keep diagnostics and complete/partial backups. A reverse
                # transaction restores its originals before reaching here, or
                # retains its recovery journal if that restoration failed.
                code = str(error) if str(error).startswith('nv_') else ('nv_import_failed' if direction == 'from-original' else 'nv_writeback_failed')
                atomic_json(self.state/'last-sync.json', {'direction': direction, 'time': int(time.time()),
                            'backup': str(backup), 'ok': False, 'error': code,
                            'cause': str(error), 'committed': committed, 'reboot_required': True,
                            'boot_id': self.boot_id()})
                raise NVError(code) from error

    def start(self, data, operation='sync'):
        if operation in ('sync','compress_backup') and data.get('confirmation') != 'yes': raise NVError('nv_confirmation_required')
        if operation == 'sync':
            if data.get('direction') not in ('from-original', 'to-original'): raise NVError('nv_invalid_direction')
        elif operation in ('compress_backup','prepare_download'):
            if not isinstance(data.get('id'), str) or not re.fullmatch(r'(?:(?:update|manual)-)?[0-9]{8}-[0-9]{6}-[0-9a-f]{12}', data['id']):
                raise NVError('nv_invalid_request')
        elif operation == 'manual_backup': pass
        else: raise NVError('nv_invalid_method')
        safe_directory(self.ram)
        with (self.ram/'launch.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if self.active_job().get('state') in ('queued', 'running'): raise NVError('nv_busy')
            saved = read_json(self.ram/'preview.json', {}) if operation == 'sync' else {}
            if operation == 'sync' and (not saved.get('token') or saved.get('direction') != data.get('direction') or
                    not secrets.compare_digest(str(saved['token']), str(data.get('token', ''))) or
                    time.monotonic()-saved['time'] > 300):
                raise NVError('nv_preview_expired')
            if operation == 'sync' and data.get('direction') == 'to-original':
                from nv_writeback import CONTRACT
                if saved.get('writeback_contract') != CONTRACT: raise NVError('nv_preview_expired')
            token = secrets.token_hex(12); request = self.ram/('request-'+token+'.json')
            atomic_json(request, {**data, 'operation': operation})
            atomic_json(self.ram/'job.json', {'id': token, 'state': 'queued', 'operation': operation})
            try:
                with (self.ram/'worker.log').open('ab') as log:
                    os.chmod(self.ram/'worker.log', 0o600)
                    process = subprocess.Popen([sys.executable, __file__, 'worker', str(request)],
                                     stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
                # The worker owns running/completion metadata. Writing a queued
                # PID record here could overwrite a fast worker's completion.
            except Exception:
                atomic_json(self.ram/'job.json', {'id': token, 'state': 'failed', 'error': 'nv_operation_failed'})
                request.unlink(missing_ok=True)
                raise
        return {'ok': True, 'job': {'id': token, 'state': 'queued', 'operation': operation}}

    def backups(self):
        entries = []
        base = self.state/'backups'
        if base.is_symlink(): raise NVError('nv_unsafe_path')
        pending = read_json(self.state/'writeback.json', {}).get('backup', '')
        pending_import = read_json(self.root/'opt/e5/nv-import.json', {}).get('backup', '')
        for path in sorted(base.iterdir(), reverse=True) if base.exists() else ():
            if path.is_symlink() or not path.is_dir(): continue
            if not re.fullmatch(r'(?:(?:update|manual)-)?[0-9]{8}-[0-9]{6}-[0-9a-f]{12}', path.name): continue
            try: record = read_json(path/'record.json', {})
            except (ValueError, OSError): record = {}
            if not isinstance(record, dict): record = {}
            files = [p for p in path.rglob('*') if p.is_file() and not p.is_symlink()]
            size = sum(p.stat().st_size for p in files)
            relative = path.relative_to(self.root).as_posix()
            entries.append({'id': path.name, 'path': '/'+relative, 'bytes': size,
                            'kind': record.get('kind', 'import'),
                            'compressed': record.get('storage') == 'gzip', 'raw_bytes': record.get('raw_bytes'),
                            'can_compress': any(p.name in NAMES for p in files),
                            'complete': bool(record.get('complete') or record.get('kind') == 'update-preservation'),
                            'protected': relative in (pending, pending_import)})
        return {'ok': True, 'entries': entries, 'total_bytes': sum(p['bytes'] for p in entries)}

    def compress_backup(self, data, _worker=False):
        """Lossless backup-only conversion. Never opens a live NV or partition."""
        if data.get('confirmation') != 'yes': raise NVError('nv_confirmation_required')
        ident = data.get('id', '')
        if not isinstance(ident, str) or not re.fullmatch(r'(?:(?:update|manual)-)?[0-9]{8}-[0-9]{6}-[0-9a-f]{12}', ident):
            raise NVError('nv_invalid_request')
        with maintenance_lock(self.root):
            if not _worker and self.active_job().get('state') in ('queued', 'running'): raise NVError('nv_busy')
            row = next((p for p in self.backups()['entries'] if p['id'] == ident), None)
            if row is None: raise NVError('nv_backup_missing')
            if row['protected']: raise NVError('nv_recovery_pending')
            backup = self.state/'backups'/ident
            if any(p.is_symlink() for p in (backup, *backup.parents)) or any(p.is_symlink() for p in backup.rglob('*')):
                raise NVError('nv_unsafe_path')
            record = read_json(backup/'record.json', {})
            if not isinstance(record, dict): raise NVError('nv_backup_failed')
            # The import's previous-working is already represented by work/.
            duplicate = backup/'previous-working'
            files = [p for p in backup.rglob('*') if p.name in NAMES and p.is_file() and duplicate not in p.parents]
            self.phase('backup')
            for path in files:
                expected, size = digest(path), path.stat().st_size
                compressed = path.with_name(path.name+'.gz')
                if compressed.exists(): verify_snapshot(path, expected, size)
                else: save_snapshot(path, path)
            updated = {**record, 'storage': 'gzip', 'raw_bytes': record.get('raw_bytes') or sum(p.stat().st_size for p in files)}
            atomic_json(backup/'record.json', updated)
            compact_previous(backup)
            # All independently verified gzip images are durable before raw
            # duplicates are removed. Interrupted conversion can be resumed.
            for path in files:
                verify_snapshot(path, digest(path), path.stat().st_size)
                path.unlink()
            for parent in {p.parent for p in files}: flush_directory(parent)
            flush_directory(backup)
        return {'ok': True, 'backup_compressed': True}

    def delete_backup(self, data):
        if data.get('confirmation') != 'yes': raise NVError('nv_confirmation_required')
        ident = data.get('id', '')
        if not isinstance(ident, str) or not re.fullmatch(r'(?:(?:update|manual)-)?[0-9]{8}-[0-9]{6}-[0-9a-f]{12}', ident):
            raise NVError('nv_invalid_request')
        with maintenance_lock(self.root):
            if self.active_job().get('state') in ('queued', 'running'): raise NVError('nv_busy')
            row = next((p for p in self.backups()['entries'] if p['id'] == ident), None)
            if row is None: raise NVError('nv_backup_missing')
            if row['protected']: raise NVError('nv_recovery_pending')
            path = self.state/'backups'/ident
            if any(p.is_symlink() for p in (path, *path.parents)) or any(p.is_symlink() for p in path.rglob('*')):
                raise NVError('nv_unsafe_path')
            shutil.rmtree(path); flush_directory(path.parent)
        return {'ok': True}


def dispatch(method, data):
    manager = Manager()
    if method == 'status': return manager.status()
    if method == 'preview': return manager.preview(data.get('direction'))
    if method == 'sync': return manager.start(data)
    if method == 'backups': return manager.backups()
    if method == 'delete_backup': return manager.delete_backup(data)
    if method == 'compress_backup': return manager.start(data, 'compress_backup')
    if method == 'manual_backup': return manager.start(data, 'manual_backup')
    if method == 'prepare_download': return manager.start(data, 'prepare_download')
    raise NVError('nv_invalid_method')


def run_worker(request, manager):
    request = Path(request)
    if request.parent != manager.ram or not re.fullmatch(r'request-[0-9a-f]{24}\.json', request.name):
        raise NVError('nv_invalid_request')
    token = request.stem.removeprefix('request-')
    data = read_json(request, {}); operation = data.get('operation', 'sync')
    running = {'id': token, 'state': 'running', 'phase': 'checking', 'operation': operation}
    if manager.root == Path('/'):
        running.update(pid=os.getpid(), start_ticks=(Path('/proc')/str(os.getpid())/'stat').read_text().rsplit(')', 1)[1].split()[19])
    atomic_json(manager.ram/'job.json', running)
    try:
        if operation == 'compress_backup': result = manager.compress_backup(data, _worker=True)
        elif operation == 'manual_backup':
            from nv_backups import manual_backup
            result = manual_backup(manager)
        elif operation == 'prepare_download':
            from nv_backups import prepare_download
            result = prepare_download(manager,data)
        elif operation == 'sync': result = manager.sync(data)
        else: raise NVError('nv_invalid_method')
        atomic_json(manager.ram/'job.json', {'id': token, 'state': 'complete', 'operation': operation, 'result': result})
    except Exception as error:
        code = ('nv_busy' if isinstance(error, BlockingIOError) else str(error) if isinstance(error, NVError)
                else 'nv_backup_space' if isinstance(error,OSError) and error.errno==errno.ENOSPC else 'nv_operation_failed')
        atomic_json(manager.ram/'job.json', {'id': token, 'state': 'failed', 'operation': operation, 'error': code})
    finally: request.unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('archive', 'factory-archive', 'factory-confirmed', 'verify', 'update-backup', 'worker'))
    parser.add_argument('request', nargs='?')
    parser.add_argument('--root', default='/')
    parser.add_argument('--lock', action='store_true')
    parser.add_argument('--gzip', action='store_true', help='stream a lossless compressed transport archive')
    args = parser.parse_args()
    if args.operation in ('archive', 'factory-archive', 'factory-confirmed'):
        with maintenance_lock(Path(args.root), snapshot=True) if args.lock else contextlib.nullcontext(), \
                gzip.GzipFile(fileobj=sys.stdout.buffer, mode='wb', compresslevel=3, mtime=0) if args.gzip else contextlib.nullcontext(sys.stdout.buffer) as output:
            if args.operation == 'factory-confirmed': confirmed_factory_archive(Path(args.root), output)
            elif args.operation == 'factory-archive': factory_archive(Path(args.root), output)
            elif not archive(Path(args.root), output): raise SystemExit(3)
    elif args.operation == 'verify': verify_preserved(Path(args.root))
    elif args.operation == 'update-backup': backup_work(Path(args.root))
    else:
        if args.root != '/' or not args.request: raise NVError('nv_invalid_request')
        run_worker(Path(args.request), Manager())
