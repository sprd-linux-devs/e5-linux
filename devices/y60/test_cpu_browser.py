"""Execute the real shared CPU view and translations without any device RPC."""
from pathlib import Path
import runpy

TOP = Path(__file__).resolve().parents[2]


def main():
    from playwright.sync_api import sync_playwright
    state = runpy.run_path(str(TOP/'devices/t551m/test_cpu_browser.py'))['STATE']
    source = (TOP/'openwrt/luci-app-t551m/htdocs/luci-static/resources/view/mu300/cpu.js').read_text(encoding='utf-8')
    common = (TOP/'openwrt/luci-app-t551m/htdocs/luci-static/resources/mu300/common.js').read_text(encoding='utf-8')
    with sync_playwright() as pw:
        chrome = Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
        browser = pw.chromium.launch(**({'executable_path':str(chrome)} if chrome.exists() else {}))
        try:
            page = browser.new_page(viewport={'width':320, 'height':480})
            errors = []
            page.on('pageerror', lambda error:errors.append(str(error)))
            page.set_content('<html lang="zh"><body></body></html>')
            page.evaluate('''([source,common,state])=>{
                window.L={env:{lang:'zh'}};
                const rpc={declare:()=>()=>Promise.resolve(state)};
                const M=new Function('rpc','baseclass',common)(rpc,{extend:x=>x});
                M.localizeMenu=()=>{};
                const cores={render:()=>document.createElement('div')};
                window.cpu=new Function('view','rpc','poll','ui','M','Cores','Idle',source)(
                    {extend:x=>x},rpc,{add:()=>{}},{addNotification:()=>{}},M,cores,cores);
                window.state=state;
                document.body.append(cpu.render(state));
            }''', [source, common, state])
            assert page.locator('[data-setting$="_voltage_next"]').count()==3
            reasons = {
                'CPU voltage adjustment is not supported on this SoC':
                    ('当前芯片尚未适配电压调整','CPU voltage adjustment is not supported','Bu çipte CPU voltaj ayarı desteklenmiyor'),
                'CPU voltage interface is missing from this kernel':
                    ('当前内核缺少 CPU 调压接口','CPU voltage interface is missing','Bu çekirdekte CPU voltaj arayüzü eksik'),
                'SML partitions are not ready; refresh after initialization':
                    ('SML 分区尚未就绪','SML partitions are not ready','SML bölümleri hazır değil'),
                'SML partitions could not be read; refresh and check storage':
                    ('无法读取 SML 分区','SML partitions could not be read','SML bölümleri okunamadı'),
                'SML voltage ABI could not be established':
                    ('尚未匹配到本机 SML 的调压协议','SML voltage ABI could not be established',"Bu SML'nin voltaj protokolü doğrulanamadı"),
                'SML compatibility checker is not ready; refresh after installation':
                    ('SML 兼容性检查组件尚未就绪','SML compatibility checker is not ready','SML uyumluluk denetleyicisi hazır değil'),
            }
            for reason, expected in reasons.items():
                for lang, text in zip(('zh','en','tr'),expected):
                    page.evaluate('''([reason,lang])=>{
                        L.env.lang=lang;document.documentElement.lang=lang;
                        state.voltage_unavailable_reason=reason;
                        state.policies.forEach(p=>p.voltage_boot_writable=false);
                        cpu.paint(state);
                    }''',[reason,lang])
                    assert text in page.inner_text('body'), (reason,lang)
                    assert page.locator('[data-setting$="_voltage_next"]').count()==0
            page.evaluate('''()=>{
                state.voltage_unavailable_reason=null;
                state.policies.forEach(p=>p.voltage_boot_writable=true);
                cpu.paint(state);
            }''')
            assert page.locator('[data-setting$="_voltage_next"]').count()==3
            assert not errors, errors
        finally:
            browser.close()
    print('PASS: real CPU view, all three domains, platform/driver reasons, zh/en/tr, refresh restores controls')


if __name__=='__main__':
    main()
