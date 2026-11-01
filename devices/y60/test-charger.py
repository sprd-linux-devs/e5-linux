#!/usr/bin/env python3
"""Execute the actual Y60 charger callbacks with mocked I2C/PMIC/work queues.

No sysfs/device access. Extract production functions rather than copying the
register algorithms into a second implementation. Run inside WSL with cc.
"""
from pathlib import Path
import argparse
import re
import runpy
import subprocess
import tempfile

HERE=Path(__file__).resolve().parent
def function(source,name):
    match=re.search(r'^static (?:int|void|u8|bool)(?: __maybe_unused)?\s+'+
                    name+r'\([^;{}]*\)\s*\{',source,re.M)
    if not match:raise ValueError('Missing production function: '+name)
    at=source.index('{',match.start());end=at+1;depth=1
    while depth:
        depth+=(source[end]=='{')-(source[end]=='}');end+=1
    return source[match.start():end]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--kernel',type=Path)
    args=p.parse_args()
    path=(args.kernel/'drivers/power/supply/eta6937-charger.c') if args.kernel else HERE/'eta6937-charger.c'
    source=path.read_text(encoding='utf-8')
    policy=runpy.run_path(str(HERE/'charger.py'))['dcp_charge_policy']
    native=('int sprd_battery_get_battery_info(void) {\n'
            '\tsprd_battery_parse_step_chg_table(info, battery_np, psy);\n}\n')
    changed=policy(native)
    assert policy(changed)==changed
    assert changed.count('y60_dcp_profile(info)')==1
    assert changed.index('sprd_battery_parse_step_chg_table')<changed.index('y60_dcp_profile(info)')
    for bad in ('unknown',native.replace('sprd_battery_parse_step_chg_table','unknown')):
        try:policy(bad)
        except ValueError:pass
        else:raise AssertionError('Unrecognized battery parser accepted')
    profile=(HERE/'charge-profile.h').read_text()
    if args.kernel:
        assert (args.kernel/'drivers/power/supply/y60-charge-profile.h').read_text()==profile
        prepared=(args.kernel/'drivers/power/supply/sprd_battery_info.c').read_text()
        assert policy(prepared)==prepared and prepared.count('y60_dcp_profile(info)')==1
    constants='\n'.join(re.findall(r'^#define ETA_.*$',source,re.M))
    tables='\n'.join(re.findall(r'static const u32 eta_(?:iin|safety_current)\[\] = \{.*?\n\};',source,re.S))
    names=('eta_read','eta_update','eta_floor','eta_safety_code','eta_set_input','eta_set_current',
           'eta_get_current','eta_set_voltage','eta_charge','eta_feed','eta_watching',
           'eta_watchdog_work','eta_otg_work','eta_get','eta_set','eta_writeable',
           'eta_enable_otg','eta_disable_otg','eta_otg_enabled','eta_hw_init','eta_stop',
           'eta_suspend','eta_resume')
    bodies='\n'.join(function(source,name) for name in names)
    prelude=r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
typedef uint8_t u8; typedef uint32_t u32;
#define BIT(n) (1U<<(n))
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define min(a,b) ((a)<(b)?(a):(b))
#define min_t(t,a,b) min((t)(a),(t)(b))
#define clamp_val(v,l,h) ((v)<(l)?(l):((v)>(h)?(h):(v)))
#define container_of(p,t,m) ((t*)((char*)(p)-offsetof(t,m)))
#define __maybe_unused
#define HZ 250
#define msecs_to_jiffies(x) (x)
#define dev_err_ratelimited(...) ((void)0)
#define dev_err(...) ((void)0)
#define dev_err_probe(d,r,...) (r)
#define CM_FAST_CHARGE_NORMAL_CMD 2
#define EXTCON_USB 1
#define POWER_SUPPLY_STATUS_CHARGING 1
#define POWER_SUPPLY_STATUS_NOT_CHARGING 3
#define POWER_SUPPLY_HEALTH_GOOD 1
#define POWER_SUPPLY_HEALTH_UNKNOWN 0
enum power_supply_property { POWER_SUPPLY_PROP_STATUS, POWER_SUPPLY_PROP_PRESENT,
 POWER_SUPPLY_PROP_CONSTANT_CHARGE_CURRENT, POWER_SUPPLY_PROP_INPUT_CURRENT_LIMIT,
 POWER_SUPPLY_PROP_CONSTANT_CHARGE_VOLTAGE_MAX, POWER_SUPPLY_PROP_HEALTH };
union power_supply_propval {int intval;};
struct mutex {bool held;};
static void mutex_lock(struct mutex *m) {assert(!m->held);m->held=true;}
static void mutex_unlock(struct mutex *m) {assert(m->held);m->held=false;}
struct work_struct {int dummy;};
struct delayed_work {struct work_struct work;bool queued;void (*fn)(struct work_struct*);unsigned delay;};
#define to_delayed_work(p) container_of(p,struct delayed_work,work)
struct alarm {bool armed;};
struct regmap {u32 bits;};
struct gpio_desc {int value;};
struct extcon_dev {int state;};
struct i2c_client {int dummy;};
struct device {void *data;};
struct power_supply {void *data;};
struct regulator_dev {void *data;};
struct eta6937 {
 struct device *dev;struct i2c_client *client;struct power_supply *psy;
 struct regmap *pmic;struct gpio_desc *enable_gpio;struct extcon_dev *edev;
 struct mutex control,io;struct delayed_work watchdog,otg_check;struct alarm alarm;
 u32 detect_reg,pd_reg,pd_mask,battery_max_mv;
 bool ready,charging,online,boost,stopping,suspended;
};
static struct eta6937 *live;
static u8 regs[8];
static int read_error=-1,write_error=-1,pmic_error,reads,writes,pmic_writes,cancels;
static void *system_wq;
static int i2c_smbus_read_byte_data(struct i2c_client *c,u8 reg) {
 (void)c;assert(reg<8);reads++;return reg==read_error?-EIO:regs[reg];
}
static int i2c_smbus_write_byte_data(struct i2c_client *c,u8 reg,u8 value) {
 (void)c;assert(reg<8);writes++;if(reg==write_error)return -EIO;
 if(reg==4)value&=~BIT(7); /* self-clearing reset bit */
 regs[reg]=value;return 0;
}
static int regmap_update_bits(struct regmap *m,u32 reg,u32 mask,u32 value) {
 (void)reg;pmic_writes++;if(pmic_error)return -EIO;
 m->bits=(m->bits&~mask)|(value&mask);return 0;
}
static void gpiod_set_value_cansleep(struct gpio_desc *g,int value) {g->value=value;}
static int extcon_get_state(struct extcon_dev *e,int id) {(void)id;return e->state;}
static bool schedule_delayed_work(struct delayed_work *w,unsigned delay) {w->queued=true;w->delay=delay;return true;}
static bool mod_delayed_work(void *q,struct delayed_work *w,unsigned delay) {(void)q;return schedule_delayed_work(w,delay);}
static bool cancel_delayed_work_sync(struct delayed_work *w) {
 /* Simulate an in-flight worker joining the cancellation. Taking io here
  * detects a synchronous cancellation while that same mutex is held. */
 assert(!live->io.held);cancels++;w->queued=false;
 if(w->fn)w->fn(&w->work);
 assert(!w->queued);return true;
}
static void *power_supply_get_drvdata(struct power_supply *p) {return p->data;}
static void *rdev_get_drvdata(struct regulator_dev *r) {return r->data;}
static void *dev_get_drvdata(struct device *d) {return d->data;}
static void alarm_cancel(struct alarm *a) {a->armed=false;}
static int ktime_set(int s,int n) {(void)n;return s;}
static void alarm_start_relative(struct alarm *a,int time) {(void)time;a->armed=true;}
#define SPRD_BATTERY_JEITA_DCP 0
struct sprd_battery_jeita_table {int temp,recovery_temp,current_ua,term_volt;};
struct sprd_battery_info {
 int constant_charge_voltage_max_uv,charge_full_design_uah,voltage_min_design_uv,constant_charge_current_max_ua;
 struct {int unknown_cur,dcp_cur,dcp_limit,sdp_cur,sdp_limit,cdp_cur,cdp_limit,unknown_limit;} cur;
 struct sprd_battery_jeita_table *jeita_table[4];
 unsigned int sprd_battery_jeita_size[4],max_current_jeita_index[4];
};
static struct sprd_battery_info battery;
static int battery_error,battery_puts;
static int sprd_battery_get_battery_info(struct power_supply *p,struct sprd_battery_info *b) {(void)p;*b=battery;return battery_error;}
static void sprd_battery_put_battery_info(struct power_supply *p,struct sprd_battery_info *b) {(void)p;(void)b;battery_puts++;}
'''
    tests=r'''
static struct eta6937 eta;
static struct power_supply psy;
static struct regulator_dev rdev;
static struct device dev;
static struct regmap pmic;
static void reset(void) {
 memset(&eta,0,sizeof(eta));memset(regs,0,sizeof(regs));memset(&pmic,0,sizeof(pmic));
 live=&eta;psy.data=&eta;rdev.data=&eta;dev.data=&eta;eta.dev=&dev;eta.psy=&psy;
 eta.pmic=&pmic;eta.pd_mask=1;eta.battery_max_mv=4340;eta.ready=true;
 eta.watchdog.fn=eta_watchdog_work;eta.otg_check.fn=eta_otg_work;
 read_error=write_error=-1;pmic_error=reads=writes=pmic_writes=cancels=0;
 battery=(struct sprd_battery_info){.constant_charge_voltage_max_uv=4340000,
  .cur={.unknown_cur=1050000,.dcp_cur=11500000,.dcp_limit=1150000}};
 battery_error=battery_puts=0;
}
static int set(enum power_supply_property p,int v) {union power_supply_propval x={.intval=v};return eta_set(&psy,p,&x);}
static int get(enum power_supply_property p) {union power_supply_propval x={.intval=-999};assert(!eta_get(&psy,p,&x));return x.intval;}
static void run(struct delayed_work *w) {w->queued=false;w->fn(&w->work);}
int main(void) {
 /* Exhaust every code/boundary, including neighboring non-current bits. */
 reset();
 for(u32 ua=0;ua<=3300000;ua+=1000) {
  regs[4]=0x0b;regs[5]=0x2d;assert(!eta_set_current(&eta,ua));
  int actual;assert(!eta_get_current(&eta,&actual));
  assert(actual==(int)(550000+(clamp_val(ua,550000U,3050000U)-550000)/100000*100000));
  assert((regs[4]&0x0f)==0x0b && (regs[5]&0x3f)==0x2d);
  u8 safety=eta_safety_code(ua);
  assert(eta_safety_current[safety]>=(u32)actual);
  assert(!safety || eta_safety_current[safety-1]<(u32)actual);
 }
 for(u32 ua=0;ua<12000000;ua+=1000) {
  regs[7]=0xb8;assert(!eta_set_input(&eta,ua));assert((regs[7]&0xf8)==0xb8);
  assert(eta_iin[regs[7]&7]<=ua || ua<eta_iin[0]);
  if((regs[7]&7)<7)assert(ua<eta_iin[(regs[7]&7)+1]);
 }
 for(u32 mv=3000;mv<=4800;mv++) {
  regs[2]=3;assert(!eta_set_voltage(&eta,mv));assert((regs[2]&3)==3);
  assert(3500U+(regs[2]>>2)*20==(clamp_val(mv,3500U,4340U)-3500)/20*20+3500);
 }
 reset();assert(!eta_hw_init(&eta));assert(battery_puts==1);
 assert((regs[6]&0x0f)==7 && (regs[6]>>4)==13);
 assert((regs[2]>>2)==42 && (regs[7]&0x0f)==10);
 u8 prior[8];memcpy(prior,regs,8);assert(!eta_feed(&eta));
 for(int i=1;i<8;i++)assert(regs[i]==prior[i]);
 /* The real stock DCP fields are CC=11.5 A (anomalous), input=1.15 A.
  * The Y60 policy normalizes both without changing another USB type. */
 reset();
 struct sprd_battery_jeita_table rows[]={
  {0,30,0,4400000},{150,180,700000,4400000},
  {450,420,1150000,4400000},{570,550,700000,4100000}};
 struct sprd_battery_jeita_table original[4];memcpy(original,rows,sizeof(rows));
 battery.charge_full_design_uah=3050000;battery.voltage_min_design_uv=3413000;
 battery.constant_charge_current_max_ua=-EINVAL;
 battery.cur.sdp_cur=battery.cur.sdp_limit=500000;
 battery.cur.cdp_cur=battery.cur.cdp_limit=1500000;
 battery.cur.unknown_limit=1050000;
 battery.jeita_table[0]=rows;battery.sprd_battery_jeita_size[0]=4;
 struct sprd_battery_info native=battery;
 assert(y60_dcp_profile(&battery));
 assert(battery.cur.dcp_cur==2500000 && battery.cur.dcp_limit==2500000);
 assert(battery.constant_charge_current_max_ua==2500000 && battery.max_current_jeita_index[0]==2);
 assert(battery.cur.sdp_cur==500000 && battery.cur.sdp_limit==500000);
 assert(battery.cur.cdp_cur==1500000 && battery.cur.cdp_limit==1500000);
 assert(battery.cur.unknown_cur==1050000 && battery.cur.unknown_limit==1050000);
 for(int i=0;i<4;i++){
  assert(rows[i].temp==original[i].temp && rows[i].recovery_temp==original[i].recovery_temp);
  assert(rows[i].term_volt==original[i].term_volt);
  assert(rows[i].current_ua==(i==2?2500000:original[i].current_ua));
 }
 assert(!eta_hw_init(&eta));assert((regs[6]>>4)==10 && (regs[6]&15)==7);
 assert(!eta_set_input(&eta,battery.cur.dcp_limit));assert(eta_iin[regs[7]&7]==2000000);
 assert(!eta_set_current(&eta,battery.cur.dcp_cur));int actual;
 assert(!eta_get_current(&eta,&actual) && actual==2450000);
 /* User stop/current controls and hot/cold voltage/current still apply. */
 assert(!eta_set_current(&eta,700000));assert(!eta_get_current(&eta,&actual) && actual==650000);
 assert(!eta_set_voltage(&eta,4100));assert(3500+(regs[2]>>2)*20==4100);
 assert(!y60_dcp_profile(&battery));
 for(int n=0;n<8+4*4;n++) {
  battery=native;memcpy(rows,original,sizeof(rows));
  switch(n){
  case 0:battery.charge_full_design_uah++;break;
  case 1:battery.constant_charge_voltage_max_uv++;break;
  case 2:battery.voltage_min_design_uv++;break;
  case 3:battery.cur.dcp_cur++;break;
  case 4:battery.cur.dcp_limit++;break;
  case 5:battery.jeita_table[0]=NULL;break;
  case 6:battery.sprd_battery_jeita_size[0]--;break;
  case 7:battery.sprd_battery_jeita_size[0]++;break;
  default:{int r=(n-8)/4;switch((n-8)%4){
   case 0:rows[r].temp++;break;case 1:rows[r].recovery_temp++;break;
   case 2:rows[r].current_ua++;break;case 3:rows[r].term_volt++;break;
  }} }
  struct sprd_battery_info saved=battery;
  struct sprd_battery_jeita_table saved_rows[4];memcpy(saved_rows,rows,sizeof(rows));
  assert(!y60_dcp_profile(&battery));
  assert(!memcmp(&saved,&battery,sizeof(battery)) && !memcmp(saved_rows,rows,sizeof(rows)));
 }
 reset();battery_error=-517;assert(eta_hw_init(&eta)==-517);assert(writes==0);
 reset();battery.constant_charge_voltage_max_uv=0;assert(eta_hw_init(&eta)==-EINVAL);assert(writes==0);
 reset();battery.constant_charge_voltage_max_uv=4500000;assert(eta_hw_init(&eta)==-EINVAL);assert(writes==0);
 reset();battery.cur.dcp_cur=-1;assert(eta_hw_init(&eta)==-EINVAL);assert(writes==0);
 reset();battery.cur.unknown_cur=-1;assert(eta_hw_init(&eta)==-EINVAL);assert(writes==0);
 /* NCE must remain distinct from OPA. Failed gate writes cannot report ON. */
 reset();regs[1]=ETA_NCE|ETA_OPA;assert(!set(POWER_SUPPLY_PROP_STATUS,1));
 assert(eta.charging && (regs[1]&ETA_OPA) && !(regs[1]&ETA_NCE));
 assert(!set(POWER_SUPPLY_PROP_STATUS,0));assert(!eta.charging && (regs[1]&ETA_NCE));
 reset();write_error=1;assert(set(POWER_SUPPLY_PROP_STATUS,1)==-EIO);assert(!eta.charging);
 reset();pmic_error=1;assert(set(POWER_SUPPLY_PROP_STATUS,1)==-EIO);assert(writes==0);
 reset();struct gpio_desc gpio={.value=1};eta.enable_gpio=&gpio;
 assert(!set(POWER_SUPPLY_PROP_STATUS,1));assert(gpio.value==0 && pmic_writes==0);
 assert(!set(POWER_SUPPLY_PROP_STATUS,0));assert(gpio.value==1);
 reset();assert(set(POWER_SUPPLY_PROP_CONSTANT_CHARGE_CURRENT,-1)==-EINVAL);assert(writes==0);
 /* Watchdog lifetime: plug, unplug, OTG, failure, suspend and teardown. */
 reset();assert(!set(POWER_SUPPLY_PROP_PRESENT,1));assert(eta.watchdog.queued);
 run(&eta.watchdog);assert(eta.watchdog.queued && eta.watchdog.delay==15*HZ);
 write_error=0;run(&eta.watchdog);assert(eta.watchdog.delay==5*HZ);write_error=-1;
 assert(!set(POWER_SUPPLY_PROP_PRESENT,0));assert(!eta.watchdog.queued && cancels==1);
 reset();regs[1]=ETA_NCE;assert(!eta_enable_otg(&rdev));assert(eta.boost && eta_otg_enabled(&rdev)==1);
 assert((regs[1]&ETA_NCE) && (pmic.bits&ETA_BC_DISABLE));
 assert(eta.watchdog.queued && eta.otg_check.queued);
 int count=writes;run(&eta.otg_check);assert(writes==count && eta.otg_check.queued);
 assert(!set(POWER_SUPPLY_PROP_PRESENT,0));assert(eta.watchdog.queued && cancels==0);
 assert(!eta_disable_otg(&rdev));assert(!eta.boost && !eta.watchdog.queued && !eta.otg_check.queued);
 assert(!(pmic.bits&ETA_BC_DISABLE) && (regs[1]&ETA_NCE));
 reset();assert(!set(POWER_SUPPLY_PROP_PRESENT,1));assert(!eta_enable_otg(&rdev));
 assert(!eta_disable_otg(&rdev));assert(eta.watchdog.queued && !eta.otg_check.queued);
 reset();write_error=1;assert(eta_enable_otg(&rdev)==-EIO);assert(!eta.boost && !pmic.bits);
 assert(!eta.watchdog.queued && !eta.otg_check.queued);
 reset();assert(!eta_enable_otg(&rdev));write_error=1;
 assert(eta_disable_otg(&rdev)==-EIO);assert(eta.boost && eta.watchdog.queued);
 reset();assert(!eta_enable_otg(&rdev));assert(!eta_suspend(&dev));
 assert(eta.suspended && eta.alarm.armed && !eta.watchdog.queued && !eta.otg_check.queued);
 assert(!eta_resume(&dev));assert(!eta.suspended && !eta.alarm.armed);
 assert(eta.watchdog.queued && eta.otg_check.queued);
 eta_stop(&eta);assert(eta.stopping && !eta.ready && !eta.boost);
 assert(!eta.watchdog.queued && !eta.otg_check.queued && !eta.alarm.armed);
 count=writes;assert(set(POWER_SUPPLY_PROP_PRESENT,1)==-EAGAIN);
 assert(eta_enable_otg(&rdev)==-EAGAIN);assert(count==writes);
 /* Read/write error propagation and warm-limit requests. */
 reset();assert(!set(POWER_SUPPLY_PROP_STATUS,1));assert(!set(POWER_SUPPLY_PROP_CONSTANT_CHARGE_VOLTAGE_MAX,4440000));
 assert(get(POWER_SUPPLY_PROP_CONSTANT_CHARGE_VOLTAGE_MAX)==4340000);
 assert(!set(POWER_SUPPLY_PROP_CONSTANT_CHARGE_VOLTAGE_MAX,4100000));
 assert(get(POWER_SUPPLY_PROP_CONSTANT_CHARGE_VOLTAGE_MAX)==4100000);
 read_error=7;union power_supply_propval x;
 assert(eta_get(&psy,POWER_SUPPLY_PROP_INPUT_CURRENT_LIMIT,&x)==-EIO);
 read_error=-1;write_error=5;assert(set(POWER_SUPPLY_PROP_CONSTANT_CHARGE_CURRENT,1550000)==-EIO);
 assert(eta_writeable(&psy,POWER_SUPPLY_PROP_PRESENT));
 assert(!eta_writeable(&psy,POWER_SUPPLY_PROP_HEALTH));
 puts("Y60 ETA production callbacks: DCP policy/thermal isolation, safety steps, register boundaries, I/O faults, DT voltage, charging/OTG/work/PM lifecycle PASS");
 return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix='y60-eta-test-') as tmp:
        directory=Path(tmp);c=directory/'check.c';exe=directory/'check'
        c.write_text(prelude+'\n'+constants+'\n'+tables+'\n'+bodies+'\n'+profile+'\n'+tests)
        subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-parameter',
                        '-fsanitize=undefined','-fno-sanitize-recover=all',str(c),'-o',str(exe)],check=True)
        subprocess.run([str(exe)],check=True)


if __name__=='__main__':
    main()
