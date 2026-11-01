#!/usr/bin/env python3
"""Compile production MM power-plan callbacks with fake AT results, no hardware."""
from pathlib import Path
import subprocess
import sys
import tempfile

input_path = Path(sys.argv[1])
source = (input_path if input_path.is_file() else input_path / 'plugins/unisoc/mm-broadband-modem-unisoc.c').read_text()


def function(name, result='void'):
    start = source.index('static ' + result + '\n' + name + ' (')
    return source[start:source.index('\n}\n', start) + 3]


# Use MM's real mandatory response processor as well as the production callbacks.
helper_source = input_path.parent / 'mm-base-modem-at.c' if input_path.is_file() else input_path / 'mm-base-modem-at.c'
helper = helper_source.read_text()
start = helper.index('MMBaseModemAtResponseProcessorResult\nmm_base_modem_response_processor_no_result_continue (')
processor = helper[start:helper.index('\n}\n', start) + 3]

model = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <stdint.h>
#include <limits.h>
#include <ctype.h>
#include <errno.h>
typedef unsigned guint; typedef char gchar; typedef int gboolean;
typedef uint64_t guint64; typedef void GVariant;
#define G_MAXUINT UINT_MAX
#define g_ascii_isspace(c) isspace((unsigned char)(c))
#define g_ascii_isdigit(c) isdigit((unsigned char)(c))
#define g_ascii_strtoull strtoull
#define MM_CORE_ERROR 2
#define MM_CORE_ERROR_FAILED 1
#define MM_CORE_ERROR_WRONG_STATE 2
typedef enum {MM_BASE_MODEM_AT_RESPONSE_PROCESSOR_RESULT_CONTINUE,
 MM_BASE_MODEM_AT_RESPONSE_PROCESSOR_RESULT_SUCCESS,
 MM_BASE_MODEM_AT_RESPONSE_PROCESSOR_RESULT_FAILURE} MMBaseModemAtResponseProcessorResult;
typedef int MMBaseModem;
typedef struct {int code; char *message;} GError;
typedef MMBaseModemAtResponseProcessorResult (*Processor)(MMBaseModem*,void*,const char*,const char*,int,const GError*,GVariant**,GError**);
typedef void (*GAsyncReadyCallback)(void);
typedef struct {char *command; unsigned timeout; Processor response_processor;} MMBaseModemAtCommandAlloc;
typedef MMBaseModemAtCommandAlloc MMBaseModemAtCommand;
typedef struct {MMBaseModemAtCommandAlloc cmds[9]; gboolean present[2]; guint probe,own;} CardsOnContext;
typedef struct {void *data; int error, returned, unrefs; CardsOnContext *owned;} GTask;
typedef int MMBaseModem;

typedef struct {const char *response;int code;} GAsyncResult;
#define TRUE 1
#define FALSE 0
typedef void *gpointer;
typedef void (*GDestroyNotify)(void*);
#define G_OBJECT(t) (t)
#define g_slice_new0(t) ((t*)calloc(1,sizeof(t)))
static unsigned radio_mask=3;
static gboolean sim_radio_enabled(guint card){return !!(radio_mask&(1u<<card));}
static guint port_card(void){return 0;}
static void cards_on_context_free(void *ptr){CardsOnContext *ctx=ptr;for(unsigned i=0;ctx->cmds[i].command;i++)free(ctx->cmds[i].command);free(ctx);}
static void g_object_set_data_full(void *task,const char *key,void *data,GDestroyNotify destroy){((GTask*)task)->owned=data;}
static void init_radio_policy_ready(MMBaseModem*,GAsyncResult*,GTask*);
#define MM_MOBILE_EQUIPMENT_ERROR 1
#define MM_MOBILE_EQUIPMENT_ERROR_SIM_NOT_INSERTED 10
#define mm_obj_info(...) ((void)0)
static int sequenced,next,inject_failure=-1,commands_run,radio_on,power_commands,ports_released;
static char last_command[100];
static void cards_on_sequence_ready(MMBaseModem*,GAsyncResult*,GTask*);
static void init_sim_on_ready(MMBaseModem*,GAsyncResult*,GTask*);
static void power_sequence_ready(void) {}
static void power_command_ready(void) {}
static void g_task_return_error(GTask *task,GError *error){task->error=error->code;free(error->message);free(error);}
static void g_object_unref(GTask *task){task->unrefs++;if(task->owned){cards_on_context_free(task->owned);task->owned=NULL;}}
static void g_task_return_boolean(GTask *task,gboolean value){task->returned=value;}
static void g_task_return_pointer(GTask *task,void *data,void *destroy){assert(task->data==data);task->returned=1;}
static void g_task_set_task_data(GTask *task,void *data,void *destroy){task->data=data;}
static void g_task_return_new_error(GTask *task,int domain,int code,const char *message){task->error=code;}
static GError *g_error_new(int domain,int code,const char *message){GError *e=malloc(sizeof(*e));e->code=code;e->message=strdup(message);return e;}
static void g_prefix_error(GError **error,const char *prefix,...){}
static GError *g_error_copy(const GError *error){return g_error_new(0,error->code,error->message);}
static int parent_stopped(MMBaseModem *self,void *data,void *error){assert(data);ports_released++;return 1;}
static struct {int (*initialization_stopped)(MMBaseModem*,void*,void*);} parent={parent_stopped};
static void *mm_broadband_modem_unisoc_parent_class=&parent;
#define MM_BROADBAND_MODEM_CLASS(p) ((typeof(&parent))(p))
#define MM_BROADBAND_MODEM(p) (p)
static GTask *g_task_new(void *self,void *cancel,void *cb,void *data){static GTask task;task=(GTask){0};return &task;}
#define MM_BASE_MODEM(p) ((MMBaseModem*)(p))
typedef MMBaseModem MMIfaceModem;
#define mm_obj_dbg(...) ((void)0)
#define mm_obj_msg(...) ((void)0)
static void cards_on(MMBaseModem *m,GAsyncReadyCallback cb,GTask *task){radio_on++;}
static void mm_base_modem_at_command(MMBaseModem *m,const char *cmd,int timeout,int cache,GAsyncReadyCallback cb,GTask *task){power_commands++;snprintf(last_command,sizeof(last_command),"%s",cmd);}
static void mm_base_modem_at_sequence_finish(MMBaseModem *m,GAsyncResult *r,void *context,GError **error){if(r->code)*error=g_error_new(0,r->code,"sequence failed");}
static gboolean cards_on_finish(MMBaseModem *m,GAsyncResult *r,GError **error){if(r->code)*error=g_error_new(0,r->code,"activation failed");return !r->code;}

static void cards_on_probe_next(GTask *task) {next++;}
static void *g_task_get_task_data(GTask *t){return t->data;}
static const char *mm_base_modem_at_command_finish(MMBaseModem *m,GAsyncResult *r,GError **error){
 if(error && r->code)*error=g_error_new(0,r->code,"AT failed");
 return r->response;
}
static int g_error_matches(GError *error,int domain,int code){return error->code==code;}
static void g_clear_error(GError **error){if(*error){free((*error)->message);free(*error);}*error=NULL;}
#define g_free free
static char *g_strdup(const char *s){return strdup(s);}
static char *g_strdup_printf(const char *fmt,...){va_list args;char *out;va_start(args,fmt);vasprintf(&out,fmt,args);va_end(args);return out;}
MMBaseModemAtResponseProcessorResult mm_base_modem_response_processor_no_result_continue(MMBaseModem*,void*,const char*,const char*,int,const GError*,GVariant**,GError**);
static void mm_base_modem_at_sequence(MMBaseModem *m,const MMBaseModemAtCommand *commands,void *a,void *b,GAsyncReadyCallback cb,GTask *t){
 sequenced++;
 if(t->owned){
  assert(commands==t->owned->cmds);
  for(unsigned i=0;commands[i].command;i++){
   unsigned card;assert(sscanf(commands[i].command,"+SPACTCARD=%u;",&card)==1);
   assert(strstr(commands[i].command,"+SFUN=5") || strstr(commands[i].command,"+CFUN?"));
   if(strstr(commands[i].command,"+SFUN=5"))assert(!sim_radio_enabled(card));
   if(strstr(commands[i].command,"+CFUN?"))assert(card==port_card());
  }
  GAsyncResult res={NULL,0};init_radio_policy_ready(m,&res,t);return;
 }
 assert(commands==((CardsOnContext*)t->data)->cmds && commands[8].command==NULL);
 commands_run=0;
 GAsyncResult reply={NULL,0};
 for(unsigned i=0;commands[i].command;i++){
  assert(commands[i].response_processor);
  commands_run++;
  GError injected={14,"injected failure"}, *error=NULL;GVariant *value=NULL;
  MMBaseModemAtResponseProcessorResult result=commands[i].response_processor(m,NULL,commands[i].command,"",!commands[i+1].command,(int)i==inject_failure?&injected:NULL,&value,&error);
  if(result==MM_BASE_MODEM_AT_RESPONSE_PROCESSOR_RESULT_FAILURE){assert(error && !value);reply.code=error->code;g_clear_error(&error);break;}
  assert(result==MM_BASE_MODEM_AT_RESPONSE_PROCESSOR_RESULT_CONTINUE && !error && !value);
 }
 cards_on_sequence_ready(m,&reply,t);
}
'''

tests = r'''
static void check(int first,int second,unsigned own){
 CardsOnContext ctx={0};ctx.present[0]=first;ctx.present[1]=second;ctx.own=own;
 GTask task={.data=&ctx};MMBaseModem modem=0;GAsyncResult modes={"+SPTESTMODE: 98,134,0,19,3,1",0};
 cards_on_testmode_ready(&modem,&modes,&task);
 unsigned i=0,sfun[2]={0},data=0;
 for(;ctx.cmds[i].command;i++){
  char *command=ctx.cmds[i].command;unsigned card;
  assert(sscanf(command,"+SPACTCARD=%u;",&card)==1 && card<2);
  if(strstr(command,"SFUN=") || strstr(command,"SPTESTMODEM=") || strstr(command,"SPSWDATA"))
    assert(ctx.present[card]);
  if(strstr(command,"SFUN="))sfun[card]++;
  if(strstr(command,"SFUN=4"))assert(sim_radio_enabled(card));
  if(strstr(command,"SFUN=5"))assert(!sim_radio_enabled(card));
  if(strstr(command,"SPSWDATA")){assert(card==own);data++;}
  if(strstr(command,"SPTESTMODEM="))assert(strstr(command,"=98,134"));
 }
 assert(i==(unsigned)(1+3*(first+second)+(ctx.present[own]?1:0)));
 assert(sfun[0]==(unsigned)(first?2:0) && sfun[1]==(unsigned)(second?2:0));
 assert(data==(unsigned)(ctx.present[own]?1:0));
 char ending[40];snprintf(ending,sizeof(ending),"+SPACTCARD=%u;+CFUN?",own);
 assert(!strcmp(ctx.cmds[i-1].command,ending));
 // Preserve vendor RIL ordering when both cards are inserted.
 if(first&&second){
  assert(!strcmp(ctx.cmds[0].command,"+SPACTCARD=0;+SFUN=2"));
  assert(!strcmp(ctx.cmds[1].command,"+SPACTCARD=1;+SFUN=2"));
  assert(strstr(ctx.cmds[2].command,"+SPACTCARD=1;+SPTESTMODEM="));
  assert(strstr(ctx.cmds[3].command,"+SPACTCARD=0;+SPTESTMODEM="));
  assert(!strcmp(ctx.cmds[5].command,sim_radio_enabled(0)?"+SPACTCARD=0;+SFUN=4":"+SPACTCARD=0;+SFUN=5"));
  assert(!strcmp(ctx.cmds[6].command,sim_radio_enabled(1)?"+SPACTCARD=1;+SFUN=4":"+SPACTCARD=1;+SFUN=5"));
 }
 assert(task.returned==1 && task.error==0 && task.unrefs==1);
 for(unsigned j=0;j<i;j++)free(ctx.cmds[j].command);
}

static void failed_modes(void){
 const char *bad[]={NULL,"garbage","+SPTESTMODE: 152","+SPTESTMODE: -1,134","+SPTESTMODE: 152,broken","+SPTESTMODE: 4294967296,134","+SPTESTMODE: 152,134junk"};
 for(unsigned i=0;i<sizeof(bad)/sizeof(bad[0]);i++){
  CardsOnContext ctx={0};ctx.present[0]=ctx.present[1]=1;GTask task={.data=&ctx};MMBaseModem modem=0;
  GAsyncResult response={bad[i],i?0:14};int before=sequenced;
  cards_on_testmode_ready(&modem,&response,&task);
  assert(sequenced==before && task.error && task.unrefs==1 && !ctx.cmds[0].command);
 }
}
static void fail_each_command(void){
 for(inject_failure=0;inject_failure<8;inject_failure++){
  CardsOnContext ctx={0};ctx.present[0]=ctx.present[1]=1;GTask task={.data=&ctx};MMBaseModem modem=0;
  GAsyncResult response={"+SPTESTMODE: 152,3,0,19,3,1",0};
  cards_on_testmode_ready(&modem,&response,&task);
  assert(commands_run==inject_failure+1 && task.error==14 && !task.returned && task.unrefs==1);
  for(unsigned j=0;ctx.cmds[j].command;j++)free(ctx.cmds[j].command);
 }
 inject_failure=-1;
}
static void power_queries(void){
 const char *responses[]={NULL,"","+CFUN: garbage","+CFUN: -1","+CFUN: 4294967296","+CFUN: 1junk","+CFUN: 0","+CFUN: 1"," +CFUN: 4\r\n", "+CFUN: 2"};
 for(unsigned i=0;i<sizeof(responses)/sizeof(responses[0]);i++){
  MMBaseModem modem=0;int token=1;GTask task={.data=&token};GAsyncResult response={responses[i],i?0:14};
  radio_on=power_commands=ports_released=0;
  init_cfun_ready(&modem,&response,&task);
  if(i<6)assert(task.error && !task.returned && task.unrefs==1 && ports_released==1 && !task.data && !radio_on && !power_commands);
  else if(i==6)assert(power_commands==1 && !strcmp(last_command,"+SPACTCARD=1;+CFUN?") && !radio_on && !task.error && !task.returned && task.data==&token);
  else assert(task.returned==1 && !task.error && task.unrefs==1 && !ports_released && task.data==&token);
  task=(GTask){0};radio_on=power_commands=0;
  power_up_cfun_ready(&modem,&response,&task);
  if(i<6)assert(task.error && task.unrefs==1 && !power_commands && !radio_on);
  else if(i==6)assert(power_commands==1 && !strcmp(last_command,"+CPIN?") && !radio_on && !task.error);
  else if(i==7)assert(task.returned && task.unrefs==1 && !power_commands && !radio_on && !task.error);
  else assert(power_commands==1 && !strcmp(last_command,"+SFUN=4") && !radio_on && !task.error);
 }
 MMBaseModem modem=0;int token=1;GTask task={.data=&token};GAsyncResult failed={NULL,14},ok={NULL,0};
 ports_released=0;init_sim_on_ready(&modem,&failed,&task);
 assert(task.error==14 && !task.returned && !task.data && task.unrefs==1 && ports_released==1);
 task=(GTask){.data=&token};ports_released=0;init_sim_on_ready(&modem,&ok,&task);
 assert(!task.error && task.returned==1 && task.data==&token && !ports_released && task.unrefs==1);
}

int main(void){
 for(radio_mask=0;radio_mask<4;radio_mask++)
  for(int first=0;first<2;first++)for(int second=0;second<2;second++)for(unsigned own=0;own<2;own++)check(first,second,own);
 radio_mask=3;
 CardsOnContext ctx={0};ctx.present[0]=ctx.present[1]=1;GTask task={.data=&ctx};MMBaseModem modem=0;
 GAsyncResult absent={NULL,10},busy={NULL,14};
 cards_on_probe_ready(&modem,&absent,&task);assert(!ctx.present[0] && ctx.probe==1);
 cards_on_probe_ready(&modem,&busy,&task);assert(ctx.present[1] && ctx.probe==2);
 assert(sequenced==32 && next==2);
 failed_modes();fail_each_command();power_queries();
 radio_mask=0;
 GTask blocked={0};GAsyncResult powered={"+CFUN: 4",0};power_commands=radio_on=0;
 power_up_cfun_ready(&modem,&powered,&blocked);
 assert(blocked.error==MM_CORE_ERROR_WRONG_STATE && blocked.unrefs==1 && !power_commands && !radio_on);
 radio_mask=2;blocked=(GTask){0};
 power_up_cfun_ready(&modem,&powered,&blocked);
 assert(blocked.returned && !blocked.error && blocked.unrefs==1 && !power_commands && !radio_on);
 // A disabled own stack reporting 0 must not reinitialize a live peer.
 radio_mask=2;int token=1;GTask warm={.data=&token};GAsyncResult zero={"+CFUN: 0",0};
 radio_on=power_commands=0;init_cfun_ready(&modem,&zero,&warm);
 assert(power_commands==1 && !strcmp(last_command,"+SPACTCARD=1;+CFUN?") && !radio_on);
 GAsyncResult no_sim={NULL,10};
 GAsyncResult peer={"+CFUN: 1",0};init_peer_cfun_ready(&modem,&peer,&warm);
 assert(warm.returned && warm.unrefs==1 && !radio_on && !warm.error);
 warm=(GTask){.data=&token};peer=(GAsyncResult){"+CFUN: 0",0};radio_on=0;
 init_peer_cfun_ready(&modem,&peer,&warm);assert(radio_on==1 && !warm.error);
 warm=(GTask){.data=&token};peer=(GAsyncResult){"bad",0};ports_released=0;
 init_peer_cfun_ready(&modem,&peer,&warm);assert(warm.error && warm.unrefs==1 && ports_released==1);
 radio_mask=0;warm=(GTask){.data=&token};radio_on=power_commands=0;
 init_cfun_ready(&modem,&zero,&warm);assert(!warm.returned && !radio_on && power_commands==1);
 peer=(GAsyncResult){"+CFUN: 0",0};init_peer_cfun_ready(&modem,&peer,&warm);
 assert(radio_on==1 && !warm.error);
 GAsyncResult powered_sim={"+CPIN: READY",0};
 // Even with both radios allowed, a live peer must restore the owner.
 radio_mask=3;warm=(GTask){.data=&token};radio_on=0;peer=(GAsyncResult){"+CFUN: 1",0};
 init_peer_cfun_ready(&modem,&peer,&warm);assert(warm.returned && !radio_on && !warm.error);
 // Re-enable a powered RF-off SIM without resetting the other stack.
 radio_mask=3;warm=(GTask){0};radio_on=power_commands=0;
 power_up_cpin_ready(&modem,&powered_sim,&warm);
 assert(!radio_on && power_commands==1 && !strcmp(last_command,"+SFUN=4"));
 warm=(GTask){0};radio_on=power_commands=0;power_up_cpin_ready(&modem,&no_sim,&warm);
 assert(radio_on==1 && !power_commands && !warm.error);
 warm=(GTask){0};radio_on=power_commands=0;power_up_cpin_ready(&modem,&busy,&warm);
 assert(warm.error && !radio_on && !power_commands);
 radio_mask=0;warm=(GTask){0};power_commands=radio_on=0;
 power_up_cpin_ready(&modem,&powered_sim,&warm);assert(warm.error && !power_commands && !radio_on);
 radio_mask=2;warm=(GTask){0};power_up_cpin_ready(&modem,&powered_sim,&warm);
 assert(warm.returned && !warm.error && !power_commands && !radio_on);
 warm=(GTask){0};power_commands=0;modem_power_down(&modem,NULL,NULL);
 assert(power_commands==1 && !strcmp(last_command,"+SFUN=5"));
 puts("SIM power checks passed: 8 slot/preference plans, absent vs busy, vendor order, mandatory failure at all 8 steps, invalid mode/CFUN rejection, init port cleanup");
}
'''
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    (root / 'test.c').write_text(model + processor +
                               function('cards_on_response','MMBaseModemAtResponseProcessorResult') +
                               function('cards_on_sequence_ready') +
                               function('power_parse_uint', 'gboolean') +
                               function('power_parse_cfun', 'gboolean') +
                               function('cards_on_testmode_ready') + function('cards_on_probe_ready') +
                               function('init_power_failed') + function('init_sim_on_ready') +
                               function('init_radio_policy_ready') + function('init_apply_radio_policy') +
                               function('init_peer_cfun_ready') + function('init_cfun_ready') +
                               function('power_up_cpin_ready') + function('power_up_cfun_ready') + function('modem_power_down') + tests)
    subprocess.run(['cc', '-D_GNU_SOURCE', '-Wall', '-Werror', str(root / 'test.c'), '-o', str(root / 'test')], check=True)
    subprocess.run([str(root / 'test')], check=True)
