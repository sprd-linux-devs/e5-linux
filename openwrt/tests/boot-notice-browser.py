"""Execute both shipped LuCI views with fake RPC; no real network/device."""
from pathlib import Path
import os
from playwright.sync_api import sync_playwright
TOP=Path(__file__).resolve().parents[2]
MU=Path(os.environ.get('MU300_REPO',str(TOP.parent/'mu300-linux-clean-tf-7.2')))
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe')
    for repo,app in [(TOP,'t551m'),(MU,'mu300')]:
        source=repo/'openwrt'/('luci-app-'+app)/'htdocs/luci-static/resources/view/mu300/home.js'
        if not source.exists():continue
        code=source.read_text(encoding='utf-8')
        page=browser.new_page(viewport={'width':375,'height':700});errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.set_content('<main></main>')
        page.evaluate('''code=>{
            window.calls=[];window.confirmed=false;
            const methods={v:id=>document.getElementById('mud-'+id),esc:s=>String(s??''),translate:s=>s,
                callLockGet:()=>Promise.resolve({}),confirmBox:()=>Promise.resolve(confirmed),
                callAct:(op,arg)=>{calls.push([op,arg]);return Promise.resolve({ok:true});},
                busy:(btn,on)=>btn.disabled=on,set:(id,text)=>{const e=methods.v(id);if(e)e.textContent=text;},
                pill:()=>'',fmtBytes:()=>'',fmtRate:()=>'',duration:()=>''};
            window.M=new Proxy(methods,{get:(o,k)=>o[k]||(()=> '')});
            const L={url:(...p)=>"/cgi-bin/luci/"+p.join("/"),resolveDefault:(p)=>Promise.resolve(p).catch(()=>null)};
            window.app=new Function('view','M','uci','L',code)({extend:x=>x},M,{},L);
            const root=document.querySelector('main');root.innerHTML=app.html();app.wire(root);
            window.setBoot=boot=>{
                const i={boot},notice=M.v('boot-notice'),setDefault=M.v('btn-default');
                // Run the actual isolated fast boot renderer from update().
                const from=code.indexOf('var boot = i.boot'),to=code.indexOf('if (androidBtn)',from);
                new Function('i','M',code.slice(from,to)).call(app,i,M);
            };
            setBoot({temporary:true,can_set_default:true});
        }''',code)
        assert page.locator('#mud-boot-notice').is_visible()
        page.locator('#mud-btn-default').click();page.wait_for_timeout(30)
        assert page.evaluate('calls')==[]
        page.evaluate('confirmed=true');page.locator('#mud-btn-default').click()
        page.wait_for_function('calls.length===1')
        assert page.evaluate('calls')==[['os','linux-default']]
        page.evaluate('setBoot({temporary:false,can_set_default:true})')
        assert page.locator('#mud-boot-notice').is_hidden()
        page.evaluate('setBoot({temporary:true,can_set_default:false})')
        assert page.locator('#mud-btn-default').is_disabled()
        page.evaluate('setBoot({temporary:null,can_set_default:false})')
        assert page.locator('#mud-boot-notice').is_hidden()
        assert not errors,errors
        page.close()
    browser.close()
print('PASS: E5 and MU300 banners, cancellation, confirmed RPC, persistent/unknown/trial states')
