#!/usr/bin/env python3
"""Exercise AW enable readback through the actual power-supply core gate."""
from pathlib import Path
import argparse
import re
import runpy
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('kernel', type=Path)
parser.add_argument('--core', type=Path, help='Explicit unchanged power_supply_core.c for an unmounted overlay upperdir')
args = parser.parse_args()
kernel = args.kernel
replace = runpy.run_path(str(HERE.parent/'t551m/prepare-kernel.py'))['replace_function']
apply = runpy.run_path(str(HERE/'charger.py'))['apply_state']


def function(source, name):
    match = re.search(r'static (?:int|bool)\s+' + name + r'\([^;{}]*\)\s*\{', source)
    assert match, name
    end, depth = match.end(), 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[match.start():end]


with tempfile.TemporaryDirectory(prefix='aw-readback-') as tmp:
    root = Path(tmp)
    path = root/'aw32257_charger.c'
    original = (kernel/'drivers/power/supply/aw32257_charger.c').read_text()
    path.write_text(original)
    apply(path, replace)
    first = path.read_bytes()
    apply(path, replace)
    assert path.read_bytes() == first
    source = path.read_text()
    core = (args.core or kernel/'drivers/power/supply/power_supply_core.c').read_text()
    props = re.search(r'static enum power_supply_property aw32257_power_supply_props\[\] = \{.*?\n};', source, re.S)[0]
    getter = function(source, 'aw32257_power_supply_get_property_locked')
    names = sorted(set(re.findall(r'POWER_SUPPLY_PROP_\w+', props + getter)))
    c = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <errno.h>
#define AW32257_REG_CONTROL 1
#define SDP_TYPE 1
#define DCP_TYPE 2
#define CDP_TYPE 3
enum {POWER_SUPPLY_USB_TYPE_SDP,POWER_SUPPLY_USB_TYPE_DCP,POWER_SUPPLY_USB_TYPE_CDP,POWER_SUPPLY_USB_TYPE_UNKNOWN};
enum {POWER_SUPPLY_STATUS_DISCHARGING=2};
''' + 'enum power_supply_property {' + ','.join(names) + '};\n' + r'''
union power_supply_propval {int intval;const char *strval;};
struct phy {int chg_type;};
struct aw32257_device {int limit,charging,input_budget_ua;struct phy *usb_phy;};
struct power_supply;
struct power_supply_desc {enum power_supply_property *properties;int num_properties;
 int (*get_property)(struct power_supply*,enum power_supply_property,union power_supply_propval*);};
struct power_supply {struct aw32257_device *data;struct power_supply_desc *desc;int use_cnt;bool initialized;void *battery_info;int extensions_sem;};
struct power_supply_ext {int (*get_property)(struct power_supply*,struct power_supply_ext*,void*,enum power_supply_property,union power_supply_propval*);};
struct power_supply_ext_registration {struct power_supply_ext *ext;void *data;};
#define power_supply_for_each_extension(reg,psy) for ((reg)=NULL;(reg)!=NULL;)
#define scoped_guard(kind,sem) for (int once=1;once;once=0)
static bool power_supply_ext_has_property(struct power_supply_ext *e,enum power_supply_property p){(void)e;(void)p;return false;}
static bool power_supply_battery_info_has_prop(void *i,enum power_supply_property p){(void)i;(void)p;return false;}
static int power_supply_battery_info_get_prop(void *i,enum power_supply_property p,union power_supply_propval *v){(void)i;(void)p;(void)v;return -EINVAL;}
static int atomic_read(int *p){return *p;}
static void *power_supply_get_drvdata(struct power_supply *p){return p->data;}
static int control,read_error;
static int aw32257_i2c_read_mask(struct aw32257_device *b,int r,int mask,int shift){(void)b;assert(r==1);return read_error?read_error:(control&mask)>>shift;}
static int sprd_hsphy_external_power(struct phy *p){(void)p;return 0;}
static int aw32257_charger_get_status(struct aw32257_device *b){return b->charging?1:3;}
static int aw32257_get_charge_current(struct aw32257_device *b){(void)b;return 500;}
static int aw32257_charger_get_online(struct aw32257_device *b,int *v){*v=b->limit!=0;return 0;}
static void aw32257_charger_get_health(struct aw32257_device *b,int *v){(void)b;*v=1;}
''' + props + '\n' + getter + '\n' + function(core, 'psy_desc_has_property') + '\n' + function(core, '__power_supply_get_property') + r'''
int main(void){
 struct phy phy={0};struct aw32257_device b={.usb_phy=&phy};
 struct power_supply_desc d={aw32257_power_supply_props,sizeof(aw32257_power_supply_props)/sizeof(*aw32257_power_supply_props),aw32257_power_supply_get_property_locked};
 struct power_supply p={.data=&b,.desc=&d,.use_cnt=1,.initialized=true};union power_supply_propval v;
 for(control=0;control<256;control++){
  v.intval=-1;assert(!__power_supply_get_property(&p,POWER_SUPPLY_PROP_CALIBRATE,&v,true));
  assert(v.intval==!(control&7));
 }
 read_error=-EIO;assert(__power_supply_get_property(&p,POWER_SUPPLY_PROP_CALIBRATE,&v,true)==-EIO);read_error=0;
 /* Negative control: reproduce the old descriptor even with a working getter. */
 enum power_supply_property missing[]={POWER_SUPPLY_PROP_STATUS};d.properties=missing;d.num_properties=1;
 control=0;assert(__power_supply_get_property(&p,POWER_SUPPLY_PROP_CALIBRATE,&v,true)==-EINVAL);
 return 0;
}
'''
    (root/'test.c').write_text(c)
    subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror', str(root/'test.c'), '-o', str(root/'test')], check=True)
    subprocess.run([str(root/'test')], check=True)
print('PASS: actual core dispatch, all 256 AW control values, I/O errors, old-descriptor rejection and reapplication')
