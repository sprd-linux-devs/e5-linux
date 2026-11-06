// Native E5 snapshot, adapted from the MU300/liuwang97 backport.
// ModemManager remains the sole owner of network, calls, SMS and URCs.
// No AT access, shell commands, configuration writes or private credentials.
import * as fs from 'fs';
import * as nl from 'nl80211';
import * as rt from 'rtnl';
import { statvfs } from 'luci.core';
import { cursor } from 'uci';
import { connect } from 'ubus';
import * as uloop from 'uloop';
import * as hotspot from '/usr/libexec/unisoc-modem/hotspot.uc';
import * as apn from '/usr/libexec/unisoc-modem/apn.uc';

const ROOT = getenv('MU300_DASH_SYSROOT') || '';
const CONFIG = getenv('MU300_DASH_CONFIG') || '/etc/config';
function rd(path) { return trim(fs.readfile(ROOT + path) || ''); }
function obj(path) { try { return json(rd(path)); } catch(e) { return null; } }
function num(v) { return v != null && match(''+v, /^-?[0-9]+(\.[0-9]+)?$/) ? +v : null; }
function text(v) { return v == null || v === '' ? null : replace(''+v,/[\r\n]/g,''); }
function device(v) { return type(v)=='string' && v!='.' && v!='..' && match(v,/^[A-Za-z0-9_.:-]{1,15}$/) ? v : null; }
function exists(p) { return fs.stat(ROOT+p)!=null; }
function executable(p) { return fs.access(ROOT+p,'x')==true; }
export function sim_state(slot) {
    if(!(slot in ['0','1']))return 'unknown';
    let row=obj('/run/t551m-sims.json')?.sims?.[int(slot)];
    let now=num(split(rd('/proc/uptime'),' ')[0]);
    // Reuse the existing per-slot collector; never query AT from an HTTP read.
    if(type(row)!='object' || row.slot!==int(slot) || (type(row.updated)!='double' && type(row.updated)!='int') ||
       now==null || now<row.updated || now-row.updated>15)return 'unknown';
    if(row.present===false && row.registration=='absent')return 'absent';
    if(row.present===true)return row.registration=='locked'?'locked':'ready';
    return 'unknown';
};
// Equipment identity is independent of SIM presence and the selected view.
// HTTP reads use RAM files; only this bounded background worker uses the AT owner.
let equipment_job=null;
function equipment(atd,slots) {
    let dir='/run/unisoc-modem-equipment', boot_id=rd('/proc/sys/kernel/random/boot_id');
    let valid=boot_id!='' && rd(dir+'/boot_id')==boot_id;
    let values=map(['0','1'],n=>valid && match(rd(dir+'/imei'+n),/^[0-9]{15}$/)?rd(dir+'/imei'+n):null);
    let stamp=fs.stat(ROOT+dir+'/attempt')?.mtime, age=stamp==null?null:time()-stamp;
    if(atd && boot_id!='' && !equipment_job && (values[0]==null || (slots=='2' && values[1]==null)) &&
       (!valid || age==null || age<0 || age>=60)) {
        equipment_job=uloop.process('/bin/sh',['/usr/libexec/unisoc-modem/dashboard-equipment'],{
            PATH:'/usr/sbin:/usr/bin:/sbin:/bin',MU300_EQUIPMENT_SLOTS:slots,T551M_AT_CHANNEL:'6'
        },()=>{equipment_job=null;});
    }
    return values;
};
function call(bus,o,m) { return bus?.call(o,m,{}) || {}; }
function net(dev) {
    dev=device(dev);
    if(!dev || !exists('/sys/class/net/'+dev))return null;
    let p='/sys/class/net/'+dev+'/';
    return {rx:num(rd(p+'statistics/rx_bytes')),tx:num(rd(p+'statistics/tx_bytes')),up:rd(p+'operstate')=='up'?1:0};
};
function address(rows,dev,global6) {
    for(let a in rows || []) if(a.dev==dev && a.address) {
        let s=replace(a.address,/\/.*/,'');
        if(!global6 || match(s,/^[23]/))return s;
    }
    return null;
};
export function power() {
    const base='/sys/class/power_supply';
    let battery=null, usb=null;
    let names=['battery','sc27xx-fgu',...(fs.lsdir(ROOT+base) || [])], seen={};
    for(let name in names) {
        if(seen[name])continue; seen[name]=true;
        let p=base+'/'+name, kind=rd(p+'/type');
        if(!battery &&
           (name=='battery' || name=='sc27xx-fgu' || kind=='Battery') &&
           rd(p+'/present')!='0') {
            let raw=rd(p+'/capacity'), cap=match(raw,/^[0-9]+$/)?+raw:null;
            if(cap!=null && cap>=0 && cap<=100)battery=p;
        }
        if(name in ['usb','ac','bq256xx-charger'] || match(kind,/^(USB|Mains)/)) {
            let on=num(rd(p+'/online'));
            if(on==1)usb=1; else if(on==0 && usb==null)usb=0;
        }
    }
    let volts=battery?num(rd(battery+'/voltage_now')):null;
    return {present:battery?1:0,capacity:battery?num(rd(battery+'/capacity')):null,
        status:battery?text(rd(battery+'/status')):null,
        volt:volts!=null && volts>0?+sprintf('%.2f',volts/1000000.0):null,
        ua:battery?num(rd(battery+'/current_now')):null,usb};
};
export function boot() {
    let state=rd('/etc/e5linux/default-boot') || 'android';
    if(!(state in ['android','linux']))state='unknown';
    let writable=executable('/opt/e5/e5-next-boot') &&
        (fs.stat(ROOT+'/run/e5linux/misc-bc-slot-b-trial.bin')?.size>0 ||
         fs.stat(ROOT+'/etc/e5linux/misc-bc-slot-b-trial.bin')?.size>0);
    if(match(rd('/proc/cmdline'),/(^| )e5\.openwrt=/))writable=false;
    return {default:state,temporary:state=='unknown'?null:state!='linux',can_set_default:!!writable};
};
function wifi_status(c,runtime) {
    let ap=hotspot.config(c), radio=runtime?.[ap.radio], live=null;
    for(let iface in radio?.interfaces || [])if(iface.section==ap.iface)live=iface;
    return {...ap,section:ap.iface,device:live?.ifname || null,enc:ap.encryption,
        up:ap.enabled && radio?.up && !!live,pending:!!radio?.pending,
        htmode:c.get('wireless',ap.radio,'htmode'),country:c.get('wireless',ap.radio,'country')};
};
function mm_cache() {
    let cache=obj('/run/e5-mm-state/state.json');
    if(cache?.boot_id!=rd('/proc/sys/kernel/random/boot_id') ||
       !match(''+cache?.pid,/^[1-9][0-9]*$/) || !exists('/proc/'+cache.pid))return {};
    return cache;
};
const metric_jobs={};
function valid_mac(mac) {
    return !!match(mac,/^([0-9a-f]{2}:){5}[0-9a-f]{2}$/) &&
        !(int(substr(mac,0,2),16)&1) && mac!='00:00:00:00:00:00';
};
function metrics(rows,dev) {
    let missing=filter(rows,r=>r.signal==null || !r.tx || !r.rx);
    if(!length(missing) || !match(dev,/^[A-Za-z0-9_.-]{1,15}$/))return;
    let index=rd('/sys/class/net/'+dev+'/ifindex');
    if(!match(index,/^[0-9]+$/))return;
    const key=dev+'-'+index;
    let cache=obj('/run/unisoc-wifi-metrics/'+key+'.json'), stamp=clock(true);
    let age=stamp[0]+stamp[1]/1000000000.0-(num(cache?.ts) ?? -5);
    if(age>=0 && age<5) {
        for(let row in rows) {
            let v=cache?.values?.[row.mac];
            if(type(v)!='array' || length(v)!=5 || v[0]!=row.mac)continue;
            let signal=num(v[1]);
            if(row.signal==null && signal!=null && signal>=-127 && signal<0)row.signal=signal;
            for(let k,idx in {tx:2,rx:3})
                if(!row[k] && type(v[idx])=='string' && match(v[idx],/^[0-9]+(\.[0-9]+)? Mbit\/s$/) && +split(v[idx],' ')[0]>0)
                    row[k]=v[idx];
        }
    } else if(!metric_jobs[key]) {
        // Retain the driver's existing one-second, flock-protected station-get
        // worker. It fills missing metrics only and never invents associations.
        metric_jobs[key]=uloop.process('/usr/libexec/e5-background',[
            '/usr/libexec/unisoc-modem/wifi-station-metrics','--kick',dev,
            ...map(slice(missing,0,32),r=>r.mac)
        ],{PATH:'/usr/sbin:/usr/bin:/sbin:/bin'},()=>{delete metric_jobs[key];});
    }
};
function clients(dev,bus,leases) {
    if(!device(dev) || !exists('/sys/class/net/'+dev))return {rows:[],count:0};
    let dump=nl.request(nl.const.NL80211_CMD_GET_STATION,nl.const.NLM_F_DUMP,{dev}), rows=[], seen={};
    // Drivers without station metrics still expose association through hostapd.
    // Both are sources in this single collector, never an alternate backend.
    for(let s in dump || []) {
        let mac=lc(s.mac || '');
        if(!valid_mac(mac) || seen[mac])continue;
        seen[mac]=true;
        let i=s.sta_info || {}, lease=leases[mac] || {};
        let rate=(r)=>(r?.bitrate32 ?? r?.bitrate)>0?sprintf('%g Mbit/s',(r.bitrate32 ?? r.bitrate)/10.0):null;
        let signal=num(i.signal);if(signal>127)signal-=256;
        if(signal==null || signal>=0 || signal < -127)signal=null;
        push(rows,{mac,host:lease.host,ip:lease.ip,signal,
            tx:rate(i.tx_bitrate),rx:rate(i.rx_bitrate),
            conn:i.connected_time!=null?sprintf('%d min',int(i.connected_time/60)):null});
    }
    if(!length(rows)) {
        let associated=call(bus,'hostapd.'+dev,'get_clients').clients;
        if(type(associated)=='object')dump=[];
        for(let original,client in type(associated)=='object'?associated:{}) {
            let mac=lc(original);
            if(!valid_mac(mac) || !(client?.assoc===true || client?.assoc===1))continue;
            let lease=leases[mac] || {};
            push(rows,{mac,host:lease.host,ip:lease.ip,signal:null,tx:null,rx:null,conn:null});
        }
    }
    metrics(rows,dev);
    return {rows,count:dump==null && !length(rows)?null:length(rows)};
};
export function conntrack() {
    let raw=rd('/proc/sys/net/netfilter/nf_conntrack_count');
    let scalar=match(raw,/^[0-9]+$/)?+raw:null;
    if(scalar!=null)return scalar;
    // Older kernels may expose only the table. Count it in bounded chunks,
    // as wc -l did, rather than allocating a potentially huge connection table.
    fs.error();
    let table=fs.open(ROOT+'/proc/net/nf_conntrack','r');
    if(!table)return null;
    let count=0;
    while(true) {
        let chunk=table.read(4096);
        if(chunk==null || chunk=='')break;
        count+=length(split(chunk,'\n'))-1;
    }
    let error=fs.error(); table.close();
    return error?null:count;
};

export function info(slot) {
    if(slot!=null && !(slot in ['0','1']))return {error:'Invalid SIM slot'};
    const c=cursor(CONFIG), bus=connect(null,2), now=time();
    function cfg(k,d) { return c.get('unisoc_modem','main',k) || d; }
    let iface=cfg('data_interface','wan'), iface6=cfg('data_interface_v6','wan6');
    let wan=match(iface,/^[A-Za-z0-9_]{1,32}$/)?call(bus,'network.interface.'+iface,'status'):{};
    let wan6=match(iface6,/^[A-Za-z0-9_]{1,32}$/)?call(bus,'network.interface.'+iface6,'status'):{};
    let data_slot=rd('/sys/module/sipc_wwan/parameters/card');
    let traffic_slot=slot in ['0','1']?slot:data_slot in ['0','1']?data_slot:null;
    let mobile=device(wan.l3_device || wan.device || cfg('data_device','sipa_eth0'));
    let viewing=slot==null || slot==data_slot;
    if(slot in ['0','1'] && !match(mobile || '',slot=='0'?/^sipa_eth[0-7]$/:/^sipa_eth([89]|1[0-5])$/))
        mobile=slot=='1'?'sipa_eth8':'sipa_eth0';
    let lan=device(cfg('lan_device','br-lan')), usb=device(cfg('usb_device','usb0'));
    let wifi=wifi_status(c,call(bus,'network.wireless','status'));
    let wd=device(wifi.device || cfg('wifi_device','wlan0'));
    let rows4=rt.request(rt.const.RTM_GETADDR,rt.const.NLM_F_DUMP,{family:rt.const.AF_INET});
    let rows6=rt.request(rt.const.RTM_GETADDR,rt.const.NLM_F_DUMP,{family:rt.const.AF_INET6});
    let leases=[], bymac={};
    for(let line in split(rd('/tmp/dhcp.leases'),'\n')) {
        let f=split(trim(line),/[ \t]+/);
        if(length(f)<4)continue;
        let row={host:f[3]=='*'?null:text(f[3]),ip:text(f[2]),mac:text(f[1]),left:max(0,(num(f[0]) || 0)-now)};
        push(leases,row); bymac[lc(f[1])]=row;
    }
    let stations=clients(wd,bus,bymac), hapd=wd?call(bus,'hostapd.'+wd,'get_status'):{};
    let cpu=split(split(rd('/proc/stat'),'\n')[0],/[ \t]+/), total=0;
    for(let i=1;i<=8;i++)total+=num(cpu[i]) || 0;
    let freqs=[];
    for(let p in fs.glob(ROOT+'/sys/devices/system/cpu/cpufreq/policy*') || []) {
        if(fs.readfile(p+'/scaling_cur_freq')==null)continue;
        push(freqs,{cur:num(trim(fs.readfile(p+'/scaling_cur_freq') || '')),max:num(trim(fs.readfile(p+'/cpuinfo_max_freq') || ''))});
    }
    let mem={};
    for(let line in split(rd('/proc/meminfo'),'\n')) {
        let m=match(line,/^(MemTotal|MemAvailable):[ \t]+([0-9]+)/);
        if(m)mem[m[1]]=+m[2];
    }
    let temps={soc:null,cpu:null,modem:null,board:null,hottest:null};
    let labels={'soc-thmzone':'soc','apcpu0-thmzone':'cpu','nr0-thmzone':'modem','board-thmzone':'board'};
    for(let z in fs.glob(ROOT+'/sys/class/thermal/thermal_zone*') || []) {
        let t=num(trim(fs.readfile(z+'/temp') || '')), kind=trim(fs.readfile(z+'/type') || '');
        if(t==null)continue;
        t=+sprintf('%.1f',t/1000.0);
        if(temps.hottest==null || t>temps.hottest)temps.hottest=t;
        if(labels[kind] && temps[labels[kind]]==null)temps[labels[kind]]=t;
    }
    let vfs=statvfs(ROOT || '/'), storage={total_kb:null,used_kb:null,avail_kb:null};
    if(vfs?.frsize)storage={total_kb:vfs.blocks*vfs.frsize/1024,used_kb:(vfs.blocks-vfs.bfree)*vfs.frsize/1024,avail_kb:vfs.bavail*vfs.frsize/1024};
    let release=match(rd('/etc/openwrt_release'),/DISTRIB_DESCRIPTION='([^']*)'/);
    let kernel=rd('/proc/sys/kernel/osrelease'), fw=release?release[1]:'Linux '+kernel;
    let private_fw=obj('/etc/unisoc-ota/current.json')?.version || rd('/etc/e5/image-version');
    if(private_fw)fw=private_fw+' ('+fw+')';
    let cached=mm_cache();
    let identity=cached.sim?.slot==data_slot?cached.sim:{};
    let selection=apn.status(c,identity), selected_apn=null;
    if(selection.ok && (slot==null || ''+selection.data_sim==slot) && selection.source in ['sim','auto','network','default'] &&
       type(selection.apn)=='string' && length(selection.apn)<=100 && !match(selection.apn,/[^A-Za-z0-9.-]/))
        selected_apn=selection.apn || '(SIM default)';
    let dns=[];
    for(let w in [wan,wan6])for(let ip in w['dns-server'] || [])if(index(dns,ip)<0)push(dns,ip);
    let atd=exists('/run/t551m-at2/cmd.sock') && index(rd('/proc/net/unix'),'/run/t551m-at2/cmd.sock')>=0;
    let ht=replace(wifi.htmode || '',/[^0-9]/g,'');
    return {ts:now,uptime:int(rd('/proc/uptime')),host:text(c.get('system','@system[0]','hostname') || rd('/proc/sys/kernel/hostname')),
        model:text(rd('/tmp/sysinfo/model') || replace(rd('/proc/device-tree/model'),/\x00/g,'')),fw,kernel,
        cpu:{n:length(filter(split(rd('/proc/cpuinfo'),'\n'),line=>!!match(line,/^processor[ \t]*:/))),total,idle:(num(cpu[4]) || 0)+(num(cpu[5]) || 0),freqs},
        mem:{total_kb:mem.MemTotal ?? null,avail_kb:mem.MemAvailable ?? null},storage,temps,power:power(),
        net:{mobile:net(mobile),sipa_eth0:net(mobile),brlan:net(lan),wlan0:net(wd),usb0:net(usb)},
        wan:{up:viewing && wan.up?1:0,uptime:viewing?(wan.uptime ?? null):0,proto:viewing?text(wan.proto):null,device:mobile,apn:viewing?selected_apn:null,
            ip4:viewing?(wan['ipv4-address']?.[0]?.address ?? null):null,ip6:viewing?address(rows6,mobile,true):null,dns:viewing?text(join(', ',dns)):null},
        wifi:{available:wifi.available?1:0,enabled:wifi.enabled?1:0,pending:wifi.pending?1:0,section:text(wifi.section),radio:text(wifi.radio),
            error:text(wifi.error),up:wifi.up && hapd.status=='ENABLED' && exists('/sys/class/net/'+wd)?1:0,
            ssid:text(wifi.ssid),channel:text(wifi.channel),band:text(wifi.band),width:ht?substr(ht,0,2)+' MHz':null,
            country:text(wifi.country),enc:wifi.enc || 'none',hidden:wifi.hidden ?? null,hostapd:hapd.status=='ENABLED'?1:0,
            clients:stations.rows,clients_n:stations.count},
        lan:{leases:length(leases),ip:address(rows4,lan,false),list:leases},
        modem:{alive:cached.alive && exists('/dev/wwan0at0')?1:0,atd:atd?1:0,data_paused:!viewing || !wan.up?1:0,viewing_data_sim:viewing?1:0,data_sim:data_slot in ['0','1']?int(data_slot):null,
            imeis:equipment(atd,'2'),sims:map(['0','1'],n=>({slot:int(n),state:atd?sim_state(n):'unknown'}))},
        boot:boot(),capabilities:{dualboot:executable('/opt/e5/e5-next-boot')?1:0},
        conns:conntrack(),traffic:traffic_slot==null?null:obj('/run/unisoc-modem-traffic/view-sim'+traffic_slot+'.json')};
};

export function rates(slot) {
    slot=slot || rd('/sys/module/sipc_wwan/parameters/card');
    if(!(slot in ['0','1']))return {error:'Invalid SIM slot'};
    let base=slot=='1'?8:0, dev='sipa_eth'+base, stamp=num(split(rd('/proc/uptime'),' ')[0]);
    if(stamp==null)return {error:'Clock unavailable'};
    let reply={card:int(slot),ts:stamp,device:dev,net:null};
    let idx=num(rd('/sys/class/net/'+dev+'/ifindex'));
    if(idx==null)return reply;
    let rx=0,tx=0;
    for(let offset=0;offset<8;offset++) {
        let path='/sys/class/net/sipa_eth'+(base+offset);
        if(!exists(path))continue;
        let r=num(rd(path+'/statistics/rx_bytes')),t=num(rd(path+'/statistics/tx_bytes'));
        if(r==null || t==null)return reply;
        if(r<0 || t<0)return {error:'Counters unavailable'};
        rx+=r;tx+=t;
    }
    return {...reply,ifindex:idx,net:{rx,tx}};
};

// Both cards share the native inbox. Its inode changes on every atomic save.
export function sms_head() {
    let state=fs.stat(ROOT+'/etc/e5-sms/inbox.json');
    return {source:'e5-sms',signature:state?join(':',[state.dev.major,state.dev.minor,state.inode,state.size,state.mtime]):'empty'};
};

const workers={};
function age(path) { let s=fs.stat(ROOT+path); return s?.size>0?time()-s.mtime:-1; }
function owner(dir) {
    let pid=rd(dir+'/pid');
    return match(pid,/^[1-9][0-9]*$/) && exists('/proc/'+pid) &&
        !!match(join(' ',split(rd('/proc/'+pid+'/cmdline'),'\x00')),/unisoc-modem\/cell/);
};
export function status(slot,cells) {
    slot=slot || rd('/sys/module/sipc_wwan/parameters/card');
    if(!(slot in ['0','1']))return {error:'Invalid SIM slot'};
    let dir='/tmp/unisoc-modem/sim'+slot, cage=age(dir+'/cell.json'), sage=age(dir+'/sig.json');
    let busy=!!workers[slot+':full'] || exists('/run/unisoc-modem-lock-apply') || owner(dir+'/collect.lck');
    let fast=busy || !!workers[slot+':fast'] || owner(dir+'/fast.lck');
    let mode=cage<0 || cage>=5?'full':!cells && (sage<0 || sage>=1)?'fast':null;
    let failed=false;
    if(mode && !(mode=='full'?busy:fast)) {
        let key=slot+':'+mode;
        // Preserve E5's engineering parser, slot addressing and command order.
        workers[key]=uloop.process('/usr/libexec/e5-background',['/usr/libexec/unisoc-modem/cell',mode],{
            PATH:'/usr/sbin:/usr/bin:/sbin:/bin:/opt/e5',
            MU300_SIM_SLOT:slot,MU300_DASH_DIR:dir
        },()=>{delete workers[key];});
        failed=!workers[key];
        if(mode=='full' && !failed)busy=true;
    }
    return {info:cells?null:info(slot),cell:failed?{error:'Unable to read cellular status'}:obj(dir+'/cell.json'),
        sig:failed?{error:'Unable to read cellular status'}:obj(dir+'/sig.json'),cell_age:cage,sig_age:sage,refreshing:busy?1:0};
};
