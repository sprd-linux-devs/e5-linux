"""Device page policy/attachment distinction and adapter controls in Chromium."""
from pathlib import Path
from playwright.sync_api import sync_playwright

source = (Path(__file__).resolve().parents[2] / 'openwrt/luci-app-t551m/htdocs/luci-static/resources/view/mu300/device.js').read_text(encoding='utf-8')
with sync_playwright() as p:
    chrome = Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
    browser = p.chromium.launch(**({'executable_path': str(chrome)} if chrome.exists() else {}))
    page = browser.new_page(viewport={'width': 390, 'height': 844})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.set_content('<style>*{box-sizing:border-box}body{margin:12px}.mud-card{padding:14px}.mud-note{font-size:12px;line-height:1.5;margin:12px 0}.mud-btn{padding:8px;font-size:12px}.mud-r{display:flex;justify-content:space-between}</style>')
    page.evaluate('''() => {
        window.fixture = { ok:1, role:'device', policy:'auto', role_auto:0, host_supported:1,
            net_available:0, lan_auto:1, pending:0 };
        window.devices=[{name:'eth1',driver:'r8152',mac:'02:11:22:33:44:55',carrier:1,in_lan:1,bound:1},
            {name:'eth2',driver:'cdc_ncm',carrier:1,in_lan:0,bound:0,managed_elsewhere:1}];
        window.calls=[];window.messages=[];
        window.Charge={mount(){}};window.NetworkPerformance={mount:()=>({dispose(){}})};
        window.L={resolveDefault:(promise,fallback)=>promise.catch(()=>fallback)};
        window.M={ injectCss(){},localizeMenu(){},localize(){},translate:s=>s,
            busy:(button,on)=>{button.disabled=on},confirmBox:()=>Promise.resolve(true),
            toast:text=>{messages.push(text);return {update:text=>messages.push(text),close(){}}},
            callUsbGet:()=>Promise.resolve({...fixture}),
            callUsbNetList:()=>Promise.resolve({ok:1,devices}),
            callUsbSet:(kind,value,scope,auto)=>{
                calls.push({kind,value,scope,auto});
                if(kind==='role'){fixture.policy=value;fixture.role_auto=+auto;}
                if(kind==='lan')fixture.lan_auto=+value;
                if(kind==='net'){fixture.net_mode=value;fixture.net_scope=scope;fixture.net_auto=+auto;}
                return Promise.resolve({ok:1,pending:kind==='role'?1:0});
            }
        };
    }''')
    page.evaluate('(source)=>{window.screenView=new Function("view","M",source)({extend:x=>x},M);document.body.appendChild(screenView.render(fixture));}', source)
    page.wait_for_selector('.mud-device-item')
    assert page.locator('#mud-usb-role').input_value() == 'auto'
    assert page.locator('#mud-usb-role-now').inner_text() == '设备模式'
    for link, expected in (({'state':'connected','links':[{'mbps':480}]},'480 Mbit/s'),
                           ({'state':'connected','links':[{'mbps':5000},{'mbps':480}]},'5 Gbit/s · 480 Mbit/s'),
                           ({'state':'disconnected','links':[]},'链路未连接'),
                           ({'state':'unavailable','links':[]},'未能确认')):
        page.evaluate('(link)=>{fixture.usb_link=link;screenView.state=fixture;screenView.paint();}',link)
        assert page.locator('#mud-usb-link-speed').inner_text() == expected
    assert page.locator('#mud-usb-role option[value="host-sink"]').count() == 0
    assert not page.locator('#mud-usb-role-apply').is_disabled()
    assert page.locator('#mud-usb-net-apply').is_disabled()
    assert page.locator('.mud-device-item .mud-btn').all_text_contents() == ['已加入 LAN', '已分配其他网络']
    page.locator('#mud-usb-role').select_option('host')
    page.locator('#mud-usb-role-apply').click()
    page.wait_for_function('messages.includes("USB 角色已应用")')
    assert page.locator('#mud-usb-role').input_value() == 'host'
    assert page.locator('#mud-usb-role-now').inner_text() == '设备模式', 'Policy acknowledgement is not fake host attachment'
    page.locator('#mud-usb-lan-auto').uncheck()
    page.wait_for_function('calls.some(c=>c.kind==="lan"&&c.value==="0")')
    page.evaluate("fixture.last_error='测试失败';fixture.policy='auto';fixture.role='none';screenView.reloadState()")
    page.wait_for_function('document.querySelector("#mud-usb-role-note").textContent==="测试失败"')
    assert page.locator('#mud-usb-role-now').inner_text() == '未连接'
    page.evaluate("Object.assign(fixture,{last_error:'',role_supported:['auto','device','host','host-sink']});screenView.reloadState()")
    page.wait_for_selector('#mud-usb-role option[value="host-sink"]',state='attached')
    page.locator('#mud-usb-role').select_option('host-sink')
    assert page.locator('#mud-usb-role-auto').is_disabled()
    assert '不进行 PD' in page.locator('#mud-usb-role-note').inner_text()
    page.locator('#mud-usb-role-apply').click()
    page.wait_for_function('calls.some(c=>c.kind==="role"&&c.value==="host-sink"&&c.auto==="0")')
    page.locator('#mud-usb-role').select_option('auto')
    assert '不进行 PD' not in page.locator('#mud-usb-role-note').inner_text()
    page.evaluate("Object.assign(fixture,{net_available:1,net_current:'ncm',net_mode:'ncm',net_supported:['ncm','ecm','rndis'],role:'host'});screenView.reloadState()")
    page.wait_for_function('!document.querySelector("#mud-usb-net-apply").disabled')
    page.locator('#mud-usb-net-mode').select_option('rndis')
    page.locator('#mud-usb-net-scope').select_option('once')
    page.locator('#mud-usb-net-apply').click()
    page.wait_for_function('calls.some(c=>c.kind==="net"&&c.value==="rndis"&&c.scope==="once"&&c.auto==="1")')
    assert page.locator('#mud-usb-net-current').inner_text() == 'NCM', 'Saving is not a live protocol change'
    for width in (390, 1280):
        page.set_viewport_size({'width':width, 'height':844})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), width
    assert not errors, errors
    browser.close()
print('PASS: mobile/desktop layout, actual role vs policy, async acknowledgement, error and LAN controls')
