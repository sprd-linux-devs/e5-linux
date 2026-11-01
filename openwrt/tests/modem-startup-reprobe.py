#!/usr/bin/env python3
"""Execute native MM startup recovery against simulated lifecycle events.

Extract production initialize_ready, modem_valid, reprobe, timeout and AT-error
callbacks. Use real GLib errors/cancellables, no device, AT or live bus access.
"""
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile

root = Path(sys.argv[1])
device = (root/'mm-device.c').read_text()
base = (root/'mm-base-modem.c').read_text()
plugin = (root/'plugins/unisoc/mm-broadband-modem-unisoc.c').read_text()
helper = (root/'mm-base-modem-at.c').read_text()


def function(source, name, result='void'):
    start = source.index('static '+result+'\n'+name+' (')
    return source[start:source.index('\n}\n', start)+3]


assert 'g_timeout_add' not in function(device, 'device_retry_unisoc_startup', 'gboolean')
assert 'cards_on_retry' not in plugin
assert 'retry_error' not in plugin
assert 'reprobe_id' in device and 'g_source_remove (self->priv->reprobe_id)' in device
delay = re.search(r'^#define REPROBE_SECS (\d+)', device, re.M)[0]
start = helper.index('MMBaseModemAtResponseProcessorResult\nmm_base_modem_response_processor_no_result_continue (')
processor = helper[start:helper.index('\n}\n', start)+3]
production = '\n'.join((
    function(device,'device_retry_unisoc_startup','gboolean'),
    function(device,'initialize_ready'),function(device,'reprobe','gboolean'),
    function(device,'modem_valid'),function(base,'port_timed_out_cb'),processor,
    function(plugin,'cards_on_response','MMBaseModemAtResponseProcessorResult')))
dispose = function(device, 'dispose')
timer_cleanup = dispose[dispose.index('    if (self->priv->reprobe_id) {'):dispose.index('    g_clear_object')]
production += '\nstatic void dispose_timer(MMDevice *self) {\n'+timer_cleanup+'}\n'
prelude = r'''
#include <gio/gio.h>
#include <assert.h>
#include <stdio.h>
#include <string.h>
#define MM_CORE_ERROR (g_quark_from_static_string("fixture-mm-core"))
#define MM_CORE_ERROR_ABORTED 9
#define MM_PORT(p) (p)
static void fixture_log(const gchar *format,...){(void)format;}
#define mm_obj_warn(obj,...) fixture_log(__VA_ARGS__)
#define mm_obj_err(obj,...) fixture_log(__VA_ARGS__)
#define mm_obj_dbg(obj,...) fixture_log(__VA_ARGS__)
typedef struct {guint max_timeouts;GCancellable *cancellable;gboolean valid;} ModemPrivate;
typedef struct {ModemPrivate *priv;const gchar *plugin,*device;gboolean reprobe;} MMBaseModem;
typedef struct {MMBaseModem *modem;guint reprobe_id;gboolean inhibited;} DevicePrivate;
typedef struct {DevicePrivate *priv;guint refs;gboolean ports;} MMDevice;
typedef struct {const gchar *name;} MMPort;
static void modem_valid(MMBaseModem*,GParamSpec*,MMDevice*);
static void initialize_ready(MMBaseModem*,GAsyncResult*,MMDevice*);
static gboolean mm_device_create_modem(MMDevice*,GError**);
static void mm_device_initialize_modem(MMDevice*);
static void mm_device_remove_modem(MMDevice*);
static void export_modem(MMDevice*);
static gboolean init_ok;
static GQuark init_domain;
static gint init_code;
static guint removed,created,exports,initializations;
static guint failures;
static MMDevice *owner;
static GSourceFunc timer;
static gpointer timer_data;
static guint next_id;
static void device_unref(MMDevice *d){assert(d->refs);d->refs--;}
G_DEFINE_AUTOPTR_CLEANUP_FUNC(MMDevice,device_unref)
static const gchar *mm_base_modem_get_plugin(MMBaseModem *m){return m->plugin;}
static const gchar *mm_base_modem_get_device(MMBaseModem *m){return m->device;}
static gboolean mm_base_modem_get_valid(MMBaseModem *m){return m->priv->valid;}
static gboolean mm_base_modem_get_reprobe(MMBaseModem *m){return m->reprobe;}
static void mm_base_modem_set_reprobe(MMBaseModem *m,gboolean yes){m->reprobe=yes;}
static GCancellable *mm_base_modem_peek_cancellable(MMBaseModem *m){return m->priv->cancellable;}
static const gchar *mm_port_get_device(MMPort *p){return p->name;}
static void mm_base_modem_set_valid(MMBaseModem *m,gboolean yes){
 m->priv->valid=yes;modem_valid(m,NULL,owner);
}
static gboolean mm_base_modem_initialize_finish(MMBaseModem *m,GAsyncResult *r,GError **error){
 if(!init_ok)*error=g_error_new_literal(init_domain,init_code,"initial AT failed");return init_ok;
}
static guint native_timer(guint seconds,GSourceFunc cb,gpointer data){
 assert(seconds==REPROBE_SECS && !timer);timer=cb;timer_data=data;return ++next_id;
}
static gboolean remove_timer(guint id){assert(id && timer);timer=NULL;return TRUE;}
#define g_timeout_add_seconds native_timer
#define g_source_remove remove_timer
typedef enum {MM_BASE_MODEM_AT_RESPONSE_PROCESSOR_RESULT_CONTINUE,
 MM_BASE_MODEM_AT_RESPONSE_PROCESSOR_RESULT_SUCCESS,
 MM_BASE_MODEM_AT_RESPONSE_PROCESSOR_RESULT_FAILURE} MMBaseModemAtResponseProcessorResult;
'''
cases = r'''
static MMBaseModem modems[32];static ModemPrivate private[32];static MMDevice dev;static DevicePrivate dp;
static void cancelled(GCancellable *c,MMBaseModem *m){
 if(owner->priv->modem==m)mm_base_modem_set_valid(m,FALSE);
}
static gboolean mm_device_create_modem(MMDevice *d,GError **error){
 if(!d->ports || d->priv->inhibited){g_set_error_literal(error,MM_CORE_ERROR,1,"device absent/inhibited");return FALSE;}
 assert(created<G_N_ELEMENTS(modems));guint i=created++;
 modems[i]=(MMBaseModem){&private[i],"unisoc","unisoc-sipc",FALSE};
 private[i]=(ModemPrivate){10,g_cancellable_new(),FALSE};
 g_signal_connect(private[i].cancellable,"cancelled",G_CALLBACK(cancelled),&modems[i]);
 d->priv->modem=&modems[i];return TRUE;
}
static void mm_device_remove_modem(MMDevice *d){
 MMBaseModem *m=d->priv->modem;if(!m)return;
 d->priv->modem=NULL;removed++;g_cancellable_cancel(m->priv->cancellable);
}
static void export_modem(MMDevice *d){assert(d->priv->modem && d->priv->modem->priv->valid);exports++;}
static void mm_device_initialize_modem(MMDevice *d){
 initializations++;init_ok=!failures;if(failures)failures--;
 init_domain=MM_CORE_ERROR;init_code=MM_CORE_ERROR_ABORTED;
 d->refs++;initialize_ready(d->priv->modem,NULL,d);
}
static void fire(void){
 assert(timer);GSourceFunc cb=timer;gpointer arg=timer_data;timer=NULL;
 assert(cb(arg)==G_SOURCE_REMOVE);
}
static void reset(void){
 assert(!timer);for(guint i=0;i<created;i++)g_clear_object(&private[i].cancellable);
 memset(modems,0,sizeof(modems));memset(private,0,sizeof(private));
 dp=(DevicePrivate){0};dev=(MMDevice){&dp,1,TRUE};owner=&dev;
 removed=created=exports=initializations=failures=0;
 GError *err=NULL;assert(mm_device_create_modem(&dev,&err)&&!err);
}
int main(void){
 /* Healthy boot exports immediately; no added wait or new timer. */
 reset();mm_device_initialize_modem(&dev);assert(exports==1 && !timer && !removed && dev.refs==1);
 /* Any fatal startup AT error keeps native recovery alive across failures. */
 reset();failures=3;mm_device_initialize_modem(&dev);
 for(guint n=0;n<3;n++){
  assert(timer && !dev.priv->modem && removed==n+1);fire();
 }
 assert(exports==1 && created==4 && initializations==4 && !timer && dev.refs==1);
 /* Other plugins, other UIDs and nonfatal initialization keep upstream policy. */
 for(guint n=0;n<4;n++){
  reset();MMBaseModem *m=dp.modem;
  if(n==0)m->plugin="generic";if(n==1)m->device="external-usb";
  if(n==2)m->plugin=NULL;if(n==3)m->device=NULL;
  failures=1;mm_device_initialize_modem(&dev);assert(!timer && !removed && !exports && dp.modem==m);
 }
 reset();init_ok=FALSE;init_domain=G_IO_ERROR;init_code=G_IO_ERROR_FAILED;
 dev.refs++;initialize_ready(dp.modem,NULL,&dev);assert(exports==1 && !timer && dev.refs==1);
 /* Explicit inhibition/cancellation/stale callbacks do not resurrect devices. */
 reset();dp.inhibited=TRUE;failures=1;mm_device_initialize_modem(&dev);assert(!timer && !removed);
 reset();MMBaseModem *old=dp.modem;g_cancellable_cancel(old->priv->cancellable);
 init_ok=FALSE;init_domain=MM_CORE_ERROR;init_code=MM_CORE_ERROR_ABORTED;
 dev.refs++;initialize_ready(old,NULL,&dev);assert(!timer && !dp.modem && dev.refs==1);
 reset();old=dp.modem;mm_device_remove_modem(&dev);GError *err=NULL;
 assert(mm_device_create_modem(&dev,&err));init_ok=FALSE;init_domain=MM_CORE_ERROR;init_code=MM_CORE_ERROR_ABORTED;
 dev.refs++;initialize_ready(old,NULL,&dev);assert(dp.modem!=old && !timer && created==2);
 reset();failures=1;mm_device_initialize_modem(&dev);dp.inhibited=TRUE;fire();
 assert(!timer && !dp.modem && created==1 && initializations==1);
 reset();failures=1;mm_device_initialize_modem(&dev);dev.ports=FALSE;fire();
 assert(!timer && !dp.modem && created==1);
 reset();failures=1;mm_device_initialize_modem(&dev);dispose_timer(&dev);
 assert(!timer && !dp.reprobe_id && created==1);dispose_timer(&dev);
 /* Startup serial timeout arms reprobe BEFORE cancellation notification. */
 reset();MMPort port={"wwan0at0"};MMBaseModem *m=dp.modem;
 for(guint n=1;n<10;n++){port_timed_out_cb(&port,n,m);assert(!m->reprobe && !timer && dp.modem==m);}
 port_timed_out_cb(&port,10,m);assert(m->reprobe && timer && !dp.modem);fire();
 assert(exports==1 && !timer && created==2);
 for(guint n=0;n<3;n++){
  reset();m=dp.modem;
  if(n==0)m->plugin="generic";if(n==1)m->device="external-usb";if(n==2)m->priv->valid=TRUE;
  port_timed_out_cb(&port,10,m);assert(!timer && !m->reprobe);
 }
 reset();m=dp.modem;g_cancellable_cancel(m->priv->cancellable);
 port_timed_out_cb(&port,10,m);assert(!timer && !m->reprobe && !dp.modem);
 /* Log context preserves exact AT domain/code; it never turns ERROR into OK. */
 for(gint code=0;code<30;code++){
  GError *input=g_error_new_literal(G_IO_ERROR,code,"AT rejected"),*output=NULL;GVariant *value=NULL;
  assert(cards_on_response(NULL,NULL,"+SPACTCARD=0;+SFUN=2",NULL,FALSE,input,&value,&output)==MM_BASE_MODEM_AT_RESPONSE_PROCESSOR_RESULT_FAILURE);
  assert(output && output->domain==input->domain && output->code==code && !value);
  assert(strstr(output->message,"AT+SPACTCARD=0;+SFUN=2: AT rejected"));g_error_free(input);g_error_free(output);
 }
 GError *output=NULL;GVariant *value=NULL;
 assert(cards_on_response(NULL,NULL,"+CFUN?","OK",TRUE,NULL,&value,&output)==MM_BASE_MODEM_AT_RESPONSE_PROCESSOR_RESULT_CONTINUE);
 assert(!output && !value);assert(dev.refs==1);
 for(guint i=0;i<created;i++)g_clear_object(&private[i].cancellable);
 puts("PASS: native MM startup reprobe: repeated failures/success, normal boot, plugin/UID scope, cancellation/inhibition/removal, startup timeout and 30 AT error contexts");
 return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='unisoc-startup-reprobe-') as directory:
    tmp = Path(directory)
    (tmp/'test.c').write_text(delay+'\n'+prelude+production+cases)
    flags = shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','gio-2.0'],text=True))
    subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-parameter',
                    '-Wno-misleading-indentation','-fsanitize=undefined','-fno-sanitize-recover=all',
                    str(tmp/'test.c'),'-o',str(tmp/'test'),*flags],check=True)
    subprocess.run([str(tmp/'test')],check=True,env={**__import__('os').environ,'G_DEBUG':'fatal-warnings'})
