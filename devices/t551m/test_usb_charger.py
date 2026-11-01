#!/usr/bin/env python3
"""Run the generated USB IRQ/work handlers against a fake register/event bus."""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

kernel = Path(sys.argv[1])
typec = (kernel / 'drivers/usb/typec/sc27xx_typec.c').read_text()
bc = (kernel / 'drivers/usb/phy/sprd-bc1p2.c').read_text()


def function(source, name):
    found = re.search(r'(?:static )?(?:void|int|irqreturn_t) ' + name + r'\([^;{}]*\)\s*\{', source)
    assert found, name
    index, depth = found.end(), 1
    while depth:
        depth += (source[index] == '{') - (source[index] == '}')
        index += 1
    return source[found.start():index]


prelude = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
typedef uint32_t u32;
typedef int irqreturn_t;
#define IRQ_NONE 0
#define IRQ_HANDLED 1
#define SC27XX_INT_MASK 0x18
#define SC27XX_STATUS 0x1c
#define SC27XX_TYPEC_DBG1 0x60
#define SC27XX_TYPEC_DBG2 0x64
#define SC27XX_ATTACH_INT 1
#define SC27XX_DETACH_INT 2
#define SC27XX_ERR_IN_INT 4
#define USB_CHARGER_ABSENT 0
#define USB_CHARGER_PRESENT 1
#define UNKNOWN_TYPE 0
#define SDP_TYPE 1
#define DCP_TYPE 2
#define CHARGER_DETECT_DONE 1
#define CHG_STATE_UNDETECT 0
#define CHG_STATE_DETECTED 2
#define SPRD_CHG_DETECT_DELAY 500
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x,v) ((x)=(v))
#define EXTCON_USB 1
static void extcon_sync(void *edev,int cable) {(void)edev;(void)cable;}
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define spin_lock_irqsave(p,f) ((void)(p),(f)=0)
#define spin_unlock_irqrestore(p,f) ((void)(p),(void)(f))
#define mutex_lock(p) ((void)(p))
#define mutex_unlock(p) ((void)(p))
#define dev_info(...) ((void)0)
#define dev_warn(...) ((void)0)
#define pr_err(...) ((void)0)
#define TYPEC_PORT_UFP 1
#define TYPEC_PORT_DFP 0
#define TYPEC_PORT_DRP 2
struct device_node { bool available,legacy; const char *role; struct device_node *extcon; };
static struct device_node controller;
#define for_each_node_with_property(node,prop) for ((node)=strcmp(prop,controller.legacy?"dr-mode":"dr_mode")?NULL:&controller;(node);(node)=NULL)
static bool of_device_is_available(struct device_node *node) { return node->available; }
static struct device_node *of_parse_phandle(struct device_node *node,const char *prop,int index) { return node->extcon; }
static void of_node_put(struct device_node *node) {}
static int of_property_read_string(struct device_node *node,const char *prop,const char **out) { *out=node->role;return *out ? 0 : -1; }
enum usb_charger_state { FAKE_USB_ABSENT = 0, FAKE_USB_PRESENT = 1 };
struct work_struct {int unused;};
struct delayed_work {struct work_struct work;};
#define to_delayed_work(w) container_of(w,struct delayed_work,work)
static int pd_enabled,hw_mode,queued_delay;
#define IS_ENABLED(x) (pd_enabled)
#define system_wq NULL
#define msecs_to_jiffies(x) (x)
#define SC27XX_MODE_MASK 3
#define SC27XX_MODE_SNK 0
#define SC27XX_MODE_SRC 1
#define SC27XX_MODE_DRP 2
#define SC27XX_SW_CFG 0x54
#define SC27XX_CC1_SW_SWITCH_MASK (3u<<12)
#define SC27XX_CC2_SW_SWITCH_MASK (3u<<14)
#define SC27XX_CC1_SW_SWITCH(x) ((x)<<12)
#define SC27XX_CC2_SW_SWITCH(x) ((x)<<14)
#define SC27XX_TYPEC_NC 1
static int cc_override,update_error,irq_disabled;
/* PMIC attached state is retained across a MODE write until CC is opened.
 * The peer is either an external source or a real sink accessory. */
static int latched_peer,cc_restarts;
static int state;
static void cc_released(void);
static void msleep(int ms) {assert(ms==20 || ms==30);}
static void disable_irq(int irq) {irq_disabled++;}
static int mod_delayed_work(void *q,struct delayed_work *w,int delay) {queued_delay=delay;return 0;}
static int cancel_delayed_work(struct delayed_work *w) {queued_delay=0;return 0;}
static int cancel_delayed_work_sync(struct delayed_work *w) {queued_delay=0;return 0;}
static int regmap_update_bits(void *map,u32 reg,u32 mask,u32 value) {
    if (update_error) {update_error=0;return -EIO;}
    if (reg==SC27XX_SW_CFG) {
        if (cc_override && !value) {
            cc_restarts++;
            cc_released();
        }
        cc_override=value;
    } else hw_mode=value;
    return 0;
}
struct variant { u32 event_mask, state_mask, int_clr, mode; };
struct sc27xx_typec { void *dev, *regmap, *edev; u32 base, state; struct variant *var_data; bool partner_connected,role_irq_requested,external_host_policy; int irq,mode,role_lock,role_phase;struct delayed_work role_work; };
static int sc27xx_typec_connect_state, acknowledged, events, read_error;
static char calls[100];
static void call(char value) { size_t n=strlen(calls); calls[n]=value; calls[n+1]=0; }
static int regmap_read(void *map, u32 reg, u32 *value) {
    if (read_error) return -5;
    *value=reg==SC27XX_INT_MASK ? events : (reg==SC27XX_STATUS ? state : 0); return 0;
}
static int regmap_write(void *map, u32 reg, u32 value) { acknowledged=value;return 0; }
static void sc27xx_typec_err_recover_state_disen(void) { call('e'); }
static void sc27xx_typec_disconnect(struct sc27xx_typec *sc, u32 state) {
    assert(acknowledged==events); call('d');sc->partner_connected=false;
}
static int sc27xx_typec_connect(struct sc27xx_typec *sc, u32 state) {
    assert(acknowledged==events);
    if (!sc->partner_connected) call('a');
    sc->partner_connected=true;return 0;
}
static int sc27xx_typec_random_tdrp(struct sc27xx_typec *sc) { return 0; }
struct kthread_work { int unused; };
struct kthread_delayed_work { struct kthread_work work; };
struct usb_phy { void *dev; int charger_detect, chg_type, flags; enum usb_charger_state chg_state; };
struct sprd_bc1p2 { int bc1p2_lock, type, detect_state, retry_chg_detect_count, chg_redet_poll_count; bool shutdown; };
struct sprd_bc1p2_priv {
    struct usb_phy *phy; struct sprd_bc1p2 *bc1p2;
    int vbus_event_lock, bc1p2_kworker; void *bc1p2_thread;
    struct kthread_delayed_work usb_change_kwork, bc1p2_kwork;
    bool vbus_events, disconnect_pending, rework, host_active, redetect_after_host; u32 vbus_generation;
};
static int reset_current, notified, interrupt_detect, queued;
static int kthread_queue_delayed_work(void *worker, void *work, int delay) { queued++;return 1; }
static int kthread_cancel_delayed_work_sync(void *work) { return 1; }
static int kthread_mod_delayed_work(void *worker, void *work, int delay) { return 1; }
static void usb_phy_set_default_current(struct usb_phy *phy) { reset_current++; }
static void sprd_bc1p2_notify_charger(struct usb_phy *phy) { notified++; }
'''
enums = re.search(r'enum sc27xx_typec_connection_state \{.*?\};', typec, re.S)[0]
enums += r'''
static void cc_released(void) {
    if (latched_peer==1)
        state=hw_mode==SC27XX_MODE_SRC?SC27XX_ATTACHWAIT_SRC:SC27XX_ATTACHED_SNK;
    if (latched_peer==2)
        state=hw_mode==SC27XX_MODE_SNK?SC27XX_ATTACHWAIT_SNK:SC27XX_ATTACHED_SRC;
}
'''
detect = r'''
static void sprd_get_bc1p2_type(struct sprd_bc1p2_priv *info) {
    info->phy->chg_type=DCP_TYPE;
    if (interrupt_detect) {
        sprd_usb_changed(info,USB_CHARGER_ABSENT);
        sprd_usb_changed(info,USB_CHARGER_PRESENT);
    }
}
'''
tests = r'''
int main(void) {
    struct device_node connector={0},other={0};
    controller=(struct device_node){.available=true,.role="peripheral",.extcon=&connector};
    assert(sc27xx_typec_controller_mode(&connector,TYPEC_PORT_DRP)==TYPEC_PORT_UFP);
    assert(sc27xx_typec_controller_mode(&other,TYPEC_PORT_DRP)==TYPEC_PORT_DRP);
    controller.role="otg";
    assert(sc27xx_typec_controller_mode(&connector,TYPEC_PORT_DRP)==TYPEC_PORT_DRP);
    controller.role="host";
    assert(sc27xx_typec_controller_mode(&connector,0)==0);
    controller.role="peripheral";controller.available=false;
    assert(sc27xx_typec_controller_mode(&connector,TYPEC_PORT_DRP)==TYPEC_PORT_DRP);
    controller.available=true;controller.legacy=true;
    assert(sc27xx_typec_controller_mode(&connector,TYPEC_PORT_DRP)==TYPEC_PORT_DRP);
    puts("PASS: standard peripheral policy honored; legacy/host/OTG/unrelated policy retained");
    struct variant variant={.event_mask=15,.state_mask=31,.int_clr=0x10};
    struct sc27xx_typec sc={.var_data=&variant,.partner_connected=true,.mode=TYPEC_PORT_DRP};
    events=3;state=SC27XX_ATTACHED_SNK;
    assert(sc27xx_typec_interrupt(0,&sc)==IRQ_HANDLED);
    assert(!strcmp(calls,"da") && sc.partner_connected);
    memset(calls,0,sizeof(calls));state=SC27XX_DETACHED_SNK;
    sc27xx_typec_interrupt(0,&sc);
    assert(!strcmp(calls,"d") && !sc.partner_connected);
    for (int i=0;i<12;i++) {
        memset(calls,0,sizeof(calls));state=SC27XX_ATTACHED_SNK;events=1;
        sc27xx_typec_interrupt(0,&sc);
        assert(!strcmp(calls,"a") && sc.partner_connected);
        state=SC27XX_DETACHED_SNK;events=2;sc27xx_typec_interrupt(0,&sc);
    }
    read_error=1;assert(sc27xx_typec_interrupt(0,&sc)==IRQ_NONE);read_error=0;
    puts("PASS: coalesced attach/detach, final detached state, rapid replug and read errors");

    /* Reproduce C-C source misclassified as OTG: MODE alone is not a fresh
     * negotiation. The driver must obtain a real sink before publishing it. */
    sc.mode=TYPEC_PORT_DRP;sc.partner_connected=false;sc.role_phase=ROLE_IDLE;
    latched_peer=1;cc_restarts=0;hw_mode=SC27XX_MODE_DRP;
    state=SC27XX_ATTACHED_SRC;events=1;memset(calls,0,sizeof(calls));
    sc27xx_typec_interrupt(0,&sc);
    assert(cc_restarts==1 && !cc_override && state==SC27XX_ATTACHED_SNK);
    queued_delay=0;sc27xx_typec_role_work(&sc.role_work.work);
    assert(sc.partner_connected && sc.state==SC27XX_ATTACHED_SNK && !queued_delay);
    state=SC27XX_DETACHED_SNK;events=2;sc27xx_typec_interrupt(0,&sc);
    latched_peer=2;cc_restarts=0;state=SC27XX_ATTACHED_SRC;events=1;
    sc27xx_typec_interrupt(0,&sc);
    assert(!sc.partner_connected && state==SC27XX_ATTACHWAIT_SNK);
    sc27xx_typec_role_work(&sc.role_work.work);
    assert(cc_restarts==2 && state==SC27XX_ATTACHED_SRC && !sc.partner_connected);
    sc27xx_typec_interrupt(0,&sc);
    assert(sc.partner_connected && sc.state==SC27XX_ATTACHED_SRC && !queued_delay);
    state=SC27XX_DETACHED_SNK;events=2;sc27xx_typec_interrupt(0,&sc);
    latched_peer=0;
    puts("PASS: latched C-C source re-evaluated as sink; real OTG still allowed after sink probe");

    sc.mode=TYPEC_PORT_DRP;memset(calls,0,sizeof(calls));
    state=SC27XX_ATTACHED_SRC;events=1;
    sc27xx_typec_interrupt(0,&sc);
    assert(!sc.partner_connected && !calls[0] && queued_delay==500 && hw_mode==SC27XX_MODE_SNK);
    events=2;state=SC27XX_DETACHED_SNK;sc27xx_typec_interrupt(0,&sc);
    assert(sc.role_phase==ROLE_TRY_SINK); /* Mode change is not a physical new session. */
    events=1;state=SC27XX_ATTACHED_SNK;sc27xx_typec_interrupt(0,&sc);
    assert(sc.partner_connected && !strcmp(calls,"a") && !queued_delay);
    events=2;state=SC27XX_DETACHED_SNK;sc27xx_typec_interrupt(0,&sc);
    assert(!sc.partner_connected && hw_mode==SC27XX_MODE_DRP);
    memset(calls,0,sizeof(calls));events=1;state=SC27XX_ATTACHED_SRC;
    sc27xx_typec_interrupt(0,&sc);
    state=SC27XX_DETACHED_SNK;sc27xx_typec_role_work(&sc.role_work.work);
    assert(!sc.partner_connected && hw_mode==SC27XX_MODE_DRP && sc.role_phase==ROLE_ALLOW_SOURCE);
    state=SC27XX_ATTACHED_SRC;sc27xx_typec_interrupt(0,&sc);
    assert(sc.partner_connected && !strcmp(calls,"a") && !queued_delay);
    events=2;state=SC27XX_DETACHED_SNK;sc27xx_typec_interrupt(0,&sc);
    events=1;state=SC27XX_ATTACHED_SRC;sc27xx_typec_interrupt(0,&sc);
    state=SC27XX_DETACHED_SNK;
    sc27xx_typec_role_work(&sc.role_work.work);
    sc27xx_typec_role_work(&sc.role_work.work);
    assert(!sc.partner_connected && sc.role_phase==ROLE_IDLE);
    pd_enabled=1;state=SC27XX_ATTACHED_SRC;sc27xx_typec_interrupt(0,&sc);
    assert(sc.partner_connected); /* PD-enabled systems retain their policy engine. */
    sc27xx_typec_role_cleanup(&sc);assert(!queued_delay);pd_enabled=0;
    puts("PASS: charger wins sink probe, real OTG starts after probe, cancellation, expiry and PD bypass");

    assert(!sc27xx_typec_set_policy(&sc,TYPEC_PORT_DFP,false));
    assert(sc.mode==TYPEC_PORT_DFP && hw_mode==SC27XX_MODE_SRC && !cc_override);
    assert(!sc.partner_connected && !queued_delay);
    state=SC27XX_ATTACHED_SNK;events=1;sc27xx_typec_interrupt(0,&sc);
    assert(!sc.partner_connected); /* Never publish a stale sink in manual host mode. */
    state=SC27XX_ATTACHED_SRC;sc27xx_typec_interrupt(0,&sc);assert(sc.partner_connected);
    assert(!sc27xx_typec_set_policy(&sc,TYPEC_PORT_UFP,false));
    assert(!sc.partner_connected && hw_mode==SC27XX_MODE_SNK && !cc_override);
    state=SC27XX_ATTACHED_SRC;sc27xx_typec_interrupt(0,&sc);assert(!sc.partner_connected);
    state=SC27XX_ATTACHED_SNK;sc27xx_typec_interrupt(0,&sc);assert(sc.partner_connected);
    update_error=1;assert(sc27xx_typec_set_policy(&sc,TYPEC_PORT_DRP,false)==-EIO);
    assert(sc.mode==TYPEC_PORT_UFP && !cc_override);
    assert(sc27xx_typec_set_policy(&sc,55,false)==-EINVAL);
    pd_enabled=1;assert(sc27xx_typec_set_policy(&sc,TYPEC_PORT_DRP,false)==-EOPNOTSUPP);pd_enabled=0;
    assert(!sc27xx_typec_set_policy(&sc,TYPEC_PORT_DRP,false));
    sc.role_irq_requested=true;sc27xx_typec_role_cleanup(&sc);sc27xx_typec_role_cleanup(&sc);
    assert(irq_disabled==1 && !sc.role_irq_requested);
    puts("PASS: manual host/device/auto policy, stale IRQ rejection, errors and cleanup");

    struct usb_phy phy={.charger_detect=1,.chg_state=USB_CHARGER_PRESENT,.chg_type=SDP_TYPE,.flags=1};
    struct sprd_bc1p2 charger={.type=SDP_TYPE,.detect_state=2,.retry_chg_detect_count=5,.chg_redet_poll_count=20};
    struct sprd_bc1p2_priv info={.phy=&phy,.bc1p2=&charger,.bc1p2_thread=(void*)1,.rework=true};
    sprd_usb_changed(&info,USB_CHARGER_ABSENT);
    sprd_usb_changed(&info,USB_CHARGER_PRESENT);
    sprd_usb_change_work(&info.usb_change_kwork.work);
    assert(phy.chg_state==USB_CHARGER_PRESENT && phy.chg_type==UNKNOWN_TYPE && !phy.flags);
    assert(charger.type==UNKNOWN_TYPE && charger.detect_state==CHG_STATE_UNDETECT);
    assert(!charger.retry_chg_detect_count && !charger.chg_redet_poll_count);
    assert(!info.disconnect_pending && !info.rework && reset_current==1);
    interrupt_detect=1;
    sprd_get_bc1p2_type_work(&info.bc1p2_kwork.work);
    assert(notified==0); /* Never publish the detection for an obsolete cable. */
    sprd_usb_change_work(&info.usb_change_kwork.work);
    interrupt_detect=0;
    sprd_get_bc1p2_type_work(&info.bc1p2_kwork.work);
    assert(notified==1 && phy.chg_type==DCP_TYPE);
    puts("PASS: unplug/replug before work runs and cable replacement during detection");
    sprd_usb_host_changed(&info,true);
    sprd_usb_changed(&info,USB_CHARGER_PRESENT);
    queued=0;sprd_usb_change_work(&info.usb_change_kwork.work);
    assert(!queued && info.redetect_after_host);
    sprd_get_bc1p2_type_work(&info.bc1p2_kwork.work);
    assert(notified==1); /* A late sink cannot sample the active host. */
    sprd_usb_host_changed(&info,false);
    queued=0;sprd_usb_change_work(&info.usb_change_kwork.work);
    assert(queued==1 && !phy.flags && phy.chg_type==UNKNOWN_TYPE);
    assert(charger.detect_state==CHG_STATE_UNDETECT && info.redetect_after_host);
    sprd_get_bc1p2_type_work(&info.bc1p2_kwork.work);
    assert(notified==2 && phy.chg_type==DCP_TYPE);
    sprd_usb_host_changed(&info,true);
    sprd_usb_changed(&info,USB_CHARGER_ABSENT);
    queued=0;sprd_usb_change_work(&info.usb_change_kwork.work);
    assert(queued==1); /* Detach still disables charging while hosting. */
    sprd_get_bc1p2_type_work(&info.bc1p2_kwork.work);
    assert(notified==3 && phy.chg_type==UNKNOWN_TYPE);
    puts("PASS: host-to-sink deferral, teardown restart and detach while hosting");
    return 0;
}
'''
code = (prelude + enums + (kernel/'drivers/usb/typec/board-usb-role.h').read_text() +
        function((kernel/'drivers/usb/typec/board-usb-policy.h').read_text(), 'sc27xx_typec_set_policy') +
        function(typec, 'sc27xx_typec_controller_mode') + function(typec, 'sc27xx_typec_interrupt') +
        function(bc, 'sprd_usb_changed') +
        function((kernel/'drivers/usb/phy/board-usb-charge-role.h').read_text(), 'sprd_usb_host_changed') +
        detect + function(bc, 'sprd_usb_change_work') +
        function(bc, 'sprd_get_bc1p2_type_work') + tests)
with tempfile.TemporaryDirectory(prefix='usb-charge-test-') as temp:
    root = Path(temp)
    (root / 'test.c').write_text(code)
    subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
                    str(root / 'test.c'), '-o', str(root / 'test')], check=True)
    subprocess.run([str(root / 'test')], check=True)
