/* Incoming calls have their own wake path; the lock underneath stays locked. */
'use strict';
window.T551MCalls = (() => {
    const live = new Set(['dialing','ringing-out','ringing-in','waiting','active','held']);
    let showing=false, ringing=new Set(), guardUntil=0, booted=false;
    const guarded=new WeakSet();
    const listeners=new Set();
    let latest=null, stream=null, streaming=false, pollTimer=null, polling=false, stopped=false;
    const active=()=>showing;
    function attach(frame) {
        const doc=frame.contentDocument;
        if(!doc||guarded.has(doc))return;
        guarded.add(doc);
        for(const type of ['touchstart','touchend','pointerdown','pointerup','mousedown','mouseup','click'])
            frame.contentWindow.addEventListener(type,event=>{
                if(showing && (blank || performance.now()<guardUntil || last?.screen?.touch===false)) {
                    event.preventDefault();event.stopImmediatePropagation();
                }
            },{capture:true,passive:false});
    }
    function update(data) {
        if(data.error || !Array.isArray(data.calls))return;
        const calls=data.calls.filter(c=>live.has(c.state));
        const incoming=calls.filter(c=>c.state==='ringing-in'||c.state==='waiting');
        const fresh=incoming.some(c=>!ringing.has(String(c.id)));
        ringing=new Set(incoming.map(c=>String(c.id)));
        if(incoming.length && (fresh || (!showing && !blank))) {
            if(blank && data.wake===false)return;
            if(blank)setBlank(false);
            if(T551MPower.isOpen())T551MPower.close();
            if(!showing){
                showing=true;
                guardUntil=performance.now()+600;
                document.body.classList.add('phone-overlay');
                clearTimeout(idleTimer);
                if(appOpen)closeApp();
                openApp({id:'phone',name:{zh:'电话',en:'Phone'},entry:'index.html',callOverlay:true});
                applyTouch();
            }
        }
        if(showing && !calls.length){
            showing=false;
            document.body.classList.remove('phone-overlay');
            if(appOpen?.id==='phone')closeApp();
            applyTouch();resetIdle();
        }
    }
    function deliver(data) {
        latest=data;update(data);
        for(const listener of listeners) { try {listener(data);} catch(e) {console.log('call listener: '+e);} }
    }
    function subscribe(listener) {
        listeners.add(listener);
        if(latest)listener(latest);
        return ()=>listeners.delete(listener);
    }
    function screenWake() {
        // An incoming call with wake=false is still retained by the stream.
        // Manual/external wake must show it even if no new call event arrives.
        if (!stopped && !blank && latest) update(latest);
    }
    function forwardKey(event) {
        // A keypad event can land on the shell after focus moves away from
        // the call frame. Send it through the same SDK/phone key handler;
        // never issue another call action or unlock the underlying screen.
        if (event.currentTarget !== window || blank || appOpen?.id !== 'phone' || T551MPower.isOpen()) return false;
        const kind = keyKind(event);
        if (kind !== 'call' && kind !== 'power' && event.key !== 'HangupPhone') return false;
        if (!appCapturePower && (kind !== 'call' || locked || T551M.isLocked())) return false;
        event.preventDefault();event.stopImmediatePropagation();resetIdle();
        if (event.type === 'keydown') toApp({e5:'hardware-key',kind,key:event.key,code:event.code,repeat:event.repeat});
        return true;
    }
    async function pollCalls() {
        clearTimeout(pollTimer);pollTimer=null;
        if(stopped || streaming || polling)return;
        polling=true;
        const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),2500);
        try {
            const response=await fetch('/api/plugins/phone/live',{cache:'no-store',signal:controller.signal});
            const data=await response.json();
            if(response.ok && !streaming && !stopped)deliver(data);
        } catch(_) {} finally {
            clearTimeout(timeout);polling=false;
            if(!stopped && !streaming)pollTimer=setTimeout(pollCalls,350);
        }
    }
    function boot(){
        if(booted)return;booted=true;
        // One stream for both the shell and the phone frame. The existing
        // observer pushes only changes; idle UI no longer wakes every 350ms.
        if(typeof EventSource==='function' && location.hostname==='127.0.0.1') {
            stream=new EventSource('http://127.0.0.1:8089/events');
            stream.onmessage=event=>{
                try {
                    const data=JSON.parse(event.data);
                    if(data.error || !Array.isArray(data.calls)) {streaming=false;pollCalls();return;}
                    streaming=true;clearTimeout(pollTimer);pollTimer=null;deliver(data);
                }catch(_) {streaming=false;pollCalls();}
            };
            stream.onerror=()=>{streaming=false;pollCalls();};
            pollTimer=setTimeout(pollCalls,1500);
        } else pollCalls();
    }
    window.addEventListener('pagehide',()=>{stopped=true;stream?.close();clearTimeout(pollTimer);listeners.clear();});
    window.addEventListener('pageshow',event=>{if(event.persisted){stopped=false;booted=false;boot();}});
    return {active,update,attach,boot,subscribe,screenWake,forwardKey};
})();
