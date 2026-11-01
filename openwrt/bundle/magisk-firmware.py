#!/usr/bin/env python3
"""Convert this Android's snapshots using Python inside the staged clean root."""
from pathlib import Path
import runpy
import sys


def settings(raw, default_ssid):
    import secrets
    import shlex
    import xml.etree.ElementTree as ET
    ssid, key = '', ''
    path = raw / 'android-hotspot.xml'
    if path.exists():
        data = path.read_bytes()
        if b'<!DOCTYPE' not in data and b'<!ENTITY' not in data:
            try:
                fields = {n.get('name'): n.text or '' for n in ET.fromstring(data).iter('string')}
                ssid = fields.get('WifiSsid', fields.get('SSID', '')).strip('"')
                key = fields.get('Passphrase', '')
            except ET.ParseError:
                pass
    if not 1 <= len(ssid.encode('utf-8')) <= 32 or not 8 <= len(key.encode('utf-8')) <= 63 or any(
            c in ssid + key for c in '\r\n\x00'):
        ssid = default_ssid
        key = ''.join(secrets.choice('abcdefghjkmnpqrstuvwxyz23456789') for _ in range(12))
    return ''.join(k + '=' + shlex.quote(v) + '\n' for k, v in (
        ('E5_APN', ''), ('E5_WIFI_SSID', ssid), ('E5_WIFI_KEY', key),
        ('E5_WIFI_CHANNEL', '149'), ('E5_DEFAULT_BOOT', 'linux')))


def convert(raw, out, tools, default_ssid, profile=''):
    raw, out, tools = Path(raw), Path(out), Path(tools)
    fw = out / 'lib/firmware'
    (fw / 'sprd').mkdir(parents=True)
    import shutil
    board=profile=='yuanhang41s'
    for p in raw.iterdir():
        if p.name in ('wcnmodem.bin', 'gnssmodem.bin', 'l_agdsp_a.img', 'aw87xxx_acf.bin', 'tsx_data', 'codec.xml') or (board and p.name in (
                'aw883xx_acf.bin','awinic_params.bin','sitronix_firmware_huaying.dump','audio_route.xml','audio_pga.xml')) or (
                p.name.startswith('wifi_board_config') and p.suffix == '.ini'):
            shutil.copyfile(p, fw / p.name)
    if profile == 'changxing60':
        for name in ('audio_config.xml','audio_route.xml','audio_pga.xml'):
            shutil.copyfile(raw/name, fw/('changxing60-'+name))
        (fw/'axs15205').mkdir()
        shutil.copyfile(raw/'axs_firmware_easyquick.bin', fw/'axs15205/easyquick.bin')
    if profile == 'y60':
        for name in ('audio_route.xml', 'audio_pga.xml'):
            shutil.copyfile(raw/name, fw/('y60-'+name))
        if not (fw/'aw87xxx_acf.bin').is_file() or not (fw/'codec.xml').is_file():
            raise ValueError('missing recipient Y60 amplifier/codec calibration')
    if not list(fw.glob('wifi_board_config*.ini')):
        raise ValueError('missing Wi-Fi board configuration')
    dsp = (raw / 'l_agdsp_a.img').read_bytes()
    if len(dsp) != 6291456 or not dsp.startswith(b'SharkL5_AUD'):
        raise ValueError('unexpected audio DSP image')
    bt = runpy.run_path(str(tools / 'sprd-bt-config.py'))
    octets = bytes(int(x, 16) for x in (raw / 'btmac.txt').read_text().strip().split(':'))
    if len(octets) != 6:
        raise ValueError('invalid Bluetooth address')
    for source, target, length, address in (
            ('bt_configure_pskey.ini' if board else 'bt_configure_pskey.xpe.ini', 'marlin3lite_pskey.bin', bt['PSKEY_LEN'], octets[::-1]),
            ('bt_configure_rf.ini' if board else 'bt_configure_rf.xpe.ini', 'marlin3lite_rf.bin', bt['RF_LEN'], None)):
        (fw / 'sprd' / target).write_bytes(bt['pack'](bt['parse'](raw / source), length, address))
    audio = runpy.run_path(str(tools / 'vbc-profile/vbc-profile.py'))
    for name in ('dsp_vbc', 'audio_structure', 'cvs'):
        tag, *_details, blob = audio['build'](raw / (name + '.xml'))
        if tag != name:
            raise ValueError('unexpected audio profile tag: ' + tag)
        (fw / name).write_bytes(blob)
    if board:
        for name in ('aw883xx_acf.bin','sitronix_firmware_huaying.dump'):
            if not (fw/name).stat().st_size:raise ValueError('missing 41S firmware: '+name)
        ucm,gain=runpy.run_path(str(tools/'yuanhang41s-audio-routes.py'))['generate'](
            raw/'audio_route.xml',raw/'audio_pga.xml',tools/'yuanhang41s-HiFi.base.conf')
        (fw/'yuanhang41s-HiFi.conf').write_text(ucm,encoding='utf-8',newline='\n')
        (fw/'yuanhang41s-media-max').write_text(str(gain)+'\n',encoding='utf-8',newline='\n')
        (fw/'sitronix').mkdir()
        (fw/'sitronix/st7123.bin').symlink_to('../sitronix_firmware_huaying.dump')
    for name in ('wcnmodem.bin', 'l_agdsp_a.img', 'audio_structure', 'dsp_vbc', 'cvs',
                 'sprd/marlin3lite_pskey.bin', 'sprd/marlin3lite_rf.bin'):
        if not (fw / name).stat().st_size:
            raise ValueError('empty firmware: ' + name)
    (out / 'install.conf').write_text(settings(raw, default_ssid), encoding='utf-8')


if __name__ == '__main__':
    convert(*sys.argv[1:6])
