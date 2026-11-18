// Exercise the production click handlers without issuing real control RPCs.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname,
  '../luci-app-t551m/htdocs/luci-static/resources/view/mu300/home.js'), 'utf8');
const deferred = () => { let resolve, reject; const promise = new Promise((r,j) => { resolve = r; reject = j; }); return {promise, resolve, reject}; };
function fixture(on = false) {
  const buttons = {}, confirmations = [], requests = [], jobs = [], toasts = [];
  const root = {isConnected: true, querySelectorAll(){return [];}, querySelector(id) {
    return buttons[id] ||= {disabled: false, addEventListener() {}};
  }};
  const M = {
    confirmBox(...args) { const d = deferred(); confirmations.push({args, ...d}); return d.promise; },
    callAct(...args) { const d = deferred(); requests.push({args, ...d}); return d.promise; },
    busy(btn,on) { btn.busy=on; }, toast(message,options) { toasts.push({message,options}); },
  };
  const view = new Function('view', 'M', 'L', 'SimRadio', source)({extend: x => x}, M,
    {resolveDefault: p => p.catch(() => undefined)},
    {wait(job) { const d=deferred();jobs.push(d);return d.promise; }});
  view.refreshLock = () => {};
  view.wire(root);
  view.lastInfo = {wan: {up: on}, wifi: {up: on}};
  view.lastCell = {cfun: on ? 1 : 0};
  return {view, root, confirmations, requests, jobs, buttons, toasts,
    click: name => buttons['#mud-btn-' + name].onclick()};
}
async function flush() { await Promise.resolve(); await Promise.resolve(); }
(async () => {
  for (const on of [false, true]) {
    for (const [button, op, arg] of [
      ['data', 'data', on ? 'down' : 'up'], ['wifi', 'wifi', on ? 'off' : 'on'],
      ['radio', 'radio', on ? 'off' : 'on'], ['modem', 'modem-reset', null],
      ['reboot', 'reboot', null], ['android', 'os', 'android'],
    ]) {
      const f = fixture(on);
      let done = f.click(button);
      assert.equal(f.requests.length, 0, 'no request before confirmation');
      assert.equal(f.confirmations.length, 1);
      f.click(button); f.click('reboot');
      assert.equal(f.confirmations.length, 1, 'only one pending dialog');
      f.confirmations[0].resolve(false); await done;
      assert.equal(f.requests.length, 0, 'cancel must do nothing');
      done = f.click(button); f.confirmations[1].resolve(true); await flush();
      assert.deepEqual(f.requests[0].args, [op, arg]);
      f.click(button); assert.equal(f.confirmations.length, 2, 'pending RPC blocks repeats');
      f.requests[0].resolve({ok: true}); await done;
      assert.equal(f.view._quickPending, false);
    }
  }
  for (const leave of ['unload', 'detach']) {
    const f = fixture(); const done = f.click('reboot');
    if (leave === 'unload') f.view.unload(); else f.root.isConnected = false;
    f.confirmations[0].resolve(true); await done;
    assert.equal(f.requests.length, 0, 'leaving the page cancels control');
  }
  for (const outcome of ['done','error','unload']) {
    const f=fixture(true),done=f.click('radio');
    f.confirmations[0].resolve(true);await flush();
    f.requests[0].resolve({ok:true,id:'radio-job'});await flush();
    assert.equal(f.jobs.length,1);
    assert(f.view._quickPending && f.buttons['#mud-btn-radio'].busy);
    const before=f.toasts.length;
    if(outcome==='error')f.jobs[0].reject(new Error('modem_busy'));
    else {
      if(outcome==='unload')f.view.unload();
      f.jobs[0].resolve(outcome==='unload'?null:{ok:true,state:'done'});
    }
    await done;
    assert(!f.view._quickPending && !f.buttons['#mud-btn-radio'].busy);
    if(outcome==='unload')assert.equal(f.toasts.length,before);
    else assert.equal(f.toasts.at(-1).options.type,outcome==='done'?'success':'error');
  }
  const f = fixture(); f.root.querySelector('#mud-btn-data').disabled = true;
  f.click('data'); assert.equal(f.confirmations.length, 0);
  console.log('PASS: all six controls, both toggle directions, cancel, duplicate clicks, pending RPC, page exit, disabled control');
})().catch(error => {console.error(error); process.exitCode = 1;});
