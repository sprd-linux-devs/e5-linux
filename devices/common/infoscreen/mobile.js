/* T551M phone shell. All device data/actions use the existing local API.
 * The swipe lock prevents accidental operation, it is not authentication.
 */
'use strict';
window.T551M = (() => {
    const icons = {
        home:'m3 10 9-7 9 7M5 9v12h5v-7h4v7h5V9',
        traffic:'M6 3v17m-4-4 4 4 4-4M18 21V4m-4 4 4-4 4 4',
        wifi:'M2 8a16 16 0 0 1 20 0M5 12a11 11 0 0 1 14 0m-11 4a6 6 0 0 1 8 0m-4 4h.01',
        apps:'M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z',
        settings:'M4 6h16M4 18h16M8 3v6m8 6v6M4 12h16m-4-3v6',
        back:'m14 5-7 7 7 7', menu:'M4 6h16M4 12h16M4 18h16',
        lock:'M7 10V7a5 5 0 0 1 10 0v3M5 10h14v11H5zM12 14v3',
        signal:'M4 20v-4m5 4v-8m5 8V8m5 12V3',
        sms:'M3 4h18v13H8l-5 4zM7 8h10m-10 5h7',
        device:'M6 2h12v20H6zM10 18h4', info:'M12 11v7m0-12v1M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20',
        up:'m6 14 6-6 6 6', close:'m6 6 12 12M18 6 6 18'
    };
    const svg = name => `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${icons[name] || icons.apps}"/></svg>`;
    const el = id => document.getElementById(id);
    let trafficPicker = null;
    function closeTrafficPicker(restoreFocus = false) {
        if (!trafficPicker || trafficPicker.list.hidden) return;
        trafficPicker.list.hidden = true;
        trafficPicker.button.setAttribute('aria-expanded', 'false');
        if (restoreFocus) trafficPicker.button.focus({preventScroll:true});
    }
    function syncTrafficPicker() {
        if (!trafficPicker) return;
        const {select, button, list} = trafficPicker;
        const text = select.selectedOptions[0]?.textContent || '';
        if (button.textContent !== text) button.textContent = text;
        for (const [i, option] of [...select.options].entries()) {
            const row = list.children[i];
            const span = row.querySelector('span'), selected = String(option.selected);
            if (span.textContent !== option.textContent) span.textContent = option.textContent;
            if (row.getAttribute('aria-selected') !== selected) row.setAttribute('aria-selected', selected);
            const tabIndex = option.selected ? 0 : -1;
            if (row.tabIndex !== tabIndex) row.tabIndex = tabIndex;
        }
    }
    function bootTrafficPicker() {
        const select = el('tf-slot'), wrap = select?.parentElement;
        if (!wrap) return;
        // Keep the existing value/change API, but never open WebKit's native
        // popup, which cannot inherit this shell's theme or touch geometry.
        select.hidden = true;
        const button = document.createElement('button'), list = document.createElement('div');
        button.id = 'tf-slot-button'; button.type = 'button'; button.className = 'traffic-trigger';
        button.setAttribute('aria-haspopup', 'listbox'); button.setAttribute('aria-expanded', 'false');
        button.setAttribute('aria-controls', 'tf-slot-options');
        list.id = 'tf-slot-options'; list.className = 'traffic-options'; list.hidden = true;
        list.setAttribute('role', 'listbox'); list.setAttribute('aria-labelledby', 'tf-slot-label');
        const label = document.querySelector('label[for="tf-slot"]');
        label.id = 'tf-slot-label'; label.htmlFor = button.id;
        for (const option of select.options) {
            const row = document.createElement('button');
            row.type = 'button'; row.dataset.value = option.value; row.setAttribute('role', 'option');
            row.innerHTML = '<span></span>' + svg('check');
            row.onclick = () => {
                const changed = select.value !== option.value;
                select.value = option.value; syncTrafficPicker(); closeTrafficPicker(true);
                if (changed) select.dispatchEvent(new Event('change', {bubbles:true}));
            };
            list.appendChild(row);
        }
        wrap.append(button, list); trafficPicker = {select, button, list};
        select.addEventListener('change', syncTrafficPicker);
        button.onclick = () => {
            if (!list.hidden) { closeTrafficPicker(true); return; }
            syncTrafficPicker(); list.hidden = false; button.setAttribute('aria-expanded', 'true');
            list.querySelector('[aria-selected="true"]').focus({preventScroll:true});
        };
        document.addEventListener('pointerdown', event => {
            if (!wrap.contains(event.target)) closeTrafficPicker();
        }, true);
        window.addEventListener('keydown', event => {
            if (list.hidden) return;
            if (event.key === 'Tab') { closeTrafficPicker(true); return; }
            if (!['Escape','ArrowUp','ArrowDown','Home','End','Enter',' '].includes(event.key)) return;
            event.preventDefault(); event.stopImmediatePropagation();
            if (event.key === 'Escape') { closeTrafficPicker(true); return; }
            const rows = [...list.children], index = rows.indexOf(document.activeElement);
            if (event.key === 'Enter' || event.key === ' ') { rows[Math.max(0,index)].click(); return; }
            const next = event.key === 'Home' ? 0 : event.key === 'End' ? rows.length-1
                : (index + (event.key === 'ArrowUp' ? -1 : 1) + rows.length) % rows.length;
            rows[next].focus({preventScroll:true});
        }, true);
        syncTrafficPicker();
    }
    const words = (zh, en) => document.documentElement.lang == 'en' ? en : zh;
    const titles = [['概览','Home'],['信号','Signal'],['流量','Usage'],['短信','Messages'],['热点','Hotspot'],['设备','Device'],['详细信息','Details'],['设置','Settings'],['应用','Apps']];
    const pageIcons = ['home','signal','traffic','sms','wifi','device','info','settings','apps'];
    let config = {}, mounted = false, screenLocked = true, dark = false;
    let gesture = null, blockUntil = 0, wakeAt = 0, animation = null;
    let gestureFrame = null;
    let usageAt = -Infinity, usageBusy = false, cachedUsage = null;
    let usageGeneration = 0, usageSlot = null;
    let keyArmed = 0;
    let menuOpen = false, menuTimer = null;
    const label = index => words(...titles[index]);
    const duration = () => config.ui_motion === false ? 0 : 240;
    const lockedNow = () => screenLocked || dark;
    const navDefaults = [0,1,2,3,7];
    let navKey = '';
    let appliedKey = '';
    function pageOrder() {
        return [...new Set(navDefaults.map((fallback, i) => {
            const value = config['nav_slot' + (i+1)];
            return value != null && /^[0-8]$/.test(String(value)) ? +value : fallback;
        }).concat(titles.map((_, i) => i)))];
    }
    function position(index) { return pageOrder().indexOf(index); }
    function step(delta) {
        const order = pageOrder();
        navigate(order[(order.indexOf(page) + delta + order.length) % order.length]);
    }
    function navigation() {
        const items = navDefaults.map((fallback, i) => {
            const value = config['nav_slot' + (i+1)];
            return value != null && /^[0-8]$/.test(String(value)) ? +value : fallback;
        });
        const key = items.join(',');
        if (key === navKey) return;
        navKey = key;
        el('mobile-nav').innerHTML = items.map(i => `<button data-page="${i}">${svg(pageIcons[i])}<span data-page-label="${i}">${label(i)}</span></button>`).join('');
        // Keep DOM/iframe state intact; ordering also drives menu and swipe navigation.
        const order = pageOrder();
        order.forEach((id, index) => { pages[id].style.order = index; });
        el('mobile-menu').querySelectorAll('.mobile-grid [data-page]').forEach(node => {
            node.style.order = position(+node.dataset.page);
        });
    }

    function menu(on, immediate=false) {
        menuOpen = on;
        clearTimeout(menuTimer);
        const panel = el('mobile-menu');
        el('mobile-more').setAttribute('aria-expanded', String(on));
        if (on) {
            panel.hidden = false;
            // Commit the closed pose before starting the transition.
            void panel.offsetHeight;
            panel.classList.add('open');
        } else {
            panel.classList.remove('open');
            if (immediate || !duration()) panel.hidden = true;
            else menuTimer = setTimeout(() => { if (!menuOpen) panel.hidden = true; }, duration());
        }
    }
    function operator(name) {
        if (!name) return name;
        const key = String(name).toUpperCase().replace(/[\s_\-]/g, '');
        const aliases = [
            [['中国移动','中国移动通信','CHINAMOBILE','CHNMOBILE','CMCC','46000','46002','46004','46007','46008'], ['中国移动','China Mobile']],
            [['中国联通','CHINAUNICOM','CHNUNICOM','UNICOM','CUCC','46001','46006','46009'], ['中国联通','China Unicom']],
            [['中国电信','CHINATELECOM','CHNTELECOM','CHNCT','CHNCTLTE','CTCC','46003','46005','46011','46012'], ['中国电信','China Telecom']],
            [['中国广电','CHINABROADNET','CHNBG','CBN','CHINABROADCASTINGNETWORK','46015'], ['中国广电','China Broadnet']]
        ];
        for (const [names, translated] of aliases) if (names.includes(key)) return words(...translated);
        return name;
    }

    function navigate(index) {
        if (lockedNow() || window.T551MCalls?.active()) return;
        if (index === page) {
            if (index === P.settings) { stDisarm(); st = [{view:'menu'}]; }
            if (index === P.sms && smsOpen != null) closeSms();
            if (index === P.adv_info) { hideIds(); extraTemps = false; }
        }
        if (appOpen) closeApp();
        if (imeOpen) closeInputMethod();
        menu(false);
        showPage(index);
        resetIdle();
    }
    function back() {
        if (appOpen) { closeApp(); return; }
        if (menuOpen) { menu(false); return; }
        if (page == P.settings && st.length > 1) { st.pop(); stRender(); return; }
        if (page == P.sms && smsOpen != null) { closeSms(); return; }
        navigate(P.overview);
    }
    function pageChanged(index) {
        if (!mounted) return;
        if (index !== P.traffic) closeTrafficPicker();
        el('mobile-title').textContent = appOpen ? lbl(appOpen.name) || appOpen.id : label(index);
        const button = el('mobile-back'), icon = index === P.overview && !appOpen ? 'home' : 'back';
        if (button.dataset.icon !== icon) {
            button.innerHTML = svg(icon);
            button.dataset.icon = icon;
        }
        button.setAttribute('aria-label', icon === 'home' ? words('主页', 'Home') : words('返回', 'Back'));
        paintPageLoad(index);
        document.querySelectorAll('#mobile-nav button').forEach(button => {
            const active = +button.dataset.page == index;
            button.classList.toggle('active', active);
            button.setAttribute('aria-current', active ? 'page' : 'false');
        });
    }
    function apply() {
        const key = JSON.stringify([config, document.documentElement.lang, screenLocked]);
        if (key === appliedKey) return;
        appliedKey = key;
        const body = document.body;
        body.dataset.theme = config.ui_theme === 'light' ? 'light' : 'dark';
        const opacity = Number(config.ui_opacity ?? 70);
        body.style.setProperty('--ui-opacity', (Number.isFinite(opacity) ? Math.min(100, Math.max(0, opacity)) : 70) / 100);
        body.dataset.accent = ['mint','blue','violet'].includes(config.ui_accent) ? config.ui_accent : 'mint';
        body.classList.toggle('compact', config.ui_density == 'compact');
        const scale = {'small':.85,'standard':1,'large':1.2,'extra':1.4}[config.ui_size] || 1;
        body.style.setProperty('--ui-scale', scale);
        navigation();
        body.classList.toggle('no-motion', config.ui_motion === false);
        body.classList.toggle('hide-status', config.status_bar === false);
        body.classList.toggle('hide-nav', config.nav_bar === false);
        body.classList.toggle('screen-locked', screenLocked);
        for (const target of ['lock','desktop']) {
            const custom = config[target+'_wallpaper'] == 'custom';
            const revision = String(config[target+'_wallpaper_rev'] || '').replace(/[^a-f0-9]/g,'').slice(0,16);
            body.classList.toggle(target+'-wallpaper', custom);
            body.style.setProperty('--'+target+'-wallpaper', custom ? `url("/wallpapers/${target}.png?v=${revision}")` : 'none');
        }
        appWallpaper(el('app-frame'));
        for (const [id, option] of [['lock-day','lock_daily'],['lock-month','lock_monthly'],['lock-rates','lock_speed']])
            el(id).hidden = config[option] === false;
        el('lock-summary').hidden = config.lock_daily === false && config.lock_monthly === false && config.lock_speed === false;
        document.querySelector('.lock-usage').hidden = config.lock_daily === false && config.lock_monthly === false;
        el('lock-hint').textContent = config.touch === false
            ? words('触控已关闭 · 按两次确认键解锁', 'Touch off · press OK twice')
            : words('从下方向上滑动解锁', 'Swipe up to unlock');
        el('lock-day-label').textContent = words('今日已用', 'TODAY');
        el('lock-month-label').textContent = words('本月已用', 'THIS MONTH');
        el('lock-rx-label').textContent = words('下载', 'DOWN');
        el('lock-tx-label').textContent = words('上传', 'UP');
        el('mobile-menu-title').textContent = words('全部页面', 'All pages');
        el('hotspot-scan-title').textContent = words('扫码即连', 'Scan to connect');
        el('hotspot-scan-note').textContent = words('用手机相机扫描，无需输入密码', 'Scan with your camera to join');
        document.querySelectorAll('[data-page-label]').forEach(node => node.textContent = label(+node.dataset.pageLabel));
        pageChanged(page);
        paintUsage();
    }
    function boot() {
        document.body.insertAdjacentHTML('beforeend', `
<div id="mobile-toolbar"><button id="mobile-back" aria-label="主页">${svg('home')}</button><h1 id="mobile-title">概览</h1><div id="mobile-loading" class="screen-loading" role="status" aria-label="读取中…" hidden><i aria-hidden="true"></i></div><button id="mobile-lock" aria-label="锁屏">${svg('lock')}</button><button id="mobile-more" aria-label="全部页面">${svg('menu')}</button></div>
<nav id="mobile-nav" aria-label="主导航"></nav>
<aside id="mobile-menu" hidden><div class="mobile-sheet-head"><h2 id="mobile-menu-title">全部页面</h2><button id="mobile-menu-close" aria-label="关闭">${svg('close')}</button></div><div class="mobile-grid">${titles.map((_, i) => `<button data-page="${i}">${svg(pageIcons[i])}<span data-page-label="${i}">${label(i)}</span></button>`).join('')}</div></aside>
<section id="mobile-lockscreen" role="region" aria-label="锁屏"><div class="lock-top"><span id="lock-symbol">${svg('lock')}</span><div id="lock-date">—</div><div id="lock-time">--:--</div><div class="lock-online"><i></i><span id="lock-network">随身网络</span></div></div>
<div id="lock-summary"><div class="lock-usage"><div id="lock-day"><span id="lock-day-label">今日已用</span><strong id="lock-day-value">—</strong></div><div id="lock-month"><span id="lock-month-label">本月已用</span><strong id="lock-month-value">—</strong></div></div>
<div id="lock-rates"><div><span>↓ <span id="lock-rx-label">下载</span></span><strong id="lock-rx">—</strong></div><div><span>↑ <span id="lock-tx-label">上传</span></span><strong id="lock-tx">—</strong></div></div>
</div><div id="lock-swipe">${svg('up')}<span id="lock-hint">从下方向上滑动解锁</span><i></i></div></section>`);
        mounted = true;
        bootTrafficPicker();
        T551MPower.boot();
        el('bar-bat').insertAdjacentHTML('beforeend', '<svg class="battery-bolt" viewBox="0 0 12 16" aria-hidden="true"><path d="M7 1 2 9h4l-1 6 7-9H7z"/></svg>');
        el('bar-bars').insertAdjacentHTML('afterend', '<span id="bar-dual" role="img" hidden>'+[0,1].map(slot=>`<span class="dual-row" id="bar-signal-${slot}"><i></i><i></i><i></i><i></i></span>`).join('')+'</span>');
        el('mobile-back').onclick = back;
        el('mobile-more').onclick = () => { menu(!menuOpen); resetIdle(); };
        el('mobile-menu-close').onclick = () => { menu(false); };
        el('mobile-lock').onclick = () => { lock(); resetIdle(); };
        for (const root of [el('mobile-nav'), el('mobile-menu')]) root.onclick = event => {
            const node = event.target.closest('[data-page]');
            if (node) navigate(+node.dataset.page);
        };
        const rates = document.querySelector('[data-title="overview"] .rates');
        rates.insertAdjacentHTML('afterbegin', '<div class="hero-label"><span id="hero-uptime-label">本次运行时长</span><span id="hero-uptime">—</span></div>');
        rates.insertAdjacentHTML('afterend', `<div id="home-usb" class="card home-usb" role="status" hidden><span class="home-usb-icon">${svg('usb')}</span><div><strong id="home-usb-title"></strong><small id="home-usb-detail"></small></div></div>`);
        rates.insertAdjacentHTML('afterend', '<div id="home-boot" class="card home-boot" hidden><strong id="home-boot-title"></strong><p id="home-boot-note"></p><button id="home-boot-default" class="btn wide" type="button"></button></div>');
        let confirmUntil = 0;
        el('home-boot-default').onclick = async () => {
            if (screenLocked || dark || bootBusy || last?.boot?.can_set_default !== true) return;
            if (Date.now() > confirmUntil) {
                confirmUntil = Date.now() + 5000;
                toast(words('再按一次设为默认启动', 'Press again to make OpenWrt the default'));
                return;
            }
            confirmUntil = 0; bootBusy = true;
            el('home-boot-default').disabled = true;
            try {
                const result = await post('settings/system', {id:'default_boot', value:'linux'});
                if (result?.ok) {
                    if (last?.boot) last.boot = {...last.boot, default:'linux', temporary:false};
                    el('home-boot').hidden = true;
                    toast(words('已设为默认启动', 'Default boot saved'));
                } else toast(words('设置失败，请重试', 'Failed to save; try again'));
            } finally { bootBusy = false; }
        };
        document.querySelector('[data-title="signal"] .cellhead').insertAdjacentHTML('afterend', `<div class="card sim-cards">${[0,1].map(slot => `<div class="sim-line" id="sim-line-${slot}"><div class="sim-heading"><b class="sim-slot">SIM ${slot+1}</b><strong id="sim-operator-${slot}">—</strong><span class="sim-role" id="sim-role-${slot}"></span></div><div class="sim-reading"><span id="sim-state-${slot}">—</span><strong id="sim-radio-${slot}">—</strong><span id="sim-signal-${slot}">—</span></div><small id="sim-note-${slot}"></small></div>`).join('')}</div>`);
        document.querySelector('[data-title="hotspot"] .qr').insertAdjacentHTML('afterbegin', '<div class="hotspot-qr-title" id="hotspot-scan-title">扫码即连</div><div id="hotspot-scan-note">用手机相机扫描，无需输入密码</div>');
        for (const span of ['day','mon']) {
            el('tf-'+span+'-rx').parentElement.insertAdjacentHTML('beforebegin', `<div class="traffic-used" id="tf-${span}-used">—</div>`);
            el('tf-'+span+'-lan-rx').parentElement.hidden = true;
        }
        lock();
        apply();
    }
    function clock() {
        if (!mounted) return;
        const d = localParts(), pad = value => String(value).padStart(2, '0');
        setText('lock-time', `${pad(d.h)}:${pad(d.mi)}`);
        // localParts derives the device timezone, independent of the viewer.
        setText('lock-date', words(`${d.mo}月${d.d}日`, `${pad(d.mo)} / ${pad(d.d)}`));
    }
    function amount(bytes, rate=false) {
        if (bytes == null || !Number.isFinite(+bytes)) return '—';
        let value = Math.max(0, +bytes), unit = 0;
        const units = ['B','KB','MB','GB','TB'];
        const base = rate ? 1024 : 1000;
        while (value >= base && unit < 4) { value /= base; unit++; }
        value = Number(value.toFixed(unit ? 2 : 0));
        if (value >= base && unit < 4) { value = 1; unit++; }
        return `${value} ${units[unit]}${rate ? '/s' : ''}`;
    }
    function speed(bytes) {
        // Accept the earlier option names so saved configurations upgrade in place.
        const byteMode = ['bytes','mbs','auto'].includes(config.speed_unit);
        const units = byteMode ? ['B/s','KB/s','MB/s','GB/s','TB/s'] : ['bps','Kbps','Mbps','Gbps','Tbps'];
        if (bytes == null || bytes === '' || !Number.isFinite(+bytes)) return ['—', units[0]];
        const base = byteMode ? 1024 : 1000;
        let value = Math.max(0, +bytes) * (byteMode ? 1 : 8), unit = 0;
        while (value >= base && unit < units.length - 1) { value /= base; unit++; }
        value = Number(value.toFixed(unit ? 2 : 0));
        if (value >= base && unit < units.length - 1) { value = 1; unit++; }
        return [String(value), units[unit]];
    }
    function paintUsage() {
        for (const [id, key] of [['lock-day-value','today'],['lock-month-value','month']]) {
            const value = cachedUsage?.available && cachedUsage[key];
            metric(id, value ? amount(cachedUsage[key + '_used'] ?? ((+value.rx || 0) + (+value.tx || 0))) : '—');
        }
    }
    function metric(id, text) {
        if (el(id).dataset.metric === text) return;
        el(id).dataset.metric = text;
        const [number, unit = ''] = text.split(' ');
        el(id).replaceChildren(document.createTextNode(number));
        const small = document.createElement('small');
        small.textContent = unit;
        el(id).appendChild(small);
    }
    async function usage() {
        if (usageBusy || dark || performance.now() - usageAt < 10000) return;
        usageBusy = true;
        usageAt = performance.now();
        const generation = usageGeneration;
        try {
            const r = await fetch('/api/traffic'+(usageSlot == null ? '' : '?slot='+usageSlot), {cache:'no-store'});
            if (!r.ok) throw new Error('usage unavailable');
            const data = await r.json();
            if (generation === usageGeneration) cachedUsage = data.wan || data;
        } catch (_) { if (generation === usageGeneration) cachedUsage = null; }
        finally {
            usageBusy = false; paintUsage();
            if (generation !== usageGeneration && !dark && screenLocked) usage();
        }
    }
    function refreshUsage() {
        ++usageGeneration;usageAt=-Infinity;cachedUsage=null;
        if (mounted && !dark) paintUsage();
        if (screenLocked && !dark) usage();
    }
    let supplyOnline = null, bootBusy = false;
    window.addEventListener('e5-power-supply-change', () => {
        if (!mounted) return;
        // The kernel catches quick swaps between two status polls. Reuse the
        // normal wake path so the lock, touch preference and idle timer agree.
        if (blank) setBlank(false);
        else resetIdle();
    });
    function status(data) {
        if (!mounted) return;
        const first = !Object.keys(config).length;
        const lockWasEnabled = config.lock_enabled !== false;
        config = data.screen || {};
        // Watch physical supply presence, not Charging/Full/current: pausing
        // at the charge limit must not wake the panel on every status change.
        const online = data.battery?.online;
        if (typeof online === 'boolean') {
            const changed = supplyOnline !== null && supplyOnline !== online;
            supplyOnline = online; // set before wake's re-entrant status paint
            if (changed) {
                if (blank) setBlank(false);
                else resetIdle();
            }
        }
        const slot = data.modem?.sim_card;
        if ([0,1].includes(slot) && slot !== usageSlot) {
            usageSlot = slot;
            refreshUsage();
        }
        if (config.lock_enabled === false && screenLocked && !dark && (first || lockWasEnabled)) finishUnlock();
        // Polling/data delivery keeps its original cadence while the display
        // is dark. Paint the newest snapshot on wake, not invisible DOM now.
        if (dark) return;
        syncTrafficPicker();
        apply();
        clock();
        const boot = data.boot || {};
        const bootHidden = boot.temporary !== true;
        if (el('home-boot').hidden !== bootHidden) el('home-boot').hidden = bootHidden;
        setText('home-boot-title', words('当前为临时启动 OpenWrt', 'OpenWrt was booted temporarily'));
        setText('home-boot-note', boot.can_set_default
            ? words('是否设为默认启动？不会立即重启或断网。', 'Make it the default? No reboot or network interruption.')
            : words('当前启动镜像不支持设置默认启动', 'This boot image cannot set a default boot'));
        setText('home-boot-default', words('设为默认启动', 'Make default boot'));
        const bootDisabled = bootBusy || boot.can_set_default !== true;
        if (el('home-boot-default').disabled !== bootDisabled) el('home-boot-default').disabled = bootDisabled;
        setText('hero-uptime-label', words('本次运行时长', 'Uptime'));
        setText('hero-uptime', data.system?.uptime == null ? '—' : fmtDuration(data.system.uptime));
        const usb = data.usb || {}, attached = usb.devices || [];
        const computer = ['enumerated','lease','online'].includes(usb.link) && usb.role !== 'host';
        const usbHidden = !(usb.role === 'host' && attached.length || computer);
        if (el('home-usb').hidden !== usbHidden) el('home-usb').hidden = usbHidden;
        setText('home-usb-title', usb.role === 'host'
            ? attached.map(d => words(usbDeviceName(d) + ' 已连接', usbDeviceName(d) + ' connected')).join('\n')
            : computer ? words('USB 已连接', 'USB connected') : '');
        setText('home-usb-detail', usb.role === 'host'
            ? words(`OTG 主机 · ${attached.length} 台设备`, `OTG host · ${attached.length} device(s)`)
            : computer ? words('设备模式 · 已连接电脑', 'Device mode · Computer connected') : '');
        const inserted = (data.sims || []).filter(s => s.present === true);
        if (el('bar-dual').hidden !== (inserted.length < 2)) el('bar-dual').hidden = inserted.length < 2;
        const singleDisplay = inserted.length >= 2 ? 'none' : '';
        if (el('bar-bars').style.display !== singleDisplay) el('bar-bars').style.display = singleDisplay;
        const primary = Number(data.modem?.sim_card ?? data.sims?.find(s=>s.data)?.slot ?? 0);
        const descriptions=[];
        for (let slot=0; slot<2; slot++) {
            const sim=data.sims?.find(s=>s.slot===slot), rsrp=sim?.signal?.rsrp;
            const bars=sim?.stale || sim?.error || rsrp == null ? 0 : rsrp>=-90 ? 4 : rsrp>=-100 ? 3 : rsrp>=-110 ? 2 : 1;
            const row = el('bar-signal-'+slot);
            row.classList.toggle('secondary', slot !== primary);
            row.querySelectorAll('i').forEach((node,i)=>node.classList.toggle('on',i<bars));
            descriptions.push(`SIM ${slot+1}: ${bars}/4`);
        }
        const description=descriptions.join(', ');
        if(el('bar-dual').getAttribute('aria-label')!==description)el('bar-dual').setAttribute('aria-label',description);
        const states = {
            home:['已注册','Registered'], roaming:['漫游','Roaming'], searching:['搜网中','Searching'],
            denied:['注册被拒绝','Registration denied'], idle:['未注册','Not registered'],
            emergency:['仅紧急服务','Emergency only'], absent:['未插卡','No SIM'],
            locked:['SIM 已锁定','SIM locked'], disabled:['射频关闭','Radio off'],
            camped:['已驻网','Camped'], unknown:['状态未知','Unknown']
        };
        for (let slot=0; slot<2; slot++) {
            const sim = data.sims?.find(s => s.slot === slot) || {};
            setText('sim-operator-'+slot, operator(sim.operator) || words('待获取运营商','Operator unavailable'));
            setText('sim-role-'+slot, slot === data.modem?.sim_card ? words('数据卡','Data') : words('副卡','Secondary'));
            setText('sim-state-'+slot, words(...(states[sim.registration] || states.unknown)));
            setText('sim-radio-'+slot, sim.radio_label || '—');
            setText('sim-signal-'+slot, sim.signal?.rsrp == null ? '— dBm' : sim.signal.rsrp+' dBm');
            setText('sim-note-'+slot, sim.stale || sim.error ? words('状态暂不可用','Status unavailable') : sim.registration === 'camped' ? words('注册详情未上报','Registration details not reported') : '');
            el('sim-line-'+slot).classList.toggle('data-sim', slot === data.modem?.sim_card);
        }
        for (const direction of ['rx','tx']) {
            const [number, unit] = speed(data.traffic?.[direction+'_rate']);
            metric('lock-'+direction, number+' '+unit);
            // A settings save updates both surfaces before the next poll.
            setText('ov-'+direction, number);
            setText('ov-'+direction+'-u', unit);
        }
        setText('lock-network', data.wan?.up ? words('蜂窝网络已连接', 'Mobile network connected') : words('等待网络连接', 'Connecting'));
        el('lock-network').parentNode.classList.toggle('offline', !data.wan?.up);
        if (screenLocked) usage();
        if (first) {
            // Page restart must restore a physically responsive panel too.
            powerQueue = powerQueue.catch(() => {}).then(() => post('backlight', {level: config.brightness || 120}));
        }
    }
    function resetGesture() {
        cancelAnimationFrame(gestureFrame);
        gestureFrame = null;
        gesture = null;
        el('mobile-lockscreen').classList.remove('dragging');
        el('mobile-lockscreen').style.transform = '';
        el('mobile-lockscreen').style.opacity = '';
        el('mobile-lockscreen').style.transitionDuration = '';
    }
    function lock() {
        if (!mounted) return;
        console.log('t551m-screen: lock');
        clearTimeout(animation);
        animation = null;
        screenLocked = true;
        wakeAt = performance.now();
        keyArmed = 0;
        if (appOpen && !window.T551MCalls?.active()) closeApp();
        if (imeOpen) closeInputMethod();
        menu(false, true);
        el('mobile-lockscreen').hidden = false;
        resetGesture();
        document.body.classList.add('screen-locked');
        if (document.activeElement?.blur) document.activeElement.blur();
        clock();
        usageAt = -Infinity;
        usage();
    }
    function finishUnlock() {
        console.log('t551m-screen: unlocked');
        screenLocked = false;
        gesture = null;
        el('mobile-lockscreen').hidden = true;
        document.body.classList.remove('screen-locked');
        blockUntil = performance.now() + 450;
        resetGesture();
        resetIdle();
        if (last) render(last);
        stRefreshVisible();
    }
    function unlock(velocity=0) {
        if (animation != null) return;
        cancelAnimationFrame(gestureFrame);
        gestureFrame = null;
        const remaining = innerHeight - (gesture ? Math.max(0, gesture.y-gesture.lastY) : 0);
        const ms = !duration() ? 0 : Math.max(140, Math.min(320, remaining / Math.max(1.5, velocity)));
        el('mobile-lockscreen').classList.remove('dragging');
        el('mobile-lockscreen').style.transitionDuration = ms+'ms';
        el('mobile-lockscreen').style.transform = 'translate3d(0,-105%,0)';
        el('mobile-lockscreen').style.opacity = '0';
        animation = setTimeout(() => { animation = null; finishUnlock(); }, ms);
    }
    function power(on) {
        closeTrafficPicker();
        dark = on;
        lock();
        if (!on && config.lock_enabled === false) finishUnlock();
        apply();
        if (!on && last) status(last);
        if (!on) window.T551MCalls?.screenWake?.();
    }
    function start(x, y, count) {
        if (count != 1) { resetGesture(); return; }
        // Follow a deliberate swipe immediately after wake. Guard its release,
        // not touch-down: dropping the start used to discard the whole swipe.
        if (animation != null || y < innerHeight * .25 || dark || config.touch === false) return;
        const now = performance.now();
        gesture = {x,y,lastX:x,lastY:y,peakY:y,time:now,samples:[{y,t:now}]};
        el('mobile-lockscreen').classList.add('dragging');
        resetIdle();
    }
    function move(x, y, count) {
        if (!gesture) return;
        const distance = Math.max(0, gesture.y - y);
        // A thumb naturally travels in an arc. Reject mostly sideways motion,
        // without imposing a fixed lateral limit on a long upward swipe.
        if (count != 1 || Math.abs(x - gesture.x) > Math.max(72, distance * .8) || y > gesture.y + 20) { resetGesture(); return; }
        gesture.lastX = x; gesture.lastY = y;
        gesture.peakY = Math.min(gesture.peakY, y);
        const now = performance.now();
        gesture.samples.push({y,t:now});
        while (gesture.samples.length > 2 && now - gesture.samples[1].t > 120) gesture.samples.shift();
        // Several input samples can arrive before one display frame. Retain
        // all samples for velocity, but paint only the newest position once.
        if (gestureFrame === null) gestureFrame = requestAnimationFrame(() => {
            gestureFrame = null;
            if (!gesture) return;
            const distance = Math.max(0, gesture.y - gesture.lastY);
            el('mobile-lockscreen').style.transform = `translate3d(0,${-distance}px,0)`;
            el('mobile-lockscreen').style.opacity = String(Math.max(.25, 1 - distance / innerHeight * .85));
            resetIdle();
        });
    }
    function end(x, y) {
        if (!gesture) return;
        const dy = gesture.y-y, dx = Math.abs(gesture.x-x), elapsed = performance.now()-gesture.time;
        const long = config.unlock_distance == 'long';
        const threshold = Math.max(long ? 132 : 88, innerHeight * (long ? .30 : .20));
        const now = performance.now(), samples = gesture.samples;
        const recent = samples.filter(p => now-p.t <= 140);
        const first = recent[0], lastPoint = samples[samples.length-1];
        // Recent speed loses momentum when held; a small release wobble is
        // tolerated, while a deliberate pull back from the peak cancels.
        const velocity = first && now-lastPoint.t < 100 ? Math.max(0, (first.y-y) / Math.max(16, now-first.t)) : 0;
        const reversed = y-gesture.peakY > Math.max(16, innerHeight*.035);
        const projected = dy + Math.min(160, velocity*velocity / (2*.0045));
        const flick = dy >= (long ? 72 : 48) && velocity >= .5 && projected >= threshold;
        if (!reversed && (dy >= threshold || flick) && dy > dx*1.35 && elapsed >= 24 && now-wakeAt >= 180) unlock(velocity);
        else resetGesture();
    }
    // Register on window before the legacy document handlers. Lock gestures
    // never reach page swipes, buttons, plugin frames or synthetic clicks.
    for (const name of ['touchstart','touchmove','touchend','touchcancel','pointerdown','pointermove','pointerup','pointercancel','mousedown','mouseup','click','wheel']) {
        window.addEventListener(name, event => {
            if (!mounted) return;
            if (T551MPower.isOpen()) {
                if (event.target.closest?.('#power-menu') && !dark && config.touch !== false) return;
                if (!name.startsWith('touch')) event.preventDefault();
                event.stopImmediatePropagation(); return;
            }
            if (!lockedNow() && performance.now() >= blockUntil) return;
            if (!name.startsWith('touch')) event.preventDefault();
            event.stopImmediatePropagation();
            if (!screenLocked || dark || config.touch === false) return;
            if (name.startsWith('touch')) {
                const point = event.touches[0] || event.changedTouches[0];
                if (name == 'touchcancel') resetGesture();
                else if (!point || (name == 'touchend' && event.touches.length)) resetGesture();
                else if (name == 'touchstart') start(point.clientX,point.clientY,event.touches.length);
                else if (name == 'touchmove') move(point.clientX,point.clientY,event.touches.length);
                else if (name == 'touchend') end(point.clientX,point.clientY);
            } else if (event.pointerType == 'mouse') {
                if (name == 'pointerdown') start(event.clientX,event.clientY,1);
                else if (name == 'pointermove' && event.buttons) move(event.clientX,event.clientY,1);
                else if (name == 'pointerup') end(event.clientX,event.clientY);
                else if (name == 'pointercancel') resetGesture();
            }
        }, {capture:true, passive:name.startsWith('touch')});
    }
    window.addEventListener('keydown', event => {
        if (!mounted || !screenLocked || dark) return;
        const kind = keyKind(event);
        if (['power','volup','voldown'].includes(kind)) return;
        event.preventDefault(); event.stopImmediatePropagation();
        // A deliberately disabled touch panel remains operable by hardware
        // OK, with two separate presses and the same wake guard.
        if (config.touch === false && kind == 'ok' && !event.repeat && performance.now()-wakeAt >= 400) {
            const now = performance.now();
            if (keyArmed && now-keyArmed < 1800) unlock();
            else { keyArmed = now; el('lock-hint').textContent = words('再按一次确认键解锁','Press OK again'); }
        }
    }, true);
    window.addEventListener('blur', () => { if (mounted && gesture) resetGesture(); });
    const dialTargets = new WeakSet();
    let openingPhone = false;
    function attachKeys(target) {
        const doc = target?.document;
        if (!doc || dialTargets.has(doc)) return;
        // A frame keeps its WindowProxy across navigation, but loses listeners.
        dialTargets.add(doc);
        target.addEventListener('keydown', async event => {
            if (!mounted || keyKind(event) !== 'call' || T551MPower.isOpen() || window.T551MCalls?.active()) return;
            // Inside Phone, its SDK owns the green key (dial/answer). Moving
            // focus to the already focused frame swallowed the original event.
            if (appOpen?.id === 'phone' && target !== window) return;
            event.preventDefault(); event.stopImmediatePropagation();
            if (event.repeat || openingPhone) return;
            if (blank) return;
            if (lockedNow() || locked) return;
            resetIdle();
            menu(false, true);
            if (appOpen?.id === 'phone') {
                if (imeOpen) closeInputMethod();
                el('app-frame').focus();
                return;
            }
            openingPhone = true;
            try {
                if (!apps?.some(app => app.id === 'phone')) await loadApps();
                // Loading the manifest must not open an app over a new lock/menu.
                if (lockedNow() || locked || T551MPower.isOpen()) return;
                const phone = apps?.find(app => app.id === 'phone');
                if (!phone) { toast(words('拨号应用未安装', 'Phone app is not installed')); return; }
                if (picShown) picClose();
                if (appOpen) closeApp();
                openApp(phone);
            } finally { openingPhone = false; }
        }, true);
    }
    attachKeys(window);
    function appWallpaper(frame) {
        const doc = frame?.contentDocument;
        if (!doc?.getElementById('t551m-phone-layout')) return;
        const root = doc.documentElement;
        root.dataset.theme = document.body.dataset.theme;
        const palette = getComputedStyle(document.body);
        for (const name of ['--ui-opacity','--bg','--surface-rgb','--button-rgb','--active-rgb','--danger-rgb',
            '--text','--dim','--line','--accent','--good','--poor','--fair','--wallpaper-wash'])
            root.style.setProperty(name, palette.getPropertyValue(name));
        root.classList.toggle('desktop-wallpaper', document.body.classList.contains('desktop-wallpaper'));
        root.style.setProperty('--desktop-wallpaper', document.body.style.getPropertyValue('--desktop-wallpaper'));
        root.style.setProperty('--wallpaper-height', innerHeight + 'px');
        root.style.setProperty('--wallpaper-offset', -frame.getBoundingClientRect().top + 'px');
    }
    function app(frame, manifest) {
        pageChanged(page);
        if (manifest.id !== 'phone' || !frame.contentDocument?.head) return;
        const doc = frame.contentDocument;
        if (doc.getElementById('t551m-phone-layout')) return;
        const style = doc.createElement('link');
        style.id = 't551m-phone-layout';
        style.rel = 'stylesheet';
        style.href = '/mobile-phone.css';
        doc.head.appendChild(style);
        appWallpaper(frame);
    }
    function appClosed(previousFocus) {
        pageChanged(page);
        if (last && !dark) render(last);
        // Pages are laid out side by side. Focusing a button on another page
        // scrolls the root viewport, independently of our translateX routing.
        const visible = previousFocus?.isConnected && previousFocus.offsetParent !== null &&
            (pages[page].contains(previousFocus) || el('mobile-toolbar').contains(previousFocus) ||
             el('mobile-nav').contains(previousFocus));
        (visible ? previousFocus : el('mobile-back')).focus({preventScroll:true});
    }
    // Stable setting IDs keep pictograms consistent across languages and routes.
    Object.assign(icons, {
        battery:'M3 7h16v10H3zM21 10v4M11 8l-3 4h5l-3 4',
        bell:'M5 17h14l-2-3V9a5 5 0 0 0-10 0v5zM10 21h4',
        volume:'M3 10h4l5-5v14l-5-5H3zM16 8a6 6 0 0 1 0 8m3-11a10 10 0 0 1 0 14',
        sun:'M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5',
        moon:'M20 14A9 9 0 0 1 10 3a9 9 0 1 0 10 11z',
        palette:'M12 3a9 9 0 1 0 0 18h1a2 2 0 0 0 1-3.7 1.5 1.5 0 0 1 1-2.8h2a4 4 0 0 0 4-4C21 6 17 3 12 3M7 10h.01M10 6.5h.01M15 7h.01M18 10h.01',
        opacity:'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18M12 3v18m3-16v14m3-12v10',
        clock:'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0M12 7v5l3 2',
        globe:'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0M3 12h18M12 3c5 5 5 13 0 18-5-5-5-13 0-18',
        type:'M3 6h12M9 6v14m-3 0h6M16 13h6m-3 0v7',
        layout:'M3 4h18v16H3zM3 9h18M3 16h18',
        density:'M4 5h16M4 10h16M4 15h16M4 20h16',
        motion:'M9 5l7 7-7 7M3 8h3m-4 4h5m-4 4h3',
        touch:'M9 13V5a2 2 0 0 1 4 0v7l2-2 5 3-1 7H9l-5-7a2 2 0 0 1 3-2z',
        terminal:'M3 4h18v16H3zM6 8l4 4-4 4m7 0h4',
        usb:'M12 20V3m-3 3 3-3 3 3M12 16l-6-4V9m6 4 6-3V7M4 6h4v3H4zM16 4h4v3h-4z',
        bluetooth:'M7 7l10 10-5 4V3l5 4L7 17',
        chip:'M6 6h12v12H6zM9 9h6v6H9zM9 3v3m6-3v3M9 18v3m6-3v3M3 9h3m-3 6h3m12-6h3m-3 6h3',
        refresh:'M3 11a9 9 0 0 1 15.36-6.36L21 7M21 3v4h-4M21 13a9 9 0 0 1-15.36 6.36L3 17M3 21v-4h4',
        navigation:'M5 3h14a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1M4 15h16M8 18h.01M12 18h.01M16 18h.01',
        download:'M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5',
        power:'M12 2v10M7 5a9 9 0 1 0 10 0',
        check:'m5 12 4 4L19 6',
        trash:'M4 6h16M9 6V3h6v3M6 6l1 15h10l1-15M10 10v7m4-7v7',
        simcard:'M6 3h9l4 4v14H6zM9 12h7v6H9zM12.5 12v6M9 15h7',
        shield:'m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6zM9 12l2 2 4-5',
        heart:'M12 20 4 12a5 5 0 0 1 8-6 5 5 0 0 1 8 6z',
        user:'M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0M4 21v-2a8 8 0 0 1 16 0v2',
        search:'M17 10a7 7 0 1 1-14 0 7 7 0 0 1 14 0m-2 5 6 6'
    });
    function settings(root, view, categories) {
        root.dataset.view = view.view;
        const names = {
            network:'signal',at:'terminal',devices:'device',appmgr:'apps',bluetooth:'bluetooth',
            charge:'battery',notify:'bell',sound:'volume',screen:'device',ui:'palette',navigation:'navigation',usb:'usb',system:'chip',about:'info',
            cpu:'chip',cpu_thermal:'sun',persist:'power',current:'chip',voltage:'battery',
            speed_unit:'traffic',ui_theme:'palette',ui_opacity:'opacity',ui_size:'type',ui_accent:'palette',ui_density:'density',ui_motion:'motion',
            status_bar:'layout',nav_bar:'navigation',lock_enabled:'lock',lock_daily:'traffic',lock_monthly:'traffic',lock_speed:'signal',unlock_distance:'touch',
            brightness:'sun',idle:'clock',touch:'touch',lang:'globe',volume:'volume',call_volume:'phone',vibrate:'bell',
            sim_card:'simcard',apn:'globe',net_mode:'signal',nr_mode:'signal',lte_bands:'signal',nr_bands:'signal',cell_lock:'lock',bands_default:'refresh',reconnect:'refresh',
            start:'battery',stop:'battery',full_once:'battery',state:'info',timezone:'globe',clock_seconds:'clock',
            version:'info',built:'clock',screen_version:'info',update_check:'refresh',update_apply:'download',update_rollback:'refresh',
            traffic_clear:'trash',clear_0:'trash',clear_1:'trash',clear_all:'trash',next_boot:'power',default_boot:'power',reboot:'refresh',poweroff:'power',android_once:'power',
            check:'search',diagnosis:'info',wireless_error:'wifi',hardware_error:'chip',controller:'usb',host_address:'device',reset_status:'info',reset:'refresh',
            usb_role_state:'usb',usb_role:'usb',usb_host_boot:'power',usb_net_current:'globe',usb_net_mode:'globe',usb_net_scope:'clock',usb_net_auto:'check',usb_lan_auto:'device',
            name:'info',maintainer:'user',copyright:'shield',license:'shield',donate:'heart',disclaimer:'info',
            mac:'device',ip:'globe',via:'wifi',appid:'apps',appver:'info',appkind:'apps',appdesc:'info',btname:'bluetooth',btmac:'bluetooth',btst:'info'
        };
        const actions = {open:'apps',settings:'settings',remove:'trash',scan:'search',power:'power',autostart:'power',connect:'bluetooth',disconnect:'bluetooth',block:'shield',unblock:'shield',kick:'shield'};
        for (const row of root.querySelectorAll('.strow')) {
            if (row.classList.contains('with-icon')) continue;
            const label = row.firstElementChild;
            if (!label) continue;
            const [kind, id] = (row.dataset.st || '').split(':');
            let icon = 'settings';
            if (kind === 'cat') icon = names[categories?.[+id]?.id] || 'settings';
            else if (kind === 'item') icon = /^nav_slot[1-5]$/.test(id)
                ? pageIcons[+view.items?.find(item => item.id === id)?.value] || 'layout'
                : /^cpu_policy|^policy\d+/.test(id) ? 'chip' : /^thermal_zone/.test(id) ? 'sun'
                : /^voltage_/.test(id) ? 'battery' : names[id] || names[view.cat?.id] || 'settings';
            else if (kind === 'info') icon = names[id] || 'info';
            else if (kind === 'opt' || kind === 'chk') {
                const option = String(view.item?.options?.[+id]?.value ?? '');
                icon = view.item?.id === 'ui_theme' ? (option === 'light' ? 'sun' : 'moon')
                    : /^nav_slot[1-5]$/.test(view.item?.id) ? pageIcons[+option]
                    : names[view.item?.id] || 'settings';
                const mark = row.querySelector('.sv');
                if (mark) mark.innerHTML = row.classList.contains('on') ? svg('check') : '';
                row.setAttribute('aria-pressed', String(row.classList.contains('on')));
            } else if (kind === 'num' || kind === 'multi') icon = id === 'clear' ? 'trash' : 'check';
            else if (kind.startsWith('at')) icon = 'terminal';
            else if (['bt','bta','act','apa'].includes(kind)) icon = actions[id] || 'settings';
            else if (kind === 'btd') icon = 'bluetooth';
            else if (kind === 'dev') icon = 'device';
            else if (kind === 'storerf') icon = 'refresh';
            else if (['store','apm','stp'].includes(kind)) icon = 'apps';
            // Preserve the existing text and data-st target; SVGs are decoration.
            const text = document.createElement('span');
            text.textContent = label.textContent;
            label.textContent = '';
            const badge = document.createElement('span');
            badge.className = 'st-icon';
            badge.innerHTML = svg(icon);
            label.classList.add('st-label');
            label.append(badge, text);
            row.classList.add('with-icon');
            row.classList.toggle('has-value', !!row.querySelector('.sv')?.textContent.trim());
        }
    }
    return {boot, status, power, clock, page:pageChanged, position, step, isLocked:lockedNow, operator, amount, speed, app, appClosed, settings, attachKeys, refreshUsage};
})();
