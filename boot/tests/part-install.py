#!/usr/bin/env python3
"""Execute install-part guards against temporary files and mocked raw tools."""
import gzip
import io
from pathlib import Path
import shutil
import struct
import subprocess
import tarfile
import tempfile
import unittest

SOURCE = (Path(__file__).resolve().parents[1] / 'install-part.sh').read_text()


class PreserveData(unittest.TestCase):
    def run_case(self, mode):
        with tempfile.TemporaryDirectory(prefix='e5-part-audit-') as folder:
            root = Path(folder)
            for name in ('dev', 'etc', 'run', 'proc/self', 'sys/class/block/mmcblk0p70',
                         'repair/lib', 'usr/bin', 'mount/e5linux'):
                (root / name).mkdir(parents=True, exist_ok=True)
            dev = root / 'dev/mmcblk0p70'
            data = bytearray(4096)
            struct.pack_into('<I', data, 1024, 0xf2f52010)
            blocks = (4194304 if mode == 'already-shrunk-bad' else 8388608) // 8
            struct.pack_into('<Q', data, 1060, blocks)
            dev.write_bytes(data)
            (root / 'proc/self/mountinfo').write_text('')
            (root / 'sys/class/block/mmcblk0p70/dev').write_text('179:70')
            # Model the sysfs partition symlink used by the shared storage
            # helper, rather than relying on the old mmc name split.
            entry=root/'sys/class/block/mmcblk0p70'
            backing=root/'sys/devices/block/mmcblk0/mmcblk0p70'
            backing.parent.mkdir(parents=True)
            entry.rename(backing); entry.symlink_to(backing)
            (backing/'partition').write_text('70\n')
            (root/'calls').touch()
            payload = root / 'mount/e5linux'
            (payload / 'part-install.conf').write_text('PART_MIB=2048\nDATA_MIB=2048\nGROW_FS=1\n')
            (payload / 'part-install.img.gz').write_bytes(gzip.compress(b'root image' * 100))
            with tarfile.open(payload / 'device-files.tar', 'w') as tar:
                info = tarfile.TarInfo('lib/firmware/wcnmodem.bin'); info.size = 1
                tar.addfile(info, io.BytesIO(b'x'))
            if mode == 'bad-image':
                (payload / 'part-install.img.gz').write_bytes(b'not gzip')
            if mode == 'bad-firmware':
                (payload / 'device-files.tar').write_bytes(b'not tar')
            (root / 'etc/part-progress.sh').write_text(
                'part_progress_start() { :; }\npart_stop() { :; }\n'
                'part_fail() { echo "failure $*" >> "$TRACE"; return 1; }\n')
            loader = root / 'repair/lib/ld-musl-aarch64.so.1'
            loader.write_text('''#!/usr/bin/env python3
import os,sys,struct
from pathlib import Path
p=Path(os.environ['TRACE']); mode=os.environ['CASE']
action='fsck' if any(a.endswith('/fsck.f2fs') for a in sys.argv) else 'resize'
with p.open('a') as f:f.write(action+'\\n')
if action=='resize':
    with open(sys.argv[-1],'r+b') as f:f.seek(1060);f.write(struct.pack('<Q',int(sys.argv[-2])//8))
    sys.exit(1 if mode=='resize-failed' else 0)
if mode in ('orphan-prompt','extra-prompt'):
    answer=sys.stdin.readline().strip()
    if answer!='n':sys.exit(8)
    if mode=='extra-prompt':
        if sys.stdin.readline()=='':sys.exit(255)
        sys.exit(8)
count=p.read_text().splitlines().count('fsck')
sys.exit(3 if mode=='already-shrunk-bad' or (mode=='post-check-failed' and count==2) else 0)
''')
            loader.chmod(0o755)
            gpt = root / 'usr/bin/ucode'
            gpt.write_text('#!/bin/sh\necho gpt >> "$TRACE"\nexit 1\n'); gpt.chmod(0o755)
            storage=(Path(__file__).resolve().parents[1]/'storage.sh').read_text()
            code = (storage+'\n'+SOURCE).replace('[ -b "$dev" ]', '[ -f "$dev" ]')
            code = code.replace('mp=/part-install', 'mp=' + str(root / 'mount'))
            for prefix in ('/etc', '/sys', '/proc', '/repair', '/run', '/usr/bin'):
                code = code.replace(prefix + '/', str(root) + prefix + '/')
            code += '\nmount() { :; }; umount() { :; }; blockdev() { :; }; log() { :; }\n'
            code += f'install_part_pending "{dev}"; echo "result=$?"\n'
            env = dict(__import__('os').environ, TRACE=str(root / 'calls'), CASE=mode)
            result = subprocess.run(['busybox', 'ash'], input=code, text=True,
                                    capture_output=True, env=env, timeout=10)
            calls = (root / 'calls').read_text().splitlines()
            return result, calls

    def test_invalid_payload_never_runs_fsck_resize_or_gpt(self):
        for mode in ('bad-image', 'bad-firmware'):
            with self.subTest(mode=mode):
                result, calls = self.run_case(mode)
                self.assertIn('result=1', result.stdout)
                self.assertFalse(set(calls) & {'fsck', 'resize', 'gpt'})

    def test_failed_resize_is_rejected_even_if_superblock_has_target_size(self):
        result, calls = self.run_case('resize-failed')
        self.assertIn('result=1', result.stdout)
        self.assertEqual(calls[:2], ['fsck', 'resize'])
        self.assertNotIn('gpt', calls)

    def test_inconsistent_shrink_never_shortens_the_partition(self):
        for mode in ('post-check-failed', 'already-shrunk-bad'):
            with self.subTest(mode=mode):
                result, calls = self.run_case(mode)
                self.assertIn('result=1', result.stdout)
                self.assertNotIn('gpt', calls)

    def test_verified_shrink_reaches_gpt_in_order(self):
        result, calls = self.run_case('ok')
        self.assertEqual(calls, ['fsck', 'resize', 'fsck', 'gpt'], result.stderr)


    def test_orphan_export_prompt_has_bounded_answer_in_both_checks(self):
        result,calls=self.run_case('orphan-prompt')
        self.assertEqual(calls,['fsck','resize','fsck','gpt'],result.stderr)

    def test_unexpected_second_prompt_fails_without_resize_or_gpt(self):
        result,calls=self.run_case('extra-prompt')
        self.assertIn('result=1',result.stdout)
        self.assertIn('userdata check failed rc=255', '\n'.join(calls))
        self.assertNotIn('resize',calls)
        self.assertNotIn('gpt',calls)


class CheckProgress(unittest.TestCase):
    def test_partition_stats_report_write_progress_without_task_io_accounting(self):
        progress=(Path(__file__).resolve().parents[1]/'part-progress.sh').read_text()
        with tempfile.TemporaryDirectory(prefix='e5-write-progress-') as folder:
            root=Path(folder)
            for name in ('run','proc/123','dev','sys/class/block/mmcblk0p71'):
                (root/name).mkdir(parents=True,exist_ok=True)
            (root/'proc/uptime').write_text('660.12 0\n')
            (root/'proc/123/status').write_text('State:\tD (disk sleep)\n')
            (root/'proc/123/wchan').write_text('mmc_wait_for_req_done\n')
            # There deliberately is no /proc/123/io.
            (root/'run/part-worker').write_text('123 4194304\n')
            (root/'run/part-disk').write_text('mmcblk0p71 4096\n')
            (root/'sys/class/block/mmcblk0p71/stat').write_text('0 0 0 0 0 0 8192 0 0 0 0\n')
            code=progress.replace('/run/',str(root)+'/run/').replace('/proc/',str(root)+'/proc/').replace('/dev/',str(root)+'/dev/').replace('/sys/',str(root)+'/sys/')
            script=code+'\nsleep() { rm -f '+str(root)+'/run/part-install.running; }\npart_progress_start; wait "$part_beat"\n'
            result=subprocess.run(['busybox','ash'],input=script,text=True,capture_output=True,timeout=5)
            self.assertEqual(result.returncode,0,result.stderr)
            status=(root/'dev/kmsg').read_text()
            self.assertIn('2/4 MiB (50%)',status)
            self.assertIn('writer=123 state=D wait=mmc_wait_for_req_done',status)

    def test_checker_state_io_and_last_line_are_visible(self):
        progress=(Path(__file__).resolve().parents[1]/'part-progress.sh').read_text()
        with tempfile.TemporaryDirectory(prefix='e5-part-progress-') as folder:
            root=Path(folder)
            for name in ('run','proc/123','dev'):(root/name).mkdir(parents=True,exist_ok=True)
            (root/'proc/uptime').write_text('7337.44 0\n')
            (root/'proc/123/status').write_text('Name:\tfsck.f2fs\nState:\tD (disk sleep)\n')
            (root/'proc/123/wchan').write_text('mmc_wait_for_req_done\n')
            (root/'proc/123/io').write_text('read_bytes: 2097152\nwrite_bytes: 1048576\n')
            logfile=root/'run/fsck.log';logfile.write_text('Checking SIT\nChecking NAT\n')
            (root/'run/part-check').write_text('123 '+str(logfile)+'\n')
            progress=progress.replace('/run/',str(root)+'/run/').replace('/proc/',str(root)+'/proc/').replace('/dev/',str(root)+'/dev/')
            # One real heartbeat iteration, without wall-clock waiting.
            script=progress+'\nsleep() { rm -f '+str(root)+'/run/part-install.running; }\npart_progress_start; wait "$part_beat"\n'
            result=subprocess.run(['busybox','ash'],input=script,text=True,capture_output=True,timeout=5)
            self.assertEqual(result.returncode,0,result.stderr)
            status=(root/'dev/kmsg').read_text()
            self.assertIn('state=D wait=mmc_wait_for_req_done',status)
            self.assertIn('read=2.0MiB write=1.0MiB',status)
            self.assertIn('Checking NAT',status)


class ImageReadback(unittest.TestCase):
    def test_real_checksums_reject_short_corrupt_or_unreadable_images(self):
        start = SOURCE.index('    echo "4/6 verifying the complete written image"')
        code = SOURCE[start:SOURCE.index('    mkdir -p /part-root', start)]
        with tempfile.TemporaryDirectory(prefix='e5-part-readback-') as folder:
            root = Path(folder); raw = b'x' * (1048576 + 333)
            for mode in ('ok', 'corrupt', 'short', 'bad-gzip', 'missing'):
                image = root / 'image.gz'; loop = root / 'loop'
                image.write_bytes(gzip.compress(raw) if mode != 'bad-gzip' else b'broken')
                loop.write_bytes(raw + b'tail' if mode == 'ok' else raw[:-1])
                if mode == 'corrupt': loop.write_bytes(b'y' + raw[1:])
                if mode == 'missing': loop.unlink()
                harness = ('verify() {\n' + code + '\n}\n'
                           'losetup() { :; }; umount() { :; }; part_fail() { return 1; }\n'
                           f'img="{image}"; lo="{loop}"; mp="{root}"; raw={len(raw)}\n'
                           'verify\n').replace('/run/part-status', str(root / 'status'))
                p = subprocess.run(['busybox', 'ash'], input=harness, text=True,
                                   capture_output=True, timeout=10)
                self.assertEqual(p.returncode == 0, mode == 'ok', (mode, p.stderr))


class AndroidPartitionWrite(unittest.TestCase):
    def test_readonly_firmware_check_detects_corruption_after_unmount(self):
        source = (Path(__file__).resolve().parents[2] / 'openwrt/bundle/part-write.sh').read_text()
        code = source[source.index("echo '3/4 installing"):source.index('echo "ROOT-VERIFIED')]
        with tempfile.TemporaryDirectory(prefix='e5-part-firmware-') as folder:
            root = Path(folder)
            for mode in ('ok', 'corrupt'):
                stage = root / mode; view = stage / 'view'
                (view / 'sbin').mkdir(parents=True)
                (view / 'etc').mkdir()
                (view / 'etc/openwrt_release').write_text('OpenWrt test\n')
                init = view / 'sbin/init'; init.write_text('#!/bin/sh\n'); init.chmod(0o755)
                (root / 'e5-install.conf').write_text("E5_WIFI_KEY='12345678'\n")
                with tarfile.open(root / 'e5-device-files.tar', 'w') as tar:
                    for name in ('lib/firmware/wcnmodem.bin', 'opt/e5/android/vendor/bin/modem_control'):
                        item = tarfile.TarInfo(name); item.size = 3; item.mode = 0o755
                        tar.addfile(item, io.BytesIO(b'abc'))
                fixture = r'''
mount() { :; }; umount() { :; }; sync() { :; }
blockdev() {
    echo flush >> "$stage/calls"
    [ "$MODE" != corrupt ] || printf damaged > "$stage/view/lib/firmware/wcnmodem.bin"
}
chroot() {
    base=$1; shift 2
    case "$1" in
        find) (cd "$base"; find lib/firmware opt/e5/android -type f -exec sha256sum '{}' \;) ;;
        sha256sum)
            shift
            if [ "$1" = -c ]; then (cd "$base"; sha256sum -c);
            else (cd "$base"; for p in "$@"; do sha256sum "${p#/}"; done); fi ;;
        *) return 1 ;;
    esac
}
'''
                script = ('set -eu\n' + fixture +
                          f'stage="{stage}"; node=mmcblk0p71; token=' + 'c' * 32 +
                          f'; disk=mmcblk0; dev=unused; MODE={mode}; nvbackup="{stage}/no-nv"\n' + code)
                script = script.replace('/data/local/tmp/', str(root) + '/')
                p = subprocess.run(['busybox', 'ash'], input=script, text=True,
                                   capture_output=True, timeout=10)
                self.assertEqual(p.returncode == 0, mode == 'ok', p.stderr)
                self.assertEqual((stage / 'calls').read_text(), 'flush\n')
                self.assertEqual((view / 'etc/e5/install.conf').stat().st_mode & 0o777, 0o600)

    def test_tools_creation_failure_releases_installation_lock(self):
        source = (Path(__file__).resolve().parents[2] / 'openwrt/bundle/part-write.sh').read_text()
        code = source[source.index('lock=/data/local/tmp/'):source.index('tar -xf /data/local/tmp/e5-ext4-tools.tar')]
        with tempfile.TemporaryDirectory(prefix='e5-part-lock-') as folder:
            code = code.replace('/data/local/tmp/', folder + '/')
            p = subprocess.run(['busybox', 'ash'], input='set -eu\nmktemp() { return 1; }\n' + code,
                               text=True, capture_output=True, timeout=10)
            self.assertNotEqual(p.returncode, 0)
            self.assertFalse((Path(folder) / 'e5-part-write.lock').exists(), p.stderr)


if __name__ == '__main__':
    if not shutil.which('busybox'):
        raise SystemExit('requires Linux BusyBox')
    unittest.main()
