#!/usr/bin/env python3
"""Recipient audio, installer identity and release isolation; no device access."""
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
TOP = HERE.parents[1]
STAGE = runpy.run_path(str(HERE / 'stage.py'))
AUDIO = STAGE['stage_audio']


class Audio(unittest.TestCase):
    def setUp(self):
        stock = os.environ.get('Y60_STOCK_FIRST')
        if not stock:
            self.skipTest('Y60_STOCK_FIRST not provided; real recipient XML required')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        def put(name, data):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data if isinstance(data, bytes) else data.encode())
        stock = Path(stock)
        self.put = put
        put('etc/e5/device-profile', 'y60\n')
        put('lib/firmware/y60-audio_route.xml', (stock/'odm_a/etc/audio_route.xml').read_bytes())
        put('lib/firmware/y60-audio_pga.xml', (stock/'odm_a/etc/audio_params/sprd/audio_pga.xml').read_bytes())
        put('lib/firmware/codec.xml', (stock/'odm_a/etc/audio_params/sprd/codec.xml').read_bytes())
        put('usr/share/alsa/ucm2/sprdphone-sc273/HiFi.conf',
            (TOP/'rootfs/overlay/usr/share/alsa/ucm2/sprdphone-sc273/HiFi.conf').read_bytes())
        put('usr/libexec/e5-volume', (TOP/'openwrt/overlay/usr/libexec/e5-volume').read_bytes())
        # Real manifest generator parses the shared voice constants, not a
        # handwritten fixture which might omit the native call daemon's keys.
        put('usr/share/e5/voice-routes.json',
            runpy.run_path(str(TOP/'devices/common/build-screen-native.py'))['route_manifest']())

    def test_factory_audio_and_repeat_start_are_idempotent(self):
        AUDIO(self.root)
        paths = ['usr/share/alsa/ucm2/sprdphone-sc273/HiFi.conf',
                 'usr/share/e5/voice-routes.json', 'usr/libexec/e5-volume']
        before = {n: (self.root/n).read_bytes() for n in paths}
        AUDIO(self.root)
        self.assertEqual(before, {n:(self.root/n).read_bytes() for n in paths})
        self.assertEqual((self.root/'etc/e5/media-hardware-max').read_text().strip(), '34')
        ucm = before[paths[0]].decode()
        self.assertIn("VBC DAC0 DG Set' 34,34", ucm)
        self.assertIn("AO Gain AO Playback Volume' 6", ucm)
        self.assertIn("VBC_IIS_TX0_WD_SEL' WD_24BIT", ucm)
        routes = json.loads(before[paths[1]])
        self.assertEqual(routes['RECEIVER']['HPL EAR Sel'], 'EAR')
        self.assertEqual(routes['SPEAKER']['AOL EAR Sel'], 'AOL')
        self.assertNotIn('VOICE_VOLUME', routes)  # uses recipient AS/CVS tables

    def test_main_mic_uses_recipient_call_and_record_gains(self):
        AUDIO(self.root)
        routes = json.loads((self.root/'usr/share/e5/voice-routes.json').read_text())
        control = 'ADC_1 Gain ADC_1 Capture Volume'
        self.assertEqual(routes['RECEIVER'][control], '7')
        self.assertEqual(routes['SPEAKER'][control], '6')
        ucm = (self.root/'usr/share/alsa/ucm2/sprdphone-sc273/HiFi.conf').read_text()
        self.assertIn("VBC ADC0 DG Set' 24,24", ucm)
        self.assertIn("ADC_1 Gain ADC_1 Capture Volume' 6", ucm)
        # Speaker routing belongs to the device, never the global verb.
        self.assertNotIn("Speaker Function' 1", ucm[:ucm.index('SectionDevice.')])
        speaker = ucm[ucm.index('SectionDevice."Speaker"'):ucm.index('SectionDevice."Earpiece"')]
        self.assertIn("DAC LRCLK Select' invert", speaker)
        self.assertIn("DAC LRCLK Select' normal", speaker)
        self.assertIn("AOL EAR Sel' EAR", speaker)
        self.assertIn("Speaker Mute' 0", speaker)

    def test_bad_capture_gain_never_half_updates_audio(self):
        path = self.root/'lib/firmware/codec.xml'
        import xml.etree.ElementTree as ET
        tree = ET.parse(path)
        tree.getroot().find('Music/Handsfree/Record/adc1_capture_volume').set('val', '0xff')
        tree.write(path)
        names = ('usr/share/alsa/ucm2/sprdphone-sc273/HiFi.conf',
                 'usr/share/e5/voice-routes.json', 'usr/libexec/e5-volume')
        before = {n:(self.root/n).read_bytes() for n in names}
        with self.assertRaisesRegex(ValueError, 'recording gain'):
            AUDIO(self.root)
        self.assertEqual(before, {n:(self.root/n).read_bytes() for n in names})
        self.assertFalse((self.root/'etc/e5/media-hardware-max').exists())

    @unittest.skipIf(os.name == 'nt', 'Native fake-ALSA regression runs in WSL')
    def test_native_call_backend_applies_and_restores_main_mic_gain(self):
        AUDIO(self.root)
        native = TOP/'devices/common/infoscreen/native'
        program = self.root/'capture.c'
        program.write_text(r'''
#define main shared_hardware_tests
#include "test-hardware.c"
#undef main
int main(void) {
 VoiceHardware *h=g_new0(VoiceHardware,1);
 fixture(h);
 GError *error=NULL;
 Json *stock=read_json("/usr/share/e5/voice-routes.json");
 const char *control="ADC_1 Gain ADC_1 Capture Volume";
 const char *groups[]={"RECEIVER","SPEAKER"};
 for(unsigned i=0;i<2;i++)
  js(jget(h->routes,groups[i]),control,jstr(jget(stock,groups[i]),control,""));
 Json *saved=snapshot(h,&error);
 assert(saved&&!error);
 h->speaker=false;
 assert(output(h,&error));
 char *gain=get(h,control,&error);
 assert(!strcmp(gain,"7,7"));g_free(gain);
 h->speaker=true;
 assert(output(h,&error));
 gain=get(h,control,&error);
 assert(!strcmp(gain,"6,6"));g_free(gain);
 assert(restore(h,saved,&error));
 gain=get(h,control,&error);
 assert(!strcmp(gain,jstr(saved,control,"")));g_free(gain);
 json_object_put(saved);json_object_put(stock);
 audio_free(h);
 g_ptr_array_unref(names);g_ptr_array_unref(writes);
 return 0;
}
''')
        build = runpy.run_path(str(native/'test-support.py'))['compile_native']
        binary = build(self.root, 'capture', [program, native/'native-common.c'])
        subprocess.run([str(binary)], env=dict(os.environ, E5_NATIVE_ROOT=str(self.root)), check=True)

    def test_another_profile_never_receives_y60_audio(self):
        self.put('etc/e5/device-profile', 'm8\n')
        with self.assertRaisesRegex(ValueError, 'another device'):
            AUDIO(self.root)

    def test_missing_recipient_route_does_not_invent_calibration(self):
        (self.root/'lib/firmware/y60-audio_route.xml').unlink()
        with self.assertRaises(FileNotFoundError): AUDIO(self.root)
        self.assertNotIn('HW_MAX=', (self.root/'usr/libexec/e5-volume').read_text())

    def test_magisk_conversion_retains_y60_audio_files_and_converts_native_tables(self):
        stock = Path(os.environ['Y60_STOCK_FIRST'])
        raw, out = self.root/'raw', self.root/'converted'
        raw.mkdir()
        for name, source in (
                ('aw87xxx_acf.bin', 'vendor_a/firmware/aw87xxx_acf.bin'),
                ('bt_configure_pskey.xpe.ini', 'odm_a/firmware/bt_configure_pskey.xpe.ini'),
                ('bt_configure_rf.xpe.ini', 'odm_a/firmware/bt_configure_rf.xpe.ini'),
                ('audio_route.xml', 'odm_a/etc/audio_route.xml')):
            shutil.copyfile(stock/source, raw/name)
        for name in ('audio_structure.xml', 'dsp_vbc.xml', 'cvs.xml', 'codec.xml', 'audio_pga.xml'):
            shutil.copyfile(stock/'odm_a/etc/audio_params/sprd'/name, raw/name)
        # Public conversion does not inspect the DSP beyond its header/size.
        # Use synthetic firmware bytes and a local test MAC, never user NV.
        (raw/'l_agdsp_a.img').write_bytes(b'SharkL5_AUD\0' + bytes(6291456-12))
        (raw/'wcnmodem.bin').write_bytes(b'public-firmware-fixture')
        (raw/'wifi_board_config.xpe.ini').write_text('[test]\n')
        (raw/'btmac.txt').write_text('02:00:00:00:00:01\n')
        tools = self.root/'tools'
        (tools/'vbc-profile').mkdir(parents=True)
        shutil.copyfile(TOP/'tools/sprd-bt-config.py', tools/'sprd-bt-config.py')
        shutil.copyfile(TOP/'tools/vbc-profile/vbc-profile.py', tools/'vbc-profile/vbc-profile.py')
        convert = runpy.run_path(str(TOP/'openwrt/bundle/magisk-firmware.py'))['convert']
        convert(raw, out, tools, 'Y60-OpenWrt', 'y60')
        fw = out/'lib/firmware'
        self.assertEqual((fw/'y60-audio_route.xml').read_bytes(), (raw/'audio_route.xml').read_bytes())
        self.assertEqual((fw/'aw87xxx_acf.bin').read_bytes(), (raw/'aw87xxx_acf.bin').read_bytes())
        for name in ('dsp_vbc', 'audio_structure', 'cvs', 'sprd/marlin3lite_pskey.bin', 'sprd/marlin3lite_rf.bin'):
            self.assertGreater((fw/name).stat().st_size, 0)
        self.assertFalse(list(fw.glob('*nv*')))


class Package(unittest.TestCase):
    @unittest.skipIf(os.name == 'nt', 'Offline service links require POSIX')
    def test_repeat_y60_staging_keeps_audio_service_link(self):
        real_run = runpy.run_path
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def base_stage(target, *, profile):
                self.assertEqual(profile, 'y60')
                for name in ('etc/e5', 'etc/rc.d', 'etc/init.d', 'opt/e5', 'usr/libexec'):
                    (target/name).mkdir(parents=True, exist_ok=True)
                (target/'opt/e5/e5-audio-dsp').write_bytes(
                    (TOP/'rootfs/overlay/opt/e5/e5-audio-dsp').read_bytes())
            def dependency(path, *args, **kwargs):
                if Path(path).resolve() == (TOP/'devices/m8/stage.py').resolve():
                    return {'stage': base_stage}
                return real_run(path, *args, **kwargs)
            with patch.object(runpy, 'run_path', side_effect=dependency):
                STAGE['stage'](root)
                first = {name:p.read_bytes() for name in ('usr/lib/e5/y60_audio.py', 'etc/init.d/e5-y60-audio')
                         if (p:=root/name).is_file()}
                STAGE['stage'](root)
                for name, data in first.items():
                    self.assertEqual((root/name).read_bytes(), data)
                service = root/'etc/rc.d/S18e5-y60-audio'
                self.assertEqual(os.readlink(service), '../init.d/e5-y60-audio')
                service.unlink()
                service.symlink_to('../init.d/foreign-service')
                with self.assertRaisesRegex(ValueError, 'Unexpected service link'):
                    STAGE['stage'](root)

    @unittest.skipIf(os.name == 'nt', 'POSIX startup execution runs in WSL')
    def test_missing_sco_control_no_longer_prevents_the_analog_route(self):
        original = (TOP/'rootfs/overlay/opt/e5/e5-audio-dsp').read_text()
        def function(text):
            start = text.index('set_routes() {')
            end = text.index('\n}\n', start) + 3
            return text[start:end]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root/'commands'
            commands = {
                'amixer': '#!/bin/sh\necho SCO >> "$TEST_LOG"\nexit 9\n',
                'awk': '#!/bin/sh\necho 1\n',
                'alsaucm': '#!/bin/sh\necho "UCM $*" >> "$TEST_LOG"\n',
            }
            for name, body in commands.items():
                path = root/name; path.write_text(body); path.chmod(0o755)
            env = dict(os.environ, PATH=str(root)+':'+os.environ['PATH'], TEST_LOG=str(log))
            old = subprocess.run(['sh', '-c', function(original)+'\nset_routes\n'],
                                 env=env, capture_output=True, text=True)
            self.assertEqual(old.returncode, 1)
            self.assertEqual(log.read_text(), 'SCO\n')
            log.unlink()
            fixed = subprocess.run(['sh', '-c', function(STAGE['audio_startup'](original))+'\nset_routes\n'],
                                   env=env, capture_output=True, text=True)
            self.assertEqual(fixed.returncode, 0, fixed.stderr)
            self.assertIn('UCM -c hw:1 set _verb HiFi set _enadev Speaker set _enadev Mic', log.read_text())
            self.assertNotIn('SCO', log.read_text())

    def test_analog_startup_does_not_require_the_bluetooth_pinmux(self):
        text = (TOP/'rootfs/overlay/opt/e5/e5-audio-dsp').read_text()
        fixed = STAGE['audio_startup'](text)
        self.assertNotIn('amixer -q -c 0 cset name=SYS_IIS0', fixed)
        self.assertEqual(STAGE['audio_startup'](fixed), fixed)
        self.assertIn('load_all || exit 1', fixed)
        self.assertIn('set_routes', fixed)
        # SCO still requests its factory mux in the real voice manifest.
        manifest = json.loads(runpy.run_path(str(TOP/'devices/common/build-screen-native.py'))['route_manifest']())
        self.assertEqual(manifest['BLUETOOTH']['SYS_IIS0'], 'vbc_iis3')

    def test_y60_is_opt_in_and_package_flows_agree(self):
        build = runpy.run_path(str(TOP/'tools/build-release.py'))
        self.assertNotIn('y60', build['PROFILES'])
        self.assertIn('y60', build['EXPERIMENTAL_PROFILES'])
        models = runpy.run_path(str(TOP/'openwrt/build-profile-tf.py'))['MODELS']
        magisk = runpy.run_path(str(TOP/'openwrt/bundle/finalize-package.py'))['MODELS']
        self.assertEqual(models['y60'], [magisk['y60']])
        self.assertEqual(models['y60'], ['CP23NV3'])
        with tempfile.TemporaryDirectory() as temp:
            Path(temp, 'device-profile.json').write_text(json.dumps({'profile':'y60','android_models':models['y60']}))
            funcs = runpy.run_path(str(TOP/'openwrt/bundle/flash.py'))
            funcs['package_profile'].__globals__['F'] = temp
            self.assertEqual(funcs['package_profile']()['profile'], 'y60')
            self.assertEqual(funcs['default_hotspot_name'](), 'Y60-OpenWrt')


if __name__ == '__main__': unittest.main()
