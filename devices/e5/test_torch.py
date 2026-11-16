#!/usr/bin/env python3
"""Compile the actual torch driver against GPIO/probe/lifecycle fixtures."""
from pathlib import Path
import re
import subprocess
import tempfile

source = (Path(__file__).parent / 'port/torch/e5-aw3641-torch.c').read_text()
source = re.sub(r'^#include.*\n', '', source, flags=re.M)
source = source[:source.index('static const struct of_device_id')]
prelude = r'''
#include <assert.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include <stddef.h>
#include <string.h>
typedef unsigned int u32;
enum led_brightness {LED_OFF=0,LED_ON=1};
struct gpio_desc {int id,value;};
struct mutex {bool held;};
struct led_classdev {const char *name;int max_brightness;
 int (*brightness_set_blocking)(struct led_classdev *,enum led_brightness);};
struct device {int chip,index,chip_error,index_error,gpio_error,register_error;};
struct platform_device {struct device dev;void *data;};
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define GFP_KERNEL 0
#define GPIOD_OUT_LOW 0
#define ENODEV 19
#define ENOMEM 12
#define IS_ERR(p) ((uintptr_t)(p)>=(uintptr_t)-4095)
#define PTR_ERR(p) ((intptr_t)(p))
static struct gpio_desc mode={.id=1},enable={.id=2};
static int trace[256],count,acquired,allocation;
static void *last_allocation;
static void (*cleanup)(void *);static void *cleanup_data;
static void mutex_init(struct mutex *m) {m->held=false;}
static void mutex_lock(struct mutex *m) {assert(!m->held);m->held=true;}
static void mutex_unlock(struct mutex *m) {assert(m->held);m->held=false;}
static void gpiod_set_value_cansleep(struct gpio_desc *g,int v) {
 assert(count<256);trace[count++]=g->id*10+v;g->value=v;
}
static int device_property_read_u32(struct device *d,const char *key,u32 *value) {
 int error=!strcmp(key,"flash-ic")?d->chip_error:d->index_error;
 if(error)return error;
 *value=!strcmp(key,"flash-ic")?d->chip:d->index;return 0;
}
static void *devm_kzalloc(struct device *d,size_t size,int flags) {
 (void)d;(void)flags;allocation++;return last_allocation=calloc(1,size);
}
static struct gpio_desc *devm_gpiod_get(struct device *d,const char *name,int flags) {
 struct gpio_desc *g=!strcmp(name,"flash-torch-en")?&mode:&enable;
 assert(!flags);acquired++;
 if(d->gpio_error==g->id)return (void *)(intptr_t)-517;
 gpiod_set_value_cansleep(g,0);return g;
}
static int dev_err_probe(struct device *d,int error,const char *message) {
 (void)d;(void)message;return error;
}
static void platform_set_drvdata(struct platform_device *p,void *data){p->data=data;}
static void *platform_get_drvdata(struct platform_device *p){return p->data;}
static int devm_add_action_or_reset(struct device *d,void (*fn)(void *),void *data) {
 (void)d;cleanup=fn;cleanup_data=data;return 0;
}
static int devm_led_classdev_register(struct device *d,struct led_classdev *led) {
 assert(led->max_brightness==1);assert(!strcmp(led->name,"e5:white:torch"));
 return d->register_error;
}
'''
checks = r'''
int main(void) {
 struct platform_device p={.dev={.chip=3641,.index_error=-22}};
 assert(!e5_aw3641_probe(&p));assert(trace[0]==10&&trace[1]==20);
 struct e5_aw3641 *t=p.data;
 for(int n=0;n<20;n++) {
  count=0;e5_aw3641_brightness(&t->led,LED_ON);
  assert(count==2&&trace[0]==10&&trace[1]==21&&enable.value==1&&!mode.value);
  count=0;e5_aw3641_brightness(&t->led,LED_OFF);
  assert(count==2&&trace[0]==20&&trace[1]==10&&!enable.value&&!mode.value);
 }
 e5_aw3641_brightness(&t->led,LED_ON);count=0;e5_aw3641_shutdown(&p);
 assert(count==2&&trace[0]==20&&trace[1]==10);
 e5_aw3641_brightness(&t->led,LED_ON);cleanup(cleanup_data);
 assert(!enable.value&&!mode.value);free(t);
 /* Wrong chip or another torch topology must not touch GPIOs. */
 acquired=allocation=0;p.dev.chip=8137;
 assert(e5_aw3641_probe(&p)==-ENODEV&&acquired==0&&allocation==0);
 p.dev.chip=3641;p.dev.index_error=0;p.dev.index=2;
 assert(e5_aw3641_probe(&p)==-ENODEV&&acquired==0&&allocation==0);
 p.dev.index=1;p.dev.chip_error=-22;
 assert(e5_aw3641_probe(&p)==-ENODEV&&acquired==0);
 /* Deferred GPIO providers must propagate without enabling the LED. */
 p.dev.chip_error=0;
 for(int id=1;id<=2;id++) {
  count=acquired=0;p.dev.gpio_error=id;
  assert(e5_aw3641_probe(&p)==-517&&acquired==id);
  for(int i=0;i<count;i++)assert(trace[i]%10==0);
  free(last_allocation);
 }
 p.dev.gpio_error=0;p.dev.register_error=-ENOMEM;count=0;
 assert(e5_aw3641_probe(&p)==-ENOMEM);
 cleanup(cleanup_data);free(p.data);
 assert(!enable.value&&!mode.value);
 return 0;
}
'''
with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    (root / 'torch.c').write_text(prelude + source + checks)
    subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-fno-pie', '-no-pie',
                    str(root / 'torch.c'), '-o', str(root / 'torch')], check=True)
    subprocess.run([str(root / 'torch')], check=True)
print('PASS: actual GPIO order, binary torch, shutdown/remove, wrong board and deferred providers')
