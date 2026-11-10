'use strict';

/* eSIM WebApp for the E5 info screen. */

const app = document.getElementById('app');
const tabs = document.getElementById('sim-tabs');
const tabNodes = [document.getElementById('sim-tab-0'), document.getElementById('sim-tab-1')];
const titleNode = document.getElementById('screen-title');
const subtitleNode = document.getElementById('screen-subtitle');
const slotBadge = document.getElementById('slot-badge');
const topbar = document.querySelector('.topbar');

const SE_AIDS = ['A06573746B6D65FFFF4953442D522030', 'A06573746B6D65FFFF4953442D522031'];
const POLL_MS = 1000;
const THEME_VARS = ['--bg', '--surface-rgb', '--button-rgb', '--active-rgb', '--text', '--dim',
 '--line', '--accent', '--ui-opacity'];

const TR = {
 "Cannot reach the eSIM": "eSIM’e erişilemiyor",
 "The activation code is invalid": "Etkinleştirme kodu geçersiz",
 "This activation code requires a confirmation code": "Bu etkinleştirme kodu için onay kodu gerekiyor",
 "Cannot read the eSIM": "eSIM okunamıyor",
 "Cannot reach the server": "Sunucuya erişilemiyor",
 "The profile was not found": "Profil bulunamadı",
 "Disable the profile first": "Önce profili devre dışı bırakın",
 "The profile is not enabled": "Profil etkin değil",
 "The eSIM policy does not allow it": "eSIM ilkesi bu işleme izin vermiyor",
 "The operation timed out": "İşlem zaman aşımına uğradı",
 "The eSIM is busy; try again later": "eSIM meşgul; daha sonra tekrar deneyin",
 "The operation failed; try again": "İşlem başarısız; tekrar deneyin",
 "The operation failed": "İşlem başarısız",
 "Invalid status": "Geçersiz durum",
 "Read the card first": "Önce kartı okuyun",
 "Profile state has not updated; try again later": "Profil durumu güncellenmedi; daha sonra tekrar deneyin",
 "SIM refresh failed": "SIM yenilenemedi",
 "Operation completed; open Notifications to retry reporting": "İşlem tamamlandı; bildirimleri yeniden göndermek için Bildirimler’i açın",
 "Operation completed; retry pending notifications from Notifications": "İşlem tamamlandı; bekleyen bildirimleri Bildirimler’den yeniden gönderin",
 "Deleting notification %d/%d…": "Bildirim siliniyor %d/%d…",
 "Handling notification %d/%d…": "Bildirim işleniyor %d/%d…",
 "Switching profile…": "Profil değiştiriliyor…",
 "Renaming…": "Yeniden adlandırılıyor…",
 "Deleting the profile…": "Profil siliniyor…",
 "Handling the notification…": "Bildirim işleniyor…",
 "Working…": "İşlem sürüyor…",
 "Some notifications could not be handled; try again later": "Bazı bildirimler işlenemedi; daha sonra tekrar deneyin",
 "Deleted %d notifications": "%d bildirim silindi",
 "Handled %d notifications": "%d bildirim işlendi",
 "Disable profile": "Profili devre dışı bırak",
 "Enable profile": "Profili etkinleştir",
 "The profile becomes unusable. If modem information stays stale, refresh it in SIM management.": "Profil kullanılamaz olur. Modem bilgisi güncellenmezse SIM yönetiminden yenileyin.",
 "This changes the active profile and may interrupt this SIM. The modem will not be reset automatically.": "Etkin profil değişir ve SIM bağlantısı kesilebilir. Modem otomatik sıfırlanmaz.",
 "Disable": "Devre dışı bırak",
 "Enable": "Etkinleştir",
 "Delete profile": "Profili sil",
 "This cannot be undone.": "Bu işlem geri alınamaz.",
 "Delete": "Sil",
 "Delete all notifications": "Tüm bildirimleri sil",
 "Enter the activation code": "Etkinleştirme kodunu girin",
 "Cancelling download…": "İndirme iptal ediliyor…",
 "Reporting download…": "İndirme bildiriliyor…",
 "Cannot continue the download": "İndirmeye devam edilemiyor",
 "Download cancelled": "İndirme iptal edildi",
 "Profile downloaded": "Profil indirildi",
 "eSIM chip": "eSIM çipi",
 "Notifications": "Bildirimler",
 "Add profile": "Profil ekle",
 "Rename": "Yeniden adlandır",
 "eSIM management": "eSIM yönetimi",
 "Installing components": "Bileşenler yükleniyor",
 "Components required": "Bileşenler gerekli",
 "Profiles, downloads and notifications": "Profiller, indirmeler ve bildirimler",
 "Runtime components missing": "Çalışma bileşenleri eksik",
 "Pending notifications": "Bekleyen bildirimler",
 "EID, versions and space": "EID, sürümler ve alan",
 "Profile details": "Profil ayrıntıları",
 "Enter an activation code": "Etkinleştirme kodu girin",
 "Confirm carrier details": "Operatör bilgilerini onaylayın",
 "Downloading profile": "Profil indiriliyor",
 "Notification details": "Bildirim ayrıntıları",
 "Please wait": "Lütfen bekleyin",
 "Starting…": "Başlatılıyor…",
 "Reading the eSIM…": "eSIM okunuyor…",
 "The first read can take a few seconds": "İlk okuma birkaç saniye sürebilir",
 "Reading notifications…": "Bildirimler okunuyor…",
 "eSIM components are required": "eSIM bileşenleri gerekli",
 "Install current complete firmware containing eSIM components; this page does not install software in the background.": "eSIM bileşenlerini içeren güncel tam yazılımı kurun; bu sayfa arka planda yazılım kurmaz.",
 "Check again": "Yeniden kontrol et",
 "Select SE": "SE seç",
 "No eUICC in this slot": "Bu yuvada eUICC yok",
 "Retry": "Tekrar dene",
 "Details ›": "Ayrıntılar ›",
 "Firmware": "Yazılım",
 "Profiles": "Profiller",
 "Add": "Ekle",
 "No profiles installed": "Yüklü profil yok",
 "Enabled": "Etkin",
 "Disabled": "Devre dışı",
 "Profile format": "Profil biçimi",
 "Free storage": "Boş depolama",
 "Free RAM": "Boş RAM",
 "Signing certificate key IDs": "İmzalama sertifikası anahtar kimlikleri",
 "Verification certificate key IDs": "Doğrulama sertifikası anahtar kimlikleri",
 "SAS accreditation": "SAS akreditasyonu",
 "Back": "Geri",
 "Process all": "Tümünü işle",
 "Delete all": "Tümünü sil",
 "Notification": "Bildirim",
 "No pending notifications": "Bekleyen bildirim yok",
 "Server": "Sunucu",
 "Process": "İşle",
 "Provider": "Sağlayıcı",
 "Status": "Durum",
 "Confirm": "Onayla",
 "Cancel": "İptal",
 "Name": "Ad",
 "Save": "Kaydet",
 "Activation code": "Etkinleştirme kodu",
 "Confirmation code (optional)": "Onay kodu (isteğe bağlı)",
 "Download": "İndir",
 "Confirm profile download": "Profil indirmeyi onayla",
 "Profile name": "Profil adı",
 "Profile class": "Profil sınıfı",
 "Write progress": "Yazma ilerlemesi",
 "Waiting for the server": "Sunucu bekleniyor",
 "Cancel download": "İndirmeyi iptal et",
 "Confirming the installation…": "Yükleme sonucu doğrulanıyor…",
 "Preparing profile data": "Profil verisi hazırlanıyor",
 "Waiting for a response…": "Yanıt bekleniyor…",
 "Install": "Yükle"
};

function zh() {
 return e5.lang === 'zh' || String(e5.lang || 'zh').startsWith('zh-');
}

function t(zhText, enText) {
 return zh() ? zhText : e5.lang === 'tr' ? (TR[enText] || enText) : enText;
}

function isObject(value) {
 return !!value && typeof value === 'object' && !Array.isArray(value);
}

function failureOf(value) {
 if (!isObject(value))
  return {};
 return { error: value.error || '', detail: value.detail || '' };
}

function jget(value, path) {
 return path.split('.').reduce((current, key) => current == null ? undefined : current[key], value);
}

function profileName(profile) {
 return String(profile && (profile.profileNickname || profile.profileName || profile.iccid) || '--');
}

function operationName(operation) {
 const names = {
  install: ['安装', 'Install'],
  enable: ['启用', 'Enable'],
  disable: ['停用', 'Disable'],
  delete: ['删除', 'Delete']
 };
 const pair = names[operation];
 return pair ? t(pair[0], pair[1]) : String(operation || '--');
}

function bytes(value) {
 let number = Number(value);
 if (!Number.isFinite(number) || number < 0)
  return '--';
 const units = ['B', 'KB', 'MB', 'GB', 'TB'];
 let index = 0;
 while (number >= 1024 && index < units.length - 1) {
  number /= 1024;
  index++;
 }
 return number.toFixed(number >= 100 || index === 0 ? 0 : 1) + ' ' + units[index];
}

const JOB_ERRORS = {
 "server_ca": [
  "eSIM 信任证书缺失或损坏，请更新完整固件",
  "eSIM trust certificate is missing or damaged; update the complete firmware"
 ],
 "server_tls": [
  "服务器证书校验失败，请核对设备时间和 CA 证书",
  "Server certificate verification failed; check the device clock and CA certificates"
 ],
 "server_timeout": [
  "运营商服务器连接超时",
  "Operator server connection timed out"
 ],
 "server_unavailable": [
  "无法连接运营商服务器，请检查设备网络",
  "Cannot connect to the operator server; check the device network"
 ],
 "scan_required": [
  "请先读取卡片",
  "Read the card first"
 ],
 "card_changed": [
  "卡槽已改变，请重新读取",
  "The card changed; read it again"
 ],
 "operation_busy": [
  "已有 eUICC 操作正在执行",
  "An eUICC operation is already running"
 ],
 "modem_busy": [
  "模组正忙，请稍后重试",
  "The modem is busy; try again later"
 ],
 "operation_interrupted": [
  "操作中断，请重新读取卡片确认结果，不要直接重复下载或删除",
  "Operation interrupted; read the card to check the result. Do not repeat downloads or deletions"
 ],
 "operation_timeout": [
  "操作超时，请重新读取卡片确认结果",
  "Operation timed out; read the card to check the result"
 ],
 "lpac_missing": [
  "系统未安装 lpac，请更新完整固件",
  "lpac is missing; update the complete firmware"
 ],
 "activation_invalid": [
  "激活码格式无效",
  "Invalid activation code format"
 ],
 "profile_enabled": [
  "请先停用此配置再删除",
  "Disable the profile before deleting it"
 ],
 "profile_missing": [
  "配置已不存在，请重新读取",
  "The profile no longer exists; read the card again"
 ],
 "readback_failed": [
  "操作已提交，但回读未确认，请重新读取卡片，不要重复执行",
  "Operation submitted but readback was not confirmed. Read the card; do not repeat the operation"
 ],
 "not_euicc": [
  "当前卡不是 eUICC，或无法选择其管理应用",
  "This card is not an eUICC, or its management application is unavailable"
 ],
 "at_timeout": [
  "AT 请求超时，请重新读取确认卡片状态",
  "AT request timed out; read the card to check its state"
 ],
 "at_rejected": [
  "模组拒绝了 APDU 请求，请核对接口设置",
  "The modem rejected the APDU request; check the interface settings"
 ],
 "lpac_failed": [
  "操作失败，请重新读取卡片确认状态",
  "Operation failed; read the card to check its state"
 ],
 "operation_failed": [
  "操作失败，请重新读取卡片确认状态",
  "Operation failed; read the card to check its state"
 ],
 "cancelled": [
  "操作已取消，请重新读取卡片确认状态",
  "Operation cancelled; read the card to check its state"
 ],
 "invalid_job": [
  "任务已不存在，请重新读取卡片确认状态",
  "The task no longer exists; read the card to check its state"
 ]
};
Object.assign(TR,{
 "eSIM trust certificate is missing or damaged; update the complete firmware": "eSIM güven sertifikası eksik veya bozuk; tam aygıt yazılımını güncelleyin",
 "Server certificate verification failed; check the device clock and CA certificates": "Sunucu sertifikası doğrulanamadı; cihaz saatini ve CA sertifikalarını kontrol edin",
 "Operator server connection timed out": "Operatör sunucusu bağlantısı zaman aşımına uğradı",
 "Cannot connect to the operator server; check the device network": "Operatör sunucusuna bağlanılamıyor; cihaz ağını kontrol edin",
 "Read the card first": "Önce kartı okuyun",
 "The card changed; read it again": "Kart değişti; yeniden okuyun",
 "An eUICC operation is already running": "Bir eUICC işlemi zaten çalışıyor",
 "The modem is busy; try again later": "Modem meşgul; daha sonra tekrar deneyin",
 "Operation interrupted; read the card to check the result. Do not repeat downloads or deletions": "İşlem kesildi; sonucu kontrol etmek için kartı okuyun. İndirme veya silme işlemini tekrarlamayın",
 "Operation timed out; read the card to check the result": "İşlem zaman aşımına uğradı; sonucu kontrol etmek için kartı okuyun",
 "lpac is missing; update the complete firmware": "lpac eksik; tam aygıt yazılımını güncelleyin",
 "Invalid activation code format": "Geçersiz etkinleştirme kodu biçimi",
 "Disable the profile before deleting it": "Silmeden önce profili devre dışı bırakın",
 "The profile no longer exists; read the card again": "Profil artık mevcut değil; kartı yeniden okuyun",
 "Operation submitted but readback was not confirmed. Read the card; do not repeat the operation": "İşlem gönderildi ancak geri okuma doğrulanamadı. Kartı okuyun; işlemi tekrarlamayın",
 "This card is not an eUICC, or its management application is unavailable": "Bu kart eUICC değil veya yönetim uygulaması kullanılamıyor",
 "AT request timed out; read the card to check its state": "AT isteği zaman aşımına uğradı; durumunu kontrol etmek için kartı okuyun",
 "The modem rejected the APDU request; check the interface settings": "Modem APDU isteğini reddetti; arayüz ayarlarını kontrol edin",
 "Operation failed; read the card to check its state": "İşlem başarısız; durumunu kontrol etmek için kartı okuyun",
 "Operation cancelled; read the card to check its state": "İşlem iptal edildi; durumunu kontrol etmek için kartı okuyun",
 "The task no longer exists; read the card to check its state": "Görev artık mevcut değil; durumunu kontrol etmek için kartı okuyun"
});

function failureText(value) {
 const failure = failureOf(value);
 const error = failure.error;
 const detail = failure.detail;
 if (JOB_ERRORS[error]) return t(...JOB_ERRORS[error]);
 if (error === 'euicc_init')
  return t('无法访问 eSIM', 'Cannot reach the eSIM');
 if (error === 'activation_code' || error === 'matching_id')
  return t('激活码无效', 'The activation code is invalid');
 if (error === 'confirmation_code' && detail === 'required')
  return t('该激活码需要确认码', 'This activation code requires a confirmation code');
 if (error === 'es10c_get_profiles_info' || error === 'es10b_list_notification')
  return t('读取 eSIM 失败', 'Cannot read the eSIM');
 if ((error.indexOf('es9p_') === 0 || error.indexOf('es8p_') === 0) &&
  (detail.indexOf('HTTP') >= 0 || detail.indexOf('http') >= 0))
  return t('服务器通信失败', 'Cannot reach the server');
 if (detail.indexOf('iccid or aid not found') >= 0)
  return t('找不到该配置文件', 'The profile was not found');
 if (detail.indexOf('profile not in disabled state') >= 0)
  return t('请先停用该配置文件', 'Disable the profile first');
 if (detail.indexOf('profile not in enabled state') >= 0)
  return t('该配置文件未启用', 'The profile is not enabled');
 if (detail.indexOf('disallowed by policy') >= 0)
  return t('eSIM 策略不允许', 'The eSIM policy does not allow it');
 if (detail.indexOf('timeout') >= 0 || detail.indexOf('Timeout') >= 0)
  return t('操作超时', 'The operation timed out');
 if (error === 'busy')
  return t('eSIM 正忙，请稍后再试', 'The eSIM is busy; try again later');
 if (error === 'lpac')
  return t('操作失败，请重试', 'The operation failed; try again');
 return detail || error || t('操作失败', 'The operation failed');
}

function toastFailure(value) {
 e5.toast(failureText(value));
}

function syncTheme() {
 let host = null;
 try { host = window.parent !== window && window.parent.document.body; } catch (error) { host = null; }
 if (!host)
  return;
 const root = document.documentElement;
 const palette = window.parent.getComputedStyle(host);
 THEME_VARS.forEach((name) => {
  const value = palette.getPropertyValue(name).trim();
  if (value)
   root.style.setProperty(name, value);
 });
 root.dataset.theme = host.dataset.theme || 'dark';
 root.classList.toggle('desktop-wallpaper', host.classList.contains('desktop-wallpaper'));
 root.style.setProperty('--desktop-wallpaper', host.style.getPropertyValue('--desktop-wallpaper'));
}

function h(tag, attrs, children) {
 const node = document.createElement(tag);
 if (attrs) {
  Object.entries(attrs).forEach(([name, value]) => {
   if (value == null || value === false)
    return;
   if (name === 'class')
    node.className = value;
   else if (name === 'focus')
    node.dataset.focus = value;
   else if (name === 'text')
    node.textContent = value;
   else if ((name === 'click' || name === 'input' || name === 'change') && typeof value === 'function')
    node.addEventListener(name, value);
   else if (name.startsWith('on') && typeof value === 'function')
    node.addEventListener(name.slice(2), value);
   else
    node.setAttribute(name, value === true ? '' : String(value));
  });
 }
 function append(value) {
  if (value == null || value === false)
   return;
  if (Array.isArray(value))
   value.forEach(append);
  else if (value instanceof Node)
   node.appendChild(value);
  else
   node.appendChild(document.createTextNode(String(value)));
 }
 append(children);
 return node;
}

function card(children, className) {
 return h('section', { class: 'card' + (className ? ' ' + className : '') }, children);
}

function heading(text, actions) {
 return h('div', { class: 'card-head' }, [h('h2', { text }), actions ? h('div', { class: 'card-actions' }, actions) : null]);
}

function message(text) {
 return h('p', { class: 'muted', text });
}

function kv(label, value, mono) {
 return h('div', { class: 'kv' }, [
  h('div', { class: 'k', text: label }),
  h('div', { class: 'v' + (mono ? ' mono' : '') }, value instanceof Node ? value : String(value == null || value === '' ? '--' : value))
 ]);
}

function button(label, kind, focus, handler, ariaLabel) {
 const node = h('button', {
  type: 'button',
  class: 'btn' + (kind ? ' ' + kind : ''),
  focus: focus || '',
  'aria-label': ariaLabel || null,
  click: handler
 }, label);
 return node;
}

function stateCard(title, hint, spinner) {
 return h('section', { class: 'card state-card' }, [
  spinner ? h('span', { class: 'spinner' }) : null,
  h('strong', { class: 'state-title', text: title }),
  hint ? h('p', { class: 'state-hint', text: hint }) : null
 ]);
}

function busyTap() {
 return !!state.action || state.downloading;
}

function newSlot() {
 return { chip: null, profiles: null, notifications: null, chipError: '', aid: '', ses: 0, scanned: false };
}

const slots = [newSlot(), newSlot()];
const state = {
 installed: null, installing: false, installError: null, installLog: '', dependencies: null,
 view: 'boot', slot: 0, pick: true,
 profile: null, notification: null, confirm: null,
 activation: '', confirmation: '', name: '',
 action: null, returnView: 'root', job: null, metadata: null,
 previewShown: false, cancelling: false, downloading: false, resuming: false,
 bulk: { total: 0, next: 0, remove: false }, waitText: '', disposed: false
};
let statusTimer = null;
let jobTimer = null;
let progressRefs = null;
let installLogFollow = true;
let installLogTop = 0;

function currentSlot() {
 return slots[state.slot];
}

function showRoot() {
 state.view = 'root';
 state.profile = null;
 state.notification = null;
 render();
}

function setView(view) {
 state.view = view;
 render();
}

function cleanInstallLog(value) {
 return String(value || '')
  .replace(/\u001b\][^\u0007]*(?:\u0007|\u001b\\)/g, '')
  .replace(/\u001b\[[0-?]*[ -/]*[@-~]/g, '')
  .replace(/\u001b[@-_]/g, '')
  .replace(/\r\n?/g, '\n')
  .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, '');
}

function logAtBottom(node) {
 return node.scrollHeight - node.scrollTop - node.clientHeight <= 8;
}

function logPanel() {
 const node = h('pre', { id: 'install-log', class: 'install-log', tabindex: '0' }, state.installLog);
 node.addEventListener('scroll', () => {
  installLogTop = node.scrollTop;
  installLogFollow = logAtBottom(node);
 });
 return node;
}

function paintInstallLog(initial) {
 const node = document.getElementById('install-log');
 if (!node)
  return false;
 if (node.textContent !== state.installLog) {
  const follow = initial ? installLogFollow : (installLogFollow || logAtBottom(node));
  const top = initial ? installLogTop : node.scrollTop;
  node.textContent = state.installLog;
  node.scrollTop = follow ? node.scrollHeight : top;
  installLogFollow = follow;
 } else if (initial) {
  node.scrollTop = installLogFollow ? node.scrollHeight : installLogTop;
 }
 installLogTop = node.scrollTop;
 return true;
}

function syncInstallView() {
 return state.view === 'install' && paintInstallLog(false);
}

function applyStatus(status) {
 if (!isObject(status))
  throw new Error(t('状态无效', 'Invalid status'));
 state.installed = status.installed === true;
 state.installing = status.installing === true;
 state.installError = status.error || null;
 if (typeof status.log === 'string')
  state.installLog = cleanInstallLog(status.log);
 if (status.dependencies)
  state.dependencies = normalizeDependencies(status.dependencies) || status.dependencies;
}

function scheduleStatusPoll() {
 if (statusTimer)
  return;
 statusTimer = window.setTimeout(async () => {
  statusTimer = null;
  if (state.disposed)
   return;
  try {
   applyStatus(await e5.api('/status'));
   if (state.installing) {
    state.view = 'install';
    if (!syncInstallView())
     render();
    scheduleStatusPoll();
    return;
   }
   if (state.installed) {
    await initialize();
    return;
   }
   state.view = 'install';
   render();
  } catch (error) {
   state.installing = false;
   state.installError = error && error.message ? error.message : String(error);
   state.view = 'install';
   render();
  }
 }, POLL_MS);
}

function stopStatusPoll() {
 if (statusTimer) {
  window.clearTimeout(statusTimer);
  statusTimer = null;
 }
}

function normalizeDependencies(value) {
 if (!isObject(value) || value.ok === false || !isObject(value.data))
  return null;
 const data = value.data;
 const missing = Array.isArray(data.missing) ? data.missing.filter((item) => typeof item === 'string') : [];
 return { ready: data.ready === true, missing, items: Array.isArray(data.items) ? data.items : [] };
}

function dependencyReady() {
 const deps = state.dependencies;
 return !deps || deps.ready || (!deps.missing || !deps.missing.length);
}

async function initialize() {
 stopStatusPoll();
 const [depsResult, job] = await Promise.all([
  rpc('dependencies').catch(() => null),
  rpc('job_status').catch(() => null)
 ]);
 const rpcDeps = normalizeDependencies(depsResult);
 if (rpcDeps)
  state.dependencies = rpcDeps;
 if (!dependencyReady()) {
  state.view = 'deps';
  render();
  return;
 }
 if (isObject(job) && job.running && job.type === 'download') {
  resumeDownload(job);
  return;
 }
 if (isObject(job) && job.running && job.type === 'operation') {
  resumeOperation(job);
  return;
 }
 state.view = 'loading';
 loadSlot();
}

async function checkStatus(initial) {
 try {
  applyStatus(await e5.api(initial ? '/status?check=1' : '/status'));
  if (state.installing) {
   state.view = 'install';
   render();
   scheduleStatusPoll();
   return;
  }
  stopStatusPoll();
  if (state.installed) {
   await initialize();
   return;
  }
  state.view = 'install';
  render();
 } catch (error) {
  state.installing = false;
  state.installError = error && error.message ? error.message : String(error);
  stopStatusPoll();
  state.view = 'install';
  render();
 }
}

// Adapted transport: every page uses the firmware's single job/AT owner.
let activeJob = null;
try { activeJob = sessionStorage.getItem('e5-esim-job') || null; } catch (error) {}
function nonce() { return Array.from(crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, '0')).join(''); }
async function rpc(method, params) {
 params = Object.assign({}, params || {});
 const start = method === 'operation_start' || method === 'download_start';
 const read = ['snapshot','profiles','notifications'].includes(method);
 if (start || read) params.job = nonce();
 if (start) {
  const chip = slots[params.slot].chip;
  if (!chip || !chip.eidValue) return {ok:false,error:'scan_required',detail:t('请先读取卡片', 'Read the card first')};
  params.eid = chip.eidValue;
  activeJob = params.job;
  sessionStorage.setItem('e5-esim-job', activeJob);
 }
 if (['job_status','job_confirm','job_cancel'].includes(method) && activeJob) params.job = activeJob;
 let result;
 try { result = await e5.api('/rpc', {method:'POST',body:{method,params}}); }
 catch (error) {
  // A lost acknowledgement does not permit replaying a write. Observe the
  // same client-generated job ID; invalid_job is an explicit interruption.
  if (start) return {ok:true,job:activeJob};
  throw error;
 }
 if (read && result && result.wait) {
  const job = result.job;
  do {
   if (state.disposed) return {ok:false,error:'cancelled'};
   result = await e5.api('/rpc',{method:'POST',body:{method:'job_status',params:{job,format:method}}});
   if (result.running) await new Promise(resolve => setTimeout(resolve, POLL_MS));
  } while (result.running);
 }
 if (method === 'job_status' && result && result.running && result.job && !activeJob) {
  activeJob = result.job;sessionStorage.setItem('e5-esim-job',activeJob);
 }
 if ((method === 'job_status' && result && !result.running) || (start && result && result.ok === false)) {
  activeJob = null;sessionStorage.removeItem('e5-esim-job');
 }
 return result;
}

function stopJobPoll() {
 if (jobTimer) {
  window.clearTimeout(jobTimer);
  jobTimer = null;
 }
}

function runJob(handler) {
 return async function tick() {
  let job = null;
  try {
   job = await rpc('job_status');
  } catch (error) {
   job = null;
  }
  if (state.disposed)
   return;
  const cont = await handler(job);
  if (cont !== false)
   jobTimer = window.setTimeout(tick, POLL_MS);
 };
}

async function watchJob(handler, initial) {
 stopJobPoll();
 if (initial) {
  const cont = await handler(initial);
  if (cont !== false && !state.disposed)
   jobTimer = window.setTimeout(runJob(handler), POLL_MS);
  return;
 }
 jobTimer = window.setTimeout(runJob(handler), POLL_MS);
}

async function loadSlot() {
 const target = currentSlot();
 target.chip = null;
 target.profiles = null;
 target.notifications = null;
 target.chipError = '';
 state.view = 'loading';
 render();
 await snap(state.slot);
}

async function snap(slot) {
 const target = slots[slot];
 const scan = !target.scanned;
 let result;
 try {
  result = await rpc('snapshot', { slot, aid: target.aid, scan });
 } catch (error) {
  result = null;
 }
 if (state.disposed || slot !== state.slot)
  return;
 if (!isObject(result) || result.ok === false) {
  if (state.pick) {
   state.pick = false;
   state.slot = 1;
   return snap(1);
  }
  target.chip = target.profiles = target.notifications = null;
  target.chipError = isObject(result) ? result.error || 'lpac' : 'lpac';
  showRoot();
  return;
 }
 state.pick = false;
 target.aid = result.aid || '';
 if (typeof result.ses === 'number')
  target.ses = result.ses;
 if (scan)
  target.scanned = true;
 if (isObject(result.chip) && result.chip.ok === false) {
  target.chipError = result.chip.error || result.error || 'lpac';
  target.chip = null;
 } else {
  target.chip = isObject(result.chip) ? (result.chip.data || null) : null;
  if (!target.chip)
   target.chipError = result.error || '';
 }
 if (isObject(result.profiles) && result.profiles.ok) {
  target.profiles = Array.isArray(result.profiles.data) ? result.profiles.data : [];
 } else if (isObject(result.profiles)) {
  target.profiles = null;
  toastFailure(result.profiles);
 }
 if (isObject(result.notifications) && result.notifications.ok) {
  target.notifications = Array.isArray(result.notifications.data) ? result.notifications.data : [];
 } else if (isObject(result.notifications)) {
  target.notifications = null;
 }
 showRoot();
}

function selectSlot(slot) {
 if (slot !== 0 && slot !== 1)
  return;
 if (busyTap() || !state.installed || (state.view !== 'root' && state.view !== 'notifications'))
  return;
 state.slot = slot;
 state.pick = false;
 state.profile = null;
 state.notification = null;
 loadSlot();
}

function selectSE(aid) {
 const target = currentSlot();
 if (target.aid === aid || busyTap())
  return;
 target.aid = aid;
 target.chip = target.profiles = target.notifications = null;
 target.chipError = '';
 state.profile = state.notification = null;
 state.view = 'loading';
 render();
 snap(state.slot);
}

function openProfile(index) {
 const target = currentSlot();
 if (!target.profiles || !target.profiles[index] || busyTap())
  return;
 state.profile = target.profiles[index];
 state.view = 'profile';
 render();
}

function openInfo() {
 state.view = 'info';
 render();
}

async function openNotifications() {
 if (busyTap())
  return;
 state.view = 'notif_loading';
 render();
 let result = null;
 try {
  result = await rpc('notifications', { slot: state.slot, aid: currentSlot().aid });
 } catch (error) {
  result = null;
 }
 if (state.disposed)
  return;
 if (isObject(result) && result.ok) {
  currentSlot().notifications = Array.isArray(result.data) ? result.data : [];
 } else {
  toastFailure(result);
 }
 state.view = 'notifications';
 render();
}

function openNotification(index) {
 const list = currentSlot().notifications || [];
 if (!list[index] || busyTap())
  return;
 state.notification = list[index];
 state.view = 'notification';
 render();
}

function openDownload() {
 if (busyTap())
  return;
 state.view = 'download';
 render();
}

function startOperation(request, returnView) {
 if (busyTap())
  return;
 state.action = request.action;
 state.returnView = returnView || (request.action === 'notifications' ? 'notifications' : 'root');
 state.bulk = {
  total: request.action === 'notifications' && Array.isArray(request.notifications) ? request.notifications.length : 0,
  next: 0,
  remove: !!request.remove
 };
 state.waitText = waitText();
 state.view = 'wait';
 render();
 const slot = state.slot;
 rpc('operation_start', {
  slot,
  request: JSON.stringify(request),
  aid: slots[slot].aid
 }).then((result) => {
  if (state.disposed)
   return;
  if (isObject(result) && result.ok === false) {
   state.action = null;
   toastFailure(result);
   state.view = state.returnView;
   render();
   return;
  }
  watchOperation(slot);
 }).catch((error) => {
  if (state.disposed)
   return;
  state.action = null;
  e5.toast(error && error.message ? error.message : String(error));
  state.view = state.returnView;
  render();
 });
}

function warnJob(job) {
 if (!isObject(job))
  return;
 if (job.profile_state_pending)
  e5.toast(t('配置状态尚未更新，请稍后重试', 'Profile state has not updated; try again later'));
 if (job.warning === 'refresh')
  e5.toast(t('SIM 刷新失败', 'SIM refresh failed'));
 else if (job.warning === 'notification_list')
  e5.toast(t('操作已完成，读取通知失败，可在通知页重试', 'Operation completed; open Notifications to retry reporting'));
 else if (job.warning === 'notification_report')
  e5.toast(t('操作已完成，部分通知尚未上报，可在通知页重试', 'Operation completed; retry pending notifications from Notifications'));
}

function waitText() {
 if (state.bulk.total && state.bulk.next) {
  return (state.bulk.remove
   ? t('正在删除通知 %d/%d…', 'Deleting notification %d/%d…')
   : t('正在处理通知 %d/%d…', 'Handling notification %d/%d…'))
   .replace('%d', String(state.bulk.next)).replace('%d', String(state.bulk.total));
 }
 switch (state.action) {
 case 'switch': return t('正在切换配置文件…', 'Switching profile…');
 case 'rename': return t('正在重命名…', 'Renaming…');
 case 'delete': return t('正在删除配置文件…', 'Deleting the profile…');
 case 'notifications': return t('正在处理通知…', 'Handling the notification…');
 }
 return t('正在处理…', 'Working…');
}

async function watchOperation(slot) {
 await watchJob(async (job) => {
  if (!isObject(job))
   return true;
  state.job = job;
  if (job.running) {
   if (job.step === 'notifications') {
    state.bulk.next = Number(job.current || 0);
    state.bulk.total = Number(job.total || state.bulk.total);
   }
   const text = waitText();
   if (text !== state.waitText) {
    state.waitText = text;
    render();
   }
   return true;
  }
  state.job = null;
  warnJob(job);
  if (job.state !== 'done') {
   toastFailure(job);
   if (state.action === 'notifications') {
    state.action = null;
    await openNotifications();
   } else {
    state.action = null;
    state.profile = null;
    state.notification = null;
    state.view = 'root';
    render();
   }
   return false;
  }
  if (state.resuming) {
   state.resuming = false;
   state.action = null;
   loadSlot();
   return false;
  }
  if (state.action === 'notifications') {
   if (job.failed)
    e5.toast(t('部分通知未能处理，可稍后重试', 'Some notifications could not be handled; try again later'));
   else
    e5.toast((state.bulk.remove
     ? t('已删除 %d 条通知', 'Deleted %d notifications')
     : t('已处理 %d 条通知', 'Handled %d notifications')).replace('%d', String(job.processed || state.bulk.total)));
   slots[slot].notifications = Array.isArray(job.data) ? job.data : [];
   state.action = null;
   state.notification = null;
   state.view = 'notifications';
   render();
  } else if (state.action === 'delete') {
   state.action = null;
   state.profile = null;
   state.notification = null;
   loadSlot();
  } else {
   if (Array.isArray(job.data))
    slots[slot].profiles = job.data;
   state.action = null;
   state.profile = null;
   state.notification = null;
   state.view = 'root';
   render();
  }
  return false;
 });
}

function openProfileAction(action) {
 const profile = state.profile;
 if (!profile)
  return;
 if (action === 'switch') {
  const enabled = profile.profileState === 'enabled';
  state.confirm = {
   title: enabled ? t('停用配置文件', 'Disable profile') : t('启用配置文件', 'Enable profile'),
   text: enabled
    ? t('停用后该配置不可用；若模组信息未更新，请到 SIM 管理中刷新。', 'The profile becomes unusable. If modem information stays stale, refresh it in SIM management.')
    : t('将切换卡内配置，可能中断此卡连接；不会自动重启基带。', 'This changes the active profile and may interrupt this SIM. The modem will not be reset automatically.'),
   label: enabled ? t('停用', 'Disable') : t('启用', 'Enable'),
   kind: 'primary',
   run: () => startOperation({ action: 'switch', iccid: profile.iccid || '', enabled: !enabled }, 'root')
  };
  state.view = 'confirm';
  render();
 } else if (action === 'rename') {
  state.name = profileName(profile);
  state.view = 'rename';
  render();
 } else if (action === 'delete') {
  state.confirm = {
   title: t('删除配置文件', 'Delete profile'),
   text: t('删除后无法恢复。', 'This cannot be undone.'),
   label: t('删除', 'Delete'),
   kind: 'danger',
   run: () => startOperation({ action: 'delete', iccid: profile.iccid || '' }, 'root')
  };
  state.view = 'confirm';
  render();
 }
}

function saveName() {
 if (busyTap())
  return;
 startOperation({ action: 'rename', iccid: state.profile && state.profile.iccid || '', name: state.name }, 'root');
}

function confirmNotification(remove) {
 const notification = state.notification;
 if (!notification)
  return;
 startOperation({
  action: 'notifications',
  notifications: [{ seqNumber: notification.seqNumber }],
  remove,
  single: true
 }, 'notifications');
}

function bulkNotifications(remove) {
 const list = currentSlot().notifications || [];
 if (!list.length || busyTap())
  return;
 // Only sequence numbers are needed. Sending every address/ICCID can exceed
 // the shared RPC size limit for a card with many pending notifications.
 startOperation({ action: 'notifications', notifications: list.map(item => ({seqNumber:item.seqNumber})), remove }, 'notifications');
}

function confirmDeleteAll() {
 state.confirm = {
  title: t('全部删除通知', 'Delete all notifications'),
  text: t('删除后无法恢复。', 'This cannot be undone.'),
  label: t('删除', 'Delete'),
  kind: 'danger',
  run: () => bulkNotifications(true)
 };
 state.view = 'confirm';
 render();
}

function startDownload() {
 if (state.downloading || state.action)
  return;
 const activation = state.activation.trim();
 if (!activation) {
  e5.toast(t('请输入激活码', 'Enter the activation code'));
  return;
 }
 const slot = state.slot;
 state.downloading = true;
 state.cancelling = false;
 state.previewShown = false;
 state.metadata = null;
 state.job = null;
 state.waitText = '';
 state.view = 'download_progress';
 render();
 rpc('download_start', {
  slot,
  activation,
  confirmation: state.confirmation.trim(),
  aid: slots[slot].aid
 }).then((result) => {
  if (state.disposed)
   return;
  if (isObject(result) && result.ok === false) {
   finishDownload(false, result);
   return;
  }
  if (state.cancelling)
   rpc('job_cancel').catch(() => {});
  watchDownload();
 }).catch((error) => {
  if (state.disposed)
   return;
  finishDownload(false, { error: 'lpac', detail: error && error.message ? error.message : String(error) });
 });
}

async function watchDownload(initial) {
 await watchJob(async (job) => {
  if (!isObject(job))
   return true;
  state.job = job;
  if (!job.running) {
   warnJob(job);
   finishDownload(job.state === 'done', job);
   return false;
  }
  if (job.metadata)
   state.metadata = job.metadata;
  if (state.cancelling) {
   if (state.view !== 'download_wait') {
    state.view = 'download_wait';
    state.waitText = t('正在取消下载…', 'Cancelling download…');
    render();
   }
   return true;
  }
  if (job.step === 'reporting' || job.step === 'notifications') {
   if (state.view !== 'download_wait') {
    state.view = 'download_wait';
    state.waitText = t('正在上报下载通知…', 'Reporting download…');
    render();
   }
   return true;
  }
  if (job.preview) {
   if (!state.previewShown) {
    state.previewShown = true;
    state.view = 'download_preview';
    render();
   }
   return true;
  }
  state.previewShown = false;
  if (state.view !== 'download_progress') {
   state.view = 'download_progress';
   render();
  } else {
   updateProgress(job);
  }
  return true;
 }, initial);
}

function acceptDownload() {
 rpc('job_confirm', { accept: true }).then((result) => {
  if (state.disposed)
   return;
  if (isObject(result) && result.ok === false) {
   e5.toast(t('无法继续下载', 'Cannot continue the download'));
   return;
  }
  state.previewShown = false;
  state.view = 'download_progress';
  render();
 }).catch(() => {
  if (!state.disposed)
   e5.toast(t('无法继续下载', 'Cannot continue the download'));
 });
}

function cancelDownload() {
 if (!state.downloading || state.cancelling)
  return;
 state.cancelling = true;
 state.previewShown = false;
 state.waitText = t('正在取消下载…', 'Cancelling download…');
 state.view = 'download_wait';
 render();
 rpc('job_cancel').catch(() => {});
}

function finishDownload(ok, result) {
 stopJobPoll();
 const cancelled = state.cancelling;
 state.downloading = false;
 state.cancelling = false;
 state.previewShown = false;
 state.metadata = null;
 state.job = null;
 if (!ok) {
  if (cancelled)
   e5.toast(t('已取消下载', 'Download cancelled'));
  else
   toastFailure(result);
  state.view = 'download';
  render();
  return;
 }
 state.activation = '';
 state.confirmation = '';
 e5.toast(t('配置文件已下载', 'Profile downloaded'));
 loadSlot();
}

function resumeOperation(job) {
 state.slot = job.slot === 1 ? 1 : 0;
 slots[state.slot].aid = job.aid || '';
 state.resuming = true;
 state.action = job.action || 'operation';
 state.bulk.remove = !!job.remove;
 state.bulk.total = Number(job.total || 0);
 state.bulk.next = Number(job.current || 0);
 state.waitText = waitText();
 state.view = 'wait';
 render();
 watchOperation(state.slot);
}

function resumeDownload(job) {
 state.slot = job.slot === 1 ? 1 : 0;
 slots[state.slot].aid = job.aid || '';
 state.downloading = true;
 state.cancelling = false;
 state.previewShown = false;
 state.metadata = job.metadata || null;
 state.waitText = '';
 state.view = 'download_progress';
 render();
 watchDownload();
}

function renderTabs() {
 const show = state.installed === true && ['root', 'notifications', 'loading', 'notif_loading'].includes(state.view);
 tabs.hidden = !show;
 const switchable = show && (state.view === 'root' || state.view === 'notifications');
 tabNodes.forEach((tab, index) => {
  tab.hidden = !show;
  tab.setAttribute('aria-selected', String(index === state.slot));
  tab.setAttribute('aria-pressed', String(index === state.slot));
  tab.setAttribute('aria-disabled', String(!switchable));
  tab.tabIndex = switchable ? 0 : -1;
 });
}

function renderChrome() {
 const inSlot = state.installed === true && !['install', 'deps', 'boot'].includes(state.view);
 const title = inSlot ? (state.view === 'info' ? t('eSIM 芯片信息', 'eSIM chip')
  : state.view === 'notifications' || state.view === 'notification' ? t('通知', 'Notifications')
  : state.view === 'download' ? t('添加配置文件', 'Add profile')
  : state.view === 'rename' ? t('重命名', 'Rename')
  : state.profile ? profileName(state.profile)
  : t('eSIM 管理', 'eSIM management')) : t('eSIM 管理', 'eSIM management');
 titleNode.textContent = title;
 document.title = title;
 subtitleNode.textContent = state.installing ? t('正在安装组件', 'Installing components')
  : state.installed === false ? t('需要安装组件', 'Components required')
  : state.view === 'root' ? t('配置文件、下载与通知', 'Profiles, downloads and notifications')
  : state.view === 'deps' ? t('缺少运行组件', 'Runtime components missing')
  : state.view === 'notifications' ? t('待处理的通知', 'Pending notifications')
  : state.view === 'info' ? t('EID、版本与空间', 'EID, versions and space')
  : state.view === 'profile' ? t('配置文件详情', 'Profile details')
  : state.view === 'download' ? t('输入激活码', 'Enter an activation code')
  : state.view === 'download_preview' ? t('确认运营商信息', 'Confirm carrier details')
  : state.view === 'download_progress' || state.view === 'download_wait' ? t('下载配置文件', 'Downloading profile')
  : state.view === 'notification' ? t('通知详情', 'Notification details')
  : state.view === 'wait' ? t('请稍候', 'Please wait')
  : t('配置文件、下载与通知', 'Profiles, downloads and notifications');
 slotBadge.hidden = !inSlot;
 slotBadge.textContent = 'SIM ' + (state.slot + 1);
 topbar.hidden = state.installed === true && ['root', 'loading', 'notif_loading'].includes(state.view);
 renderTabs();
}

function render() {
 if (state.disposed)
  return;
 syncTheme();
 document.documentElement.lang = zh() ? 'zh' : e5.lang === 'tr' ? 'tr' : 'en';
 const active = document.activeElement;
 const previousFocus = active && active.dataset ? active.dataset.focus : '';
 progressRefs = null;
 app.replaceChildren(...viewNodes());
 renderChrome();
 app.dataset.view = state.view;
 if (state.view === 'install')
  paintInstallLog(true);
 if (!app.children.length)
  return;
 let target = previousFocus ? findFocus(previousFocus) : null;
 if (!target)
  target = app.querySelector('button:not([disabled]), input:not([disabled])');
 if (target)
  target.focus({ preventScroll: true });
}

function viewNodes() {
 switch (state.view) {
 case 'boot':
  return [stateCard(t('正在启动…', 'Starting…'), null, true)];
 case 'install':
  return installNodes();
 case 'deps':
  return dependencyNodes();
 case 'loading':
  return [stateCard(t('正在读取 eSIM…', 'Reading the eSIM…'), t('首次读取可能需要数秒', 'The first read can take a few seconds'), true)];
 case 'notif_loading':
  return [stateCard(t('正在读取通知…', 'Reading notifications…'), null, true)];
 case 'root':
  return rootNodes();
 case 'info':
  return infoNodes();
 case 'notifications':
  return notificationNodes();
 case 'notification':
  return notificationDetailNodes();
 case 'profile':
  return profileNodes();
 case 'confirm':
  return confirmNodes();
 case 'rename':
  return renameNodes();
 case 'download':
  return downloadNodes();
 case 'download_preview':
  return downloadPreviewNodes();
 case 'download_progress':
 case 'download_wait':
  return downloadProgressNodes();
 case 'wait':
  return [stateCard(state.waitText || waitText(), null, true)];
 }
 return [];
}

function installNodes() {
 return [stateCard(t('需要安装 eSIM 组件', 'eSIM components are required'),
  t('请安装包含 eSIM 组件的最新完整固件；此页面不会后台安装软件。', 'Install current complete firmware containing eSIM components; this page does not install software in the background.'), false),
  h('div', {class:'actions'}, [button(t('重新检查', 'Check again'), 'primary', 'check-deps', () => checkStatus(true))])];
}
function dependencyNodes() { return installNodes(); }

function rootNodes() {
 const slot = currentSlot();
 const nodes = [];
 if (slot.ses) {
  const choices = [];
  SE_AIDS.forEach((aid, index) => {
   if (!(slot.ses & (1 << index)))
    return;
   const selected = slot.aid === aid;
   choices.push(h('button', {
    type: 'button',
    class: 'chip',
    focus: 'se:' + index,
    'aria-pressed': String(selected),
    click: () => selectSE(aid)
   }, 'SE ' + index));
  });
  nodes.push(card([
   heading(t('选择 SE', 'Select SE')),
   h('div', { class: 'chips', role: 'group', 'aria-label': t('选择 SE', 'Select SE') }, choices)
  ]));
 }
 if (!slot.chip && !slot.profiles) {
  const reason = slot.chipError === 'euicc_init'
   ? t('该卡槽没有 eUICC', 'No eUICC in this slot')
   : slot.chipError ? failureText({error:slot.chipError}) : t('无法读取 eSIM 信息', 'Cannot read the eSIM');
  nodes.push(card([
   message(reason),
   h('div', { class: 'actions' }, [button(t('重试', 'Retry'), 'primary', 'retry', loadSlot)])
  ]));
  return nodes;
 }
 const chip = slot.chip || {};
 nodes.push(card([
  heading(t('eSIM 芯片', 'eSIM chip'), [button(t('详情 ›', 'Details ›'), 'small ghost', 'info', openInfo)]),
  kv('EID', jget(chip, 'eidValue') || '--', true),
  kv(t('固件', 'Firmware'), jget(chip, 'EUICCInfo2.euiccFirmwareVer') || '--')
 ]));
 const notifications = slot.notifications || [];
 const profileCard = [
  heading(t('配置文件', 'Profiles'), [
   button(t('通知', 'Notifications') + ' (' + notifications.length + ')', 'small ghost', 'notifications', openNotifications),
   button(t('添加', 'Add'), 'small primary', 'add-profile', openDownload)
  ])
 ];
 if (!slot.profiles) {
  profileCard.push(message(t('读取 eSIM 失败', 'Cannot read the eSIM')));
  profileCard.push(h('div', { class: 'actions' }, [button(t('重试', 'Retry'), 'primary', 'retry-profiles', loadSlot)]));
 } else if (!slot.profiles.length) {
  profileCard.push(message(t('尚未安装配置文件', 'No profiles installed')));
 } else {
  profileCard.push(h('div', { class: 'list' }, slot.profiles.map((profile, index) => {
   const enabled = profile.profileState === 'enabled';
   const name = profileName(profile);
   return h('button', {
    type: 'button',
    class: 'tile',
    focus: 'profile:' + index,
    'aria-label': name,
    click: () => openProfile(index)
   }, [
    h('span', { class: 'tile-main' }, [
     h('span', { class: 'tile-title', text: name }),
     h('span', { class: 'tile-sub', text: [profile.serviceProviderName, profile.iccid].filter(Boolean).join(' · ') || '--' })
    ]),
    h('span', { class: 'tile-meta' }, [
     h('span', { class: 'pill' + (enabled ? ' on' : ''), text: enabled ? t('已启用', 'Enabled') : t('未启用', 'Disabled') }),
     h('span', { class: 'chevron', text: '›' })
    ])
   ]);
  })));
 }
 nodes.push(card(profileCard));
 return nodes;
}

function infoField(label, path, mono) {
 const chip = currentSlot().chip || {};
 const value = jget(chip, path);
 if (Array.isArray(value)) {
  return kv(label, value.length
   ? h('span', {}, value.map((item) => h('span', { class: 'line', text: String(item) })))
   : '--', mono);
 }
 if (typeof value === 'number')
  return kv(label, bytes(value), mono);
 return kv(label, value == null || value === '' ? '--' : String(value), mono);
}

function infoNodes() {
 return [
  card([
   heading(t('eSIM 芯片', 'eSIM chip')),
   infoField('EID', 'eidValue', true),
   infoField(t('固件版本', 'Firmware'), 'EUICCInfo2.euiccFirmwareVer'),
   infoField('SGP.22', 'EUICCInfo2.svn'),
   infoField(t('配置格式版本', 'Profile format'), 'EUICCInfo2.profileVersion'),
   infoField('GlobalPlatform', 'EUICCInfo2.globalplatformVersion')
  ]),
  card([
   infoField(t('剩余存储空间', 'Free storage'), 'EUICCInfo2.extCardResource.freeNonVolatileMemory'),
   infoField(t('剩余运行内存', 'Free RAM'), 'EUICCInfo2.extCardResource.freeVolatileMemory')
  ]),
  card([
   infoField(t('签名证书公钥标识', 'Signing certificate key IDs'), 'EUICCInfo2.euiccCiPKIdListForSigning', true),
   infoField(t('验证证书公钥标识', 'Verification certificate key IDs'), 'EUICCInfo2.euiccCiPKIdListForVerification', true),
   infoField(t('SAS 认证编号', 'SAS accreditation'), 'EUICCInfo2.sasAcreditationNumber')
  ]),
  h('div', { class: 'actions' }, [button(t('返回', 'Back'), 'secondary', 'back', showRoot)])
 ];
}

function notificationNodes() {
 const list = currentSlot().notifications || [];
 const nodes = [
  card([
   heading(t('通知', 'Notifications'), list.length ? [
    button(t('处理全部', 'Process all'), 'small ghost', 'process-all', () => bulkNotifications(false)),
    button(t('全部删除', 'Delete all'), 'small danger', 'delete-all', confirmDeleteAll)
   ] : null),
   list.length ? h('div', { class: 'list' }, list.map((notification, index) => {
    const seq = notification.seqNumber;
    return h('button', {
     type: 'button',
     class: 'tile',
     focus: 'notification:' + index,
     'aria-label': t('通知', 'Notification') + ' ' + seq,
     click: () => openNotification(index)
    }, [
     h('span', { class: 'tile-main' }, [
      h('span', { class: 'tile-title', text: operationName(notification.profileManagementOperation || '') + ' #' + seq }),
      h('span', { class: 'tile-sub', text: [notification.iccid, notification.notificationAddress].filter(Boolean).join(' · ') || '--' })
     ]),
     h('span', { class: 'tile-meta' }, [h('span', { class: 'chevron', text: '›' })])
    ]);
   })) : message(t('没有待处理的通知', 'No pending notifications'))
  ]),
  h('div', { class: 'actions' }, [button(t('返回', 'Back'), 'secondary', 'back', showRoot)])
 ];
 return nodes;
}

function notificationDetailNodes() {
 const notification = state.notification || {};
 return [
  card([
   heading(operationName(notification.profileManagementOperation || '') + ' #' + (notification.seqNumber ?? '--')),
   kv('ICCID', notification.iccid || '--', true),
   kv(t('服务器', 'Server'), notification.notificationAddress || '--', true)
  ]),
  h('div', { class: 'actions' }, [
   button(t('处理', 'Process'), 'primary', 'process-one', () => confirmNotification(false)),
   button(t('删除', 'Delete'), 'danger', 'remove-one', () => confirmNotification(true))
  ]),
  h('div', { class: 'actions' }, [button(t('返回', 'Back'), 'secondary', 'back', () => setView('notifications'))])
 ];
}

function profileNodes() {
 const profile = state.profile || {};
 const enabled = profile.profileState === 'enabled';
 const actions = [
  button(enabled ? t('停用', 'Disable') : t('启用', 'Enable'), 'primary', 'toggle-profile',
   () => openProfileAction('switch')),
  button(t('重命名', 'Rename'), 'ghost', 'rename-profile', () => openProfileAction('rename'))
 ];
 if (!enabled)
  actions.push(button(t('删除', 'Delete'), 'danger', 'delete-profile', () => openProfileAction('delete')));
 return [
  card([
   heading(profileName(profile)),
   kv(t('运营商', 'Provider'), profile.serviceProviderName || '--'),
   kv('ICCID', profile.iccid || '--', true),
   kv(t('状态', 'Status'), enabled ? t('已启用', 'Enabled') : t('未启用', 'Disabled'))
  ]),
  h('div', { class: 'actions' }, actions),
  h('div', { class: 'actions' }, [button(t('返回', 'Back'), 'secondary', 'back', showRoot)])
 ];
}

function confirmNodes() {
 const confirm = state.confirm || {};
 return [
  card([
   heading(confirm.title || t('确认', 'Confirm')),
   message(confirm.text || '')
  ]),
  h('div', { class: 'actions' }, [
   button(confirm.label || t('确认', 'Confirm'), confirm.kind || 'primary', 'confirm-action', () => {
    const run = confirm.run;
    state.confirm = null;
    if (run)
     run();
   }),
   button(t('取消', 'Cancel'), 'secondary', 'cancel-action', () => {
    state.confirm = null;
    state.view = state.profile ? 'profile' : state.notification ? 'notification' : 'notifications';
    render();
   })
  ])
 ];
}

function renameNodes() {
 return [
  card([
   heading(t('重命名', 'Rename')),
   h('div', { class: 'field' }, [
    h('label', { for: 'esim-name', text: t('名称', 'Name') }),
    h('input', {
     id: 'esim-name',
     type: 'text',
     maxlength: '64',
     autocomplete: 'off',
     spellcheck: 'false',
     value: state.name,
     focus: 'input:name',
     input: (event) => { state.name = event.target.value; }
    })
   ])
  ]),
  h('div', { class: 'actions' }, [
   button(t('保存', 'Save'), 'primary', 'save-name', saveName),
   button(t('返回', 'Back'), 'secondary', 'back', () => setView('profile'))
  ])
 ];
}

function downloadNodes() {
 return [
  card([
   heading(t('添加配置文件', 'Add profile')),
   h('div', { class: 'field' }, [
    h('label', { for: 'esim-activation', text: t('激活码', 'Activation code') }),
    h('input', {
     id: 'esim-activation',
     type: 'text',
     placeholder: 'LPA:1$…',
     maxlength: '3500',
     autocomplete: 'off',
     spellcheck: 'false',
     value: state.activation,
     focus: 'input:activation',
     input: (event) => { state.activation = event.target.value; }
    })
   ]),
   h('div', { class: 'field' }, [
    h('label', { for: 'esim-confirmation', text: t('确认码（可选）', 'Confirmation code (optional)') }),
    h('input', {
     id: 'esim-confirmation',
     type: 'password',
     maxlength: '500',
     autocomplete: 'off',
     value: state.confirmation,
     focus: 'input:confirmation',
     input: (event) => { state.confirmation = event.target.value; }
    })
   ])
  ]),
  h('div', { class: 'actions' }, [
   button(t('下载', 'Download'), 'primary', 'start-download', startDownload),
   button(t('返回', 'Back'), 'secondary', 'back', showRoot)
  ])
 ];
}

function downloadPreviewNodes() {
 const metadata = state.metadata || {};
 return [
  card([
   heading(t('确认下载配置文件', 'Confirm profile download')),
   kv(t('运营商', 'Provider'), metadata.serviceProviderName || '--'),
   kv(t('配置名称', 'Profile name'), metadata.profileName || '--'),
   kv('ICCID', metadata.iccid || '--', true),
   kv(t('配置类别', 'Profile class'), metadata.profileClass || '--')
  ]),
  h('div', { class: 'actions' }, [
   button(t('确认下载', 'Download'), 'primary', 'accept-download', acceptDownload),
   button(t('取消', 'Cancel'), 'danger', 'cancel-download', cancelDownload)
  ])
 ];
}

function downloadProgressNodes() {
 const job = state.job || {};
 const step = downloadStep(job.step);
 const waiting = state.view === 'download_wait';
 if (waiting)
  return [stateCard(state.waitText || t('正在取消下载…', 'Cancelling download…'), null, true)];
 const fill = h('div', { style: 'width:0%' });
 const meter = h('div', { class: 'progress', role: 'progressbar', 'aria-label': t('写入进度', 'Write progress'),
  'aria-valuemin': 0, 'aria-valuemax': 100 }, fill);
 const percent = h('strong');
 const amount = h('span', { text: t('等待服务器响应', 'Waiting for the server') });
 progressRefs = { fill, meter, percent, amount, step: null };
 const stepNode = h('p', { class: 'muted', text: step });
 progressRefs.step = stepNode;
 const nodes = [
  card([
   stepNode,
   h('div', { class: 'progress-top' }, [amount, percent]),
   meter
  ]),
  h('div', { class: 'actions' }, [button(t('取消下载', 'Cancel download'), 'danger', 'cancel-download', cancelDownload)])
 ];
 updateProgress(job, progressRefs);
 return nodes;
}

const STEPS = {
 writing: ['正在写入 eSIM…', 'Writing to the eSIM…'],
 es10b_get_euicc_challenge_and_info: ['正在验证 eSIM…', 'Verifying the eSIM…'],
 es9p_initiate_authentication: ['正在连接服务器…', 'Connecting to the server…'],
 es10b_authenticate_server: ['正在验证服务器…', 'Verifying the server…'],
 es9p_authenticate_client: ['正在认证…', 'Authenticating…'],
 es8p_metadata_parse: ['正在解析配置文件…', 'Parsing the profile…'],
 'es8p_meatadata_parse': ['正在解析配置文件…', 'Parsing the profile…'],
 es10b_prepare_download: ['正在准备下载…', 'Preparing the download…'],
 es9p_get_bound_profile_package: ['正在获取配置文件…', 'Fetching the profile…'],
 es10b_load_bound_profile_package: ['正在写入 eSIM…', 'Writing to the eSIM…'],
 es10b_cancel_session: ['正在取消会话…', 'Cancelling the session…'],
 es9p_cancel_session: ['正在取消会话…', 'Cancelling the session…']
};

function downloadStep(step) {
 const pair = STEPS[step];
 return pair ? t(pair[0], pair[1]) : t('正在处理…', 'Working…');
}

function updateProgress(job, refs) {
 refs = refs || progressRefs;
 if (!refs)
  return;
 const write = job && job.write;
 const writing = job && ['writing','es10b_load_bound_profile_package'].includes(job.step);
 refs.step.textContent = writing && write && write.percent === 100
  ? t('正在确认安装结果…', 'Confirming the installation…')
  : downloadStep(job && job.step);
 if (write && Number(write.total) > 0) {
  const percent = Math.max(0, Math.min(100, Number(write.percent) || 0));
  refs.fill.style.width = percent + '%';
  refs.meter.setAttribute('aria-valuenow', String(percent));
  refs.percent.textContent = percent + '%';
  refs.amount.textContent = bytes(write.written) + ' / ' + bytes(write.total);
 } else {
  refs.fill.style.width = '0%';
  refs.meter.removeAttribute('aria-valuenow');
  refs.percent.textContent = '';
  refs.amount.textContent = writing
   ? t('正在准备写入数据', 'Preparing profile data')
   : t('正在等待响应…', 'Waiting for a response…');
 }
}

function findFocus(key) {
 if (!key)
  return null;
 return Array.from(document.querySelectorAll('[data-focus]'))
  .find((node) => node.dataset.focus === key) || null;
}

function bodyFocusables() {
 return Array.from(app.querySelectorAll('button:not([disabled]), input:not([disabled]), #install-log'))
  .filter((node) => !node.closest('[hidden]'));
}

function focusNode(node) {
 if (!node)
  return false;
 node.focus({ preventScroll: true });
 if (typeof node.scrollIntoView === 'function')
  node.scrollIntoView({ block: 'nearest' });
 return true;
}

function moveFocus(direction) {
 const items = bodyFocusables();
 if (!items.length)
  return false;
 const active = document.activeElement;
 if (!items.includes(active)) {
  const target = direction === 'up' || direction === 'left' ? items[items.length - 1] : items[0];
  return focusNode(target);
 }
 const from = active.getBoundingClientRect();
 const horizontal = direction === 'left' || direction === 'right';
 const sign = direction === 'left' || direction === 'up' ? -1 : 1;
 const fromX = (from.left + from.right) / 2;
 const fromY = (from.top + from.bottom) / 2;
 let best = null;
 let bestScore = Infinity;
 for (const node of items) {
  if (node === active)
   continue;
  const rect = node.getBoundingClientRect();
  const dx = (rect.left + rect.right) / 2 - fromX;
  const dy = (rect.top + rect.bottom) / 2 - fromY;
  const forward = (horizontal ? dx : dy) * sign;
  if (forward <= 1)
   continue;
  const aligned = horizontal
   ? rect.top < from.bottom && rect.bottom > from.top
   : rect.left < from.right && rect.right > from.left;
  if (!aligned)
   continue;
  const score = (horizontal ? Math.abs(dx) : Math.abs(dy)) * 2 +
   (horizontal ? Math.abs(dy) : Math.abs(dx));
  if (score < bestScore) {
   best = node;
   bestScore = score;
  }
 }
 if (!best) {
  const at = items.indexOf(active);
  best = direction === 'down' || direction === 'right' ? items[at + 1] : items[at - 1];
 }
 return best ? focusNode(best) : false;
}

function insertDigit(input, text) {
 const start = input.selectionStart == null ? input.value.length : input.selectionStart;
 const end = input.selectionEnd == null ? start : input.selectionEnd;
 input.value = input.value.slice(0, start) + text + input.value.slice(end);
 input.setSelectionRange(start + text.length, start + text.length);
 input.dispatchEvent(new Event('input', { bubbles: true }));
}

function handleKey(key) {
 if (!key)
  return false;
 const active = document.activeElement;
 const onTab = !!(active && tabs.contains(active));
 if (!tabs.hidden) {
  if (onTab) {
   if (key.kind === 'left' || key.kind === 'right') {
    selectSlot(state.slot + (key.kind === 'right' ? 1 : -1));
    return true;
   }
   if (key.kind === 'down') {
    focusNode(bodyFocusables()[0]);
    return true;
   }
   if (key.kind === 'up') {
    const items = bodyFocusables();
    focusNode(items[items.length - 1]);
    return true;
   }
   if (key.kind === 'ok') {
    const target = Number(active.dataset.slot);
    if (target !== state.slot)
     selectSlot(target);
    return true;
   }
  } else if (key.kind === 'up') {
   const items = bodyFocusables();
   if (items.length && active === items[0]) {
    focusNode(tabNodes[state.slot]);
    return true;
   }
  }
 }
 if (active && active.id === 'install-log' && (key.kind === 'up' || key.kind === 'down')) {
  const atBottom = logAtBottom(active);
  if (key.kind === 'up') {
   if (active.scrollTop > 0) {
    active.scrollTop = Math.max(0, active.scrollTop - Math.max(18, Math.floor(active.clientHeight * .6)));
    installLogTop = active.scrollTop;
    installLogFollow = logAtBottom(active);
   }
   return true;
  }
  if (!atBottom) {
   active.scrollTop = Math.min(active.scrollHeight, active.scrollTop + Math.max(18, Math.floor(active.clientHeight * .6)));
   installLogTop = active.scrollTop;
   installLogFollow = logAtBottom(active);
   return true;
  }
  const items = bodyFocusables();
  const next = items[items.indexOf(active) + 1];
  if (next)
   return focusNode(next);
  return true;
 }
 if (key.kind === 'digit' && active && active.tagName === 'INPUT' && /^[0-9*#]$/.test(key.key || '')) {
  insertDigit(active, key.key);
  return true;
 }
 if (key.kind === 'ok') {
  if (active && app.contains(active)) {
   if (active.tagName === 'BUTTON') {
    e5.press(active);
    return true;
   }
   if (active.tagName === 'INPUT') {
    const form = active.closest('.card');
    const button = form && form.parentElement && form.parentElement.querySelector('.actions .primary');
    if (button) {
     e5.press(button);
     return true;
    }
   }
  }
  const first = bodyFocusables()[0];
  if (first) {
   focusNode(first);
   return true;
  }
  return false;
 }
 if (key.kind === 'up' || key.kind === 'down' || key.kind === 'left' || key.kind === 'right')
  return moveFocus(key.kind);
 return false;
}

function goBack() {
 if (state.view === 'root' || state.view === 'install' || state.view === 'deps' || state.view === 'boot')
  return false;
 if (state.view === 'wait' || state.view === 'download_progress' || state.view === 'download_wait')
  return true;
 if (state.view === 'confirm') {
  state.confirm = null;
  state.view = state.profile ? 'profile' : state.notification ? 'notification' : 'notifications';
  render();
  return true;
 }
 if (state.view === 'notification') {
  setView('notifications');
  return true;
 }
 if (state.view === 'profile') {
  showRoot();
  return true;
 }
 if (state.view === 'rename')
  setView('profile');
 else if (state.view === 'info' || state.view === 'notifications' || state.view === 'download')
  showRoot();
 else if (state.view === 'download_preview')
  cancelDownload();
 else
  showRoot();
 return true;
}

tabNodes.forEach((tab, index) => {
 tab.addEventListener('click', () => selectSlot(index));
});

e5.onKey(handleKey);
e5.onBack(goBack);
e5.onLang(() => {
 document.documentElement.lang = zh() ? 'zh' : e5.lang === 'tr' ? 'tr' : 'en';
 render();
});

window.addEventListener('pagehide', () => {
 state.disposed = true;
 stopStatusPoll();
 stopJobPoll();
});

document.documentElement.lang = zh() ? 'zh' : e5.lang === 'tr' ? 'tr' : 'en';
render();
checkStatus(true);
