#!/usr/bin/env python3
"""Local build task logging and serial release assembly; never flash a device.

Run in Linux/WSL. Native installer compilation keeps installer/build.py.
plan/check are read-only; package reuses verified inputs and never compiles them.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

TOP = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
OWNER = 'e5-linux-build-release-v1'
PROFILES = ('e5', 't551m', 'm8', 't512n', 'yuanhang41s', 'k1', 'lym10k', 'changxing60')
EXPERIMENTAL_PROFILES = ('y60',)
COMMON = ('base', 'defaults', 'busybox', 'block_apk', 'wifi_apks')


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.new')
    temporary.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    # Windows readers of a DrvFS status file can briefly deny its replacement.
    # Keep publication atomic; retry sharing/access contention for at most 1 s.
    for attempt in range(21):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 20:
                raise
            time.sleep(0.05)


def layout(config, workspace, profiles, repo=TOP):
    data = json.loads(config.read_text(encoding='utf-8'))
    if data.get('format') != 1:
        raise ValueError('Unsupported build layout')
    workspace = workspace.expanduser().resolve()
    if workspace == Path('/') or workspace == Path.home():
        raise ValueError('Choose a dedicated build workspace')
    if workspace == Path('/mnt/c') or workspace.is_relative_to('/mnt/c'):
        raise ValueError('Build workspace must not migrate to C:')
    values = {'repo': str(repo.resolve()), 'workspace': str(workspace)}
    def path(value):
        result = Path(value.format(**values)).expanduser()
        if not result.is_absolute():
            raise ValueError('Build input paths must be absolute after expansion')
        return result.resolve()
    common = {key: path(data[key]) for key in COMMON}
    rows = {}
    for model in profiles:
        if model not in (*PROFILES, *EXPERIMENTAL_PROFILES) or model not in data['profiles']:
            raise ValueError('Unknown/unconfigured model: ' + model)
        rows[model] = {key: path(data['profiles'][model][key])
                       for key in ('kernel', 'stock_boot', 'misc_head')}
    return common, rows


@contextmanager
def workspace_lock(workspace):
    import fcntl
    directory = workspace / 'locks'
    directory.mkdir(parents=True, exist_ok=True)
    # A sudo packaging run must not make the next user's compiler task require
    # write access to a root-owned lock file. Linux flock works on a read FD.
    descriptor = os.open(directory / 'openwrt-release.lock', os.O_RDONLY | os.O_CREAT, 0o644)
    with os.fdopen(descriptor, 'rb') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError('Another build/package task owns this workspace') from error
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def stage_path(workspace, model):
    if model not in (*PROFILES, *EXPERIMENTAL_PROFILES):
        raise ValueError('Unknown staging model')
    parent = workspace / 'package-work/e5-release'
    target = parent / model
    if parent.is_symlink() or parent.resolve() != parent or target.is_symlink():
        raise ValueError('Staging path must not use symlinks')
    if not target.resolve().is_relative_to(workspace.resolve()):
        raise ValueError('Staging path escaped workspace')
    return target


def clean_stage(workspace, model):
    target = stage_path(workspace, model)
    if not target.exists():
        return
    marker = target / '.build-owner.json'
    if marker.is_symlink() or json.loads(marker.read_text()) != {'owner': OWNER, 'profile': model}:
        raise ValueError('Refusing to clean unowned staging: ' + str(target))
    # Refuse a live image/root mount anywhere below the staging tree.
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        mount = Path(re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), line.split()[4]))
        if mount == target or mount.is_relative_to(target):
            raise ValueError('Unmount staging before cleanup: ' + str(mount))
    shutil.rmtree(target)


def installer_artifact(platform):
    directory, variable = {
        'windows-x64': ('windows', 'OPENWRT_GUI_ARTIFACT'),
        'macos-arm64': ('macos-arm64', 'OPENWRT_GUI_MACOS_ARTIFACT'),
    }[platform]
    return Path(os.environ.get(variable, str(TOP / 'installer/artifacts' / directory)))


def input_check(common, rows):
    if not (TOP/'installer/package_gui.py').is_file():
        raise ValueError('Initialize the shared installer submodule / 请先执行 git submodule update --init --recursive')
    missing = [str(p) for p in common.values() if not p.exists()]
    missing += [str(p) for row in rows.values() for p in row.values() if not p.exists()]
    if missing:
        raise ValueError('Missing registered inputs (nothing was built/copied):\n' + '\n'.join(missing))
    if not (common['base'] / 'sbin/sysupgrade.openwrt').is_file():
        raise ValueError('Clean base lacks the original configuration backup implementation')
    runpy.run_path(str(TOP / 'openwrt/bundle/flash.py'))['validate_installer_busybox'](common['busybox'])
    packages = runpy.run_path(str(TOP / 'tools/openwrt-package-state.py'))
    current = packages['inspect']('25.12.5')
    if json.loads(packages['STATE'].read_text()) != current:
        raise ValueError('ModemManager inputs stale: build openwrt/build-modemmanager.sh first')
    runpy.run_path(str(TOP / 'openwrt/wifi-sae-state.py'))['inspect'](common['wifi_apks'])
    block = common['block_apk']
    expected = runpy.run_path(str(TOP / 'tools/ci-release.py'))['block_build_id']()
    if Path(str(block) + '.build-id').read_text().strip() != expected:
        raise ValueError('block-mount input is stale')
    if Path(str(block) + '.sha256').read_text().split()[0] != digest(block):
        raise ValueError('block-mount input checksum mismatch')
    sys.path.insert(0, str(TOP / 'installer'))
    from package_gui import sources, validate_artifact
    source = sources()
    for platform in ('windows-x64', 'macos-arm64'):
        validate_artifact(installer_artifact(platform), platform, source)
    check = runpy.run_path(str(TOP / 'upstream/check-container-support.py'))['check']
    for model, row in rows.items():
        release = check(row['kernel'])
        tokens = ('-yuanhang41s-', '-yh41s-') if model == 'yuanhang41s' else ('-' + model + '-',)
        if not any(token in release for token in tokens):
            raise ValueError('Wrong kernel model: ' + model + ': ' + release)


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def verify_archive(path, require_android=False):
    with zipfile.ZipFile(path) as archive:
        if require_android:
            runpy.run_path(str(TOP/'installer/package_android.py'))['verify_archive'](archive)
        names = archive.namelist()
        if len(names) != len(set(names)) or archive.testzip():
            raise ValueError('ZIP duplicate entries or CRC failure: ' + str(path))
        if (names.count('files/boot.img') != 1 or names.count('files/openwrt.ext4.gz') != 1
                or sum(n.endswith('/boot.img') or n == 'boot.img' for n in names) != 1
                or sum(n.endswith(('openwrt.ext4.gz', 'rootfs.tar.gz', 'mu300-openwrt.tar.gz'))
                       for n in names) != 1):
            raise ValueError('Expected one boot and one system image')
        manifest = {}
        for line in archive.read('files/SHA256SUMS').decode().splitlines():
            wanted, name = line.split(None, 1)
            if name in manifest:
                raise ValueError('Duplicate checksum entry')
            manifest[name] = wanted
        if set(manifest) != {n for n in names if not n.endswith('/') and n != 'files/SHA256SUMS'}:
            raise ValueError('Incomplete ZIP checksums')
        for name, wanted in manifest.items():
            with archive.open(name) as stream:
                h = hashlib.sha256()
                for chunk in iter(lambda: stream.read(1 << 20), b''):
                    h.update(chunk)
            if h.hexdigest() != wanted:
                raise ValueError('ZIP checksum mismatch: ' + name)
        required = {'OpenWrt-Diff-Studio.exe','OpenWrt-Diff-Studio.py',
                    'OpenWrt-Diff-Studio.app/Contents/MacOS/openwrt-installer',
                    'tools/backend/openwrt-backend.exe','tools/macos/backend/openwrt-backend'}
        tool = json.loads(archive.read('diff-tool.json'))
        if tool.get('protocol') != 1 or not required.issubset(tool.get('files', {})):
            raise ValueError('Diff Studio missing native entries/runtime')
        for name, wanted in tool['files'].items():
            if (name not in required and not name.startswith(('backend/', 'tools/backend/',
                    'tools/macos/backend/', 'OpenWrt-Diff-Studio.app/'))) or manifest.get(name) != wanted:
                raise ValueError('Diff Studio runtime scope/checksum mismatch: ' + name)


class Task:
    def __init__(self, workspace, label):
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,60}', label):
            raise ValueError('Invalid task label')
        self.workspace = workspace
        stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
        self.id = stamp + '-' + label + '-' + str(os.getpid())
        self.logs = TOP / 'out/build-logs' / self.id
        self.logs.mkdir(parents=True)
        self.data = {'format': 1, 'task': self.id, 'pid': os.getpid(), 'state': 'running',
                     'workspace': str(workspace), 'logs': str(self.logs), 'steps': []}
        self.save()

    def save(self, **fields):
        self.data.update(fields)
        write_json(self.logs / 'status.json', self.data)
        write_json(TOP / 'out/build-state/latest.json', self.data)

    def run(self, label, command):
        log = self.logs / (label + '.log')
        step = {'stage': label, 'command': list(map(str, command)), 'log': str(log),
                'started': time.time(), 'state': 'running'}
        self.data['steps'].append(step); self.save(stage=label)
        temp_parent = self.workspace / 'tmp'
        temp_parent.mkdir(parents=True, exist_ok=True)
        print(label + ': ' + str(log), flush=True)
        try:
            with tempfile.TemporaryDirectory(prefix='e5-release-', dir=temp_parent) as temp:
                env = dict(os.environ, TMPDIR=temp, PYTHONDONTWRITEBYTECODE='1')
                with log.open('wb') as stream:
                    subprocess.run(list(map(str, command)), cwd=TOP, env=env,
                                   stdout=stream, stderr=subprocess.STDOUT, check=True)
        except BaseException:
            step.update(state='failed', finished=time.time()); self.save(state='failed')
            raise
        step.update(state='complete', finished=time.time()); self.save()


def package(task, common, rows):
    if os.geteuid() != 0:
        raise ValueError('Image assembly requires root; plan/check do not')
    input_check(common, rows)  # All models and both GUI platforms before copying rootfs.
    for model in rows:
        if stage_path(task.workspace, model).exists():
            raise ValueError('Prior staging retained; inspect it then run clean-staging: ' + model)
    identify = runpy.run_path(str(TOP / 'tools/release-identity.py'))['identify']
    before = identify(TOP, 'e5', '6.18.54')
    version = before['private_version']
    parent = TOP / 'out/releases'
    pending = parent / ('.building-' + task.id)
    pending.mkdir(parents=True)
    task.save(pending_output=str(pending))
    assets = []
    for model, row in rows.items():
        stage = stage_path(task.workspace, model)
        stage.mkdir(parents=True)
        write_json(stage / '.build-owner.json', {'owner': OWNER, 'profile': model})
        args = [sys.executable, TOP / 'openwrt/build-profile-tf.py', '--profile', model,
                '--work', stage / 'assembly', '--output', pending, '--release-version', version]
        for key, path in {**common, **row}.items():
            args += ['--' + key.replace('_', '-'), path]
        task.run(model + '-package', args)
        matches = list(pending.glob(model + '-*.zip'))
        if len(matches) != 1:
            raise ValueError('Expected one completed archive for ' + model)
        archive = matches[0]
        verify_archive(archive,require_android=True)
        assets.append({'profile': model, 'file': archive.name, 'bytes': archive.stat().st_size,
                       'sha256': digest(archive)})
        clean_stage(task.workspace, model)
    after = identify(TOP, 'e5', '6.18.54')
    if after['source_fingerprint'] != before['source_fingerprint']:
        raise ValueError('Repository sources changed during release; output stays unpublished')
    write_json(pending / 'BUILD-RUN.json', {**task.data, 'state': 'verified',
               'source': before, 'assets': assets})
    destination = parent / task.id
    pending.rename(destination)
    task.save(state='complete', output=str(destination), assets=assets)
    print('Verified release: ' + str(destination))


def refresh_installers(task, common, rows, source):
    if source is None:raise ValueError('Supply --source-release for installer-only refresh')
    source=source.resolve()
    if source.parent!=(TOP/'out/releases').resolve() or source.name.startswith('.'):
        raise ValueError('Use a published local release under out/releases')
    base=json.loads((source/'BUILD-RUN.json').read_text())
    if base.get('state')!='verified':raise ValueError('Installer refresh source is not verified')
    assets={row['profile']:row for row in base['assets']}
    selected={}
    for profile in rows:
        row=assets[profile];path=source/row['file']
        if path.resolve().parent!=source or digest(path)!=row['sha256']:
            raise ValueError('Source archive checksum/path mismatch: '+profile)
        verify_archive(path);selected[profile]=path
    identify=runpy.run_path(str(TOP/'tools/release-identity.py'))['identify']
    before=identify(TOP,'e5','6.18.54')
    parent=TOP/'out/releases';pending=parent/('.building-'+task.id);pending.mkdir()
    task.save(pending_output=str(pending),build_type='installer-refresh',base_release=str(source))
    refresh=runpy.run_path(str(TOP/'tools/refresh-release-installers.py'))['refresh']
    outputs=[]
    temporary_parent=task.workspace/'tmp';temporary_parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='e5-release-',dir=temporary_parent) as temporary:
        tools=Path(temporary)/'ext4-tools.tar'
        native=Path(temporary)/'native'
        task.run('installer-native',[sys.executable,TOP/'tools/package-diff-studio.py','--prepare','--package',native])
        task.run('installer-tools',[sys.executable,TOP/'openwrt/prepare-ext4-tools.py','--root',common['base'],'--include-lock','--out',tools])
        for profile,path in selected.items():
            target=pending/(path.stem+'-installer-g'+before['source_commit'][:8]+'.zip')
            refresh(path,target,tools,before,native=native);verify_archive(target,require_android=True)
            checksum=digest(target)
            (pending/(target.name+'.sha256')).write_text(checksum+'  '+target.name+'\n')
            outputs.append({'profile':profile,'file':target.name,'bytes':target.stat().st_size,'sha256':checksum})
            task.save(assets=outputs,stage=profile+'-installer-refresh')
            print('Installer verified: '+profile,flush=True)
    if identify(TOP,'e5','6.18.54')['source_fingerprint']!=before['source_fingerprint']:
        raise ValueError('Sources changed during installer refresh; output stays unpublished')
    write_json(pending/'BUILD-RUN.json',{**task.data,'state':'verified','source':before,'assets':outputs})
    destination=parent/task.id;pending.rename(destination)
    task.save(state='complete',output=str(destination),assets=outputs)
    print('Verified release: '+str(destination))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('plan', 'check', 'package', 'refresh-installers', 'run', 'status', 'clean-staging'))
    parser.add_argument('--profiles', nargs='+', choices=('all', *PROFILES, *EXPERIMENTAL_PROFILES), default=['all'])
    parser.add_argument('--workspace', type=Path, default=Path.home() / 'openwrt-build')
    parser.add_argument('--config', type=Path, default=TOP / 'tools/build-layout.json')
    parser.add_argument('--label', default='build')
    parser.add_argument('--source-release',type=Path)
    # Compiler arguments follow -- and are passed without a shell.
    args, command = parser.parse_known_args()
    if command and command[0] == '--': command = command[1:]
    if command and args.action != 'run': parser.error('Unexpected extra arguments')
    if os.name == 'nt': parser.error('Run in WSL; see docs/LOCAL-BUILD.zh-CN.md')
    workspace = args.workspace.expanduser().resolve()
    profiles = list(PROFILES) if 'all' in args.profiles else list(dict.fromkeys(args.profiles))
    common, rows = layout(args.config, workspace, profiles)
    if args.action == 'plan':
        print(json.dumps({'workspace': str(workspace), 'inputs': common, 'profiles': rows,
              'staging': workspace / 'package-work/e5-release', 'output': TOP / 'out/releases',
              'logs': TOP / 'out/build-logs'}, default=str, indent=2)); return
    if args.action == 'status':
        print((TOP / 'out/build-state/latest.json').read_text(encoding='utf-8')); return
    if args.action == 'check':
        input_check(common, rows); print('All selected inputs verified; nothing built/copied'); return
    with workspace_lock(workspace):
        if args.action == 'clean-staging':
            for model in profiles: clean_stage(workspace, model)
            return
        task = Task(workspace, args.label)
        try:
            if args.action == 'run':
                if not command: raise ValueError('Supply a real compiler/build command after --')
                task.run('command', command); task.save(state='complete')
            elif args.action=='refresh-installers':
                refresh_installers(task,common,rows,args.source_release)
            else:
                package(task, common, rows)
        except BaseException as error:
            task.save(state='failed', error=str(error))
            raise


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        sys.exit('Build stopped: ' + str(error))
