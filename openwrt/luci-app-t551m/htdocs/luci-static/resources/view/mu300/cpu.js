'use strict';
'require view';
'require rpc';
'require poll';
'require mu300.common as M';
'require mu300.cpu-cores as Cores';
'require mu300.cpu-idle as Idle';

/* CPU layout adapted from mu300-linux (local revision 25f8d0c).
 * MIT License
 *
 * Copyright (c) 2026 dikeckaan
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in all
 * copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE.
 *
 * Note: kernel/patches/*.patch modify GPL-2.0 kernel code and are licensed GPL-2.0.
 */

const getCpu = rpc.declare({object:'e5-cpu',method:'get',expect:{}});
const applyCpu = rpc.declare({object:'e5-cpu',method:'apply',params:['changes','persist'],expect:{}});
const resetCpu = rpc.declare({object:'e5-cpu',method:'reset',expect:{}});
const text = (zh,en) => M.translate(zh);
const mhz = value => value == null ? '—' : (value / 1000) + ' MHz';
const effectiveRange = p => text('当前有效范围：','Effective range: ') + mhz(p.effective_min ?? p.min) + ' – ' + mhz(p.effective_max ?? p.max);
const mv = value => value == null ? '—' : (value / 1000) + ' mV';
const offsetLabel = value => value == 0 ? text('原厂电压（0 mV）','Factory voltage (0 mV)') : (value > 0 ? '+' : '') + mv(value);
const voltageNow = p => text('当前偏移：','Active offset: ') + offsetLabel(p.voltage_offset) + text(' · 实测 ',' · Measured ') + mv(p.voltage_actual);

function node(tag, cls, value) {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    if (value != null) el.textContent = value;
    return el;
}
function field(label, input) {
    const wrap = node('label','cpu-field mud-cpu-field');
    wrap.append(node('span',null,label),input);
    return wrap;
}
function select(values, current, label) {
    const el = node('select');
    values.forEach(value => {
        const option = node('option',null,label ? label(value) : value);
        option.value = value; el.append(option);
    });
    el.value = current;
    return el;
}

return view.extend({
    load: function() { return getCpu(); },
    render: function(state) {
        M.injectCss(); M.localizeMenu();
        this.root = node('div','mud mud-cpu cpu-settings');
        // Layout adapted from the MU300 dashboard; CPU RPC and thermal policy remain local.
        const style = node('style',null,`
.mud-cpu{max-width:1200px;margin:0 auto;padding:4px 0 12px}
.mud-cpu .mud-cpu-title{margin:0 0 20px;padding:0 2px}
.mud-cpu .mud-cpu-title h2{margin:0 0 8px;padding:0;border:0;font-size:1.5rem;font-weight:650;letter-spacing:-.03em;color:var(--text,#222)}
.mud-cpu .mud-note{margin:0;color:var(--text-muted,#777);font-size:.77rem;line-height:1.65}
.mud-cpu .mud-cpu-section{padding:22px;margin:0 0 20px;overflow-wrap:anywhere}
.mud-cpu .mud-cpu-section:hover{border-color:var(--hairline,var(--border,#e3e6ea))}
.mud-cpu-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;margin-bottom:20px}
.mud-cpu-heading>div{min-width:0;flex:1}
.mud-cpu .mud-cpu-heading h3{margin:0 0 6px;padding:0;border:0;font-size:1rem;font-weight:650;letter-spacing:0;color:var(--text,#222)}
.mud-cpu-badge{flex-shrink:0;border:1px solid var(--hairline,#ddd);border-radius:99px;padding:4px 10px;color:var(--text-muted,#777);background:var(--surface-sunken,rgba(127,127,127,.05));font-size:.7rem;line-height:1.5}
.mud-cpu-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,260px),1fr));gap:14px;align-items:start}
.mud-cpu-cluster{min-width:0;padding:18px;border:1px solid var(--hairline,#ddd);border-radius:12px;background:color-mix(in srgb,var(--surface-sunken,#f4f5f7) 55%,var(--surface,#fff))}
.mud-cpu-cluster-head{display:flex;align-items:center;gap:10px;margin-bottom:18px}
.mud-cpu-cluster-head::before{content:'';width:8px;height:8px;border-radius:3px;background:var(--brand,#2f7bf6);opacity:.8;flex-shrink:0}
.mud-cpu .mud-cpu-cluster-head h4{font-size:.85rem;font-weight:650;letter-spacing:.015em;margin:0;padding:0;border:0;color:var(--text,#222)}
.mud-cpu-metric{display:flex;flex-direction:column;gap:4px;margin:0 0 20px}
.mud-cpu-metric>span{font-size:.72rem;color:var(--text-muted,#777)}
.mud-cpu-metric>div{display:flex;align-items:baseline;gap:7px;font-variant-numeric:tabular-nums;line-height:1.2}
.mud-cpu-metric strong{font-size:1.8rem;font-weight:650;letter-spacing:-.04em;color:var(--text,#222)}
.mud-cpu-metric small{font-size:.78rem;color:var(--text-muted,#777)}
.mud-cpu-field{display:flex;flex-direction:column;gap:7px;margin:0 0 14px;min-width:0;font-size:.75rem;color:var(--text-muted,#777)}
.mud-cpu .mud-cpu-field select,.mud-cpu .mud-cpu-field input{width:100%;max-width:none;min-width:0;box-sizing:border-box;margin:0;min-height:40px;padding:8px 10px;border:1px solid var(--hairline,#ddd);border-radius:8px;background:var(--surface,#fff);color:var(--text,#222);box-shadow:none;font-size:.84rem;font-variant-numeric:tabular-nums}
.mud-cpu .mud-cpu-field :disabled{opacity:.5;cursor:not-allowed}
.mud-cpu-range{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
.mud-cpu .mud-cpu-meta{font-size:.65rem;line-height:1.6;color:var(--text-subtle,var(--text-muted,#888));padding-top:10px;border-top:1px solid var(--hairline,#ddd);overflow-wrap:anywhere}
.mud-cpu-actions{display:flex;flex-wrap:wrap;gap:12px;align-items:center;justify-content:flex-end;padding-top:18px;margin-top:18px;border-top:1px solid var(--hairline,#ddd)}
.mud-cpu .mud-cpu-actions .mud-btn{min-height:38px;padding:8px 16px;line-height:1.5;white-space:normal;text-align:center}
.mud-cpu-persist{display:flex;gap:10px;align-items:flex-start;flex:1;min-width:min(100%,240px);margin:0;color:var(--text,#222);cursor:pointer}
.mud-cpu-persist input{margin:3px 0 0;flex-shrink:0;accent-color:var(--brand,#2f7bf6)}
.mud-cpu-persist>span{display:flex;flex-direction:column;gap:3px;max-width:620px;font-size:.8rem}
.mud-cpu-persist .mud-note{font-size:.7rem}
.mud-cpu .mud-cpu-warning{margin-top:16px;padding:12px 14px;border-left:2px solid var(--warning,#ad7420);border-radius:0 6px 6px 0;background:color-mix(in srgb,var(--warning,#ad7420) 5%,var(--surface,#fff));font-size:.7rem}
.mud-cpu .cpu-note{font-size:.75rem;line-height:1.65;color:var(--text-muted,#777);margin:12px 0;overflow-wrap:anywhere}
.mud-cpu .cpu-message{font-size:.8rem;line-height:1.65;margin-top:14px;overflow-wrap:anywhere}.mud-cpu .cpu-message.error{color:var(--danger,#df596a)}
.mud-cpu .cpu-current{font-variant-numeric:tabular-nums}.mud-cpu .cpu-thermal .cpu-current{font-size:1.5rem;font-weight:650;display:block;margin-bottom:18px}
.mud-cpu-table{border-top:1px solid var(--hairline,#ddd);margin-top:6px;padding-top:12px}
.mud-cpu-table>button{display:flex;align-items:center;justify-content:space-between;gap:12px;width:100%;cursor:pointer;font-size:.72rem;color:var(--text-muted,#777);line-height:1.6;padding:2px 0;border:0;border-radius:0;background:transparent;box-shadow:none;text-align:left;white-space:normal}
.mud-cpu-table>button::after{content:'↗';color:var(--brand,#2f7bf6);flex-shrink:0}
.mud-cpu-table>button:focus-visible{outline:2px solid var(--brand,#2f7bf6);outline-offset:2px}
.mud-dlg .mud-cpu-voltage-scroll{max-height:min(55vh,420px);overflow:auto;overscroll-behavior:contain;white-space:normal;margin-top:12px}
.mud-dlg .mud-cpu-voltage-table{width:100%;margin:0;border-collapse:collapse;font-size:.78rem;font-variant-numeric:tabular-nums;table-layout:fixed}
.mud-dlg .mud-cpu-voltage-table :is(td,th){padding:8px 10px;border:0;border-bottom:1px solid var(--hairline,#ddd);background:transparent;color:var(--text,#222);overflow-wrap:anywhere;text-align:left}
.mud-dlg .mud-cpu-voltage-table th{position:sticky;top:0;background:var(--surface,#fff);font-weight:600}
.mud-dlg .mud-cpu-voltage-table :is(td,th):last-child{text-align:right}
.mud-cpu .cpu-thermal-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,180px),1fr));gap:8px 18px}
.mud-cpu .mud-cpu-field :is(input,select):focus-visible{outline:2px solid var(--brand,#2f7bf6);outline-offset:2px}
@media(max-width:600px){.mud-cpu .mud-cpu-section{padding:16px}.mud-cpu-heading{flex-wrap:wrap;gap:8px;margin-bottom:16px}.mud-cpu-cluster{padding:16px}.mud-cpu-grid{grid-template-columns:minmax(0,1fr)}.mud-cpu-actions>.mud-cpu-persist{flex-basis:100%}.mud-cpu .mud-cpu-actions .mud-btn{flex:1}.mud-cpu .mud-cpu-title h2{font-size:1.3rem}}
`);
        this.root.append(style);
        this.content = node('div'); this.root.append(this.content);
        this.paint(state);
        poll.add(() => {
            if (!this.root.isConnected || document.hidden || this.busy) return Promise.resolve();
            return getCpu().then(s => {
                if (!s.ok) throw new Error(s.error || 'CPU unavailable');
                (s.policies || []).forEach(p => {
                    const el = this.root.querySelector('[data-current="'+p.id+'"]');
                    if (el) el.textContent = p.current == null ? '—' : p.current / 1000;
                    const limits = this.root.querySelector('[data-limits="'+p.id+'"]');
                    if (limits) limits.textContent = effectiveRange(p);
                    const voltage = this.root.querySelector('[data-voltage="'+p.id+'"]');
                    if (voltage) voltage.textContent = voltageNow(p);
                    const input = this.inputs.find(item => item.p.id === p.id);
                    if (input) input.p.voltages = p.voltages;
                });
                (s.zones || []).forEach(z => {
                    const el = this.root.querySelector('[data-temperature="'+z.id+'"]');
                    if (el) el.textContent = z.temp == null ? '—' : (z.temp / 1000).toFixed(1) + ' °C';
                });
            }).catch(e => this.message(e.message,true));
        },2);
        return this.root;
    },
    message: function(value,error) {
        this.messageBox.textContent = M.translate(value);
        this.messageBox.classList.toggle('error',!!error);
    },
    paint: function(s) {
        this.state = s;
        this.content.replaceChildren();
        this.inputs = []; this.thermalInputs = [];
        const head = node('div','mud-cpu-title');
        head.append(node('h2',null,text('CPU 设置','CPU settings')),
            node('p','mud-note',text('频率 · 电压 · 温控','Frequency · Voltage · Thermal')));
        this.content.append(head,Cores.render(),Idle.render());
        if (!s.ok || !s.available) this.content.append(node('div','mud-card',M.translate(s.error) || text('CPU 调频驱动尚未就绪','The CPU frequency driver is not ready')));
        const section = (title,badge) => {
            const card = node('section','mud-card mud-cpu-section'), head = node('div','mud-cpu-heading');
            head.append(node('h3',null,title),node('span','mud-cpu-badge',badge));card.append(head);
            return card;
        };
        const frequency = section(text('频率与调速策略','Frequency and governor'),text('即时生效','Applies immediately'));
        const voltageSection = section(text('电压设置','Voltage settings'),text('重启后生效','Applies after reboot'));
        const grid = node('div','cpu-grid mud-cpu-grid'), voltageGrid = node('div','mud-cpu-grid');
        frequency.append(grid); voltageSection.append(voltageGrid);
        if (!(s.policies || []).some(p=>p.voltage_boot_writable)) voltageSection.append(node('p','mud-note',
            s.voltage_unavailable_reason ? M.translate(s.voltage_unavailable_reason) : text('当前内核或固件不支持开机电压调整','Boot voltage adjustment is unavailable')));
        (s.policies || []).forEach(p => {
            const card = node('section','mud-cpu-cluster'), title = node('div','mud-cpu-cluster-head');
            const now = node('strong','cpu-current',p.current == null ? '—' : p.current/1000); now.dataset.current = p.id;
            const titleText = 'CPU '+p.cpus.trim().replace(/\s+/g,', ');
            title.append(node('h4',null,titleText));
            const metric = node('div','mud-cpu-metric'), value = node('div');
            value.append(now,node('small',null,'MHz'));metric.append(node('span',null,text('当前频率','Current frequency')),value);
            const governor = select(p.governors,p.governor), low = select(p.frequencies,p.min,mhz), high = select(p.frequencies,p.max,mhz);
            const writable=p.writable!==false && p.frequencies.length && p.governors.length && p.min != null && p.max != null;
            [governor,low,high].forEach(e=>{e.disabled=!writable;e.dataset.cpuReadonly=String(!writable);});
            governor.dataset.setting = p.id+'_governor'; low.dataset.setting = p.id+'_min'; high.dataset.setting = p.id+'_max';
            const range = node('div','mud-cpu-range');
            range.append(field(text('最低频率','Minimum frequency'),low),field(text('最高频率','Maximum frequency'),high));
            card.append(title,metric,field(text('调速器','Governor'),governor),range);
            const limits = node('p','cpu-note',effectiveRange(p)); limits.dataset.limits = p.id; card.append(limits);
            if (!this.inputs.length) frequency.append(node('p','cpu-note',text('schedutil 按负载调频；powersave 请求最低频率。上下限相同可固定频率，温控仍可降频。','schedutil follows load; powersave requests the minimum. Equal limits fix the requested frequency; thermal limits still apply.')));
            const voltageCard = node('section','mud-cpu-cluster'), voltageTitle = node('div','mud-cpu-cluster-head');
            voltageTitle.append(node('h4',null,titleText));voltageCard.append(voltageTitle);
            let voltage = null;
            if (p.voltage_boot_writable) {
                const values = [];
                for (let v = s.voltage_min; v <= s.voltage_max; v += s.voltage_step) values.push(v);
                voltage = select(values,p.voltage_next,offsetLabel);
                voltage.dataset.setting = p.id+'_voltage_next';
                const actual = node('p','cpu-note',voltageNow(p)); actual.dataset.voltage = p.id;
                voltageCard.append(field(text('下次启动电压偏移','Voltage offset on next boot'),voltage),actual,
                    node('p','cpu-note',text('保存后重启生效，CPU 与 SRAM 由固件同步调整。降压可能不稳定，建议每次只调一档；异常断电或崩溃后，下次启动自动恢复原厂电压。','Saved separately and applied after reboot. Firmware adjusts CPU and SRAM together. Undervolting can be unstable: change one step at a time. An unclean shutdown restores factory voltage on the next boot.')));
            }
            const tableAction = node('div','mud-cpu-table'), tableButton = node('button',null,text('查看频率与电压表','Frequency and voltage table'));
            tableButton.type = 'button'; tableButton.setAttribute('aria-haspopup','dialog');
            tableButton.onclick = () => {
                if (this.tableOpen) return;
                this.tableOpen = true;
                const scroll = node('div','mud-cpu-voltage-scroll'), table = node('table','mud-cpu-voltage-table');
                const head = node('thead'), header = node('tr'), body = node('tbody');
                ['MHz','mV'].forEach(unit => { const cell = node('th',null,unit); cell.scope = 'col'; header.append(cell); });
                head.append(header);
                (p.voltages || []).forEach(v => { const row = node('tr'); row.append(node('td',null,v.khz/1000),node('td',null,v.uv/1000)); body.append(row); });
                table.append(head,body); scroll.append(table);
                M.alertBox(text('查看频率与电压表','Frequency and voltage table')+' · '+titleText,
                    text('此表为当前生效的固件电压表。偏移作用于整个供电域，不能逐频点单独改压，也不新增超频档位。','The active firmware voltage table. Offsets apply to the whole domain; individual frequency edits and extra overclock states are unavailable.'),
                    {content:scroll}).finally(() => {
                        this.tableOpen = false;
                        if (tableButton.isConnected) tableButton.focus({preventScroll:true});
                    });
            };
            tableAction.append(tableButton); voltageCard.append(tableAction); voltageGrid.append(voltageCard); grid.append(card);
            this.inputs.push({p,governor,low,high,voltage});
        });
        this.content.append(frequency,voltageSection);
        const thermal = section(text('温控','Thermal'),text('即时生效','Applies immediately'));
        const thermalGrid = node('div','mud-cpu-grid');thermal.append(thermalGrid);
        if ((s.zones || []).length) this.content.append(thermal);
        (s.zones || []).forEach(z => {
            const card = node('section','mud-cpu-cluster cpu-thermal'), head = node('div','mud-cpu-cluster-head');
            const temp = node('span','cpu-current',z.temp == null ? '—' : (z.temp/1000).toFixed(1)+' °C'); temp.dataset.temperature=z.id;
            head.append(node('h4',null,z.name));card.append(head,temp);
            const fields = node('div','cpu-thermal-grid');
            const critical=z.trips.filter(t=>['critical','hot'].includes(t.type)).map(t=>t.temp/1000-10);
            z.trips.forEach(t => {
                if (t.writable) {
                    const input=node('input'); input.type='number';input.min=40;input.max=Math.min(100,...critical);input.step=1;input.value=t.temp/1000;
                    input.dataset.setting=z.id+'_trip'+t.id;
                    fields.append(field((t.throttles_cpu === false ? text('被动温控起点','Passive monitoring threshold') : text('降频触发温度','CPU throttling threshold'))+' (°C)',input));
                    this.thermalInputs.push({z,t,input});
                } else fields.append(node('div','cpu-note',(t.type==='critical'?text('过热关机保护','Critical shutdown'):t.type)+' · '+t.temp/1000+' °C'));
            });
            card.append(fields,node('p','cpu-note',text('被动温控起点用于更频繁地检测温度，达到降频触发温度才限制 CPU。阈值按顺序递增，原厂回差与过热关机保护保持生效。','Passive monitoring increases temperature checks; CPU throttling starts at the bound trip. Trips must increase in order. Factory hysteresis and critical shutdown remain active.')));thermalGrid.append(card);
        });
        const footer=node('div','cpu-footer mud-cpu-actions'),label=node('label','cpu-persist mud-cpu-persist');
        this.persist=node('input');this.persist.type='checkbox';this.persist.checked=!!s.persistent;
        label.append(this.persist,node('span',null,text('开机应用调频与温控','Apply frequency and thermal settings at boot')));
        const apply=node('button','mud-btn on',text('应用设置','Apply settings'));
        const reset=node('button','mud-btn',text('恢复默认','Restore defaults'));
        apply.disabled=!s.available;reset.disabled=!s.available;
        apply.onclick=()=>this.change(false);reset.onclick=()=>this.change(true);
        footer.append(label,apply,reset);this.content.append(footer,node('p','cpu-note',text('调频与温控可即时应用；电压设置独立保存，重启后生效。恢复默认后，电压也需要重启才能还原。关机充电始终使用原厂电压。','Frequency and thermal settings apply immediately; voltage settings are saved separately and need a reboot, including when restoring defaults. Charger-only boot uses factory voltage.')));
        this.messageBox=node('div','cpu-message');this.messageBox.setAttribute('role','status');this.content.append(this.messageBox);
        if (s.last_boot_error) this.message(text('上次开机配置未应用：','The boot profile was rejected: ')+s.last_boot_error,true);
        if (s.voltage_error) this.message(text('电压配置已回退：','Voltage profile reverted: ')+s.voltage_error,true);
        else if (s.voltage_reboot_required) this.message(text('电压配置已保存，重启后生效','Voltage settings saved; reboot to apply'));
    },
    change: async function(reset) {
        if(this.busy) return;
        try {
            const changes={policies:[],thermal:[]};
            if(!reset) {
                this.inputs.forEach(({p,governor,low,high,voltage})=>{
                    if(p.writable===false || !p.frequencies.length || !p.governors.length || p.min == null || p.max == null) return;
                    if(+low.value>+high.value) throw new Error(text('最低频率不能大于最高频率','Minimum frequency must not exceed maximum'));
                    const item={id:p.id,cpus:p.cpus,min:+low.value,max:+high.value,governor:governor.value};
                    if(voltage) item.voltage_next=+voltage.value;
                    changes.policies.push(item);
                });
                this.thermalInputs.forEach(({z,t,input})=>{
                    if(!input.checkValidity()) throw new Error(text('请填写有效的温度阈值','Enter a valid temperature threshold'));
                    changes.thermal.push({zone:z.name,trip:t.id,temp:+input.value*1000});
                });
            }
            this.busy=true;this.content.querySelectorAll('button,input,select').forEach(e=>{if(!e.closest('.mud-cpu-cores'))e.disabled=true;});
            const result=await (reset?resetCpu():applyCpu(changes,this.persist.checked));
            if(!result.ok) throw new Error(result.error||'Failed');
            this.paint(result);this.message(result.voltage_reboot_required ? text('调频与温控已应用；电压配置已保存，重启后生效','Frequency and thermal settings applied; reboot to apply saved voltage settings') : text('已应用，并读取确认当前设置','Applied and confirmed by kernel readback'));
        } catch(e) { this.message(e.message,true); }
        finally {this.busy=false;this.content.querySelectorAll('button,input,select').forEach(e=>{if(!e.closest('.mud-cpu-cores'))e.disabled=!this.state.available || e.dataset.cpuReadonly==='true';});}
    },
    handleSaveApply:null,handleSave:null,handleReset:null
});
