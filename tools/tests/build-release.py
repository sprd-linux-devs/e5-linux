#!/usr/bin/env python3
"""Build orchestration boundaries: no compilation, containers or device access."""
import hashlib
import importlib.util
import json
import os
import runpy
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

TOP = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('build_release', TOP / 'tools/build-release.py')
build = importlib.util.module_from_spec(spec); spec.loader.exec_module(build)
verify_android=runpy.run_path(str(TOP/'installer/package_android.py'))['verify_archive']


class Layout(unittest.TestCase):
    def test_installer_pin_rejects_checkout_drift_and_mislabeled_downloads(self):
        with patch.object(build.subprocess, 'check_output', return_value='f'*40):
            with self.assertRaisesRegex(ValueError, 'submodule differs'):
                build.verify_installer_pin()
        current = build.installer_lock()
        with tempfile.TemporaryDirectory() as folder, patch.object(build, 'TOP', Path(folder)):
            (Path(folder)/'tools').mkdir()
            current['assets']['installer_windows']['url'] = current['assets']['installer_windows']['url'].replace(current['installer_commit'][:7], '0000000')
            (Path(folder)/'tools/installer-inputs.lock.json').write_text(json.dumps(current))
            with self.assertRaisesRegex(ValueError, 'version/checksum differs'):
                build.installer_lock()

    def test_installer_defaults_follow_versioned_shared_cache(self):
        with patch.dict(os.environ, {}, clear=True):
            pin = build.installer_lock()['installer_commit'][:7]
            root = Path.home()/'openwrt-build/artifacts/openwrt-tools'/pin
            self.assertEqual(build.installer_artifact('windows-x64'), root/'windows')
            self.assertEqual(build.installer_artifact('macos-arm64'), root/'macos-arm64')
            self.assertEqual(build.installer_artifact('android-aarch64'), root/'android')
        with patch.dict(os.environ, {'OPENWRT_GUI_ANDROID_ARTIFACT': '/verified/android'}):
            self.assertEqual(build.installer_artifact('android-aarch64'), Path('/verified/android'))
        with patch.dict(os.environ, {'OPENWRT_GUI_ARTIFACT': '/verified/windows',
                                    'OPENWRT_GUI_MACOS_ARTIFACT': '/verified/mac'}):
            self.assertEqual(build.installer_artifact('windows-x64'), Path('/verified/windows'))
            self.assertEqual(build.installer_artifact('macos-arm64'), Path('/verified/mac'))

    def test_changing_the_version_lock_changes_the_cache_without_editing_paths(self):
        current = build.installer_lock()
        with tempfile.TemporaryDirectory() as folder, patch.object(build, 'TOP', Path(folder)), patch.dict(os.environ, {}, clear=True):
            root = Path(folder); (root/'tools').mkdir()
            (root/'tools/build-layout.json').write_text(json.dumps({'installer_artifacts': '{workspace}/artifacts/openwrt-tools/{installer_revision}'}))
            old = current['installer_commit'][:7]
            current['installer_commit'] = 'a'*40
            for entry in current['assets'].values(): entry['url'] = entry['url'].replace(old, 'a'*7)
            (root/'tools/installer-inputs.lock.json').write_text(json.dumps(current))
            workspace = root/'workspace'
            self.assertEqual(build.installer_artifact('windows-x64', workspace), workspace/'artifacts/openwrt-tools/aaaaaaa/windows')
            self.assertFalse(workspace.exists())

    def test_registry_covers_every_model_without_copying_or_creating(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder) / 'not-created'
            common, rows = build.layout(TOP / 'tools/build-layout.json', workspace, build.PROFILES)
            self.assertEqual(set(rows), set(build.PROFILES))
            self.assertEqual(rows['k1']['kernel'], workspace / 'k1/kernel')
            self.assertEqual(common['base'], workspace / 'base/e5')
            self.assertFalse(workspace.exists())

    def test_missing_inputs_stop_before_any_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); missing = root / 'missing'
            with self.assertRaisesRegex(ValueError, 'Missing registered inputs'):
                build.input_check({'base': missing}, {})
            self.assertFalse(missing.exists())

    def test_unknown_profile_and_unsafe_workspace(self):
        with self.assertRaisesRegex(ValueError, 'Unknown'):
            build.layout(TOP / 'tools/build-layout.json', Path('/tmp/e5-build'), ['other'])
        with self.assertRaisesRegex(ValueError, 'dedicated'):
            build.layout(TOP / 'tools/build-layout.json', Path('/'), ['e5'])
        with self.assertRaisesRegex(ValueError, 'C:'):
            build.layout(TOP / 'tools/build-layout.json', Path('/mnt/c/build'), ['e5'])


@unittest.skipIf(os.name == 'nt', 'Linux workspace lock and mount checks')
class Ownership(unittest.TestCase):
    def test_second_owner_is_blocked_and_lock_releases_after_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder)
            with self.assertRaisesRegex(RuntimeError, 'fixture'):
                with build.workspace_lock(workspace):
                    with self.assertRaisesRegex(ValueError, 'Another build'):
                        with build.workspace_lock(workspace):self.fail('lock bypass')
                    raise RuntimeError('fixture')
            with build.workspace_lock(workspace):pass

    def test_only_owned_staging_deleted_caches_and_backups_remain(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ['sources/kernel', 'objects/e5', 'cache/input', 'backups/boot.img']:
                path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('keep')
            stage = build.stage_path(root, 'e5'); stage.mkdir(parents=True)
            (stage / 'root').mkdir()
            with self.assertRaises(FileNotFoundError):build.clean_stage(root, 'e5')
            build.write_json(stage / '.build-owner.json', {'owner': build.OWNER, 'profile': 'm8'})
            with self.assertRaisesRegex(ValueError, 'unowned'):build.clean_stage(root, 'e5')
            build.write_json(stage / '.build-owner.json', {'owner': build.OWNER, 'profile': 'e5'})
            build.clean_stage(root, 'e5')
            self.assertFalse(stage.exists())
            self.assertTrue(all((root / n).exists() for n in
                ['sources/kernel', 'objects/e5', 'cache/input', 'backups/boot.img']))

    def test_symlink_escape_and_live_mount_are_not_deleted(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); outside = root / 'outside'; outside.mkdir()
            workspace = root / 'workspace'; parent = workspace / 'package-work/e5-release'
            parent.mkdir(parents=True)
            target = parent / 'e5'; target.symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'symlinks'):build.clean_stage(workspace, 'e5')
            target.unlink(); target.mkdir()
            build.write_json(target / '.build-owner.json', {'owner': build.OWNER, 'profile': 'e5'})
            read_text = Path.read_text
            def read(path, *args, **kwargs):
                if str(path) == '/proc/self/mountinfo':
                    return '1 2 3 / ' + str(target / 'assembly/root') + ' rw - ext4 /dev/loop0 rw\n'
                return read_text(path, *args, **kwargs)
            with patch.object(Path, 'read_text', read):
                with self.assertRaisesRegex(ValueError, 'Unmount'):build.clean_stage(workspace, 'e5')
            self.assertTrue(target.exists()); self.assertTrue(outside.exists())


class Archives(unittest.TestCase):
    def fixture(self, path, *, corrupt=False, extra=None):
        files = {'files/boot.img': b'boot', 'files/openwrt.ext4.gz': b'root', 'OpenWrt-Installer.py': b'cli'}
        files['OpenWrt-Tools.apk']=b'fixture ARM64 release'
        files['docs/GUI-BUILD-android.json']=json.dumps({'protocol':1,'platform':'android-aarch64','debug':False,
            'signing':{'alias':'fixture'},'files':{'OpenWrt-Tools.apk':hashlib.sha256(files['OpenWrt-Tools.apk']).hexdigest()}}).encode()
        runtime = {'OpenWrt-Diff-Studio.exe': b'native diff', 'OpenWrt-Diff-Studio.py': b'diff CLI',
                   'OpenWrt-Diff-Studio.app/Contents/MacOS/openwrt-installer': b'mac diff',
                   'tools/backend/openwrt-backend.exe': b'Windows backend',
                   'tools/macos/backend/openwrt-backend': b'Mac backend'}
        files.update(runtime)
        files['diff-tool.json'] = json.dumps({'protocol': 1, 'files': {
            n:hashlib.sha256(v).hexdigest() for n,v in runtime.items()}}).encode()
        if extra:files[extra] = b'duplicate root'
        sums = ''.join(hashlib.sha256(v).hexdigest() + '  ' + k + '\n' for k, v in files.items())
        if corrupt:files['files/boot.img'] = b'wrong'
        with zipfile.ZipFile(path, 'w') as archive:
            for k,v in files.items():archive.writestr(k,v)
            archive.writestr('files/SHA256SUMS', sums)

    def test_full_archive_and_corruption(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'test.zip'; self.fixture(path); build.verify_archive(path)
            self.fixture(path, corrupt=True)
            with self.assertRaisesRegex(ValueError, 'checksum mismatch'):build.verify_archive(path)

    def test_duplicate_payloads_and_missing_checksum_coverage(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'test.zip'
            for extra in ['other/boot.img', 'other/openwrt.ext4.gz', 'rootfs.tar.gz']:
                self.fixture(path, extra=extra)
                with self.assertRaisesRegex(ValueError, 'one boot'):build.verify_archive(path)
            self.fixture(path)
            with zipfile.ZipFile(path, 'a') as archive:archive.writestr('unrecorded', b'extra')
            with self.assertRaisesRegex(ValueError, 'Incomplete'):build.verify_archive(path)

    def test_diff_tool_manifest_cannot_export_the_full_firmware(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'test.zip';self.fixture(path)
            with zipfile.ZipFile(path) as z:files={n:z.read(n) for n in z.namelist() if n!='files/SHA256SUMS'}
            meta=json.loads(files['diff-tool.json']);meta['files']['files/boot.img']=hashlib.sha256(files['files/boot.img']).hexdigest()
            files['diff-tool.json']=json.dumps(meta).encode()
            with zipfile.ZipFile(path,'w') as z:
                for n,v in files.items():z.writestr(n,v)
                z.writestr('files/SHA256SUMS',''.join(hashlib.sha256(v).hexdigest()+'  '+n+'\n' for n,v in files.items()))
            with self.assertRaisesRegex(ValueError,'runtime scope'):build.verify_archive(path)


class TaskState(unittest.TestCase):
    def fake_assembly(self, task, model, args):
        workspace = task.workspace
        # A second model must never overlap the previous model's staging.
        current = model.removesuffix('-package')
        active = [p.name for p in (workspace / 'package-work/e5-release').iterdir()]
        self.assertEqual(active, [current])
        stage = Path(args[args.index('--work') + 1]); stage.mkdir()
        (stage / 'temporary-image').write_bytes(b'temporary root')
        output = Path(args[args.index('--output') + 1])
        Archives().fixture(output / (current + '-release.zip'))

    def test_serial_success_cleans_only_staging_and_publishes_at_end(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(build, 'TOP', Path(folder)), \
             patch.object(build.os, 'geteuid', return_value=0), patch.object(build, 'input_check'), \
             patch.object(build.runpy, 'run_path', return_value={
                'identify': lambda *a: {'private_version':'r-test','source_fingerprint':'same'},'verify_archive':verify_android}):
            task = build.Task(Path(folder) / 'native', 'fixture')
            with patch.object(task, 'run', side_effect=lambda model,args:self.fake_assembly(task,model,args)):
                build.package(task, {}, {'e5': {}, 'k1': {}})
            destination = Path(folder) / 'out/releases' / task.id
            self.assertTrue(destination.is_dir())
            self.assertFalse(destination.with_name('.building-' + task.id).exists())
            self.assertEqual(len(list(destination.glob('*.zip'))), 2)
            self.assertFalse(build.stage_path(task.workspace, 'e5').exists())
            self.assertFalse(build.stage_path(task.workspace, 'k1').exists())
            self.assertEqual(task.data['state'], 'complete')

    def test_changed_sources_block_publication_after_assembly(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(build, 'TOP', Path(folder)), \
             patch.object(build.os, 'geteuid', return_value=0), patch.object(build, 'input_check'):
            identify = unittest.mock.Mock(side_effect=[
                {'private_version':'r-test','source_fingerprint':'before'},
                {'private_version':'r-test','source_fingerprint':'after'}])
            with patch.object(build.runpy, 'run_path', return_value={'identify': identify,'verify_archive':verify_android}):
                task = build.Task(Path(folder) / 'native', 'fixture')
                with patch.object(task, 'run', side_effect=lambda model,args:self.fake_assembly(task,model,args)):
                    with self.assertRaisesRegex(ValueError, 'sources changed'):
                        build.package(task, {}, {'e5': {}})
                self.assertFalse((Path(folder) / 'out/releases' / task.id).exists())
                self.assertTrue((Path(folder) / 'out/releases' / ('.building-' + task.id)).exists())

    def test_real_child_logs_and_failure_status(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(build, 'TOP', Path(folder)):
            workspace = Path(folder) / 'native'
            task = build.Task(workspace, 'fixture')
            task.run('ok', [sys.executable, '-c', 'print("test-log-output")'])
            self.assertIn('test-log-output', (task.logs / 'ok.log').read_text())
            with self.assertRaises(subprocess.CalledProcessError):
                task.run('error', [sys.executable, '-c', 'raise SystemExit(3)'])
            status = json.loads((task.logs / 'status.json').read_text())
            self.assertEqual(status['state'], 'failed')
            self.assertEqual([x['state'] for x in status['steps']], ['complete', 'failed'])
            self.assertFalse((Path(folder) / 'out/releases').exists())
            self.assertEqual(list((workspace / 'tmp').iterdir()), [])

    def test_failure_keeps_owned_staging_and_unpublished_archive(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(build, 'TOP', Path(folder)):
            root = Path(folder); workspace = root / 'native'
            with patch.object(build.runpy, 'run_path', return_value={
                'identify': lambda *a: {'private_version':'r-test','source_fingerprint':'same'}}), \
                 patch.object(build, 'input_check'), patch.object(build.os, 'geteuid', return_value=0):
                task = build.Task(workspace, 'fixture')
                def fail(*args):raise RuntimeError('assembler failed')
                with patch.object(task, 'run', side_effect=fail):
                    with self.assertRaisesRegex(RuntimeError, 'assembler failed'):
                        build.package(task, {}, {'e5': {}})
                stage = build.stage_path(workspace, 'e5')
                self.assertTrue((stage / '.build-owner.json').exists())
                self.assertEqual([p.name for p in (root / 'out/releases').iterdir()], ['.building-' + task.id])

    def test_preflight_failure_creates_no_root_staging_or_release(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(build, 'TOP', Path(folder)), \
             patch.object(build.os, 'geteuid', return_value=0), \
             patch.object(build, 'input_check', side_effect=ValueError('stale GUI')):
            task = build.Task(Path(folder) / 'native', 'fixture')
            with self.assertRaisesRegex(ValueError, 'stale GUI'):build.package(task, {}, {'e5': {}})
            self.assertFalse((Path(folder) / 'native/package-work').exists())
            self.assertFalse((Path(folder) / 'out/releases').exists())


if __name__ == '__main__':unittest.main()
