#!/usr/bin/env python3
"""Upload an update over authenticated SSH; no inbound PC firewall rule needed."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import shlex
import socket
import struct
import sys
import time
import uuid
GUI = None


def partition_update_command(image):
    if image[:8] != b'ANDROID!' or len(image) < 1584 or struct.unpack_from('<I', image, 40)[0] != 4:
        raise ValueError('Partition update requires a verified boot-v4 image')
    pad = b'e5.lkpad=0000000000 ' if image[44:1580].startswith(b'e5.lkpad=') else b''
    return pad + b'e5.part_v=2 e5.root=part e5.part_update=1'


def bind_update_boot(image, manifest, fallback, linux_trial, helper):
    if hashlib.sha256(image).hexdigest() != manifest['sha256']:
        raise ValueError('Package boot checksum mismatch')
    android = helper['validate_control'](fallback)
    linux = 'b' if android == 'a' else 'a'
    if (len(linux_trial) != 32 or linux_trial[:2] != ('_'+linux).encode()
            or linux_trial[4:8] != b'BCAB'
            or struct.unpack_from('<I',linux_trial,28)[0] != __import__('zlib').crc32(linux_trial[:28])):
        raise ValueError('Installed Android/Linux boot roles conflict')
    if android == 'b' and manifest.get('slot_roles_version',0) < 1:
        raise ValueError('Package initramfs lacks dynamic-slot support')
    return helper['bind_boot'](image, fallback, android)


def read_control(client, path):
    _, out, err = client.exec_command('cat '+path, timeout=15)
    data = out.read(); error = err.read()
    if out.channel.recv_exit_status() or len(data) != 32:
        raise ValueError('Cannot read installed boot role: '+path+' '+error.decode('utf-8','replace'))
    return data


def image_capacity(client):
    if GUI:
        return int(GUI.ctx.record['plan']['openwrt_bytes'])
    # Use raw SSH stdout, without requiring od/hexdump or SFTP on OpenWrt.
    dev = execute(client, "readlink -f $(awk '$2==\"/\" {print $1}' /proc/mounts | tail -1)").strip()
    if not re.fullmatch(r'/dev/(?:block/)?(?:mmcblk\d+(?:p\d+)?|sd[a-z]+[1-9][0-9]*|loop\d+)', dev):
        raise ValueError('Cannot identify the current image root')
    _, out, err = client.exec_command(f'dd if={dev} bs=1024 skip=1 count=1 2>/dev/null', timeout=15)
    raw = out.read()
    err.read()
    if out.channel.recv_exit_status() or len(raw) != 1024 or raw[56:58] != b'\x53\xef':
        raise ValueError('Cannot read the current ext4 image capacity')
    shift = struct.unpack_from('<I', raw, 24)[0]
    blocks = struct.unpack_from('<I', raw, 4)[0]
    if struct.unpack_from('<I', raw, 96)[0] & 0x80:
        blocks |= struct.unpack_from('<I', raw, 336)[0] << 32
    if shift > 6 or not blocks:
        raise ValueError('Invalid ext4 image capacity')
    return blocks * (1024 << shift)


def execute(client, command, timeout=1800):
    channel = client.get_transport().open_session()
    channel.settimeout(timeout)
    channel.exec_command('set -eu\n' + command)
    result = bytearray()
    deadline = time.monotonic() + timeout
    while not channel.exit_status_ready() or channel.recv_ready() or channel.recv_stderr_ready():
        if time.monotonic() > deadline:
            channel.close()
            raise TimeoutError('device update command timed out')
        for ready, read in ((channel.recv_ready, channel.recv), (channel.recv_stderr_ready, channel.recv_stderr)):
            if ready():
                data = read(65536)
                result.extend(data)
                print(data.decode('utf-8', 'replace'), end='', flush=True)
        time.sleep(.03)
    status = channel.recv_exit_status()
    channel.close()
    if status:
        lines = result.decode('utf-8', 'replace').strip().splitlines()
        detail = ': '+lines[-1][:500] if lines else ''
        raise RuntimeError(f'device command failed (exit {status}); no success was reported'+detail)
    return result.decode('utf-8', 'replace')


def upload(client, path, destination):
    size = path.stat().st_size
    channel = client.get_transport().open_session()
    channel.settimeout(120)
    channel.exec_command('umask 077; cat > ' + shlex.quote(destination))
    count = 0; digest = hashlib.sha256(); last = 0
    started = time.monotonic()
    with path.open('rb') as stream:
        while data := stream.read(262144):
            channel.sendall(data); digest.update(data); count += len(data)
            if GUI: GUI.transfer(path.name, count, size, started)
            if time.monotonic() - last >= 1:
                print(f'\r   {path.name}: {count >> 20}/{size >> 20} MiB', end='', flush=True)
                last = time.monotonic()
    channel.shutdown_write()
    error = channel.makefile_stderr().read().decode('utf-8', 'replace')
    status = channel.recv_exit_status(); channel.close()
    print()
    if status:
        raise RuntimeError('upload failed: ' + error)
    expected = digest.hexdigest()
    got = execute(client, 'sha256sum ' + shlex.quote(destination)).split()[0]
    if got != expected:
        raise RuntimeError('uploaded file checksum mismatch: ' + path.name)


def save_nv_backup(client, stage, profile, compress=False):
    """Persist a verified copy on the PC before any root/boot overwrite.

    The early-boot updater still captures the final, fully stopped working
    copies. This separate copy survives a power loss during a full rewrite.
    No NV bytes are printed and no SFTP server is required.
    """
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,40}', profile): raise ValueError('Invalid NV backup profile')
    policy = 'preserve'
    archive_flags = ' --gzip' if compress else ''
    try:
        result = execute(client, 'if [ -e /opt/e5/nv ] || [ -L /opt/e5/nv ]; then '
            'python3 '+shlex.quote(stage+'/nv-persistence.py')+' archive --lock'+archive_flags+' > '+shlex.quote(stage+'/nv.tar')+'; '
            'printf "NV-BACKUP "; sha256sum '+shlex.quote(stage+'/nv.tar')+' | cut -d" " -f1; '
            'else echo NV-NONE; fi')
    except Exception as error:
        detail = str(error)
        if re.search(r'\b(?:nv_busy|nv_writer_busy|BlockingIOError)\b', detail):
            raise ValueError('Another update or NV operation is active; retry after it finishes / '
                             '更新或 NV 操作正在执行，请在完成后重试；未改用原机 NV') from error
        # Only an identified working-copy integrity/source error can offer
        # original-NV recovery. Connectivity, locking and program errors do
        # not establish that the working NV is damaged.
        if not re.search(r'\bnv_(?:invalid_(?:header|size|checksum|runtime)|origin_unavailable|'
                         r'work_unavailable|snapshot_changed)\b', detail):
            raise
        # Verify a separate source first. A mutex/transport/original-NV failure
        # cannot be bypassed by merely clicking a recovery button.
        try:
            result = execute(client, 'python3 '+shlex.quote(stage+'/nv-persistence.py')+
                ' factory-archive --lock'+archive_flags+' > '+shlex.quote(stage+'/nv-original.tar')+'; '
                'printf "NV-BACKUP "; sha256sum '+shlex.quote(stage+'/nv-original.tar')+' | cut -d" " -f1')
        except Exception as source_error:
            raise ValueError('Original NV recovery could not be verified; nothing overwritten / '
                             '本机原始 NV 的恢复检查未完成，尚未覆盖系统') from source_error
        reason = 'Working NV could not be preserved / 工作 NV 无法保留: '+str(error)
        if GUI:
            accepted = GUI.confirm_nv_recovery(reason)
        else:
            print(reason)
            accepted = input('Use this device\'s original (Android) NV instead? OpenWrt NV changes will be lost; '
                'original partitions are not modified. / 改用本机原始 NV，将丢失 OpenWrt NV 修改，原分区不变。输入 yes: ').strip() == 'yes'
        if not accepted: raise ValueError('NV recovery declined; nothing overwritten / 未确认恢复，未覆盖系统')
        execute(client, 'mv '+shlex.quote(stage+'/nv-original.tar')+' '+shlex.quote(stage+'/nv.tar'))
        policy = 'original'
    if result.strip() == 'NV-NONE': return None
    matches = re.findall(r'^NV-BACKUP ([0-9a-f]{64})$', result, re.M)
    if len(matches) != 1: raise ValueError('NV backup did not complete; update stopped')
    base = Path(GUI.backup_base()) if GUI and hasattr(GUI, 'backup_base') else Path.home()/'e5-backups'
    directory = base/'nv-updates'/(profile+'-'+time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8])
    directory.mkdir(parents=True, mode=0o700)
    path = directory/'nv.tar'; checksum = hashlib.sha256()
    record = {'profile': profile, 'time': int(time.time()), 'sha256': matches[0], 'ok': False,
              'policy': policy, 'compression': 'gzip' if compress else 'none'}
    try:
        _, out, err = client.exec_command('cat '+shlex.quote(stage+'/nv.tar'), timeout=180)
        with path.open('xb') as stream:
            os.chmod(path, 0o600)
            while data := out.read(262144):
                stream.write(data); checksum.update(data)
            stream.flush(); os.fsync(stream.fileno())
        err.read()
        if out.channel.recv_exit_status() or checksum.hexdigest() != matches[0]:
            raise ValueError('NV backup readback failed; update stopped; retained '+str(directory))
        (directory/'SHA256SUMS').write_text(matches[0]+'  nv.tar\n',encoding='utf-8')
        record['ok'] = True
    except Exception as error:
        record['error'] = str(error)
        raise
    finally:
        (directory/'backup.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    print('NV backup verified / NV 备份已校验: '+str(path), flush=True)
    return path


def main():
    import paramiko
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--package', type=Path, required=True)
    p.add_argument('--host', required=True)
    p.add_argument('--raw-size', type=int, required=True)
    p.add_argument('--raw-sha256', required=True)
    p.add_argument('--check-only', action='store_true', help='validate the connected device without staging or flashing')
    a = p.parse_args()
    files = a.package / 'files'
    profile = json.loads((files / 'device-profile.json').read_text())['profile'] if (files / 'device-profile.json').exists() else 'e5'
    client = paramiko.SSHClient()
    # USB-connected devices reuse the same management address. Keep trust
    # within this connection rather than pinning that IP to one installation.
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    if GUI:
        GUI.connect_ssh(client,a.host,GUI.password)
    else:
        client.connect(a.host, username='root', password=os.environ['E5_TELNET_PASS'],
                       look_for_keys=False, allow_agent=False, timeout=30, banner_timeout=60, auth_timeout=60)
        client.get_transport().set_keepalive(15)
    if GUI: GUI.validate_ssh(client)
    stage = None
    try:
        execute(client, '[ "$(id -u)" = 0 ]')
        source_profile = execute(client, 'cat /etc/e5/device-profile').strip()
        if not re.fullmatch(r'[a-z][a-z0-9-]{0,40}', source_profile):
            raise ValueError('Cannot read the installed profile / 无法读取已安装系统的机型标识')
        if source_profile != profile:
            if GUI:
                GUI.confirm_update_profile(source_profile)
            else:
                print('Model mismatch / 机型不匹配: ' + source_profile + ' -> ' + profile)
                print('Display, charging or boot may be incompatible. / 屏幕、充电或启动可能不兼容。')
                if input('Type yes to use this package anyway / 输入 yes 仍使用此安装包: ').strip() != 'yes':
                    raise ValueError('Model exception declined; nothing staged / 未确认机型例外，尚未上传更新')
        # Detection and capacity checks precede uploads and all boot writes.
        layout = execute(client, 'if [ -f /etc/e5/part-root ]; then echo part; '
            'elif [ -f /etc/e5/sd-root ]; then echo sd; else echo image; fi').strip()
        capacity_env = ''
        if layout == 'image':
            capacity = image_capacity(client)
            if capacity < a.raw_size:
                raise ValueError('New image exceeds the installed filesystem capacity; nothing staged')
            capacity_env = 'E5_IMAGE_FS_BYTES=' + str(capacity) + ' '
        boot = json.loads((files / 'boot.json').read_text())
        helper = runpy.run_path(str(a.package/'scripts/installer/boot-slots.py'))
        bound_boot = bind_update_boot((files/'boot.img').read_bytes(), boot,
            read_control(client,'/run/e5linux/misc-bc-slot-a.bin'),
            read_control(client,'/run/e5linux/misc-bc-slot-b-trial.bin'), helper)
        if layout in ('part', 'sd') and not boot.get('part_update'):
            raise RuntimeError('this package has no independent-partition update support; use a newer package')
        if layout == 'sd' and not boot.get('tf_update'):
            raise RuntimeError('this package has no single-root TF update support; rebuild the package')
        if layout in ('part', 'sd'):
            execute(client, 'dev=$(cat /run/e5linux/' + layout + '-root-dev); '
                '[ -b "$dev" ] && [ "$(awk \'$2=="/" {print $1}\' /proc/mounts | tail -1)" = "$dev" ]; '
                'sectors=$(cat /sys/class/block/${dev##*/}/size); '
                'test "$((sectors * 512))" -ge ' + str(a.raw_size))
        if a.check_only:
            print('Update preflight passed / 更新预检查通过: ' + profile + ', ' + layout)
            return
        # Root-backed staging: a complete NV snapshot and uploaded image must
        # not compete with the running screen/browser for tmpfs RAM.
        stage = '/.e5-upload-' + uuid.uuid4().hex
        required = sum((files / n).stat().st_size for n in ('boot.img', 'openwrt.ext4.gz', 'ext4-tools.tar')) + (64 << 20)
        execute(client, 'test "$(df -Pk / | awk \'NR==2 {print $4}\')" -gt ' + str((required+1023)//1024) + '; mkdir -m 700 ' + stage)
        # Internal partition updates carry the selection in the boot header,
        # allowing encrypted Android userdata to stay completely unmounted.
        with __import__('tempfile').TemporaryDirectory() as temporary:
            image = bytearray(bound_boot)
            if layout == 'part':
                image[44:1580] = partition_update_command(image).ljust(1536, b'\0')
            head = Path(temporary) / 'boot-head.img'
            head.write_bytes(image[:boot['persist_log_offset']])
            for name in ('openwrt.ext4.gz', 'ext4-tools.tar', 'device-install-image.sh',
                         'device-flash-boot.sh', 'device-stage-part-update.sh', 'e5-gpt', 'storage.sh', 'nv-persistence.py'):
                upload(client, files / name, stage + '/' + name)
            upload(client, head, stage + '/boot-head.img')
            nv_backup = save_nv_backup(client, stage, source_profile, compress=layout in ('part', 'sd'))
            nv_policy = json.loads((nv_backup.parent/'backup.json').read_text())['policy'] if nv_backup else 'preserve'
            command = ('umask 077; mkdir -p /run/e5-upgrade; '
                '[ ! -L /run/e5-upgrade ] && [ "$(stat -c %u:%a /run/e5-upgrade)" = 0:700 ]; '
                '[ ! -L /run/e5-upgrade/lock ]; exec 8>>/run/e5-upgrade/lock; '
                'flock -n 8 || { echo "another upgrade is running"; exit 1; }; '
                'export E5_UPGRADE_LOCK_HELD=1; ' +
                capacity_env + 'E5_NV_POLICY='+nv_policy+' E5_IMAGE_SIZE=' + str(a.raw_size) + ' E5_IMAGE_SHA256=' + shlex.quote(a.raw_sha256) +
                ' E5_UPDATE_PROFILE=' + shlex.quote(profile) +
                ' E5_UPDATE_SOURCE_PROFILE=' + shlex.quote(source_profile) +
                ' sh ' + stage + '/device-stage-part-update.sh ' + stage)
            command += '; sh ' + stage + '/device-flash-boot.sh ' + stage + '/boot-head.img ' + \
                    hashlib.sha256(head.read_bytes()).hexdigest() + ' ' + str(boot['persist_log_offset'] >> 20)
            # Publish an internal update request only after boot readback passes.
            if layout in ('part', 'sd'):
                command += '; mv /.e5-update/request.ready /.e5-update/request; sync'
            else:
                command += '; e5-os openwrt'
            command += '; echo "== all uploaded files verified; rebooting"; (sleep 3; reboot) </dev/null >/dev/null 2>&1 &'
            if GUI: GUI.action('update-commit', lambda: execute(client, command))
            else: execute(client, command)
            print('Update verified; rebooting / 更新已校验，正在重启', flush=True)
    finally:
        if stage:
            try:
                execute(client, 'rm -rf ' + shlex.quote(stage), timeout=15)
            except Exception:
                pass  # A completed offline rewrite also removes its old staging.
        client.close()


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        raise SystemExit('Update failed / 更新失败: ' + str(error))
