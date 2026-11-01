#!/usr/bin/env python3
"""Check startup patching and actual netifd EPS branches without modem access.

Run on Linux: test_network_startup.py <original modemmanager.sh> <original modemmanager.js>
"""
from pathlib import Path
import os
import signal
import time
import runpy
import subprocess
import sys
import tempfile
import unittest

PROTO, LUCI = [Path(p).read_text() for p in sys.argv[1:3]]
del sys.argv[1:3]
HERE = Path(__file__).resolve().parent
BUILD = runpy.run_path(str(HERE.parents[1]/'tools/build-release.py'))
PROFILES = (*BUILD['PROFILES'], *BUILD['EXPERIMENTAL_PROFILES'])
patch_root = runpy.run_path(str(HERE / 'network-startup.py'))['patch_root']
LOADER = (HERE.parents[1] / 'openwrt/overlay/etc/init.d/e5-sipc-wwan').read_text()


class Startup(unittest.TestCase):
    def test_direct_overlay_already_preserves_pacing_and_immediate_port_report(self):
        # Maintenance and common runtime staging also copy this file directly,
        # before APK postinstall/network-startup gets a chance to patch it.
        self.assertIn('card=$C tx_gap_ms=50', LOADER)
        self.assertIn('[ $C = 0 ] && insmod $M/sipc_wwan.ko tx_gap_ms=50;', LOADER)
        report=LOADER.index('/usr/libexec/e5-mm-report-ports ] ||')
        self.assertGreater(report, LOADER.index('insmod $M/sipc_wwan.ko card=$C'))
        self.assertLess(report, LOADER.index('echo "sipc_wwan loaded'))

    def test_data_disconnect_keeps_unisoc_rf_unless_explicitly_overridden(self):
        text=(self.root/'lib/netifd/proto/modemmanager.sh').read_text()
        start=text.index('\t# unisoc-data-rf-independent:')
        end=text.index('\n\t# low power, only if requested',start)
        block=text[start:end]
        for device in ('unisoc-sipc','usb-modem'):
            for explicit in ('','0','1'):
                shell='uci_get(){ if [ -n "$EXPLICIT" ]; then echo "$EXPLICIT"; else echo "$4"; fi; }\nmmcli(){ echo MM_DISABLE; }\nrun(){\n'+block+'\n}\nrun\n'
                result=subprocess.run(['sh','-c',shell],env=dict(os.environ,device=device,interface='wan',EXPLICIT=explicit),capture_output=True,text=True)
                expected=explicit=='1' or (not explicit and device!='unisoc-sipc')
                self.assertEqual('MM_DISABLE' in result.stdout,expected,(device,explicit,result.stderr))
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='t551m-network-test-')
        self.root = Path(self.tmp.name)
        for name, text in [('etc/init.d/e5-sipc-wwan', LOADER),
                           ('lib/netifd/proto/modemmanager.sh', PROTO),
                           ('www/luci-static/resources/protocol/modemmanager.js', LUCI)]:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        patch_root(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_idempotent_and_loader_preserves_sim_selection(self):
        files = [p for p in self.root.rglob('*') if p.is_file()]
        before = {p: p.read_bytes() for p in files}
        patch_root(self.root)
        self.assertEqual(before, {p: p.read_bytes() for p in files})
        text = (self.root / 'etc/init.d/e5-sipc-wwan').read_text()
        self.assertIn('card=$C tx_gap_ms=50', text)
        self.assertIn('e5-sim-probe /dev/stty_nr1 "$C"', text)
        self.assertIn('[ $C = 0 ] && insmod $M/sipc_wwan.ko tx_gap_ms=50;', text)
        self.assertIn("o.value('keep'", (self.root / 'www/luci-static/resources/protocol/modemmanager.js').read_text())
        subprocess.run(['busybox', 'sh', '-n', str(self.root / 'etc/init.d/e5-sipc-wwan')], check=True)

    def test_upgrade_old_pacing_and_preserve_recovery_entry(self):
        loader = self.root / 'etc/init.d/e5-sipc-wwan'
        for gap in (100, 300):
            loader.write_text(LOADER.replace('tx_gap_ms=50', f'tx_gap_ms={gap}'))
            patch_root(self.root)
            self.assertEqual(loader.read_text().count('tx_gap_ms=50'), 2)
            self.assertNotIn(f'tx_gap_ms={gap}', loader.read_text())
        config = (self.root / 'lib/preinit/01_e5_boot_wait').read_text()
        self.assertIn('fs_failsafe_wait_timeout=1', config)
        self.assertNotIn('pi_preinit_no_failsafe=', config)

    def test_every_profile_stages_one_identical_event_recovery(self):
        expected = (HERE.parents[1] / 'openwrt/overlay/usr/libexec/e5-network-recovery').read_bytes().replace(b'\r\n', b'\n')
        for profile in ('e5', 't551m', 'm8', 't512n', 'yuanhang41s'):
            with self.subTest(profile=profile):
                patch_root(self.root, profile)
                target = self.root/'usr/libexec/e5-network-recovery'
                self.assertEqual(target.read_bytes(), expected)
                self.assertTrue(target.stat().st_mode & 0o111)
                self.assertEqual(os.readlink(self.root/'etc/rc.d/S96e5-network-recovery'),
                                 '../init.d/e5-network-recovery')

    def test_keep_skips_radio_cycle_and_existing_modes_still_apply(self):
        text = (self.root / 'lib/netifd/proto/modemmanager.sh').read_text()
        subprocess.run(['busybox', 'sh', '-n', str(self.root / 'lib/netifd/proto/modemmanager.sh')], check=True)
        start = text.index('\t# set initial eps bearer settings')
        end = text.index('\tif [ -z "${allowedmode}" ]', start)
        harness = '''
modemmanager_init_epsbearer() { printf 'EPS:%s:%s\\n' "$1" "$3"; }
append_param() { [ -z "$connectargs" ] || connectargs="$connectargs,"; connectargs="$connectargs$1"; }
run_eps() {
''' + text[start:end] + '\n: # normal setup continues to mode/PLMN and simple-connect\n}\nrun_eps\n'
        for mode in ('keep', '', 'default', 'custom'):
            with self.subTest(mode=mode):
                env = dict(os.environ, init_epsbearer=mode, device='fake', apn='internet',
                           init_apn='private', iptype='ipv4', init_iptype='ipv4v6',
                           allowedauth='pap', init_allowedauth='chap', username='user', password='pass')
                out = subprocess.run(['busybox', 'sh', '-c', harness], env=env,
                                     capture_output=True, text=True, check=True).stdout
                if mode == 'keep':
                    self.assertNotIn('EPS:', out)
                elif not mode:
                    self.assertEqual(out, 'EPS:none:\n')
                elif mode == 'default':
                    self.assertIn('EPS:default:apn=internet,ip-type=ipv4,allowed-auth=pap,user=user,password=pass', out)
                else:
                    self.assertIn('EPS:custom:apn=private,ip-type=ipv4v6,allowed-auth=chap', out)
        self.assertIn('modemmanager_connect_retry "$device" "$connectargs"', text)

    def test_migration_only_changes_original_default_once(self):
        script = (HERE / 'network-startup-defaults').read_text()
        marker = self.root / 'migrated'
        script = script.replace('/etc/e5/t551m-network-startup-v1', str(marker))
        harness = '''
cat() { echo "$PROFILE"; }
python3() { :; }
uci() {
    case "$*" in
        '-q get network.wan.proto') echo modemmanager;;
        '-q get network.wan.init_epsbearer') echo "$MODE";;
        *) echo "$*";;
    esac
}
'''
        for profile in (*PROFILES, 'foreign'):
            for mode in ('custom', 'connection', 'keep', '', 'default'):
                with self.subTest(profile=profile, mode=mode):
                    marker.unlink(missing_ok=True)
                    env = dict(os.environ, MODE=mode, PROFILE=profile)
                    out = subprocess.run(['busybox', 'sh', '-c', harness + script], env=env,
                                         capture_output=True, text=True, check=True).stdout
                    supported = profile != 'foreign'
                    self.assertEqual('set network.wan.init_epsbearer=keep' in out,
                                     supported and mode == 'default')
                    self.assertEqual(marker.exists(), supported)
                    again = subprocess.run(['busybox', 'sh', '-c', harness + script], env=env,
                                           capture_output=True, text=True, check=True).stdout
                    self.assertEqual(again, '')

    def test_default_dial_does_not_overwrite_pre_dial_mode(self):
        text = (self.root / 'lib/netifd/proto/modemmanager.sh').read_text()
        start = text.index('\tif [ -z "${allowedmode}" ]')
        end = text.index('\tif [ -z "${plmn}" ]', start)
        harness = '''
modemmanager_set_allowed_mode() { echo SET:$3; }
modemmanager_set_preferred_mode() { echo PREFERRED:$3:$4; }
run_modes() {
''' + text[start:end] + '\n: # real setup continues to PLMN and simple-connect\n}\nrun_modes\n'
        for mode in ('', '4g', 'any'):
            out = subprocess.run(['busybox', 'sh', '-c', harness],
                                 env=dict(os.environ, allowedmode=mode), capture_output=True, text=True, check=True).stdout
            if not mode:
                self.assertNotIn('SET:', out)
                self.assertIn('Keeping current network mode', out)
            else:
                self.assertEqual(out.strip(), 'SET:'+mode)

    def test_pdp_retry_shared_across_profiles(self):
        path = self.root / 'lib/netifd/proto/modemmanager.sh'
        for profile in PROFILES:
            with self.subTest(profile=profile):
                path.write_text(PROTO)
                patch_root(self.root, profile)
                self.assertEqual(path.read_text().count('# unisoc-pdp-connect-retry:'), 1)
                self.assertIn('modemmanager_connect_retry "$device" "$connectargs" || {', path.read_text())
                before = path.read_bytes()
                patch_root(self.root, profile)
                self.assertEqual(path.read_bytes(), before)
                self.test_pdp_retry_backs_off_and_only_retries_transient_errors()

    def test_pdp_retry_backs_off_and_only_retries_transient_errors(self):
        text = (self.root / 'lib/netifd/proto/modemmanager.sh').read_text()
        helper = text[text.index('# unisoc-pdp-connect-retry:'):text.index('proto_modemmanager_setup() {')]
        harness = '''
mmcli() {
    case "$*" in *--output-keyvalue*) echo cached; return 0 ;; esac
    n=$(cat "$COUNT" 2>/dev/null || echo 0); n=$((n+1)); echo "$n" > "$COUNT"
    if [ "$n" -gt "$FAILURES" ]; then echo connected; return 0; fi
    echo "$ERROR" >&2; return 1
}
sleep() { echo "WAIT:$1"; }
modemmanager_get_field() { case "$2" in modem.generic.state) echo registered ;; *) echo attached ;; esac; }
''' + helper + '\nmodemmanager_connect_retry "$DEVICE" "apn=test,ip-type=ipv4v6"\n'
        error = "error: couldn't connect the modem: 'GDBus.Error:Unknown: Couldn't activate PDP context 1: Unknown mobile equipment error: 28'"
        cases = [(0, error, 'unisoc-sipc', 1, [], 0),
                 (1, error, 'unisoc-sipc', 2, ['WAIT:1'], 0),
                 (2, error, 'unisoc-sipc', 3, ['WAIT:1', 'WAIT:3'], 0),
                 (12, error, 'unisoc-sipc', 13, ['WAIT:1', 'WAIT:3', 'WAIT:5', 'WAIT:7'] * 3, 0),
                 (2, 'GDBus.Error:org.freedesktop.ModemManager1.Error.MobileEquipment.NoNetwork: No network', 'unisoc-sipc', 3, ['WAIT:1', 'WAIT:3'], 0),
                 (1, 'No IPv4 settings for PDP context 1', 'unisoc-sipc', 2, ['WAIT:1'], 0),
                 (1, 'GDBus.Error:org.freedesktop.ModemManager1.Error.Core.Cancelled: Operation was cancelled', 'unisoc-sipc', 2, ['WAIT:1'], 0),
                 (9, 'GDBus.Error:org.freedesktop.ModemManager1.Error.MobileEquipment.GprsAuthenticationFailure: authentication failed', 'unisoc-sipc', 1, [], 1),
                 (9, 'GDBus.Error:org.freedesktop.ModemManager1.Error.Core.InvalidArgs: bad APN', 'unisoc-sipc', 1, [], 1),
                 (9, 'SIM PIN required', 'unisoc-sipc', 1, [], 1),
                 (9, error.replace("28'", "29'"), 'unisoc-sipc', 1, [], 1),
                 (9, error, '/dev/ttyUSB0', 1, [], 1)]
        count = self.root / 'attempts'
        for failures, message, device, expected, waits, rc in cases:
            with self.subTest(failures=failures, message=message, device=device):
                count.unlink(missing_ok=True)
                env = dict(os.environ, COUNT=str(count), FAILURES=str(failures), ERROR=message, DEVICE=device)
                result = subprocess.run(['busybox', 'sh', '-c', harness], env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, rc, result.stderr)
                self.assertEqual(int(count.read_text()), expected)
                self.assertEqual([line for line in result.stdout.splitlines() if line.startswith('WAIT:')], waits)

    def test_cancelled_setup_requires_a_still_enabled_modem(self):
        text = (self.root / 'lib/netifd/proto/modemmanager.sh').read_text()
        helper = text[text.index('# unisoc-pdp-connect-retry:'):text.index('proto_modemmanager_setup() {')]
        harness = '''
mmcli() { [ "$*" = '--modem=unisoc-sipc --output-keyvalue' ] || exit 9; [ "$READ_FAIL" != 1 ] && echo cached; }
modemmanager_get_field() { echo "$STATE"; }
''' + helper + '''
modemmanager_unisoc_retryable 'GDBus.Error:org.freedesktop.ModemManager1.Error.Core.Cancelled: Operation was cancelled' unisoc-sipc
'''
        for state in ('enabled', 'enabling', 'searching', 'registered', 'connecting', 'connected', 'disconnecting',
                      'disabled', 'disabling', 'failed', 'locked', 'unknown', ''):
            for failed in ('0', '1'):
                with self.subTest(state=state, read_failed=failed):
                    result = subprocess.run(['busybox', 'sh', '-c', harness],
                        env=dict(os.environ, STATE=state, READ_FAIL=failed),
                        capture_output=True, text=True, timeout=5)
                    allowed = state in ('enabled', 'enabling', 'searching', 'registered', 'connecting', 'connected', 'disconnecting') and failed == '0'
                    self.assertEqual(result.returncode, 0 if allowed else 1, result.stderr)

    def test_cancelled_handover_runs_the_real_setup_failure_branch(self):
        text = (self.root / 'lib/netifd/proto/modemmanager.sh').read_text()
        helper = text[text.index('# unisoc-pdp-connect-retry:'):text.index('proto_modemmanager_setup() {')]
        start = text.index('\tmodemmanager_connect_retry "$device" "$connectargs" || {')
        end = text.index('\n\t# check if Signal refresh rate', start)
        branch = text[start:end]
        harness = '''
mmcli() {
 case "$*" in *--output-keyvalue*) echo cached; return 0 ;; esac
 n=$(cat "$COUNT" 2>/dev/null || echo 0); n=$((n+1)); echo "$n" > "$COUNT"
 [ "$n" -gt "$FAILURES" ] && { echo connected; return 0; }
 echo "GDBus.Error:org.freedesktop.ModemManager1.Error.Core.$ERROR: Operation failed"; return 1
}
modemmanager_get_field() { case "$2" in modem.generic.state) echo "$STATE" ;; *) echo "$PACKET" ;; esac; }
sleep() { echo WAIT:$1; }
proto_set_available() { echo AVAILABLE:$1:$2; }
proto_block_restart() { echo BLOCK:$1; }
proto_notify_error() { echo ERROR:$2; }
''' + helper + '\nsetup() {\n' + branch + '\necho SETUP_CONNECTED\n}\nsetup\n'
        count = self.root / 'handover-attempts'
        cases = [('Cancelled', 'registered', 'attached', 3, 0, ['WAIT:1', 'WAIT:3', 'WAIT:5']),
                 ('Cancelled', 'disconnecting', 'attached', 2, 0, ['WAIT:1', 'WAIT:3']),
                 ('Cancelled', 'connected', 'attached', 1, 0, ['WAIT:1']),
                 ('WrongState', 'disconnecting', 'attached', 1, 0, ['WAIT:1']),
                 ('WrongState', 'enabling', 'attached', 1, 0, ['WAIT:1']),
                 ('Cancelled', 'searching', 'detached', 1, 1, []),
                 ('Cancelled', 'registered', 'detached', 1, 1, []),
                 ('Cancelled', 'disabling', 'attached', 1, 1, []),
                 ('Cancelled', 'disabled', 'detached', 1, 1, []),
                 ('Cancelled', 'failed', 'detached', 1, 1, []),
                 ('WrongState', 'registered', 'attached', 1, 1, [])]
        for error, state, packet, failures, rc, waits in cases:
            with self.subTest(error=error, state=state, packet=packet):
                count.unlink(missing_ok=True)
                env = dict(os.environ, COUNT=str(count), FAILURES=str(failures),
                           ERROR=error, STATE=state, PACKET=packet, interface='wan',
                           device='unisoc-sipc', connectargs='apn=test', force_connection='0')
                result = subprocess.run(['busybox', 'sh', '-c', harness], env=env,
                                        capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, rc, result.stderr)
                self.assertEqual([l for l in result.stdout.splitlines() if l.startswith('WAIT:')], waits)
                if not rc:
                    self.assertIn('SETUP_CONNECTED', result.stdout)
                    self.assertNotIn('BLOCK:', result.stdout)
                    self.assertNotIn('ERROR:', result.stdout)
                    self.assertEqual(int(count.read_text()), failures + 1)
                elif state == 'searching' or state == 'registered' and packet == 'detached':
                    self.assertIn('AVAILABLE:wan:0', result.stdout)
                    self.assertNotIn('BLOCK:', result.stdout)
                    self.assertEqual(int(count.read_text()), 1)
                else:
                    self.assertIn('BLOCK:wan', result.stdout)
                    self.assertEqual(int(count.read_text()), 1)

    def test_registration_uses_same_transient_policy(self):
        text=(self.root/'lib/netifd/proto/modemmanager.sh').read_text()
        start=text.index('modemmanager_set_plmn() {')
        self.assertIn('modemmanager_register_retry "$device" "$plmn" || {',text[start:])
        helper=text[text.index('# unisoc-pdp-connect-retry:'):text.index('proto_modemmanager_setup() {')]
        count=self.root/'register-attempts'
        harness="""
mmcli() {
 case "$*" in *--output-keyvalue*) echo cached; return 0 ;; esac
 case "$*" in *--3gpp-register-in-operator=*) ;; *) return 9 ;; esac
 n=$(cat "$COUNT" 2>/dev/null || echo 0); n=$((n+1)); echo "$n" > "$COUNT"
 [ "$n" -gt 2 ] && return 0
 echo 'GDBus.Error:org.freedesktop.ModemManager1.Error.MobileEquipment.NetworkTimeout: Network timeout'; return 1
}
sleep() { echo "WAIT:$1"; }
modemmanager_get_field() { case "$2" in modem.generic.state) echo registered ;; *) echo attached ;; esac; }
"""+helper+'\nmodemmanager_register_retry unisoc-sipc ""\n'
        result=subprocess.run(['busybox','sh','-c',harness],env=dict(os.environ,COUNT=str(count)),capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(count.read_text().strip(),'3')
        self.assertEqual([line for line in result.stdout.splitlines() if line.startswith('WAIT:')],['WAIT:1','WAIT:3'])

    def test_no_coverage_waits_for_ps_event_without_blocking_user_intent(self):
        text=(self.root/'lib/netifd/proto/modemmanager.sh').read_text()
        helper=text[text.index('# unisoc-pdp-connect-retry:'):text.index('proto_modemmanager_setup() {')]
        harness='''
mmcli() {
 case "$*" in *--output-keyvalue*) echo cached; return 0 ;; esac
 echo 'GDBus.Error:org.freedesktop.ModemManager1.Error.MobileEquipment.NoNetwork: No network';return 1
}
modemmanager_get_field() { case "$2" in modem.generic.state) echo searching ;; *) echo detached ;; esac; }
sleep() { echo UNEXPECTED_SLEEP; }
proto_set_available() { echo AVAILABLE:$1:$2; }
proto_block_restart() { echo BLOCK:$1; }
''' + helper + '''
modemmanager_connect_retry unisoc-sipc apn=test
modemmanager_unisoc_block_restart wan unisoc-sipc
MODEMMANAGER_UNISOC_WAIT_PS=0
modemmanager_unisoc_block_restart wan unisoc-sipc
'''
        result=subprocess.run(['busybox','sh','-c',harness],capture_output=True,text=True,timeout=5,check=True)
        self.assertIn('AVAILABLE:wan:0',result.stdout)
        self.assertIn('BLOCK:wan',result.stdout)
        self.assertNotIn('UNEXPECTED_SLEEP',result.stdout)

    def test_old_retry_helper_is_upgraded_without_replaying_settings(self):
        path=self.root/'lib/netifd/proto/modemmanager.sh'
        text=path.read_text();start=text.index('# unisoc-pdp-connect-retry:');end=text.index('proto_modemmanager_setup() {',start)
        path.write_text(text[:start]+'# unisoc-pdp-connect-retry: old finite retry\nmodemmanager_connect_retry() { return 1; }\n\n'+text[end:])
        patch_root(self.root)
        upgraded=path.read_text()
        self.assertNotIn('old finite retry',upgraded)
        self.assertIn('modemmanager_unisoc_retryable()',upgraded)
        self.assertEqual(upgraded.count('# unisoc-apn-selection:'),1)
        self.assertEqual(upgraded.count('modemmanager_register_retry "$device" "$plmn" || {'),1)

    def test_setup_sigterm_stops_mmcli_and_backoff_without_further_attempts(self):
        text=(self.root/'lib/netifd/proto/modemmanager.sh').read_text()
        helper=text[text.index('# unisoc-pdp-connect-retry:'):text.index('proto_modemmanager_setup() {')]
        bindir=self.root/'bin';bindir.mkdir()
        for command in ('mmcli','sleep'):
            tool=bindir/command
            tool.write_text('#!/usr/bin/env python3\nimport os,time,sys\nfrom pathlib import Path\nname=Path(sys.argv[0]).name\nif name=="mmcli" and os.environ["MODE"]=="backoff":\n print("GDBus.Error:org.freedesktop.ModemManager1.Error.MobileEquipment.NoNetwork: No network");sys.exit(1)\nif name=="mmcli" and os.environ["MODE"]=="cancelled-backoff":\n if "--output-keyvalue" in sys.argv: print("cached");sys.exit(0)\n print("GDBus.Error:org.freedesktop.ModemManager1.Error.Core.Cancelled: Operation was cancelled");sys.exit(1)\nPath(os.environ["CHILD"]).write_text(str(os.getpid()))\ntime.sleep(30)\n')
            tool.chmod(0o755)
        for mode in ('command','backoff','cancelled-backoff'):
            with self.subTest(mode=mode):
                child=self.root/'child';child.unlink(missing_ok=True)
                script='mktemp() { command mktemp "$TMPDIR/start.XXXXXX"; }\nsleep() { exec "$TEST_BIN/sleep" "$@"; }\nmodemmanager_get_field() { case "$2" in modem.generic.state) echo registered ;; *) echo attached ;; esac; }\n'+helper+'\nmodemmanager_connect_retry unisoc-sipc apn=test\n'
                env=dict(os.environ,PATH=str(bindir)+os.pathsep+os.environ['PATH'],MODE=mode,CHILD=str(child),TMPDIR=str(self.root),TEST_BIN=str(bindir))
                proc=subprocess.Popen(['busybox','ash','-c',script],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                try:
                    end=time.monotonic()+3
                    while not child.exists() and time.monotonic()<end:time.sleep(.01)
                    self.assertTrue(child.exists(),'controlled command did not start')
                    pid=int(child.read_text())
                    proc.send_signal(signal.SIGTERM)
                    stdout,stderr=proc.communicate(timeout=3)
                    self.assertEqual(proc.returncode,143,stderr)
                    self.assertFalse(Path('/proc/'+str(pid)).exists(),'cancelled child survived setup')
                    self.assertFalse(list(self.root.glob('start.*')),'retry output survived cancellation')
                finally:
                    if proc.poll() is None:proc.terminate();proc.communicate(timeout=3)

    def test_unknown_package_layout_refused(self):
        path = self.root / 'lib/netifd/proto/modemmanager.sh'
        path.write_text('# changed upstream interface\n')
        with self.assertRaisesRegex(ValueError, 'Unexpected ModemManager'):
            patch_root(self.root)

    def test_modem_auto_mode_profile_boundary_and_explicit_override(self):
        path = self.root / 'etc/config/unisoc_modem'
        path.parent.mkdir(parents=True, exist_ok=True)
        original = "config core 'main'\n\toption device '/dev/ttyUSB0'\n"
        path.write_text(original)
        for profile in ('e5', 'm8', 't512n', 'yuanhang41s', 'k1', 'lym10k', 'changxing60'):
            path.write_text(original)
            patch_root(self.root, profile)
            self.assertIn("option auto_work_mode_default '152'", path.read_text())
            self.assertIn("option auto_work_mode 'default'", path.read_text())
        patch_root(self.root, 't551m')
        configured = path.read_text()
        self.assertIn("option auto_work_mode_default '152'", configured)
        self.assertIn("option auto_work_mode 'default'", configured)
        patch_root(self.root, 't551m')
        self.assertEqual(path.read_text(), configured)
        for override in ('134', '152', 'default'):
            path.write_text(configured.replace("auto_work_mode 'default'", "auto_work_mode '" + override + "'"))
            patch_root(self.root, 't551m')
            self.assertIn("option auto_work_mode '" + override + "'", path.read_text())


if __name__ == '__main__':
    unittest.main()
