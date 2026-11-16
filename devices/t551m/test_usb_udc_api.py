#!/usr/bin/env python3
"""Replay the real vendor detach and UDC APIs, including the obsolete layout."""
import argparse
from pathlib import Path
import re
import runpy
import subprocess
import tempfile


def function(source, name):
    match = re.search(r'(?:static\s+)?(?:inline\s+)?(?:int|void)\s+' + name +
                      r'\([^;{}]*\)[^{;]*\{', source)
    assert match, name
    end, depth = match.end(), 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[match.start():end] + '\n'


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('kernel', type=Path)
parser.add_argument('--glue-source', type=Path)
parser.add_argument('--adapt-legacy', action='store_true',
                    help='Exercise a legacy source in memory instead of checking build input')
args = parser.parse_args()
glue = (args.glue_source or args.kernel / 'drivers/usb/musb/musb_sprd.c').read_text()
core = (args.kernel / 'drivers/usb/gadget/udc/core.c').read_text()
adapt = runpy.run_path(str(Path(__file__).with_name('usb_host.py')))['gadget_udc_api']
fixed = adapt(glue)
if not args.adapt_legacy:
    assert fixed == glue, 'UDC repair is absent from the actual prepared source'
assert adapt(fixed) == fixed
assert 'struct sprd_usb_udc' not in fixed
udc = re.search(r'struct usb_udc \{.*?\n\};', core, re.S).group()
legacy = re.search(r'struct sprd_usb_udc \{.*?\n\};', glue, re.S)
# A prepared source may already carry the fix. Use the tracked legacy layout
# for the negative control; the public API still uses the actual core layout.
legacy = legacy.group() if legacy else '''struct sprd_usb_udc {
 struct usb_gadget_driver *driver; struct usb_gadget *gadget;
 struct device dev; struct list_head list; bool vbus; bool started;
};'''
apis = ''.join(function(core, name) for name in (
    'usb_gadget_connect_locked', 'usb_gadget_connect',
    'usb_gadget_disconnect_locked', 'usb_gadget_disconnect',
    'usb_udc_connect_control_locked', 'usb_udc_vbus_handler'))
detach = function(fixed, 'musb_sprd_otg_start_peripheral')
detach = detach.split('\n\t} else {', 1)[1].rsplit('\n\t}\n', 1)[0]
detach = 'static void role_stop(struct sprd_glue *glue) {\nstruct musb *musb = glue->musb;\n' + detach + '\n}\n'

prelude = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
struct device { unsigned char opaque[776]; };
struct list_head { void *next, *prev; };
struct work_struct { int scheduled; };
struct mutex { int unused; };
struct usb_gadget;
struct usb_gadget_driver { void (*disconnect)(struct usb_gadget *); };
struct gadget_ops { int (*pullup)(struct usb_gadget *, int); };
struct usb_gadget { struct usb_udc *udc; struct gadget_ops *ops;
 bool connected, deactivated; };
#define __must_hold(x)
#define EOPNOTSUPP 95
#define USB_STATE_NOTATTACHED 0
#define SPRD_USBPHY_EVENT_TYPEC 0
#define mutex_lock(x) ((void)(x))
#define mutex_unlock(x) ((void)(x))
#define trace_usb_gadget_connect(...) ((void)0)
#define trace_usb_gadget_disconnect(...) ((void)0)
#define dev_info(...) ((void)0)
static struct mutex udc_lock;
static void schedule_work(struct work_struct *w) { w->scheduled++; }
static int pullups, callbacks, power_down, releases;
static int pullup(struct usb_gadget *g, int on) {
 (void)g; pullups += on ? 1 : -1; return 0;
}
static void disconnected(struct usb_gadget *g) { (void)g; callbacks++; }
struct musb {struct usb_gadget g; int gadget_work, offload_used; void *controller;};
struct sprd_glue {struct musb *musb; bool use_pdhub_c2c; void *dev;};
static void flush_delayed_work(int *w) {(void)w;}
static void musb_sprd_release_all_request(struct musb *m) {
 assert(!m->g.connected); releases++;
}
static void usb_gadget_set_state(struct usb_gadget *g, int state) {
 assert(!g->connected && !state);
}
static void call_sprd_usbphy_event_notifiers(int e, bool b, void *p) {
 (void)e;(void)b;(void)p;
}
static void pm_runtime_put_sync(void *d) {(void)d;power_down++;}
static void pm_relax(void *d) {(void)d;}
'''
checks = r'''
int main(void) {
 struct usb_gadget_driver driver = {.disconnect=disconnected};
 struct gadget_ops ops = {.pullup=pullup};
 struct musb musb = {0}; struct sprd_glue glue = {.musb=&musb};
 struct usb_udc udc = {.driver=&driver,.gadget=&musb.g,
                      .started=true,.vbus=true,.allow_connect=true};
 void *sentinel=(void *)(uintptr_t)0x123456789abcdeffULL;
 udc.list.prev=sentinel;
 /* This is the real vendor cast and write: it hits list.prev, not vbus,
  * after the core added gadget_release ahead of struct device. */
 ((struct sprd_usb_udc *)&udc)->vbus=false;
 assert(udc.list.prev!=sentinel && udc.vbus);
 udc.list.prev=sentinel;
 musb.g.udc=&udc;musb.g.ops=&ops;musb.g.connected=true;
 /* The old direct pullup call leaves connected=true. The next public
  * connect then succeeds without turning the pullup back on. */
 musb.g.ops->pullup(&musb.g,0);
 assert(!usb_gadget_connect(&musb.g));
 assert(musb.g.connected && pullups==-1);
 pullups=0;
 for(int cycle=0;cycle<10;cycle++) {
  udc.vbus=true;musb.g.connected=true;
  role_stop(&glue);
  assert(!udc.vbus && !musb.g.connected && udc.list.prev==sentinel);
  assert(udc.started && udc.driver==&driver);
  assert(power_down==cycle+1 && releases==cycle+1);
  assert(callbacks==cycle+1 && pullups==-(cycle+1));
  /* The queued VBUS worker must not run a second disconnect callback. */
  assert(usb_udc_connect_control_locked(&udc)==0);
  assert(callbacks==cycle+1);
 }
 /* Disconnect also clears the shadow while soft-stopped/deactivated,
  * without issuing hardware operations against an inactive controller. */
 udc.started=false;udc.vbus=true;musb.g.connected=true;
 role_stop(&glue);assert(!udc.vbus && !musb.g.connected && callbacks==10);
 udc.started=true;musb.g.deactivated=true;musb.g.connected=true;
 role_stop(&glue);assert(!musb.g.connected && callbacks==10);
 /* A subsequent real attachment is connectable again. */
 musb.g.deactivated=false;udc.vbus=true;
 assert(!usb_gadget_connect(&musb.g));assert(musb.g.connected);
 assert(pullups==-9 && udc.list.prev==sentinel);
 return 0;
}
'''
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    (root / 'test.c').write_text(prelude + udc + legacy + apis + detach + checks)
    subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                    '-Wno-unused-variable', '-fno-strict-aliasing',
                    '-fsanitize=address,undefined', '-fno-pie', '-no-pie',
                    '-g', str(root / 'test.c'),
                    '-o', str(root / 'test')], check=True)
    subprocess.run([str(root / 'test')], check=True)
print('PASS: obsolete UDC write reproduces list corruption; public detach APIs preserve layout, reconnect and role PM')
