#!/usr/bin/env python3
"""SMS idle waits stay bounded even when scans find no card/message.

This receiver uses driver sysfs events, not MU300's shell safety deadline.
No modem, SMS store or hardware access.
"""
import importlib.machinery
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

path=Path(__file__).resolve().parents[1]/'overlay/usr/libexec/e5-sms-receive'
loader=importlib.machinery.SourceFileLoader('sms_idle_receiver',str(path))
spec=importlib.util.spec_from_loader(loader.name,loader)
receiver=importlib.util.module_from_spec(spec);loader.exec_module(receiver)


class IdleEvents(unittest.TestCase):
    def test_missing_event_node_sleeps_instead_of_polling(self):
        with patch.object(receiver.glob,'glob',return_value=[]), patch.object(receiver.time,'sleep') as sleep:
            events=receiver.Events()
            self.assertEqual(events.wait(2),set())
            sleep.assert_called_once_with(2)

    def test_empty_scans_keep_waiting_after_the_safety_scan(self):
        waits=[]
        class Events:
            fd=7
            def wait(self,timeout):
                waits.append(timeout)
                if len(waits)==4:receiver.running=False
                return set()
            def close(self):pass
        previous=receiver.running
        try:
            receiver.running=True
            with patch.object(receiver,'Events',Events), patch.object(receiver.time,'monotonic',return_value=100), patch.object(receiver,'scan') as scan:
                receiver.serve()
                scan.assert_called_once_with({0,1})
            self.assertEqual(waits,[1,2,2,2])
        finally:receiver.running=previous


if __name__=='__main__':unittest.main()
