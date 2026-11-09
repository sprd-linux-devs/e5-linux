#!/usr/bin/env python3
"""PDU, two-card state and origin tests; no modem or external webhook involved."""
import importlib.machinery
import importlib.util
from pathlib import Path
import sys
import hashlib
import tempfile
import unittest
from unittest.mock import patch

TOP=Path(__file__).resolve().parents[2]
LIB=TOP/'openwrt/overlay/usr/lib/e5'
sys.path.insert(0,str(LIB))
import sms_pdu
path=TOP/'openwrt/overlay/usr/libexec/e5-sms-receive'
loader=importlib.machinery.SourceFileLoader('sms_receive',str(path))
spec=importlib.util.spec_from_loader(loader.name,loader)
receiver=importlib.util.module_from_spec(spec);loader.exec_module(receiver)

def ucs2(text,ref=None,part=1,total=2):
    # A fixture builder writes fields in TS 23.040 order, independent of decode().
    header=bytes([5,0,3,ref,total,part]) if ref is not None else b''
    user=header+text.encode('utf-16-be')
    return (b'\x00'+bytes([0x40 if header else 0,5,0x81,0x01,0x80,0xf6,0,8])+
            bytes.fromhex('62015091208523')+bytes([len(user)])+user).hex()

def incoming(text,index=1,ref=None,part=1,total=2):
    result=sms_pdu.decode(ucs2(text,ref,part,total))
    return {**result,'storage_index':index,'storage_status':0}


class Pdu(unittest.TestCase):
    def test_gsm7_known_packed_string(self):
        self.assertEqual(sms_pdu.septets(bytes.fromhex('E8329BFD4697D9EC37'),10),'hellohello')

    def test_ucs2_sender_timestamp_and_non_ascii(self):
        msg=sms_pdu.decode(ucs2('测试\n"&<中文>'))
        self.assertEqual(msg['text'],'测试\n"&<中文>')
        self.assertEqual(msg['number'],'10086')
        self.assertEqual(msg['time'],'2026-10-05T19:02:58+08:00')

    def test_multipart_out_of_order_and_missing_part(self):
        one=incoming('第一段',1,55,1);two=incoming('第二段',2,55,2)
        self.assertEqual(sms_pdu.assemble([two,one])[0]['text'],'第一段第二段')
        self.assertEqual(sms_pdu.assemble([two])[0]['state'],'receiving')

    def test_malformed_pdu_does_not_become_empty_sms(self):
        parts,errors=sms_pdu.listing('+CMGL: 1,0,,1\n\n0000\n')
        self.assertEqual(parts,[]);self.assertEqual(len(errors),1)

    def test_submit_known_gsm7_and_international_address(self):
        pdu=bytes.fromhex(sms_pdu.submit('+12345','hellohello',77)[0])
        self.assertEqual(pdu[:8],bytes.fromhex('00010005912143f5'))
        self.assertEqual(pdu[8:],bytes.fromhex('00000AE8329BFD4697D9EC37'))

    def test_submit_multipart_limits_unicode_surrogates_and_extension(self):
        for text,alphabet in [('中文'*100,8),('a'*400,0),('^'*160,0),('😀'*100,8)]:
            pdus=sms_pdu.submit('10086',text,0x1234)
            self.assertGreater(len(pdus),1)
            payloads=[]
            for part,hexpdu in enumerate(pdus,1):
                pdu=bytes.fromhex(hexpdu);self.assertEqual(pdu[1],0x41)
                self.assertEqual(pdu[9],alphabet);self.assertLessEqual(len(pdu[11:]),140)
                self.assertEqual(pdu[11:18],bytes([6,8,4,0x12,0x34,len(pdus),part]))
                payloads.append(sms_pdu.septets(pdu[11:],pdu[10]-8,56) if alphabet==0 else pdu[18:].decode('utf-16-be'))
            self.assertEqual(''.join(payloads),text)

    def test_submit_rejects_invalid_recipient_and_empty_text(self):
        for number,text in [('x;ATD','test'),('10086','')]:
            with self.assertRaises(ValueError):sms_pdu.submit(number,text)


class Inbox(unittest.TestCase):
    def setUp(self):
        # Never let offline tests write into a host /var/run or /tmp/run.
        temporary = tempfile.TemporaryDirectory(prefix='e5-sms-inbox-test-')
        self.addCleanup(temporary.cleanup)
        scoped = patch.object(receiver, 'RUN', Path(temporary.name))
        scoped.start()
        self.addCleanup(scoped.stop)

    def test_both_slots_restore_stored_mode_before_listing(self):
        for own in (0, 1):
            for card in (0, 1):
                commands=[]
                def at(slot, command):
                    commands.append((slot,command))
                    if command=='CCID?':return '+CCID: "89860012345678901234"'
                    if command=='CNMI?':return '+CNMI: 3,2,2,1,1'
                    if command=='CMGF?':return '+CMGF: 0'
                    if command=='CMGL=4':return '+CMGL: 1,0,,10\n'+ucs2('slot fixture')+'\nOK'
                    return 'OK'
                with patch.object(receiver,'at',side_effect=at):
                    _, messages = receiver.read_card(card,own)
                self.assertTrue(messages)
                self.assertIn((card,'CNMI=2,1,0,0,0'),commands)
                self.assertTrue(all(slot==card for slot,_ in commands))
                self.assertLess(commands.index((card,'CNMI=2,1,0,0,0')),commands.index((card,'CMGL=4')))

    def test_nr0_origin_hint_does_not_become_a_message_slot(self):
        # The event's ring/card field is not origin evidence. A sole ring-0
        # indication must make both explicitly selected storages eligible.
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'sms_events'
            path.write_text('1 0 SM 7\n')
            class Poll:
                def register(self,*args):pass
                def poll(self,*args):return []
            events=receiver.Events()
            try:
                with patch.object(receiver.glob,'glob',return_value=[str(path)]),patch.object(receiver.select,'poll',return_value=Poll()):
                    self.assertEqual(events.wait(0),{0,1})
                    self.assertEqual(events.wait(0),set())
                    path.write_text('2 0 SM 7\n')
                    self.assertEqual(events.wait(0),{0,1})
            finally:events.close()

    def fresh(self):
        return {'version':1,'next_id':receiver.MIN_ID,'initialized':[],'messages':[],'slots':{}}

    def test_web_read_and_screen_read_all_share_persisted_unread_projection(self):
        data=self.fresh()
        body='new 中文 \"quoted\" \\path\tpreview'
        for card in (0,1):
            receiver.ingest(data,card,'card'+str(card),[],1)
            receiver.ingest(data,card,'card'+str(card),sms_pdu.assemble([incoming(body,card+1)]),2)
        ids=[m['id'] for m in data['messages']]
        path=TOP/'openwrt/luci-app-t551m/root/usr/libexec/unisoc-modem/t551m-sms'
        loader=importlib.machinery.SourceFileLoader('sms_web',str(path))
        spec=importlib.util.spec_from_loader(loader.name,loader)
        web=importlib.util.module_from_spec(spec);loader.exec_module(web)
        def local_run(argv,timeout=30):
            if argv==[web.TOOL,'list']:return receiver.inbox()
            if argv[:2]==[web.RECEIVER,'read']:return receiver.mark_read(int(argv[2]))
            self.fail('Unexpected web operation: '+repr(argv))
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with patch.object(receiver,'DATA',root/'data'),patch.object(receiver,'RUN',root/'run'),patch.object(receiver,'INBOX',root/'data/inbox.json'),patch.object(receiver,'at') as modem,patch.object(web,'run',side_effect=local_run),patch.object(web,'hidden',return_value=set()):
                with receiver.locked():receiver.save(data)
                unread=root/'run/unread'
                self.assertEqual(len(unread.read_text().splitlines()),2)
                listed=web.main('list',{})
                self.assertEqual((listed['total'],listed['unread']),(2,2))
                self.assertEqual({m['card'] for m in listed['msgs']},{0,1})
                for message in listed['msgs']:
                    self.assertEqual(message['time'],'2026-10-05T19:02:58+08:00')
                    self.assertEqual(message['preview'],body)
                self.assertTrue(web.main('show',{'id':str(ids[0])})['ok'])
                self.assertEqual(unread.read_text(),f'/org/freedesktop/ModemManager1/SMS/{ids[1]}\n')
                self.assertEqual([m['unread'] for m in receiver.load()['messages']],[False,True])
                # The screen's existing read-all operation clears BOTH slots.
                self.assertTrue(receiver.mark_read()['ok'])
                self.assertEqual(unread.read_text(),'')
                self.assertFalse(any(m['unread'] for m in receiver.load()['messages']))
                modem.assert_not_called()

    def test_capacity_release_requires_durable_copy_and_matching_sim_and_pdu(self):
        ccid='89860012345678901234'; identity=hashlib.sha256(ccid.encode()).hexdigest()
        for failure in ['', 'archive', 'identity', 'index', 'inbox']:
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                root=Path(directory); (root/'run').mkdir(); commands=[]
                data=self.fresh(); message=sms_pdu.assemble([incoming('keep me',7)])
                receiver.ingest(data,1,identity,message,1)
                def fake(card, query):
                    self.assertEqual(card,1); commands.append(query)
                    if query=='CPMS?': return '+CPMS: "SM",40,40'
                    if query=='CCID?': return '+CCID: '+('89860099999999999999' if failure=='identity' else ccid)
                    if query=='CMGR=7': return '+CMGR: 0,,20\n'+ucs2('different' if failure=='index' else 'keep me')+'\nOK'
                    if query=='CMGD=7':
                        archive=list((root/'archive/1'/identity).glob('*.json'))
                        self.assertEqual(len(archive),1)
                        self.assertIn(ucs2('keep me'),archive[0].read_text())
                        self.assertEqual(receiver.load()['messages'][0]['text'],'keep me')
                        return 'OK'
                    self.fail(query)
                with patch.object(receiver,'DATA',root),patch.object(receiver,'RUN',root/'run'),patch.object(receiver,'INBOX',root/'inbox.json'),patch.object(receiver,'at',side_effect=fake):
                    receiver.save(data)
                    if failure=='archive':
                        with patch.object(receiver,'atomic',side_effect=OSError('full')):
                            with self.assertRaises(OSError): receiver.archive_capacity(data,1,identity)
                    elif failure=='inbox':
                        (root/'inbox.json').unlink()
                        with self.assertRaises(RuntimeError): receiver.archive_capacity(data,1,identity)
                    elif failure=='identity':
                        with self.assertRaises(RuntimeError): receiver.archive_capacity(data,1,identity)
                    else: receiver.archive_capacity(data,1,identity)
                    self.assertEqual([q for q in commands if q.startswith('CMGD')], [] if failure else ['CMGD=7'])
                    if not failure: self.assertTrue(receiver.load()['messages'][0]['archived'])

    def test_partial_archive_rescan_preserves_complete_multipart_message(self):
        data=self.fresh(); one=incoming('one',1,55,1); two=incoming('two',2,55,2)
        receiver.ingest(data,0,'card0',sms_pdu.assemble([one,two]),1)
        data['messages'][0]['archived_parts']=[two['fingerprint']]
        receiver.ingest(data,0,'card0',sms_pdu.assemble([one]),2)
        self.assertEqual(data['messages'][0]['text'],'onetwo')
        self.assertEqual(data['messages'][0]['state'],'received')
        self.assertEqual(len(data['messages'][0]['parts']),2)

    def test_secondary_notification_on_primary_ring_wakes_both_cards(self):
        events=receiver.Events();events.path='fixture';events.fd=55;events.sequence=1
        with patch.object(receiver.glob,'glob',return_value=['fixture']),patch.object(receiver.select,'poll'),patch.object(receiver.os,'lseek'),patch.object(receiver.os,'read',return_value=b'1 0 SM 3\n2 0 SM 1\n'):
            self.assertEqual(events.wait(2),{0,1})
            self.assertEqual(events.sequence,2)

    def test_old_messages_silent_then_each_card_alerts_once(self):
        data=self.fresh();old=sms_pdu.assemble([incoming('old')])
        for card in [0,1]:
            self.assertEqual(receiver.ingest(data,card,'identity-'+str(card),old,1),([],[]))
        new=sms_pdu.assemble([incoming('new',2)])
        ids=[]
        for card in [0,1]:
            alerts,forwards=receiver.ingest(data,card,'identity-'+str(card),new,2)
            self.assertEqual(len(alerts),1);self.assertEqual(alerts,forwards);ids+=alerts
            self.assertEqual(receiver.ingest(data,card,'identity-'+str(card),new,3),([],[]))
        self.assertNotEqual(*ids)
        self.assertEqual([m['sim'] for m in data['messages'] if m['id'] in ids],['SIM1','SIM2'])

    def test_restart_keeps_ids_and_does_not_forward_again(self):
        data=self.fresh();receiver.ingest(data,1,'card2',[],1)
        receiver.ingest(data,1,'card2',sms_pdu.assemble([incoming('fixture')]),2)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with patch.object(receiver,'DATA',root/'data'),patch.object(receiver,'RUN',root/'run'),patch.object(receiver,'INBOX',root/'data/inbox.json'):
                with receiver.locked():receiver.save(data)
                restored=receiver.load()
                self.assertEqual(receiver.ingest(restored,1,'card2',sms_pdu.assemble([incoming('fixture')]),3),([],[]))
                self.assertEqual(restored['messages'][0]['id'],data['messages'][0]['id'])
                self.assertTrue((root/'run/unread').read_text().endswith(str(data['messages'][0]['id'])+'\n'))

    def test_multipart_allocates_id_and_alerts_only_when_complete(self):
        data=self.fresh();receiver.ingest(data,1,'card2',[],1)
        two=incoming('尾部',2,8,2);one=incoming('头部',1,8,1)
        alerts,forwards=receiver.ingest(data,1,'card2',sms_pdu.assemble([two]),2)
        self.assertEqual(data['messages'],[]);self.assertEqual((alerts,forwards),([],[]))
        identifier=data['next_id']
        alerts,forwards=receiver.ingest(data,1,'card2',sms_pdu.assemble([two,one]),3)
        self.assertEqual(data['messages'][0]['id'],identifier)
        self.assertEqual(forwards,[identifier]);self.assertEqual(data['messages'][0]['text'],'头部尾部')

    def test_sim_replacement_does_not_relabel_old_messages(self):
        data=self.fresh()
        receiver.ingest(data,0,'oldcard',sms_pdu.assemble([incoming('old')]),1)
        receiver.ingest(data,0,'newcard',sms_pdu.assemble([incoming('new')]),2)
        self.assertEqual(len(data['messages']),2)
        self.assertEqual(data['messages'][0]['identity'],'oldcard')
        self.assertTrue(all(m['historical'] for m in data['messages']))

    def test_scan_restores_selected_card_and_uses_modemmanager_owner(self):
        data=self.fresh();commands=[]
        def fake(card,query):
            commands.append((card,query))
            if query=='CCID?':return '+CCID: "89860012345678901234"'
            if query=='CNMI?':return '+CNMI: 0,0,0,1,0'
            if query=='CMGF?':return '+CMGF: 0'
            if query=='CMGL=4':return '+CMGL: 1,0,,10\n\n'+ucs2('模拟内容')+'\n'
            return 'OK'
        with tempfile.TemporaryDirectory() as directory,patch.object(receiver,'RUN',Path(directory)),patch.object(receiver,'load',return_value=data),patch.object(receiver,'save'),patch.object(receiver,'alert'),patch.object(receiver,'forward'),patch.object(receiver,'execute',return_value='No calls were found'),patch.object(receiver,'current_card',return_value=0),patch.object(receiver,'at',side_effect=fake):
            receiver.scan({1})
        self.assertIn((1,'CNMI=2,1,0,0,0'),commands)
        self.assertEqual(commands[-1],(0,'CFUN?'))
        self.assertEqual(data['messages'][0]['card'],1)

    def test_reused_storage_index_and_replaced_sim_are_never_deleted(self):
        data=self.fresh()
        receiver.ingest(data,1,'original',sms_pdu.assemble([incoming('original')]),1)
        identifier=data['messages'][0]['id']
        with patch.object(receiver,'load',return_value=data),patch.object(receiver,'at') as modem,patch.object(receiver,'save') as save,patch.object(receiver,'current_card',return_value=0):
            for identity in ['replacement','original']:
                with patch.object(receiver,'read_card',return_value=(identity,sms_pdu.assemble([incoming('another')]))):
                    with self.assertRaises(RuntimeError):receiver.delete_locked(identifier)
            self.assertFalse(any('CMGD=' in args[1] for args,kwargs in modem.call_args_list))
            save.assert_not_called()
            self.assertFalse(data['messages'][0].get('deleted',False))

    def test_delete_only_matching_parts_then_restores_context(self):
        data=self.fresh();live=sms_pdu.assemble([incoming('original',7)])
        receiver.ingest(data,1,'original',live,1)
        with patch.object(receiver,'load',return_value=data),patch.object(receiver,'read_card',return_value=('original',live)),patch.object(receiver,'at') as modem,patch.object(receiver,'save'),patch.object(receiver,'current_card',return_value=0):
            self.assertTrue(receiver.delete_locked(data['messages'][0]['id'])['ok'])
            self.assertEqual(modem.call_args_list[0].args,(1,'CMGD=7'))
            self.assertEqual(modem.call_args_list[-1].args,(0,'CFUN?'))

    def test_one_absent_card_does_not_block_other_inbox(self):
        data=self.fresh()
        def read(card,own):
            if card==0:raise RuntimeError('SIM identity unavailable')
            return 'card2',sms_pdu.assemble([incoming('fixture')])
        with tempfile.TemporaryDirectory() as directory,patch.object(receiver,'RUN',Path(directory)),patch.object(receiver,'load',return_value=data),patch.object(receiver,'save'),patch.object(receiver,'alert'),patch.object(receiver,'forward'),patch.object(receiver,'execute',return_value='No calls were found'),patch.object(receiver,'current_card',return_value=0),patch.object(receiver,'at',return_value='OK'),patch.object(receiver,'read_card',side_effect=read):
            receiver.scan({0,1})
        self.assertFalse(data['slots']['0']['ok']);self.assertTrue(data['slots']['1']['ok'])
        self.assertEqual(data['messages'][0]['sim'],'SIM2')

    def test_sending_lock_defers_scan(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(receiver,'RUN',Path(directory)),patch.object(receiver,'scan_locked') as scan:
            with receiver.modem_locked() as acquired:
                self.assertTrue(acquired);receiver.scan({0,1})
            scan.assert_not_called()
            receiver.scan({0,1});scan.assert_called_once()

    def test_cleanup_failure_does_not_drop_committed_sms_alert_or_forward(self):
        data=self.fresh();receiver.ingest(data,1,'card2',[],1)
        messages=sms_pdu.assemble([incoming('new message')])
        with tempfile.TemporaryDirectory() as directory,patch.object(receiver,'RUN',Path(directory)),patch.object(receiver,'load',return_value=data),patch.object(receiver,'save') as save,patch.object(receiver,'alert') as alert,patch.object(receiver,'forward') as forward,patch.object(receiver,'execute',return_value='No calls were found'),patch.object(receiver,'current_card',return_value=0),patch.object(receiver,'read_card',return_value=('card2',messages)),patch.object(receiver,'archive_capacity'),patch.object(receiver,'at',side_effect=RuntimeError('owner temporarily unavailable')),self.assertLogs(level='WARNING'):
            receiver.scan({1})
        identifier=data['messages'][0]['id']
        self.assertTrue(data['messages'][0]['unread']);self.assertTrue(save.called)
        alert.assert_called_once_with([identifier],data);forward.assert_called_once_with([identifier])

    def test_successful_delete_stays_successful_when_context_cleanup_fails(self):
        data=self.fresh();live=sms_pdu.assemble([incoming('delete fixture',7)])
        receiver.ingest(data,1,'original',live,1)
        def at(card,command):
            if command=='CFUN?':raise RuntimeError('owner temporarily unavailable')
            self.assertEqual((card,command),(1,'CMGD=7'));return 'OK'
        with patch.object(receiver,'load',return_value=data),patch.object(receiver,'read_card',return_value=('original',live)),patch.object(receiver,'at',side_effect=at),patch.object(receiver,'save'),patch.object(receiver,'current_card',return_value=0),self.assertLogs(level='WARNING'):
            self.assertTrue(receiver.delete_locked(data['messages'][0]['id'])['ok'])
        self.assertTrue(data['messages'][0]['deleted'])


if __name__=='__main__':unittest.main()
