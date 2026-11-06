#!/usr/bin/env python3
"""Compile the actual patched C functions with deterministic fault injection.

Usage: python3 devices/common/test_sipa.py /path/to/linux-lts-e5
No device access, modem commands or kernel loading.
"""
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
scope = runpy.run_path(str(HERE/'sipa.py'))
apply = scope['apply']


def function(source, name):
    import re
    match = re.search(r'(?m)^(?:static )?(?:int|void|bool|netdev_tx_t)\s+' + name + r'\([^;{}]*\)\s*\{', source)
    assert match, name
    start = source.index('{', match.start())
    end, depth = start + 1, 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[match.start():end]


PRELUDE = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <errno.h>
#define likely(x) (x)
#define unlikely(x) (x)
#define pr_err_ratelimited(...) ((void)0)
#define dev_warn_ratelimited(...) ((void)0)
#define dev_err_ratelimited(...) ((void)0)
typedef uint16_t u16;
typedef uint32_t u32;
static int held;
#define spin_lock_irqsave(lock, flags) do { (void)(lock); (flags)=0; assert(!held); held=1; } while(0)
#define spin_unlock_irqrestore(lock, flags) do { (void)(lock); (void)(flags); assert(held); held=0; } while(0)
'''

POWER_STUBS = r'''
#define SMSG_FLG_DELE_ENABLE 7
#define SMSG_FLG_DELE_DISABLE 8
#define SMSG_VAL_DELE_REQ_SUCCESS 0
#define SMSG_VAL_DELE_REQ_FAIL 1
struct config { int sipa_sys_eb; };
struct sipa_delegator { struct config *cfg; bool pd_get_flag, pd_eb_flag; int pdev, power_lock; };
static int pm_result, hal_result, pm_gets, pm_refs, awake, enables, ipa_refs, last_ack, acks;
static void mutex_lock(int *lock) { assert(!*lock); *lock=1; }
static void mutex_unlock(int *lock) { assert(*lock); *lock=0; }
static int pm_runtime_resume_and_get(int dev) { (void)dev; pm_gets++; if(pm_result>=0)pm_refs++; return pm_result<0?pm_result:0; }
static void pm_runtime_put(int dev) { (void)dev; assert(pm_refs>0); pm_refs--; }
static void pm_stay_awake(int dev) { (void)dev; awake++; }
static void pm_relax(int dev) { (void)dev; assert(awake>0); awake--; }
static int sipa_set_enabled(bool on) { if(on){enables++;ipa_refs++;return hal_result;} assert(ipa_refs>0);ipa_refs--;return 0; }
static void sipa_dele_start_done_work(struct sipa_delegator *d, int flag, int value) { (void)d; assert(flag==7); last_ack=value; acks++; }
static void sipa_dele_on_commad(void *priv, u16 flag, u32 data) { (void)priv;(void)flag;(void)data; }
'''
POWER_MAIN = r'''
int main(void) {
 for(int runtime=0;runtime<=1;runtime++) {
  struct config cfg={runtime}; struct sipa_delegator d={.cfg=&cfg};
  pm_result=1; hal_result=0; pm_gets=pm_refs=awake=enables=ipa_refs=acks=0;
  cp_dele_on_commad(&d,7,0); cp_dele_on_commad(&d,7,0);
  assert(d.pd_get_flag && d.pd_eb_flag && ipa_refs==1 && enables==1 && acks==2 && last_ack==0);
  assert(pm_gets==runtime && pm_refs==runtime && awake==!runtime);
  cp_dele_on_commad(&d,8,0); cp_dele_on_commad(&d,8,0);
  assert(!d.pd_get_flag && !d.pd_eb_flag && !ipa_refs && !pm_refs && !awake);
  hal_result=-EIO;
  cp_dele_on_commad(&d,7,0);
  assert(last_ack==1 && !d.pd_get_flag && !d.pd_eb_flag && !ipa_refs && !pm_refs && !awake);
  hal_result=0;pm_result=-EIO;int previous=enables;
  if(runtime) {
   cp_dele_on_commad(&d,7,0);
   assert(enables==previous && last_ack==1 && !pm_refs && !ipa_refs);
  }
 }
 puts("PASS: both power policies, duplicate enable/disable, positive PM success, PM/HAL failures and balanced references");
}
'''

TX_STUBS = r'''
#define NETDEV_TX_OK 0
#define NETDEV_TX_BUSY 16
#define DEV_ON 1
#define CHECKSUM_PARTIAL 1
#define ETH_HLEN 14
#define ETH_P_IP 0x800
#define ETH_P_IPV6 0x86dd
#define IPPROTO_TCP 6
#define IPPROTO_UDP 17
#define NEXTHDR_TCP 6
#define NEXTHDR_UDP 17
#define htons(x) (x)
#define pr_err(...) ((void)0)
typedef unsigned short __sum16;
typedef int netdev_tx_t;
struct sk_buff { unsigned len, headroom; int mac_header, network_header, protocol, ip_summed;
 unsigned char padding[14]; };
struct ethhdr { unsigned char addresses[12]; unsigned short h_proto; };
#include <string.h>
struct net_device_stats { unsigned tx_dropped,tx_errors,tx_packets,tx_bytes; };
struct sipa_eth_init_data { int netid, src_id; };
struct sipa_eth { struct sipa_eth_init_data *pdata; struct net_device_stats *stats; int state,nic_id; };
struct net_device { struct sipa_eth *priv; const char *name; bool stopped; };
struct iphdr { int protocol; }; struct ipv6hdr { int nexthdr; }; struct transport { __sum16 check; };
static struct iphdr fake_ipv4;static struct ipv6hdr fake_ipv6;static struct transport tcp,udp;
#define ip_hdr(s) (&fake_ipv4)
#define ipv6_hdr(s) (&fake_ipv6)
#define tcp_hdr(s) (&tcp)
#define udp_hdr(s) (&udp)
static int queue_lock, next_result, linearize_result, cow_result, recovery, freed;
static void *netdev_priv(struct net_device *d){return d->priv;}
static int skb_linearize(struct sk_buff *s){(void)s;return linearize_result;}
static int skb_cow_head(struct sk_buff *s,unsigned n){if(cow_result)return cow_result;if(s->headroom<n)s->headroom=n;return 0;}
static unsigned skb_headroom(struct sk_buff *s){return s->headroom;}
static void dev_kfree_skb_any(struct sk_buff *s){(void)s;freed++;}
static void *skb_push(struct sk_buff *s,unsigned len){assert(s->headroom>=len);s->headroom-=len;s->len+=len;return s->padding;}
static void skb_pull(struct sk_buff *s,unsigned len){s->headroom+=len;s->len-=len;}
static int sipa_nic_tx(int nic,int src,int netid,struct sk_buff *s){
 (void)nic;(void)src;(void)netid;
 if(s->mac_header==s->network_header){
  for(int i=0;i<12;i++)assert(s->padding[i]==0);
  assert(((struct ethhdr *)s->padding)->h_proto==s->protocol);
 }
 return next_result;
}
static bool sipa_nic_check_flow_ctrl(int nic){(void)nic;assert(held);return next_result==-EINPROGRESS;}
static void netif_stop_queue(struct net_device *d){assert(held);d->stopped=true;}
static void sipa_nic_trigger_flow_ctrl_work(int nic,int error){(void)nic;(void)error;assert(!held);recovery++;}
'''
TX_MAIN = r'''
int main(void) {
 struct sipa_eth_init_data pdata={0};struct net_device_stats stats={0};
 struct sipa_eth eth={.pdata=&pdata,.stats=&stats,.state=DEV_ON};
 struct net_device dev={.priv=&eth,.name="test"};
 struct sk_buff skb={.len=100,.headroom=64};
 for(int ipv6=0;ipv6<2;ipv6++) for(int is_tcp=0;is_tcp<2;is_tcp++)
 for(int raw=0;raw<2;raw++) for(int partial=0;partial<2;partial++) {
  skb=(struct sk_buff){.len=100,.headroom=64,.network_header=raw?0:14,
   .protocol=ipv6?ETH_P_IPV6:ETH_P_IP,.ip_summed=partial?CHECKSUM_PARTIAL:0};
  memset(skb.padding,0xa5,sizeof(skb.padding));
  fake_ipv4.protocol=fake_ipv6.nexthdr=is_tcp?IPPROTO_TCP:IPPROTO_UDP;
  tcp.check=0x1234;udp.check=0x5678;int previous_recovery=recovery;
  for(int i=0;i<50;i++) {
   next_result=i&1?-EINPROGRESS:-EAGAIN;
   assert(sipa_eth_start_xmit(&skb,&dev)==NETDEV_TX_BUSY);
   assert(skb.len==100 && skb.headroom==64 && recovery==previous_recovery+i+1 && dev.stopped && !freed);
   assert(tcp.check==0x1234 && udp.check==0x5678);
   assert(!stats.tx_dropped && !stats.tx_errors);
  }
  next_result=0;assert(sipa_eth_start_xmit(&skb,&dev)==NETDEV_TX_OK);
  assert((is_tcp?tcp.check:udp.check)==(partial?0:(is_tcp?0x1234:0x5678)));
  assert(skb.len==(raw?114:100));
 }
 assert(stats.tx_packets==16 && stats.tx_bytes==1600 && !freed);
 skb.len=100;skb.headroom=64;linearize_result=-ENOMEM;
 assert(sipa_eth_start_xmit(&skb,&dev)==NETDEV_TX_OK && freed==1 && stats.tx_dropped==1);
 linearize_result=0;cow_result=-ENOMEM;skb.mac_header=skb.network_header=0;
 assert(sipa_eth_start_xmit(&skb,&dev)==NETDEV_TX_OK && freed==2 && stats.tx_dropped==2);
 cow_result=0;skb.headroom=0;next_result=0;
 assert(sipa_eth_start_xmit(&skb,&dev)==NETDEV_TX_OK&&skb.len==114&&!skb.headroom);
 puts("PASS: 16 protocol/header/checksum combinations, 50 retries each preserve geometry and checksum seed, balanced recovery and consumption");
}
'''

COMPLETION_STUBS = r'''
#define SIPA_LEAVE_FLOWCTRL 1
struct sipa_node_desc_tag { int match;unsigned err_code,src,dst,net_id,length; };
struct fifo { int idx; struct {int fifo_depth;} rx_fifo; };
struct endpoint { struct fifo send_fifo; };
struct sipa_skb_sender { int dev,left_cnt;unsigned completion_error_cnt;bool free_notify_net;struct endpoint *ep; };
struct sipa_plat_drv_cfg { struct sipa_skb_sender *sender; };
static struct endpoint ep={.send_fifo.rx_fifo.fifo_depth=8};
static struct sipa_skb_sender sender={.ep=&ep};
static struct sipa_plat_drv_cfg ipa={.sender=&sender};
static struct sipa_node_desc_tag nodes[4];
static int count, advanced, null_at=-1, freed, notified;
static struct sipa_plat_drv_cfg *sipa_get_ctrl_pointer(void){return &ipa;}
static void sipa_hal_cmn_fifo_get_filled_depth(int dev,int idx,void *rx,u32 *num){(void)dev;(void)idx;(void)rx;*num=count;}
static void sipa_hal_sync_node_from_tx_fifo(int dev,int idx,u32 num){(void)dev;(void)idx;(void)num;}
static struct sipa_node_desc_tag *sipa_hal_get_tx_node_rptr(int dev,int idx,u32 i){(void)dev;(void)idx;return (int)i==null_at?NULL:&nodes[i];}
static bool sipa_do_free_skb(struct sipa_node_desc_tag *node){if(node->match){freed++;return true;}return false;}
static void sipa_hal_add_tx_fifo_rptr(int dev,int idx,u32 num){(void)dev;(void)idx;advanced+=num;}
static void atomic_add(int n,int *p){*p+=n;}
static int atomic_read(int *p){return *p;}
static void sipa_inform_evt_to_nics(struct sipa_skb_sender *s,int evt){(void)s;(void)evt;notified++;}
'''
COMPLETION_MAIN = r'''
int main(void) {
 count=3;nodes[0].match=0;nodes[1].match=nodes[2].match=1;
 sender.left_cnt=1;sender.free_notify_net=true;sipa_free_sent_items();
 assert(advanced==3 && freed==2 && sender.left_cnt==3 && notified==1 && !sender.free_notify_net);
 advanced=freed=0;sender.left_cnt=0;null_at=1;nodes[0].match=1;sipa_free_sent_items();
 assert(advanced==1 && freed==1 && sender.left_cnt==1);
 count=0;advanced=freed=0;sipa_free_sent_items();assert(!advanced && !freed);
 count=1;null_at=-1;nodes[0].match=1;
 for(unsigned error=1;error<16;error++){
  nodes[0].err_code=error;sipa_free_sent_items();
  assert(sender.completion_error_cnt==error);
 }
 assert(advanced==15&&freed==15);
 puts("PASS: unmatched completion cannot discard later buffers, credits count reclaimed buffers, null node advances only consumed prefix");
}
'''

HANDSHAKE_STUBS = r'''
#define pr_info(...) ((void)0)
#define pr_debug(...) do { if (0) printf(__VA_ARGS__); } while (0)
#define SMSG_FLG_DELE_REQUEST 1
#define SMSG_VAL_DELE_REQ_FAIL 1
#define SIPA_RM_EVT_GRANTED 1
enum sipa_dele_state { SIPA_DELE_ACTIVE,SIPA_DELE_REQUESTING,SIPA_DELE_RELEASING,SIPA_DELE_RELEASED,SIPA_DELE_POWER_OFF };
struct sipa_delegator { enum sipa_dele_state stat;int lock,prod_id,smsg_wq,notify_work;bool connected; };
static int releases,requests,grants;
static void sipa_dele_start_rls_work(struct sipa_delegator *d){(void)d;releases++;}
static void sipa_dele_start_req_work(struct sipa_delegator *d){(void)d;requests++;}
static void sipa_rm_notify_completion(int event,int id){(void)event;(void)id;grants++;}
static void queue_work(int queue,int *work){(void)queue;(void)work;}
'''
HANDSHAKE_MAIN = r'''
int main(void) {
 struct sipa_delegator d={.stat=SIPA_DELE_REQUESTING,.connected=true};
 assert(sipa_dele_local_rls_r_prod(&d)==-EINPROGRESS);
 assert(d.stat==SIPA_DELE_RELEASING && releases==0);
 sipa_dele_on_done(&d,1,0);
 assert(d.stat==SIPA_DELE_RELEASED && releases==1);
 sipa_dele_on_done(&d,1,0);assert(releases==1);
 d.stat=SIPA_DELE_REQUESTING;releases=0;
 assert(sipa_dele_local_rls_r_prod(&d)==-EINPROGRESS);
 assert(sipa_dele_local_req_r_prod(&d)==-EINPROGRESS);
 sipa_dele_on_done(&d,1,0);
 assert(d.stat==SIPA_DELE_ACTIVE && !releases && grants==1);
 puts("PASS: release waits for request ACK, no duplicate release, renewed request keeps the grant");
}
'''


EVENT_STUBS = r'''
#define SIPA_HAL_TXFIFO_FULL_INT 0x40000
#define SIPA_HAL_TXFIFO_OVERFLOW 0x20000
#define SIPA_HAL_ERRORCODE_IN_TX_FIFO 0x10000
#define SIPA_HAL_ENTER_FLOW_CTRL 0x80000
#define SIPA_HAL_EXIT_FLOW_CTRL 0x100000
#define SIPA_RECV_WARN_EVT 0x70000
#define SIPA_RECV_EVT 0x8000
enum sipa_hal_evt_type {NO_EVENT=0};
struct ep {int id;};
struct sipa_skb_sender {int dev,no_free_cnt,free_waitq,enter_flow_ctrl_cnt,exit_flow_ctrl_cnt;struct ep *ep;};
static int wakeups;
static void wake_up(int *p){(void)p;wakeups++;}
'''
EVENT_MAIN = r'''
int main(void){
 struct ep ep={1};struct sipa_skb_sender s={.ep=&ep};
 sipa_sender_notify_cb(&s,SIPA_HAL_ERRORCODE_IN_TX_FIFO,0,0);
 assert(s.no_free_cnt==0&&wakeups==1);
 sipa_sender_notify_cb(&s,SIPA_HAL_TXFIFO_FULL_INT,0,0);
 assert(s.no_free_cnt==1&&wakeups==2);
 sipa_sender_notify_cb(&s,SIPA_HAL_TXFIFO_OVERFLOW|SIPA_HAL_ERRORCODE_IN_TX_FIFO,0,0);
 assert(s.no_free_cnt==2&&wakeups==3);
 sipa_sender_notify_cb(&s,SIPA_HAL_ENTER_FLOW_CTRL|SIPA_HAL_EXIT_FLOW_CTRL,0,0);
 assert(s.enter_flow_ctrl_cnt==1&&s.exit_flow_ctrl_cnt==1);
 puts("PASS: packet rejection is not FIFO pressure; completions and real queue faults still wake the reclaimer");
}
'''


def main():
    kernel = Path(sys.argv[1]).resolve()
    patch = HERE/'sipa-data-path.patch'
    paths = sorted({line[6:] for item in scope['PATCHES'] for line in item.read_text().splitlines()
                    if line.startswith('+++ b/')})
    with tempfile.TemporaryDirectory(prefix='sipa-regression-') as directory:
        root = Path(directory)
        for name in paths:
            target = root/name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(subprocess.check_output(['git','-c','safe.directory='+str(kernel),'-C',str(kernel),'show','HEAD:'+name]))
        original = {name:(root/name).read_bytes() for name in paths}
        apply(root)
        before = {name:(root/name).read_bytes() for name in paths}
        apply(root)
        assert before == {name:(root/name).read_bytes() for name in paths}, 'Not idempotent'
        # Incremental builders already contain the previous public SIPA patch.
        # Upgrading them must produce exactly the same source as a clean build.
        for name,data in original.items():
            (root/name).write_bytes(data)
        subprocess.run(['git','apply','--whitespace=nowarn',str(patch)],cwd=root,check=True)
        previous_tx = (root/'drivers/unisoc_platform/net/sipa_v3/sipa_eth.c').read_text()
        apply(root)
        assert before == {name:(root/name).read_bytes() for name in paths}, 'Old patched tree upgrade differs'
        sources = {Path(name).name:(root/name).read_text() for name in paths}
        runpy.run_path(str(HERE/'test_sipa_flow.py'))['run'](root/'drivers/unisoc_platform/net/sipa_v3')
        cp = sources['sipa_dele_cp_in_ap.c']
        assert cp.index('mutex_init(') < cp.index('ret = sipa_delegator_start(') < cp.index('wake_up_process(')
        assert 'wake_up_process(' not in sources['sipa_dele_cmn.c']
        for name, stubs, body, tail in [
            ('power', POWER_STUBS, function(cp,'cp_dele_on_commad'), POWER_MAIN),
            ('backpressure', TX_STUBS, function(sources['sipa_eth.c'],'sipa_eth_start_xmit'), TX_MAIN),
            ('completion', COMPLETION_STUBS, function(sources['sipa_skb_send.c'],'sipa_free_sent_items'), COMPLETION_MAIN),
            ('events', EVENT_STUBS, function(sources['sipa_skb_send.c'],'sipa_sender_notify_cb'), EVENT_MAIN),
            ('handshake', HANDSHAKE_STUBS, '\n'.join(function(sources['sipa_dele_cmn.c'],name) for name in (
                'sipa_dele_local_rls_r_prod','sipa_dele_local_req_r_prod','sipa_dele_on_done')), HANDSHAKE_MAIN),
        ]:
            source = root/(name+'.c')
            source.write_text(PRELUDE+stubs+body+tail)
            executable = root/name
            subprocess.run(['cc','-std=gnu11','-Wall','-Werror','-Wno-unused-variable',
                            '-fsanitize=address,undefined','-fno-pie','-no-pie',
                            str(source),'-o',str(executable)],check=True)
            subprocess.run([str(executable)],check=True)
        source = root/'old-backpressure.c'
        source.write_text(PRELUDE+TX_STUBS+function(previous_tx,'sipa_eth_start_xmit')+TX_MAIN)
        # The old function uses the shared flags variable; include its test
        # stand-in solely for this before/after executable comparison.
        source.write_text(source.read_text().replace('static int queue_lock,',
                                                    'static int queue_lock_flags, queue_lock,'))
        executable = root/'old-backpressure'
        subprocess.run(['cc','-std=gnu11','-Wno-unused-variable',str(source),'-o',str(executable)],check=True)
        result = subprocess.run([str(executable)],capture_output=True)
        assert result.returncode != 0 and b'tcp.check==0x1234 && udp.check==0x5678' in result.stderr, result.stderr
        broken = root/'drivers/unisoc_platform/net/sipa_delegate/sipa_dele_cp_in_ap.c'
        broken.write_text(broken.read_text().replace('mutex_lock(&delegator->power_lock);','changed_vendor_function();',1))
        before = {name:(root/name).read_bytes() for name in paths}
        try: apply(root)
        except ValueError: pass
        else: raise AssertionError('Unsupported mixed patch state accepted')
        assert before == {name:(root/name).read_bytes() for name in paths}
        print('PASS: original checksum-loss reproduced; clean/old/current patch states converge, startup ordering and changed-source rejection')


if __name__ == '__main__': main()
