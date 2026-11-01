// Both frontends use the same validator and kernel readback.
function cpu_read() {
	return ctx.sh_json('/usr/libexec/unisoc-modem/cpu-control get') ?? {};
}
function cpu_set(id, value) {
	let body = replace(sprintf('%J', {id, value}), /'/g, "'\\''");
	let result = ctx.sh_json(`/usr/libexec/unisoc-modem/cpu-control set '${body}'`);
	return result?.ok ? null : result?.error ?? 'CPU control unavailable';
}
function cpu_link(id, zh, en) {
	return {id, type:'category', category:id, label:L(zh,en)};
}
function cpu_voltage_reason(reason) {
	const reasons = {
		'CPU voltage adjustment is not supported on this SoC': '当前芯片尚未适配电压调整',
		'SML partitions are not ready; refresh after initialization': 'SML 分区尚未就绪，请稍后刷新',
		'SML partitions could not be read; refresh and check storage': '无法读取 SML 分区，请检查存储',
		'SML voltage ABI could not be established': '尚未匹配到本机 SML 的调压协议，请保留原厂电压',
		'SML compatibility checker is not ready; refresh after installation': 'SML 检查组件尚未就绪，请安装后刷新',
		'CPU voltage interface is missing from this kernel': '当前内核缺少调压接口，请更新配套内核和模块'
	};
	return L(reasons[reason] ?? reason, reason);
}
const cpu_inventory = cpu_read();
const cpu_categories = [{
	id:'cpu', parent:'system', label:L('CPU 设置','CPU settings'),
	items:function() {
		let s = cpu_read(), items = [];
		if (!s.available) push(items, {id:'unavailable',type:'info',label:L('调频驱动','Frequency driver'),
			value:L('尚未就绪','Not ready')});
		for (let p in s.policies ?? [])
			push(items, cpu_link('cpu_' + p.id, `CPU ${p.cpus}`, `CPU ${p.cpus}`));
		push(items, cpu_link('cpu_thermal','温控设置','Thermal settings'));
		push(items, {id:'persist',type:'toggle',label:L('开机应用调频与温控','Persist frequency and thermal'),value:!!s.persistent,reload:true,
			note:L('电压独立保存，重启后生效','Voltage is saved separately and applied after reboot')});
		if (s.voltage_reboot_required) push(items,{id:'voltage_pending',type:'info',label:L('电压配置','Voltage profile'),value:L('重启后生效','Reboot to apply')});
		if (s.voltage_error) push(items,{id:'voltage_error',type:'info',label:L('电压已回退','Voltage reverted'),value:s.voltage_error});
		push(items, {id:'reset',type:'action',label:L('恢复默认','Restore defaults'),confirm:true,reload:true,
			note:L('恢复调频与温控；电压重启后恢复原厂','Restore frequency and thermal; factory voltage takes effect after reboot')});
		return items;
	}, set:cpu_set
}, {
	id:'cpu_thermal',parent:'cpu',label:L('温控设置','Thermal settings'),
	items:function() {
		let items = [];
		for (let z in cpu_read().zones ?? []) {
			push(items,{id:z.id,type:'info',label:L(z.name,z.name),value:z.temp == null ? '--' : `${z.temp / 1000} °C`});
			for (let t in z.trips) {
				let critical = filter(z.trips, x => x.type == 'critical' || x.type == 'hot');
				let ceiling = 100;
				for (let c in critical) ceiling = min(ceiling,c.temp / 1000 - 10);
				push(items,{id:`${z.id}_trip${t.id}`,type:t.writable ? 'number' : 'info',
					label:t.type == 'critical' ? L('过热关机保护','Critical shutdown') : t.throttles_cpu == false ? L('被动温控起点','Passive monitoring threshold') : L('降频触发温度','CPU throttling threshold'),
					value:t.writable ? t.temp / 1000 : `${t.temp / 1000} °C`,min:40,max:ceiling,step:1,unit:' °C',reload:true,
						note:t.writable ? (t.throttles_cpu == false ? L('提高温度检测频率，此处不直接限频','Increases temperature checks; does not directly throttle the CPU') : L(`回差 ${t.hysteresis / 1000} °C · 阈值须逐级升高`,`Hysteresis ${t.hysteresis / 1000} °C · Keep trips in increasing order`))
						: L('由系统保护策略管理','Managed by system protection')});
			}
		}
		return items;
	},set:cpu_set
}];
for (let inventory in cpu_inventory.policies ?? []) {
	let policy_id = inventory.id;
	push(cpu_categories, {
		id:'cpu_' + policy_id,parent:'cpu',label:L(`CPU ${inventory.cpus}`,`CPU ${inventory.cpus}`),
		items:function() {
			let state = cpu_read();
			let p = filter(state.policies ?? [], x => x.id == policy_id)[0];
			if (!p) return [];
			let options = map(p.frequencies, f => ({value:`${f}`,label:`${f / 1000} MHz`}));
			let items = [
				{id:'current',type:'info',label:L('实际频率','Current frequency'),value:p.current == null ? '--' : `${p.current / 1000} MHz`},
				{id:'effective',type:'info',label:L('当前有效范围','Effective range'),value:`${(p.effective_min ?? p.min) / 1000}–${(p.effective_max ?? p.max) / 1000} MHz`,
				 note:L('温控可以进一步限制设定的范围','Thermal protection may further limit the requested range')},
				{id:`${p.id}_governor`,type:'choice',label:L('调速器','Governor'),value:p.governor,reload:true,
				 options:map(p.governors,g=>({value:g,label:g})),note:L('schedutil 按负载调频；powersave 保持最低档','schedutil follows load; powersave requests the minimum')},
				{id:`${p.id}_min`,type:'choice',label:L('最低频率','Minimum frequency'),value:`${p.min}`,reload:true,
				 options:filter(options,o=>int(o.value)<=p.max)},
				{id:`${p.id}_max`,type:'choice',label:L('最高频率','Maximum frequency'),value:`${p.max}`,reload:true,
				 options:filter(options,o=>int(o.value)>=p.min),note:L('最低与最高相同可固定频率；温控仍可降频','Equal limits fix the requested frequency; thermal limits still apply')},
				{id:'voltage',type:'info',label:L('实际供电电压','Measured voltage'),value:p.voltage_actual == null ? '--' : `${p.voltage_actual / 1000} mV`,
				 note:L('以下为当前生效的固件电压表','The voltage table below is currently active')}
			];
			if (p.voltage_boot_writable) {
				let offsets = [];
				for (let v = state.voltage_min; v <= state.voltage_max; v += state.voltage_step)
					push(offsets,{value:`${v}`,label:v == 0 ? L('原厂 · 0 mV','Factory · 0 mV') : `${v > 0 ? '+' : ''}${v / 1000} mV`});
				push(items,{id:`${p.id}_voltage_next`,type:'choice',label:L('下次启动电压偏移','Next boot voltage offset'),value:`${p.voltage_next}`,options:offsets,reload:true,
					note:L(`当前 ${p.voltage_offset / 1000} mV · 保存后重启生效`,`Active ${p.voltage_offset / 1000} mV · Reboot to apply`)});
				push(items,{id:'voltage_note',type:'info',label:L('电压调整说明','Voltage adjustment'),value:L('CPU 与 SRAM 同步偏移','CPU and SRAM offset together'),
					note:L('建议每次只调一档；崩溃或异常断电后自动回退原厂。关机充电使用原厂电压。','Change one step at a time. An unclean shutdown restores factory voltage. Charger-only boot uses factory voltage.')});
			} else if (state.voltage_unavailable_reason) {
				push(items,{id:'voltage_unavailable',type:'info',label:L('电压调整不可用','Voltage adjustment unavailable'),
					value:cpu_voltage_reason(state.voltage_unavailable_reason)});
			}
			for (let v in p.voltages) push(items,{id:`voltage_${v.khz}`,type:'info',label:`${v.khz / 1000} MHz`,value:`${v.uv / 1000} mV`});
			return items;
		},set:cpu_set
	});
}
