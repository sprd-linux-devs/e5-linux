"""Run the real image capacity helper on disposable ext4 files, never devices."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

TOP = Path(__file__).resolve().parents[2]
SOURCE = (TOP / 'openwrt/device-install-image.sh').read_text(encoding='utf-8')
START = SOURCE.index('preserve_image_capacity() (')
FUNCTION = SOURCE[START:SOURCE.index('\n)\n', START) + 3]
TOOLS = ('sh', 'mke2fs', 'e2fsck', 'resize2fs', 'debugfs', 'fallocate')


@unittest.skipUnless(all(shutil.which(tool) for tool in TOOLS), 'requires Linux ext4 tools')
class ImageUpdateCapacity(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.old = self.image('old.ext4', 16 << 20)
        self.new = self.image('new.ext4', 8 << 20)
        self.old_hash = hashlib.sha256(self.old.read_bytes()).digest()

    def tearDown(self):
        self.temp.cleanup()

    def image(self, name, size):
        path = self.root / name
        with path.open('wb') as stream:
            stream.truncate(size)
        subprocess.run(['mke2fs', '-q', '-F', '-t', 'ext4', '-b', '4096', str(path)],
                       check=True, capture_output=True)
        return path

    def helper(self, old=None, archive=None, filesystem=None):
        environment = dict(os.environ)
        environment.pop('E5_IMAGE_FS_BYTES', None)
        if filesystem is not None:
            environment['E5_IMAGE_FS_BYTES'] = str(filesystem)
        result = subprocess.run(['sh', '-ec', FUNCTION + '\npreserve_image_capacity "$1" "$2" "$3"',
                                 'test', str(self.new), str(old or self.old),
                                 str(archive or self.root / 'missing-tools.tar')],
                                capture_output=True, text=True, timeout=30, env=environment)
        self.assertEqual(hashlib.sha256(self.old.read_bytes()).digest(), self.old_hash,
                         'the old system image was modified')
        return result

    def capacity(self):
        with self.new.open('rb') as stream:
            stream.seek(1024)
            data = stream.read(1024)
        return struct.unpack_from('<I', data, 4)[0] * (1024 << struct.unpack_from('<I', data, 24)[0])

    def archive(self):
        tools = self.root / 'tools'
        loader = tools / 'lib/ld-musl-aarch64.so.1'
        loader.parent.mkdir(parents=True)
        loader.write_text('#!/bin/sh\n[ "$1" = --library-path ] || exit 9\nshift 2\nexec "$@"\n')
        loader.chmod(0o755)
        files = [loader]
        for name in ('e2fsck', 'resize2fs'):
            tool = tools / ('usr/sbin/' + name)
            tool.parent.mkdir(parents=True, exist_ok=True)
            tool.write_text('#!/bin/sh\nexec ' + shutil.which(name) + ' "$@"\n')
            tool.chmod(0o755)
            files.append(tool)
        (tools / 'SHA256SUMS').write_text(''.join(hashlib.sha256(path.read_bytes()).hexdigest() +
                                              '  ' + path.relative_to(tools).as_posix() + '\n'
                                              for path in files))
        archive = self.root / 'ext4-tools.tar'
        with tarfile.open(archive, 'w') as output:
            for path in tools.rglob('*'):
                output.add(path, arcname=path.relative_to(tools).as_posix(), recursive=False)
        return archive

    def test_grown_replacement_keeps_files_and_old_system(self):
        marker = self.root / 'marker'
        marker.write_text('replacement system content\n')
        subprocess.run(['debugfs', '-w', '-R', 'write ' + str(marker) + ' /marker', str(self.new)],
                       check=True, capture_output=True)
        result = self.helper()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.new.stat().st_size, 16 << 20)
        self.assertEqual(self.capacity(), 16 << 20)
        content = subprocess.run(['debugfs', '-R', 'cat /marker', str(self.new)],
                                 check=True, capture_output=True, text=True).stdout
        self.assertEqual(content, marker.read_text())

    def test_packaged_tool_dispatch_also_grows_real_ext4(self):
        result = self.helper(archive=self.archive())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.capacity(), 16 << 20)

    def test_file_allocation_and_filesystem_capacity_remain_distinct(self):
        self.old = self.image('old-unexpanded.ext4', 8 << 20)
        with self.old.open('r+b') as stream:
            stream.truncate(16 << 20)
        self.old_hash = hashlib.sha256(self.old.read_bytes()).digest()
        result = self.helper(filesystem=8 << 20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.new.stat().st_size, 16 << 20)
        self.assertEqual(self.capacity(), 8 << 20)

    def test_reported_two_to_four_gib_capacity(self):
        if shutil.disk_usage(self.root).free < 5 << 30:
            self.skipTest('needs 5 GiB free for a temporary replacement file')
        previous = self.image('old-four-gib.ext4', 4 << 30)
        self.new = self.image('new-two-gib.ext4', 2 << 30)
        with previous.open('rb') as stream:
            stream.seek(1024)
            before = stream.read(1024)
        result = self.helper(old=previous)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.new.stat().st_size, 4 << 30)
        self.assertEqual(self.capacity(), 4 << 30)
        with previous.open('rb') as stream:
            stream.seek(1024)
            self.assertEqual(stream.read(1024), before)

    def test_bad_packaged_tools_stop_without_allocating_or_replacing(self):
        archive = self.archive()
        with tarfile.open(archive, 'a') as output:
            changed = self.root / 'changed'
            changed.write_text('changed tool')
            output.add(changed, arcname='usr/sbin/resize2fs')
        before = self.new.read_bytes()
        self.assertNotEqual(self.helper(archive=archive).returncode, 0)
        self.assertEqual(self.new.read_bytes(), before)

    def test_larger_new_image_stops_instead_of_shrinking_or_committing(self):
        self.new = self.image('too-large.ext4', 24 << 20)
        self.assertNotEqual(self.helper().returncode, 0)

    def test_equal_capacity_and_first_install_are_unchanged(self):
        for previous in (self.new, self.root / 'not-installed.ext4'):
            with self.subTest(previous=previous):
                before = self.new.read_bytes()
                result = self.helper(old=previous)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(self.new.read_bytes(), before)

    def test_failed_resize_leaves_old_system_untouched(self):
        archive = self.archive()
        with tarfile.open(archive, 'a') as output:
            failing = self.root / 'failing'
            failing.write_text('#!/bin/sh\nexit 7\n')
            failing.chmod(0o755)
            output.add(failing, arcname='usr/sbin/resize2fs')
            tools = self.root / 'tools'
            (tools / 'usr/sbin/resize2fs').write_bytes(failing.read_bytes())
            entries = [p for p in tools.rglob('*') if p.is_file() and p.name != 'SHA256SUMS']
            manifest = self.root / 'manifest'
            manifest.write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest() + '  ' +
                                        p.relative_to(tools).as_posix() + '\n' for p in entries))
            output.add(manifest, arcname='SHA256SUMS')
        self.assertEqual(self.helper(archive=archive).returncode, 7)


class IntegrationOrder(unittest.TestCase):
    def test_growth_precedes_mount_settings_and_commit(self):
        call = SOURCE.index('preserve_image_capacity "$PART" "$IMG"')
        for step in ('mount -t ext4 -o loop "$PART"', 'keep_config "$from" "$N"',
                     'mv "$PART" "$IMG.new"', 'mv "$PART" "$IMG"'):
            self.assertGreater(SOURCE.index(step), call)
        self.assertIn('previous_bytes=$(stat -c %s "$IMG")', SOURCE)
        self.assertIn('required_kib=$(( (previous_bytes + 1023) / 1024 + 524288 ))', SOURCE)


class HostImageCapacity(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('e5_capacity_update', TOP / 'tools/e5-update.py')
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def test_cli_reads_binary_superblock_without_od_or_sftp(self):
        raw = bytearray(1024)
        raw[56:58] = b'\x53\xef'
        struct.pack_into('<I', raw, 4, (4 << 30) // 4096)
        struct.pack_into('<I', raw, 24, 2)
        client = Mock()
        client.exec_command.return_value = (None, SimpleNamespace(read=lambda: bytes(raw),
            channel=SimpleNamespace(recv_exit_status=lambda: 0)), io.BytesIO())
        with patch.object(self.module, 'execute', return_value='/dev/loop0'):
            self.assertEqual(self.module.image_capacity(client), 4 << 30)
        client.exec_command.assert_called_once_with('dd if=/dev/loop0 bs=1024 skip=1 count=1 2>/dev/null', timeout=15)
        client.open_sftp.assert_not_called()

    def test_gui_capacity_is_passed_to_the_real_commit_command(self):
        for capacity in (2 << 30, 4 << 30):
            with self.subTest(capacity=capacity), tempfile.TemporaryDirectory() as folder:
                files = Path(folder) / 'files'
                files.mkdir()
                for name in ('boot.img', 'openwrt.ext4.gz', 'ext4-tools.tar'):
                    (files / name).write_bytes(b'fixture')
                (files / 'boot.json').write_text(json.dumps({'persist_log_offset': 1 << 20}))
                gui = SimpleNamespace(password='', ctx=SimpleNamespace(record={'plan': {'openwrt_bytes': capacity}}),
                                      validate_ssh=Mock(), connect_ssh=Mock(),
                                      action=lambda name, operation: operation())
                commands = []
                def execute(_client, command, **_options):
                    commands.append(command)
                    if command=='cat /etc/e5/device-profile':return 'e5'
                    return 'image' if command.startswith('if [ -f /etc/e5/part-root ]') else ''
                with patch.object(self.module, 'GUI', gui), patch.object(self.module, 'execute', side_effect=execute), \
                     patch.object(self.module.runpy, 'run_path', return_value={}), \
                     patch.object(self.module, 'read_control', return_value=b'control'), \
                     patch.object(self.module, 'bind_update_boot', return_value=b'fixture'), \
                     patch.object(self.module, 'save_nv_backup', return_value=None), \
                     patch.object(self.module, 'upload'), patch.dict('sys.modules', {'paramiko': Mock()}), \
                     patch('sys.argv', ['e5-update', '--package', folder, '--host', '192.0.2.1',
                                        '--raw-size', str(2 << 30), '--raw-sha256', 'a' * 64]), \
                     patch('sys.stdout', new_callable=io.StringIO):
                    self.module.main()
                commit = next(command for command in commands if 'device-stage-part-update.sh ' in command)
                self.assertIn('E5_IMAGE_FS_BYTES=' + str(capacity) + ' ', commit)


if __name__ == '__main__':
    unittest.main()
