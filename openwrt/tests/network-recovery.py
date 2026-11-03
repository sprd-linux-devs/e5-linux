#!/usr/bin/env python3
"""Registration recovery must preserve user intent and never create retry loops."""
from pathlib import Path
import copy
import json
import runpy
import subprocess
import unittest
import tempfile
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'overlay/usr/libexec/e5-network-recovery'
scope = runpy.run_path(str(SOURCE))
Recovery = scope['Recovery']
GLOBALS = Recovery.evaluate.__globals__
MODEM = {'dbus-path': '/modem/0',
         'generic': {'device': 'unisoc-sipc', 'plugin': 'unisoc', 'state': 'registered',
                     'sim': '/sim/0',
                     'primary-sim-slot': '1', 'access-technologies': ['lte']},
         '3gpp': {'registration-state': 'home', 'packet-service-state': 'attached',
                  'operator-code': '46001'}}
WAN = {'interface': 'wan', 'proto': 'modemmanager', 'available': False,
       'autostart': True, 'up': False, 'pending': False,
       'errors': [{'code': 'MM_CONNECT_FAILED'}]}


class Tests(unittest.TestCase):
    def setUp(self):
        self.modem, self.wan = copy.deepcopy(MODEM), copy.deepcopy(WAN)
        self.commands = []
        def query(args):
            if args[0] == 'mmcli':
                return {'modem': self.modem}
            return {'interface': [self.wan]}
        def run(args, **kwargs):
            self.commands.append(args)
            return subprocess.CompletedProcess(args, 0, 'unisoc-sipc\n', '')
        self.permission=('0',True)
        self.patches = [patch.dict(GLOBALS, query=query,roaming_policy=lambda:self.permission), patch.object(scope['subprocess'], 'run', run)]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.recovery = Recovery()

    def resumes(self):
        return [c for c in self.commands if c[:3] == ['ubus', 'call', 'network.interface.wan']]

    def test_reattach_releases_availability_once(self):
        for _ in range(10):
            self.recovery.evaluate()
        self.assertEqual(self.resumes(), [['ubus', 'call', 'network.interface.wan',
                                          'notify_proto', '{"action":5,"available":true}']])

    def test_roaming_default_off_stops_data_without_radio_reset(self):
        self.permission=('0',False)
        self.modem['3gpp']['registration-state']='roaming'
        self.wan.update(up=True,available=True,errors=[])
        self.recovery.evaluate()
        notices=[json.loads(c[-1]) for c in self.resumes()]
        self.assertEqual(notices,[{'action':3,'error':['ROAMING_DISABLED']},{'action':5,'available':False}])
        self.commands.clear();self.wan.update(up=False,available=False,errors=[{'code':'ROAMING_DISABLED'}])
        self.recovery.evaluate();self.assertFalse(self.resumes())
        self.modem['3gpp']['registration-state']='home'
        self.recovery.evaluate()
        self.assertEqual(json.loads(self.resumes()[-1][-1]),{'action':5,'available':True})

    def test_permission_change_recreates_bearer_but_preserves_user_ifdown(self):
        self.wan.update(up=True,available=True,errors=[])
        self.recovery.evaluate();self.commands.clear()
        self.permission=('0',False)
        self.recovery.evaluate()
        self.assertEqual(json.loads(self.resumes()[-1][-1]),{'action':5,'available':False})
        self.commands.clear();self.wan.update(up=False,available=False,autostart=False)
        self.permission=('0',True);self.recovery.evaluate();self.assertFalse(self.resumes())

    def test_data_sim_switch_does_not_add_second_reconnect(self):
        self.wan.update(up=True,available=True,errors=[])
        self.recovery.evaluate();self.commands.clear()
        self.permission=('1',False);self.recovery.evaluate();self.assertFalse(self.resumes())

    def test_data_only_sim_needs_no_ims_or_cs_registration(self):
        for slot in ('1', '2'):
            for rat in ('lte', '5gnr'):
                for registration in ('home', 'roaming'):
                    self.modem = copy.deepcopy(MODEM)
                    self.modem['generic'].update({'primary-sim-slot': slot,
                                                 'access-technologies': [rat]})
                    self.modem['3gpp'].update({'registration-state': registration,
                                             'cs-registration-state': 'denied'})
                    self.commands.clear()
                    self.recovery = Recovery()
                    self.recovery.evaluate()
                    self.assertEqual(len(self.resumes()), 1, (slot, rat, registration))

    def test_manual_ifdown_pending_up_pin_and_auth_are_preserved(self):
        for update in ({'autostart': False}, {'pending': True}, {'up': True},
                       {'errors': [{'code': 'MM_PIN_REQUIRED'}]}, {'proto': 'dhcp'}):
            self.wan = {**copy.deepcopy(WAN), **update}
            self.recovery = Recovery()
            self.recovery.evaluate()
        self.assertEqual(self.resumes(), [])

    def test_packet_service_and_real_rat_required(self):
        for group, field, value in (('3gpp', 'packet-service-state', 'detached'),
                                     ('3gpp', 'registration-state', 'searching'),
                                     ('generic', 'access-technologies', ['unknown']),
                                     ('generic', 'device', '/dev/ttyUSB0'),
                                     ('generic', 'state', 'disabled')):
            self.modem = copy.deepcopy(MODEM)
            self.modem[group][field] = value
            self.recovery.evaluate()
        self.assertEqual(self.resumes(), [])

    def test_new_registration_or_rat_can_retry_after_previous_failure(self):
        self.recovery.evaluate()
        self.modem['3gpp']['registration-state'] = 'searching'
        self.recovery.evaluate()
        self.modem['3gpp']['registration-state'] = 'home'
        self.recovery.evaluate()
        self.modem['generic']['access-technologies'] = ['5gnr']
        self.recovery.evaluate()
        self.assertEqual(len(self.resumes()), 3)

    def test_active_bearer_is_never_cycled(self):
        self.wan['up'] = True
        for _ in range(4):
            self.recovery.evaluate()
        self.assertFalse(self.commands)

    def test_missing_sim_wait_resumes_only_after_real_registration(self):
        self.wan['errors'] = [{'code': 'MM_FAILED_REASON_SIM_MISSING'}]
        self.modem['generic']['state'] = 'failed'
        self.recovery.evaluate()
        self.assertFalse(self.resumes())
        self.modem = copy.deepcopy(MODEM)
        self.recovery.evaluate()
        self.assertEqual(len(self.resumes()), 1)
        self.wan['autostart'] = False
        self.recovery = Recovery()
        self.recovery.evaluate()
        self.assertEqual(len(self.resumes()), 1)

    def test_connecting_state_does_not_reset_retry_generation(self):
        self.recovery.evaluate()
        self.modem['generic']['state'] = 'connecting'
        self.wan['pending'] = True
        self.recovery.evaluate()
        self.modem['generic']['state'] = 'registered'
        self.wan['pending'] = False
        self.recovery.evaluate()
        self.assertEqual(len(self.resumes()), 1)

    def test_quality_refresh_is_ignored(self):
        self.assertFalse(scope['relevant_property'](b' string "SignalQuality"'))
        self.assertTrue(scope['relevant_property'](b' string "AccessTechnologies"'))
        self.assertTrue(scope['relevant_property'](b' string "State"'))
        self.assertTrue(scope['relevant_property'](b' string "PrimarySimSlot"'))

    def test_attached_before_generic_registered_does_not_lose_recovery(self):
        self.modem['generic']['state'] = 'enabled'
        self.recovery.evaluate()
        self.assertEqual(self.resumes(), [])
        self.modem['generic']['state'] = 'registered'
        self.recovery.evaluate()
        self.assertEqual(len(self.resumes()), 1)

    def test_late_modem_recovers_boot_no_device_before_registration(self):
        self.wan['errors'] = [{'code': 'NO_DEVICE'}]
        self.modem['generic']['state'] = 'enabled'
        self.modem['3gpp'].update({'registration-state': 'idle',
                                  'packet-service-state': 'detached'})
        self.modem['generic']['access-technologies'] = []
        for _ in range(10):
            self.recovery.evaluate()
        self.assertEqual(len(self.resumes()), 1)

    def test_no_device_preserves_sim_lock_manual_data_and_foreign_devices(self):
        self.wan['errors'] = [{'code': 'NO_DEVICE'}]
        for update in ({'state': 'failed'}, {'state': 'locked'},
                       {'state': 'initializing'}, {'sim': '--'},
                       {'device': '/dev/ttyUSB0'}):
            self.modem = copy.deepcopy(MODEM)
            self.modem['generic'].update(update)
            if 'sim' in update:
                self.modem['generic']['state'] = 'enabled'
                self.modem['3gpp']['packet-service-state'] = 'detached'
            self.recovery = Recovery()
            self.recovery.evaluate()
        self.assertFalse(self.resumes())
        self.modem = copy.deepcopy(MODEM)
        self.wan['autostart'] = False
        self.recovery.evaluate()
        self.assertFalse(self.resumes())

    def test_no_device_does_not_resume_with_explicit_radio_off(self):
        self.wan['errors'] = [{'code': 'NO_DEVICE'}]
        with patch.dict(GLOBALS, radio_allowed=lambda: False), \
             patch.object(Recovery, 'enable_other_sim_services'):
            self.recovery.evaluate()
        self.assertFalse(self.resumes())

    def test_disabled_data_sim_keeps_other_sim_services_without_data_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'policy').write_text('0 1\n')
            (root/'card').write_text('0\n')
            def mapped_path(name):
                return {'/etc/e5/sim-radio': root/'policy',
                        '/sys/module/sipc_wwan/parameters/card': root/'card',
                        '/run/unisoc-data-sim': root/'run'}.get(str(name), Path(name))
            self.modem['generic']['state'] = 'disabled'
            with patch.dict(GLOBALS, Path=mapped_path):
                for _ in range(4):
                    self.recovery.evaluate()
                enables = [c for c in self.commands if '--enable' in c]
                self.assertEqual(len(enables), 1)
                self.assertFalse(self.resumes())
                (root/'policy').write_text('0 0\n')
                self.recovery = Recovery()
                self.recovery.evaluate()
                self.assertEqual(len([c for c in self.commands if '--enable' in c]), 1)

    def test_sim_switch_lock_prevents_competing_logical_enable(self):
        import fcntl
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'policy').write_text('0 1\n')
            (root/'card').write_text('0\n')
            (root/'run').mkdir()
            def mapped_path(name):
                return {'/etc/e5/sim-radio': root/'policy',
                        '/sys/module/sipc_wwan/parameters/card': root/'card',
                        '/run/unisoc-data-sim': root/'run'}.get(str(name), Path(name))
            self.modem['generic']['state'] = 'disabled'
            with (root/'run/switch.lock').open('a') as lock, patch.dict(GLOBALS, Path=mapped_path):
                fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
                self.recovery.evaluate()
                self.assertFalse(self.commands)
                fcntl.flock(lock, fcntl.LOCK_UN)
                self.recovery.evaluate()
                self.assertEqual(len([c for c in self.commands if '--enable' in c]), 1)


if __name__ == '__main__':
    unittest.main()
