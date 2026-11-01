"""Real shell + Phone + SDK, fake HTTP calls; never reaches a modem/device."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import runpy
import shutil
import tempfile
import threading
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright

TOP=Path(__file__).resolve().parents[2]
SCREEN=TOP/'devices/common/infoscreen'


def main():
    state={'time':1700000000,'uptime':20,'screen':{'awake':True,'brightness':150,'idle':0,
        'lock_enabled':False,'touch':True,'donate_seen':True,'lang':'zh'},
        'battery':{'capacity':60,'online':False,'status':'Discharging'},'modem':{},
        'wan':{'up':False},'wifi':{'enabled':False},'clients':[],'system':{},
        'traffic':{'rx_rate':0,'tx_rate':0},'sms':{'unread':[]},'notifications':[]}
    live={'calls':[],'contacts':[],'sim':{'card':0},'wake':True,
          'audio':{'available':True,'active':True,'speaker':False,'muted':False}}
    posts=[];errors=[]
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self,*args):pass
        def reply(self,data):
            self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
            try:self.wfile.write(json.dumps(data).encode())
            except (BrokenPipeError,ConnectionError):pass
        def do_GET(self):
            path=urlsplit(self.path).path
            if path=='/api/status':return self.reply(state)
            if path in ('/api/plugins/phone/live','/api/plugins/phone/status'):return self.reply(live)
            if path=='/api/plugins':return self.reply({'plugins':[{'id':'phone','name':'Phone','entry':'index.html'}]})
            if path.startswith('/api/'):return self.reply({})
            return super().do_GET()
        def do_POST(self):
            path=urlsplit(self.path).path
            body=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))) or '{}')
            posts.append((path,body))
            if path.endswith('/answer'):live['calls']=[{**live['calls'][0],'state':'active'}]
            if path.endswith('/call'):
                live['calls']=[{'id':'20','state':'dialing','direction':'outgoing','number':body['number'],'card':0}]
                return self.reply({'ok':True,'id':'20'})
            if path.endswith('/hangup'):live['calls']=[]
            if path=='/api/backlight':state['screen']['awake']=body['level']>0
            return self.reply({'ok':True})
    with tempfile.TemporaryDirectory(prefix='phone-keys-') as temporary:
        root=Path(temporary)
        for name,text in runpy.run_path(str(SCREEN/'stage.py'))['sources']().items():
            if name.startswith('www/'):
                path=root/name[4:];path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text,encoding='utf-8')
        shutil.copytree(SCREEN/'phone',root/'plugins/phone')
        server=ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=str(root)))
        threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            with sync_playwright() as pw:
                chrome=Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
                browser=pw.chromium.launch(**({'executable_path':str(chrome)} if chrome.exists() else {}))
                page=browser.new_page(viewport={'width':320,'height':480},has_touch=True)
                page.add_init_script('window.EventSource=undefined')
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(f'http://127.0.0.1:{server.server_port}/')
                page.wait_for_function('last && typeof T551MCalls!=="undefined" && !T551M.isLocked()')
                frame=page.frame_locator('#app-frame')
                def dispatch(target,key,repeat=False):
                    script='''([key,repeat])=>{for(const type of ['keydown','keyup'])
                        document.dispatchEvent(new KeyboardEvent(type,{key,repeat,bubbles:true,cancelable:true}));}'''
                    if target=='shell':page.evaluate(script,[key,repeat])
                    else:frame.locator('body').evaluate('(el,args)=>('+script+')(args)',[key,repeat])
                for number,(target,green,red,touch) in enumerate((
                        ('shell','F13','PowerOff',True),('frame','F13','PowerOff',False),
                        ('shell','Phone','HangupPhone',False),('frame','PickupPhone','PowerOff',True))):
                    state['screen'].update(lock_enabled=True,touch=touch)
                    page.evaluate('last.screen='+json.dumps(state['screen'])+';T551M.status(last);setBlank(true)')
                    call={'id':str(number+1),'state':'ringing-in','direction':'incoming','sim':'SIM1','card':0,'number':'12345'}
                    live['calls']=[call]
                    page.wait_for_function('T551MCalls.active() && !blank && appCapturePower')
                    frame.locator('#accept').wait_for(state='visible')
                    assert page.evaluate('T551M.isLocked()')
                    before=sum(p.endswith('/answer') for p,b in posts)
                    dispatch(target,green,True);page.wait_for_timeout(100)
                    assert sum(p.endswith('/answer') for p,b in posts)==before,'repeat answered a call'
                    dispatch(target,green)
                    frame.locator('#dtmf-toggle').wait_for(state='visible')
                    assert sum(p.endswith('/answer') for p,b in posts)==before+1,(target,green,posts)
                    assert page.evaluate('!blank && T551M.isLocked() && !T551MPower.isOpen()')
                    before=sum(p.endswith('/hangup') for p,b in posts)
                    dispatch(target,red)
                    page.wait_for_function('!T551MCalls.active()')
                    assert sum(p.endswith('/hangup') for p,b in posts)==before+1,(target,red,posts)
                    assert page.evaluate('!blank && T551M.isLocked() && !T551MPower.isOpen()')
                # A disabled incoming-call wake setting stays respected. The
                # first red wakes only; a second red rejects the visible call.
                live.update(wake=False,calls=[])
                page.evaluate('setBlank(true)')
                live['calls']=[{**call,'id':'10'}]
                page.wait_for_timeout(750)
                before=sum(p.endswith('/hangup') for p,b in posts)
                dispatch('shell','F13');page.wait_for_timeout(100)
                assert page.evaluate('blank && T551M.isLocked()')
                dispatch('shell','PowerOff')
                page.wait_for_function('T551MCalls.active() && !blank && appCapturePower')
                assert sum(p.endswith('/hangup') for p,b in posts)==before
                dispatch('shell','PowerOff');page.wait_for_function('!T551MCalls.active()')
                assert sum(p.endswith('/hangup') for p,b in posts)==before+1
                # The frame green key must reach the dialler too, rather than
                # being swallowed by the shell's "open Phone" shortcut.
                state['screen'].update(lock_enabled=False,touch=True)
                page.evaluate('last.screen='+json.dumps(state['screen'])+';T551M.status(last);openApp({id:"phone",name:"Phone",entry:"index.html"})')
                frame.locator('#dial').wait_for(state='visible')
                for digit in '12345':dispatch('frame',digit)
                before=sum(p.endswith('/call') for p,b in posts)
                dispatch('frame','F13')
                frame.locator('#call-card').wait_for(state='visible')
                page.wait_for_function('appCapturePower')
                assert sum(p.endswith('/call') for p,b in posts)==before+1
                dispatch('frame','PowerOff')
                frame.locator('#dial').wait_for(state='visible')
                page.wait_for_function('!appCapturePower')
                # Without a call, short red still toggles the display and long
                # red still opens the power menu; no stale capture leaks.
                before=sum(p.endswith('/hangup') for p,b in posts)
                dispatch('shell','PowerOff');page.wait_for_function('blank')
                dispatch('shell','PowerOff');page.wait_for_function('!blank')
                page.evaluate("document.dispatchEvent(new KeyboardEvent('keydown',{key:'PowerOff',bubbles:true,cancelable:true}))")
                page.wait_for_function('T551MPower.isOpen()')
                page.evaluate("document.dispatchEvent(new KeyboardEvent('keyup',{key:'PowerOff',bubbles:true,cancelable:true}))")
                assert sum(p.endswith('/hangup') for p,b in posts)==before
                assert not errors,errors
                browser.close()
                print('PASS: shell/frame answer and hangup, locked touch on/off, repeat suppression, dark wake-only, reject, dial, idle short/long power; no real calls')
        finally:server.shutdown()


if __name__=='__main__':main()
