"""Reproducible shared handheld adaptation of infoscreen 1.6.7 (see LICENSE/README)."""
from pathlib import Path
import json
import re

HERE = Path(__file__).resolve().parent


def scalable_css(text):
    # Keep physical page/gesture geometry. Scale all typography, including
    # upstream fixed-pixel fonts and shorthand declarations, through one setting.
    head, marker, tail = text.partition('/* Display size scales')
    head = re.sub(r'(font-size:\s*)([\d.]+)px', r'\1calc(\2px * var(--ui-scale, 1))', head)
    head = re.sub(r'(font:[^;{}]*?)([\d.]+)px', r'\1calc(\2px * var(--ui-scale, 1))', head)
    return head + marker + tail


def replace(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Expected one upstream anchor: ' + old[:100])
    return text.replace(old, new, 1)


def confirmation_rows(app):
    app = replace(app, '''function stDisarm() {
\tif (stArmed) clearTimeout(stArmed.timer);
\tstArmed = null;
}''', '''function stDisarm() {
\tif (stArmed) {
\t\tclearTimeout(stArmed.timer);
\t\tstArmed.el?.classList.remove('armed');
\t\tstArmed.el?.querySelector('.st-confirm-hint')?.remove();
\t}
\tstArmed = null;
}''')
    app = replace(app, "stArmed = { key, timer: setTimeout(() => { stDisarm(); stRender(); }, 3000) };",
                  "stArmed = { key, el, timer: setTimeout(() => { stDisarm(); stRender(); }, 3000) };")
    return replace(app, "\t\tconst sv = el.querySelector('.sv');\n\t\tif (sv) sv.textContent = t('press_again');", '''
\t\tconst hint = document.createElement('span');
\t\thint.className = 'st-confirm-hint';
\t\thint.setAttribute('aria-live', 'polite');
\t\thint.textContent = t('press_again');
\t\tel.appendChild(hint);''')


def sources():
    app = (HERE / 'base/app.js').read_text(encoding='utf-8')
    common = (HERE.parents[2] / 'openwrt/luci-app-t551m/htdocs/luci-static/resources/mu300/common.js').read_text(encoding='utf-8')
    start = common.index('/* BEGIN SHARED PLATFORM MESSAGES:')
    end = common.index('/* END SHARED PLATFORM MESSAGES */', start)
    app = replace(app, 'const I18N = {', common[start:end] + '\nconst I18N = {')
    app = confirmation_rows(app)
    app = replace(app, "f.src = `/plugins/${encodeURIComponent(m.id)}/${m.entry ?? 'index.html'}?lang=${lang}`;",
                  "f.src = `/plugins/${encodeURIComponent(m.id)}/${m.entry ?? 'index.html'}?lang=${lang}${m.callOverlay ? '&callonly=1' : ''}`;")
    app = replace(app, "\tconst send = (msg) => fromIme ? toIme(msg) : toApp(msg);", """
	if (fromApp && T551MCalls.active() && (m.e5 === 'exit' || m.e5 === 'input' || (m.e5 === 'key' && m.kind === 'menu'))) return;
	const send = (msg) => fromIme ? toIme(msg) : toApp(msg);""")
    app = replace(app, ' notificationList = list;', " list = list.filter(n => n.plugin !== 'phone' || !String(n.id).startsWith('call-'));\n notificationList = list;")
    app = replace(app, "appCapturePower && !blank && !locked",
                  "appCapturePower && !blank && (!locked || (appOpen?.id === 'phone' && T551MCalls.active()))")
    app = replace(app, "\tsetHTML('st-view', html);", "\tsetHTML('st-view', html);\n\tT551M.settings($('st-view'), v, stCats);")
    for direction in ['rx', 'tx']:
        app = replace(app, f'fmtRate(st.traffic.{direction}_rate)', f'T551M.speed(st.traffic.{direction}_rate)')
    app = replace(app, "x.view == 'atres' ? x.cmd :", "x.view == 'atres' ? (lang == 'zh' ? '执行结果' : 'Result') :")
    app = replace(app, "x.cat ? lbl(x.cat.label) : x.item ? lbl(x.item.label) :", "x.item ? lbl(x.item.label) : x.cat ? lbl(x.cat.label) :")
    app = replace(app, '<div class="card"><div class="sub">${esc(v.cmd)}</div>',
                  '<div class="card st-at-result"><div class="st-at-command">${esc(v.cmd)}</div>')
    app = replace(app, '<div class="smstext" style="margin-top:6px;font-size:13px">${esc(v.reply ?? t(\'at_running\'))}</div>',
                  '${v.reply == null ? \'\' : `<pre class="st-at-output">${esc(v.reply)}</pre>`}')
    app = replace(app, '<div class="card stnum">', '<div class="stnumber-editor"><div class="card stnum">')
    app = replace(app, '<div style="height:8px"></div><button class="strow" data-st="num:save"><span>${esc(t(\'save\'))}</span><span class="sv"></span></button>',
                  '<button class="strow" data-st="num:save"><span>${esc(t(\'save\'))}</span><span class="sv"></span></button></div>')
    app = replace(app, 'function openApp(m) {', 'let appReturnFocus = null;\nfunction openApp(m) {\n\tif (!appOpen) appReturnFocus = document.activeElement;')
    app = replace(app, '\tappOpen = m;', '\tappOpen = m;\n\tT551M.page(page);')
    app = replace(app, 'f.onload = () => { observeAppInputs(f); f.focus(); };',
                  'f.onload = () => { if (appOpen !== m || f.hidden) return; T551M.app(f, m); observeAppInputs(f); f.focus({preventScroll:true}); };')
    app = replace(app, "\tconst f = $('app-frame');\n\tf.hidden = true;", "\tconst f = $('app-frame');\n\tf.onload = null;\n\tf.hidden = true;")
    app = replace(app, "\tconst b = document.querySelector('[data-app]');\n\tif (b) b.focus();", "\tT551M.appClosed(appReturnFocus);\n\tappReturnFocus = null;")
    app = replace(app, '\tdoc.__e5InputObserver = true;', '\tdoc.__e5InputObserver = true;\n\tT551MPower.attach(frame.contentWindow);\n\tT551M.attachKeys(frame.contentWindow);\n\tT551MCalls.attach(frame);')
    app = replace(app, '\tif (!blank && idle > 0 && !(appOpen && appKeepAwake))', '\tif (!blank && idle > 0 && !T551MPower.isOpen() && !T551MCalls.active() && !(appOpen && appKeepAwake))')
    app = replace(app, 'function setBlank(on) {', 'let powerQueue = Promise.resolve(), powerChangedAt = -Infinity;\nfunction setBlank(on) {')
    app = replace(app, "\tblank = on;\n\tdocument.body.classList.toggle('blank', on);\n\tpost('backlight', { level: on ? 0 : brightness });", """
	blank = on;
	powerChangedAt = performance.now();
	T551M.power(on);
	applyTouch();
	document.body.classList.toggle('blank', on);
	const level = on ? 0 : brightness;
	powerQueue = powerQueue.catch(() => {}).then(() => post('backlight', { level })).then(r => {
		if (!r?.ok) throw new Error('screen power transition failed');
	}).catch(e => { console.log(e); toast(lang == 'zh' ? '屏幕状态同步失败，请按电源键重试' : 'Press power to retry'); });""")
    app = replace(app, 'function touchOff() { return locked || last?.screen?.touch === false; }',
                  'function touchOff() { return blank || (locked && !T551MCalls.active()) || last?.screen?.touch === false; }')
    app = replace(app, '\t\t\tlast = st;\n\t\t\tapplyTouch();', '''
			last = st;
			// Reconcile changes made outside the browser, without accepting a
			// stale status reply during a local power transition.
			if (typeof st.screen.awake == 'boolean' && st.screen.awake === blank && performance.now() - powerChangedAt > 1000) {
				blank = !st.screen.awake;
				T551M.power(blank);
				document.body.classList.toggle('blank', blank);
				tickClock();
				schedulePageRefresh();
				resetIdle();
			}
			T551M.status(st);
			stAPNSync(st);
			applyTouch();''')
    app = replace(app, "\tpage = (n + pages.length) % pages.length;", "\tpage = (n + pages.length) % pages.length;\n\tT551M.page(page);")
    app = replace(app, '\t\tif (!st.screen.donate_seen) donateOnce();', '\t\tif (!st.screen.donate_seen) post(\'donate-seen\');')
    app = replace(app, "\tif (r?.ok && v.cat.id == 'screen') stScreenApplied", "\tif (r?.ok && ['ui', 'navigation'].includes(v.cat.id)) {\n\t\tlast.screen[body.id] = r.item?.value ?? body.value;\n\t\tT551M.status(last);\n\t}\n\tif (r?.ok && v.cat.id == 'screen') stScreenApplied")
    app = replace(app, '\tshowPage(0);\n\tpoll();', '\tT551M.boot();\n\tT551MCalls.boot();\n\tshowPage(0);\n\tpoll();')
    # A wake notification may light the lock, but cannot expose the inbox.
    app = replace(app, "if (page != P.sms) showPage(P.sms);", "if (!T551M.isLocked() && page != P.sms) showPage(P.sms);")
    app = replace(app, "setText('bar-op', m.operator ??", "setText('bar-op', T551M.operator(m.operator) ??")
    app = replace(app, "[m.operator, m.registration", "[T551M.operator(m.operator), m.registration")
    start = app.index('async function loadAdvanced() {')
    end = app.index('\nfunction renderAdvanced', start)
    app = app[:start] + '''let advancedBusy = false, advancedRetry = null;
async function loadAdvanced() {
	if (adv) renderAdvanced(adv);
	if (advancedBusy) return;
	advancedBusy = true;
	clearTimeout(advancedRetry);
	try {
		adv = await pageRead('/api/advanced', P.adv_info);
		pageLoadPending(P.adv_info, adv?.radio_pending);
	} catch (e) {
		pageLoadPending(P.adv_info, false);
		console.log('advanced: ' + e);
	}
	finally { advancedBusy = false; }
	if (adv) renderAdvanced(adv);
	if (adv?.radio_pending && page === P.adv_info && !blank)
		advancedRetry = setTimeout(() => { if (page === P.adv_info && !blank) loadAdvanced(); }, 800);
}
''' + app[end:]
    app = replace(app, "const bands = (list, pre) => list?.length ?", "const bands = (list, pre) => list == null ? '--' : list.length ?")
    app = replace(app, "setText('ad-cell', b ?", "setText('ad-cell', b && b.lte_cell_lock != null && b.nr_cell_lock != null ?")
    app = replace(app, "\tconst d = a.device ?? {}, b = a.baseband, s = a.sim;", '''
	const d = a.device ?? {}, b = a.baseband, s = a.sim;
	setText('ad-freshness', a.radio_error ? (lang == 'zh' ? '部分无线信息暂不可用' : 'Some radio details unavailable') : '');
	$('ad-freshness').hidden = !a.radio_error;''')
    api = (HERE / 'base/api.uc').read_text(encoding='utf-8')
    api = replace(api, 'function status() {', '''function boot_status() {
    let state = read_trim('/etc/e5linux/default-boot') ?? 'android';
    if (state != 'linux' && state != 'android') state = 'unknown';
    let trial = match(read_trim('/proc/cmdline') ?? '', /(^| )e5\\.openwrt=/) != null;
    let control = stat('/run/e5linux/misc-bc-slot-b-trial.bin') ?? stat('/etc/e5linux/misc-bc-slot-b-trial.bin');
    return { default: state, temporary: state == 'unknown' ? null : state != 'linux',
             can_set_default: !trial && control != null && stat('/opt/e5/e5-next-boot') != null };
}
function status() {''')
    api = replace(api, '\t\ttime: t,', '\t\ttime: t,\n\t\tboot: boot_status(),')
    api = replace(api, 'function status() {', (HERE / 'sims.uc').read_text(encoding='utf-8') + '\nfunction status() {')
    api = replace(api, '\tlet m = modem_status();\n\treturn {', '\tlet sims = sim_status();\n\tlet m = card_modem(modem_status(), sims);\n\treturn {\n\t\tsims,')
    api = replace(api, "model: 'Rongyue E5',", "model: ubus_call('system', 'board')?.model ?? null,")
    api = replace(api, 'function advanced() {', 'function advanced_base() {')
    api = api.replace("state_get('advanced', 30)", "state_get('advanced-base-' + sim_card(), 30)").replace("state_put('advanced', r)", "state_put('advanced-base-' + sim_card(), r)")
    for query in ['AT+SPLBAND=0','AT+SPLBAND=3','AT+SPACTCARD?','AT+SP5GRAN?','AT+SPFORCEFRQ=12,3','AT+SPFORCEFRQ=16,3']:
        # Only replace the details function, never mutation/settings handlers.
        start = api.index('function advanced_base() {')
        end = api.index('\nfunction identity()', start)
        section = replace(api[start:end], "at('" + query + "')", 'null')
        api = api[:start] + section + api[end:]
    api = replace(api, 'function identity() {', (HERE / 'details.uc').read_text(encoding='utf-8') + '\nfunction identity() {')
    config = '''status_bar: c.get('e5-infoscreen', 'main', 'status_bar') != '0',
		awake: (read_num(backlight_path() + '/brightness') ?? 0) > 0,
		lock_wallpaper: c.get('e5-infoscreen', 'main', 'lock_wallpaper') ?? 'default',
		lock_wallpaper_rev: c.get('e5-infoscreen', 'main', 'lock_wallpaper_rev') ?? '',
		desktop_wallpaper: c.get('e5-infoscreen', 'main', 'desktop_wallpaper') ?? 'default',
		desktop_wallpaper_rev: c.get('e5-infoscreen', 'main', 'desktop_wallpaper_rev') ?? '',
		nav_bar: c.get('e5-infoscreen', 'main', 'nav_bar') != '0',
		ui_size: c.get('e5-infoscreen', 'main', 'ui_size') ?? 'standard',
		speed_unit: (c.get('e5-infoscreen', 'main', 'speed_unit') == 'mbs' || c.get('e5-infoscreen', 'main', 'speed_unit') == 'auto' || c.get('e5-infoscreen', 'main', 'speed_unit') == 'bytes') ? 'bytes' : 'bits',
		ui_theme: c.get('e5-infoscreen', 'main', 'ui_theme') ?? 'dark',
		ui_opacity: +(c.get('e5-infoscreen', 'main', 'ui_opacity') ?? 70),
		ui_accent: c.get('e5-infoscreen', 'main', 'ui_accent') ?? 'mint',
		ui_density: c.get('e5-infoscreen', 'main', 'ui_density') ?? 'comfortable',
		ui_motion: c.get('e5-infoscreen', 'main', 'ui_motion') != '0',
		lock_enabled: c.get('e5-infoscreen', 'main', 'lock_enabled') != '0',
		lock_daily: c.get('e5-infoscreen', 'main', 'lock_daily') != '0',
		lock_monthly: c.get('e5-infoscreen', 'main', 'lock_monthly') != '0',
		lock_speed: c.get('e5-infoscreen', 'main', 'lock_speed') != '0',
		unlock_distance: c.get('e5-infoscreen', 'main', 'unlock_distance') ?? 'standard',
        '''
    for i, fallback in enumerate(['0','1','2','3','7'], 1):
        config += f"nav_slot{i}: c.get('e5-infoscreen', 'main', 'nav_slot{i}') ?? '{fallback}',\n\t\t"
    api = replace(api, "idle: +(c.get('e5-infoscreen', 'main', 'idle') ?? 60),", config + "idle: +(c.get('e5-infoscreen', 'main', 'idle') ?? 60),")
    api = replace(api, "return writefile(p + '/brightness', `${level}\\n`) != null;", "return system(`/usr/libexec/t551m-screen-power set ${level}`) == 0;")
    settings = (HERE / 'base/settings.uc').read_text(encoding='utf-8')
    settings = replace(settings, '与荣悦及设备、芯片厂商无关', '与设备、芯片厂商无关')
    settings = replace(settings, 'not affiliated with Rongyue or the device and chip makers', 'not affiliated with the device and chip makers')
    settings = replace(settings, 'const screen = uci_category(', (HERE / 'ui-settings.uc').read_text(encoding='utf-8') + '\nconst screen = uci_category(')
    settings = replace(settings, 'const system_cat = {', (HERE / 'cpu-settings.uc').read_text(encoding='utf-8') + '\nconst system_cat = {')
    settings = replace(settings, "{ id: 'traffic_clear', type: 'category',", "cpu_link('cpu', 'CPU 设置', 'CPU settings'),\n\t\t\t{ id: 'traffic_clear', type: 'category',")
    settings = replace(settings, "default: '1', label: L('触摸', 'Touch'),", "default: '1', label: L('触摸', 'Touch'), confirm: true, apply: '/usr/libexec/t551m-screen-power sync',")
    settings = replace(settings, 'screen, usb_cat, system_cat, traffic_records, about ];', 'screen, mobile_ui, mobile_navigation, usb_cat, system_cat, traffic_records, ...cpu_categories, about ];')
    index = (HERE / 'base/index.html').read_text(encoding='utf-8')
    index = replace(index, '<link rel="stylesheet" href="style.css">', '<link rel="stylesheet" href="style.css">\n<link rel="stylesheet" href="mobile.css">')
    index = replace(index, '<script src="app.js"></script>', '<script src="transport.js"></script>\n<script src="power-menu.js"></script>\n<script src="mobile.js"></script>\n<script src="calls.js"></script>\n<script src="app.js"></script>')
    index = replace(index, '<section class="page" data-title="adv_info">', '<section class="page" data-title="adv_info"><div id="ad-freshness" hidden></div>')
    app += '\n' + (HERE / 'apn.js').read_text(encoding='utf-8')
    return {'www/app.js': app, 'api.uc': api, 'settings.uc': settings, 'www/index.html': index,
            'xkb/rules/e5': (HERE / 'xkb/rules/e5').read_text(encoding='utf-8'),
            'xkb/symbols/e5': (HERE / 'xkb/symbols/e5').read_text(encoding='utf-8'),
            'updates.uc': (HERE / 'base/updates.uc').read_text(encoding='utf-8'),
            'ADAPTATION': 'e5-device-ui-v1\n',
            'www/style.css': scalable_css((HERE / 'base/style.css').read_text(encoding='utf-8')),
            'www/mobile.js': (HERE / 'mobile.js').read_text(encoding='utf-8'),
            'www/calls.js': (HERE / 'calls.js').read_text(encoding='utf-8'),
            'www/transport.js': (HERE / 'transport.js').read_text(encoding='utf-8'),
            'www/sdk/e5.js': (HERE / 'base/sdk.js').read_text(encoding='utf-8'),
            'www/power-menu.js': (HERE / 'power-menu.js').read_text(encoding='utf-8'),
            'www/mobile-phone.css': (HERE / 'mobile-phone.css').read_text(encoding='utf-8'),
            'www/mobile.css': scalable_css((HERE / 'mobile.css').read_text(encoding='utf-8'))}


def stage(root):
    root = Path(root)
    for name, content in sources().items():
        dest = root / 'usr/share/e5-infoscreen' / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content.replace('\r\n', '\n').encode())
        dest.chmod(0o644)
    for source, name in [
                         ('base/session', 'usr/libexec/e5-infoscreen/session'),
                         ('base/update', 'usr/libexec/e5-infoscreen/update'),
                         ('base/service', 'etc/init.d/e5-infoscreen'),
                         ('base/plugin', 'usr/libexec/e5-infoscreen/plugin'),
                         ('sim-service', 'etc/init.d/t551m-sim-status'),
                         ('details-radio.py', 'usr/libexec/t551m-screen-details'),
                         ('power-service', 'etc/init.d/t551m-screen-power'),
                         ('wallpaper-rpc.py', 'usr/libexec/rpcd/t551m-screen')]:
        dest = root / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((HERE / source).read_bytes().replace(b'\r\n', b'\n'))
        dest.chmod(0o755)
    (root / 'usr/share/e5-infoscreen/LICENSE.t551m').write_bytes((HERE / 'LICENSE').read_bytes())
    voice = root / 'usr/libexec/e5-voice-audio'
    voice.write_bytes((HERE.parents[2] / 'openwrt/overlay/usr/libexec/e5-voice-audio').read_bytes().replace(b'\r\n', b'\n'))
    voice.chmod(0o755)
    # A screen-only staging pass also carries the audio route implementation
    # required by the phone app; do not ship a picker with an old backend.
    repo = HERE.parents[2]
    for name, source in {
        'usr/libexec/e5-hfp': repo / 'openwrt/overlay/usr/libexec/e5-hfp',
        'usr/libexec/e5-volume': repo / 'openwrt/overlay/usr/libexec/e5-volume',
        'usr/libexec/e5-call-volume': repo / 'openwrt/overlay/usr/libexec/e5-call-volume',
        'usr/lib/e5/e5_call_volume.py': repo / 'openwrt/overlay/usr/lib/e5/e5_call_volume.py',
        'usr/lib/e5/e5_sounds.py': repo / 'openwrt/overlay/usr/lib/e5/e5_sounds.py',
        'usr/libexec/e5-notification-sound': repo / 'openwrt/overlay/usr/libexec/e5-notification-sound',
        'usr/libexec/e5-sms-notify': repo / 'openwrt/overlay/usr/libexec/e5-sms-notify',
        'etc/init.d/e5-voice-audio': repo / 'openwrt/overlay/etc/init.d/e5-voice-audio',
        'etc/init.d/e5-hfp': repo / 'openwrt/overlay/etc/init.d/e5-hfp',
        'etc/sysctl.d/10-e5-printk.conf': repo / 'openwrt/overlay/etc/sysctl.d/10-e5-printk.conf',
        'opt/e5/e5-call-audio.py': repo / 'rootfs/overlay/opt/e5/e5-call-audio.py',
        'opt/e5/e5_call_profiles.py': repo / 'rootfs/overlay/opt/e5/e5_call_profiles.py',
    }.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes().replace(b'\r\n', b'\n'))
        target.chmod(0o644 if name.startswith('etc/sysctl.d/') else 0o755)
    for name in ('e5_call_events.py', 'e5_screen_rpc.py', 'e5_power_events.py'):
        (root / 'usr/lib/e5' / name).unlink(missing_ok=True)
    # All screen-capable profiles and shared screen updates use these same ELFs.
    native = __import__('runpy').run_path(str(repo / 'devices/common/build-screen-native.py'))
    for name, binary in native['build']().items():
        target = root / 'usr/libexec' / name
        target.write_bytes(binary.read_bytes())
        target.chmod(0o755)
    manifest = root / 'usr/share/e5/voice-routes.json'
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_bytes(native['route_manifest']())
    manifest.chmod(0o644)
    # Repair every built-in asset during shared updates as well as fresh
    # builds. WAV payloads are binary: newline conversion shifts PCM samples.
    for name in ('ding.wav', 'call.wav', 'beep.wav'):
        sound = root / 'usr/share/e5' / name
        sound.parent.mkdir(parents=True, exist_ok=True)
        sound.write_bytes((repo / 'openwrt/overlay/usr/share/e5' / name).read_bytes())
        sound.chmod(0o644)
    for source in (repo / 'openwrt/overlay/usr/lib/e5/vendor').iterdir():
        target = root / 'usr/lib/e5/vendor' / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())  # wheel must stay byte-identical
        target.chmod(0o644)
    for source in (HERE / 'phone').iterdir():
        if not source.is_file():
            continue
        target = root / 'etc/e5-infoscreen/plugins/phone' / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes().replace(b'\r\n', b'\n'))
        target.chmod(0o644)
        # Archive/browser fixture roots have no upstream plugin symlink yet.
        web = root / 'usr/share/e5-infoscreen/www/plugins/phone'
        if not web.is_symlink():
            web.mkdir(parents=True, exist_ok=True)
            (web / source.name).write_bytes(target.read_bytes())
    luci = (HERE / 'base/luci-settings.js').read_text(encoding='utf-8')
    luci = replace(luci, "\t\to = s.option(form.Value, 'update_url',", """
		for (var field of [
			['status_bar', '顶部状态栏'], ['nav_bar', '底部导航栏'], ['ui_motion', '界面过渡动画'],
			['lock_enabled', '亮屏后上滑解锁'], ['lock_daily', '锁屏显示今日流量'],
			['lock_monthly', '锁屏显示本月流量'], ['lock_speed', '锁屏显示实时网速']
		]) {
			o = s.option(form.Flag, field[0], field[1]); o.default = '1'; o.rmempty = false;
		}
		o = s.option(form.ListValue, 'ui_accent', '界面主题色');
		o.value('mint', '薄荷绿'); o.value('blue', '冰川蓝'); o.value('violet', '鸢尾紫'); o.default = 'mint';
		o = s.option(form.ListValue, 'ui_theme', '外观模式', '同时调整屏幕、锁屏和电话的配色，保存并应用后自动生效。');
		o.value('dark', '暗色'); o.value('light', '亮色'); o.default = 'dark'; o.rmempty = false;
		o = s.option(form.ListValue, 'speed_unit', '网速单位', '锁屏和主页同步切换，随速度自动进位。比特模式按 1000 进位，字节模式按 1024 进位。');
		o.value('bits', '比特 · bps / Kbps / Mbps / Gbps'); o.value('bytes', '字节 · B/s / KB/s / MB/s / GB/s'); o.default = 'bits'; o.rmempty = false;
		o.cfgvalue = function(section) {
			var value = form.ListValue.prototype.cfgvalue.call(this, section);
			return ['bytes', 'auto', 'mbs'].indexOf(value) >= 0 ? 'bytes' : 'bits';
		};
		o = s.option(form.Value, 'ui_opacity', '卡片不透明度（%）', '壁纸下生效；0 为全透明，100 为实色，文字与图标不受影响。');
		o.datatype = 'and(uinteger,range(0,100))'; o.default = '70'; o.rmempty = false;
		o = s.option(form.ListValue, 'ui_density', '内容密度');
		o.value('comfortable', '舒适'); o.value('compact', '紧凑'); o.default = 'comfortable';
		o = s.option(form.ListValue, 'ui_size', '显示大小');
		o.value('small', '小 · 85%'); o.value('standard', '标准 · 100%');
		o.value('large', '大 · 120%'); o.value('extra', '特大 · 140%'); o.default = 'standard';
		o = s.option(form.DummyValue, '_navigation', '底部导航');
		o.rawhtml = true;
		o.cfgvalue = function() { return '<a class="cbi-button" href="' + L.url('admin','services','e5-infoscreen','navigation') + '">自定义五个入口</a>'; };
		o = s.option(form.ListValue, 'unlock_distance', '上滑解锁距离');
		o.value('standard', '标准'); o.value('long', '更长 · 防误触'); o.default = 'standard';
		o = s.option(form.DummyValue, '_wallpapers', '锁屏与桌面壁纸');
		o.rawhtml = true;
		o.cfgvalue = function() { return '<a class="cbi-button" href="' + L.url('admin','services','e5-infoscreen','wallpapers') + '">预览与更换壁纸</a>'; };
		o = s.option(form.Value, 'update_url',""")
    dest = root / 'www/luci-static/resources/view/e5-infoscreen/settings.js'
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(luci.encode())
    dest.chmod(0o644)
    dest = root / 'www/luci-static/resources/view/e5-infoscreen/wallpapers.js'
    dest.write_bytes((HERE / 'wallpapers.js').read_bytes().replace(b'\r\n', b'\n'))
    dest.chmod(0o644)
    dest = root / 'www/luci-static/resources/view/e5-infoscreen/navigation.js'
    dest.write_bytes((HERE / 'navigation.js').read_bytes().replace(b'\r\n', b'\n'))
    dest.chmod(0o644)
    for name, data in {
        'usr/share/luci/menu.d/luci-app-t551m-screen.json': {
            'admin/services/e5-infoscreen/navigation': {'title':'底部导航','order':14,
                'action':{'type':'view','path':'e5-infoscreen/navigation'},
                'depends':{'acl':['luci-app-e5-infoscreen']}},
            'admin/services/e5-infoscreen/wallpapers': {'title':'屏幕壁纸','order':15,
                'action':{'type':'view','path':'e5-infoscreen/wallpapers'},
                'depends':{'acl':['luci-app-t551m-screen']}}
        },
        'usr/share/rpcd/acl.d/luci-app-t551m-screen.json': {
            'luci-app-t551m-screen': {'description':'Screen wallpapers',
                'read':{'ubus':{'t551m-screen':['wallpaper_get','wallpaper_read']}},
                'write':{'ubus':{'t551m-screen':['wallpaper_set','wallpaper_upload','wallpaper_finish','wallpaper_reset']}}}
        }
    }.items():
        dest = root / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(data, ensure_ascii=False)+'\n', encoding='utf-8')
        dest.chmod(0o644)
    dest = root / 'lib/upgrade/keep.d/t551m-screen'
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text('/etc/e5-infoscreen/wallpapers/\n/etc/config/e5-infoscreen\n', encoding='utf-8')
    if __import__('os').name != 'nt':
        for name in ('S98e5-hfp', 'K08e5-hfp'):
            link = root / 'etc/rc.d' / name
            link.parent.mkdir(parents=True, exist_ok=True)
            if not link.is_symlink(): link.symlink_to('../init.d/e5-hfp')
        sim_link = root / 'etc/rc.d/S96t551m-sim-status'
        sim_link.parent.mkdir(parents=True, exist_ok=True)
        if not sim_link.is_symlink():
            sim_link.symlink_to('../init.d/t551m-sim-status')
        sim_stop = root / 'etc/rc.d/K10t551m-sim-status'
        if not sim_stop.is_symlink():
            sim_stop.symlink_to('../init.d/t551m-sim-status')
        link = root / 'etc/rc.d/S94t551m-screen-power'
        link.parent.mkdir(parents=True, exist_ok=True)
        if not link.is_symlink():
            link.symlink_to('../init.d/t551m-screen-power')
