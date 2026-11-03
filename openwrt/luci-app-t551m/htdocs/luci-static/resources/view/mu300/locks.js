'use strict';
'require view';
'require poll';
'require mu300.common as M';
'require mu300.auto-mode as AutoMode';
'require mu300.roaming as Roaming';

/* Network settings use verified asynchronous jobs. Each operation reports its
 * own completion/error; bands require command acknowledgement, other fields verify. */

var MODES = [ [ 'auto', '自动' ], [ '5g4g', '5G/4G' ], [ '4g', '仅 4G' ], [ 'sa', '5G SA' ], [ 'nsa', '5G NSA' ] ];
var NR_CAND = [], LTE_CAND = []; /* 读取后端能力后再显示，避免短暂展示错误频段。 */

return view.extend({
	load: function() { return Promise.resolve(); },

	render: function() {
		M.injectCss();
		M.watchSms();
		var root = document.createElement('div');
		root.className = 'mud';
		root.innerHTML = `
<!-- 与主页同一套 hero 结构：mud-hero-l/mud-hero-r 让手机端媒体查询统一生效
     （信息块在上，RSRP 行左对齐、芯片右对齐），桌面端保持 RSRP 块右对齐 -->
<div class="mud-card mud-hero">
  <div class="mud-hero-l">
    <div style="font-size:.78rem;color:var(--text-muted,var(--text-light,#777))">当前驻网</div>
    <div style="font-size:1.25rem;font-weight:700;margin-top:2px" id="mud-srv-rat">--</div>
    <div class="mud-cellline" id="mud-srv"></div>
    <div class="mud-loadline" id="mud-serving-loading" role="status"></div>
  </div>
  <div class="mud-hero-r">
    <div class="mud-rsrp" id="mud-srv-rsrp" style="font-size:1.9rem">--</div>
    <div class="mud-chips" id="mud-srv-chips"></div>
  </div>
</div>

<div class="mud-sec">
  <h3>网络模式 · EN-DC</h3>
  <div class="mud-loadline" id="mud-lock-loading" role="status"></div>
  <div class="mud-ctl" id="mud-lock-modes" style="grid-template-columns:repeat(auto-fit,minmax(76px,1fr));max-width:520px"></div>
  <div id="mud-auto-mode" hidden></div>
  <div class="mud-ctl" style="margin-top:7px;grid-template-columns:1fr 1fr;max-width:340px">
    <button class="mud-btn" id="mud-lock-endc">EN-DC</button>
    <button class="mud-btn" id="mud-lock-refresh">刷新锁定状态</button>
  </div>
  <div class="mud-ctl" style="margin-top:7px;max-width:340px">
    <button class="mud-btn" id="mud-lock-auto-apply">开机自动应用</button>
  </div>
  <div class="mud-note">关闭后只停止下次开机回放，已保存的网络、VoLTE 和 VoNR 设置不会被删除。</div>
</div>

<div id="mud-roaming"></div>
<div class="mud-sec">
  <h3>VoLTE · VoNR</h3>
  <div class="mud-note">VoLTE 用于 4G 通话，VoNR 用于 5G SA 通话。设置按当前查看的 SIM 保存，并跟随“开机自动应用”。</div>
  ${['volte','vonr'].map(function(kind) {
    var name = {volte:'VoLTE',vonr:'VoNR'}[kind];
    return '<div class="mud-r mud-voice-row"><span class="mud-k">'+name+'</span>'+
      '<span class="mud-v" id="mud-lock-'+kind+'-state">--</span>'+
      '<button type="button" class="mud-btn mud-voice-switch" data-voice="'+kind+'" role="switch" aria-label="'+name+'" aria-checked="false" disabled>'+
      '<span class="mud-voice-track" aria-hidden="true"></span></button></div>';
  }).join('')}
  <div class="mud-note">关闭 VoLTE 或 VoNR 不等于屏蔽全部来电和短信，传统网络业务仍可能到达。</div>
</div>

<div class="mud-sec">
  <h3>频段锁定</h3>
  <div class="mud-cols">
    <div>
      <div class="mud-rows">
        <div class="mud-r"><span class="mud-k">NR 频段</span><span class="mud-v" id="mud-lock-nrline">--</span></div>
      </div>
      <div class="mud-chiprow" id="mud-lock-nr"></div>
    </div>
    <div>
      <div class="mud-rows">
        <div class="mud-r"><span class="mud-k">LTE 频段</span><span class="mud-v" id="mud-lock-lteline">--</span></div>
      </div>
      <div class="mud-chiprow" id="mud-lock-lte"></div>
    </div>
  </div>
  <div class="mud-ctl" style="margin-top:8px;max-width:360px">
    <button class="mud-btn" id="mud-lock-nr-apply">应用 NR 频段</button>
    <button class="mud-btn" id="mud-lock-lte-apply">应用 LTE 频段</button>
  </div>
</div>

<div class="mud-sec">
  <h3>邻区与小区锁定</h3>
  <div class="mud-loadline" id="mud-neigh-loading" role="status"></div>
  <div id="mud-lockedcells"></div>
  <div class="mud-ctl" style="max-width:400px;margin-bottom:8px">
    <button class="mud-btn" id="mud-lock-cell">锁定当前服务小区</button>
    <button class="mud-btn warn" id="mud-lock-cell-off">解除小区锁定</button>
  </div>
  <details class="mud-manual-cell">
    <summary>手动输入小区</summary>
    <form id="mud-lock-manual-form" novalidate>
      <div class="mud-manual-cell-fields">
        <label><span>制式</span><select id="mud-lock-manual-rat"><option value="lte">LTE (4G)</option><option value="nr">NR (5G)</option></select></label>
        <label><span>频点（EARFCN / NR-ARFCN）</span><input id="mud-lock-manual-frequency" type="text" inputmode="numeric" autocomplete="off" required></label>
        <label><span>PCI</span><input id="mud-lock-manual-pci" type="text" inputmode="numeric" autocomplete="off" required></label>
        <button type="submit" class="mud-btn" id="mud-lock-manual-apply">锁定指定小区</button>
      </div>
      <div class="mud-note">LTE：EARFCN 0–262143，PCI 0–503；NR：NR-ARFCN 1–3279165，PCI 0–1007。</div>
      <div class="mud-note">应用于当前查看的 SIM，无需小区出现在邻区列表中。请输入频点编号，不是 MHz 频率。</div>
    </form>
  </details>
  <div class="mud-scroll">
  <table class="mud-table"><thead><tr><th>制式/频段</th><th>PCI</th><th>频点</th><th>RSRP</th><th>RSRQ</th><th>SINR</th><th></th></tr></thead>
  <tbody id="mud-neigh"></tbody></table>
  </div>
  <div class="mud-note">手动应用会短暂重建蜂窝连接。启用“开机自动应用”后，保存的设置会在 AT 就绪、首次拨号前应用，不额外重启射频。频段全不选再点应用 = 恢复自动。</div>
</div>`;
		M.localize(root);
		this.wire(root);
		M.simSelector(root);
		return root;
	},

	wire: function(root) {
		var self = this;
		this._root = root; this._disposed = false;
		this.lockSel = { nr: {}, lte: {} };
		this.lockCand = { nr: NR_CAND, lte: LTE_CAND };
		this.Q = function(id) { return root.querySelector('#mud-' + id); };
		this._roaming = Roaming.mount(this.Q('roaming'));
		this.loading('serving', true); this.loading('lock', true); this.loading('neigh', true);

		/* 主题化确认框替代浏览器 confirm；确认后再进入实际执行 */
		var apply = function(kind, val, what, opts) {
			opts = opts || {};
			var slot = M.simSlot();
			opts.slot = slot;
			return M.confirmBox('应用「' + what + '」？',
				opts.noSfun ? '' : '蜂窝连接会重新建立，蜂窝断开约半分钟。',
				{ danger: !opts.noSfun, okText: '应用' })
				.then(function(go) {
					if (!go || self._disposed || !root.isConnected) return;
					if (M.simSlot() !== slot) { self.note('查看卡槽已改变，请重新确认操作', 'info'); return; }
					applyNow(kind, val, what, opts);
				});
		};
		var applyNow = function(kind, val, what, opts) {
			if (self._applying) { self.note('请等待当前操作完成', 'info'); return; }
			self._applying = true;
			var btn = opts.btn;
			if (opts.optimistic) opts.optimistic();   /* 按钮立刻切到目标态，回读负责校正 */
			M.busy(btn, true);   /* 在 optimistic 之后：它可能重置按钮的 className */
			self.note('正在后台应用 ' + what + ' …' + (opts.noSfun ? '' : '（重新建立蜂窝连接，约半分钟）'), 'busy');
			var run = function() {
				if (opts.prepare && (self._disposed || M.simSlot() !== opts.slot))
					throw new Error(M.translate('查看卡槽已改变，请重新确认操作'));
				return M.callLockSet(kind, val);
			};
			// Save only the compatibility option after confirmation; keep the
			// existing selected-SIM job and AT/replay ordering unchanged.
			var operation = opts.prepare ? Promise.resolve().then(opts.prepare).then(run) : run();
			operation.then(function(r) {
				r = r || {};
				if (!r.ok) {
					self._applying = false;
					M.busy(btn, false); self.paintAutoMode();
					self.refresh();
					self.note('失败：' + (r.error || '未知错误'), 'error');
					return;
				}
				self.readback(r, btn);
			}, function(error) { self._applying = false; M.busy(btn, false); self.paintAutoMode(); self.refresh(); self.note(error && error.message || '调用失败', 'error'); });
		};

		this.autoMode = AutoMode.attach(this.Q('auto-mode'), function(btn, prepare) {
			apply('mode', 'auto', M.translate('自动模式兼容性'), {btn:btn, prepare:prepare});
		});

		this.Q('lock-modes').innerHTML = MODES.map(function(m) {
			return '<button class="mud-btn" data-mode="' + m[0] + '">' + M.esc(M.translate(m[1])) + '</button>';
		}).join('');
		root.querySelectorAll('#mud-lock-modes .mud-btn').forEach(function(b) {
			b.onclick = function() {
				var m = b.getAttribute('data-mode');
				if (m === (self.lastLock && self.lastLock.mode && self.lastLock.mode.label)) return;
				var btn = b;
				apply('mode', m, '网络模式：' + b.textContent, { btn: btn, optimistic: function() {
					Array.prototype.forEach.call(self.Q('lock-modes').querySelectorAll('.mud-btn'), function(x) {
						x.className = x === btn ? 'mud-btn on' : 'mud-btn';
					});
				} });
			};
		});
		this.Q('lock-endc').onclick = function() {
			var on = self.lastLock && self.lastLock.endc === '1';
			var btn = this;
			apply('endc', on ? 'off' : 'on', on ? '关闭 EN-DC（NSA 锚点）' : '开启 EN-DC（NSA 锚点）',
				{ btn: btn, noSfun: true, optimistic: function() {
					btn.className = 'mud-btn' + (on ? '' : ' on');
					btn.textContent = on ? 'EN-DC' : 'EN-DC ✓';
				} });
		};
		this.Q('lock-auto-apply').onclick = function() {
			var on = !self.lastLock || self.lastLock.auto_apply !== 0;
			var btn = this;
			apply('auto_apply', on ? 'off' : 'on', on ? '关闭开机自动应用' : '开启开机自动应用',
				{ btn: btn, noSfun: true, optimistic: function() {
					btn.className = 'mud-btn' + (on ? '' : ' on');
					btn.textContent = on ? '开机自动应用' : '开机自动应用 ✓';
				} });
		};
		root.querySelectorAll('[data-voice]').forEach(function(btn) {
			btn.onclick = function() {
				var kind = btn.dataset.voice, state = (self.lastLock || {})[kind];
				if (self._applying || btn.disabled || !state || typeof state.enabled !== 'boolean') return;
				var val = state.enabled ? 'off' : 'on';
				var name = {volte:'VoLTE',vonr:'VoNR'}[kind];
				apply(kind, val, M.translate(val === 'on' ? '开启' : '关闭')+' '+name,
					{btn:btn,noSfun:true});
			};
		});
		this.Q('lock-refresh').onclick = function() {
			if (self.autoMode) self.autoMode.reload();
			var btn = this;
			M.busy(btn, true);
			self.note('正在直读调制解调器（最多几秒）…', 'busy');
			L.resolveDefault(M.callLockFresh('1')).then(function(l) {
				M.busy(btn, false); self.paintAutoMode();
				self.lastLock = l || {};
				self.paint();
				self.note(l && !l.error ? '已刷新' : '刷新失败：' + (l && l.error || '无法读取模组'), l && !l.error ? 'success' : 'error');
				self.paintNeighbors();
			}, function() { M.busy(btn, false); self.paintAutoMode(); self.note('刷新失败', 'error'); });
			self.loadServing();
			self.loadServingMeta();
		};

		this.chipRow = function(el, rat, cand) {
			el.innerHTML = cand.map(function(b) {
				return '<span class="mud-chip" data-rat="' + rat + '" data-b="' + b + '">' + (rat === 'nr' ? 'n' : 'B') + b + '</span>';
			}).join('');
			/* chips 重建后恢复选中态 */
			Array.prototype.forEach.call(el.children, function(ch) {
				var b = ch.getAttribute('data-b');
				if (self.lockSel[rat][b]) ch.className = 'mud-chip on';
			});
		};
		this.chipRow(this.Q('lock-nr'), 'nr', NR_CAND);
		this.chipRow(this.Q('lock-lte'), 'lte', LTE_CAND);
		/* 事件委托绑在容器上：paint() 依模组能力重建 chips 后点击依然有效 */
		[ 'nr', 'lte' ].forEach(function(rat) {
			self.Q('lock-' + rat).addEventListener('click', function(ev) {
				var ch = ev.target;
				if (!ch.getAttribute || !ch.getAttribute('data-b')) return;
				var b = ch.getAttribute('data-b');
				self.lockSel[rat][b] = !self.lockSel[rat][b];
				ch.className = self.lockSel[rat][b] ? 'mud-chip on' : 'mud-chip';
			});
		});
		var selBands = function(rat) {
			return Object.keys(self.lockSel[rat]).filter(function(b) { return self.lockSel[rat][b]; })
				.map(Number).sort(function(a, b) { return a - b; });
		};
		this.Q('lock-nr-apply').onclick = function() {
			var sel = selBands('nr');
			if (!sel.length) return apply('nr', '', 'NR 频段：恢复自动', { btn: this });
			apply('nr', sel.join(','), 'NR 频段锁定：n' + sel.join(' n'), { btn: this });
		};
		this.Q('lock-lte-apply').onclick = function() {
			var sel = selBands('lte');
			if (!sel.length) return apply('lte', '', 'LTE 频段：恢复自动', { btn: this });
			apply('lte', sel.join(','), 'LTE 频段锁定：B' + sel.join(' B'), { btn: this });
		};
		this.Q('lock-cell').onclick = function() { apply('cell', 'auto', '锁定当前服务小区', { btn: this }); };
		this.Q('lock-cell-off').onclick = function() { apply('cell', 'off', '解除小区锁定', { btn: this }); };

		this.Q('lock-manual-form').onsubmit = function(ev) {
			ev.preventDefault();
			if (self._disposed || self._applying || self._manualConfirm) return;
			var rat = self.Q('lock-manual-rat').value;
			var frequency = self.Q('lock-manual-frequency').value.trim();
			var pci = self.Q('lock-manual-pci').value.trim();
			var nr = rat === 'nr';
			if ((rat !== 'lte' && !nr) || !/^[0-9]{1,7}$/.test(frequency) || !/^[0-9]{1,4}$/.test(pci) ||
				Number(frequency) < (nr ? 1 : 0) || Number(frequency) > (nr ? 3279165 : 262143) ||
				Number(pci) > (nr ? 1007 : 503)) {
				self.note('请输入范围内的十进制频点和 PCI', 'error');
				return;
			}
			var value = rat + ':' + Number(frequency) + ',' + Number(pci);
			self._manualConfirm = true;
			return apply('cell', value, M.translate('手动锁定小区') + ' ' + (nr ? 'NR' : 'LTE') +
				' / ' + Number(frequency) + ' / PCI ' + Number(pci), {btn:self.Q('lock-manual-apply')})
				.finally(function() { self._manualConfirm = false; });
		};


		this.Q('lockedcells').addEventListener('click', function(ev) {
			var btn = ev.target.closest('[data-unlock]');
			if (btn) apply('cell', 'off-' + btn.getAttribute('data-unlock'), '解除小区锁定', {btn:btn});
		});
		this.Q('neigh').addEventListener('click', function(ev) {
			var btn = ev.target.closest('[data-lock]');
			if (btn) apply('cell', btn.getAttribute('data-lock'), '锁定小区 ' + btn.getAttribute('data-lock'), {btn:btn});
		});

		this.refresh();
		this.loadServingMeta();
		this.loadServing();
		/* A slow live AT request must not hold up cache/neighbor discovery. */
		this._poll = function() { self.loadServing(); return self.loadServingMeta(); };
		poll.add(this._poll, 2);
	},
	unload: function() {
		this._disposed = true;
		if (this._roaming) this._roaming.dispose();
		clearTimeout(this._lockRetry);
		if (this._poll) poll.remove(this._poll);
	},
	loading: function(part, pending, error, notice) {
		var el = this.Q && this.Q(part + '-loading'); if (!el) return;
		el.hidden = !pending && !error;
		el.classList.toggle('is-error', !!error);
		var text = notice || error || ({serving:'正在读取服务小区…',lock:'正在读取锁定设置…',neigh:'正在读取邻小区…'})[part];
		var html = (pending ? '<i class="mud-loading-spinner" aria-hidden="true"></i>' : '') + '<span>' + M.esc(M.translate(text)) + '</span>';
		if (el.innerHTML !== html) el.innerHTML = html;
	},
	paintNeighbors: function() {
		var nb = this.Q && this.Q('neigh');
		if (nb && this.neighborCell) nb.innerHTML = M.neighborRows(this.neighborCell, (this.lastLock || {}).cells || []);
	},
	mergeServing: function() {
		if (!this.lastSignal) return;
		var c = {}, meta = this.servingMeta || {}, live = this.lastSignal;
		if (meta.error && Number(meta.ts) > Number(live.ts)) { this.paintServing(meta); return; }
		Object.keys(meta).forEach(function(k) { c[k] = meta[k]; });
		Object.keys(live).forEach(function(k) { c[k] = live[k]; });
		if (!live.error && live.ts) delete c.error;
		if (live.partial && (meta.lte || meta.nr)) {
			['sig', 'sig_src', 'lte', 'nr'].forEach(function(k) { c[k] = meta[k]; });
		}
		this.paintServing(c);
	},

	/* 统一反馈：所有提示走顶部 toast（M.toast），进行中的用 busy 自带转圈；
	 * 同一时间只保留一条（新提示顶掉旧提示，进度→结果一路更新不堆叠）。 */
	note: function(txt, type) {
		if (this._toast) this._toast.close();
		this._toast = M.toast(txt, { type: type || 'info' });
	},

	/* 运营商与邻区属于低频元数据；实时信号不会从这里读取。 */
	loadServingMeta: function() {
		var self = this;
		if (this._disposed || this._metaRequest) return this._metaRequest;
		this._metaRequest = M.callCells().then(function(st) {
			if (self._disposed) return;
			if (!st || st.error) throw new Error(st && st.error || '邻区读取失败');
			var cell = st.cell;
			if (cell && cell.error) throw new Error(cell.error);
			if (cell) self.servingMeta = cell;
			if (!self._liveLoaded && st.sig && !st.sig.error && st.sig_age >= 0 && st.sig_age <= 10) {
				self.lastSignal = st.sig; self.loading('serving', false);
			}
			self.mergeServing();
			var pending = !cell || !!cell.neigh_pending;
			if (!pending) { self.neighborCell = cell; self._neighborSince = null; self.paintNeighbors(); }
			else if (!self._neighborSince) self._neighborSince = Date.now();
			var stalled = pending && Date.now() - self._neighborSince > 30000;
			self.loading('neigh', pending && !stalled, stalled ? '邻区读取较慢，正在等待模组回应' : null);
		}).catch(function(error) {
			if (!self._disposed) self.loading('neigh', false, error.message || '邻区读取失败');
		}).finally(function() { self._metaRequest = null; });
		return this._metaRequest;
	},

	/* 每次都由后端完成一轮新的 AT 快照；不接受上一轮 signal/cell 缓存。 */
	loadServing: function() {
		var self = this;
		if (this._disposed || this._signalRequest) return this._signalRequest;
		this._signalRequest = M.callSignal().then(function(live) {
			if (self._disposed) return;
			if (live && (live.busy || live.error === 'busy')) {
				self.loading('serving', true, null, 'AT 通道正忙，正在等待更新…'); return;
			}
			if (!live || live.error || !live.ts) throw new Error(live && live.error || '模组尚未返回有效的实时信号');
			self.lastSignal = live; self._liveLoaded = true;
			self.loading('serving', false); self.mergeServing();
		}).catch(function(error) {
			if (!self._disposed) {
				self.lastSignal = null; self.paintServing(null);
				self.loading('serving', false, '信号读取失败');
			}
		}).finally(function() { self._signalRequest = null; });
		return this._signalRequest;
	},

	paintServing: function(c) {
		var e = this.Q('srv'); if (!e) return;
		this.lastCell = c;
		if (!c || c.error) {
			this.Q('srv-rat').textContent = M.translate('暂无驻网数据');
			this.Q('srv-rsrp').textContent = '--';
			this.Q('srv-chips').innerHTML = '';
			e.innerHTML = '';
			return;
		}
		var ratTxt = (c.nr && c.nr.band) ? ((c.lte && c.lte.band) ? '5G NSA' : '5G SA') : (c.lte && c.lte.band) ? 'LTE' : '--';
		var sig = c.sig || {}, label = M.qLabel(sig.rsrp, sig.rsrq, sig.sinr);
		var operName = M.carrierName(c.operator);
			if (operName === '--' && c.ident && c.ident.imsi)
				operName = M.translate(M.PLMN_CN[c.ident.imsi.substring(0, 5)] || c.ident.imsi.substring(0, 5));
			this.Q('srv-rat').textContent = ratTxt + ' · ' + operName;
		this.Q('srv-rat').style.color = M.qCol(label);
		var rsrpEl = this.Q('srv-rsrp');
		if (sig.rsrp != null) { rsrpEl.innerHTML = sig.rsrp.toFixed(1) + '<small> dBm</small>'; rsrpEl.style.color = M.qCol(label); }
		else { rsrpEl.textContent = '--'; rsrpEl.style.color = ''; }
		this.Q('srv-chips').innerHTML =
			(sig.rsrq != null ? '<span class="mud-tag">RSRQ ' + sig.rsrq.toFixed(1) + '</span>' : '') +
			(sig.sinr != null ? '<span class="mud-tag">SINR ' + sig.sinr.toFixed(1) + '</span>' : '');
		var rows = [];
		if (c.nr && c.nr.band) rows.push([ 'NR 服务小区', 'n' + c.nr.band + ' · PCI ' + c.nr.pci + ' · ARFCN ' + c.nr.arfcn + (c.nr.bw_mhz ? ' · ' + c.nr.bw_mhz + ' MHz' : '') ]);
		if (c.lte && c.lte.band) rows.push([ 'LTE 锚点', 'B' + c.lte.band + ' · PCI ' + c.lte.pci + ' · EARFCN ' + c.lte.earfcn ]);
		e.innerHTML = rows.map(function(x) {
			return '<div class="mud-srvline"><span class="k">' + M.esc(M.translate(x[0])) + '</span><span class="v">' + M.esc(x[1]) + '</span></div>';
		}).join('');
	},

	/* Follow this operation's result; device and browser clocks can differ. */
	readback: function(operation, btn) {
		var self = this, receipt;
		return M.waitLockJob(operation).then(function(result) {
			receipt = result;
			return M.callLockGet().catch(function() { return null; });
		}).then(function(l) {
			if (l && !l.error) {
				self.lastLock = l; self.paint(); self.paintServing(self.lastCell); self.paintNeighbors();
			}
			if (receipt.reconnect === 'deferred')
				self.note('设置已保存；当前模组未就绪或射频已关闭，已跳过重连', 'info');
			else if (receipt.reconnect === 'failed')
				self.note('设置已接受，但重连失败：' + (receipt.reconnect_error || ''), 'error');
			else if (!l || l.error || receipt.refresh_error)
				self.note('设置已应用；状态刷新暂不可用，请稍后刷新', 'info');
			else self.note(['lte','nr','bands_default'].indexOf(operation.kind || operation.op) >= 0 ?
				'频段设置已应用，实际频段以模组回读为准' : '已应用并核对模组状态', 'success');
		}).catch(function(error) {
			self.note('应用失败：' + (error.message || error), 'error');
			self.refresh();
		}).then(function() {
			self._applying = false; M.busy(btn, false); self.paintAutoMode();
			if (!self._disposed) self.paintVoiceSwitches(self.lastLock || {});
		});
	},
	refreshSoon: function() {
		var self = this;
		setTimeout(function() { self.refresh(); }, 1500);
	},


	refresh: function() {
		var self = this;
		if (this._disposed) return;
		return L.resolveDefault(M.callLockGet()).then(function(l) {
			if (self._disposed) return;
			l = l || {};
			/* 空结果多半是 rpcd 高并发下的一次瞬时失败（实测同请求重发即好）：轻量重试 */
			if (!l.mode && (self._retry = (self._retry || 0) + 1) <= 3)
				return self._lockRetry = setTimeout(function() { self.refresh(); }, 1800);
			self._retry = 0;
			self.lastLock = l;
			self.paint();
			/* 锁定状态回来了，把邻区表的“已锁定”标记也刷新一下 */
			self.paintNeighbors();
		});
	},

	paintVoiceSwitches: function(l) {
		var self = this;
		['volte','vonr'].forEach(function(kind) {
			var state = l[kind] || {}, known = typeof state.enabled === 'boolean';
			var text = M.translate(known ? (state.enabled ? '已开启' : '已关闭') : '状态暂不可读，请刷新后重试');
			var status = self.Q('lock-'+kind+'-state');
			if (status) status.textContent = text;
			var box = self._root;
			if (box) box.querySelectorAll('[data-voice="'+kind+'"]').forEach(function(btn) {
				btn.className = 'mud-btn mud-voice-switch'+(known && state.enabled ? ' on' : '');
				btn.setAttribute('aria-checked', String(known && state.enabled));
				btn.setAttribute('aria-label', kind === 'volte' ? 'VoLTE' : 'VoNR');
				btn.disabled = !!self._applying || !known;
			});
		});
	},

	paintAutoMode: function() {
		if (this.autoMode) this.autoMode.update((this.lastLock || {}).mode, !!this._applying);
	},

	paint: function() {
		this.paintAutoMode();
		var l = this.lastLock || {};
		var self = this;
		this.loading('lock', false, l.error || (!l.mode ? '锁定状态读取失败，请刷新' : null));
		this.paintVoiceSwitches(l);
		var setR = function(id, txt) { var e = self.Q(id); if (e) e.textContent = (txt == null || txt === '') ? '--' : txt; };
		if (l.error) { setR('lock-nrline', l.error); setR('lock-lteline', ''); return; }
		var MODE_TXT = { auto: '自动（5G/4G）', '4g': '仅 4G', sa: '仅 5G SA', nsa: '仅 5G NSA' };
		var cur = this.Q('lock-modes');
		if (cur) Array.prototype.forEach.call(cur.querySelectorAll('.mud-btn'), function(b) {
			b.className = (b.getAttribute('data-mode') === (l.mode && l.mode.label)) ? 'mud-btn on' : 'mud-btn';
		});
		var eb = this.Q('lock-endc');
		if (eb) { eb.className = 'mud-btn' + (l.endc === '1' ? ' on' : ''); eb.textContent = l.endc === '1' ? 'EN-DC' : 'EN-DC'; }
		var ab = this.Q('lock-auto-apply'), autoApply = l.auto_apply !== 0;
		if (ab) { ab.className = 'mud-btn' + (autoApply ? ' on' : ''); ab.textContent = M.translate(autoApply ? '开机自动应用 ✓' : '开机自动应用'); }

		/* NR 来自模组能力列表；LTE 使用平台配置，避免显示固件不接受的频段。 */
		var caps = l.caps || {};
		/* 已锁定小区独立表：多小区都列出来，每个 RAT 一个解锁按钮 */
		var lc = self.Q('lockedcells');
		if (lc) {
			var cells = l.cells || [];
			lc.innerHTML = cells.length
				? '<div class="mud-note" style="margin:0 0 4px">' + M.esc(M.translate('已锁定小区')) + '</div><table class="mud-table"><tbody>' +
					cells.map(function(k) {
						var parts = k.split(':'), rat = parts[0], fp = (parts[1] || '').split(',');
						return '<tr><td>' + (rat == 'nr' ? 'NR' : 'LTE') + '</td><td>' + M.esc(fp[0] || '?') + '</td>' +
							'<td>' + M.esc(fp[1] || '?') + '</td>' +
							'<td><button class="mud-lockbtn" data-unlock="' + rat + '">' + M.esc(M.translate('解锁 ')) + (rat == 'nr' ? 'NR' : 'LTE') + '</button></td></tr>';
					}).join('') + '</tbody></table>'
				: '';
		}
		[ 'nr', 'lte' ].forEach(function(rat) {
			var capList = (caps[rat] || '').split(',').map(Number).filter(function(b) { return b > 0; });
			{
				capList.sort(function(a, b) { return a - b; });
				self.lockCand[rat] = capList;
				self.lockSel[rat] = {};
				var box = self.Q('lock-' + rat);
				if (box) self.chipRow(box, rat, capList);
			}
			var locked = (l[rat] && l[rat].locked) || '';
			var arr = locked ? locked.split(',').map(Number) : [];
			var isAuto = arr.length === 0 || (capList.length > 0 && capList.every(function(b) { return arr.indexOf(b) >= 0; }));
			setR('lock-' + rat + 'line', M.translate(!capList.length ? '频段能力暂不可用，请刷新'
				: isAuto
				? '自动（支持 ' + self.lockCand[rat].length + ' 个）'
				: '已锁 ' + arr.length + ' 个：' + (rat === 'nr' ? 'n' : 'B') + arr.join(' ' + (rat === 'nr' ? 'n' : 'B'))));
			var box = self.Q('lock-' + rat);
			if (box) Array.prototype.forEach.call(box.children, function(ch) {
				var b = ch.getAttribute('data-b');
				var on = !isAuto && arr.indexOf(Number(b)) >= 0;
				self.lockSel[rat][b] = on;
				ch.className = on ? 'mud-chip on' : 'mud-chip';
			});
		});
	}
});
