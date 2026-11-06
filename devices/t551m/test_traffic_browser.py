"""Shared traffic UI checks with mocked RPC/HTTP; never clears device records."""
import argparse,json,threading
from functools import partial
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
from playwright.sync_api import sync_playwright

TOP=Path(__file__).resolve().parents[2]
def usage(slot):
    n=(slot+1)*1000
    return {'slot':slot,'available':True,'interface_available':False,'today_used':n,'month_used':n*2,
            'today':{'rx':n,'tx':300},'month':{'rx':n*2,'tx':600},'days':[{'date':'10-10','rx':n,'tx':300}],
            'session':{'rx':n*3,'tx':900},'since':1791504000}
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--webroot',type=Path,required=True);ap.add_argument('--fixtures',type=Path,required=True);args=ap.parse_args()
    fixtures=json.loads(args.fixtures.read_text(encoding='utf-8'))
    fixtures['/api/status']['screen'].update(idle=0,lock_enabled=False)
    fixtures['/api/status']['modem']['sim_card']=0
    posts=[]
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            parsed=urlsplit(self.path)
            if not parsed.path.startswith('/api/'):return super().do_GET()
            if parsed.path=='/api/traffic':data=usage(int(parse_qs(parsed.query).get('slot',['0'])[0]))
            else:data=fixtures.get(parsed.path,{})
            self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(json.dumps(data).encode())
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))) or '{}');posts.append((self.path,body))
            self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(b'{"ok":true}')
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=str(args.webroot)))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe')
        page=browser.new_page(viewport={'width':320,'height':480},has_touch=True)
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(f'http://127.0.0.1:{server.server_port}/');page.wait_for_function("typeof last!=='undefined'&&last!==null")
        page.evaluate('showPage(P.traffic)');page.wait_for_function("document.querySelector('#tf-day-used').textContent==='1 KB'")
        assert '历史记录' in page.locator('#tf-state').inner_text()
        page.wait_for_timeout(600)  # Let the initial wake touch guard expire.
        assert page.locator('#tf-slot').is_hidden(), 'Native popup must not be reachable'
        page.locator('#tf-slot-button').click()
        assert page.locator('#tf-slot-options').is_visible()
        assert page.locator('#tf-slot-options [aria-selected=true]').inner_text()=='跟随数据卡'
        page.evaluate('T551M.status(last)')
        assert page.locator('#tf-slot-options').is_visible(), 'Polling closed the picker'
        page.keyboard.press('Escape')
        assert page.locator('#tf-slot-options').is_hidden()
        assert page.locator('#tf-slot-button').evaluate('(e)=>e===document.activeElement')
        for theme in ['dark','light']:
            page.evaluate("theme=>{last.screen.ui_theme=theme;last.screen.ui_size='large';T551M.status(last)}",theme)
            page.locator('#tf-slot-button').click()
            page.wait_for_timeout(200)  # Inspect the settled opening animation.
            box=page.locator('#tf-slot-options').bounding_box()
            assert box['x']>=0 and box['x']+box['width']<=320 and box['y']+box['height']<=480
            page.screenshot(path=str(TOP/f'logs/t551m/traffic-picker-{theme}.png'))
            page.locator('#mobile-title').click()
            assert page.locator('#tf-slot-options').is_hidden()
        page.locator('#tf-slot-button').click()
        page.locator('#tf-slot-options [data-value="1"]').click()
        page.wait_for_function("document.querySelector('#tf-day-used').textContent==='2 KB'")
        assert page.locator('#tf-slot-button').inner_text()=='SIM 2'
        assert page.locator('#tf-slot-options').is_hidden()
        assert page.locator('#tf-boot-rx').inner_text()=='6 KB'
        assert not any('sim' in path for path,_ in posts),'View selector switched real SIM'
        page.screenshot(path=str(TOP/'logs/t551m/traffic-screen.png'))
        page.evaluate('''()=>{
            clearInterval(advTimer);window.pending=[];const original=window.fetch;
            window.fetch=(url,options)=>String(url).startsWith('/api/traffic') ? new Promise(resolve=>pending.push({url,resolve})) : original(url,options);
            document.querySelector('#tf-slot').value='0';loadTraffic();
            document.querySelector('#tf-slot').value='1';loadTraffic();
        }''')
        page.evaluate('u=>pending[1].resolve(new Response(JSON.stringify(u)))',usage(1))
        page.wait_for_function("document.querySelector('#tf-day-used').textContent==='2 KB'")
        page.evaluate('u=>pending[0].resolve(new Response(JSON.stringify(u)))',usage(0))
        page.wait_for_timeout(100);assert page.locator('#tf-day-used').inner_text()=='2 KB'
        page.evaluate('loadTraffic();void 0')
        page.evaluate("pending[2].resolve(new Response('{}',{status:503}))")
        page.wait_for_function("document.querySelector('#tf-day-rx').textContent==='—'")
        assert page.locator('#tf-days').inner_text()==''
        assert '暂不可用' in page.locator('#tf-state').inner_text()
        # Lock reads follow the data SIM, never the history selector; stale
        # replies during a data-SIM change cannot overwrite the new readings.
        page.evaluate("last.screen.lock_enabled=true;T551M.status(last);T551M.power(true);T551M.power(false)")
        page.wait_for_function('pending.length>=4')
        page.evaluate('last.modem.sim_card=1;T551M.status(last)')
        page.evaluate('u=>pending[3].resolve(new Response(JSON.stringify(u)))',usage(0))
        page.wait_for_function('pending.length>=5')
        assert '2' not in page.locator('#lock-day-value').inner_text()
        page.evaluate('u=>pending[4].resolve(new Response(JSON.stringify(u)))',usage(1))
        page.wait_for_function("document.querySelector('#lock-day-value').textContent.includes('2')")
        assert 'slot=1' in page.evaluate('pending[4].url')
        assert not errors,errors

        web=browser.new_page(viewport={'width':390,'height':844})
        web.set_content('<html lang="zh"><style>*{box-sizing:border-box}body{margin:12px}.mud-card{padding:12px;border:1px solid #ddd}</style></html>')
        source=(TOP/'openwrt/luci-app-t551m/htdocs/luci-static/resources/view/mu300/traffic.js').read_text(encoding='utf-8')
        web.evaluate('''source=>{
            window.calls=[];window.messages=[];window.scope='0';window.fail=false;
            window.data={slot:0,config:{plan_name:'keep',monthly_gb:20},status:{available:true,clock_ok:true,today_used:1000,month_used:2000},days:[],months:[]};
            const M={injectCss(){},localizeMenu(){},localize(){},simSelector(){},translate:s=>s,fmtTrafficBytes:n=>n==null?'--':String(n),esc:s=>s,simSlot:()=>scope,
                callTrafficGet:slot=>Promise.resolve({...data,slot:Number(slot??scope)}),callTrafficSet:()=>Promise.resolve({ok:1}),
                callTrafficClear:(slot,confirm)=>{calls.push({slot,confirm});return Promise.resolve(fail?{ok:0,error:'storage_failed'}:{ok:1});},
                confirmBox:(title,note)=>{window.confirmTitle=title;return new Promise(resolve=>window.answer=resolve);},
                busy:(el,value)=>el.disabled=value,toast:()=>({update:(s,type)=>messages.push({s,type}),close(){}})};
            const view=new Function('view','poll','M','L',source)({extend:v=>v},{add(){}},M,{resolveDefault:(p,d)=>p.catch(()=>d)});
            document.body.append(view.render(data));
        }''',source)
        web.locator('#mud-tr-clear').click();assert 'SIM 1' in web.evaluate('confirmTitle')
        web.evaluate('answer(false)');web.wait_for_timeout(50);assert web.evaluate('calls.length')==0
        web.locator('#mud-tr-clear').click();web.evaluate("scope='1';answer(true)")
        web.wait_for_function('calls.length===1&&!document.querySelector("#mud-tr-clear").disabled')
        assert web.evaluate('calls[0]')=={'slot':'0','confirm':True}
        assert web.locator('#mud-tr-plan_name').input_value()=='keep'
        web.evaluate('fail=true');web.locator('#mud-tr-clear').click();web.evaluate('answer(true)')
        web.wait_for_function('messages.some(m=>m.type==="error")')
        assert web.evaluate('messages.at(-1).s')=='统计数据保存失败'
        assert web.evaluate('document.documentElement.scrollWidth<=innerWidth')
        web.screenshot(path=str(TOP/'logs/t551m/traffic-web-mobile.png'),full_page=True)
        browser.close();server.shutdown()
    print('PASS: offline history/count mode, per-SIM view, stale reply/failure clearing, lock SIM change, web confirmation/cancel/immutable scope/error, responsive layout')
if __name__=='__main__':main()
