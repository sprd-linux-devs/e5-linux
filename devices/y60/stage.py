#!/usr/bin/env python3
"""Y60 userspace: shared features with this unit's analog audio calibration."""
from pathlib import Path
import json
import re
import runpy
import xml.etree.ElementTree as ET


def ucm_controls(values):
    return ''.join('\t\tcset "name=\'' + key + "' " + value + '"\n'
                   for key, value in values)


def device_sequence(text, device, action, values):
    """Replace one device sequence; never turn on a speaker in the verb itself."""
    start = text.index('SectionDevice."' + device + '" {')
    end = text.find('\nSectionDevice.', start + 1)
    if end < 0:
        end = len(text)
    block = text[start:end]
    pattern = r'(?m)(\t' + action + r'Sequence \[\n).*?(\n?\t\])'
    changed, count = re.subn(pattern, lambda m: m[1] + ucm_controls(values) + '\t]',
                             block, count=1, flags=re.S)
    if count != 1:
        raise ValueError('Missing Y60 UCM ' + device + '/' + action)
    return text[:start] + changed + text[end:]


def capture_gain(codec, scene):
    # Current recipient tables use the same analog main-mic gain for all four
    # call bandwidths. Do not silently pick one if a future firmware differs.
    values = []
    for mode in ('NB1', 'WB1', 'SWB1', 'FB1'):
        node = codec.find('Audio/' + scene + '/' + mode + '/adc1_capture_volume')
        value = int(node.attrib['val'], 0)
        if not 0 <= value <= 7:
            raise ValueError('Invalid Y60 main-mic gain')
        values.append(value)
    if len(set(values)) != 1:
        raise ValueError('Y60 per-band main-mic gains require separate routing')
    return str(values[0])


def audio_startup(text):
    # In Y60's factory route table SYS_IIS0 belongs to Bluetooth SCO, not to
    # the internal codec playback/capture route. Do not let that unrelated
    # pinctrl control (or its card index) prevent all analog audio startup.
    # The common call backend still applies SYS_IIS0 when selecting SCO.
    old = '    amixer -q -c 0 cset name=SYS_IIS0 vbc_iis3 || return 1\n'
    new = '    # Y60 analog codec routes do not require the Bluetooth SYS_IIS0 pinmux.\n'
    if new in text:
        return text
    if text.count(old) != 1:
        raise ValueError('Unexpected shared audio startup pinmux')
    return text.replace(old, new, 1)


def stage(root):
    root = Path(root)
    runpy.run_path(str(Path(__file__).resolve().parents[1] / 'm8/stage.py'))['stage'](
        root, profile='y60')
    (root / 'etc/e5/receiver-wiring').write_text('hpl\n')
    startup = root / 'opt/e5/e5-audio-dsp'
    startup.write_text(audio_startup(startup.read_text()))
    collector = root / 'usr/libexec/y60-collect-audio'
    collector.write_bytes(Path(__file__).with_name('collect-audio.sh').read_bytes().replace(b'\r\n', b'\n'))
    collector.chmod(0o755)
    target = root / 'usr/lib/e5/y60_audio.py'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(Path(__file__).read_bytes().replace(b'\r\n', b'\n'))
    service = root / 'etc/init.d/e5-y60-audio'
    service.write_text('''#!/bin/sh /etc/rc.common
START=18
start() {
    /usr/bin/python3 -c 'from sys import path; path.insert(0, "/usr/lib/e5"); from y60_audio import stage_audio; stage_audio("/")'
}
''')
    service.chmod(0o755)
    runpy.run_path(str(Path(__file__).resolve().parents[1] / 'e5/stage.py'))['link'](
        root, 'S18e5-y60-audio', 'e5-y60-audio')


def stage_audio(root):
    """Apply recipient XML after installation has imported its public firmware.

    No mixer I/O and no donor calibration. The common call service already
    imports the unit's codec.xml, AS/CVS and HPL receiver route.
    """
    root = Path(root)
    if (root / 'etc/e5/device-profile').read_text().strip() != 'y60':
        raise ValueError('Y60 audio used for another device')
    firmware = root / 'lib/firmware'
    route = ET.parse(firmware / 'y60-audio_route.xml').getroot()
    def controls(path):
        node = route.find(path)
        if node is None:
            raise ValueError('Missing Y60 audio route: ' + path)
        values = [(n.attrib['name'], n.attrib['val']) for n in node.findall('ctl')]
        if not values or any(any(c in k+v for c in "'\"\\\r\n") for k,v in values):
            raise ValueError('Invalid Y60 audio controls: ' + path)
        return values
    if dict(controls('devices/handset/on')).get('HPL EAR Sel') != 'EAR':
        raise ValueError('Y60 receiver is no longer the verified HPL/EAR wiring')
    speaker = controls('devices/speaker/on')
    if dict(speaker).get('Speaker Function') != '1' or dict(speaker).get('AOL EAR Sel') != 'AOL':
        raise ValueError('Unexpected Y60 speaker endpoint')
    routes_path = root / 'usr/share/e5/voice-routes.json'
    routes = json.loads(routes_path.read_text())
    routes['ROUTES'].update(dict(controls('devices/main_mic/on')))
    routes['RECEIVER'].update(dict(controls('devices/handset/on')))
    routes['SPEAKER'].update(dict(speaker))
    routes['CODEC_IIS'].update(dict(controls('vbc_iis_mux/only_codec_p/on')))
    routes['CODEC_IIS'].update(dict(controls('vbc_iis_mux/only_codec_c/on')))
    pga = ET.parse(firmware / 'y60-audio_pga.xml').getroot()
    maximum = int(pga.find('Music/Handsfree/Playback/VBC_DAC0_DG/volume0').attrib['val'], 0)
    if not 1 <= maximum <= 127:
        raise ValueError('Invalid Y60 media gain')
    codec_root = ET.parse(firmware / 'codec.xml').getroot()
    routes['RECEIVER']['ADC_1 Gain ADC_1 Capture Volume'] = capture_gain(codec_root, 'Handset')
    routes['SPEAKER']['ADC_1 Gain ADC_1 Capture Volume'] = capture_gain(codec_root, 'Handsfree')
    codec = codec_root.find('Music/Handsfree/Playback')
    ao = int(codec.find('ao_playback_volume/volume6').attrib['val'], 0)
    dac = int(codec.find('dacs_playback_volume/volume6').attrib['val'], 0)
    if not 0 <= ao <= 7 or not 0 <= dac <= 3:
        raise ValueError('Invalid Y60 codec gain')
    record = codec_root.find('Music/Handsfree/Record/adc1_capture_volume')
    record_analog = int(record.attrib['val'], 0)
    record_digital = int(pga.find('Music/Handsfree/Record/VBC_ADC0_DG/volume0').attrib['val'], 0)
    if not 0 <= record_analog <= 7 or not 0 <= record_digital <= 127:
        raise ValueError('Invalid Y60 recording gain')
    # Modify the common media template without touching voice/BT ownership.
    ucm = root / 'usr/share/alsa/ucm2/sprdphone-sc273/HiFi.conf'
    text = ucm.read_text()
    marker = '# Y60 factory analog playback'
    mux = controls('vbc_iis_mux/only_codec_p/on')
    lines = '\t\t' + marker + '\n' + ucm_controls(mux)
    if marker in text:
        # Migrate the older block which also enabled the speaker globally.
        text, count = re.subn(r'(?m)^\t\t' + re.escape(marker) + r'\n(?:\t\tcset [^\n]*\n)*',
                              lambda _: lines, text, count=1)
        if count != 1:
            raise ValueError('Invalid Y60 UCM calibration block')
    else:
        anchor = '\tEnableSequence [\n'
        if anchor not in text:
            raise ValueError('Missing UCM enable sequence')
        text = text.replace(anchor, anchor + lines, 1)
    text = device_sequence(text, 'Speaker', 'Enable',
        [('Earpiece Function', '0'), ('Speaker Mute', '0')] + speaker + [('Speaker1 Function', '0')])
    text = device_sequence(text, 'Speaker', 'Disable', controls('devices/speaker/off'))
    text = device_sequence(text, 'Mic', 'Enable',
        [('ADC_1 Gain ADC_1 Capture Volume', str(record_analog))] + controls('devices/main_mic/on'))
    text = device_sequence(text, 'Mic', 'Disable', controls('devices/main_mic/off'))
    # Replace the final gain entries too: later csets must not undo this unit.
    text = re.sub(r"(name='VBC DAC0 DG Set' )\d+,\d+", rf'\g<1>{maximum},{maximum}', text)
    text = re.sub(r"(name='AO Gain AO Playback Volume' )\d+", rf'\g<1>{ao}', text)
    text = re.sub(r"(name='DAC Gain DAC Playback Volume' )\d+", rf'\g<1>{dac}', text)
    text = re.sub(r"(name='VBC ADC0 DG Set' )\d+,\d+",
                  rf'\g<1>{record_digital},{record_digital}', text)
    ucm.write_text(text)
    # Persist the maximum as data so repeat starts don't double-patch the script.
    (root / 'etc/e5/media-hardware-max').write_text(str(maximum) + '\n')
    volume = root / 'usr/libexec/e5-volume'
    text = volume.read_text()
    if 'HW_MAX=' not in text:
        text = text.replace('MAX=15\n', 'MAX=15\nHW_MAX=$(cat /etc/e5/media-hardware-max) || exit 1\n')
        # Clamp the lowest step for a board whose maximum is below the common 39.
        text = text.replace('echo $((39 - (MAX - $1) * 2))',
            '{ g=$((HW_MAX - (MAX - $1) * 2)); [ "$g" -ge 0 ] || g=0; echo "$g"; }')
        text = text.replace('&& g=39', '&& g=$HW_MAX')
        volume.write_text(text)
    routes_path.write_text(json.dumps(routes, separators=(',', ':')) + '\n')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    stage(parser.parse_args().root)
