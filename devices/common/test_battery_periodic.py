#!/usr/bin/env python3
"""Run a prepared CM's whole periodic SOC worker, including rescheduling/errors.

Pass each model's actual prepared source directory. This is an offline mocked
bus/workqueue test, not a charge-cycle or accuracy validation on hardware.
"""
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
extract = runpy.run_path(str(HERE/'test_fuel_gauge.py'))['function']
source = (Path(sys.argv[1])/'drivers/power/supply/charger-manager.c').read_text()
body = extract(source, 'cm_batt_works')
prelude = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <errno.h>
#include <stdio.h>
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define to_delayed_work(p) container_of(p,struct delayed_work,work)
#define dev_info(...) ((void)0)
#define dev_warn(...) ((void)0)
#define dev_err(...) ((void)0)
#define dev_dbg(...) ((void)0)
#define CM_MAGIC_NUM (-1)
#define CM_CAP_CYCLE_TRACK_TIME_15S 15
#define CM_LOW_TEMP_REGION 0
#define CM_LOW_TEMP_SHUTDOWN_VALTAGE 3200000
#define CM_CAP_FULL_PERCENT 1000
#define CM_UVLO_CALIBRATION_VOLTAGE_THRESHOLD 3300000
#define CM_UVLO_CALIBRATION_CNT_THRESHOLD 3
#define CM_HCAP_THRESHOLD 995
#define CM_HCAP_DECREASE_STEP 8
#define CM_CAP_ONE_PERCENT 10
#define CM_FORCE_SET_FUEL_CAP_FULL 1000
#define HZ 100
#define READ_ONCE(v) (v)
#define DIV_ROUND_CLOSEST(n,d) (((n)+(d)/2)/(d))
#define clamp(n,lo,hi) ((n)<(lo)?(lo):((n)>(hi)?(hi):(n)))
#define msecs_to_jiffies(n) (n)
enum {POWER_SUPPLY_STATUS_CHARGING=1,POWER_SUPPLY_STATUS_DISCHARGING,
 POWER_SUPPLY_STATUS_NOT_CHARGING,POWER_SUPPLY_STATUS_FULL};
struct work_struct {int unused;};
struct delayed_work {struct work_struct work;};
struct timespec64 {int tv_sec;};
struct desc {
 int cap,temperature,charger_type,low_temp_trigger_cnt,trickle_time,trickle_start_time,
 trickle_time_out,cap_one_time,update_capacity_time,last_query_time,charger_status,
 fullbatt_uV,fullbatt_vchkdrop_uV,uvlo_trigger_cnt;
 bool force_set_full;
 struct {bool cp_running;} cp;
};
struct charger_manager {struct delayed_work cap_update_work,uvlo_work;
 struct desc *desc;int battery_status,charger_psy,dev;bool shutdown_flag;};
static int now,raw,amps=600000,fail,queues,changes,saves,reads;
static bool online=true,charging=true,full;
static int system_unbound_wq,system_power_efficient_wq;
static struct timespec64 ktime_to_timespec64(int value){return (struct timespec64){value};}
static int ktime_get_boottime(void){return now;}
static int voltage(struct charger_manager *c,int *v){(void)c;*v=3800000;return fail==1?-EIO:0;}
static int get_vbat_now_uV(struct charger_manager *c,int *v){return voltage(c,v);}
static int get_vbat_avg_uV(struct charger_manager *c,int *v){return voltage(c,v);}
static int get_batt_ocv(struct charger_manager *c,int *v){(void)c;*v=3800000;return fail==2?-EIO:0;}
static int get_ibat_now_uA(struct charger_manager *c,int *v){(void)c;*v=amps;return fail==3?-EIO:0;}
static int get_ibat_avg_uA(struct charger_manager *c,int *v){return get_ibat_now_uA(c,v);}
static int get_batt_cap(struct charger_manager *c,int *v){(void)c;reads++;*v=raw;return fail==4?-EIO:0;}
static int zero(struct charger_manager *c,int *v){(void)c;*v=0;return 0;}
#define get_constant_charge_current zero
#define get_input_current_limit zero
#define get_cp_ibus_uA zero
#define get_charger_input_current zero
#define get_charger_voltage zero
#define get_charger_term_voltage zero
#define cm_get_board_temperature zero
static int cm_get_battery_temperature(struct charger_manager *c,int *v){(void)c;*v=250;return fail==5?-EIO:0;}
static bool is_full_charged(struct charger_manager *c){(void)c;return full;}
static bool is_charging(struct charger_manager *c){(void)c;return charging;}
static bool is_ext_pwr_online(struct charger_manager *c){(void)c;return online;}
static int cm_calc_batt_works_cycle(struct charger_manager *c,int v){(void)c;(void)v;return 15;}
static int set_batt_cap(struct charger_manager *c,int v){assert(c->desc->cap==v);saves++;return 0;}
static void power_supply_changed(int p){(void)p;changes++;}
static void queue_delayed_work(int q,struct delayed_work *w,int delay){
 (void)q;(void)w;assert(delay==15*HZ);queues++;
}
'''
if 'cm_cap_advance_full(' in body:
    prelude += 'static int cm_cap_advance_full(struct charger_manager *c,int v){(void)c;return v;}\n'
tests = r'''
static struct desc d;
static struct charger_manager cm={.desc=&d};
static void reset(int cap){
 d=(struct desc){.cap=cap,.cap_one_time=30,.fullbatt_uV=4400000,.fullbatt_vchkdrop_uV=100000};
 now=0;raw=cap;amps=600000;fail=queues=changes=saves=reads=0;
 online=charging=true;full=cm.shutdown_flag=false;
}
static void tick(void){int old=queues;now+=15;cm_batt_works(&cm.cap_update_work.work);assert(queues==old+1);}
int main(void){
 /* Repeated updates without any cable/status transition, at both reported SOCs. */
 const int levels[]={20,40,400,800};
 for(unsigned n=0;n<sizeof(levels)/sizeof(*levels);n++){
  reset(levels[n]);
  for(int i=0;i<20;i++){raw+=2;tick();}
  assert(d.cap>levels[n]&&saves>0&&changes>0&&reads==20);
  online=charging=false;amps=-400000;
  int start=d.cap;raw=start;
  for(int i=0;i<20;i++){raw-=2;tick();}
  assert(d.cap<start&&d.charger_status==POWER_SUPPLY_STATUS_DISCHARGING);
 }
 /* A misclassified charging state holds the UI by design, not a dead worker. */
 reset(20);charging=false;raw=100;
 for(int i=0;i<20;i++)tick();
 assert(d.cap==20&&reads==20&&!saves&&queues==20);
 charging=true;for(int i=0;i<20;i++)tick();assert(d.cap>20);
 /* A lower retained UI can legitimately hold until the measured SOC catches it. */
 reset(800);charging=online=false;amps=-100000;raw=900;
 for(int i=0;i<50;i++){raw-=2;tick();assert(d.cap==800);}
 for(int i=0;i<10;i++){raw-=2;tick();}assert(d.cap<800);
 /* Unknown charger type is not an early-return condition in this worker. */
 reset(800);raw=790;charging=online=false;amps=-100000;
 for(int i=0;i<4;i++)tick();assert(d.cap<800);
 /* Transient critical reads must requeue, then recover without a replug. */
 for(int f=1;f<=5;f++){
  reset(40);raw=60;fail=f;tick();assert(d.cap==40&&!saves);
  fail=0;for(int i=0;i<4;i++)tick();assert(d.cap>40);
 }
 reset(800);full=true;raw=1000;tick();assert(d.cap>800);
 reset(800);cm.shutdown_flag=true;now=15;
 cm_batt_works(&cm.cap_update_work.work);assert(!queues);
 puts("PASS: full CM worker, unchanged-state charge/discharge at 2/4/40/80%, false Not-charging hold, five read failures/recovery, full and shutdown");
 return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='cm-periodic-') as tmp:
    root = Path(tmp)
    c = root/'test.c'
    c.write_text(prelude + body + tests)
    subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-Wno-unused-but-set-variable', '-Wno-unused-function',
                    str(c), '-o', str(root/'test')], check=True)
    subprocess.run([str(root/'test')], check=True)
