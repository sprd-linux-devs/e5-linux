'use strict';
(() => {
 const button = document.getElementById('switch');
 const label = document.getElementById('state');
 const hint = document.getElementById('hint');
 const errorNode = document.getElementById('error');
 const retry = document.getElementById('retry');
 const texts = {
  title: {zh:'手电筒',en:'Flashlight',tr:'El feneri'},
  on: {zh:'已开启',en:'On',tr:'Açık'},
  off: {zh:'已关闭',en:'Off',tr:'Kapalı'},
  loading: {zh:'读取中…',en:'Reading…',tr:'Okunuyor…'},
  changing: {zh:'切换中…',en:'Switching…',tr:'Değiştiriliyor…'},
  unknown: {zh:'状态未知',en:'State unknown',tr:'Durum bilinmiyor'},
  turnOn: {zh:'轻点打开',en:'Tap to turn on',tr:'Açmak için dokunun'},
  turnOff: {zh:'轻点关闭',en:'Tap to turn off',tr:'Kapatmak için dokunun'},
  retry: {zh:'重新读取',en:'Read again',tr:'Yeniden oku'},
  unavailable: {zh:'手电筒驱动未就绪',en:'Flashlight driver is not ready',tr:'El feneri sürücüsü hazır değil'},
  failed: {zh:'操作未确认，请重新读取状态',en:'Operation not confirmed; read the state again',tr:'İşlem doğrulanamadı; durumu yeniden okuyun'},
  read: {zh:'无法读取手电筒状态',en:'Cannot read flashlight state',tr:'El feneri durumu okunamıyor'}
 };
 let state = null, busy = false, action = '', error = '';
 const t = key => e5.t(texts[key]);
 function render() {
  document.documentElement.lang = e5.lang;
  document.title = t('title');
  button.classList.toggle('on', state === true);
  button.setAttribute('aria-pressed', state == null ? 'mixed' : String(state));
  button.setAttribute('aria-busy', String(busy));
  button.setAttribute('aria-label', t('title') + ' · ' + (state == null ? t('unknown') : t(state ? 'turnOff' : 'turnOn')));
  button.disabled = busy || state == null;
  label.textContent = busy ? t(action) : state == null ? t('unknown') : t(state ? 'on' : 'off');
  hint.textContent = busy || state == null ? '' : t(state ? 'turnOff' : 'turnOn');
  errorNode.textContent = error ? t(error) : '';
  errorNode.hidden = !error;
  retry.hidden = !error;
  retry.disabled = busy;
  retry.textContent = t('retry');
 }
 function accept(result) {
  state = result?.available === true && typeof result.on === 'boolean' ? result.on : null;
  if (result?.ok !== true) throw new Error(result?.error || 'unavailable');
  if (state == null) throw new Error('unavailable');
 }
 async function refresh() {
  if (busy) return;
  busy = true; action = 'loading'; state = null; error = ''; render();
  try { accept(await e5.api('/state')); }
  catch (failure) { error = failure.message === 'unavailable' ? 'unavailable' : 'read'; }
  finally { busy = false; render(); }
 }
 async function toggle() {
  if (busy || state == null) return;
  busy = true; action = 'changing'; error = ''; render();
  try { accept(await e5.api('/toggle', {body:{}})); }
  catch (failure) {
   // The write may have succeeded before a transport timeout. Never retry it:
   // obtain a fresh state instead, so another tap cannot reverse it blindly.
   state = null;
   try { accept(await e5.api('/state')); } catch (_) { state = null; }
   error = failure.message === 'unavailable' ? 'unavailable' : 'failed';
  } finally { busy = false; render(); }
 }
 function syncTheme() {
  let host;
  try { host = window.parent !== window && window.parent.document.body; } catch (_) { return; }
  if (!host) return;
  const root = document.documentElement, style = window.parent.getComputedStyle(host);
  for (const key of ['--bg','--text','--dim','--accent','--poor','--surface-rgb','--button-rgb','--ui-scale','--surface-alpha','--wallpaper-wash'])
   root.style.setProperty(key, style.getPropertyValue(key).trim());
  root.dataset.theme = host.dataset.theme || 'dark';
  for (const name of ['desktop-wallpaper','no-motion']) root.classList.toggle(name, host.classList.contains(name));
  root.style.setProperty('--desktop-wallpaper', host.style.getPropertyValue('--desktop-wallpaper'));
  const rect = window.frameElement.getBoundingClientRect();
  root.style.setProperty('--wallpaper-width', window.parent.innerWidth + 'px');
  root.style.setProperty('--wallpaper-height', window.parent.innerHeight + 'px');
  root.style.setProperty('--wallpaper-offset', -rect.top + 'px');
  root.style.setProperty('--wallpaper-left', -rect.left + 'px');
 }
 button.addEventListener('click', toggle);
 retry.addEventListener('click', refresh);
 e5.onLang(render);
 e5.onKey(event => {
  if (event.kind !== 'ok') return false;
  if (!event.repeat) e5.press(state == null ? retry : button);
  return true;
 });
 document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
 window.addEventListener('pageshow', event => { if (event.persisted) refresh(); });
 // A screen wake is an event, not a background polling timer.
 window.addEventListener('message', event => {
  if (event.source === window.parent && event.data?.e5 === 'blank' && event.data.on === false) refresh();
 });
 window.addEventListener('resize', syncTheme);
 let observer;
 if (window.parent !== window) {
  try {
   observer = new MutationObserver(syncTheme);
   observer.observe(window.parent.document.body, {attributes:true, attributeFilter:['class','style','data-theme','data-accent']});
   window.parent.addEventListener('resize', syncTheme);
  } catch (_) { /* Standalone or cross-origin host: use the local palette. */ }
 }
 window.addEventListener('pagehide', () => {
  observer?.disconnect();
  if (window.parent !== window) window.parent.removeEventListener('resize', syncTheme);
 });
 syncTheme();
 refresh();
})();
