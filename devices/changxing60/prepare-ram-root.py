#!/usr/bin/env python3
"""Build a P720S20 RAM trial from the registered clean base.

Without --device-files this is display-only. A verified recipient capture
enables the shared hardware services with isolated NV in RAM. Both modes keep
physical storage read-only and retain the original Android fallback.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import tarfile

TOP = Path(__file__).resolve().parents[2]
PROFILE = 'changxing60'
DISABLED = {
    'e5-boot-ok', 'fstab', 'e5-apn-auto', 'e5-vendor', 'e5-sipc-wwan',
    'ModemManager', 'e5-network-recovery', 'e5-audio', 'e5-pulseaudio',
    'e5-call-audio', 'e5-bt', 'e5-charge-mode', 'e5-charge', 'e5-battery-guard',
    't551m-usb', 'e5-hw', 'e5-cpu', 'unisoc-cpu-cores', 'unisoc-cpu-idle',
    'modemmanager', 'e5-modemd', 'e5-hfp', 'e5-usb-watch',
    'unisoc-battery', 'e5-sms-notify',
}


def full_network_defaults():
    """Use normal addressing/network/APN/IPv6/firewall with a lab PC tag.

    The original tiny probe pool is for the development PC only. A full trial
    needs normal hotspot leases and LAN routing, including the shared /64
    extension. Suppress IPv4 router/DNS options only for this USB host's tag.
    """
    source = (TOP/'openwrt/overlay/etc/uci-defaults/90-e5').read_text()
    # Fresh RAM roots follow the same no-extra-EPS-cycle policy as releases.
    source = source.replace("set network.wan.init_epsbearer='default'",
                            "set network.wan.init_epsbearer='keep'")
    source = source.replace("hostname='E5'", "hostname='Changxing-60'")
    source = source.replace('02:50:00:00:e5:02', '02:50:00:00:60:02')
    anchor = "set dhcp.usb_host.tag='usbhost'\n"
    if source.count(anchor) != 1:
        raise ValueError('Shared first-boot USB reservation changed')
    source = source.replace(anchor, anchor + "set dhcp.usb_host.broadcast='1'\n"
        "set dhcp.usbhost=tag\nadd_list dhcp.usbhost.dhcp_option='3'\n"
        "add_list dhcp.usbhost.dhcp_option='6'\n", 1)
    # The normal release's 96-e5-usb-ipv4 migration intentionally removes the
    # old usbhost gateway suppression. This lab-only PC policy is separate.
    return source.replace("dhcp.usb_host.tag='usbhost'", "dhcp.usb_host.tag='cx60probe'").replace(
        'dhcp.usbhost', 'dhcp.cx60probe')


def configure(root, kernel, backup, device_files=None, refresh_modules=False, voltage_test=0):
    root, kernel, backup = map(Path, (root, kernel, backup))
    if voltage_test not in (0, 3125) or voltage_test and device_files is None:
        raise ValueError('Only zero or the reviewed one-step full-RAM voltage trial is allowed')
    if os.name == 'nt' or root.resolve() == Path('/'):
        raise ValueError('Use an offline Linux root')
    if (root / 'etc/e5/device-profile').read_text().strip() != PROFILE:
        raise ValueError('Wrong RAM root profile')
    board = runpy.run_path(str(Path(__file__).with_name('stage.py')))
    if device_files is not None:
        board['stage'](root)
    else:
        board['stage_screen'](root)
    release = (kernel / 'kernel.release').read_text().strip()
    if '-changxing60-' not in release:
        raise ValueError('Wrong kernel profile')
    manifest = json.loads((backup / 'manifest.json').read_text())
    if (manifest['profile'], manifest['board']) != (PROFILE, 'P720S20'):
        raise ValueError('Wrong stock capture')
    name = 'reference/vendor/firmware/axs_firmware_easyquick.bin'
    firmware = (backup / name).read_bytes()
    if hashlib.sha256(firmware).hexdigest() != manifest['files'][name]['sha256']:
        raise ValueError('Touch firmware differs from stock capture')
    if device_files is None and any((root / 'opt/e5/android').iterdir()):
        raise ValueError('UI trial must not contain Android vendor files')
    if device_files is not None:
        device_files = Path(device_files)
        captured = json.loads((device_files / 'manifest.json').read_text())
        archive = device_files / 'device-files.tar'
        if (captured['profile'], captured['android_slot']) != (PROFILE, manifest['android_slot']):
            raise ValueError('Vendor runtime belongs to another model/slot')
        if hashlib.sha256(archive.read_bytes()).hexdigest() != captured['archive_sha256']:
            raise ValueError('Own vendor runtime archive changed')
        store = root / 'opt/e5/nv'
        if store.is_symlink() or store.exists() and any(store.iterdir()):
            raise ValueError('Never reuse stored NV in a RAM trial root')
        with tarfile.open(archive) as stream:
            stream.extractall(root, filter='tar')
        board['stage_audio'](root)

    def put(name, data, mode=0o644):
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink():
            target.unlink()
        target.write_bytes(data if isinstance(data, bytes) else data.encode())
        target.chmod(mode)

    disabled = DISABLED if device_files is None else {'e5-boot-ok', 'fstab', 'e5-charge-mode'}
    for link in (root / 'etc/rc.d').iterdir():
        if link.name[3:] in disabled:
            if not link.is_symlink():
                raise ValueError('Unexpected non-link startup entry: ' + str(link))
            link.unlink()
    # preinit in the sanitized base may still attempt its historical disk root.
    # This trial already has a complete writable tmpfs root; do not import it.
    for entry in (root / 'lib/preinit').glob('*e5*'):
        if 'debian_root' in entry.name:
            entry.unlink()
    put('etc/config/fstab', "config global\n option anon_mount '0'\n option auto_mount '0'\n option auto_swap '0'\n")
    # Match the normal shared handoff: netifd owns an empty bridge; its existing
    # hotplug attaches usb0 without taking the negotiated NCM link down/up.
    put('etc/config/network', "config interface 'loopback'\n option device 'lo'\n option proto 'static'\n option ipaddr '127.0.0.1'\n option netmask '255.0.0.0'\n\nconfig device\n option name 'br-lan'\n option type 'bridge'\n option bridge_empty '1'\n option macaddr '02:50:00:00:60:01'\n\nconfig interface 'lan'\n option device 'br-lan'\n option proto 'static'\n option ipaddr '192.168.92.1'\n option netmask '255.255.255.0'\n")
    put('etc/config/dhcp', "config dnsmasq\n option authoritative '1'\n\nconfig dhcp 'lan'\n option interface 'lan'\n option start '2'\n option limit '1'\n option leasetime '10m'\n list dhcp_option '3'\n list dhcp_option '6'\n\nconfig host 'probe_host'\n option mac '02:50:00:00:60:02'\n option ip '192.168.92.2'\n option broadcast '1'\n")
    put('etc/e5/ram-probe', PROFILE + '\n')
    # Always write zero as well: finishing the owned staging must not retain
    # the previous positive-offset experiment in the final test image.
    put('etc/e5-cpu-voltage.json', json.dumps({'version': 1, 'offsets': [voltage_test] * 3}) + '\n', 0o600)
    armed = root / 'etc/e5-cpu-voltage-armed.json'
    if armed.is_symlink():
        raise ValueError('Unexpected voltage trial marker symlink')
    if armed.exists():
        armed.unlink()
    put('etc/e5/configured.network', '')
    put('etc/e5/image-version', PROFILE + '-ram-ui1\n')
    put('lib/firmware/axs15205/easyquick.bin', firmware)
    if refresh_modules:
        owned = root.resolve()
        if owned.parts[-3:] != ('e5-release', 'changxing60', 'ram-ui'):
            raise ValueError('Module refresh is restricted to the owned RAM staging')
        target = root / 'lib/modules' / release
        if target.is_symlink() or target.resolve().parent != (root / 'lib/modules').resolve():
            raise ValueError('Unsafe staged module path')
        if target.exists():
            if not (target / 'container-support.json').is_file():
                raise ValueError('Unowned staged module cohort')
            shutil.rmtree(target)
    runpy.run_path(str(TOP / 'upstream/stage-root-modules.py'))['stage'](kernel, root)
    wanted = ['panfrost.ko', 'ump96xx_fuel_gauge.ko', 'bq2560x-charger.ko', 'axs15205.ko']
    if device_files is not None:
        wanted = (TOP / 'upstream/module-order.txt').read_text().split()
        wanted = [('axs15205.ko' if m == 'tlsc6x.ko' else 'bq2560x-charger.ko'
                   if m == 'aw32257_charger.ko' else m) for m in wanted]
    order = runpy.run_path(str(TOP / 'devices/common/bringup-probe.py'))['module_order'](
        kernel / 'modules', wanted, release)
    put('etc/e5/ram-ui-module-order', '\n'.join(order) + '\n')
    module_script = '''#!/bin/sh
[ "$(cat /etc/e5/ram-probe)" = changxing60 ] || exit 1
while read -r module; do
 name=$(printf '%s' "${module%.ko}" | tr - _)
 [ -d "/sys/module/$name" ] || insmod "/lib/modules/$(uname -r)/$module" || exit 1
done < /etc/e5/ram-ui-module-order
'''
    if device_files is not None:
        module_script = module_script.replace('while read -r module;',
            '/opt/e5/t551m-nv-prepare || exit 1\nwhile read -r module;')
    put('usr/libexec/e5-ram-ui-modules', module_script, 0o755)
    put('etc/init.d/e5-ram-ui-modules', '#!/bin/sh /etc/rc.common\nSTART=07\nstart() { /usr/libexec/e5-ram-ui-modules; }\n', 0o755)
    put('etc/init.d/e5-ram-probe', '#!/bin/sh /etc/rc.common\nSTART=08\nstart() { logger -t cx60-ram "Bounded UI trial; modem/audio not enabled; Android fallback retained"; }\n', 0o755)
    module_link = root / 'etc/rc.d/S07e5-ram-ui-modules'
    if module_link.is_symlink():
        module_link.unlink()
    module_link.symlink_to('../init.d/e5-ram-ui-modules')
    # This native observer also owns the screen HTTP/WebSocket event bridge.
    # It does not boot the DSP without e5-audio.ready or control modem calls.
    for name in ('S93e5-voice-audio', 'S98e5-voice-audio'):
        path = root / 'etc/rc.d' / name
        if path.is_symlink():
            path.unlink()
    (root / 'etc/rc.d/S93e5-voice-audio').symlink_to('../init.d/e5-voice-audio')
    if device_files is not None:
        # These links were intentionally absent in UI-only trials. Restore the
        # normal shared service ordering after the complete own firmware import.
        for name, priority in (('e5-vendor', '09'), ('e5-hw', '11'), ('e5-cpu', '13'),
                ('modemmanager', '70'), ('e5-sipc-wwan', '23'), ('e5-modemd', '22'),
                ('e5-network-recovery', '96'), ('e5-bt', '99'), ('t551m-usb', '25'),
                ('e5-usb-watch', '98'), ('e5-audio', '97'), ('unisoc-battery', '86'),
                ('e5-sms-notify', '80')):
            link = root / ('etc/rc.d/S' + priority + name)
            if not link.is_symlink():
                link.symlink_to('../init.d/' + name)
        # The native UI observer also handles calls; HFP is a separate optional
        # service. Its normal enable flag remains the user's choice.
        put('etc/e5/image-version', PROFILE + '-ram-full1\n')
        put('etc/e5/install.conf', "E5_WIFI_SSID='Changxing60-OpenWrt'\nE5_WIFI_KEY='cx60test2026'\n")
        # Run the same normal first-boot setup as the release, not the one-host
        # diagnostic DHCP pool. Keep gateway suppression scoped to the USB PC.
        (root/'etc/e5/configured.network').unlink()
        put('etc/uci-defaults/90-e5', full_network_defaults(), 0o755)
        put('etc/config/dhcp', "config dnsmasq\n option authoritative '1'\n\n"
            "config dhcp 'lan'\n option interface 'lan'\n")
        put('etc/config/network', (root/'etc/config/network').read_text() +
            "\nconfig interface 'wan'\n option proto 'modemmanager'\n option device 'unisoc-sipc'\n option apn_auto '1'\n option iptype 'ipv4v6'\n option disable_modem '0'\n option init_epsbearer 'keep'\n option sourcefilter '0'\n")
        put('etc/init.d/e5-ram-probe', '#!/bin/sh /etc/rc.common\nSTART=08\nstart() { logger -t cx60-ram "Full RAM trial; factory storage read-only; Android fallback retained"; }\n', 0o755)
    password = subprocess.check_output(['openssl', 'passwd', '-6', 'root'], text=True).strip()
    fields = [line.split(':') for line in (root / 'etc/shadow').read_text().splitlines()]
    for line in fields:
        if line[0] == 'root':
            line[1] = password
    put('etc/shadow', '\n'.join(':'.join(line) for line in fields) + '\n', 0o600)
    subprocess.run(['aarch64-linux-gnu-gcc', '-static', '-Os', '-s', '-Wall', '-Wextra', '-Werror',
                    str(TOP / 'devices/common/probe-watchdog.c'), '-o', str(root / 'usr/libexec/e5-ram-watchdog')], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--finish-existing', action='store_true',
                        help='Finish this same owned UI staging after reviewing a failed/prepared run')
    parser.add_argument('--device-files', type=Path, help='Verified own vendor capture enables full RAM hardware services')
    parser.add_argument('--refresh-modules', action='store_true', help='Replace only the owned RAM staging module cohort after a kernel rebuild')
    parser.add_argument('--voltage-test', type=int, choices=(0, 3125), default=0,
                        help='Temporary positive one-step DVFS ABI check, in RAM only; default restores zero')
    for name in ('base', 'defaults', 'root', 'kernel', 'backup', 'out'):
        parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError('Keep the previous diagnostic artifact; select a new output')
    if not args.finish_existing:
        runpy.run_path(str(TOP / 'devices/m8/prepare-root.py'))['prepare'](
            args.base, args.root, args.defaults, profile=PROFILE)
    configure(args.root, args.kernel, args.backup, args.device_files, args.refresh_modules, args.voltage_test)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(args.out, 'w:gz', compresslevel=1) as archive:
        for path in sorted(args.root.iterdir()):
            archive.add(path, arcname=path.name)
    args.out.with_suffix('.sha256').write_text(hashlib.sha256(args.out.read_bytes()).hexdigest() + '  ram-root.tar.gz\n')
    print(('Full' if args.device_files else 'UI-only') + ' RAM root ready:', args.out, args.out.stat().st_size)


if __name__ == '__main__':
    main()
