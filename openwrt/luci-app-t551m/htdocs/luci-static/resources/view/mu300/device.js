'use strict';
'require view';
'require mu300.common as M';
'require mu300.network-performance as NetworkPerformance';

return view.extend({
	load: function() { return L.resolveDefault(M.callUsbGet(), {}); },
	render: function(state) {
		M.injectCss();
		M.localizeMenu();
		var root = document.createElement('div');
		root.className = 'mud';
		root.innerHTML = `
<style>
.mud-device-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
.mud-device-field{display:flex;flex-direction:column;gap:7px;margin:12px 0}
.mud-device-field label{font-size:.8rem;color:var(--text-muted,var(--text-light,#777))}
.mud-device-field select{width:100%;min-height:38px;border:1px solid var(--hairline,var(--border,#ccc));border-radius:var(--radius-base,.5rem);padding:6px 10px;background:var(--surface,var(--background,#fff));color:var(--text,#222)}
.mud-device-toggle{display:flex;align-items:center;gap:9px;font-size:.82rem;line-height:1.45;cursor:pointer}
.mud-device-toggle input{accent-color:var(--brand,var(--primary,#2f7bf6))}
.mud-device-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}
.mud-device-head{display:flex;align-items:center;justify-content:space-between;gap:10px}
.mud-device-head h3{margin:0;font-size:.85rem}
.mud-device-list{display:grid;gap:8px;margin-top:12px}
.mud-device-item{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:11px 12px;border:1px solid var(--hairline,var(--border,#ddd));border-radius:var(--radius-base,.5rem)}
.mud-device-item-main{min-width:0;display:flex;align-items:center;gap:10px}
.mud-device-dot{width:9px;height:9px;border-radius:50%;background:var(--text-muted,#888);flex:none}
.mud-device-dot.up{background:var(--success,#2fbf71)}
.mud-device-item-name{font-weight:650;overflow-wrap:anywhere}
.mud-device-item-sub{font-size:.72rem;color:var(--text-muted,var(--text-light,#777))}
@media(max-width:720px){.mud-device-grid{grid-template-columns:1fr}.mud-device-item{align-items:flex-start}.mud-device-item .mud-btn{white-space:nowrap}}
</style>
<div class="mud-device-grid">
 <section class="mud-card">
  <h3>USB 角色</h3>
  <div class="mud-r"><span class="mud-k">当前角色</span><span class="mud-v" id="mud-usb-role-now">--</span></div>
  <div class="mud-r"><span class="mud-k">USB 链路速率</span><span class="mud-v" id="mud-usb-link-speed">--</span></div>
  <div class="mud-device-field"><label for="mud-usb-role">切换 USB 角色</label>
   <select id="mud-usb-role"><option value="auto">自动识别（默认）</option><option value="device">设备模式</option><option value="host">主机模式</option></select></div>
  <label class="mud-device-toggle"><input type="checkbox" id="mud-usb-role-auto">开机自动启用主机模式</label>
  <div class="mud-device-actions"><button class="mud-btn" id="mud-usb-role-apply">应用角色</button></div>
  <div class="mud-note" id="mud-usb-role-note">自动模式根据连接设备选择充电或 OTG；手动主机模式会断开本端口的 USB 网络与串口。未勾选开机自动启用时，重启恢复自动模式。</div>
 </section>
 <section class="mud-card" id="mud-usb-net-card">
  <h3>USB 网络模式</h3>
  <div class="mud-r"><span class="mud-k">当前协议</span><span class="mud-v" id="mud-usb-net-current">--</span></div>
  <div class="mud-device-field"><label for="mud-usb-net-mode">网络协议</label>
   <select id="mud-usb-net-mode"><option value="ncm">NCM</option><option value="ecm">ECM</option><option value="rndis">RNDIS</option></select></div>
  <div class="mud-device-field"><label for="mud-usb-net-scope">生效期限</label>
   <select id="mud-usb-net-scope"><option value="once">仅下次重启</option><option value="permanent">永久生效</option></select></div>
  <label class="mud-device-toggle"><input type="checkbox" id="mud-usb-net-auto">启用所选协议</label>
  <div class="mud-device-actions"><button class="mud-btn" id="mud-usb-net-apply">保存，重启后生效</button></div>
  <div class="mud-note" id="mud-usb-net-note">NCM 为默认模式。Windows 不原生支持 ECM；RNDIS 会改变枚举方式。关闭“启用所选协议”时仅保存选择；选择“仅下次重启”则成功应用一次后恢复默认 NCM。</div>
 </section>
</div>
<section class="mud-card" style="margin-top:14px" id="mud-usb-adapters-card">
 <div class="mud-device-head"><h3>USB 网卡</h3><button class="mud-btn" id="mud-usb-refresh">刷新</button></div>
 <label class="mud-device-toggle" style="margin-top:12px"><input type="checkbox" id="mud-usb-lan-auto">新接入的 USB 网卡自动加入 LAN</label>
 <div class="mud-note">已加入 LAN 的网卡会在重新插入后自动连接。已分配给其他网络的网卡保留原配置；关闭自动加入不会移除已保存的 LAN 端口。</div>
 <div class="mud-device-list" id="mud-usb-adapters"></div>
</section>`;
		M.localize(root);
		this.root = root;
		this.state = state || {};
		this.wire();
		this.paint();
		this._networkPerformance = NetworkPerformance.mount(root);
		return root;
	},
	unload: function() { if (this._networkPerformance) this._networkPerformance.dispose(); },
	q: function(id) { return this.root.querySelector('#mud-usb-' + id); },
	paint: function() {
		var s = this.state || {};
		this.q('role-now').textContent = M.translate(s.role === 'host' ? '主机模式' : s.role === 'device' ? '设备模式' : '未连接');
		var link = s.usb_link || {}, rates = [];
		(link.links || []).forEach(function(l) {
			var n = Number(l.mbps), label = isFinite(n) && n > 0 ? (n >= 1000 ? n / 1000 + ' Gbit/s' : n + ' Mbit/s') : l.speed === 'super-speed-plus' ? 'SuperSpeedPlus' : '';
			if (label && rates.indexOf(label) < 0) rates.push(label);
		});
		this.q('link-speed').textContent = link.state === 'connected' && rates.length ? rates.join(' · ') : M.translate(link.state === 'disconnected' ? '链路未连接' : '未能确认');
		this.q('link-speed').title = M.translate('当前协商的 USB 数据链路速率，不代表实时传输速度；接入扩展坞时显示与扩展坞的链路。');
		this.q('role').querySelector('option[value="host"]').disabled = s.host_supported === 0;
		var external = this.q('role').querySelector('option[value="host-sink"]');
		if (s.role_supported?.includes('host-sink') && !external) {
			external = document.createElement('option'); external.value = 'host-sink';
			external.textContent = M.translate('主机＋外部供电（实验）'); this.q('role').appendChild(external);
		} else if (!s.role_supported?.includes('host-sink') && external) external.remove();
		this.q('role').value = s.policy || 'auto';
		this.q('role-auto').checked = !!s.role_auto;
		this.q('lan-auto').checked = !!s.lan_auto;
		this.q('role-note').textContent = M.translate(s.last_error || (s.host_supported === 0 ? '当前内核支持自动识别，但未提供手动角色切换接口。' : '自动模式根据连接设备选择充电或 OTG；手动主机模式会断开本端口的 USB 网络与串口。未勾选开机自动启用时，重启恢复自动模式。'));
		this.q('net-mode').value = s.net_mode || 'ncm';
		this.q('net-scope').value = s.net_scope || 'permanent';
		this.q('net-auto').checked = !!s.net_auto;
		this.q('net-current').textContent = (s.net_current || 'ncm').toUpperCase();
		this.q('net-mode').querySelectorAll('option').forEach(function(option) {
			option.disabled = Array.isArray(s.net_supported) && s.net_supported.indexOf(option.value) < 0;
		});
		this.updateDisabled();
		this.refreshAdapters();
	},
	updateDisabled: function() {
		var host = this.state.role === 'host', hostAuto = this.q('role-auto').checked && this.q('role').value === 'host';
		this.q('role-auto').disabled = this.q('role').value !== 'host';
		if (this.q('role').value !== 'host') this.q('role-auto').checked = false;
		this.q('role-note').textContent = M.translate(this.state.last_error || (this.q('role').value === 'host-sink' ? '关闭本机 OTG 供电，保持数据主机并尝试从扩展坞充电。不进行 PD 协商；需要扩展坞提供上游 5V。重启恢复自动模式。' : this.state.host_supported === 0 ? '当前内核支持自动识别，但未提供手动角色切换接口。' : '自动模式根据连接设备选择充电或 OTG；手动主机模式会断开本端口的 USB 网络与串口。未勾选开机自动启用时，重启恢复自动模式。'));
		this.q('role-apply').disabled = this.state.host_supported === 0;
		var locked = this.state.net_available === 0;
		[ 'net-mode', 'net-scope', 'net-auto', 'net-apply' ].forEach(function(id) { this.q(id).disabled = locked; }, this);
		this.q('net-note').textContent = M.translate(this.state.net_boot?.error || (locked ? '当前内核尚未支持协议切换，请先更新内核。' : '下次重启生效，当前连接不会中断。NCM 为默认模式；ECM 主要用于 Linux/macOS。选择“仅下次重启”则应用一次后恢复 NCM。主机模式不使用共享协议，切回设备模式时使用。'));
		this.q('refresh').disabled = false;
	},
	wire: function() {
		var self = this;
		this.q('role').addEventListener('change', function() { self.updateDisabled(); });
		this.q('role-auto').addEventListener('change', function() { self.updateDisabled(); });
		this.q('net-mode').addEventListener('change', function() { self.q('net-auto').checked = true; });
		this.q('net-scope').addEventListener('change', function() { self.q('net-auto').checked = true; });
		this.q('role-apply').addEventListener('click', function() {
			var role = self.q('role').value, auto = self.q('role-auto').checked ? '1' : '0';
			var warning = role === 'host-sink' ? '仅用于独立供电扩展坞：本机停止向外供电，USB 管理连接会中断。不支持该接法的扩展坞可能无法枚举或充电。' : role === 'host' ? '切换主机模式会断开本端口的 USB 管理连接，请通过 Wi-Fi 管理。插入 OTG 外设后才会开启供电。' : role === 'auto' ? '恢复自动识别充电器、电脑和 OTG 外设，当前 USB 连接可能重新枚举。' : '切回设备模式后 USB 网络和串口会重新枚举。';
			M.confirmBox('确认切换 USB 角色？', warning, { danger: role === 'host', okText: '应用' }).then(function(yes) {
				if (!yes) return;
				var btn = self.q('role-apply'); M.busy(btn, true);
				var msg = M.toast('正在切换 USB 角色…', { type: 'busy', timeout: 0 });
				M.callUsbSet('role', role, '', auto).then(function(r) {
					M.busy(btn, false);
					if (!r || r.ok !== 1) {
						msg.update(r && r.ok === 0 ? '切换失败：' + (r.error || '未知错误') : '管理连接已中断；请重新连接后确认 USB 角色。', r && r.ok === 0 ? 'error' : 'info');
						setTimeout(function() { msg.close(); }, 6000);
						return;
					}
					if (r.pending) {
						msg.update('切换请求已接收，USB 连接可能短暂中断。', 'info');
						self.watchRole(role, msg, 0);
					} else {
						msg.update('USB 角色已应用', 'success'); setTimeout(function() { msg.close(); }, 2500);
						self.reloadState();
					}
				}, function() {
					M.busy(btn, false);
					msg.update('管理连接已中断；请重新连接后确认 USB 角色。', 'info');
					setTimeout(function() { msg.close(); }, 6000);
				});
			});
		});
		this.q('net-apply').addEventListener('click', function() {
			var mode = self.q('net-mode').value, scope = self.q('net-scope').value, auto = self.q('net-auto').checked ? '1' : '0';
			M.confirmBox('保存 USB 网络模式？', auto === '1' ? '网络模式将在下次重启时生效，USB 管理连接可能需要重新识别。' : '只保存选择；未启用所选协议，下次重启仍使用默认 NCM。', { okText: '保存' }).then(function(yes) {
				if (!yes) return;
				var btn = self.q('net-apply'); M.busy(btn, true);
				var msg = M.toast('正在保存 USB 网络设置…', { type: 'busy', timeout: 0 });
				L.resolveDefault(M.callUsbSet('net', mode, scope, auto), {}).then(function(r) {
					M.busy(btn, false); msg.update(r.ok ? '设置已保存' : '保存失败：' + (r.error || '未知错误'), r.ok ? 'success' : 'error');
					setTimeout(function() { msg.close(); }, 3500);
					if (r.ok) self.reloadState();
				});
			});
		});
		this.q('refresh').addEventListener('click', function() { self.reloadState(); });
		this.q('lan-auto').addEventListener('change', function() {
			var input = self.q('lan-auto'), value = input.checked ? '1' : '0'; input.disabled = true;
			L.resolveDefault(M.callUsbSet('lan', value, '', ''), {}).then(function(r) {
				input.disabled = false;
				M.toast(r.ok ? '自动加入 LAN 设置已保存' : '保存失败：' + (r.error || '连接中断'), { type: r.ok ? 'success' : 'error' });
				self.reloadState();
			});
		});
	},
	reloadState: function() {
		var self = this;
		L.resolveDefault(M.callUsbGet(), {}).then(function(s) { if (s.ok) { self.state = s; self.paint(); } });
	},
	watchRole: function(role, msg, attempt) {
		var self = this;
		setTimeout(function() {
			M.callUsbGet().then(function(s) {
				if (s && s.ok && !s.pending && s.last_error) {
					msg.update('切换失败：' + s.last_error, 'error');
					setTimeout(function() { msg.close(); }, 6000);
					self.state = s; self.paint(); return;
				}
				if (s && s.ok && !s.pending && s.policy === role) {
					msg.update('USB 角色已应用', 'success');
					setTimeout(function() { msg.close(); }, 2500);
					self.state = s; self.paint();
					return;
				}
				self.finishRoleWatch(role, msg, attempt);
			}, function() { self.finishRoleWatch(role, msg, attempt); });
		}, attempt ? 1000 : 350);
	},
	finishRoleWatch: function(role, msg, attempt) {
		if (attempt < 4) { this.watchRole(role, msg, attempt + 1); return; }
		msg.update('暂时无法确认角色；请重新连接后刷新页面。', 'info');
		setTimeout(function() { msg.close(); }, 5000);
	},
	refreshAdapters: function(attempt) {
		attempt = attempt || 0;
		var self = this, list = this.q('adapters');
		list.replaceChildren();
		var wait = document.createElement('div'); wait.className = 'mud-note mud-booting';
		wait.textContent = M.translate('正在扫描 USB 网卡…'); list.appendChild(wait);
		M.busy(this.q('refresh'), true);
		L.resolveDefault(M.callUsbNetList(), {}).then(function(r) {
			M.busy(self.q('refresh'), false);
			list.replaceChildren();
			if (!r.ok || !r.devices || !r.devices.length) {
				list.textContent = !r.ok ? M.translate('读取失败：') + (r.error || M.translate('连接中断')) : M.translate('没有发现 USB 网卡，请通过 OTG 接入受支持的 USB 以太网卡。');
				if (self.state.role === 'host' && attempt < 2)
					setTimeout(function() { if (self.state.role === 'host') self.refreshAdapters(attempt + 1); }, 1600);
				return;
			}
			r.devices.forEach(function(d) {
				var row = document.createElement('div'); row.className = 'mud-device-item';
				var main = document.createElement('div'); main.className = 'mud-device-item-main';
				var dot = document.createElement('i'); dot.className = 'mud-device-dot' + (d.carrier ? ' up' : ''); main.appendChild(dot);
				var info = document.createElement('div');
				var name = document.createElement('div'); name.className = 'mud-device-item-name'; name.textContent = d.name;
				var sub = document.createElement('div'); sub.className = 'mud-device-item-sub'; sub.textContent = M.translate(d.carrier ? '链路已连接' : '链路未连接') + ' · ' + (d.driver || '') + (d.mac ? ' · ' + d.mac : '');
				info.appendChild(name); info.appendChild(sub); main.appendChild(info); row.appendChild(main);
				var btn = document.createElement('button'); btn.className = 'mud-btn'; btn.textContent = M.translate(d.managed_elsewhere ? '已分配其他网络' : d.in_lan && d.bound ? '已加入 LAN' : d.in_lan ? '重新连接 LAN' : '添加到 LAN'); btn.disabled = !!d.managed_elsewhere || !!(d.in_lan && d.bound);
				btn.addEventListener('click', function() {
					M.confirmBox('添加 USB 网卡到 LAN？', '这会保存网桥配置并重新加载网络，现有连接可能短暂中断。', { okText: '添加' }).then(function(yes) {
						if (!yes) return;
						M.busy(btn, true); var msg = M.toast('正在添加 USB 网卡…', { type: 'busy', timeout: 0 });
						L.resolveDefault(M.callUsbNetAdd(d.name), {}).then(function(a) {
							M.busy(btn, false); msg.update(a.ok ? '已添加到 LAN' : '添加失败：' + (a.error || '未知错误'), a.ok ? 'success' : 'error');
							setTimeout(function() { msg.close(); }, 3500); self.refreshAdapters();
						});
					});
				});
				row.appendChild(btn); list.appendChild(row);
			});
		});
	}
});
