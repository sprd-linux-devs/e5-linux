'use strict';
'require rpc';
'require baseclass';
/* mu300 面板共享模块：rpc 声明、格式化/信号质量助手、主题感知的样式表。
 * 页面通过 'require mu300.common' 引用（LuCI 的 dotted require 映射到
 * /luci-static/resources/mu300/common.js）。
 *
 * 样式只引用主题令牌：本机装的是 luci-theme-aurora（--surface/--hairline/
 * --brand/--text-muted/--success 等，html[data-darkmode] 一键翻转深浅色），
 * 其它主题时逐级回退到 LuCI 标准变量（--background-alt/--border/--primary...）。
 * 质量色不用写死的色值，走 --success/--warning/--danger 与 color-mix，
 * 深浅两套模式都跟随主题。 */

function simSlot() { return sessionStorage.getItem('modem-view-slot') === '1' ? '1' : '0'; }
var dataSimRevision = 0, simVisibilityBound = false;
function followDataSim(slot, confirmed) {
	if (slot !== 0 && slot !== 1 && slot !== '0' && slot !== '1') return;
	var next = String(slot), previous = sessionStorage.getItem('modem-data-slot');
	// A manual view stays selected until the actual data SIM changes again.
	// First observation also repairs sessions left on SIM 1 by older releases.
	if (!confirmed && previous === next) return;
	dataSimRevision++;
	sessionStorage.setItem('modem-data-slot', next);
	var changed = simSlot() !== next;
	sessionStorage.setItem('modem-view-slot', next);
	// Drop all page-local signal/history/rate caches together, just like a
	// manual selector change. The SIM-management page itself has no selector.
	if (changed && document.querySelector('.mud-sim-selector')) window.location.reload();
}
function scopedRpc(method, params) {
	params = params || [];
	// An AT-backed request may take seconds. Never share its HTTP batch with
	// rates/status or another SIM's data. Keep the existing polling/cache rules.
	var nativeRead = ['status', 'rates', 'cells'].indexOf(method) >= 0;
	var call = rpc.declare({object:nativeRead?'e5status':'mu300dash', method:method, params:params.concat(['slot']), expect:{'':{}}, nobatch:true});
	return function() {
		var args = Array.prototype.slice.call(arguments, 0, params.length);
		while (args.length < params.length) args.push('');
		var revision = dataSimRevision;
		return call.apply(null, args.concat([simSlot()])).then(function(result) {
			if (method === 'status' && revision === dataSimRevision)
				followDataSim(result && result.info && result.info.modem && result.info.modem.data_sim);
			return result;
		});
	};
}
var simSelectorCleanup = null;
function simSelector(root, layout) {
	if (simSelectorCleanup) simSelectorCleanup();
	var anchor=layout==='hero' && root.querySelector('.mud-hero-meta');
	var row=document.createElement('div');
	row.className=anchor?'mud-sim-selector mud-sim-hero':'mud-card mud-sim-selector';
	row.innerHTML='<button type="button" class="mud-sim-toggle" aria-expanded="false" aria-controls="mud-sim-panel">'+
		'<span class="mud-sim-title">查看 / 控制卡槽</span><span class="mud-sim-current"></span>'+
		'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg></button>'+
		'<div id="mud-sim-panel" class="mud-sim-panel" aria-hidden="true" inert><div class="mud-sim-clip">'+
		'<div class="mud-sim-options"><select aria-label="查看 / 控制卡槽"></select>'+
		'<small>仅切换查看与操作对象，不切换上网卡</small></div></div></div>';
	var toggle=row.querySelector('.mud-sim-toggle'), panel=row.querySelector('.mud-sim-panel'), select=row.querySelector('select');
	row.querySelector('.mud-sim-current').textContent='SIM '+(Number(simSlot())+1);
	['SIM 1','SIM 2'].forEach(function(name,i){var o=document.createElement('option');o.value=String(i);o.textContent=name;select.appendChild(o);});
	select.value=simSlot();
	select.onchange=function(){sessionStorage.setItem('modem-view-slot',select.value);window.location.reload();};
	function expand(open) {
		row.classList.toggle('is-open',open);
		toggle.setAttribute('aria-expanded',String(open));
		panel.setAttribute('aria-hidden',String(!open));
		panel.toggleAttribute('inert',!open);
	}
	toggle.onclick=function(){expand(toggle.getAttribute('aria-expanded')!=='true');};
	row.onkeydown=function(event){
		if(event.key==='Escape' && toggle.getAttribute('aria-expanded')==='true'){
			event.preventDefault();expand(false);toggle.focus();
		}
	};
	localize(row);
	toggle.setAttribute('aria-label',translate('查看 / 控制卡槽')+' SIM '+(Number(simSlot())+1));
	if(anchor)anchor.appendChild(row);else root.insertBefore(row,root.firstChild);
	function outside(event){if(anchor && !row.contains(event.target))expand(false);}
	var lifetime=new MutationObserver(function(){if(!root.isConnected)cleanup();});
	function cleanup(){
		lifetime.disconnect();row.remove();document.removeEventListener('click',outside);
		if(simSelectorCleanup===cleanup)simSelectorCleanup=null;
	}
	simSelectorCleanup=cleanup;
	document.addEventListener('click',outside);
	lifetime.observe(document.body,{childList:true,subtree:true});
	callSimGet().catch(function() {});
	if (!simVisibilityBound) {
		simVisibilityBound = true;
		document.addEventListener('visibilitychange', function() {
			if (!document.hidden && document.querySelector('.mud-sim-selector')) callSimGet().catch(function() {});
		});
	}
}
var callStatus = scopedRpc('status');
var callRates = scopedRpc('rates');
/* Separate HTTP replies let cached neighbors/config paint during a live AT read. */
var callCells = scopedRpc('cells');
var callSignal = scopedRpc('signal');
var callSysinfo = rpc.declare({ object: 'e5status', method: 'sysinfo', expect: { '': {} }, nobatch: true });
var readSimGet = rpc.declare({object:'mu300dash',method:'sim_get',expect:{'':{}},nobatch:true});
function callSimGet() {
	var revision = dataSimRevision;
	return readSimGet().then(function(info) {
		// A late pre-switch read must not undo a verified completed switch.
		if (revision === dataSimRevision && info && info.ok !== false) followDataSim(info.data_sim);
		return info;
	});
}
var callSimSet = rpc.declare({object:'mu300dash',method:'sim_set',params:['slot','current','confirm'],expect:{'':{}},nobatch:true});
var callSimStatus = rpc.declare({object:'mu300dash',method:'sim_status',params:['id'],expect:{'':{}},nobatch:true});
var callAct = scopedRpc('act',['op','arg']);
var callAt = scopedRpc('at',['cmd']);
var callAtHist = scopedRpc('at_history');
var callLockGet = scopedRpc('lock_get');
var callLockFresh = scopedRpc('lock_get',['fresh']);
var callLockSet = scopedRpc('lock_set',['kind','val']);
var callLockStatus = scopedRpc('lock_status',['id']);
function waitLockJob(started) {
	return new Promise(function(resolve, reject) {
		if (!started || !started.ok || !started.id) { reject(new Error(started && started.error || '网络设置提交失败')); return; }
		var done = false, next;
		var finish = function(error, result) {
			if (done) return;
			done = true; clearTimeout(limit); clearTimeout(next);
			if (error) reject(error); else resolve(result);
		};
		var limit = setTimeout(function() { finish(new Error('应用超时，请刷新确认模组状态')); }, 240000);
		var check = function() {
			callLockStatus(started.id).then(function(r) {
				if (done) return;
				if (r && r.state === 'done' && r.ok) finish(null, r);
				else if (!r || r.state === 'error') finish(new Error(r && r.error || '网络设置执行失败'));
				else if (r.state === 'queued' || r.state === 'running') next = setTimeout(check, 1000);
				else finish(new Error('无效的操作状态'));
			}, function(error) { finish(error); });
		};
		check();
	});
}
var callSmsList = (function() {
	var call = rpc.declare({ object: 'mu300dash', method: 'sms_list', params: [ 'page' ], expect: { '': {} } });
	return function(page) { return call(String(page || 1)); };
})();
var callSmsShow = (function() {
	var call = rpc.declare({ object: 'mu300dash', method: 'sms_show', params: [ 'id' ], expect: { '': {} } });
	return function(id) { return call(String(id)); };
})();
var callSmsSend = rpc.declare({ object: 'mu300dash', method: 'sms_send', params: [ 'num', 'text', 'card' ], expect: { '': {} } });
var callSmsDel = (function() {
	var call = rpc.declare({ object: 'mu300dash', method: 'sms_delete', params: [ 'id', 'sim' ], expect: { '': {} } });
	return function(id, sim) {
		return call(String(id), sim === true || sim === 1 || sim === '1' ? '1' : '0');
	};
})();
var callSmsSync = rpc.declare({ object: 'mu300dash', method: 'sms_sync', expect: { '': {} } });
var callForwardGet = rpc.declare({ object: 'mu300dash', method: 'forward_get', params: [ 'profile' ], expect: { '': {} } });
var callForwardStatus = rpc.declare({ object: 'mu300dash', method: 'forward_status', params: [ 'profile' ], expect: { '': {} } });
var callForwardSet = rpc.declare({ object: 'mu300dash', method: 'forward_set', params: [ 'payload' ], expect: { '': {} } });
var callForwardClear = rpc.declare({ object: 'mu300dash', method: 'forward_log_clear', expect: { '': {} } });
var callForwardTest = rpc.declare({ object: 'mu300dash', method: 'forward_test', params: [ 'profile' ], expect: { '': {} } });
var trafficGetRpc = rpc.declare({object:'mu300dash',method:'traffic_get',params:['slot'],expect:{'':{}},nobatch:true});
var trafficSetRpc = rpc.declare({object:'mu300dash',method:'traffic_set',params:['payload','slot'],expect:{'':{}},nobatch:true});
function callTrafficGet(slot) { return trafficGetRpc(slot == null ? simSlot() : String(slot)); }
function callTrafficSet(payload, slot) { return trafficSetRpc(payload, slot == null ? simSlot() : String(slot)); }
var callTrafficClear = rpc.declare({object:'mu300dash',method:'traffic_clear',params:['slot','confirm'],expect:{'':{}}});
var callTtlGet = rpc.declare({ object: 'mu300dash', method: 'ttl_get', expect: { '': {} } });
var callTtlSet = rpc.declare({ object: 'mu300dash', method: 'ttl_set', params: [ 'value' ], expect: { '': {} }, nobatch: true });
var callUsbGet = rpc.declare({ object: 'mu300dash', method: 'usb_get', expect: { '': {} } });
var callUsbSet = rpc.declare({ object: 'mu300dash', method: 'usb_set', params: [ 'kind', 'value', 'scope', 'auto' ], expect: { '': {} } });
var callUsbNetList = rpc.declare({ object: 'mu300dash', method: 'usb_net_list', expect: { '': {} } });
var callUsbNetAdd = rpc.declare({ object: 'mu300dash', method: 'usb_net_add', params: [ 'iface' ], expect: { '': {} } });

/* Dashboard translations deliberately ship as a tiny runtime catalog: a
 * standalone package works in any OpenWrt buildroot without po2lmo or extra
 * language packages. Chinese remains the source/fallback language. */
/* BEGIN SHARED PLATFORM MESSAGES: stage.py also embeds these in the screen. */
const PLATFORM_ERRORS = [
  [
    "CPU unavailable",
    "CPU 状态暂不可用",
    "CPU durumu kullanılamıyor"
  ],
  [
    "CPU control unavailable",
    "CPU 控制服务暂不可用",
    "CPU denetim hizmeti kullanılamıyor"
  ],
  [
    "Failed",
    "操作失败",
    "İşlem başarısız"
  ],
  [
    "Invalid voltage profile",
    "电压配置无效",
    "Geçersiz voltaj profili"
  ],
  [
    "Expected three voltage domains",
    "电压配置必须包含三个供电域",
    "Voltaj profili üç güç alanını içermelidir"
  ],
  [
    "Voltage offset must be -50000..25000 uV in 3125 uV steps",
    "电压偏移须在 -50 至 +25 mV 内，步进为 3.125 mV",
    "Voltaj ofseti -50 ile +25 mV arasında, 3,125 mV adımlarla olmalıdır"
  ],
  [
    "Unclean shutdown with custom voltage; restored factory voltage",
    "自定义电压下出现异常关机，已恢复原厂电压",
    "Özel voltajla beklenmeyen kapanma oldu; fabrika voltajı geri yüklendi"
  ],
  [
    "CPU voltage adjustment is not supported on this SoC",
    "当前芯片尚未适配电压调整",
    "Bu çipte CPU voltaj ayarı desteklenmiyor"
  ],
  [
    "CPU voltage interface is missing from this kernel",
    "当前内核缺少 CPU 调压接口，需要更新配套内核和模块",
    "Bu çekirdekte CPU voltaj arayüzü eksik; çekirdeği ve eşleşen modülleri güncelleyin"
  ],
  [
    "SML partitions are not ready; refresh after initialization",
    "SML 分区尚未就绪，请稍后刷新",
    "SML bölümleri hazır değil; başlatma tamamlanınca yenileyin"
  ],
  [
    "SML partitions could not be read; refresh and check storage",
    "无法读取 SML 分区，请刷新并检查存储状态",
    "SML bölümleri okunamadı; yenileyin ve depolamayı denetleyin"
  ],
  [
    "SML voltage ABI could not be established",
    "尚未匹配到本机 SML 的调压协议，请保留原厂电压",
    "Bu SML'nin voltaj protokolü doğrulanamadı; fabrika voltajını koruyun"
  ],
  [
    "SML compatibility checker is not ready; refresh after installation",
    "SML 兼容性检查组件尚未就绪，请安装完成后刷新",
    "SML uyumluluk denetleyicisi hazır değil; kurulumdan sonra yenileyin"
  ],
  [
    "CPU driver failed to initialize; reboot to restore default voltage",
    "CPU 驱动初始化失败，请重启恢复原厂电压",
    "CPU sürücüsü başlatılamadı; fabrika voltajını geri yüklemek için yeniden başlatın"
  ],
  [
    "Kernel did not accept ",
    "内核未接受设置：",
    "Çekirdek ayarı kabul etmedi: "
  ],
  [
    "Expected an integer",
    "请输入整数",
    "Bir tam sayı girin"
  ],
  [
    "Unknown CPU setting",
    "未知的 CPU 设置",
    "Bilinmeyen CPU ayarı"
  ],
  [
    "Invalid persistence flag",
    "开机应用选项无效",
    "Geçersiz açılışta uygulama seçeneği"
  ],
  [
    "Invalid CPU policy",
    "CPU 调频域配置无效",
    "Geçersiz CPU frekans alanı ayarı"
  ],
  [
    "CPU policy missing or repeated",
    "CPU 调频域缺失或重复",
    "CPU frekans alanı eksik veya yinelenmiş"
  ],
  [
    "Boot voltage adjustment unavailable for this kernel/firmware",
    "当前内核或固件不支持开机电压调整",
    "Bu çekirdek veya ürün yazılımında açılış voltajı ayarlanamıyor"
  ],
  [
    "CPU topology changed; reset saved settings",
    "CPU 拓扑已变化，请恢复默认设置",
    "CPU topolojisi değişti; kayıtlı ayarları sıfırlayın"
  ],
  [
    "Choose supported frequencies with minimum <= maximum",
    "请选择支持的频率，最低频率不能高于最高频率",
    "Desteklenen frekansları seçin; en düşük değer en yüksek değeri aşamaz"
  ],
  [
    "Governor unavailable",
    "所选调速器不可用",
    "Seçilen frekans yöneticisi kullanılamıyor"
  ],
  [
    "Invalid thermal setting",
    "温控设置无效",
    "Geçersiz sıcaklık ayarı"
  ],
  [
    "CPU thermal zone unavailable or ambiguous",
    "CPU 温区不可用或无法唯一确定",
    "CPU sıcaklık bölgesi kullanılamıyor veya belirsiz"
  ],
  [
    "Only writable passive CPU trips may be changed",
    "只能修改可写的 CPU 被动温控阈值",
    "Yalnızca yazılabilir pasif CPU sıcaklık eşikleri değiştirilebilir"
  ],
  [
    "Temperature must use 1 C steps within the protected range",
    "温度须在允许范围内按 1 °C 步进设置",
    "Sıcaklık korunan aralıkta 1 °C adımlarla ayarlanmalıdır"
  ],
  [
    "Passive trip temperatures must increase by at least 1 C",
    "被动温控阈值须逐级至少升高 1 °C",
    "Pasif sıcaklık eşikleri en az 1 °C artan sırada olmalıdır"
  ],
  [
    "rollback failed: ",
    "回退失败：",
    "geri alma başarısız: "
  ],
  [
    "Invalid frequency",
    "频率无效",
    "Geçersiz frekans"
  ],
  [
    "Thermal zone unavailable",
    "温区不可用",
    "Sıcaklık bölgesi kullanılamıyor"
  ],
  [
    "Unsupported CPU setting",
    "不支持的 CPU 设置",
    "Desteklenmeyen CPU ayarı"
  ],
  [
    "Unknown operation",
    "未知操作",
    "Bilinmeyen işlem"
  ],
  [
    "Cannot read the current data SIM",
    "无法读取当前上网卡",
    "Etkin internet SIM kartı okunamıyor"
  ],
  [
    "Invalid SIM switch job",
    "切卡任务无效",
    "Geçersiz SIM değiştirme görevi"
  ],
  [
    "SIM switch interrupted; check the current data SIM",
    "切卡任务已中断，请检查当前上网卡",
    "SIM değiştirme kesildi; etkin internet SIM kartını kontrol edin"
  ],
  [
    "Data SIM changed; refresh before switching",
    "上网卡已变化，请刷新后再切换",
    "İnternet SIM kartı değişti; geçişten önce yenileyin"
  ],
  [
    "System SIM switch failed",
    "系统切卡失败",
    "Sistemin SIM değiştirme işlemi başarısız"
  ],
  [
    "Data SIM did not match the saved selection; refresh actual state",
    "实际卡槽与保存值不一致，请刷新检查",
    "Etkin SIM kayıtlı seçimle eşleşmiyor; mevcut durumu yenileyin"
  ],
  [
    "Invalid SIM switch request",
    "切卡请求无效",
    "Geçersiz SIM değiştirme isteği"
  ],
  [
    "Select a valid SIM slot",
    "请选择有效的 SIM 卡槽",
    "Geçerli bir SIM yuvası seçin"
  ],
  [
    "Confirm the data SIM switch",
    "请确认切换上网卡",
    "İnternet SIM kartı değişikliğini onaylayın"
  ],
  [
    "A data SIM switch is already running",
    "正在切换上网卡，请稍后再试",
    "İnternet SIM kartı zaten değiştiriliyor; lütfen bekleyin"
  ],
  [
    "Invalid data SIM operation",
    "上网卡操作无效",
    "Geçersiz internet SIM işlemi"
  ],
  [
    "Modem is busy; try again shortly",
    "基带正忙，请稍后重试",
    "Modem meşgul; biraz sonra yeniden deneyin"
  ],
  [
    "Network service unavailable",
    "网络控制服务暂不可用",
    "Ağ denetim hizmeti kullanılamıyor"
  ],
  [
    "Invalid SIM slot",
    "SIM 卡槽无效",
    "Geçersiz SIM yuvası"
  ],
  [
    "Cannot save SIM selection",
    "无法保存卡槽选择",
    "SIM seçimi kaydedilemiyor"
  ],
  [
    "Cannot start SIM switch",
    "无法启动切卡任务",
    "SIM değiştirme başlatılamıyor"
  ],
  [
    "Cannot save APN",
    "无法保存 APN",
    "APN kaydedilemiyor"
  ],
  [
    "Invalid band list",
    "频段列表无效",
    "Geçersiz bant listesi"
  ],
  [
    "Invalid network setting",
    "网络设置无效",
    "Geçersiz ağ ayarı"
  ],
  [
    "Cannot start network operation",
    "无法启动网络设置任务",
    "Ağ ayarı görevi başlatılamıyor"
  ],
  [
    "Charge start must be lower than stop",
    "充电启动阈值必须低于停止阈值",
    "Şarj başlatma eşiği durdurma eşiğinden düşük olmalıdır"
  ],
  [
    "Cannot save setting",
    "无法保存设置",
    "Ayar kaydedilemiyor"
  ],
  [
    "Setting saved but apply failed",
    "设置已保存，但应用失败",
    "Ayar kaydedildi ancak uygulanamadı"
  ],
  [
    "Cannot select Android",
    "无法选择 Android 启动",
    "Android açılışı seçilemiyor"
  ],
  [
    "Current network mode cannot be combined with this NR setting",
    "当前网络模式不支持该 5G 组网选项",
    "Geçerli ağ modu bu NR ayarıyla birleştirilemiyor"
  ],
  [
    "Default LTE bands did not survive reconnect",
    "重连后 LTE 默认频段未保持，请刷新检查",
    "Yeniden bağlantıdan sonra varsayılan LTE bantları korunmadı; yenileyin"
  ],
  [
    "AT service unavailable",
    "AT 服务暂不可用",
    "AT hizmeti kullanılamıyor"
  ],
  [
    "Invalid network job",
    "网络设置任务无效",
    "Geçersiz ağ ayarı görevi"
  ],
  [
    "Invalid hotspot state",
    "热点状态无效",
    "Geçersiz erişim noktası durumu"
  ],
  [
    "No hotspot configured",
    "尚未配置热点",
    "Erişim noktası yapılandırılmamış"
  ],
  [
    "Cannot save hotspot setting",
    "无法保存热点设置",
    "Erişim noktası ayarı kaydedilemiyor"
  ],
  [
    "An update task is already running",
    "已有更新任务正在执行",
    "Bir güncelleme görevi zaten çalışıyor"
  ],
  [
    "Unknown update action",
    "未知更新操作",
    "Bilinmeyen güncelleme işlemi"
  ],
  [
    "The release has changed; check again",
    "更新版本已变化，请重新检查",
    "Sürüm değişti; yeniden kontrol edin"
  ],
  [
    "No update backup",
    "没有可回退的更新备份",
    "Geri dönülecek güncelleme yedeği yok"
  ],
  [
    "Cannot start the update task",
    "无法启动更新任务",
    "Güncelleme görevi başlatılamıyor"
  ],
  [
    "This package does not include the device UI integration; use a compatible firmware/update package",
    "此更新包未包含设备界面适配，请使用兼容的固件或更新包",
    "Bu paket cihaz arayüzü uyarlamasını içermiyor; uyumlu ürün yazılımı veya güncelleme paketi kullanın"
  ],
  [
    "This app requires its device-integrated update; the generic package would replace platform features",
    "此应用需要设备适配版本，通用包会覆盖平台功能",
    "Bu uygulama cihaza uyarlanmış güncelleme gerektirir; genel paket platform özelliklerinin üzerine yazar"
  ],
  [
    "Confirmation is required",
    "需要确认此操作",
    "Bu işlem için onay gerekiyor"
  ],
  [
    "Could not save traffic records",
    "流量记录保存失败",
    "Veri kullanım kayıtları kaydedilemedi"
  ],
  [
    "Traffic service unavailable",
    "流量统计服务暂不可用",
    "Veri kullanım hizmeti kullanılamıyor"
  ],
  [
    "System clock is not synchronized",
    "系统时间尚未同步",
    "Sistem saati eşitlenmedi"
  ],
  [
    "Invalid data SIM",
    "上网卡无效",
    "Geçersiz internet SIM kartı"
  ],
  [
    "AT request timed out",
    "AT 请求超时",
    "AT isteği zaman aşımına uğradı"
  ],
  [
    "expected response field missing",
    "响应缺少预期字段",
    "Yanıtta beklenen alan eksik"
  ],
  [
    "invalid numeric response",
    "响应数值无效",
    "Yanıttaki sayısal değer geçersiz"
  ],
  [
    "Unknown active SIM",
    "无法确定当前 SIM 卡",
    "Etkin SIM kartı belirlenemiyor"
  ],
  [
    "Incomplete network mode response",
    "网络模式响应不完整",
    "Ağ modu yanıtı eksik"
  ],
  [
    "Incomplete band mask response",
    "频段掩码响应不完整",
    "Bant maskesi yanıtı eksik"
  ],
  [
    "Incomplete cell lock response",
    "小区锁定响应不完整",
    "Hücre kilidi yanıtı eksik"
  ],
  [
    "Active SIM changed while reading; refresh again",
    "读取时上网卡已变化，请重新刷新",
    "Okuma sırasında etkin SIM değişti; yeniden yenileyin"
  ],
  [
    "Requested NR band has no supported SPLBAND encoding",
    "所选 NR 频段没有受支持的 SPLBAND 编码",
    "Seçilen NR bandı için desteklenen SPLBAND kodlaması yok"
  ],
  [
    "Unsupported band requested",
    "请求的频段不受支持",
    "İstenen bant desteklenmiyor"
  ],
  [
    "Unacknowledged setting failed readback: ",
    "设置未确认且回读失败：",
    "Onaylanmayan ayar geri okunamadı: "
  ],
  [
    "Modem readback does not match requested setting",
    "基带回读与请求设置不一致",
    "Modemden okunan değer istenen ayarla eşleşmiyor"
  ],
  [
    "Active SIM changed during operation",
    "操作期间上网卡已变化",
    "İşlem sırasında etkin SIM değişti"
  ],
  [
    "Setting accepted, but reconnect failed: ",
    "设置已接受，但重连失败：",
    "Ayar kabul edildi ancak yeniden bağlantı başarısız: "
  ],
  [
    "Setting did not survive reconnect",
    "重连后设置未保持",
    "Ayar yeniden bağlantıdan sonra korunmadı"
  ],
  [
    "Cannot read standby radio state",
    "无法读取备用卡射频状态",
    "Yedek SIM radyo durumu okunamıyor"
  ],
  [
    "Cannot read modem state before reconnect",
    "重连前无法读取模组状态",
    "Yeniden bağlantı öncesinde modem durumu okunamıyor"
  ],
  [
    "Radio reconnect timed out",
    "射频重连超时",
    "Radyo yeniden bağlantısı zaman aşımına uğradı"
  ],
  [
    "Another network operation is still running",
    "另一个网络操作仍在执行",
    "Başka bir ağ işlemi hâlâ çalışıyor"
  ],
  [
    "Invalid job ID",
    "任务编号无效",
    "Geçersiz görev kimliği"
  ],
  [
    "Saved settings do not match modem readback: ",
    "已保存设置与基带回读不一致：",
    "Kayıtlı ayarlar modemden okunan değerlerle eşleşmiyor: "
  ],
  [
    "Boot replay is only allowed before initial radio activation",
    "开机回放只能在首次射频激活前执行",
    "Açılış ayarları yalnızca ilk radyo etkinleştirmesinden önce uygulanabilir"
  ],
  [
    "Unknown lock operation",
    "未知锁定操作",
    "Bilinmeyen kilitleme işlemi"
  ],
  [
    "unknown card",
    "未知 SIM 卡",
    "Bilinmeyen SIM kartı"
  ],
  [
    "unknown APN",
    "未知 APN",
    "Bilinmeyen APN"
  ],
  [
    "Choose a SIM in Clear traffic records",
    "请在“清空流量记录”中选择卡槽",
    "Veri geçmişini temizle bölümünde bir SIM seçin"
  ],
  [
    "Invalid USB setting",
    "USB 设置无效",
    "Geçersiz USB ayarı"
  ],
  [
    "USB operation failed",
    "USB 操作失败",
    "USB işlemi başarısız"
  ],
  [
    "no such setting",
    "没有此设置项",
    "Böyle bir ayar yok"
  ]
];
PLATFORM_ERRORS.push(...[
  [
    "Enable the target SIM radio before switching",
    "请先开启目标 SIM 的射频，再切换上网卡",
    "Geçişten önce hedef SIM radyosunu açın"
  ],
  [
    "This SIM radio is disabled by the user",
    "该卡射频已被用户禁用",
    "Bu SIM radyosu kullanıcı tarafından kapatılmış"
  ],
  [
    "Invalid saved SIM radio policy",
    "已保存的 SIM 射频设置无效",
    "Kaydedilmiş SIM radyo ayarları geçersiz"
  ],
  [
    "Radio setting saved; modem command failed:",
    "设置已保存，但基带执行失败：",
    "Radyo ayarı kaydedildi; modem komutu başarısız:"
  ],
  [
    "Radio setting saved; RF readback not confirmed",
    "设置已保存，但未能确认射频状态",
    "Radyo ayarı kaydedildi; modem durumu doğrulanamadı"
  ],
  [
    "Radio setting saved; target SIM is not ready",
    "设置已保存，目标 SIM 尚未就绪",
    "Radyo ayarı kaydedildi; hedef SIM henüz hazır değil"
  ],
  [
    "Radio setting saved; RF enable failed",
    "设置已保存，但射频开启失败",
    "Radyo ayarı kaydedildi; radyo açılamadı"
  ],
  [
    "Radio setting saved; RF disable failed",
    "设置已保存，但射频关闭失败",
    "Radyo ayarı kaydedildi; radyo kapatılamadı"
  ],
  [
    "Radio setting failed",
    "射频设置失败",
    "Radyo ayarı başarısız"
  ],
  [
    "Invalid radio request",
    "射频设置请求无效",
    "Radyo isteği geçersiz"
  ]
]);
const PLATFORM_CODES = {
    invalid_slot:'Select a valid SIM slot', confirmation_required:'Confirmation is required',
    storage_failed:'Could not save traffic records', traffic_unavailable:'Traffic service unavailable',
    clock_unsynced:'System clock is not synchronized'
};
const PLATFORM_PATTERN = new RegExp(PLATFORM_ERRORS.map(row=>row[0]).sort((a,b)=>b.length-a.length).map(key=>key.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')).join('|'),'g');
function errorText(value, language) {
    let text = String(value ?? '');
    text = PLATFORM_CODES[text] || text;
    const column = language === 'zh' ? 1 : language === 'tr' ? 2 : 0;
    return text.replace(PLATFORM_PATTERN, key=>PLATFORM_ERRORS.find(row=>row[0]===key)[column]);
}
/* END SHARED PLATFORM MESSAGES */

var DASH_I18N = {
	"电池与电量": ["Battery & power", "Pil ve güç"],
	"电池历史": ["Battery history", "Pil geçmişi"],
	"电池使用时间": ["On battery", "Pilde geçen süre"],
	"预估续航": ["Estimated time left", "Tahmini kalan süre"],
	"自上次充满": ["Since last full charge", "Son tam şarjdan beri"],
	"自上次充电": ["Since last charge", "Son şarjdan beri"],
	"24 小时": ["24 hours", "24 saat"],
	"7 天": ["7 days", "7 gün"],
	"小时": ["h", "sa"],
	"分钟": ["min", "dk"],
	"已连接电源，未充电": ["Plugged in, not charging", "Güce bağlı, şarj olmuyor"],
	"正在充电或已充满": ["Charging or full", "Şarj oluyor veya dolu"],
	"电池放电功率": ["Power drawn from the battery", "Pilden çekilen güç"],
	"时间区间": ["Time range", "Zaman aralığı"],
	"每分钟记录，保留最近 10 天；关机或缺失时段留空。功率和电流为电池净值，不是充电器输入值。": ["Recorded every minute, kept for 10 days. Off-device and missing periods stay blank. Power and current are net battery values, not charger input.", "Dakikada bir kaydedilir, 10 gün saklanır. Kapalı veya eksik dönemler boş kalır. Güç ve akım, şarj girişi değil net pil değerleridir."],
	"未检测到电池": ["No battery detected", "Pil algılanmadı"],
	"暂无历史记录，采集后自动显示": ["No history yet; new readings will appear automatically", "Henüz geçmiş yok; yeni ölçümler otomatik görünür"],
	"电池记录读取失败，请稍后重试": ["Could not read battery history; retry shortly", "Pil geçmişi okunamadı; biraz sonra yeniden deneyin"],
	"连接电源时不估算续航": ["Not estimated while plugged in", "Güce bağlıyken tahmin edilmez"],
	"放电记录不足，暂不估算": ["More discharge history is needed", "Daha fazla deşarj geçmişi gerekiyor"],
	"按最近放电速度估算": ["Based on recent discharge", "Son deşarj hızına göre"],
	"暂无记录": ["No readings", "Ölçüm yok"],
	"已更新": ["Updated", "Güncellendi"],
	"AT 通道正忙，正在等待更新…": ["AT channel busy; waiting for an update…", "AT kanalı meşgul; güncelleme bekleniyor…"],
	"模组尚未返回有效的实时信号": ["The modem has not returned valid live signal data", "Modem henüz geçerli canlı sinyal verisi döndürmedi"],
	"另一项 TTL 操作正在执行，请稍后重试": ["Another TTL operation is running; please retry shortly", "Başka bir TTL işlemi çalışıyor; biraz sonra yeniden deneyin"],
	"正数充电，负数放电；显示电池净电流，不是 USB 输入电流。": ["Positive: charging; negative: discharging. Net battery current, not USB input current.", "Pozitif: şarj; negatif: deşarj. USB giriş akımı değil, net pil akımıdır."],
	"充电": ["Charging", "Şarj"],
	"放电": ["Discharging", "Deşarj"],
	"USB供电": ["USB power", "USB gücü"],
	"电池供电": ["Battery power", "Pil gücü"],
	"供电来源未知": ["Unknown power source", "Bilinmeyen güç kaynağı"],
	"功率和电流均为电池净值，不是 USB 输入值；充放电方向按电池电流判断。": ["Power and current are net battery values, not USB input. Direction follows battery current.", "Güç ve akım USB girişini değil, pilin net değerlerini gösterir. Yön pil akımına göre belirlenir."],
	"当前设置": ["Current setting", "Geçerli ayar"],
	"固定为 %d": ["Fixed at %d", "%d olarak sabit"],
	"保持不变（默认）": ["Not changed (default)", "Değiştirilmedi (varsayılan)"],
	"生效规则": ["Rule in force", "Etkin kural"],
	"流量卸载": ["Flow offloading", "Akış hızlandırma"],
	"已启用": ["Enabled", "Etkin"],
	"已禁用": ["Disabled", "Devre dışı"],
	"蜂窝网络 TTL": ["Cellular TTL", "Mobil veri TTL"],
	"设为 %d": ["Set %d", "%d ayarla"],
	"设置": ["Set", "Ayarla"],
	"关闭 TTL": ["Turn off TTL", "TTL kapat"],
	"请输入 1 至 255 的整数": ["Enter an integer from 1 to 255", "1 ile 255 arasında tam sayı girin"],
	"设置会保留到重启后；默认关闭。": ["Settings persist after reboot; disabled by default.", "Ayarlar yeniden başlatmada korunur; varsayılan kapalıdır."],
	"操作失败：%s": ["Failed: %s", "Başarısız: %s"],
	"管理连接已断开": ["Management connection lost", "Yönetim bağlantısı kesildi"],
	"无法读取 TTL 设置": ["Cannot read TTL settings", "TTL ayarı okunamadı"],
	"无法应用 TTL 设置": ["Cannot apply TTL settings", "TTL ayarı uygulanamadı"],
	"TTL 无效": ["Invalid TTL", "Geçersiz TTL"],
	"设置蜂窝出口数据包的 TTL 和 IPv6 跳数限制；仅影响蜂窝网络，不改变 Wi-Fi 或 USB 局域网。": ["Set the TTL and IPv6 hop limit of cellular outbound packets. Local Wi-Fi and USB traffic are unchanged.", "Hücresel çıkışın TTL ve IPv6 atlama sınırını ayarlar. Yerel Wi-Fi ve USB trafiğini değiştirmez."],
	"固定 TTL 可与软件流量卸载同时使用；IPv6 邻居发现等控制报文保持原值。启用期间暂停硬件流量卸载，关闭 TTL 后恢复原设置。": ["Fixed TTL works with software flow offloading. IPv6 neighbor discovery and other control packets keep their original hop limit. Hardware flow offloading is paused while fixed TTL is enabled, then restored when TTL is turned off.", "Sabit TTL, yazılımsal akış hızlandırmasıyla birlikte çalışır. IPv6 komşu keşfi ve diğer kontrol paketlerinin atlama sınırı korunur. Sabit TTL açıkken donanımsal akış hızlandırması duraklatılır; TTL kapatılınca geri yüklenir."],
	"软件流量卸载": ["Software flow offloading", "Yazılımsal akış hızlandırma"],
	"硬件流量卸载": ["Hardware flow offloading", "Donanımsal akış hızlandırma"],
	"固定 TTL 期间暂停": ["Paused while fixed TTL is enabled", "Sabit TTL açıkken duraklatıldı"],
	"等待蜂窝接口，出现后自动应用。": ["Waiting for a cellular interface; applies automatically when it appears.", "Hücresel arayüz bekleniyor; oluştuğunda otomatik uygulanır."],
	"旧规则，请重新应用 TTL": ["Legacy rules; apply TTL again", "Eski kurallar; TTL ayarını yeniden uygulayın"],

    "自动模式兼容性": ["Automatic mode compatibility", "Otomatik mod uyumluluğu"],
    "机型默认": ["Model default", "Model varsayılanı"],
    "全制式自动（134，含 2G）": ["All-RAT auto (134, includes 2G)", "Tüm teknolojiler otomatik (134, 2G dahil)"],
    "自动选网（152，不含 2G）": ["Auto selection (152, excludes 2G)", "Otomatik seçim (152, 2G hariç)"],
    "134：5G／4G／3G／2G 自动，可回落 2G；152：5G／4G／3G 自动，不使用 2G。编号表示制式组合，不代表固定的频段优先级。": ["134: automatic 5G/4G/3G/2G, with 2G fallback. 152: automatic 5G/4G/3G, without 2G. The numbers identify radio technology combinations, not fixed frequency-band priorities.", "134: 2G'ye geri dönüş dahil otomatik 5G/4G/3G/2G. 152: 2G olmadan otomatik 5G/4G/3G. Numaralar sabit frekans bandı önceliklerini değil, radyo teknolojisi birleşimlerini belirtir."],
    "保存并应用": ["Save and apply", "Kaydet ve uygula"],
    "此项可能影响双卡延迟和自动选网偏好，例如联通 n78／n1 的驻留选择；实际效果取决于基带和网络，不保证驻留指定频段。延迟高、网络卡顿或驻留不理想时可尝试调整，应用后会重新连接网络。": ["This option may affect dual-SIM latency and automatic network selection preferences, such as camping on China Unicom n78 or n1. Results depend on modem firmware and the network; a specific band is not guaranteed. Try adjusting it for high latency, stalls or an undesired serving band. Applying it reconnects the cellular network.", "Bu seçenek çift SIM gecikmesini ve otomatik şebeke seçimi tercihlerini, örneğin China Unicom n78 veya n1 bandına bağlanmayı etkileyebilir. Sonuç modem yazılımına ve şebekeye bağlıdır; belirli bir bant garanti edilmez. Yüksek gecikme, takılma veya istenmeyen bant seçimi durumunda değiştirmeyi deneyin. Uygulama hücresel ağı yeniden bağlar."],
    "兼容性选项由两张 SIM 共用，本次应用到当前查看的 SIM；显式 4G／SA／NSA 模式不受影响。": ["Both SIMs share this compatibility option; this operation applies to the SIM being viewed. Explicit 4G/SA/NSA modes are unaffected.", "Bu uyumluluk seçeneği iki SIM için ortaktır; işlem görüntülenen SIM için uygulanır. Açıkça seçilen 4G/SA/NSA modları etkilenmez."],
    "正在读取兼容性设置…": ["Reading compatibility settings…", "Uyumluluk ayarları okunuyor…"],
    "无法读取兼容性设置，请刷新页面后重试": ["Unable to read compatibility settings; reload the page and try again", "Uyumluluk ayarları okunamadı; sayfayı yenileyip tekrar deneyin"],
    "保存兼容性设置失败，未执行网络模式应用": ["Could not save compatibility settings; the network mode was not applied", "Uyumluluk ayarları kaydedilemedi; şebeke modu uygulanmadı"],
    '恢复核心初始状态': ['Restore initial core states', 'İlk çekirdek durumlarını geri yükle'],
    'CPU0 保持在线': ['CPU0 stays online', 'CPU0 açık kalır'],
    'CPU policy is offline; enable its cores before changing frequency': ['CPU policy is offline; enable its cores before changing frequency', 'CPU kümesi çevrimdışı; frekansı değiştirmeden önce çekirdeklerini etkinleştirin'],
    '恢复启动基线': ['Restore boot baseline', 'Başlangıç temelini geri yükle'],
    "CPU0 深度休眠": ["CPU0 deep idle", "CPU0 derin boşta bekleme"],
    "允许 CPU0 深度休眠": ["Allow CPU0 deep idle", "CPU0 derin boşta beklemesine izin ver"],
    "开启有利于空闲省电；关闭优先低延迟。仅改变 CPU0 深层空闲状态，WFI 和其他核心保持原设置。": ["Enable to favor idle power savings; disable to favor low latency. Only CPU0 deep states change; WFI and other cores keep their settings.", "Boştayken enerji tasarrufu için açın; düşük gecikme için kapatın. Yalnızca CPU0 derin durumları değişir; WFI ve diğer çekirdek ayarları korunur."],
    "设置即时生效并在开机后保留。": ["Changes apply immediately and persist across reboots.", "Ayarlar hemen uygulanır ve yeniden başlatmalarda korunur."],
    "设置已应用并保存，重启后继续生效。": ["Settings applied and saved for future boots.", "Ayarlar uygulandı ve sonraki açılışlar için kaydedildi."],
    "无法读取 CPU0 深度休眠状态": ["Cannot read CPU0 deep idle state", "CPU0 derin boşta bekleme durumu okunamıyor"],
    "CPU0 深度休眠设置失败": ["CPU0 deep idle change failed", "CPU0 derin boşta bekleme ayarı başarısız"],
    "CPU 核心开关": ["CPU core controls", "CPU çekirdek denetimleri"],
    "按内核能力逐核开启或关闭。CPU0 保持在线；关闭核心会降低并行处理能力，是否省电取决于实际负载。": ["Enable or disable individual cores supported by the kernel. CPU0 stays online. Disabling cores reduces parallel capacity; power savings depend on the workload.", "Çekirdek desteğine göre CPU çekirdeklerini açın veya kapatın. CPU0 açık kalır. Çekirdek kapatmak paralel kapasiteyi azaltır; enerji tasarrufu yüke bağlıdır."],
    "仅保存核心开关；不改变调频、调压和温控配置。": ["Save core states only; frequency, voltage and thermal settings are unchanged.", "Yalnızca çekirdek durumlarını kaydeder; frekans, voltaj ve sıcaklık ayarları değişmez."],
    "应用核心设置": ["Apply core settings", "Çekirdek ayarlarını uygula"],
    "正在读取核心状态…": ["Reading core states…", "Çekirdek durumları okunuyor…"],
    "核心设置已应用；调频与温控页面将在下次打开时刷新。": ["Core settings applied. Reopen CPU settings to refresh frequency and thermal controls.", "Çekirdek ayarları uygulandı. Frekans ve sıcaklık kontrollerini yenilemek için CPU ayarlarını yeniden açın."],
    "此核心由内核管理，不能关闭": ["This core is managed by the kernel and cannot be disabled", "Bu çekirdek sistem tarafından yönetiliyor ve kapatılamaz"],
    "CPU 核心配置无效": ["Invalid CPU core settings", "Geçersiz CPU çekirdek ayarları"],
    "CPU 核心列表已变化，请重新载入": ["The CPU core list changed; reload the page", "CPU çekirdek listesi değişti; sayfayı yenileyin"],
    "无法保存核心设置": ["Unable to save core settings", "Çekirdek ayarları kaydedilemedi"],
    "内核未接受核心开关设置": ["The kernel rejected the core state change", "Sistem çekirdek durumu değişikliğini reddetti"],
    "核心设置正忙，请稍后重试": ["Core settings are busy; try again shortly", "Çekirdek ayarları meşgul; biraz sonra yeniden deneyin"],
    "无法读取 CPU 核心状态": ["Unable to read CPU core states", "CPU çekirdek durumları okunamadı"],
    "回滚未完成，请检查实际核心状态": ["Rollback was incomplete; check the actual core states", "Geri alma tamamlanamadı; gerçek çekirdek durumlarını kontrol edin"],
    "离线": ["Offline", "Çevrimdışı"],
	'保存并应用': ['Save & apply', 'Kaydet ve uygula'],
	"充电管理": ["Charging controls", "Şarj denetimi"],
	"当前电量": ["Battery level", "Pil seviyesi"],
	"充电状态": ["Charging status", "Şarj durumu"],
	"正在读取…": ["Reading…", "Okunuyor…"],
	"启用充电上限": ["Enable charge limit", "Şarj sınırını etkinleştir"],
	"停止充电于（50–100%）": ["Stop charging at (50–100%)", "Şarjı durdur (%50–100)"],
	"恢复充电于（20–95%）": ["Resume charging at (20–95%)", "Şarjı sürdür (%20–95)"],
	"到达上限后暂停充电，降至下限时恢复。关闭上限会恢复正常充电。设置与屏幕共用，重启后保留。": ["Charging pauses at the upper limit and resumes at the lower limit. Disabling the limit restores normal charging. Settings are shared with the screen and persist after reboot.", "Üst sınırda şarj durur, alt sınırda sürer. Sınırı kapatmak normal şarjı geri getirir. Ayarlar ekranla ortaktır ve yeniden başlatmada korunur."],
	"临时充满一次": ["Charge to full once", "Bir kez tam şarj et"],
	"正在临时充满…": ["Charging to full once…", "Bir kez tam şarj ediliyor…"],
	"临时充满后，自动恢复原来的充电上限。": ["The original charge limit resumes automatically after reaching full charge.", "Tam şarjdan sonra önceki şarj sınırı otomatik geri yüklenir."],
	"充电阈值必须是范围内的整数": ["Charge thresholds must be whole numbers within range", "Şarj eşikleri belirtilen aralıkta tam sayı olmalıdır"],
	"恢复充电阈值必须低于停止阈值": ["The resume threshold must be lower than the stop threshold", "Devam eşiği durdurma eşiğinden düşük olmalıdır"],
	"插电直接启动 OpenWrt": ["Boot OpenWrt when plugged in", "Güç bağlandığında OpenWrt'yi başlat"],
	"关机后插电，跳过充电动画并启动系统。关闭此选项保留关机充电；下次启动生效。": ["After shutdown, plug in to skip the charging screen and boot. Turn this off to keep charging mode. Takes effect on the next boot.", "Kapatıldıktan sonra güç bağlandığında şarj ekranını atlayıp başlatır. Şarj modunu korumak için kapatın. Sonraki açılışta uygulanır."],
	"当前设备的充电控制暂不可用": ["Charging controls are currently unavailable on this device", "Bu cihazda şarj denetimi şu anda kullanılamıyor"],
	"充电设置保存失败": ["Failed to save charging settings", "Şarj ayarları kaydedilemedi"],
	"充电设置已保存，但服务应用失败，请重试": ["Charging settings were saved, but the service could not apply them. Please retry.", "Şarj ayarları kaydedildi ancak hizmet uygulayamadı. Yeniden deneyin."],
	"充电设置正在应用，请稍后重试": ["Charging settings are being applied. Please try again shortly.", "Şarj ayarları uygulanıyor. Biraz sonra yeniden deneyin."],
	"充电控制读取失败，请刷新重试": ["Failed to read charging controls. Refresh to retry.", "Şarj denetimi okunamadı. Yenileyerek tekrar deneyin."],
	"已按上限暂停充电": ["Paused at charge limit", "Şarj sınırında duraklatıldı"],
	"已充满": ["Fully charged", "Tam şarj oldu"],
	"正在充电": ["Charging", "Şarj ediliyor"],
	"使用电池": ["On battery", "Pille çalışıyor"],
	"未充电": ["Not charging", "Şarj olmuyor"],
	"正在应用充电设置…": ["Applying charging settings…", "Şarj ayarları uygulanıyor…"],
	"充电设置已应用，与屏幕同步生效": ["Charging settings applied and shared with the screen", "Şarj ayarları uygulandı ve ekranla eşitlendi"],
	'转发配置': ['Forwarding profiles', 'Yönlendirme profilleri'],
	'启用当前配置': ['Enable this profile', 'Bu profili etkinleştir'],
	'电源通知使用共用配置；请同时开启该配置并设置渠道。': ['Power notifications use the shared profile; enable that profile and configure its channel.', 'Güç bildirimleri ortak profili kullanır; bu profili etkinleştirip kanalını yapılandırın.'],
	'转发正在执行，请稍后再试': ['A delivery is running; please try again shortly', 'Bir gönderim sürüyor; lütfen biraz sonra tekrar deneyin'],
	'配置模式': ['Configuration mode', 'Yapılandırma modu'],
	'所有 SIM 共用': ['Shared by all SIMs', 'Tüm SIM kartları için ortak'],
	'按 SIM 独立配置': ['Separate profile per SIM', 'SIM başına ayrı profil'],
	'正在编辑': ['Editing profile', 'Düzenlenen profil'],
	'共用配置 / 电源通知': ['Shared profile / power notifications', 'Ortak profil / güç bildirimleri'],
	'独立模式按收到短信的卡选择渠道和黑名单，不受上网卡切换影响。电源通知始终使用共用配置。': ['Separate mode selects the channel and blacklist by the receiving SIM, not the data SIM. Power notifications always use the shared profile.', 'Ayrı modda kanal ve kara liste veri SIM kartına değil, SMS alan karta göre seçilir. Güç bildirimleri her zaman ortak profili kullanır.'],
	'当前配置用于新短信转发。': ['This profile handles new incoming SMS.', 'Bu profil yeni gelen SMS mesajlarını yönlendirir.'],
	'当前配置不用于短信；保存后仍保留，可单独测试。': ['This profile is inactive for SMS; its settings are retained and can be tested separately.', 'Bu profil SMS için etkin değil; ayarları korunur ve ayrı olarak test edilebilir.'],
	'电源通知请在共用配置中设置，独立模式下仍生效。': ['Configure power notifications in the shared profile; they remain active in separate mode.', 'Güç bildirimlerini ortak profilde ayarlayın; ayrı modda da etkin kalır.'],
	'填入推送预设': ['Fill from a push preset', 'Bildirim ön ayarını doldur'],
	'自定义 / 兼容旧版': ['Custom / legacy compatible', 'Özel / eski sürümle uyumlu'],
	'企业微信': ['WeCom', 'WeCom'],
	'钉钉 Webhook': ['DingTalk Webhook', 'DingTalk Webhook'],
	'预设只填入表单，请替换密钥后保存；需要钉钉加签时请选择“钉钉机器人”。': ['Presets only fill the form. Replace the keys and save; use DingTalk bot for signed requests.', 'Ön ayarlar yalnızca formu doldurur. Anahtarları değiştirip kaydedin; imzalı istekler için DingTalk botunu seçin.'],
	'请求方法': ['Request method', 'İstek yöntemi'],
	'请求超时（秒，1–120）': ['Request timeout (seconds, 1–120)', 'İstek zaman aşımı (saniye, 1–120)'],
	'正文格式': ['Body format', 'Gövde biçimi'],
	'正文模板': ['Body template', 'Gövde şablonu'],
	'纯文本': ['Plain text', 'Düz metin'],
	'占位符：{from}、{text}、{time}、{sim}、{device}、{kind}。JSON 占位符放在字符串内；按格式自动转义，绝不执行命令。': ['Placeholders: {from}, {text}, {time}, {sim}, {device}, {kind}. Put JSON placeholders inside strings; values are escaped for the format, never executed.', 'Yer tutucular: {from}, {text}, {time}, {sim}, {device}, {kind}. JSON yer tutucularını dizgelerin içine koyun; değerler biçime göre kaçışlanır, komut olarak çalıştırılmaz.'],
	'GET 只发送 URL 参数；JSON 模板留空时沿用旧版 from/text/date 格式。仅支持公网 HTTPS，验证证书且不跟随重定向。': ['GET sends URL parameters only. An empty JSON template preserves the legacy from/text/date format. Public HTTPS only, with certificate verification and no redirects.', 'GET yalnızca URL parametrelerini gönderir. Boş JSON şablonu eski from/text/date biçimini korur. Yalnızca genel HTTPS; sertifika doğrulanır, yönlendirmeler izlenmez.'],
	'附加请求头（每行 Name: value）': ['Extra headers (Name: value, one per line)', 'Ek başlıklar (satır başına Name: value)'],
	'请求超时必须为 1–120 秒': ['Request timeout must be 1–120 seconds', 'İstek zaman aşımı 1–120 saniye olmalıdır'],
	'正文模板必须是有效 JSON': ['Body template must be valid JSON', 'Gövde şablonu geçerli JSON olmalıdır'],
	'填入推送预设？': ['Fill from this push preset?', 'Bu bildirim ön ayarı doldurulsun mu?'],
	'将替换当前 Webhook 地址、正文及请求头，保存后才会生效。': ['This replaces the Webhook URL, body and headers in the form. Changes take effect only after saving.', 'Formdaki Webhook adresi, gövde ve başlıklar değiştirilir. Değişiklikler yalnızca kaydettikten sonra geçerli olur.'],
	'切换编辑配置？': ['Switch the profile being edited?', 'Düzenlenen profil değiştirilsin mi?'],
	'未保存的修改将被丢弃。': ['Unsaved changes will be discarded.', 'Kaydedilmemiş değişiklikler silinecek.'],
	'最近投递记录': ['Recent deliveries', 'Son teslimatlar'],
	'测试消息': ['Test message', 'Test mesajı'],
	'仅保留本次开机最近 30 次投递结果，不记录号码、地址或短信内容。': ['Keeps the last 30 delivery results since boot; no numbers, addresses or message content are recorded.', 'Açılıştan bu yana son 30 teslimat sonucu tutulur; numara, adres veya mesaj içeriği kaydedilmez.'],
	"频率与调速策略": ["Frequency and governor", "Frekans ve yönetici"],
	"即时生效": ["Applies immediately", "Hemen uygulanır"],
	"电压设置": ["Voltage settings", "Voltaj ayarları"],
	"重启后生效": ["Applies after reboot", "Yeniden başlatmada uygulanır"],
	"当前频率": ["Current frequency", "Geçerli frekans"],
	"当前内核或固件不支持开机电压调整": ["Boot voltage adjustment is unavailable with this kernel or firmware", "Bu çekirdek veya ürün yazılımı açılış voltajı ayarını desteklemiyor"],
	"当前有效范围：": ["Effective range: ", "Etkin aralık: "],
	"原厂电压（0 mV）": ["Factory voltage (0 mV)", "Fabrika voltajı (0 mV)"],
	"当前偏移：": ["Active offset: ", "Etkin ofset: "],
	" · 实测 ": [" · Measured ", " · Ölçülen "],
	"CPU 设置": ["CPU settings", "CPU ayarları"],
	"频率 · 电压 · 温控": ["Frequency · Voltage · Thermal", "Frekans · Voltaj · Sıcaklık"],
	"CPU 调频驱动尚未就绪": ["The CPU frequency driver is not ready", "CPU frekans sürücüsü henüz hazır değil"],
	"调速器": ["Governor", "Frekans yöneticisi"],
	"最低频率": ["Minimum frequency", "En düşük frekans"],
	"最高频率": ["Maximum frequency", "En yüksek frekans"],
	"schedutil 按负载调频；powersave 请求最低频率。上下限相同可固定频率，温控仍可降频。": ["schedutil follows load; powersave requests the minimum. Equal limits fix the requested frequency; thermal limits still apply.", "schedutil yüke göre frekansı ayarlar; powersave en düşük frekansı ister. Eşit sınırlar istenen frekansı sabitler; sıcaklık koruması frekansı yine düşürebilir."],
	"下次启动电压偏移": ["Voltage offset on next boot", "Sonraki açılışta voltaj ofseti"],
	"保存后重启生效，CPU 与 SRAM 由固件同步调整。降压可能不稳定，建议每次只调一档；异常断电或崩溃后，下次启动自动恢复原厂电压。": ["Saved separately and applied after reboot. Firmware adjusts CPU and SRAM together. Undervolting can be unstable: change one step at a time. An unclean shutdown restores factory voltage on the next boot.", "Ayrı kaydedilir ve yeniden başlatmada uygulanır. Ürün yazılımı CPU ve SRAM voltajını birlikte ayarlar. Düşük voltaj kararsızlığa neden olabilir; her seferinde tek kademe değiştirin. Beklenmeyen kapanma veya çökme sonrasında fabrika voltajı geri yüklenir."],
	"查看频率与电压表": ["Frequency and voltage table", "Frekans ve voltaj tablosu"],
	"此表为当前生效的固件电压表。偏移作用于整个供电域，不能逐频点单独改压，也不新增超频档位。": ["The active firmware voltage table. Offsets apply to the whole domain; individual frequency edits and extra overclock states are unavailable.", "Bu, ürün yazılımının etkin voltaj tablosudur. Ofset tüm güç alanına uygulanır; her frekans için ayrı voltaj ayarlanamaz ve yeni hız aşırtma kademeleri eklenmez."],
	"温控": ["Thermal", "Sıcaklık denetimi"],
	"被动温控起点": ["Passive monitoring threshold", "Pasif izleme eşiği"],
	"降频触发温度": ["CPU throttling threshold", "CPU frekans düşürme eşiği"],
	"过热关机保护": ["Critical shutdown", "Aşırı ısınmada kapatma koruması"],
	"被动温控起点用于更频繁地检测温度，达到降频触发温度才限制 CPU。阈值按顺序递增，原厂回差与过热关机保护保持生效。": ["Passive monitoring increases temperature checks; CPU throttling starts at the bound trip. Trips must increase in order. Factory hysteresis and critical shutdown remain active.", "Pasif izleme eşiği sıcaklığı daha sık kontrol ettirir; CPU frekansı bağlı eşikte sınırlanır. Eşikler artan sırada olmalıdır. Fabrika histerezisi ve aşırı ısınmada kapatma koruması etkin kalır."],
	"开机应用调频与温控": ["Apply frequency and thermal settings at boot", "Frekans ve sıcaklık ayarlarını açılışta uygula"],
	"应用设置": ["Apply settings", "Ayarları uygula"],
	"恢复默认": ["Restore defaults", "Varsayılanları geri yükle"],
	"调频与温控可即时应用；电压设置独立保存，重启后生效。恢复默认后，电压也需要重启才能还原。关机充电始终使用原厂电压。": ["Frequency and thermal settings apply immediately; voltage settings are saved separately and need a reboot, including when restoring defaults. Charger-only boot uses factory voltage.", "Frekans ve sıcaklık ayarları hemen uygulanır. Voltaj ayrı kaydedilir ve varsayılanlara dönüş dahil yeniden başlatma gerektirir. Kapalıyken şarj modu her zaman fabrika voltajını kullanır."],
	"上次开机配置未应用：": ["The boot profile was rejected: ", "Açılış profili uygulanamadı: "],
	"电压配置已回退：": ["Voltage profile reverted: ", "Voltaj profili geri alındı: "],
	"电压配置已保存，重启后生效": ["Voltage settings saved; reboot to apply", "Voltaj ayarları kaydedildi; uygulamak için yeniden başlatın"],
	"最低频率不能大于最高频率": ["Minimum frequency must not exceed maximum", "En düşük frekans en yüksek frekansı aşamaz"],
	"请填写有效的温度阈值": ["Enter a valid temperature threshold", "Geçerli bir sıcaklık eşiği girin"],
	"调频与温控已应用；电压配置已保存，重启后生效": ["Frequency and thermal settings applied; reboot to apply saved voltage settings", "Frekans ve sıcaklık ayarları uygulandı; kaydedilen voltaj için yeniden başlatın"],
	"已应用，并读取确认当前设置": ["Applied and confirmed by kernel readback", "Uygulandı ve çekirdekten okunarak doğrulandı"],
	"设备适配更新源需声明 adaptation=e5-device-ui-v1，更新包也须包含对应 ADAPTATION 标记；未适配的上游包不能覆盖当前界面。": ["The device update feed must declare adaptation=e5-device-ui-v1 and the package must contain the matching ADAPTATION marker. Generic upstream packages cannot replace this interface.", "Cihaz güncelleme kaynağı adaptation=e5-device-ui-v1 bildirmeli, paket de eşleşen ADAPTATION işaretini içermelidir. Uyarlanmamış üst kaynak paketleri bu arayüzün üzerine kurulamaz."],
	"更新 JSON 地址": ["Update JSON URL", "Güncelleme JSON adresi"],
	'上网 SIM 卡': ['Data SIM', 'İnternet SIM kartı'],
	'当前上网卡': ['Current data SIM', 'Etkin internet SIM kartı'],
	'切换上网卡': ['Switch data SIM', 'İnternet SIM kartını değiştir'],
	'切换会重新连接蜂窝网络，并保存为开机使用的卡槽。': ['Switching reconnects cellular data and saves the SIM selection for boot.', 'Değiştirme mobil veriyi yeniden bağlar ve SIM seçimini sonraki açılış için kaydeder.'],
	'正在切换上网卡…': ['Switching data SIM…', 'İnternet SIM kartı değiştiriliyor…'],
	'上网卡已切换，正在刷新连接状态。': ['Data SIM switched; refreshing connection status.', 'İnternet SIM kartı değiştirildi; bağlantı durumu yenileniyor.'],
	'切换等待超时，请刷新实际状态': ['Switch timed out; refresh the actual state', 'Değiştirme zaman aşımına uğradı; mevcut durumu yenileyin'],
	'无法读取切换结果': ['Cannot read the switch result', 'Değiştirme sonucu okunamıyor'],
	'SIM 卡管理': ['SIM management', 'SIM yönetimi'],
	'开机使用': ['SIM at boot', 'Açılışta SIM'],
	'切换上网卡后，看板、锁定和 AT 的查看卡槽会同步；仍可手动查看另一张卡。': ['After switching the data SIM, dashboard, lock and AT views follow it; you can still select the other SIM manually.', 'İnternet SIM kartı değiştirildiğinde panel, kilit ve AT görünümleri onu izler; diğer SIM kartı yine elle seçebilirsiniz.'],
	'提交失败': ['Submission failed', 'Gönderim başarısız'],
	'与屏幕共用系统双卡短信池': ['Shared system inbox for both SIMs and the screen', 'Ekran ile ortak çift SIM mesaj kutusu'],
	'清空当前卡记录': ['Clear this SIM history', 'Bu SIM geçmişini temizle'],
	'清空流量记录': ['Clear traffic history', 'Veri geçmişini temizle'],
	'清空': ['Clear', 'Temizle'],
	'今日、本月、历史和周期校准将清零，套餐额度与计量设置保留。此操作无法撤销。': ['Daily, monthly and historical usage and cycle adjustments will be cleared. Plan settings are kept. This cannot be undone.', 'Günlük, aylık ve geçmiş kullanım ile dönem düzeltmeleri silinir. Paket ayarları korunur. Geri alınamaz.'],
	'正在清空流量记录…': ['Clearing traffic history…', 'Veri geçmişi temizleniyor…'],
	'流量记录已清空': ['Traffic history cleared', 'Veri geçmişi temizlendi'],
	'请选择有效的 SIM 卡槽': ['Select a valid SIM slot', 'Geçerli bir SIM yuvası seçin'],
	'需要确认清空': ['Confirm before clearing', 'Temizlemeyi onaylayın'],
	'正在读取服务小区…': ['Loading serving cell…', 'Hizmet hücresi yükleniyor…'],
	'正在读取锁定设置…': ['Loading lock settings…', 'Kilit ayarları yükleniyor…'],
	'正在读取邻小区…': ['Loading neighboring cells…', 'Komşu hücreler yükleniyor…'],
	'邻区读取较慢，正在等待模组回应': ['Neighbor scan is taking longer; waiting for the modem.', 'Komşu taraması uzun sürüyor; modemin yanıtı bekleniyor.'],
	'邻区读取失败': ['Could not load neighboring cells', 'Komşu hücreler yüklenemedi'],
	'信号读取失败': ['Could not load signal', 'Sinyal yüklenemedi'],
	'锁定状态读取失败，请刷新': ['Could not load lock settings; please refresh', 'Kilit ayarları yüklenemedi; lütfen yenileyin'],
	'查看 / 控制卡槽': ['View / control SIM', 'SIM görüntüle / yönet'],
	'仅切换查看与操作对象，不切换上网卡': ['Select the SIM to view and control; the data SIM stays unchanged.', 'Görüntülenecek ve yönetilecek SIM kartı seçin; veri SIM kartı değişmez.'],
	'会话': ['Conversations', 'Görüşmeler'],
	'收件人': ['Recipient', 'Alıcı'],
	'发送卡': ['Send with', 'Gönderen SIM'],
	'全部 SIM': ['All SIMs', 'Tüm SIM kartlar'],
	'当前数据卡': ['Current data SIM', 'Geçerli veri SIM kartı'],
	'暂无短信': ['No messages yet', 'Henüz mesaj yok'],
	'暂无会话': ['No conversations yet', 'Henüz görüşme yok'],
	'短信内容': ['Message', 'Mesaj'],
	'号码，如 10086 或 +86…': ['Number, e.g. 10086 or +86…', 'Numara, ör. 10086 veya +86…'],
	'选择会话查看短信，或填写收件人开始新短信。': ['Select a conversation, or enter a recipient to start a new message.', 'Bir görüşme seçin veya yeni mesaj için alıcı girin.'],
	'收到的短信会显示在这里，可尝试从 SIM 同步。': ['Received messages appear here. You can also sync from the SIM.', 'Gelen mesajlar burada görünür. SIM karttan da eşitleyebilirsiniz.'],
	'选择发送卡不会切换移动数据卡。删除单条：点击气泡上的删除按钮。': ['Choosing a sending SIM does not switch mobile data. Use the delete button on a message to remove it.', 'Gönderen SIM seçimi mobil veriyi değiştirmez. Mesajı silmek için üzerindeki sil düğmesini kullanın.'],
	'本机号码': ['Phone number', 'Telefon numarası'],
	'流量池': ['Data plan', 'Veri paketi'],
	'今日流量': ['Today’s data', 'Bugünkü veri'],
	'当月流量': ['This month’s data', 'Bu ayki veri'],
	'自然月统计': ['Calendar-month usage', 'Takvim ayı kullanımı'],
	'套餐周期已用': ['Used this billing cycle', 'Bu dönemde kullanılan'],
	'套餐剩余': ['Plan remaining', 'Pakette kalan'],
	'套餐与流量池': ['Plan and data allowance', 'Paket ve veri kotası'],
	'套餐名称': ['Plan name', 'Paket adı'],
	'每周期额度（GB）': ['Allowance per cycle (GB)', 'Dönem kotası (GB)'],
	'每日参考额度（GB）': ['Daily reference allowance (GB)', 'Günlük referans kotası (GB)'],
	'每月重置日（1–31）': ['Monthly reset day (1–31)', 'Aylık sıfırlama günü (1–31)'],
	'套餐计量方式': ['Plan accounting', 'Paket hesaplama yöntemi'],
	'上下行合计': ['Download + upload', 'İndirme + yükleme'],
	'仅下行': ['Download only', 'Yalnızca indirme'],
	'仅上行': ['Upload only', 'Yalnızca yükleme'],
	'额度为 0 表示不限量；1 GB = 1000 MB。重置日在设备当地时间零点生效，短月份使用当月最后一天。': ['Set 0 for unlimited; 1 GB = 1000 MB. Reset takes place at midnight in the device timezone; shorter months use their last day.', 'Sınırsız için 0 girin; 1 GB = 1000 MB. Sıfırlama cihazın yerel saatine göre gece yarısı yapılır; kısa aylarda ayın son günü kullanılır.'],
	'统计网卡': ['Accounting interface', 'İstatistik arayüzü'],
	'自动使用蜂窝 WAN 网卡': ['Use the cellular WAN interface automatically', 'Hücresel WAN arayüzünü otomatik kullan'],
	'校准本周期已用（GB，可选）': ['Adjust used data this cycle (GB, optional)', 'Bu dönem kullanılan veriyi düzelt (GB, isteğe bağlı)'],
	'留空保持现有统计': ['Leave blank to keep existing usage', 'Mevcut kullanımı korumak için boş bırakın'],
	'校准只调整当前套餐周期，不修改每日和自然月历史；下个周期自动恢复实际统计。': ['Adjustments affect only the current billing cycle, not daily or calendar-month history. The next cycle uses measured data again.', 'Düzeltme yalnızca mevcut paket dönemini etkiler; günlük ve takvim ayı geçmişi değişmez. Sonraki dönemde ölçülen veri kullanılır.'],
	'最近每日用量': ['Recent daily usage', 'Son günlük kullanımlar'],
	'每月用量历史': ['Monthly usage history', 'Aylık kullanım geçmişi'],
	'日期': ['Date', 'Tarih'],
	'月份': ['Month', 'Ay'],
	'下行': ['Download', 'İndirme'],
	'上行': ['Upload', 'Yükleme'],
	'合计': ['Total', 'Toplam'],
	'从启用统计时开始记录；统计约每 10 秒更新、每 60 秒保存。突然断电可能损失最近未保存的记录。': ['Recording starts when accounting is enabled. Usage updates about every 10 seconds and is saved every 60 seconds. Sudden power loss may lose recent unsaved usage.', 'Kayıt, istatistik hizmeti açıldığında başlar. Kullanım yaklaşık 10 saniyede güncellenir, 60 saniyede kaydedilir. Ani güç kesintisinde son kaydedilmemiş veriler kaybolabilir.'],
	'本地网卡统计供参考，计费以运营商为准。额度用于显示和提醒，不会自动断网。': ['Local interface statistics are an estimate; carrier billing takes precedence. Allowances display warnings and never disconnect the network.', 'Yerel arayüz istatistikleri tahminidir; operatörün hesabı esas alınır. Kotalar uyarı gösterir, ağı otomatik kesmez.'],
	'不限量': ['Unlimited', 'Sınırsız'],
	'未设置套餐名称': ['No plan name set', 'Paket adı ayarlanmadı'],
	'每周期额度：': ['Cycle allowance: ', 'Dönem kotası: '],
	'下次重置：': ['Next reset: ', 'Sonraki sıfırlama: '],
	'每日参考额度：': ['Daily reference allowance: ', 'Günlük referans kotası: '],
	'更新于：': ['Updated: ', 'Güncelleme: '],
	'流量统计服务暂不可用': ['Data accounting service is unavailable', 'Veri istatistik hizmeti kullanılamıyor'],
	'统计网卡暂不可用': ['Accounting interface is unavailable', 'İstatistik arayüzü kullanılamıyor'],
	'系统时间尚未同步': ['System clock is not synchronized yet', 'Sistem saati henüz eşitlenmedi'],
	'统计数据保存失败': ['Failed to save usage data', 'Kullanım verileri kaydedilemedi'],
	'已达到套餐额度': ['Plan allowance reached', 'Paket kotasına ulaşıldı'],
	'已达到每日参考额度': ['Daily reference allowance reached', 'Günlük referans kotasına ulaşıldı'],
	'暂无统计记录': ['No usage records yet', 'Henüz kullanım kaydı yok'],
	'校准本周期已用流量？': ['Adjust this cycle’s used data?', 'Bu dönemin kullanılan verisi düzeltilecek mi?'],
	'这会将当前套餐周期已用值调整为输入值，每日和自然月记录不变。': ['This sets current cycle usage to the entered value. Daily and calendar-month records stay unchanged.', 'Mevcut dönem kullanımı girilen değere ayarlanır. Günlük ve takvim ayı kayıtları değişmez.'],
	'正在保存流量池设置…': ['Saving data plan settings…', 'Veri paketi ayarları kaydediliyor…'],
	'短信转发': ['SMS forwarding', 'SMS yönlendirme'],
	'开启短信转发': ['Enable SMS forwarding', 'SMS yönlendirmeyi aç'],
	'转发已开启': ['Forwarding enabled', 'Yönlendirme açık'],
	'转发未开启': ['Forwarding disabled', 'Yönlendirme kapalı'],
	'转发方式': ['Forwarding method', 'Yönlendirme yöntemi'],
	'模板语言': ['Template language', 'Şablon dili'],
	'简体中文': ['Simplified Chinese', 'Basitleştirilmiş Çince'],
	'保存后用于转发标题、提示文字和电源通知；短信原文及设备备注保持不变。': ['After saving, this language is used for forwarding titles, labels, and power notifications. Original SMS text and device notes stay unchanged.', 'Kaydettikten sonra yönlendirme başlıkları, etiketler ve güç bildirimleri bu dilde gönderilir. SMS metni ve cihaz notları değiştirilmez.'],
	'钉钉机器人': ['DingTalk bot', 'DingTalk botu'],
	'本机短信': ['Device SMS', 'Cihaz SMS’i'],
	'邮件 SMTP': ['Email SMTP', 'E-posta SMTP'],
	'HTTPS 地址': ['HTTPS address', 'HTTPS adresi'],
	'以固定 JSON 格式发送，不执行自定义命令。': ['Sends a fixed JSON payload; no custom commands are run.', 'Sabit bir JSON gönderir; özel komut çalıştırılmaz.'],
	'机器人 Webhook 地址': ['Bot webhook URL', 'Bot webhook adresi'],
	'加签密钥 · 留空保留': ['Signing secret · leave blank to keep', 'İmza anahtarı · korumak için boş bırakın'],
	'清除加签密钥': ['Clear signing secret', 'İmza anahtarını sil'],
	'附带设备信息': ['Include device information', 'Cihaz bilgisini ekle'],
	'SMTP 服务器域名': ['SMTP server domain', 'SMTP sunucu alan adı'],
	'端口 · 465 / 587': ['Port · 465 / 587', 'Bağlantı noktası · 465 / 587'],
	'发件邮箱': ['Sender email', 'Gönderen e-posta'],
	'收件邮箱': ['Recipient email', 'Alıcı e-posta'],
	'授权码 / 密码 · 留空保留': ['App password / password · leave blank to keep', 'Uygulama şifresi / şifre · korumak için boş bırakın'],
	'已配置，留空保留': ['Configured; leave blank to keep', 'Yapılandırıldı; korumak için boş bırakın'],
	'请输入授权码': ['Enter an app password', 'Uygulama şifresini girin'],
	'可选': ['Optional', 'İsteğe bağlı'],
	'清除邮件配置': ['Clear email configuration', 'E-posta yapılandırmasını sil'],
	'使用邮箱提供的 SMTP 授权码；始终验证 TLS 证书。': ['Use your email provider’s SMTP app password; the TLS certificate is always verified.', 'E-posta sağlayıcınızın SMTP uygulama şifresini kullanın; TLS sertifikası her zaman doğrulanır.'],
	'短信接收号码 · 每行一个，最多 3 个': ['SMS recipients · one per line, up to 3', 'SMS alıcıları · satır başına bir, en fazla 3'],
	'经本机 SIM 转发，可能产生短信费用；每条最多 70 个 UCS-2 单元，不限制每日转发条数。': ['Forwarding uses the device SIM and may incur SMS charges; up to 70 UCS-2 units per message, with no daily forwarding limit.', 'Yönlendirme cihazın SIM kartını kullanır ve ücret doğurabilir; mesaj başına en fazla 70 UCS-2 birimi, günlük yönlendirme sınırı yoktur.'],
	'电源通知': ['Power notifications', 'Güç bildirimleri'],
	'电源状态通知': ['Power status notifications', 'Güç durumu bildirimleri'],
	'充电状态变化，或电量跨过 5%、20%、40%、60%、80%、100% 时通知。': ['Notify when charging status changes or battery level crosses 5%, 20%, 40%, 60%, 80%, or 100%.', 'Şarj durumu değiştiğinde veya pil seviyesi %5, %20, %40, %60, %80 ya da %100 eşiğini geçtiğinde bildir.'],
	'设备暂未提供有效电池状态': ['No valid battery status is available on this device', 'Bu cihazda geçerli pil durumu yok'],
	'设备备注': ['Device note', 'Cihaz notu'],
	'黑名单': ['Blocklists', 'Engelleme listeleri'],
	'号码黑名单 · 每行一个，最多 64 个': ['Number blocklist · one per line, up to 64', 'Numara engelleme listesi · satır başına bir, en fazla 64'],
	'关键词黑名单 · 每行一个，最多 32 个': ['Keyword blocklist · one per line, up to 32', 'Anahtar kelime engelleme listesi · satır başına bir, en fazla 32'],
	'命中的新短信只记为已处理，不会转发；清空规则后不会补发。规则不影响电源通知。': ['Matching new SMS are marked processed and not forwarded; clearing rules will not resend them. Power notifications are unaffected.', 'Eşleşen yeni SMS’ler işlenmiş sayılır ve yönlendirilmez; kurallar silinince tekrar gönderilmez. Güç bildirimleri etkilenmez.'],
	'测试与状态': ['Test and status', 'Test ve durum'],
	'设备独立执行，关闭页面仍生效；仅转发新短信，失败不自动重发。': ['Runs on the device even with this page closed; only new SMS are forwarded, and failed deliveries are not retried.', 'Sayfa kapalıyken de cihazda çalışır; yalnızca yeni SMS’ler yönlendirilir ve başarısız teslimatlar yeniden denenmez.'],
	'保存设置': ['Save settings', 'Ayarları kaydet'],
	'发送测试消息': ['Send test message', 'Test mesajı gönder'],
	'刷新状态': ['Refresh status', 'Durumu yenile'],
	'最近转发：': ['Last forwarding: ', 'Son yönlendirme: '],
	'最近电源通知：': ['Last power notice: ', 'Son güç bildirimi: '],
	"成功响应条件（可选）": ["Success response condition (optional)", "Başarılı yanıt koşulu (isteğe bağlı)"],
	"留空时任意 HTTP 2xx 为成功；填写 errcode=0 或 ok=true 时，还需响应 JSON 顶层字段匹配。": ["Empty accepts any HTTP 2xx; errcode=0 or ok=true also checks a top-level JSON field.", "Boşken tüm HTTP 2xx yanıtları başarılıdır; errcode=0 veya ok=true üst düzey JSON alanını da denetler."],
	"成功响应条件格式无效": ["Invalid success response condition", "Başarılı yanıt koşulu geçersiz"],
	"服务返回失败结果": ["The service rejected the delivery", "Hizmet gönderimi reddetti"],
	"服务响应无法确认成功": ["The service response does not confirm success", "Hizmet yanıtı başarıyı doğrulamıyor"],
	"请等待 5 秒后再测试": ["Please wait 5 seconds before testing again", "Tekrar denemeden önce 5 saniye bekleyin"],
	"清空投递记录": ["Clear delivery history", "Teslimat geçmişini temizle"],
	"清空投递记录？": ["Clear delivery history?", "Teslimat geçmişi temizlensin mi?"],
	"只清除最近投递记录，不影响短信、转发配置或已处理状态。": ["Only clears delivery history; messages, settings and processed state stay unchanged.", "Yalnızca teslimat geçmişini temizler; mesajlar, ayarlar ve işlenen kayıtlar korunur."],
	'暂无投递': ['No delivery yet', 'Henüz teslimat yok'],
	'发送成功': ['Sent successfully', 'Başarıyla gönderildi'],
	'已拦截向原发件人转发': ['Forwarding to original sender blocked', 'Asıl gönderene yönlendirme engellendi'],
	'短信过长，未发送': ['SMS too long; not sent', 'SMS çok uzun; gönderilmedi'],
	'设备保存失败': ['Device storage failed', 'Cihaza kaydedilemedi'],
	'短信服务暂不可用': ['SMS service temporarily unavailable', 'SMS hizmeti geçici olarak kullanılamıyor'],
	'配置无效': ['Invalid configuration', 'Geçersiz yapılandırma'],
	'目标地址无效': ['Invalid destination', 'Geçersiz hedef adresi'],
	'投递失败，请检查配置和设备网络': ['Delivery failed; check the settings and device network', 'Teslimat başarısız; ayarları ve cihaz ağını kontrol edin'],
	'邮箱服务器拒绝登录，请检查授权码': ['SMTP login rejected; check the app password', 'SMTP girişi reddedildi; uygulama şifresini kontrol edin'],
	'读取失败，请刷新页面': ['Loading failed; refresh the page', 'Yükleme başarısız; sayfayı yenileyin'],
	'号码无效、重复或超过数量上限': ['Invalid, duplicate or too many numbers', 'Geçersiz, yinelenen veya fazla sayıda numara'],
	'关键词无效、重复或超过数量上限': ['Invalid, duplicate or too many keywords', 'Geçersiz, yinelenen veya fazla sayıda anahtar kelime'],
	'请先配置当前转发渠道': ['Configure the selected forwarding channel first', 'Önce seçilen yönlendirme kanalını yapılandırın'],
	'保存短信转发设置？': ['Save SMS forwarding settings?', 'SMS yönlendirme ayarları kaydedilsin mi?'],
	'开启后只处理新收到的短信；历史短信不会补发。': ['Only newly received SMS will be processed; old messages will not be forwarded.', 'Yalnızca yeni alınan SMS’ler işlenecek; eski mesajlar yönlendirilmeyecek.'],
	'正在保存短信转发设置…': ['Saving SMS forwarding settings…', 'SMS yönlendirme ayarları kaydediliyor…'],
	'保存失败': ['Save failed', 'Kaydetme başarısız'],
	'已保存': ['Saved', 'Kaydedildi'],
	'请先保存修改再测试': ['Save changes before testing', 'Testten önce değişiklikleri kaydedin'],
	'请先开启并保存短信转发': ['Enable and save forwarding first', 'Önce yönlendirmeyi açıp kaydedin'],
	'将使用本机 SIM 向已保存号码发送，可能产生短信费用。': ['The device SIM will send to the saved numbers; SMS charges may apply.', 'Cihazın SIM kartı kayıtlı numaralara gönderecek; SMS ücreti doğabilir.'],
	'将向当前已保存渠道发送一条固定测试消息。': ['A fixed test message will be sent to the saved channel.', 'Kayıtlı kanala sabit bir test mesajı gönderilecek.'],
	'发送测试消息？': ['Send a test message?', 'Test mesajı gönderilsin mi?'],
	'测试已开始，请稍后刷新状态': ['Test started; refresh status shortly', 'Test başladı; kısa süre sonra durumu yenileyin'],
	'测试失败：': ['Test failed: ', 'Test başarısız: '],
	'未知错误': ['Unknown error', 'Bilinmeyen hata'],
	'设备管理': ['Device management', 'Cihaz yönetimi'],
	'USB 角色': ['USB role', 'USB rolü'],
	'当前角色': ['Current role', 'Geçerli rol'],
	'USB 链路速率': ['USB link speed', 'USB bağlantı hızı'],
	'链路未连接': ['Link disconnected', 'Bağlantı yok'],
	'未能确认': ['Unconfirmed', 'Doğrulanamadı'],
	'当前协商的 USB 数据链路速率，不代表实时传输速度；接入扩展坞时显示与扩展坞的链路。': ['Negotiated USB data link speed, not current throughput. With a dock, this is the link to the dock.', 'Anlaşılan USB veri bağlantı hızı; anlık aktarım hızı değildir. Çoklayıcı takılıysa çoklayıcıya olan bağlantı gösterilir.'],
	'切换 USB 角色': ['Switch USB role', 'USB rolünü değiştir'],
	'设备模式': ['Device mode', 'Cihaz modu'],
	'主机模式': ['Host mode', 'Ana makine modu'],
	'主机＋外部供电（实验）': ['Host + external power (experimental)', 'Ana makine + harici güç (deneysel)'],
	'当前内核不支持所选 USB 角色': ['The kernel does not support the selected USB role', 'Çekirdek seçilen USB rolünü desteklemiyor'],
	'关闭本机 OTG 供电，保持数据主机并尝试从扩展坞充电。不进行 PD 协商；需要扩展坞提供上游 5V。重启恢复自动模式。': ['Disable local OTG power, retain data host and try charging from the dock. No PD negotiation; the dock must supply upstream 5V. Reboot restores automatic mode.', 'Yerel OTG gücünü kapatır, veri ana makinesini korur ve dock üzerinden şarjı dener. PD görüşmesi yapılmaz; dock üst bağlantıya 5V sağlamalıdır. Yeniden başlatma otomatik moda döner.'],
	'仅用于独立供电扩展坞：本机停止向外供电，USB 管理连接会中断。不支持该接法的扩展坞可能无法枚举或充电。': ['Only for independently powered docks: local power output stops and USB management disconnects. Incompatible docks may neither enumerate nor charge.', 'Yalnızca harici güçlü docklar için: yerel güç çıkışı durur ve USB yönetimi kesilir. Uyumsuz docklar tanınmayabilir veya şarj etmeyebilir.'],
	'开机自动启用主机模式': ['Enable host mode at boot', 'Açılışta ana makine modunu etkinleştir'],
	'应用角色': ['Apply role', 'Rolü uygula'],
	'主机模式会断开本端口的 USB 网络与串口。F50 没有电池；切换后可能失去管理连接，外接 USB 网卡通常需要自供电 Hub。': ['Host mode disconnects USB networking and serial on this port. F50 has no battery; management may be lost and a USB adapter usually needs a powered hub.', 'Ana makine modu bu bağlantı noktasındaki USB ağını ve seri bağlantıyı keser. F50 bataryasızdır; yönetim bağlantısı kaybolabilir ve USB bağdaştırıcısı genellikle harici güçlü bir hub gerektirir.'],
	'USB 网络模式': ['USB network mode', 'USB ağ modu'],
	'网络协议': ['Network protocol', 'Ağ protokolü'],
	'生效期限': ['Apply duration', 'Uygulama süresi'],
	'仅下次重启': ['Next reboot only', 'Yalnızca sonraki yeniden başlatma'],
	'永久生效': ['Permanent', 'Kalıcı'],
	'启用所选协议': ['Enable selected protocol', 'Seçilen protokolü etkinleştir'],
	'保存，重启后生效': ['Save; apply after reboot', 'Kaydet; yeniden başlatınca uygula'],
	'NCM 为默认模式。Windows 不原生支持 ECM；RNDIS 会改变枚举方式。关闭“启用所选协议”时仅保存选择；选择“仅下次重启”则成功应用一次后恢复默认 NCM。': ['NCM is the default. Windows does not natively support ECM; RNDIS changes enumeration. With Enable selected protocol off, only your choice is saved. Next reboot only applies once, then returns to NCM.', 'NCM varsayılandır. Windows ECM’yi yerel olarak desteklemez; RNDIS aygıt tanımayı değiştirir. Seçilen protokolü etkinleştir kapalıysa yalnızca seçim kaydedilir. Yalnızca sonraki yeniden başlatma bir kez uygulanır, ardından NCM’ye dönülür.'],
	'主机模式下不可选择 USB 网络模式；主机开机自启会自动关闭 USB 网络开机自启。': ['USB network mode is unavailable in host mode; host auto-start also disables USB network auto-start.', 'Ana makine modunda USB ağ modu kullanılamaz; ana makine otomatik başlatma USB ağının otomatik başlatmasını da kapatır.'],
	'USB 网卡': ['USB network adapters', 'USB ağ bağdaştırıcıları'],
	'仅主机模式可用。刷新时会尝试启用发现的 USB 网卡；添加到 LAN 后将保存到网桥并重新加载网络。': ['Available only in host mode. Refresh brings discovered USB adapters up; adding to LAN saves the bridge and reloads networking.', 'Yalnızca ana makine modunda kullanılabilir. Yenileme bulunan USB bağdaştırıcılarını açar; LAN’a ekleme köprüyü kaydeder ve ağı yeniden yükler.'],
	'切换到主机模式后显示 USB 网卡。': ['Switch to host mode to see USB adapters.', 'USB bağdaştırıcılarını görmek için ana makine moduna geçin.'],
	'正在扫描 USB 网卡…': ['Scanning USB adapters…', 'USB bağdaştırıcıları taranıyor…'],
	'没有发现 USB 网卡。': ['No USB adapters found.', 'USB bağdaştırıcısı bulunamadı.'],
	'链路已连接': ['Link connected', 'Bağlantı kuruldu'],
	'链路未连接，已尝试启用': ['No link; enable attempted', 'Bağlantı yok; etkinleştirme denendi'],
	'已加入 LAN': ['Added to LAN', 'LAN’a eklendi'],
	'添加到 LAN': ['Add to LAN', 'LAN’a ekle'],
	'确认切换 USB 角色？': ['Switch USB role?', 'USB rolü değiştirilsin mi?'],
	'切换主机模式会立即断开 USB 管理连接。F50 没有电池，外设可能需要自供电；请确认有其他管理途径。': ['Host mode immediately disconnects USB management. F50 has no battery and peripherals may need external power; make sure another management path exists.', 'Ana makine modu USB yönetimini hemen keser. F50 bataryasızdır ve çevre birimleri harici güç gerektirebilir; başka bir yönetim yolu olduğundan emin olun.'],
	'切回设备模式后 USB 网络和串口会重新枚举。': ['USB networking and serial will re-enumerate in device mode.', 'Cihaz modunda USB ağı ve seri bağlantı yeniden tanınır.'],
	'正在切换 USB 角色…': ['Switching USB role…', 'USB rolü değiştiriliyor…'],
	'切换请求已接收，USB 连接可能短暂中断。': ['Switch request accepted; the USB connection may briefly disconnect.', 'Geçiş isteği alındı; USB bağlantısı kısa süreli kesilebilir.'],
	'管理连接已中断；请重新连接后确认 USB 角色。': ['Management connection lost; reconnect to confirm the USB role.', 'Yönetim bağlantısı kesildi; USB rolünü doğrulamak için yeniden bağlanın.'],
	'暂时无法确认角色；请重新连接后刷新页面。': ['Unable to confirm the role yet; reconnect and refresh the page.', 'Rol henüz doğrulanamadı; yeniden bağlanıp sayfayı yenileyin.'],
	'USB 角色已应用': ['USB role applied', 'USB rolü uygulandı'],
	'保存 USB 网络模式？': ['Save USB network mode?', 'USB ağ modu kaydedilsin mi?'],
	'网络模式将在下次重启时生效，USB 管理连接可能需要重新识别。': ['The network mode applies on the next reboot; USB management may need to reconnect.', 'Ağ modu sonraki yeniden başlatmada uygulanır; USB yönetimi yeniden bağlanabilir.'],
	'只保存选择；未启用所选协议，下次重启仍使用默认 NCM。': ['Save the selection only; with the selected protocol disabled, the next boot still uses default NCM.', 'Yalnızca seçim kaydedilir; seçilen protokol etkin değilse sonraki açılışta varsayılan NCM kullanılır.'],
	'正在保存 USB 网络设置…': ['Saving USB network settings…', 'USB ağ ayarları kaydediliyor…'],
	'设置已保存': ['Settings saved', 'Ayarlar kaydedildi'],
	'添加 USB 网卡到 LAN？': ['Add USB adapter to LAN?', 'USB bağdaştırıcısı LAN’a eklensin mi?'],
	'这会保存网桥配置并重新加载网络，现有连接可能短暂中断。': ['This saves the bridge configuration and reloads networking; existing connections may briefly drop.', 'Bu işlem köprü yapılandırmasını kaydedip ağı yeniden yükler; mevcut bağlantılar kısa süreli kesilebilir.'],
	'正在添加 USB 网卡…': ['Adding USB adapter…', 'USB bağdaştırıcısı ekleniyor…'],
	'添加失败：': ['Add failed: ', 'Ekleme başarısız: '],
	'切换失败：': ['Switch failed: ', 'Değiştirme başarısız: '],
	'保存失败：': ['Save failed: ', 'Kaydetme başarısız: '],
	'不可用': ['Unavailable', 'Kullanılamıyor'],
	'保存': ['Save', 'Kaydet'],
	'添加': ['Add', 'Ekle'],
	'USB role adapter is not executable': ['USB role adapter is not executable', 'USB rol bağdaştırıcısı çalıştırılabilir değil'],
	'USB role adapter failed': ['USB role adapter failed', 'USB rol bağdaştırıcısı başarısız'],
	'Device is the boot default; host auto-apply is the only persistent role': ['Device is the boot default; host auto-apply is the only persistent role', 'Cihaz modu açılış varsayılanıdır; yalnızca ana makine otomatik uygulaması kalıcıdır'],
	'Cannot save USB role policy': ['Cannot save USB role policy', 'USB rol ilkesi kaydedilemiyor'],
	'Cannot disable USB network boot policy': ['Cannot disable USB network boot policy', 'USB ağı açılış ilkesi kapatılamıyor'],
	'Cannot commit USB role policy': ['Cannot commit USB role policy', 'USB rol ilkesi uygulanamıyor'],
	'Cannot save USB network policy': ['Cannot save USB network policy', 'USB ağ ilkesi kaydedilemiyor'],
	'Cannot commit USB network policy': ['Cannot commit USB network policy', 'USB ağ ilkesi uygulanamıyor'],
	'Cannot create USB boot settings directory': ['Cannot create USB boot settings directory', 'USB açılış ayarları dizini oluşturulamıyor'],
	'Cannot write USB boot settings': ['Cannot write USB boot settings', 'USB açılış ayarları yazılamıyor'],
	'Cannot save USB boot settings': ['Cannot save USB boot settings', 'USB açılış ayarları kaydedilemiyor'],
	'Invalid USB role': ['Invalid USB role', 'Geçersiz USB rolü'],
	'Invalid USB network mode': ['Invalid USB network mode', 'Geçersiz USB ağ modu'],
	'Invalid USB network scope': ['Invalid USB network scope', 'Geçersiz USB ağ süresi'],
	'Invalid boot-auto value': ['Invalid boot-auto value', 'Geçersiz otomatik başlatma değeri'],
	'USB role switch is unavailable': ['USB role switch is unavailable', 'USB rol anahtarı kullanılamıyor'],
	'USB role readback did not match': ['USB role readback did not match', 'USB rolü geri okuması eşleşmedi'],
	'USB role switch was refused by platform safety checks': ['USB role switch was refused by platform safety checks', 'USB rol değişimi platform güvenlik denetimi tarafından reddedildi'],
	'USB network mode is unavailable in host role': ['USB network mode is unavailable in host role', 'Ana makine rolünde USB ağ modu kullanılamaz'],
	'Disable host boot-auto before configuring USB network': ['Disable host boot-auto before configuring USB network', 'USB ağını yapılandırmadan önce ana makine otomatik başlatmasını kapatın'],
	'USB host mode is required': ['USB host mode is required', 'USB ana makine modu gerekli'],
	'Not a USB network interface': ['Not a USB network interface', 'USB ağ arayüzü değil'],
	'LAN bridge device section was not found': ['LAN bridge device section was not found', 'LAN köprü aygıtı bölümü bulunamadı'],
	'Cannot bring USB network interface up': ['Cannot bring USB network interface up', 'USB ağ arayüzü etkinleştirilemiyor'],
	'Cannot add interface to LAN bridge': ['Cannot add interface to LAN bridge', 'Arayüz LAN köprüsüne eklenemiyor'],
	'Cannot save LAN bridge': ['Cannot save LAN bridge', 'LAN köprüsü kaydedilemiyor'],
	'Cannot attach USB interface to LAN bridge': ['Cannot attach USB interface to LAN bridge', 'USB arayüzü LAN köprüsüne bağlanamıyor'],
	'Network reload failed': ['Network reload failed', 'Ağ yeniden yüklenemedi'],
	'链路与流量': ['Link & traffic', 'Bağlantı ve trafik'],
	'下行速率': ['Download rate', 'İndirme hızı'],
	'上行速率': ['Upload rate', 'Yükleme hızı'],
	'累计接收': ['Total received', 'Toplam alınan'],
	'累计发送': ['Total sent', 'Toplam gönderilen'],
	'会话时长': ['Session duration', 'Oturum süresi'],
	'注册状态': ['Registration', 'Kayıt durumu'],
	'调制方式 下/上': ['Modulation DL/UL', 'Modülasyon İndirme/Yükleme'],
	'MCS 下/上': ['MCS DL/UL', 'MCS İndirme/Yükleme'],
	'BLER 下/上': ['BLER DL/UL', 'BLER İndirme/Yükleme'],
	'按当前 MCS 估算': ['Estimated from current MCS', 'Geçerli MCS değerinden tahmin'],
	'频宽': ['Bandwidth', 'Bant genişliği'],
	'AMBR 下/上': ['AMBR DL/UL', 'AMBR İndirme/Yükleme'],
	'无线 · 局域网 · 设备 · SIM': ['Wi-Fi · LAN · Device · SIM', 'Wi-Fi · LAN · Cihaz · SIM'],
	'CPU 占用': ['CPU usage', 'CPU kullanımı'],
	'内存': ['Memory', 'Bellek'],
	'存储': ['Storage', 'Depolama'],
	'电源': ['Power', 'Güç'],
	'信道': ['Channel', 'Kanal'],
	'加密': ['Encryption', 'Şifreleme'],
	'隐藏 SSID': ['Hidden SSID', 'Gizli SSID'],
	'国家': ['Country', 'Ülke'],
	'AP 状态': ['AP status', 'AP durumu'],
	'USB 网络': ['USB network', 'USB ağı'],
	'连接跟踪': ['Connection tracking', 'Bağlantı izleme'],
	'LAN 地址': ['LAN address', 'LAN adresi'],
	'无线客户端': ['Wi-Fi clients', 'Wi-Fi istemcileri'],
	'DHCP 租约': ['DHCP leases', 'DHCP kiraları'],
	'设备型号': ['Device model', 'Cihaz modeli'],
	'系统': ['System', 'Sistem'],
	'调制解调器': ['Modem', 'Modem'],
	'运营商': ['Carrier', 'Operatör'],
	'模组': ['Module', 'Modül'],
	'固件': ['Firmware', 'Ürün yazılımı'],
	'显示卡号信息': ['Show SIM identifiers', 'SIM kimliklerini göster'],
	'隐藏卡号信息': ['Hide SIM identifiers', 'SIM kimliklerini gizle'],
	'快捷控制': ['Quick controls', 'Hızlı denetimler'],
	'数据连接': ['Data connection', 'Veri bağlantısı'],
	'蜂窝射频': ['Cellular radio', 'Hücresel radyo'],
	'Wi-Fi 热点': ['Wi-Fi hotspot', 'Wi-Fi erişim noktası'],
	'重启调制解调器': ['Restart modem', 'Modemi yeniden başlat'],
	'重启设备': ['Restart device', 'Cihazı yeniden başlat'],
	"手动输入小区": ["Enter a cell manually", "Hücreyi elle gir"],
	"制式": ["Radio technology", "Radyo teknolojisi"],
	"频点（EARFCN / NR-ARFCN）": ["Channel number (EARFCN / NR-ARFCN)", "Kanal numarası (EARFCN / NR-ARFCN)"],
	"锁定指定小区": ["Lock specified cell", "Belirtilen hücreyi kilitle"],
	"LTE：EARFCN 0–262143，PCI 0–503；NR：NR-ARFCN 1–3279165，PCI 0–1007。": ["LTE: EARFCN 0–262143, PCI 0–503; NR: NR-ARFCN 1–3279165, PCI 0–1007.", "LTE: EARFCN 0–262143, PCI 0–503; NR: NR-ARFCN 1–3279165, PCI 0–1007."],
	"应用于当前查看的 SIM，无需小区出现在邻区列表中。请输入频点编号，不是 MHz 频率。": ["Applies to the SIM being viewed; the cell need not appear in the neighbor list. Enter the channel number, not a frequency in MHz.", "Görüntülenen SIM için uygulanır; hücrenin komşu listesinde olması gerekmez. MHz frekansı değil, kanal numarasını girin."],
	"请输入范围内的十进制频点和 PCI": ["Enter a decimal channel number and PCI within the listed ranges", "Listelenen aralıklarda ondalık kanal numarası ve PCI girin"],
	"手动锁定小区": ["Manual cell lock", "Elle hücre kilitleme"],
	"关机或重启": ["Power off or restart", "Kapat veya yeniden başlat"],
	"请选择关机或重启，执行后所有连接都会断开。": ["Choose power off or restart. All connections will be disconnected.", "Kapatmayı veya yeniden başlatmayı seçin. Tüm bağlantılar kesilecektir."],
	"关机": ["Power off", "Kapat"],
	"重启": ["Restart", "Yeniden başlat"],
	"正在关机…": ["Powering off…", "Kapatılıyor…"],
	"正在重启…": ["Restarting…", "Yeniden başlatılıyor…"],
	'切换到 Android': ['Switch to Android', 'Android’e geç'],
	'邻区': ['Neighbor cells', 'Komşu hücreler'],
	'制式/频段': ['RAT/Band', 'Teknoloji/Bant'],
	'频点': ['Frequency', 'Frekans'],
	'暂无邻区数据': ['No neighbor-cell data', 'Komşu hücre verisi yok'],
	'已锁定': ['Locked', 'Kilitli'],
	'锁定小区': ['Lock cell', 'Hücreyi kilitle'],
	'锁定': ['Lock', 'Kilitle'],
	'已运行': ['Uptime', 'Çalışma süresi'],
	'无线电已关': ['Radio off', 'Radyo kapalı'],
	'未插卡': ['No SIM card', 'SIM kart takılı değil'],
	'未驻留小区': ['No serving cell', 'Bağlı olunan hücre yok'],
	'无应答': ['No response', 'Yanıt yok'],
	'信号': ['Signal', 'Sinyal'],
	'优秀': ['Excellent', 'Mükemmel'],
	'良好': ['Good', 'İyi'],
	'一般': ['Fair', 'Orta'],
	'较差': ['Poor', 'Zayıf'],
	'未知': ['Unknown', 'Bilinmiyor'],
	'未注册': ['Not registered', 'Kayıtlı değil'],
	'已注册（漫游）': ['Registered (roaming)', 'Kayıtlı (dolaşım)'],
	'已注册': ['Registered', 'Kayıtlı'],
	'搜索中': ['Searching', 'Aranıyor'],
	'注册被拒': ['Registration denied', 'Kayıt reddedildi'],
	'仅紧急': ['Emergency only', 'Yalnızca acil arama'],
	'状态': ['Status', 'Durum'],
	'LTE 锚点': ['LTE anchor', 'LTE bağlantı noktası'],
	'LTE 链路': ['LTE link', 'LTE bağlantısı'],
	'锚点': ['Anchor', 'Bağlantı noktası'],
	'已隐藏': ['Hidden', 'Gizli'],
	'运行中': ['Running', 'Çalışıyor'],
	'未运行': ['Not running', 'Çalışmıyor'],
	'已连接': ['Connected', 'Bağlı'],
	'未连接': ['Disconnected', 'Bağlı değil'],
	'未读': ['unread', 'okunmamış'],
	' 条未读': [' unread', ' okunmamış'],
	'约半分钟': ['about 30 seconds', 'yaklaşık 30 saniye'],
	'近期 DHCP 租约': ['Recent DHCP leases', 'Son DHCP kiraları'],
	'主板': ['Board', 'Anakart'],
	'无温度读数': ['No temperature readings', 'Sıcaklık verisi yok'],
	'在线': ['Online', 'Çevrimiçi'],
	'AT 适配器不可用': ['AT adapter unavailable', 'AT bağdaştırıcısı kullanılamıyor'],
	'正在执行': ['Running', 'Çalıştırılıyor'],
	'已后台执行': ['Started in background', 'Arka planda başlatıldı'],
	'已执行': ['Done', 'Tamamlandı'],
	'失败': ['Failed', 'Başarısız'],
	'未知错误': ['Unknown error', 'Bilinmeyen hata'],
	'调用失败': ['Request failed', 'İstek başarısız'],
	'状态暂不可读，请刷新后重试': ['State unavailable; refresh and retry', 'Durum okunamıyor; yenileyip tekrar deneyin'],
	'查看卡槽已改变，请重新确认操作': ['The viewed SIM changed; confirm the operation again', 'Görüntülenen SIM değişti; işlemi yeniden onaylayın'],
	'关闭后只停止下次开机回放，已保存的网络、VoLTE 和 VoNR 设置不会被删除。': ['Turning this off only disables boot replay; saved network, VoLTE and VoNR settings are kept.', 'Kapatmak yalnızca açılışta uygulamayı durdurur; ağ, VoLTE ve VoNR ayarları korunur.'],
	'VoLTE 用于 4G 通话，VoNR 用于 5G SA 通话。设置按当前查看的 SIM 保存，并跟随“开机自动应用”。': ['VoLTE handles 4G calls and VoNR handles 5G SA calls. Settings are saved per viewed SIM and follow Apply at boot.', 'VoLTE 4G, VoNR 5G SA aramaları içindir. Ayarlar görüntülenen SIM için kaydedilir ve açılışta uygulama ayarını izler.'],
	'关闭 VoLTE 或 VoNR 不等于屏蔽全部来电和短信，传统网络业务仍可能到达。': ['Disabling VoLTE or VoNR does not block every call or SMS; traditional network services may still arrive.', 'VoLTE veya VoNR kapatıldığında tüm aramalar ve SMS engellenmez; geleneksel şebeke hizmetleri ulaşabilir.'],
	'正在断开数据连接': ['Disconnecting data', 'Veri bağlantısı kesiliyor'],
	'正在拨号': ['Connecting data', 'Veri bağlantısı kuruluyor'],
	'断开数据连接': ['Disconnect data', 'Veri bağlantısını kes'],
	'建立数据连接': ['Connect data', 'Veri bağlantısı kur'],
	'将断开蜂窝数据连接，依赖此连接的设备将无法上网。': ['Cellular data will disconnect. Devices using this connection will lose internet access.', 'Hücresel veri bağlantısı kesilecek. Bu bağlantıyı kullanan cihazlar internet erişimini kaybedecek.'],
	'将建立蜂窝数据连接，可能产生流量费用。': ['A cellular data connection will be established. Data charges may apply.', 'Hücresel veri bağlantısı kurulacak. Veri ücreti uygulanabilir.'],
	'关闭 Wi-Fi 热点': ['Turn off Wi-Fi hotspot', 'Wi-Fi erişim noktasını kapat'],
	'打开 Wi-Fi 热点': ['Turn on Wi-Fi hotspot', 'Wi-Fi erişim noktasını aç'],
	'热点客户端会断开；若正通过此热点管理设备，需要重新连接后才能继续访问。': ['Hotspot clients will disconnect. If you are managing the device through this hotspot, reconnect to regain access.', 'Erişim noktasına bağlı cihazların bağlantısı kesilecek. Cihazı bu erişim noktasından yönetiyorsanız erişmek için yeniden bağlanmanız gerekecek.'],
	'将使用已保存的配置开启 Wi-Fi 热点。': ['The Wi-Fi hotspot will start using the saved settings.', 'Wi-Fi erişim noktası kayıtlı ayarlarla açılacak.'],
	'关闭蜂窝射频': ['Turn off cellular radio', 'Hücresel radyoyu kapat'],
	'打开蜂窝射频': ['Turn on cellular radio', 'Hücresel radyoyu aç'],
	'蜂窝连接会中断': ['Cellular connectivity will be interrupted', 'Hücresel bağlantı kesilecek'],
	'将执行 SFUN 上电序列（最多约 1 分钟）': ['The SFUN power-on sequence will run (up to about 1 minute)', 'SFUN açılış sırası çalışacak (yaklaşık 1 dakikaya kadar)'],
	'蜂窝连接会中断 1-2 分钟': ['Cellular connectivity may stop for 1–2 minutes', 'Hücresel bağlantı 1–2 dakika kesilebilir'],
	'重启整个设备': ['Restart the entire device', 'Tüm cihazı yeniden başlat'],
	'所有连接会断开': ['All connections will be interrupted', 'Tüm bağlantılar kesilecek'],
	  '启动控制不可用': ['Boot control unavailable', 'Açılış kontrolü kullanılamıyor'],
 '启动控制正忙，请稍后重试': ['Boot control is busy; try again later', 'Açılış kontrolü meşgul; sonra tekrar deneyin'],
 '启动控制信息无效': ['Invalid boot control information', 'Açılış kontrol bilgisi geçersiz'],
 '启动控制回读校验失败': ['Boot control readback verification failed', 'Açılış kontrolü geri okuma doğrulaması başarısız'],
 '启动控制回退失败，请检查启动设置': ['Boot control rollback failed; check boot settings', 'Açılış kontrolü geri alma başarısız; açılış ayarlarını kontrol edin'],
 '默认启动设置失败，请重试': ['Could not save the default boot; try again', 'Varsayılan açılış kaydedilemedi; tekrar deneyin'],
'当前为临时启动 OpenWrt': ['OpenWrt was booted temporarily', 'OpenWrt geçici olarak başlatıldı'],
 '是否将 OpenWrt 设为默认启动？不会立即重启或断网。': ['Make OpenWrt the default boot? This will not reboot or interrupt networking.', 'OpenWrt varsayılan açılsın mı? Yeniden başlatma veya ağ kesintisi olmaz.'],
 '设为默认启动': ['Make default boot', 'Varsayılan başlatma yap'],
 '以后开机默认进入 OpenWrt；启动失败仍保留 Android 回退。现在不会重启。': ['Future boots will use OpenWrt, with Android fallback if startup fails. No reboot now.', 'Sonraki açılışlar OpenWrt kullanır; başarısızlıkta Android geri dönüşü korunur. Şimdi yeniden başlatılmaz.'],
 '当前启动镜像不支持设置默认启动': ['This boot image cannot set a default boot', 'Bu açılış imajı varsayılan başlatmayı ayarlayamaz'],
'切换到 Android 系统': ['Switch to Android', 'Android sistemine geç'],
	'下次启动将进入 Android 并立即重启，此管理页面与蜂窝共享都会断开': ['The next boot will enter Android and reboot now. This management page and cellular sharing will disconnect', 'Sonraki açılış Android’e geçecek ve cihaz şimdi yeniden başlayacak. Yönetim sayfası ve hücresel paylaşım kesilecek'],
	'回到 OpenWrt：在 Android 上执行 mu300-next-boot linux 后重启': ['To return to OpenWrt, run mu300-next-boot linux in Android and reboot', 'OpenWrt’ye dönmek için Android’de mu300-next-boot linux çalıştırıp yeniden başlatın'],
	'或什么都不做，连续 5 次开机未完成会自动回退': ['Or do nothing: five failed boots trigger automatic fallback', 'Ya da hiçbir şey yapmayın: beş başarısız açılışta otomatik geri dönülür'],
	'切换并重启': ['Switch and reboot', 'Geç ve yeniden başlat'],
	'正在武装 Android 引导并重启': ['Preparing Android boot and rebooting', 'Android açılışı hazırlanıyor ve yeniden başlatılıyor'],
	'协议栈会重启（SFUN），蜂窝断开约半分钟': ['The radio stack will restart (SFUN); cellular service will stop for about 30 seconds', 'Radyo yığını yeniden başlayacak (SFUN); hücresel bağlantı yaklaşık 30 saniye kesilecek'],
	'正在后台锁定': ['Locking in background', 'Arka planda kilitleniyor'],
	'已后台锁定': ['Lock started in background', 'Kilit arka planda başlatıldı'],
	'稍后自动刷新状态': ['status will refresh shortly', 'durum birazdan yenilenecek'],
	'锁定失败': ['Lock failed', 'Kilitleme başarısız'],
	'确认': ['Confirm', 'Onayla'],
	'确定': ['OK', 'Tamam'],
	'取消': ['Cancel', 'İptal'],
	'新短信': ['New SMS', 'Yeni SMS'],
	'未知号码': ['Unknown number', 'Bilinmeyen numara'],
	'中国移动': ['China Mobile', 'China Mobile'],
	'中国联通': ['China Unicom', 'China Unicom'],
	'中国电信': ['China Telecom', 'China Telecom'],
	'中国广电': ['China Broadnet', 'China Broadnet'],
	'中国铁通': ['China Tietong', 'China Tietong'],
	' 天 ': [' d ', ' gün '],
	' 小时': [' h', ' sa'],
	' 分': [' min', ' dk'],
	' 条': [' entries', ' kayıt'],
	' 台': [' clients', ' istemci'],
	' 簇': [' cluster', ' küme'],
	'共 ': ['Total ', 'Toplam '],
	'余 ': ['Free ', 'Boş '],
	'簇': ['Cluster ', 'Küme '],
	'数据漫游': ['Data roaming', 'Veri dolaşımı'],
	'使用中': ['In use', 'Kullanımda'],
	'是': ['Yes', 'Evet'],
	'否': ['No', 'Hayır'],
    '接入点 APN': ['Access points (APN)', 'Erişim noktaları (APN)'],
    '基带NV设置': ['Baseband NV settings', 'Temel bant NV ayarları'],
    '请先升级 ModemManager 以支持 APN 鉴权': ['Upgrade ModemManager first to support APN authentication', 'APN kimlik doğrulaması için önce ModemManager’ı yükseltin'],
    '无法读取当前 SIM 身份，请稍后重试': ['Cannot read the current SIM identity; try again later', 'Geçerli SIM kimliği okunamadı; daha sonra tekrar deneyin'],
    '此接入点仍被 SIM 使用，不能删除': ['This profile is still assigned to a SIM and cannot be deleted', 'Bu profil hâlâ bir SIM’e atanmış; silinemez'],
    '当前 SIM 已记住接入点，请使用按卡应用': ['This SIM has a saved profile; apply it per SIM', 'Bu SIM’in kayıtlı profili var; SIM’e özel uygulayın'],
    '无鉴权': ['No authentication', 'Kimlik doğrulama yok'],
    '用户名': ['Username', 'Kullanıcı adı'],
    '密码': ['Password', 'Parola'],
    '正在连接': ['Connecting', 'Bağlanıyor'],
    '连接失败': ['Connection failed', 'Bağlantı başarısız'],
    '鉴权方式': ['Authentication', 'Kimlik doğrulama'],
    '留空保留原密码': ['Leave empty to keep the saved password', 'Kayıtlı parolayı korumak için boş bırakın'],
    '未设置密码': ['No password set', 'Parola ayarlanmadı'],
    '清除已保存密码': ['Clear saved password', 'Kayıtlı parolayı sil'],
    '漫游 IP 协议': ['Roaming IP protocol', 'Dolaşım IP protokolü'],
    '配置初始附着 APN（高级）': ['Configure initial attach APN (advanced)', 'İlk bağlantı APN’sini yapılandır (gelişmiş)'],
    '初始附着默认关闭；仅在运营商需要时启用。不修改 IMS 配置。': ['Initial attach configuration is off by default; enable only if required by your carrier. IMS settings are not changed.', 'İlk bağlantı yapılandırması varsayılan olarak kapalıdır; yalnızca operatör gerektiriyorsa açın. IMS ayarları değiştirilmez.'],
    '按当前 SIM 记住选择': ['Remember selection for this SIM', 'Seçimi bu SIM için hatırla'],
    '使用全局接口配置': ['Using global interface settings', 'Genel arayüz ayarları kullanılıyor'],
    '自动匹配当前 SIM': ['Auto-match current SIM', 'Geçerli SIM’i otomatik eşleştir'],
    '按运营商匹配公网 APN；未知运营商使用 SIM 默认。专网或物联卡请手动设置。': ['Match a public APN by carrier; unknown carriers use the SIM default. Configure private networks and IoT SIMs manually.', 'Operatöre göre genel APN eşleştirilir; bilinmeyen operatörlerde SIM varsayılanı kullanılır. Özel ağları ve IoT SIM’leri elle yapılandırın.'],
    '当前蜂窝接口不支持 APN 管理': ['The current cellular interface does not support APN management', 'Geçerli hücresel arayüz APN yönetimini desteklemiyor'],
    '接入点参数无效': ['Invalid access point settings', 'Geçersiz erişim noktası ayarları'],
    '接入点已不存在，请刷新': ['Access point no longer exists; refresh the list', 'Erişim noktası artık mevcut değil; listeyi yenileyin'],
    '网络或 APN 配置有未应用更改，请先保存或撤销': ['Network or APN settings have pending changes; save or discard them first', 'Ağ veya APN ayarlarında bekleyen değişiklikler var; önce kaydedin veya geri alın'],
    '接入点保存失败': ['Failed to save the access point', 'Erişim noktası kaydedilemedi'],
    '最多保存 32 个接入点': ['You can save up to 32 access points', 'En fazla 32 erişim noktası kaydedebilirsiniz'],
    '相同 APN 和协议的接入点已存在': ['An access point with this APN and protocol already exists', 'Bu APN ve protokole sahip bir erişim noktası zaten var'],
    '不能删除当前接入点，请先切换': ['Switch to another access point before deleting the current one', 'Geçerli erişim noktasını silmeden önce başka birine geçin'],
    '配置已保存，但应用失败，请刷新后重试': ['Settings saved, but could not be applied; refresh and try again', 'Ayarlar kaydedildi ancak uygulanamadı; yenileyip tekrar deneyin'],
    '正在应用…': ['Applying…', 'Uygulanıyor…'],
    '接入点已应用，正在连接；能否上网取决于 SIM 和运营商': ['APN applied; connecting. Internet access depends on your SIM and carrier', 'APN uygulandı; bağlanılıyor. İnternet erişimi SIM ve operatörünüze bağlıdır'],
    '接入点已保存': ['Access point saved', 'Erişim noktası kaydedildi'],
    '留空使用 SIM 默认接入点': ['Leave empty to use the SIM default APN', 'SIM varsayılan APN değerini kullanmak için boş bırakın'],
    '接入点名称': ['Profile name', 'Profil adı'],
    'IP 协议': ['IP protocol', 'IP protokolü'],
    '编辑接入点': ['Edit access point', 'Erişim noktasını düzenle'],
    '添加接入点': ['Add access point', 'Erişim noktası ekle'],
    '保存仅修改列表，点击切换后才会应用。': ['Saving only updates the list. Switch to a profile to apply it.', 'Kaydetmek yalnızca listeyi günceller. Uygulamak için profile geçin.'],
    '当前配置': ['Current configuration', 'Geçerli yapılandırma'],
    'SIM 默认': ['SIM default', 'SIM varsayılanı'],
    '接入点应用于当前上网接口，不切换 SIM。切换会短暂中断蜂窝网络，重启后仍保留。': ['Profiles apply to the current data interface without switching SIMs. Switching briefly interrupts cellular data and persists across reboots.', 'Profiller SIM değiştirmeden geçerli veri arayüzüne uygulanır. Geçiş hücresel veriyi kısa süreli keser ve yeniden başlatmalarda korunur.'],
    '暂无接入点，请添加': ['No access points yet. Add one to get started.', 'Henüz erişim noktası yok. Başlamak için bir tane ekleyin.'],
    '再次应用': ['Apply again', 'Yeniden uygula'],
    '切换接入点？': ['Switch access point?', 'Erişim noktası değiştirilsin mi?'],
    '将重新建立蜂窝连接，USB 和 Wi-Fi 不受影响。': ['The cellular connection will be re-established. USB and Wi-Fi are unaffected.', 'Hücresel bağlantı yeniden kurulacak. USB ve Wi-Fi etkilenmez.'],
    '删除接入点？': ['Delete access point?', 'Erişim noktası silinsin mi?'],
    '当前 ModemManager 适配不支持独立漫游协议和初始附着编辑；不修改 IMS。': ['This ModemManager adapter does not support separate roaming IP or initial attach editing; IMS is unchanged.', 'Bu ModemManager bağdaştırıcısı ayrı dolaşım IP protokolünü veya ilk bağlantı düzenlemeyi desteklemiyor; IMS değişmez.'],
	'状态看板': ['Dashboard', 'Durum paneli'],
	'蜂窝': ['Cellular', 'Hücresel'],
	'网络锁定': ['Network locks', 'Ağ kilitleri'],
	'短信': ['SMS', 'SMS'],
	'AT 终端': ['AT terminal', 'AT terminali'],
	"自动网络模式编号": ["Automatic network mode code", "Otomatik şebeke modu kodu"],
	"默认": ["Default", "Varsayılan"],
	"控制各 SIM 自动模式的基带制式组合。双卡时若网络延迟很高或明显卡顿，可尝试切换 134／152；效果取决于本机基带。": ["Used by automatic network mode on each SIM. If dual-SIM service has high latency or stalls, try switching between 134 and 152; results depend on the modem firmware.", "Her SIM’in otomatik şebeke modunda kullanılır. Çift SIM ile gecikme veya takılma varsa 134 ile 152 arasında geçişi deneyin; sonuç modem yazılımına bağlıdır."],
	"保存后需在网络锁定重新应用自动模式；已开启开机自动应用的卡也会在下次启动时采用此值。显式 4G／SA／NSA 模式不变。": ["After saving, reapply automatic mode in Network Locks. SIMs with apply-at-startup enabled also use this value at the next boot. Explicit 4G/SA/NSA modes are unchanged.", "Kaydettikten sonra Şebeke Kilitleri’nde otomatik modu yeniden uygulayın. Açılışta uygulama etkin SIM’ler de sonraki açılışta bu değeri kullanır. Açıkça seçilen 4G/SA/NSA modları değişmez."],
	"短信池": ["SMS pool", "SMS havuzu"],
	'适配设置': ['Adapter settings', 'Bağdaştırıcı ayarları'],
	'主页刷新间隔（秒）': ['Home dashboard refresh interval (seconds)', 'Ana pano yenileme aralığı (saniye)'],
	'状态刷新间隔为 2–60 秒；网速独立每 1 秒刷新，保存后重新进入主页生效。': ['Status refresh interval: 2–60 seconds. Network rates refresh separately every second. Reopen Home after saving.', 'Durum yenileme aralığı: 2–60 saniye. Ağ hızları ayrı olarak her saniye yenilenir. Kaydettikten sonra Ana Sayfa’yı yeniden açın.'],
	'当前驻网': ['Serving network', 'Bağlı olunan ağ'],
	'网络模式 · EN-DC': ['Network mode · EN-DC', 'Ağ modu · EN-DC'],
	'自动（5G/4G）': ['Automatic (5G/4G)', 'Otomatik (5G/4G)'],
	'仅 4G': ['4G only', 'Yalnızca 4G'],
	'仅 5G SA': ['5G SA only', 'Yalnızca 5G SA'],
	'仅 5G NSA': ['5G NSA only', 'Yalnızca 5G NSA'],
	'自动': ['Automatic', 'Otomatik'],
	'刷新锁定状态': ['Refresh lock status', 'Kilit durumunu yenile'],
	'开机自动应用': ['Apply at startup', 'Başlangıçta uygula'],
	'开机自动应用已': ['Apply at startup is ', 'Başlangıçta uygulama '],
	'关闭后只停止下次开机回放，已保存的网络模式、EN-DC、频段和小区配置不会被删除。': ['Turning this off only stops replay at the next boot; saved network mode, EN-DC, band and cell settings remain.', 'Kapatılması yalnızca sonraki açılışta yeniden uygulamayı durdurur; kayıtlı ağ modu, EN-DC, bant ve hücre ayarları korunur.'],
	'频段锁定': ['Band locking', 'Bant kilitleme'],
	'NR 频段': ['NR bands', 'NR bantları'],
	'LTE 频段': ['LTE bands', 'LTE bantları'],
	'应用 NR 频段': ['Apply NR bands', 'NR bantlarını uygula'],
	'应用 LTE 频段': ['Apply LTE bands', 'LTE bantlarını uygula'],
	'邻区与小区锁定': ['Neighbor cells and cell locking', 'Komşu hücreler ve hücre kilidi'],
	'锁定当前服务小区': ['Lock current serving cell', 'Geçerli hizmet hücresini kilitle'],
	'解除小区锁定': ['Unlock cell', 'Hücre kilidini kaldır'],
	'已锁定小区': ['Locked cells', 'Kilitli hücreler'],
	'解锁': ['Unlock', 'Kilidi kaldır'],
	' 小区锁定': [' cell lock', ' hücre kilidi'],
	' 的小区锁定': [' cell lock', ' hücre kilidi'],
	'应用后协议栈重启（SFUN），蜂窝会短暂断开；设置会持久保存，并在启用“开机自动应用”时由插件于 AT 就绪后回放。接入平台的射频前钩子时可无重启回放。频段全不选再点应用 = 恢复自动。': ['Applying restarts the radio stack (SFUN) and briefly interrupts cellular service. Settings are saved and replayed by the plugin after AT is ready when Apply at startup is enabled. A platform pre-radio hook can replay without a restart. Apply with no bands selected to restore automatic mode.', 'Uygulama radyo yığınını (SFUN) yeniden başlatır ve hücresel bağlantıyı kısa süre keser. Ayarlar kaydedilir ve Başlangıçta uygula etkinse AT hazır olduğunda eklenti tarafından yeniden uygulanır. Platformun radyo öncesi kancasıyla yeniden başlatmadan uygulanabilir. Otomatik moda dönmek için hiçbir bant seçmeden uygulayın.'],
	'正在后台应用': ['Applying in background', 'Arka planda uygulanıyor'],
	'协议栈会重启（SFUN），约半分钟': ['The radio stack will restart (SFUN), taking about 30 seconds', 'Radyo yığını yeniden başlayacak (SFUN), yaklaşık 30 saniye sürecek'],
	'协议栈会重启（SFUN），蜂窝断开约半分钟': ['The radio stack will restart (SFUN); cellular service will stop for about 30 seconds', 'Radyo yığını yeniden başlayacak (SFUN); hücresel bağlantı yaklaşık 30 saniye kesilecek'],
	'SFUN 重启约半分钟': ['SFUN restart takes about 30 seconds', 'SFUN yeniden başlatması yaklaşık 30 saniye sürer'],
	'SFUN 重启 + 重新驻网，约半分钟': ['SFUN restart and re-registration take about 30 seconds', 'SFUN yeniden başlatması ve ağa yeniden kayıt yaklaşık 30 saniye sürer'],
	'约半分钟': ['about 30 seconds', 'yaklaşık 30 saniye'],
	'自动回读状态': ['status will be read back automatically', 'durum otomatik olarak geri okunacak'],
	'NR 频段锁定': ['NR band lock', 'NR bant kilidi'],
	'LTE 频段锁定': ['LTE band lock', 'LTE bant kilidi'],
	'选择': ['Select', 'Seç'],
	'已后台执行': ['Started in background', 'Arka planda başlatıldı'],
	'已排队：另一项锁定正在应用（SFUN 重启中），随后自动生效': ['Queued: another lock is being applied during SFUN restart; this will take effect afterward', 'Sıraya alındı: SFUN yeniden başlarken başka bir kilit uygulanıyor; ardından etkinleşecek'],
	'正在确认 EN-DC 状态': ['Confirming EN-DC status', 'EN-DC durumu doğrulanıyor'],
	'正在确认开机自动应用': ['Confirming startup setting', 'Başlangıç ayarı doğrulanıyor'],
	'正在直读调制解调器（最多几秒）': ['Reading modem directly (a few seconds at most)', 'Modem doğrudan okunuyor (en fazla birkaç saniye)'],
	'频段设置已应用，实际频段以模组回读为准': ['Band setting applied; actual bands are shown by modem readback', 'Bant ayarı uygulandı; gerçek bantlar modem geri okumasında gösterilir'],
	'设置已保存；当前模组未就绪或射频已关闭，已跳过重连': ['Settings saved; reconnect skipped because the modem is not ready or the radio is off', 'Ayarlar kaydedildi; modem hazır değil veya radyo kapalı olduğundan yeniden bağlantı atlandı'],
	'设置已应用；状态刷新暂不可用，请稍后刷新': ['Settings applied; status refresh is temporarily unavailable, please refresh later', 'Ayarlar uygulandı; durum şu anda yenilenemiyor, lütfen daha sonra yenileyin'],
	'设置已接受，但重连失败：': ['Settings accepted, but reconnect failed: ', 'Ayarlar kabul edildi ancak yeniden bağlantı başarısız: '],
	'已刷新': ['Refreshed', 'Yenilendi'],
	'刷新失败': ['Refresh failed', 'Yenileme başarısız'],
	'暂无驻网数据': ['No serving-network data', 'Bağlı olunan ağ verisi yok'],
	'NR 服务小区': ['NR serving cell', 'NR hizmet hücresi'],
	'回读超时，请点「刷新锁定状态」': ['Readback timed out; select “Refresh lock status”', 'Geri okuma zaman aşımına uğradı; “Kilit durumunu yenile”yi seçin'],
	'状态已回读': ['Status confirmed', 'Durum doğrulandı'],
	'已生效（EN-DC 不需要重启协议栈）': ['Applied (EN-DC does not require a radio-stack restart)', 'Uygulandı (EN-DC için radyo yığını yeniden başlatılmaz)'],
	'状态回读超时，点「刷新锁定状态」确认': ['Status readback timed out; use “Refresh lock status” to confirm', 'Durum geri okuması zaman aşımına uğradı; doğrulamak için “Kilit durumunu yenile”yi kullanın'],
	'已锁': ['Locked', 'Kilitli'],
	'支持': ['supported', 'destekleniyor'],
	' 个会话': [' conversations', ' görüşme'],
	' 个': [' bands', ' bant'],
	'网络模式': ['Network mode', 'Ağ modu'],
	'关闭 EN-DC': ['Disable EN-DC', 'EN-DC’yi kapat'],
	'开启 EN-DC': ['Enable EN-DC', 'EN-DC’yi aç'],
	'关闭开机自动应用': ['Disable apply at startup', 'Başlangıçta uygulamayı kapat'],
	'开启开机自动应用': ['Enable apply at startup', 'Başlangıçta uygulamayı aç'],
	'关闭': ['Disabled', 'Kapalı'],
	'开启': ['Enabled', 'Açık'],
	'已开启': [' enabled', ' etkin'],
	'已关闭': [' disabled', ' devre dışı'],
	'应用': ['Apply', 'Uygula'],
	'恢复自动': ['Restore automatic', 'Otomatiğe dön'],
	'解除': ['Unlock', 'Kilidi kaldır'],
	'正在解除': ['Unlocking', 'Kilit kaldırılıyor'],
	'解锁失败': ['Unlock failed', 'Kilit kaldırılamadı'],
	'已后台解除': ['Unlock started in background', 'Kilit kaldırma arka planda başlatıldı'],
	'重新驻网': ['re-registering', 'yeniden ağa kaydoluyor'],
	'回读状态': ['read back status', 'durumu geri oku'],
	'基础': ['Basic', 'Temel'],
	'注册/信号': ['Registration/signal', 'Kayıt/sinyal'],
	'承载': ['Bearer', 'Taşıyıcı'],
	'工程模式': ['Engineering mode', 'Mühendislik modu'],
	'AT 命令（↑↓ 翻历史，Enter 发送）': ['AT command (↑↓ history, Enter to send)', 'AT komutu (↑↓ geçmiş, göndermek için Enter)'],
	'发送': ['Send', 'Gönder'],
	'清屏': ['Clear screen', 'Ekranı temizle'],
	'就绪': ['Ready', 'Hazır'],
	'会话历史（点击复用）': ['Session history (click to reuse)', 'Oturum geçmişi (yeniden kullanmak için tıklayın)'],
	'无输出': ['No output', 'Çıktı yok'],
	'错误': ['Error', 'Hata'],
	'AT 通道正忙，命令未发出': ['AT channel busy; command not sent', 'AT kanalı meşgul; komut gönderilmedi'],
	'空': ['Empty', 'Boş'],
	'收件人：号码，如 10086 或 +86...': ['Recipient: number, e.g. 10086 or +86...', 'Alıcı: numara, ör. 10086 veya +86...'],
	'刷新': ['Refresh', 'Yenile'],
	'从 SIM 同步': ['Sync from SIM', 'SIM’den eşitle'],
	'SIM 存储': ['SIM storage', 'SIM depolama'],
	'SIM 存储已满；自动归档尚未释放空间，请检查短信服务。': ['SIM storage is full; automatic archiving has not freed space. Check the SMS service.', 'SIM depolaması dolu; otomatik arşivleme henüz yer açmadı. SMS hizmetini kontrol edin.'],
	'清空本地池': ['Clear local pool', 'Yerel havuzu temizle'],
	'加载中': ['Loading', 'Yükleniyor'],
	'选择左侧会话，或直接在下方输入号码发送。': ['Select a conversation on the left, or enter a number below to send.', 'Soldan bir görüşme seçin veya göndermek için aşağıya bir numara girin.'],
	'短信内容（Enter 发送，Shift+Enter 换行）': ['Message (Enter to send, Shift+Enter for newline)', 'Mesaj (göndermek için Enter, yeni satır için Shift+Enter)'],
	'发送走 AT+CMGS（PDU 模式）；通道忙会提示重试。删除单条：在气泡上右键（手机长按）。': ['Sending uses AT+CMGS (PDU mode); retry if the channel is busy. To delete one message, right-click its bubble (long-press on mobile).', 'Gönderme AT+CMGS (PDU modu) kullanır; kanal meşgulse yeniden deneyin. Bir mesajı silmek için balona sağ tıklayın (mobilde uzun basın).'],
	'正在后台从 SIM 同步（AT+CMGL）': ['Syncing from SIM in background (AT+CMGL)', 'SIM’den arka planda eşitleniyor (AT+CMGL)'],
	'SIM 同步已开始，几秒后自动刷新': ['SIM sync started; refreshing shortly', 'SIM eşitlemesi başladı; birazdan yenilenecek'],
	'清空本地短信池': ['Clear local SMS pool', 'Yerel SMS havuzunu temizle'],
	'只删本地文件，SIM 上的不动': ['Only local files will be deleted; messages on the SIM remain.', 'Yalnızca yerel dosyalar silinir; SIM’deki mesajlar korunur.'],
	'清空': ['Clear', 'Temizle'],
	'删除这条短信': ['Delete this SMS', 'Bu SMS’i sil'],
	'删除后不可恢复': ['Deletion cannot be undone', 'Silme işlemi geri alınamaz'],
	'仅删本地': ['Local only', 'Yalnızca yerel'],
	'本地 + SIM': ['Local + SIM', 'Yerel + SIM'],
	'删除失败': ['Delete failed', 'Silme başarısız'],
	'已删除': ['Deleted', 'Silindi'],
	'已删除（仅本地）': ['Deleted (local only)', 'Silindi (yalnızca yerel)'],
	'删除': ['Delete', 'Sil'],
	'号码和内容都要填': ['Enter both a number and a message', 'Numara ve mesaj girin'],
	'发送中': ['Sending', 'Gönderiliyor'],
	'已发送，稍后自动刷新': ['Sent; refreshing shortly', 'Gönderildi; birazdan yenilenecek'],
	'发送失败': ['Send failed', 'Gönderme başarısız'],
	'AT 通道正忙，稍后重试': ['AT channel busy; retry shortly', 'AT kanalı meşgul; birazdan yeniden deneyin'],
	'池子是空的：收到/发出的短信会出现在这里，或点「从 SIM 同步」。': ['The pool is empty. Incoming and sent messages appear here, or select “Sync from SIM”.', 'Havuz boş. Gelen ve gönderilen mesajlar burada görünür veya “SIM’den eşitle”yi seçin.'],
	'我: ': ['Me: ', 'Ben: '],
	'这里定义插件与当前紫光 OpenWrt 的边界。修改后无需改动看板、AT、锁定或短信页面。': ['Configure how this plugin connects to the current Unisoc OpenWrt platform. Changes do not require editing the dashboard, AT, locks or SMS pages.', 'Bu eklentinin mevcut Unisoc OpenWrt platformuna nasıl bağlandığını yapılandırın. Değişiklikler panel, AT, kilit veya SMS sayfalarını düzenlemeyi gerektirmez.'],
	'平台适配': ['Platform adapter', 'Platform bağdaştırıcısı'],
	'AT 后端': ['AT backend', 'AT arka ucu'],
	'自动检测': ['Auto-detect', 'Otomatik algıla'],
	'atinout + 串口': ['atinout + serial port', 'atinout + seri port'],
	'自定义适配器': ['Custom adapter', 'Özel bağdaştırıcı'],
	'AT 串口': ['AT serial port', 'AT seri portu'],
	'自定义 AT 适配器': ['Custom AT adapter', 'Özel AT bağdaştırıcısı'],
	'可执行文件依次接收超时秒数和完整 AT 命令。它必须与平台拨号程序共享串口锁。': ['The executable receives a timeout in seconds and the complete AT command, in that order. It must share the serial lock with the platform dialer.', 'Yürütülebilir dosya sırayla saniye cinsinden zaman aşımını ve tam AT komutunu alır. Seri port kilidini platform arama programıyla paylaşmalıdır.'],
	'短信适配器': ['SMS adapter', 'SMS bağdaştırıcısı'],
	'实现 list、show、send、delete、sync 子命令；留空时自动查找 mu300-sms。': ['Implement the list, show, send, delete and sync subcommands; leave blank to find mu300-sms automatically.', 'list, show, send, delete ve sync alt komutlarını uygulayın; mu300-sms otomatik bulunsun diye boş bırakın.'],
	'短信池目录': ['SMS pool directory', 'SMS havuzu dizini'],
	'蜂窝逻辑接口': ['Cellular logical interface', 'Hücresel mantıksal arabirim'],
	'蜂窝 IPv6 接口': ['Cellular IPv6 interface', 'Hücresel IPv6 arabirimi'],
	'蜂窝网卡': ['Cellular network device', 'Hücresel ağ aygıtı'],
	'留空则从 netifd 自动获取': ['Leave blank to detect from netifd', 'netifd’den otomatik algılamak için boş bırakın'],
	'LAN 网桥': ['LAN bridge', 'LAN köprüsü'],
	'Wi-Fi 网卡': ['Wi-Fi device', 'Wi-Fi aygıtı'],
	'USB 网卡': ['USB device', 'USB aygıtı'],
	'等待 AT 就绪上限（秒）': ['Maximum wait for AT readiness (seconds)', 'AT hazır olma üst bekleme süresi (saniye)'],
	'持久化状态目录': ['Persistent state directory', 'Kalıcı durum dizini'],
	'，': [', ', ', '],
	'。': ['.', '.'],
	'；': ['; ', '; '],
	'：': [': ', ': '],
	'（': ['(', '('],
	'）': [')', ')'],
	'？': ['?', '?'],
	'「': ['“', '“'],
	'」': ['”', '”']
};
DASH_I18N['铃声与通知'] = ['Ringtones & notifications', 'Zil sesleri ve bildirimler'];
Object.assign(DASH_I18N, {
  "关闭后该卡无法通话、收发短信或上网，设置会在重启后保留。": [
    "This SIM will have no calls, SMS or data. The setting persists after reboot.",
    "Bu SIM arama, SMS veya veri kullanamaz. Ayar yeniden başlatınca korunur."
  ],
  "将开启所选卡的射频，设置会在重启后保留。": [
    "Enable the selected SIM radio and keep this setting after reboot.",
    "Seçili SIM radyosunu aç ve ayarı yeniden başlatınca koru."
  ],
  "SIM 射频": [
    "SIM radios",
    "SIM radyoları"
  ],
  "射频": [
    "Radio",
    "Radyo"
  ],
  "分别控制每张卡的射频并记住设置。关闭后该卡无法通话、收发短信或上网；不会自动切换到另一张卡。": [
    "Control and remember RF for each SIM separately. When off, that SIM cannot make calls, send or receive SMS, or use data. The other SIM is not selected automatically.",
    "Her SIM radyosunu ayrı kontrol edin ve kaydedin. Kapalı SIM arama, SMS veya veri kullanamaz. Diğer SIM otomatik seçilmez."
  ],
  "设置会在重启后保留。关闭当前上网卡会中断蜂窝网络。": [
    "Saved across reboots. Turning off the data SIM disconnects cellular data.",
    "Yeniden başlatmada korunur. Veri SIM radyosunu kapatmak hücresel bağlantıyı keser."
  ],
  "开启射频": [
    "Enable radio",
    "Radyoyu aç"
  ],
  "关闭射频": [
    "Disable radio",
    "Radyoyu kapat"
  ],
  "已开启": [
    "Enabled",
    "Açık"
  ],
  "已关闭": [
    "Disabled",
    "Kapalı"
  ],
  "正在应用射频设置…": [
    "Applying radio settings…",
    "Radyo ayarları uygulanıyor…"
  ],
  "射频设置已应用并保存": [
    "Radio settings applied and saved",
    "Radyo ayarları uygulandı ve kaydedildi"
  ],
  "Enable the target SIM radio before switching": [
    "Enable the target SIM radio before switching",
    "Geçişten önce hedef SIM radyosunu açın"
  ],
  "This SIM radio is disabled by the user": [
    "This SIM radio is disabled by the user",
    "Bu SIM radyosu kullanıcı tarafından kapatılmış"
  ],
  "Invalid saved SIM radio policy": [
    "Invalid saved SIM radio policy",
    "Kaydedilmiş SIM radyo ayarları geçersiz"
  ],
  "Radio setting saved; modem command failed:": [
    "Radio setting saved; modem command failed:",
    "Radyo ayarı kaydedildi; modem komutu başarısız:"
  ],
  "Radio setting saved; RF readback not confirmed": [
    "Radio setting saved; RF readback not confirmed",
    "Radyo ayarı kaydedildi; modem durumu doğrulanamadı"
  ],
  "Radio setting saved; RF enable failed": [
    "Radio setting saved; RF enable failed",
    "Radyo ayarı kaydedildi; radyo açılamadı"
  ],
  "Radio setting saved; RF disable failed": [
    "Radio setting saved; RF disable failed",
    "Radyo ayarı kaydedildi; radyo kapatılamadı"
  ],
  "请先开启目标 SIM 的射频，再切换上网卡": [
    "Enable the target SIM radio before switching",
    "Geçişten önce hedef SIM radyosunu açın"
  ],
  "该卡射频已被用户禁用": [
    "This SIM radio is disabled by the user",
    "Bu SIM radyosu kullanıcı tarafından kapatılmış"
  ],
  "已保存的 SIM 射频设置无效": [
    "Invalid saved SIM radio policy",
    "Kaydedilmiş SIM radyo ayarları geçersiz"
  ],
  "设置已保存，但基带执行失败：": [
    "Radio setting saved; modem command failed:",
    "Radyo ayarı kaydedildi; modem komutu başarısız:"
  ],
  "设置已保存，但未能确认射频状态": [
    "Radio setting saved; RF readback not confirmed",
    "Radyo ayarı kaydedildi; modem durumu doğrulanamadı"
  ],
  "设置已保存，目标 SIM 尚未就绪": [
    "Radio setting saved; target SIM is not ready",
    "Radyo ayarı kaydedildi; hedef SIM henüz hazır değil"
  ],
  "设置已保存，但射频开启失败": [
    "Radio setting saved; RF enable failed",
    "Radyo ayarı kaydedildi; radyo açılamadı"
  ],
  "设置已保存，但射频关闭失败": [
    "Radio setting saved; RF disable failed",
    "Radyo ayarı kaydedildi; radyo kapatılamadı"
  ],
  "射频设置失败": [
    "Radio setting failed",
    "Radyo ayarı başarısız"
  ],
  "射频设置请求无效": [
    "Invalid radio request",
    "Radyo isteği geçersiz"
  ]
});

var DASH_KEYS = Object.keys(DASH_I18N).sort(function(a, b) { return b.length - a.length; });
var DASH_PATTERN = new RegExp(DASH_KEYS.map(function(k) { return k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }).join('|'), 'g');
function uiLanguage() {
	var lang = (L.env && L.env.lang) || document.documentElement.lang || navigator.language || 'en';
	if (lang === 'auto') lang = document.documentElement.lang || navigator.language || 'en';
	lang = String(lang).toLowerCase().replace('_', '-');
	return lang.indexOf('zh') === 0 ? 'zh' : lang.indexOf('tr') === 0 ? 'tr' : 'en';
}
function translate(text) {
	var lang = uiLanguage();
	text = errorText(text,lang);
	if (lang === 'zh' || text == null) return String(text == null ? '' : text);
	var column = lang === 'tr' ? 1 : 0;
	return String(text).replace(DASH_PATTERN, function(key) { return DASH_I18N[key][column]; });
}
function localize(root) {
	if (uiLanguage() === 'zh' || !root) return;
	var walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT), node;
	while ((node = walk.nextNode())) {
		if (node.parentElement && /^(SCRIPT|STYLE|TEXTAREA)$/.test(node.parentElement.tagName)) continue;
		var translated = translate(node.nodeValue);
		if (translated !== node.nodeValue) node.nodeValue = translated;
	}
	var elements = [root].concat(Array.prototype.slice.call(root.querySelectorAll('*')));
	elements.forEach(function(el) {
		[ 'title', 'placeholder', 'aria-label' ].forEach(function(attr) {
			if (el.hasAttribute && el.hasAttribute(attr)) el.setAttribute(attr, translate(el.getAttribute(attr)));
		});
	});
}
var menuObserver, menuRoot;
function localizeMenu() {
	/* Bootstrap builds #topmenu asynchronously, often after the view renders.
	 * Its parent dropdown uses href="#", so link-URL matching alone misses 蜂窝. */
	var root = document.getElementById('topmenu');
	if (!root || !root.querySelectorAll) return;
	var update = function() {
		if (uiLanguage() === 'zh') return;
		Array.prototype.forEach.call(root.querySelectorAll('a[href*="/admin/home"], a[href*="/admin/modem"]'), localize);
		Array.prototype.forEach.call(root.children, function(li) {
			var a = li.querySelector('a');
			if (a && a.textContent.trim() === '蜂窝') localize(a);
		});
	};
	if (menuRoot !== root) {
		if (menuObserver) menuObserver.disconnect();
		menuRoot = root;
		if (typeof MutationObserver !== 'undefined') {
			menuObserver = new MutationObserver(update);
			menuObserver.observe(root, { childList: true, subtree: true });
		}
	}
	update();
}

/* 大陆运营商 PLMN -> 名称；COPS 给数字格式时用它还原 */
var PLMN_CN = {
	'46000': '中国移动', '46002': '中国移动', '46004': '中国移动', '46007': '中国移动', '46008': '中国移动',
	'46001': '中国联通', '46006': '中国联通', '46009': '中国联通',
	'46003': '中国电信', '46005': '中国电信', '46011': '中国电信', '46012': '中国电信',
	'46015': '中国广电', '46020': '中国铁通'
};

function carrierName(op) {
	if (!op) return '--';
	var name = op.name || PLMN_CN[op.plmn] || op.plmn || '--';
	var key = String(name).toUpperCase().replace(/[\s_\-]/g, '');
	// Same domestic aliases as the screen; leave other carriers untouched.
	var aliases = [
		[['中国移动','中国移动通信','CHINAMOBILE','CHNMOBILE','CMCC'], '中国移动'],
		[['中国联通','CHINAUNICOM','CHNUNICOM','UNICOM','CUCC'], '中国联通'],
		[['中国电信','CHINATELECOM','CHNTELECOM','CHNCT','CHNCTLTE','CTCC'], '中国电信'],
		[['中国广电','CHINABROADNET','CHNBG','CBN','CHINABROADCASTINGNETWORK'], '中国广电']
	];
	for (var i=0;i<aliases.length;i++)
		if (aliases[i][0].indexOf(key)>=0) return translate(aliases[i][1]);
	return name;
}

/* 信号质量分级（阈值来自 ufi_tools 的 SignalQuality.kt），返回 CSS 颜色表达式 */
function qLabel(rsrp, rsrq, sinr) {
	if (rsrp == null && sinr == null && rsrq == null) return '未知';
	if (rsrp != null) {
		if (rsrp >= -90) return '优秀';
		if (rsrp >= -100) return '良好';
		if (rsrp >= -110) return '一般';
		return '较差';
	}
	if (sinr != null) {
		if (sinr >= 20) return '优秀';
		if (sinr >= 13) return '良好';
		if (sinr >= 0) return '一般';
		return '较差';
	}
	if (rsrq >= -8) return '优秀';
	if (rsrq >= -11) return '良好';
	if (rsrq >= -14) return '一般';
	return '较差';
}
function qCol(label) {
	switch (label) {
		case '优秀': return 'var(--success, #2FBF71)';
		case '良好': return 'color-mix(in oklab, var(--success, #7BC96F) 62%, var(--text, #444))';
		case '一般': return 'var(--warning, #F2B544)';
		case '较差': return 'var(--danger, #E25555)';
		default:     return 'var(--text-subtle, var(--text-light, #8A8F98))';
	}
}
/* 10 分制：RSRP 40% / RSRQ 25% / SINR 35%，锚点插值，缺项权重重分配 */
function interp(v, pts) {
	if (v == null) return null;
	for (var i = 0; i < pts.length - 1; i++)
		if (v <= pts[i][0])
			return pts[i][1] + (v - pts[i][0]) * (pts[i+1][1] - pts[i][1]) / (pts[i+1][0] - pts[i][0]);
	return pts[pts.length - 1][1];
}
function qScore(s) {
	var parts = [
		[ interp(s.rsrp, [ [ -120, 0 ], [ -110, 3.5 ], [ -100, 6.5 ], [ -90, 8.5 ], [ -80, 10 ] ]), 0.40 ],
		[ interp(s.rsrq, [ [ -20, 0 ], [ -14, 3.5 ], [ -11, 6.5 ], [ -8, 8.5 ], [ -3, 10 ] ]), 0.25 ],
		[ interp(s.sinr, [ [ -5, 0 ], [ 0, 3.5 ], [ 13, 6.5 ], [ 20, 8.5 ], [ 30, 10 ] ]), 0.35 ]
	];
	var sum = 0, w = 0;
	parts.forEach(function(p) { if (p[0] != null) { sum += p[0] * p[1]; w += p[1]; } });
	return w == 0 ? null : Math.max(0, Math.min(10, sum / w));
}

/* ---------------------------------------------------------------- 格式化 */
function esc(s) {
	return String(s == null ? '' : s).replace(/[&<>"']/g, function(c) {
		return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
	});
}
function fmtBatteryCurrent(ua) {
	if (typeof ua !== 'number' || !Number.isFinite(ua)) return '--';
	var ma = Math.round(ua / 1000);
	return (ma > 0 ? '+' : '') + ma + 'mA';
}
function fmtBatterySummary(power) {
	var p = power || {};
	var current = typeof p.ua === 'number' && Number.isFinite(p.ua) ? p.ua : null;
	var voltage = typeof p.volt === 'number' && Number.isFinite(p.volt) && p.volt > 0 ? p.volt : null;
	var amps = current == null ? null : Math.abs(current) / 1000000;
	// Net battery current determines direction even while connected to USB.
	var state = current > 0 ? '充电' : current < 0 ? '放电' :
		({ Charging: '充电', Discharging: '放电', Full: '已充满', 'Not charging': '未充电' }[p.status] || '未知');
	var watts = amps != null && voltage != null ? (amps * voltage).toFixed(1) : '--';
	var amperes = amps == null ? '--' : amps.toFixed(amps > 0 && amps < 0.01 ? 3 : 2);
	var source = p.usb === true || p.usb === 1 ? 'USB供电' :
		p.usb === false || p.usb === 0 ? '电池供电' : '供电来源未知';
	return translate(state) + (uiLanguage() === 'zh' ? '' : ' ') + watts + 'W/' + amperes + 'A·' +
		(voltage == null ? '--' : voltage.toFixed(2)) + 'V·' + translate(source);
}
function fmtBytes(b) {
	if (b == null || isNaN(b)) return '--';
	var u = [ 'B', 'KB', 'MB', 'GB', 'TB' ], i = 0;
	while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
	return (b >= 100 ? b.toFixed(0) : b.toFixed(1)) + ' ' + u[i];
}
// Traffic plans use decimal GB; keep memory/rate formatting unchanged.
function fmtTrafficBytes(b) {
	if (b == null || b === '' || !Number.isFinite(Number(b)) || Number(b) < 0) return '--';
	b = Number(b);
	var u = [ 'B', 'KB', 'MB', 'GB', 'TB' ], i = 0;
	while (b >= 1000 && i < u.length - 1) { b /= 1000; i++; }
	var value = Number(b.toFixed(i === 0 ? 0 : 2));
	if (value >= 1000 && i < u.length - 1) { value = 1; i++; }
	return value + ' ' + u[i];
}
function fmtRate(bps) {
	if (bps == null || isNaN(bps) || bps < 0) return '--';
	var u = [ 'B/s', 'KB/s', 'MB/s', 'GB/s' ], i = 0;
	while (bps >= 1024 && i < u.length - 1) { bps /= 1024; i++; }
	return (bps >= 100 ? bps.toFixed(0) : bps.toFixed(1)) + ' ' + u[i];
}
function fmtUptime(s) {
	if (s == null) return '--';
	var d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60);
	if (d > 0) return d + ' 天 ' + h + ' 小时';
	if (h > 0) return h + ' 小时 ' + m + ' 分';
	return m + ' 分';
}

/* ------------------------------------------------------------------ 样式 */
var CSS = `
/* Bootstrap exposes a different token family. Only activate this bridge when
 * Aurora's --surface token is absent, so existing Aurora styling wins intact.
 * Bootstrap's data-darkmode switch updates these aliases without a reload. */
html.mud-bootstrap-theme{--surface:var(--background-color-high);--surface-sunken:var(--background-color-low);--brand-subtle:color-mix(in srgb,var(--primary-color-high) 10%,var(--background-color-high));--hairline:var(--border-color-low);--text:var(--text-color-high);--text-muted:var(--text-color-medium);--text-subtle:var(--text-color-low);--brand:var(--primary-color-high);--success:var(--success-color-high);--warning:var(--warn-color-high);--danger:var(--error-color-high);--info:var(--primary-color-high);--on-brand:var(--on-primary-color);--hover-faint:var(--background-color-medium)}
.mud{color:var(--text,#222);font-size:.85rem;line-height:1.45}
.mud *{box-sizing:border-box}
.mud-loadline{display:flex;align-items:center;gap:7px;min-height:22px;margin:5px 0;font-size:.75rem;color:var(--text-muted,#787d85)}
.mud-loadline[hidden]{display:none}.mud-loadline.is-error{color:var(--warning,#b76d00)}
.mud-loading-spinner{flex:0 0 auto;width:12px;height:12px;border:2px solid color-mix(in srgb,currentColor 20%,transparent);border-top-color:currentColor;border-radius:50%;animation:mud-loading-spin .75s linear infinite}
@keyframes mud-loading-spin{to{transform:rotate(360deg)}}
@media(prefers-reduced-motion:reduce){.mud-loading-spinner{animation:none}}
.mud-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:10px;margin-top:6px}
.mud-card{background:var(--surface,var(--background-alt,var(--background,#fff)));border:1px solid var(--hairline,var(--border,#e3e6ea));border-radius:calc(var(--radius-base,.5rem) + .375rem);padding:14px 16px;box-shadow:var(--app-shadow-sm,0 1px 3px rgba(0,0,0,.04));transition:border-color .15s}
.mud-card:hover{border-color:color-mix(in oklab,var(--brand,var(--primary,#2f7bf6)) 30%,var(--hairline,var(--border,#e3e6ea)))}
.mud-card.mud-sim-selector{padding:0;margin-bottom:10px;overflow:hidden}
.mud-sim-toggle{display:flex;align-items:center;gap:10px;width:100%;min-height:42px;margin:0;padding:9px 12px;border:0;border-radius:inherit;background:transparent;box-shadow:none;color:inherit;font:inherit;text-align:left;cursor:pointer}
.mud .mud-sim-toggle:hover{background:transparent}
.mud-sim-toggle:focus-visible{outline:2px solid var(--brand,var(--primary,#2f7bf6));outline-offset:-3px}
.mud-sim-title{flex:1;min-width:0;font-size:.8rem;font-weight:500}
.mud-sim-current{flex-shrink:0;padding:2px 7px;border-radius:6px;background:var(--brand-subtle,rgba(128,128,128,.1));color:var(--brand,var(--primary,#2f7bf6));font-size:.72rem;font-weight:600;line-height:1.5}
.mud-sim-toggle svg{flex-shrink:0;width:16px;height:16px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round;color:var(--text-muted,#787d85);transition:transform .24s ease}
.mud-sim-selector.is-open .mud-sim-toggle svg{transform:rotate(180deg)}
.mud-sim-panel{display:grid;grid-template-rows:0fr;opacity:0;visibility:hidden;transition:grid-template-rows .24s cubic-bezier(.2,.7,.2,1),opacity .18s ease,visibility 0s .24s}
.mud-sim-selector.is-open .mud-sim-panel{grid-template-rows:1fr;opacity:1;visibility:visible;transition-delay:0s}
.mud-sim-clip{min-height:0;overflow:hidden}
.mud-sim-options{display:flex;align-items:center;flex-wrap:wrap;gap:8px 12px;padding:0 12px 12px}
.mud-sim-options select{width:auto;min-width:100px;max-width:100%;margin:0}
.mud-sim-options small{flex:1;min-width:min(100%,190px);color:var(--text-muted,#787d85);font-size:.72rem;line-height:1.5}
.mud-data-sim{display:grid;gap:7px;margin:0 0 18px;padding:12px;border:1px solid var(--hairline,var(--border-color,#ddd));border-radius:10px}
.mud-data-sim-controls{display:flex;align-items:center;flex-wrap:wrap;gap:8px 12px}
.mud-data-sim-controls label{flex:1;min-width:110px;font-weight:600;margin:0}
.mud-data-sim-controls select{width:auto;min-width:90px;max-width:100%;margin:0}
.mud-data-sim [data-result]:empty{display:none}
@media(prefers-reduced-motion:reduce){.mud-sim-panel,.mud-sim-toggle svg{transition:none}}
.mud-card>h3{margin:0 0 8px;font-size:.7rem;font-weight:600;color:var(--text-muted,var(--text-light,#787d85));letter-spacing:.08em}
.mud-card>h3::before{content:'';display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--brand,var(--primary,#2f7bf6));margin-right:7px;vertical-align:1px}
.mud-hero{display:flex;flex-wrap:wrap;gap:12px 28px;align-items:center;background:var(--brand-subtle,var(--surface,#fff));margin-bottom:12px;padding:16px 20px}
.mud-hero{position:relative}
.mud-hero-meta{display:flex;align-items:center;flex-wrap:wrap;gap:5px}
.mud-sim-hero{position:relative;display:inline-block;margin-left:7px;font-size:.74rem;line-height:1.3;z-index:10;color:var(--text,#222)}
.mud-sim-hero>.mud-sim-toggle{width:auto;min-height:0;gap:7px;white-space:nowrap;padding:4px 9px;border:1px solid var(--hairline,var(--border,#ddd));border-radius:999px;background:var(--surface,var(--background,#fff));font-weight:600}
.mud-sim-hero .mud-sim-title{display:none}
.mud-sim-hero .mud-sim-current{padding:0;border-radius:0;background:transparent;color:inherit;font-size:inherit;line-height:inherit}
.mud-sim-hero .mud-sim-toggle svg{width:12px;height:12px}
.mud-sim-hero>.mud-sim-panel{position:absolute;top:calc(100% + 8px);left:0;box-sizing:border-box;width:280px;max-width:calc(100vw - 32px);border:1px solid var(--hairline,var(--border,#ddd));border-radius:calc(var(--radius-base,.5rem) + .375rem);background:var(--surface,var(--background,#fff));box-shadow:var(--app-shadow-md,0 8px 28px rgba(0,0,0,.15))}
.mud-sim-hero .mud-sim-options{padding:14px}
@media(max-width:600px){.mud-hero-meta{padding-right:78px}.mud-sim-hero{position:absolute;right:14px;top:12px;margin:0}.mud-sim-hero>.mud-sim-panel{left:auto;right:0}}
.mud-sec{padding:2px 2px 6px}
.mud-sec>h3{margin:16px 0 10px;font-size:.7rem;font-weight:600;color:var(--text-muted,var(--text-light,#787d85));letter-spacing:.08em}
.mud-sec>h3::before{content:'';display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--brand,var(--primary,#2f7bf6));margin-right:7px;vertical-align:1px}
.mud-cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:0 28px}
.mud-client-cols{grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr));gap:16px 28px;margin-top:16px;align-items:start}
.mud-client-cols>div{min-width:0}
.mud-client-cols .mud-cli .t{flex-wrap:wrap;overflow-wrap:anywhere}
.mud-client-cols .mud-cli .s{overflow-wrap:anywhere}
.mud-body>.mud-sec+.mud-sec{border-top:1px dashed color-mix(in oklab,var(--hairline,var(--border,#ddd)) 60%,transparent);margin-top:14px;padding-top:2px}
/* 首屏骨架：卡片正常占位，只让待填字段呼吸；第一份快照到达后停止。 */
@keyframes mudpulse{0%,100%{opacity:1}50%{opacity:.35}}
.mud-booting .mud-v,.mud-booting .mud-kpi b,.mud-booting .mud-rsrp,.mud-booting .mud-rat,.mud-booting .mud-temp span{animation:mudpulse 1.1s ease-in-out infinite}
/* 紧凑键值行：键与值相邻排布（不两端对齐拉开），用于驻网参照等 */
.mud-srvline{display:flex;flex-wrap:wrap;gap:4px 10px;padding:2px 0;font-size:.84rem}
.mud-srvline .k{color:var(--text-muted,var(--text-light,#777));flex:0 0 auto}
.mud-srvline .v{font-variant-numeric:tabular-nums;font-weight:500}
.mud-charts{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px}
.mud-chart{background:transparent;border-radius:var(--radius-base,.5rem);padding:2px 4px 0}
.mud-chart .t{display:flex;align-items:baseline;gap:8px}
.mud-chart .t b{font-size:1.2rem;font-weight:700;font-variant-numeric:tabular-nums}
.mud-chart .t span{font-size:.72rem;color:var(--text-muted,var(--text-light,#777))}
.mud-chart .c{height:40px;margin-top:2px}
.mud-chart .c svg{display:block;width:100%;height:100%}
.mud-lockbtn{padding:0 10px;border-radius:99px;border:1px solid var(--hairline,var(--border,#ccc));background:var(--surface,var(--background,#fff));color:var(--text,#222);font-size:.72rem;cursor:pointer;line-height:1.7}
.mud-lockbtn.on,.mud-lockbtn:active{background:var(--brand,var(--primary,#2f7bf6));border-color:var(--brand,var(--primary,#2f7bf6));color:var(--on-brand,#fff)}
.mud-lockbtn.locked{opacity:.45;pointer-events:none;background:var(--surface-sunken,rgba(127,127,127,.1));color:var(--text-muted,var(--text-light,#888));border-color:transparent}
.mud-hero-l{flex:1 1 260px;min-width:0;display:flex;flex-direction:column;gap:5px}
.mud-hero-r{flex:0 0 auto;text-align:right;display:flex;flex-direction:column;gap:8px;align-items:flex-end}
.mud-rat{font-size:1.7rem;font-weight:700;line-height:1.1;letter-spacing:.01em}
.mud-op{color:var(--text-muted,var(--text-light,#777));font-size:.85rem}
.mud-cellline{font-size:.78rem;color:var(--text-muted,var(--text-light,#777));font-variant-numeric:tabular-nums;line-height:1.55}
.mud-rsrp{font-size:2.3rem;font-weight:700;font-variant-numeric:tabular-nums;line-height:1}
.mud-rsrp small{font-size:.9rem;font-weight:500}
.mud-chips{display:flex;gap:6px;justify-content:flex-end;flex-wrap:wrap}
.mud-imei-label{display:inline-flex;align-items:center;gap:8px;flex-wrap:wrap}
.mud-imei-active{display:inline-flex;align-items:center;padding:1px 6px;border-radius:99px;font-size:.68rem;font-weight:600;line-height:1.4;color:var(--success,#2fbf71);background:color-mix(in srgb,var(--success,#2fbf71) 14%,transparent);white-space:nowrap}
.mud-imei-active[hidden]{display:none}
.mud-tag{display:inline-block;padding:1px 8px;border-radius:99px;background:var(--surface-sunken,rgba(127,127,127,.1));font-size:.74rem;font-weight:600;font-variant-numeric:tabular-nums}
.mud-q{display:inline-block;min-width:3em;padding:1px 8px;border-radius:99px;font-size:.74rem;font-weight:600;text-align:center}
.mud-rows{display:grid;gap:2px}
.mud-r{display:flex;justify-content:space-between;gap:10px;padding:3px 0;border-bottom:1px dashed color-mix(in oklab,var(--hairline,var(--border,#ddd)) 55%,transparent)}
.mud-r:last-child{border-bottom:none}
.mud-k{color:var(--text-muted,var(--text-light,#777));flex:0 0 auto}
.mud-v{font-variant-numeric:tabular-nums;text-align:right;word-break:break-all;font-weight:500}
.mud-bars{display:inline-flex;align-items:flex-end;gap:2px;height:16px;margin-left:8px;vertical-align:baseline}
.mud-bars i{width:3px;border-radius:1px;background:var(--hairline,var(--border,#ccc))}
.mud-bars i.on{background:currentColor}
.mud-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(122px,1fr));gap:10px;margin-bottom:10px}
.mud-kpi{background:var(--surface-sunken,rgba(127,127,127,.06));border-radius:var(--radius-base,.5rem);padding:9px 12px}
.mud-kpi b{display:block;font-size:1.05rem;font-variant-numeric:tabular-nums;font-weight:700;line-height:1.25}
.mud-kpi span{font-size:.68rem;color:var(--text-muted,var(--text-light,#777))}
.mud-sub{font-size:.68rem;color:var(--text-subtle,var(--text-light,#999));font-variant-numeric:tabular-nums}
.mud-meter{height:5px;border-radius:3px;background:var(--surface-sunken,rgba(127,127,127,.15));overflow:hidden;margin:3px 0 1px}
.mud-meter i{display:block;height:100%;border-radius:3px}
.mud-freq{display:flex;align-items:center;font-size:.76rem;font-variant-numeric:tabular-nums;padding:1px 0}
.mud-freq .mud-k{flex:0 0 2.4em}
.mud-manual-cell{margin:12px 0;max-width:720px;min-width:0}
.mud-manual-cell summary{cursor:pointer;padding:8px 0;font-size:.85rem;font-weight:600}
.mud-manual-cell form{margin:4px 0 12px}
.mud-manual-cell-fields{display:flex;flex-wrap:wrap;align-items:end;gap:12px}
.mud-manual-cell-fields label{display:flex;flex:1 1 140px;flex-direction:column;gap:6px;margin:0;min-width:0;font-size:.82rem}
.mud-manual-cell-fields input,.mud-manual-cell-fields select{box-sizing:border-box;width:100%;max-width:100%;min-width:0;min-height:38px;margin:0;padding:8px 10px;border:1px solid var(--hairline,var(--border,#ccc));border-radius:var(--radius-base,.5rem);background:var(--surface,var(--background,#fff));color:var(--text,#222);font:inherit}
.mud-manual-cell-fields button{min-height:38px;margin:0;white-space:normal}
.mud-manual-cell-fields input:focus,.mud-manual-cell-fields select:focus{outline:2px solid var(--brand,var(--primary,#37a));outline-offset:1px}
.mud-btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;padding:7px 12px;border:1px solid var(--hairline,var(--border,#ccc));border-radius:var(--radius-base,.5rem);background:var(--surface,var(--background,#fff));color:var(--text,#222);font-size:.82rem;cursor:pointer;user-select:none}
.mud-btn:active{transform:scale(.97)}
.mud-voice-row{align-items:center;gap:12px;padding:8px 0}
.mud-voice-row .mud-v{flex:1;text-align:right;min-width:0;overflow-wrap:anywhere}
.mud-btn.mud-voice-switch{flex:0 0 48px;min-height:36px;padding:6px;border:0;border-radius:18px;background:transparent;color:var(--text,#222)}
.mud-voice-switch:focus-visible{outline:2px solid var(--brand,var(--primary,#2f7bf6));outline-offset:2px}
.mud-voice-track{position:relative;display:block;width:36px;height:22px;flex:0 0 36px;border-radius:12px;background:var(--muted,#777);transition:background .18s}
.mud-voice-track:after{content:"";position:absolute;left:3px;top:3px;width:16px;height:16px;border-radius:50%;background:#fff;box-shadow:0 1px 3px #0003;transition:transform .18s}
.mud-voice-switch.on .mud-voice-track{background:var(--brand,var(--primary,#2f7bf6))}
.mud-voice-switch.on .mud-voice-track:after{transform:translateX(14px)}
@media(prefers-reduced-motion:reduce){.mud-voice-track,.mud-voice-track:after{transition:none}}

.mud-btn.on:not(.mud-voice-switch){background:var(--brand,var(--primary,#2f7bf6));border-color:var(--brand,var(--primary,#2f7bf6));color:var(--on-brand,#fff)}
.mud-btn.warn{border-color:color-mix(in oklab,var(--danger,#E25555) 55%,transparent);color:var(--danger,#E25555)}
.mud-btn[disabled]{opacity:.4;pointer-events:none}
.mud-ctl{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:7px}
.mud-note{font-size:.72rem;color:var(--text-subtle,var(--text-light,#999));margin-top:7px}
.mud-table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums;font-size:.8rem}
.mud-table th{font-weight:500;color:var(--text-muted,var(--text-light,#777));text-align:right;padding:1px 4px;border-bottom:1px solid var(--hairline,var(--border,#ddd));font-size:.72rem;position:sticky;top:0;background:var(--surface,var(--background-alt,var(--background,#fff)))}
.mud-table td{text-align:right;padding:3px 6px;border-bottom:1px dashed color-mix(in oklab,var(--hairline,var(--border,#ddd)) 5%,transparent)}
.mud-table th:first-child,.mud-table td:first-child{text-align:left}
.mud-scroll{max-height:230px;overflow:auto;border:1px solid color-mix(in oklab,var(--hairline,var(--border,#ddd)) 45%,transparent);border-radius:var(--radius-base,.5rem);padding:4px}
.mud-cli{padding:4px 8px;border-radius:var(--radius-base,.5rem);border:1px solid color-mix(in oklab,var(--hairline,var(--border,#ddd)) 55%,transparent);margin-bottom:5px}
.mud-cli .t{display:flex;justify-content:space-between;gap:8px;align-items:baseline}
.mud-cli .s{font-size:.72rem;color:var(--text-muted,var(--text-light,#888));font-variant-numeric:tabular-nums;margin-top:1px}
/* ---- 聊天式短信 ---- */
.mud-chat{display:flex;gap:12px;min-height:420px}
.mud-convs{flex:0 0 240px;overflow:auto;max-height:520px}
.mud-conv{padding:7px 9px;border-radius:var(--radius-base,.5rem);cursor:pointer;margin-bottom:4px;border:1px solid transparent}
.mud-conv:hover{background:var(--hover-faint,rgba(127,127,127,.06))}
.mud-conv.sel{background:var(--brand-subtle,var(--surface-sunken,rgba(127,127,127,.08)));border-color:color-mix(in oklab,var(--brand,var(--primary,#2f7bf6)) 30%,transparent)}
.mud-conv .n{display:flex;justify-content:space-between;gap:6px;font-weight:600;font-size:.84rem}
.mud-conv .p{font-size:.74rem;color:var(--text-muted,var(--text-light,#888));white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:1px}
.mud-thread{flex:1;display:flex;flex-direction:column;min-width:0;border-left:1px solid var(--hairline,var(--border,#ddd));padding-left:12px}
.mud-msgs{flex:1;overflow:auto;max-height:460px;padding:4px 2px;display:flex;flex-direction:column;gap:6px}
.mud-bub{max-width:78%;padding:6px 11px;border-radius:calc(var(--radius-base,.5rem) + .25rem);font-size:.85rem;white-space:pre-wrap;word-break:break-word;align-self:flex-start;background:var(--surface-sunken,rgba(127,127,127,.08))}
.mud-bub.out{align-self:flex-end;background:var(--brand,var(--primary,#2f7bf6));color:var(--on-brand,#fff)}
.mud-bub .tm{display:block;font-size:.64rem;opacity:.65;margin-top:2px;text-align:right;font-variant-numeric:tabular-nums}
.mud-comp{display:flex;gap:8px;margin-top:8px}
.mud-comp input,.mud-comp textarea{padding:7px 11px;border:1px solid var(--hairline,var(--border,#ccc));border-radius:var(--radius-base,.5rem);background:var(--surface,var(--background,#fff));color:var(--text,#222);font-family:inherit}
.mud-comp input{flex:0 0 170px}
.mud-comp textarea{flex:1;resize:none;min-height:40px;max-height:120px}
@media(max-width:700px){.mud-chat{flex-direction:column}.mud-convs{flex:none;max-height:150px}.mud-thread{border-left:none;padding-left:0;border-top:1px solid var(--hairline,var(--border,#ddd));padding-top:8px}}
/* ---- 专业 AT 终端 ---- */
.mud-at-grid{display:grid;grid-template-columns:1fr 220px;gap:10px}
.mud-at-grid .mud-scroll{max-height:340px}
@media(max-width:700px){.mud-at-grid{grid-template-columns:1fr}.mud-term{height:300px}.mud-at-grid .mud-scroll{max-height:120px}}
.mud-term{font-family:var(--font-mono,monospace);font-size:.8rem;line-height:1.5;background:color-mix(in oklab,var(--surface,#14161a) 92%,var(--brand,#2f7bf6) 3%);color:var(--text,#d5d9de);border:1px solid var(--hairline,var(--border,#2a2d33));border-radius:var(--radius-base,.5rem);padding:12px;height:380px;overflow:auto;white-space:pre-wrap;word-break:break-all}
.mud-term .ln-cmd{color:var(--brand,#6ab0ff);font-weight:600}
.mud-term .ln-ok{color:var(--success,#57c98a);font-weight:600}
.mud-term .ln-err{color:var(--danger,#ff7b72);font-weight:600}
.mud-term .ln-data{color:var(--text,#d5d9de)}
.mud-term .ln-meta{color:var(--text-subtle,#7d8590);font-style:italic}
.mud-term .ln-ms{float:right;color:var(--text-subtle,#7d8590);font-size:.7rem}
.mud-dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--text-subtle,#8A8F98);margin-right:6px;vertical-align:1px}
.mud-dot.on{background:var(--success,#2FBF71)}
.mud-temp{display:inline-flex;gap:5px;flex-wrap:wrap}
.mud-temp span{padding:1px 8px;border-radius:var(--radius-base,.5rem);background:var(--surface-sunken,rgba(127,127,127,.08));font-variant-numeric:tabular-nums;font-size:.76rem}
.mud-at-in{display:flex;gap:7px;margin-bottom:7px}
.mud-at-in input{flex:1;min-width:0;padding:6px 10px;border:1px solid var(--hairline,var(--border,#ccc));border-radius:var(--radius-base,.5rem);background:var(--surface,var(--background,#fff));color:var(--text,#222);font-family:var(--font-mono,monospace)}
.mud-out{font-family:var(--font-mono,monospace);font-size:.78rem;white-space:pre-wrap;background:var(--surface-sunken,rgba(127,127,127,.07));border-radius:var(--radius-base,.5rem);padding:9px;max-height:260px;overflow:auto;margin:7px 0 0}
.mud-chiprow{display:flex;flex-wrap:wrap;gap:5px;margin-top:7px}
.mud-chip{padding:2px 9px;border-radius:99px;border:1px solid var(--hairline,var(--border,#ccc));font-size:.72rem;font-family:var(--font-mono,monospace);cursor:pointer}
.mud-chip.on{background:var(--brand,var(--primary,#2f7bf6));border-color:var(--brand,var(--primary,#2f7bf6));color:var(--on-brand,#fff)}
.mud-sms-item{padding:6px 8px;border-radius:var(--radius-base,.5rem);border:1px solid color-mix(in oklab,var(--hairline,var(--border,#ddd)) 60%,transparent);margin-bottom:6px;cursor:pointer}
.mud-sms-item:hover{background:var(--hover-faint,rgba(127,127,127,.05))}
.mud-sms-top{display:flex;justify-content:space-between;gap:8px;align-items:baseline}
.mud-badge{display:flex;align-items:center;justify-content:center;font-size:.68rem;padding:0 7px;min-width:20px;height:20px;box-sizing:border-box;border-radius:99px;background:var(--brand,var(--primary,#2f7bf6));color:var(--on-brand,#fff)}
/* 手机端 hero 与锁定页一致：信息块在上、RSRP 块自然换行到下一行（右对齐） */
@media(max-width:600px){
.mud-hero{gap:8px}
.mud-hero-l{flex:1 1 100%}
.mud-hero-r{flex:1 0 100%;flex-direction:row;justify-content:space-between;align-items:baseline;text-align:left}
.mud-rsrp{font-size:1.9rem}
.mud-chips{justify-content:flex-end}}
/* ---- 顶部 toast 与按钮忙碌态（各页共用的反馈框架） ---- */
.mud-toasts{position:fixed;top:14px;left:50%;transform:translateX(-50%);z-index:9999;display:flex;flex-direction:column;gap:8px;align-items:center;pointer-events:none;width:max-content;max-width:min(92vw,560px)}
.mud-toast{pointer-events:auto;display:flex;align-items:center;gap:9px;padding:9px 16px;border-radius:99px;background:var(--surface,var(--background,#fff));border:1px solid var(--hairline,var(--border,#ddd));box-shadow:0 6px 24px rgba(0,0,0,.14);font-size:.82rem;color:var(--text,#222);animation:mudtoast-in .22s ease-out;max-width:100%}
.mud-toast.out{animation:mudtoast-out .25s ease-in forwards}
.mud-toast .mud-tico{flex:0 0 auto;width:8px;height:8px;border-radius:50%;background:var(--brand,var(--primary,#2f7bf6))}
.mud-toast.success .mud-tico{background:var(--success,#2FBF71)}
.mud-toast.error .mud-tico{background:var(--danger,#E25555)}
.mud-toast.busy .mud-tico{width:12px;height:12px;background:transparent;border:2px solid color-mix(in oklab,var(--brand,#2f7bf6) 30%,transparent);border-top-color:var(--brand,#2f7bf6);animation:mudspin .7s linear infinite}
@keyframes mudtoast-in{from{opacity:0;transform:translateY(-12px)}to{opacity:1;transform:none}}
@keyframes mudtoast-out{to{opacity:0;transform:translateY(-8px)}}
@keyframes mudspin{to{transform:rotate(360deg)}}
.mud-toast.notify{flex-direction:row;align-items:center;max-width:340px;text-align:left;border-radius:calc(var(--radius-base,.5rem) + .375rem)}
.mud-toast.notify .mud-nb{display:flex;flex-direction:column;gap:2px;min-width:0}
.mud-toast.notify .mud-nb b{font-size:.82rem;font-weight:700}
.mud-toast.notify .mud-nb span{font-size:.76rem;color:var(--text-muted,var(--text-light,#888));overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
.mud-btn .mud-spin,.mud-lockbtn .mud-spin{flex:0 0 auto;width:12px;height:12px;border-radius:50%;border:2px solid color-mix(in oklab,currentColor 30%,transparent);border-top-color:currentColor;animation:mudspin .7s linear infinite}
.mud-btn.busy,.mud-lockbtn.busy{pointer-events:none;opacity:.75}
/* ---- 主题化对话框（替代浏览器 confirm/alert） ---- */
.mud-dlg-wrap{position:fixed;inset:0;z-index:10000;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,.42);animation:mudfade-in .16s ease-out;padding:20px}
.mud-dlg{background:var(--surface,var(--background,#fff));border:1px solid var(--hairline,var(--border,#ddd));border-radius:calc(var(--radius-base,.5rem) + .5rem);box-shadow:0 18px 50px rgba(0,0,0,.28);max-width:420px;width:100%;padding:18px 20px 16px;animation:muddlg-in .2s cubic-bezier(.2,.9,.3,1.15)}
.mud-dlg h4{margin:0 0 8px;font-size:.95rem;font-weight:700;color:var(--text,#222)}
.mud-dlg .mud-dlg-msg{font-size:.84rem;line-height:1.6;color:var(--text-muted,var(--text-light,#666));white-space:pre-wrap;word-break:break-word}
.mud-dlg .mud-dlg-btns{display:flex;gap:8px;justify-content:flex-end;margin-top:16px;flex-wrap:wrap}
/* 短信气泡的删除按钮：红色垃圾桶，平时隐淡、悬停显形；正文留出右侧空间防重叠 */
.mud-bub{position:relative;padding-right:28px}
.mud-del{position:absolute;top:2px;right:2px;display:flex;align-items:center;justify-content:center;width:24px;height:24px;padding:0;border:none;background:transparent;color:var(--danger,#E25555);opacity:.4;cursor:pointer;border-radius:50%}
.mud-del:hover{opacity:.9;background:color-mix(in oklab,var(--danger,#E25555) 12%,transparent)}
.mud-del svg{display:block}
/* 预览 -> 全文回填的过渡动画，消除首载的生硬跳变 */
@keyframes mudfadein{from{opacity:.25}to{opacity:1}}
.mud-bub .bd.fadein{animation:mudfadein .25s ease-out}
@keyframes muddlg-in{from{opacity:0;transform:scale(.94) translateY(10px)}to{opacity:1;transform:none}}
@keyframes mudfade-in{from{opacity:0}to{opacity:1}}
/* 手机端锁定页 hero：RSRP 数字左对齐（其余屏幕保持右对齐） */
@media(max-width:600px){
.mud-rsrp{text-align:left}}
`;

function injectCss() {
	localizeMenu();
	// Discard our own aliases before probing, otherwise the second LuCI page
	// would mistake this bridge for Aurora and turn it off.
	document.documentElement.classList.remove('mud-bootstrap-theme');
	var theme = getComputedStyle(document.documentElement);
	var hasAuroraTokens = theme.getPropertyValue('--surface').trim() ||
		getComputedStyle(document.body).getPropertyValue('--surface').trim();
	document.documentElement.classList.toggle('mud-bootstrap-theme',
		!hasAuroraTokens && !!theme.getPropertyValue('--background-color-high').trim());
	if (document.getElementById('mud-style')) return;
	var st = document.createElement('style');
	st.id = 'mud-style';
	st.textContent = CSS;
	document.head.appendChild(st);
}
function v(id) { return document.getElementById('mud-' + id); }
function set(id, text, color) {
	var e = v(id);
	if (!e) return;
	e.textContent = (text == null || text === '') ? '--' : text;
	if (color !== undefined) e.style.color = color;
}
function spark(el, arr, min, max, win) {
	if (!el || !arr || arr.length < 2) return;
	var w = 100, h = 34, padX = 1, padY = 3, baseY = h - padY, pts = [];
	for (var i = 0; i < arr.length; i++) {
		pts.push([ padX + i / (win - 1) * (w - 2 * padX),
			baseY - Math.max(0, Math.min(1, (arr[i] - min) / (max - min || 1))) * (h - 2 * padY) ]);
	}
	/* Catmull-Rom 转三次贝塞尔：折线变平滑曲线 */
	var d = 'M' + pts[0][0].toFixed(1) + ',' + pts[0][1].toFixed(1);
	for (var i = 0; i < pts.length - 1; i++) {
		var p0 = pts[Math.max(0, i - 1)], p1 = pts[i], p2 = pts[i + 1], p3 = pts[Math.min(pts.length - 1, i + 2)];
		// Catmull-Rom can overshoot even when every sample is inside the SVG.
		// Bound controls to their segment and leave room for the stroke itself.
		var lo = Math.min(p1[1], p2[1]), hi = Math.max(p1[1], p2[1]);
		var c1y = Math.max(lo, Math.min(hi, p1[1] + (p2[1] - p0[1]) / 6));
		var c2y = Math.max(lo, Math.min(hi, p2[1] - (p3[1] - p1[1]) / 6));
		d += 'C' + (p1[0] + (p2[0] - p0[0]) / 6).toFixed(1) + ',' + c1y.toFixed(1) +
			' ' + (p2[0] - (p3[0] - p1[0]) / 6).toFixed(1) + ',' + c2y.toFixed(1) +
			' ' + p2[0].toFixed(1) + ',' + p2[1].toFixed(1);
	}
	var last = pts.length - 1;
	var area = d + ' L' + pts[last][0].toFixed(1) + ',' + baseY + ' L' + pts[0][0].toFixed(1) + ',' + baseY + ' Z';
	var gid = 'mudg-' + (el.id || Math.floor(Math.random() * 1e6));
	el.innerHTML = '<svg viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none">' +
		'<defs><linearGradient id="' + gid + '" x1="0" y1="0" x2="0" y2="1">' +
		'<stop offset="0" stop-color="currentColor" stop-opacity=".32"/>' +
		'<stop offset="1" stop-color="currentColor" stop-opacity="0"/></linearGradient></defs>' +
		'<path d="' + area + '" fill="url(#' + gid + ')"/>' +
		'<path d="' + d + '" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" vector-effect="non-scaling-stroke"/></svg>';
}

/* 邻区表（主页与网络锁定页共用）：NR 置顶按 RSRP 排序，行尾带锁定按钮。
 * lockedCell 是 lock_get 的 cell 字段（如 "nr:627264,501"），命中行显示灰色"已锁定"。
 * 点击事件由页面用事件委托绑定（[data-lock] 属性："<rat>:<arfcn>,<pci>"）。 */
function neighborRows(c, lockedCell) {
	var nb = (c && c.neigh) || [];
	nb.sort(function(a, b) {
		if ((a.rat == 'nr') != (b.rat == 'nr')) return a.rat == 'nr' ? -1 : 1;
		return (b.rsrp || -999) - (a.rsrp || -999);
	});
	if (!nb.length)
		return '<tr><td colspan="7" style="color:var(--text-muted,var(--text-light,#777))">' + esc(translate('暂无邻区数据')) + '</td></tr>';
	var lk = Array.isArray(lockedCell) ? lockedCell.join('|') : (lockedCell || '');
	return nb.map(function(n) {
		var l = qLabel(n.rsrp, n.rsrq, n.sinr);
		var key = n.rat + ':' + n.arfcn + ',' + n.pci;
		var isLocked = lk.split('|').indexOf(key) >= 0;
		var nrBand = n.band != null && n.band !== 0 ? 'n' + esc(n.band) :
			(Array.isArray(n.band_candidates) && n.band_candidates.length ?
				n.band_candidates.map(function(b) { return 'n' + esc(b); }).join('/') : '--');
		var lteBand = n.band != null && n.band !== 0 ? 'B' + esc(n.band) : '--';
		return '<tr><td>' + (n.rat == 'nr' ? 'NR ' + nrBand : 'LTE ' + lteBand) + '</td>' +
			'<td>' + esc(n.pci != null ? n.pci : '--') + '</td>' +
			'<td>' + esc(n.arfcn != null ? n.arfcn : '--') + '</td>' +
			'<td style="color:' + qCol(l) + '">' + (n.rsrp != null ? n.rsrp.toFixed(1) : '--') + '</td>' +
			'<td>' + (n.rsrq != null ? n.rsrq.toFixed(1) : '--') + '</td>' +
			'<td>' + (n.sinr != null ? n.sinr.toFixed(1) : '--') + '</td>' +
			'<td><button class="mud-lockbtn' + (isLocked ? ' locked' : '') + '" data-lock="' + key + '"' +
			(isLocked ? ' disabled' : '') + '>' + esc(translate(isLocked ? '已锁定' : '锁定')) + '</button></td></tr>';
	}).join('');
}

/* ------------------------------------------------------------------ 反馈框架
 * M.toast(text, {type, timeout})：顶部弹出的统一提示，type = info|success|error|busy
 * （busy 自带转圈点，适合“正在…”进行态）。返回句柄 {update(text,type), close()}，
 * 长操作可以一路 update 下去而不堆叠。timeout=0 表示不自动消失。
 * M.busy(btn[, on])：给按钮加/去内嵌转圈并禁点；不传 on 则翻转。 */
function toast(text, opts) {
	opts = opts || {};
	if (!document.getElementById('mud-toasts')) {
		var w = document.createElement('div');
		w.id = 'mud-toasts';
		w.className = 'mud-toasts';
		document.body.appendChild(w);
	}
	var t = document.createElement('div');
	t.className = 'mud-toast ' + (opts.type || 'info');
	t.innerHTML = '<i class="mud-tico"></i><span></span>';
	t.lastChild.textContent = translate(text);
	document.getElementById('mud-toasts').appendChild(t);
	var timer = null, dead = false;
	var life = opts.timeout !== undefined ? opts.timeout : 3500;
	var arm = function() {
		if (timer) clearTimeout(timer);
		if (life > 0) timer = setTimeout(close, life);
	};
	var close = function() {
		if (dead) return;
		dead = true;
		if (timer) clearTimeout(timer);
		t.classList.add('out');
		setTimeout(function() { t.remove(); }, 260);
	};
	arm();
	return {
		update: function(text2, type2) {
			if (dead) return;
			t.lastChild.textContent = translate(text2);
			if (type2) t.className = 'mud-toast ' + type2;
			arm();
		},
		close: close
	};
}
function busy(btn, on) {
	if (!btn || !btn.classList) return;
	if (on === undefined) on = !btn.classList.contains('busy');
	if (on && !btn.classList.contains('busy')) {
		btn.classList.add('busy');
		var s = document.createElement('i');
		s.className = 'mud-spin';
		btn.insertBefore(s, btn.firstChild);
	} else if (!on) {
		btn.classList.remove('busy');
		btn.querySelectorAll('.mud-spin').forEach(function(sp) { sp.remove(); });
	}
}

/* ------------------------------------------------------------------ 对话框
 * M.confirmBox(title, message, opts) -> Promise<boolean>：主题化确认框，
 * 取消/遮罩/Escape 都 resolve(false)，确定/Enter resolve(true)。
 * M.alertBox(title, message, opts) -> Promise<true>：单按钮提示框。
 * opts: { danger:true 红色确认键, okText, cancelText, content: DOM Node }；danger 时默认焦点在取消上。 */
function dialog(opts) {
	opts = opts || {};
	return new Promise(function(resolve) {
		var wrap = document.createElement('div');
		wrap.className = 'mud-dlg-wrap';
		var withCancel = opts.cancelText !== null;
		wrap.innerHTML = '<div class="mud-dlg" role="dialog" aria-modal="true">' +
			'<h4></h4><div class="mud-dlg-msg"></div><div class="mud-dlg-btns">' +
			(withCancel ? '<button type="button" class="mud-btn" data-r="0"></button>' : '') +
			'<button type="button" class="mud-btn' + (opts.danger ? ' warn' : '') + '" data-r="1"></button>' +
			'</div></div>';
		wrap.querySelector('h4').textContent = translate(opts.title || '确认');
		wrap.querySelector('.mud-dlg-msg').textContent = translate(opts.message || '');
		if (opts.content instanceof Node) wrap.querySelector('.mud-dlg-msg').appendChild(opts.content);
		var btns = wrap.querySelectorAll('.mud-dlg-btns .mud-btn');
		btns[btns.length - 1].textContent = translate(opts.okText || '确定');
		if (withCancel) btns[0].textContent = translate(opts.cancelText || '取消');
		var done = function(r) {
			document.removeEventListener('keydown', onKey, true);
			wrap.remove();
			resolve(r);
		};
		var onKey = function(ev) {
			if (ev.key == 'Escape') { ev.preventDefault(); done(withCancel ? false : true); }
			else if (ev.key == 'Enter') { ev.preventDefault(); done(true); }
		};
		wrap.addEventListener('click', function(ev) {
			var b = ev.target.closest('.mud-dlg-btns button[data-r]');
			if (b) done(b.getAttribute('data-r') == '1');
			else if (ev.target === wrap && withCancel) done(false);
		});
		document.addEventListener('keydown', onKey, true);
		document.body.appendChild(wrap);
		/* 危险操作默认焦点给取消，防手滑回车 */
		(withCancel && opts.danger ? btns[0] : btns[btns.length - 1]).focus();
	});
}
/* 手机通知样式的横幅：标题（发件人）+ 两行预览，默认 6 s */
function notify(title, message, opts) {
	opts = opts || {};
	if (!document.getElementById('mud-toasts')) {
		var w = document.createElement('div');
		w.id = 'mud-toasts';
		w.className = 'mud-toasts';
		document.body.appendChild(w);
	}
	var t = document.createElement('div');
	t.className = 'mud-toast notify ' + (opts.type || 'info');
	t.innerHTML = '<i class="mud-tico"></i><div class="mud-nb"><b></b><span></span></div>';
	t.querySelector('b').textContent = translate(title);
	t.querySelector('span').textContent = message == null ? '' : String(message);
	document.getElementById('mud-toasts').appendChild(t);
	var life = opts.timeout !== undefined ? opts.timeout : 6000;
	var timer = life > 0 ? setTimeout(function() {
		t.classList.add('out');
		setTimeout(function() { t.remove(); }, 260);
	}, life) : null;
	t.addEventListener('click', function() {
		if (timer) clearTimeout(timer);
		t.remove();
	});
	return t;
}

/* One metadata check per five seconds; only read a changed shared inbox.
 * Keep both SIMs, the silent initial baseline and incoming-only notifications. */
var callSmsHead = rpc.declare({ object:'e5status', method:'sms_head', nobatch:true, expect:{'':{}} });
var smsWatch = null;
function watchSms() {
    if (smsWatch) return;
    smsWatch = { seen:null, signature:null, busy:false };
    window.setInterval(function() {
        if (document.hidden || smsWatch.busy) return;
        smsWatch.busy = true;
        Promise.resolve().then(function() { return callSmsHead(); }).then(function(head) {
            if (!head || typeof head.signature !== 'string' || head.error) throw new Error('SMS metadata unavailable');
            if (head.signature === smsWatch.signature) return;
            return callSmsList(1).then(function(r) {
                if (!r || !Array.isArray(r.msgs) || r.error) throw new Error('SMS list unavailable');
                var msgs=r.msgs, max=0;
                msgs.forEach(function(m) { max=Math.max(max,parseInt(m.id,10)||0); });
                if (smsWatch.seen != null && max >= smsWatch.seen) {
                    msgs.forEach(function(m) {
                        var id=parseInt(m.id,10)||0;
                        if(id>smsWatch.seen && m.dir==='mt')
                            notify('新短信 · '+(m.peer || '未知号码'),m.preview || '',{type:'success'});
                    });
                }
                smsWatch.seen=max;
                // A failed list must not consume a signature: retry next tick.
                smsWatch.signature=head.signature;
            });
        }).catch(function() {}).then(function() { smsWatch.busy=false; });
    },5000);
}

function confirmBox(title, message, opts) {
	opts = opts || {};
	opts.title = title;
	opts.message = message;
	return dialog(opts);
}
function alertBox(title, message, opts) {
	opts = opts || {};
	opts.title = title;
	opts.message = message;
	opts.cancelText = null;
	return dialog(opts);
}

/* 多选对话框：M.choiceBox(title, message, [{label, value, danger}], opts)
 * -> Promise(选中项的 value)；取消/遮罩/Escape resolve(undefined)。
 * choices 里的按钮从左到右排，danger 项红色。 */
function choiceBox(title, message, choices, opts) {
	opts = opts || {};
	return new Promise(function(resolve) {
		var wrap = document.createElement('div');
		wrap.className = 'mud-dlg-wrap';
		var btns = (choices || []).map(function(c, i) {
			return '<button type="button" class="mud-btn' + (c.danger ? ' warn' : '') +
				'" data-i="' + i + '"></button>';
		}).join('');
		wrap.innerHTML = '<div class="mud-dlg" role="dialog" aria-modal="true">' +
			'<h4></h4><div class="mud-dlg-msg"></div>' +
			'<div class="mud-dlg-btns">' + btns + '</div></div>';
		wrap.querySelector('h4').textContent = translate(title || '选择');
		wrap.querySelector('.mud-dlg-msg').textContent = translate(message || '');
		(choices || []).forEach(function(c, i) {
			wrap.querySelector('[data-i="' + i + '"]').textContent = translate(c.label || '?');
		});
		var done = function(v) {
			document.removeEventListener('keydown', onKey, true);
			wrap.remove();
			resolve(v);
		};
		var onKey = function(ev) {
			if (ev.key == 'Escape') { ev.preventDefault(); done(undefined); }
		};
		wrap.addEventListener('click', function(ev) {
			var b = ev.target.closest('button');
			if (b) done(choices[parseInt(b.getAttribute('data-i'), 10)].value);
			else if (ev.target === wrap) done(undefined);
		});
		document.addEventListener('keydown', onKey, true);
		document.body.appendChild(wrap);
		var first = wrap.querySelector('.mud-dlg-btns .mud-btn');
		if (first) first.focus();
	});
}

/* LuCI 的 require 把模块当类工厂：必须返回 baseclass 派生的类，加载后拿到的是它的实例 */
return baseclass.extend({
	simSlot: simSlot, simSelector: simSelector, followDataSim: followDataSim,
	callSimGet: callSimGet, callSimSet: callSimSet, callSimStatus: callSimStatus,
	callStatus: callStatus, callRates: callRates, callCells: callCells, callSignal: callSignal, callSysinfo: callSysinfo, callAct: callAct, callAt: callAt, callAtHist: callAtHist,
	callLockGet: callLockGet, callLockFresh: callLockFresh, callLockSet: callLockSet, callLockStatus: callLockStatus, waitLockJob: waitLockJob,
	callSmsList: callSmsList, callSmsShow: callSmsShow, callSmsSend: callSmsSend,
	callSmsDel: callSmsDel, callSmsSync: callSmsSync,
	callForwardGet: callForwardGet, callForwardStatus: callForwardStatus,
	callForwardSet: callForwardSet, callForwardTest: callForwardTest, callForwardClear: callForwardClear,
	callTrafficGet: callTrafficGet, callTrafficSet: callTrafficSet, callTrafficClear: callTrafficClear,
	callTtlGet: callTtlGet, callTtlSet: callTtlSet, callUsbGet: callUsbGet, callUsbSet: callUsbSet,
	callUsbNetList: callUsbNetList, callUsbNetAdd: callUsbNetAdd,
	carrierName: carrierName, qLabel: qLabel, qCol: qCol, qScore: qScore,
	esc: esc, fmtBatteryCurrent: fmtBatteryCurrent, fmtBatterySummary: fmtBatterySummary, fmtBytes: fmtBytes, fmtTrafficBytes: fmtTrafficBytes, fmtRate: fmtRate, fmtUptime: fmtUptime, PLMN_CN: PLMN_CN,
	uiLanguage: uiLanguage, translate: translate, localize: localize, localizeMenu: localizeMenu,
	injectCss: injectCss, v: v, set: set, spark: spark, neighborRows: neighborRows,
	toast: toast, busy: busy, confirmBox: confirmBox, alertBox: alertBox, choiceBox: choiceBox,
	notify: notify, watchSms: watchSms
});
