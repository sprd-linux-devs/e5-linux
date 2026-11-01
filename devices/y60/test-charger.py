#!/usr/bin/env python3
"""Execute the actual Y60 charger callbacks with mocked I2C/PMIC/work queues.

No sysfs/device access. Extract production functions rather than copying the
register algorithms into a second implementation. Run inside WSL with cc.
"""
from pathlib import Path
import argparse
import re
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
    constants='\n'.join(re.findall(r'^#define ETA_.*$',source,re.M))
    tables='\n'.join(re.findall(r'static const u32 eta_(?:iin|safety_current)\[\] = \{.*?\n\};',source,re.S))
    names=('eta_read','eta_update','eta_floor','eta_set_input','eta_set_current',
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
struct sprd_battery_info {int constant_charge_voltage_max_uv;struct {int unknown_cur,dcp_cur;} cur;};
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
 battery=(struct sprd_battery_info){4340000,{1050000,1150000}};
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
 assert((regs[6]&0x0f)==7 && (regs[6]>>4)==3);
 assert((regs[2]>>2)==42 && (regs[7]&0x0f)==10);
 u8 prior[8];memcpy(prior,regs,8);assert(!eta_feed(&eta));
 for(int i=1;i<8;i++)assert(regs[i]==prior[i]);
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
 puts("Y60 ETA production callbacks: register boundaries, I/O faults, DT voltage, charging/OTG/work/PM lifecycle PASS");
 return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix='y60-eta-test-') as tmp:
        directory=Path(tmp);c=directory/'check.c';exe=directory/'check'
        c.write_text(prelude+'\n'+constants+'\n'+tables+'\n'+bodies+'\n'+tests)
        subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-parameter',
                        '-fsanitize=undefined','-fno-sanitize-recover=all',str(c),'-o',str(exe)],check=True)
        subprocess.run([str(exe)],check=True)


if __name__=='__main__':
    main()
