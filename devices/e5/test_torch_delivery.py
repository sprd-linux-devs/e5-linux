#!/usr/bin/env python3
"""Generate/apply a real diff and migrate a full image, preserving user data."""
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import zipfile

TOP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(TOP / 'installer'))
from backend.ota_engine import Engine, Patch, canonical, descriptor
from backend.ota_package import compare

stage = runpy.run_path(str(TOP / 'devices/e5/torch-screen.py'))['stage']
BOOT = b'unchanged boot fixture'


def put(root, name, data):
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    target.chmod(0o644)


def release(root, version):
    entries = {p.relative_to(root).as_posix():descriptor(p) for p in root.rglob('*')}
    return SimpleNamespace(family='e5', source=str(root),
        meta=dict(profile='e5', image_version=version, kernel_release='6.18.54-e5-test', openwrt='25.12.5'),
        packages={}, entries=entries, boot_name='boot.img',
        boot_digest=hashlib.sha256(BOOT).hexdigest(), open=lambda name:io.BytesIO(BOOT))


with tempfile.TemporaryDirectory(prefix='e5-torch-delivery-') as temp:
    root = Path(temp)
    old, new, live = [root / name for name in ('old', 'new', 'live')]
    for target in (old, new):
        (target / 'etc/modules.d').mkdir(parents=True)
        put(target, 'etc/e5/device-profile', b'e5\n')
        put(target, 'etc/config/wireless', b'user Wi-Fi password')
        put(target, 'etc/e5-infoscreen/wallpapers/desktop.png', b'user wallpaper')
        put(target, 'etc/e5-infoscreen/plugins/own/main.js', b'user application')
    stage(new)
    stage(new)  # Repeated preparation must keep one canonical, working link.
    service = 'etc/init.d/e5-infoscreen'
    put(old, service, b'old service')
    put(new, service, (TOP / 'devices/common/infoscreen/base/service').read_bytes())
    # Execute actual screen startup with its UI disabled. Preparation must
    # run once, and a failed optional loader must not make startup fatal.
    service_text = (TOP / 'devices/common/infoscreen/base/service').read_text()
    start = service_text.index('start_service() {')
    startup = service_text[start:service_text.index('\n}\n', start) + 3]
    helper = root / 'torch-loader'
    log = root / 'loader.log'
    helper.write_text('#!/bin/sh\nprintf called >> "$TORCH_TEST_LOG"\nexit "${TORCH_TEST_FAIL:-0}"\n')
    helper.chmod(0o755)
    startup = startup.replace('/usr/libexec/e5-torch-start', str(helper))
    startup = startup.replace('/usr/libexec/t551m-screen-power set 0', ':')
    prelude = 'config_load() { :; }; config_get_bool() { enabled=0; }; logger() { :; };\n'
    for fail in ('0', '1'):
        env = {**os.environ, 'TORCH_TEST_LOG':str(log), 'TORCH_TEST_FAIL':fail}
        subprocess.run(['sh', '-ec', prelude + startup + '\nstart_service'], env=env, check=True)
    assert log.read_text() == 'calledcalled'
    put(new, 'lib/modules/6.18.54-e5-test/e5-aw3641-torch.ko', b'torch module fixture')
    put(new, 'etc/config/wireless', b'default password that must not overwrite user data')
    put(old, 'etc/e5/release.json', json.dumps(release(old, 'e5-r1').meta).encode())
    put(new, 'etc/e5/release.json', json.dumps(release(new, 'e5-r2').meta).encode())
    # Runtime bootstrap is independent of app ownership and uses no real device
    # in this small fixture. Comparison and the transaction engine are real.
    runtime = importlib.import_module(compare.__module__.rsplit('.', 1)[0] + '.ota_runtime')
    with patch.object(runtime, 'build', return_value=({}, None, {})):
        plan, extra = compare(release(old, 'e5-r1'), release(new, 'e5-r2'))
    assert plan['can_export'], plan['blockers']
    manifest = plan['manifest']
    names = {op['path'] for op in manifest['operations']}
    assert service in names and 'usr/libexec/e5-torch-start' in names
    assert 'lib/modules/6.18.54-e5-test/e5-aw3641-torch.ko' in names
    app = 'usr/share/e5-infoscreen/builtin-apps/torch/'
    assert all(app + p.name in names for p in (TOP / 'devices/e5/infoscreen-torch').iterdir() if p.is_file())
    link = 'usr/share/e5-infoscreen/www/plugins/torch'
    assert link in names
    assert not any(name.startswith('etc/e5-infoscreen/plugins/torch/') for name in names)

    def apply_plan(plan, source, destination):
        archive = root / ('patch-' + plan['manifest']['target_version'] + '.ota')
        with zipfile.ZipFile(archive, 'w') as stream:
            stream.writestr('manifest.json', canonical(plan['manifest']))
            added = set()
            for op in plan['manifest']['operations']:
                desc = op['after']
                if desc and desc['kind'] == 'file' and desc['sha256'] not in added:
                    stream.write(source / op['path'], 'blobs/' + desc['sha256'])
                    added.add(desc['sha256'])
        with Patch(archive) as delta:
            assert Engine(destination).apply(delta)['status'] == 'complete'

    shutil.copytree(old, live, symlinks=True)
    apply_plan(plan, new, live)
    assert (live / link / 'torch.js').read_bytes() == (new / app / 'torch.js').read_bytes()
    assert (live / 'usr/libexec/e5-torch-start').is_file()
    assert (live / 'etc/config/wireless').read_bytes() == b'user Wi-Fi password'
    assert (live / 'etc/e5-infoscreen/wallpapers/desktop.png').read_bytes() == b'user wallpaper'
    assert (live / 'etc/e5-infoscreen/plugins/own/main.js').read_bytes() == b'user application'

    # A subsequent diff must update code again, not preserve it as /etc data.
    third = root / 'third'
    shutil.copytree(new, third, symlinks=True)
    js = third / app / 'torch.js'
    js.write_bytes(js.read_bytes() + b'\n/* next release fixture */\n')
    put(third, 'etc/e5/release.json', json.dumps(release(third, 'e5-r3').meta).encode())
    with patch.object(runtime, 'build', return_value=({}, None, {})):
        again, _ = compare(release(new, 'e5-r2'), release(third, 'e5-r3'))
    assert again['can_export'], again['blockers']
    apply_plan(again, third, live)
    assert (live / link / 'torch.js').read_bytes() == js.read_bytes()

    # Execute the actual ordinary-image configuration migration.
    text = (TOP / 'openwrt/device-install-image.sh').read_text()
    start = text.index('keep_config() {')
    function = text[start:text.index('\n}\n', start) + 3]
    function = function.replace('/tmp/e5-img.', str(root / 'migration.'))
    put(old, 'etc/e5-infoscreen/plugins/torch/manifest.json', b'{"id":"torch"}')
    put(old, 'etc/e5-infoscreen/plugins/torch/torch.js', b'stale development copy')
    subprocess.run(['sh', '-ec', function + '\nkeep_config "$1" "$2"',
                    'test', str(old), str(third)], check=True)
    # Plugin relinking must not point the new image back at that stale copy.
    plugin = (TOP / 'devices/common/infoscreen/base/plugin').read_text()
    plugin = plugin.replace('WWW=/usr/share/e5-infoscreen/www/plugins', 'WWW=' + str(third / 'usr/share/e5-infoscreen/www/plugins'))
    plugin = plugin.replace('USER_DIR=/etc/e5-infoscreen/plugins', 'USER_DIR=' + str(third / 'etc/e5-infoscreen/plugins'))
    subprocess.run(['sh', '-ec', plugin, 'plugin', 'link'], check=True)
    assert (third / link / 'torch.js').read_bytes() == js.read_bytes()
    assert (third / 'etc/config/wireless').read_bytes() == b'user Wi-Fi password'

    for profile in ('t551m', 'm8', 't512n', 'yuanhang41s', 'k1', 'lym10k', 'changxing60', 'y60'):
        other = root / profile
        put(other, 'etc/e5/device-profile', (profile + '\n').encode())
        stage(other)
        assert not (other / 'usr/share/e5-infoscreen/builtin-apps/torch').exists()

print('PASS: fresh/diff/second diff/full-image migration, driver/startup delivery, stale app isolation, user data and profile boundaries')
