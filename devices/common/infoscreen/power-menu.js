/* Hardware power key: short release toggles the panel, 1.2 s hold opens a menu.
 * The local settings API owns shutdown and boot selection, including NV cleanup.
 */
'use strict';
window.T551MPower = (() => {
    let root, held = null, selected = null, busy = false, previousFocus, focusedButton;
    let lastBack = -Infinity, lastMove = -Infinity;
    const wired = new WeakSet();
    const words = (zh, en) => document.documentElement.lang === 'en' ? en : zh;
    const actions = {
        poweroff: {name: () => words('关机', 'Power off'), icon:'M12 2v10M7 5a9 9 0 1 0 10 0'},
        reboot: {name: () => words('重启', 'Restart'), icon:'M19.5 8A8 8 0 1 0 20 15M19.5 3.5V8H15'},
        android_once: {name: () => words('切换到 Android', 'Switch to Android'), icon:'M4 16a8 8 0 0 1 16 0v2H4v-2ZM7 9 5 5m12 4 2-4M8 14h.01M16 14h.01'}
    };
    const isOpen = () => !!root && !root.hidden;
    function cancelHold() { if (held) clearTimeout(held.timer); held = null; }
    function buttons() {
        return Array.from(root.querySelectorAll('button:not(:disabled)')).filter(b => b.getClientRects().length);
    }
    function remember(button) {
        if (!button || !root.contains(button) || button.disabled) return;
        focusedButton?.classList.remove('power-key-focus');
        focusedButton = button;
        focusedButton.classList.add('power-key-focus');
    }
    function focus(button) {
        if (!button) return;
        remember(button);
        button.focus({preventScroll:true});
        // Scroll only the sheet: background pages may be laid out off-screen.
        const sheet = root.querySelector('.power-sheet');
        const item = button.getBoundingClientRect(), box = sheet.getBoundingClientRect();
        if (item.top < box.top) sheet.scrollTop -= box.top - item.top;
        else if (item.bottom > box.bottom) sheet.scrollTop += item.bottom - box.bottom;
    }
    function currentButton() {
        const list = buttons();
        return list.includes(document.activeElement) ? document.activeElement
            : list.includes(focusedButton) ? focusedButton : list.find(b => b.hasAttribute('data-cancel'));
    }
    function close() {
        if (busy || !root) return;
        root.hidden = true;
        document.body.classList.remove('power-menu-open');
        selected = null;
        focusedButton = null;
        resetIdle();
        if (!T551M.isLocked() && previousFocus?.isConnected) previousFocus.focus({preventScroll:true});
    }
    function paint() {
        root.innerHTML = `<div class="power-sheet" role="dialog" aria-modal="true" aria-labelledby="power-title">
<div class="power-heading"><h2 id="power-title">${selected ? actions[selected].name() : words('电源菜单','Power menu')}</h2></div>
${selected ? `<p class="power-note">${selected === 'android_once' ? words('重启进入 Android，并将其设为默认启动系统。','Restart into Android and make it the default system.') : words('确认'+actions[selected].name()+'？','Confirm '+actions[selected].name().toLowerCase()+'?')}</p>
<button class="power-confirm" data-confirm>${words('确认','Confirm')}</button>` : `<div class="power-actions">${Object.entries(actions).map(([id,a]) => `<button data-power="${id}"><span class="power-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="${a.icon}"/></svg></span><span>${a.name()}</span><span class="power-chevron">›</span></button>`).join('')}</div>`}
<p id="power-error" class="power-note" role="status" hidden></p><button class="power-cancel" data-cancel>${words('取消','Cancel')}</button></div>`;
        focus(root.querySelector('[data-cancel]'));
    }
    async function execute() {
        if (busy || !selected) return;
        busy = true;
        root.querySelectorAll('button').forEach(b => b.disabled = true);
        const status = root.querySelector('#power-error');
        status.hidden = false;
        status.textContent = words('正在执行…','Working…');
        const result = await post('settings/system', {id:selected});
        if (result?.ok) return; // Keep controls disabled until the system exits.
        busy = false;
        root.querySelectorAll('button').forEach(b => b.disabled = false);
        status.textContent = words('操作失败，请重试','Operation failed. Try again.');
        focus(currentButton());
    }
    function activate(button) {
        if (busy || !button || !root.contains(button) || button.disabled) return;
        // Hardware confirmation is an action, not a synthetic touch click:
        // a deliberately disabled touchscreen must not block the keypad.
        if (button.hasAttribute('data-cancel')) { if (selected) { selected = null; paint(); } else close(); }
        else if (Object.prototype.hasOwnProperty.call(actions, button.dataset.power)) { selected = button.dataset.power; paint(); }
        else if (button.hasAttribute('data-confirm')) execute();
    }
    function open() {
        if (isOpen() || !root) return;
        previousFocus = document.activeElement;
        if (blank) setBlank(false);
        clearTimeout(idleTimer);
        selected = null;
        lastBack = lastMove = -Infinity;
        root.hidden = false;
        document.body.classList.add('power-menu-open');
        paint();
        post('vibrate', {ms:80});
        console.log('t551m-screen: power menu');
    }
    function key(event) {
        if (!root) return;
        const kind = keyKind(event);
        if (window.T551MCalls?.forwardKey(event)) { cancelHold(); return; }
        // The phone SDK captures the red key while a live call exists.
        // Keep idle/dark-screen power behavior and all other plugins unchanged.
        if (!isOpen() && !blank && kind === 'power' && appOpen?.id === 'phone' && appCapturePower) {
            cancelHold();return;
        }
        if (kind === 'power') {
            event.preventDefault(); event.stopImmediatePropagation();
            if (event.type === 'keydown') {
                if (event.repeat || held) return;
                const press = held = {fired:false, timer:null};
                press.timer = setTimeout(() => {
                    if (held !== press) return;
                    press.fired = true;
                    open();
                }, 1200);
            } else {
                if (!held) return;
                const fired = held.fired;
                cancelHold();
                if (!fired) { if (isOpen()) close(); else setBlank(!blank); }
            }
            return;
        }
        // Capture in both the shell and plugin frames, before the legacy
        // any-key wake and call-key handlers. Only power wakes a dark lock.
        if (blank && !['volup','voldown'].includes(kind)) {
            event.preventDefault(); event.stopImmediatePropagation();
            return;
        }
        if (!isOpen()) return;
        event.preventDefault(); event.stopImmediatePropagation();
        if (event.type !== 'keydown' || busy) return;
        const navigation = ['up','down','left','right'].includes(kind) || event.key === 'Tab';
        if (event.repeat && !navigation) return;
        if (kind === 'back') {
            const now = performance.now();
            // Some keypads emit BrowserBack and Backspace for the same press.
            if (now - lastBack < 150) return;
            lastBack = now;
            if (selected) { selected = null; paint(); } else close();
        }
        else if (kind === 'ok') activate(currentButton());
        else if (navigation) {
            const now = performance.now();
            if (event.repeat && now - lastMove < 100) return;
            lastMove = now;
            const list = buttons();
            if (!list.length) return;
            const step = ['up','left'].includes(kind) || event.shiftKey ? -1 : 1;
            const index = list.indexOf(currentButton());
            focus(list[index < 0 ? (step > 0 ? 0 : list.length - 1) : (index+step+list.length)%list.length]);
        }
    }
    function attach(target) {
        const doc = target?.document;
        if (!doc || wired.has(doc)) return;
        wired.add(doc);
        target.addEventListener('keydown', key, true);
        target.addEventListener('keyup', key, true);
    }
    function boot() {
        root = document.createElement('div');
        root.id = 'power-menu'; root.hidden = true;
        document.body.appendChild(root);
        root.addEventListener('focusin', event => remember(event.target.closest('button')));
        for (const name of ['touchstart','touchmove','touchend','pointerdown','pointermove','pointerup'])
            root.addEventListener(name, event => event.stopPropagation());
        root.addEventListener('click', event => {
            event.stopPropagation();
            if (busy) return;
            const button = event.target.closest('button');
            if (!button) { if (event.target === root) close(); return; }
            activate(button);
        });
    }
    attach(window);
    window.addEventListener('blur', () => { if (held && !held.fired) cancelHold(); });
    document.addEventListener('visibilitychange', () => { if (document.hidden) cancelHold(); });
    return {boot, attach, isOpen, close};
})();
