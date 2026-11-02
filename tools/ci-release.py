#!/usr/bin/env python3
"""Record release sources/time, then verify a flash bundle before publication."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import struct
import tarfile
import time
import zipfile

TOP = Path(__file__).resolve().parents[1]
UTC8 = timezone(timedelta(hours=8))
RELEASE = TOP / 'out/release'
BLOCK_SOURCES = ('block-mount.Dockerfile', 'build-block-mount.sh',
                 'build-block-mount-inner.sh', 'block-probe-guard.h',
                 'patches/fstools-probe-device-types.patch')


def block_build_id():
    # Same ordered input bytes as build-block-mount.sh's cache stamp.
    return hashlib.sha256(b''.join((TOP / 'openwrt' / name).read_bytes()
                                   for name in BLOCK_SOURCES)).hexdigest()


def digest(stream):
    result = hashlib.sha256()
    while data := stream.read(1 << 20):
        result.update(data)
    return result.hexdigest()


def file_digest(path):
    with path.open('rb') as stream:
        return digest(stream)


def revision(path):
    return subprocess.check_output(['git', '-C', str(path), 'rev-parse', 'HEAD'], text=True).strip()


def outputs(values):
    target = os.environ.get('GITHUB_OUTPUT')
    if target:
        with open(target, 'a') as stream:
            for name, value in values.items():
                stream.write(f'{name}={value}\n')


def prepare():
    epoch = int(time.time())
    started = datetime.fromtimestamp(epoch, UTC8)
    stamp = started.strftime('%Y%m%d-%H%M%S')
    ver = os.environ.get('E5_WRT_VER', '25.12.5')
    if not re.fullmatch(r'\d+\.\d+\.\d+', ver):
        raise ValueError('invalid OpenWrt version')
    sources = {name: {'repository': repo, 'revision': revision(path)} for name, repo, path in [
        ('e5-linux', os.environ.get('GITHUB_REPOSITORY', 'Enceka/e5-linux'), TOP),
        ('kernel', 'Enceka/linux-lts-e5', TOP / 'linux-lts-e5'),
        ('infoscreen', 'Enceka/infoscreen', TOP / 'ci/infoscreen'),
        ('plugins', 'Enceka/infoscreen-plugins', TOP / 'ci/infoscreen-plugins'),
    ]}
    RELEASE.mkdir(parents=True, exist_ok=True)
    info = {'build_epoch': epoch, 'build_started_at': started.isoformat(timespec='seconds'),
            'timestamp': stamp, 'openwrt_version': ver, 'sources': sources,
            'bootstrap_sha256': os.environ.get('E5_CI_INPUTS_SHA256'),
            'run_url': os.environ.get('E5_RUN_URL')}
    (RELEASE / 'build.json').write_text(json.dumps(info, indent=2) + '\n')
    env = os.environ.get('GITHUB_ENV')
    if env:
        with open(env, 'a') as stream:
            stream.write(f'E5_BUILD_EPOCH={epoch}\n')
            stream.write('KBUILD_BUILD_TIMESTAMP=' + started.strftime('%a %b %d %H:%M:%S %z %Y') + '\n')
    outputs({'timestamp': stamp, 'release_tag': f'build-{stamp}-{sources["e5-linux"]["revision"][:7]}'})
    print(info['build_started_at'])


def audit_root(info):
    expected = {}
    for source, root, relative, prefix in [
        ('e5-linux', TOP, 'openwrt/overlay', ''),
        ('infoscreen', TOP / 'ci/infoscreen', 'root', ''),
        ('plugins', TOP / 'ci/infoscreen-plugins', 'plugins/phone', 'etc/e5-infoscreen/plugins/phone/'),
    ]:
        files = subprocess.check_output(['git', '-C', str(root), 'ls-files', relative], text=True).splitlines()
        for item in files:
            tail = Path(item).relative_to(relative).as_posix()
            # rc/config may change during assembly; verify runtime backend/UI files.
            if source != 'plugins' and not tail.startswith(('usr/', 'www/')):
                continue
            if source == 'e5-linux' and tail == 'usr/libexec/e5-sysupgrade':
                # build-rootfs.sh installs this safety guard at /sbin/sysupgrade.
                tail = 'sbin/sysupgrade'
            expected[prefix + tail] = file_digest(root / item)
    # These shared startup files are copied from the Debian overlay, rather
    # than openwrt/overlay. Verify the selective cold-start adapter as well.
    for name in ('vendor-start.sh', 'e5-modem-coldboot'):
        expected['opt/e5/' + name] = file_digest(TOP / 'rootfs/overlay/opt/e5' / name)
    helper = TOP / 'out/modem-loader/modem-loader-patch'
    receipt = json.loads(helper.with_suffix('.build.json').read_text())
    if (receipt['inputs']['source'] != file_digest(TOP/'openwrt/src/modem-loader-patch.c') or
            receipt['inputs']['builder'] != file_digest(TOP/'devices/common/build-modem-loader.py') or
            receipt['binary'] != file_digest(helper)):
        raise ValueError('Loader recognizer build receipt differs from current sources')
    expected['opt/e5/modem-loader-patch'] = receipt['binary']
    expected['etc/e5/block-mount.build-id'] = hashlib.sha256((block_build_id() + '\n').encode()).hexdigest()
    import runpy
    wifi_id = runpy.run_path(str(TOP / 'openwrt/wifi-sae-state.py'))['build_id']()
    expected['etc/e5/wifi-sae.build-id'] = hashlib.sha256((wifi_id + '\n').encode()).hexdigest()
    expected['lib/netifd/hostapd-unisoc.sh'] = file_digest(TOP / 'openwrt/hostapd-unisoc.sh')
    expected['usr/share/ucode/wifi/unisoc-sae.uc'] = file_digest(TOP / 'openwrt/hostapd-unisoc.uc')
    found, versions, modules = {}, {}, set()
    rootfs = TOP / 'work/openwrt' / f'e5-openwrt-{info["openwrt_version"]}-generic-rootfs.tar.gz'
    if not rootfs.is_file():
        raise ValueError(f'root filesystem archive was not built: {rootfs}; inspect bundle-build.log for the original failure')
    forbidden = re.compile(r'^(?:lib/firmware/(?:wcnmodem|gnssmodem|l_agdsp|wifi_board|sprd/)|'
                           r'opt/e5/android/.+|etc/e5/install\.conf|etc/dropbear/dropbear_.+_host_key|etc/ssh/ssh_host_)')
    wanted = {'usr/share/e5-infoscreen/VERSION', 'etc/e5-infoscreen/plugins/phone/manifest.json',
              'etc/e5/build-time', 'etc/machine-id',
              'sbin/block', 'lib/libblkid-tiny.so', 'etc/init.d/fstab'}
    with tarfile.open(rootfs, 'r|gz') as archive:
        for entry in archive:
            name = entry.name.removeprefix('./')
            if forbidden.match(name):
                raise ValueError('device-specific file in generic image: ' + name)
            if name.startswith('lib/modules/') and entry.isfile() and name.endswith('.ko'):
                modules.add(name.split('/')[2])
            if entry.isfile() and (name in expected or name in wanted):
                stream = archive.extractfile(entry)
                if name in wanted:
                    data = stream.read()
                    versions[name] = data
                    found[name] = hashlib.sha256(data).hexdigest()
                else:
                    found[name] = digest(stream)
    missing = set(expected) - set(found)
    different = [name for name in expected if name in found and expected[name] != found[name]]
    if missing or different:
        raise ValueError(f'root source mismatch: missing={sorted(missing)}, changed={different}')
    for name in ('sbin/block', 'lib/libblkid-tiny.so', 'etc/init.d/fstab'):
        if not versions.get(name):
            raise ValueError('guarded block-mount payload missing: ' + name)
    kernel = (TOP / 'upstream/out-release/kernel.release').read_text().strip()
    if modules != {kernel}:
        raise ValueError('root modules do not all match the release kernel')
    if int(versions['etc/e5/build-time']) != info['build_epoch']:
        raise ValueError('root image build time differs from CI compile start')
    if versions.get('etc/machine-id', b'').strip():
        raise ValueError('generic image has a machine ID')
    info.update({'kernel_release': kernel, 'infoscreen_version': versions['usr/share/e5-infoscreen/VERSION'].decode().strip(),
                 'phone_version': json.loads(versions['etc/e5-infoscreen/plugins/phone/manifest.json'])['version']})


def verify():
    info = json.loads((RELEASE / 'build.json').read_text())
    audit_root(info)
    # Ensure nobody advanced one of the checkouts during the build.
    for name, path in [('e5-linux', TOP), ('kernel', TOP / 'linux-lts-e5'),
                       ('infoscreen', TOP / 'ci/infoscreen'), ('plugins', TOP / 'ci/infoscreen-plugins')]:
        if revision(path) != info['sources'][name]['revision']:
            raise ValueError('source revision changed: ' + name)
    glob = f'e5-openwrt-flash-{info["openwrt_version"]}-mainline-{info["timestamp"]}-*.tar.gz'
    candidates = list((TOP / 'out/openwrt').glob(glob))
    if len(candidates) != 1:
        raise ValueError('expected exactly one completed bundle for this build timestamp')
    tarpath = candidates[0]
    stem = tarpath.name.removesuffix('.tar.gz')
    zipath = tarpath.with_name(stem + '.zip')
    members, data = {}, {}
    with tarfile.open(tarpath, 'r|gz') as archive:
        for entry in archive:
            if not entry.isfile():
                continue
            if not entry.name.startswith(stem + '/'):
                raise ValueError('unexpected archive root')
            name = entry.name[len(stem) + 1:]
            if name in members:
                raise ValueError('duplicate bundle member: ' + name)
            stream = archive.extractfile(entry)
            if name in ('SHA256SUMS', 'files/SHA256SUMS', 'files/VERSION', 'files/boot.json'):
                content = stream.read()
                data[name] = content
                members[name] = hashlib.sha256(content).hexdigest()
            else:
                members[name] = digest(stream)
    listed = {}
    sums = 'files/SHA256SUMS' if 'files/SHA256SUMS' in data else 'SHA256SUMS'
    for line in data[sums].decode().splitlines():
        checksum, name = line.split(None, 1)
        listed[name] = checksum
    expected_members = {name: checksum for name, checksum in members.items() if name != sums}
    if listed != expected_members:
        raise ValueError('bundle SHA256SUMS mismatch')
    for name, path in [('files/boot.img', TOP / 'work/boot-linux-slotb-bundle-mainline.img'),
                       ('files/android-bootchain.sh', TOP / 'tools/android-bootchain.sh'),
                       ('OpenWrt-Installer.py', TOP / 'openwrt/bundle/flash.py'),
                       ('files/openwrt.ext4.gz', TOP / 'out/openwrt' / f'e5-openwrt-{info["openwrt_version"]}-generic.ext4.gz')]:
        if members[name] != file_digest(path):
            raise ValueError('bundle uses a different build output: ' + name)
    boot = json.loads(data['files/boot.json'])
    if boot['overlay_files'] or boot['sha256'] != members['files/boot.img']:
        raise ValueError('boot image contains an overlay or mismatches its manifest')
    version = data['files/VERSION'].decode()
    if info['build_started_at'] not in version or info['kernel_release'] not in version:
        raise ValueError('bundle version/time mismatch')
    with zipfile.ZipFile(zipath) as archive:
        if archive.testzip() is not None:
            raise ValueError('ZIP CRC check failed')
        prefix = '' if 'module.prop' in archive.namelist() else stem + '/'
        if set(archive.namelist()) != {prefix + name for name in members}:
            raise ValueError('ZIP and tar file lists differ')
        for name, checksum in members.items():
            with archive.open(prefix + name) as stream:
                if digest(stream) != checksum:
                    raise ValueError('ZIP differs from tar: ' + name)
    modules = list((TOP / 'out/magisk').glob(f'e5-linux-switch-*-{info["timestamp"]}.zip'))
    if len(modules) != 1:
        raise ValueError('expected one completed Magisk module for the build timestamp')
    module_path = modules[0]
    with zipfile.ZipFile(module_path) as module:
        expected = {p.name: p.read_bytes() for p in (TOP / 'magisk/e5-linux-switch').iterdir() if p.name != 'bootctl.c'}
        expected['README.md'] = (TOP / 'magisk/README.md').read_bytes()
        expected['sd-registry.sh'] = (TOP / 'rootfs/overlay/opt/e5/e5-sd-registry').read_bytes()
        expected['bootchain.sh'] = (TOP / 'tools/android-bootchain.sh').read_bytes()
        if set(module.namelist()) != set(expected) | {'e5-bootctl'} or module.testzip() is not None:
            raise ValueError('Magisk module member or CRC mismatch')
        for name, content in expected.items():
            if module.read(name) != content:
                raise ValueError('Magisk module source mismatch: ' + name)
        helper = module.read('e5-bootctl')
        if helper[:5] != b'\x7fELF\x02' or struct.unpack_from('<H', helper, 18)[0] != 183:
            raise ValueError('Magisk boot control helper is not arm64 ELF')
    info['assets'] = {}
    for path in (tarpath, zipath, module_path):
        checksum = file_digest(path)
        info['assets'][path.name] = {'sha256': checksum, 'bytes': path.stat().st_size}
        destination = RELEASE / path.name
        os.link(path, destination)
    (RELEASE / 'SHA256SUMS').write_text(''.join(f'{item["sha256"]}  {name}\n' for name, item in info['assets'].items()))
    (RELEASE / 'build.json').write_text(json.dumps(info, indent=2) + '\n')
    refs = '\n'.join(f'- {name}: `{item["repository"]}@{item["revision"]}`' for name, item in info['sources'].items())
    (RELEASE / 'release-notes.md').write_text(
        f'编译时间（UTC+8）：**{info["build_started_at"]}**\n\n'
        f'OpenWrt {info["openwrt_version"]} · 内核 `{info["kernel_release"]}` · '
        f'信息屏 {info["infoscreen_version"]} · 电话插件 {info["phone_version"]}\n\n'
        '完整固件 ZIP 可在 Android Magisk 内安装到 TF 卡（清空整卡），'
        '也可解压后运行 `OpenWrt-Installer.exe` 或 `launchers/start-installer.sh`。'
        '详细使用指南在包内顶层 `START-HERE.md`，已安装系统用更新入口保留设置。\n\n'
        '另附的小型 e5-linux-switch Magisk ZIP 仅用于手动切回已安装的 Linux，不负责首次部署。\n\n'
        '镜像不含设备固件和 Android vendor 运行库；安装器从目标设备提取。'
        'CI 已验证文件和模块一致性，硬件实测仍需在 E5 上进行。\n\n'
        f'源码版本：\n\n{refs}\n\n[构建记录]({info.get("run_url")})\n')
    outputs({'bundle_name': stem, 'release_title': 'E5 OpenWrt ' + info['build_started_at']})
    print('Verified release:', stem)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'verify'])
    args = parser.parse_args()
    try:
        (prepare if args.command == 'prepare' else verify)()
    except (ValueError, KeyError) as error:
        parser.exit(1, 'Release check: ' + str(error) + '\n')
