"""Run opt-in SQC boards' real C status/endpoint functions with fake supplies.

Usage in Linux: python3 test_charger_endpoint.py --kernel /path/to/prepared/kernel
These are offline regressions, not a physical full-charge-cycle validation.
"""
from pathlib import Path
import argparse
import re
import runpy
import subprocess
import tempfile


def function(source, name):
    found = re.search(r'(?m)^static (?:int|bool)\s+' + name + r'\([^;{}]*\)\s*\{', source)
    if not found:
        raise ValueError(name)
    start = source.index('{', found.start())
    end, depth = start + 1, 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[found.start():end]


PRELUDE = r'''
#include <assert.h>
#include <stdbool.h>
#include <errno.h>
#include <string.h>
typedef unsigned char u8;
enum { POWER_SUPPLY_STATUS_CHARGING=1, POWER_SUPPLY_STATUS_DISCHARGING,
 POWER_SUPPLY_STATUS_NOT_CHARGING, POWER_SUPPLY_STATUS_FULL };
#define POWER_SUPPLY_PROP_STATUS 1
#define CM_FORCE_SET_FUEL_CAP_FULL 1000
#define BQ2560X_REG_8 8
#define BIT(n) (1U << (n))
#define dev_info(...) ((void)0)
struct bq2560x_charger_info { bool charging; };
static int read_error, raw_status;
static int bq2560x_read(struct bq2560x_charger_info *i, int reg, u8 *v) {
 (void)i; assert(reg==8); *v=raw_status; return read_error;
}
struct charger_desc { const char **psy_charger_stat; int fullbatt_uV; bool force_set_full; };
struct charger_manager { struct charger_desc *desc; bool charger_enabled, emergency_stop;
 int battery_status, dev; };
union power_supply_propval { int intval; };
struct power_supply { int index; };
static struct power_supply supply[2]={{0},{1}};
static bool battery=true, external=true;
static int voltage=4400000, voltage_error, calibration_error, calibrations;
static int states[2]={1,1}, errors[2], gets, puts;
static bool present[2]={true,true};
static bool is_batt_present(struct charger_manager *c){(void)c;return battery;}
static bool is_ext_pwr_online(struct charger_manager *c){(void)c;return external;}
static struct power_supply *power_supply_get_by_name(const char *name){
 unsigned i=!strcmp(name,"second");if(!present[i])return 0; gets++;return &supply[i];
}
static void power_supply_put(struct power_supply *p){(void)p;puts++;}
static int power_supply_get_property(struct power_supply *p,int prop,union power_supply_propval *v){
 assert(prop==POWER_SUPPLY_PROP_STATUS);v->intval=states[p->index];return errors[p->index];
}
static int get_vbat_now_uV(struct charger_manager *c,int *v){(void)c;*v=voltage;return voltage_error;}
static int adjust_fuel_cap(struct charger_manager *c,int cap){
 (void)c;assert(cap==1000);calibrations++;return calibration_error;
}
'''

MAIN = r'''
int main(void) {
 struct bq2560x_charger_info info={true};
 int expected[]={3,1,1,4};
 for(raw_status=0;raw_status<256;raw_status++) {
  assert(bq2560x_charger_get_status(&info)==((raw_status&4)?expected[(raw_status>>3)&3]:2));
 }
 raw_status=0x38;
 assert(bq2560x_charger_get_status(&info)==2);
 raw_status=0x3c;info.charging=false;
 assert(bq2560x_charger_get_status(&info)==3);
 info.charging=true;read_error=-EIO;
 assert(bq2560x_charger_get_status(&info)==-EIO);read_error=0;

 const char *names[]={"first","second",0};
 struct charger_desc d={names,4300000,false};
 struct charger_manager c={&d,true,false,1,0};
 /* High voltage or stale UI/full flags cannot establish a full endpoint. */
 assert(!is_full_charged(&c)&&!calibrations);
 d.force_set_full=true;assert(!is_full_charged(&c)&&!d.force_set_full);
 states[0]=4;voltage=4299999;
 assert(!is_full_charged(&c)&&!calibrations);
 voltage=4300000;voltage_error=-EIO;
 assert(!is_full_charged(&c)&&!calibrations);voltage_error=0;
 calibration_error=-EIO;
 assert(!is_full_charged(&c)&&!d.force_set_full&&calibrations==1);
 calibration_error=0;
 assert(is_full_charged(&c)&&d.force_set_full&&calibrations==2);
 c.battery_status=4;
 for(int n=0;n<20;n++)assert(is_full_charged(&c));
 assert(calibrations==2); /* Do not repeatedly reset the coulomb counter. */
 external=false;assert(!is_full_charged(&c)&&!d.force_set_full);
 external=true;c.battery_status=1;
 for(int n=0;n<5;n++) {
  battery=n!=0;c.charger_enabled=n!=1;c.emergency_stop=n==2;
  d.fullbatt_uV=n==3?0:4300000;errors[0]=n==4?-EIO:0;states[1]=1;
  assert(!is_full_charged(&c)&&!d.force_set_full);
 }
 assert(calibrations==2);
 battery=true;c.charger_enabled=true;c.emergency_stop=false;d.fullbatt_uV=4300000;
 errors[0]=-EIO;states[1]=4;
 assert(is_full_charged(&c)&&calibrations==3);c.battery_status=4;
 present[0]=false;present[1]=false;
 assert(!is_full_charged(&c)&&!d.force_set_full);
 assert(gets==puts);
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel', type=Path, required=True)
    args = parser.parse_args()
    folder = args.kernel / 'drivers/power/supply'
    charger = (folder / 'bq2560x-charger.c').read_text()
    manager = (folder / 'charger-manager.c').read_text()
    assert 'ret = bq2560x_charger_get_status(info);\n\t\tif (ret < 0)\n\t\t\tgoto out;' in charger
    assert 'cm->desc->trickle_time >= cm->desc->trickle_time_out' not in manager
    with tempfile.TemporaryDirectory() as temp:
        target = Path(temp)
        # Real existing prepared policy can be migrated/replayed without
        # accumulating a second implementation or changing unknown source.
        policy = runpy.run_path(str(Path(__file__).with_name('charger-hardware-full.py')))
        prepared = target/'drivers/power/supply/charger-manager.c'
        prepared.parent.mkdir(parents=True)
        prepared.write_text(manager)
        policy['restore'](target)
        policy['apply'](target)
        assert prepared.read_text() == manager
        policy['apply'](target)
        assert prepared.read_text() == manager
        legacy = manager.replace(policy['COMMENT'], policy['LEGACY_COMMENT']).replace(
            'SQC hardware full endpoint: vbat=', 'P720S11 hardware full endpoint: vbat=')
        prepared.write_text(legacy)
        policy['restore'](target)
        policy['apply'](target)
        assert prepared.read_text() == manager
        source = PRELUDE + function(charger, 'bq2560x_charger_get_status') + '\n'
        source += function(manager, 'is_full_charged') + MAIN
        (target / 'endpoint.c').write_text(source)
        subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', str(target / 'endpoint.c'),
                        '-o', str(target / 'endpoint')], check=True)
        subprocess.run([str(target / 'endpoint')], check=True)
    print('PASS: all 256 REG08 values, input/stop/I2C errors, full voltage boundary, '
          'calibration retry/once per endpoint, disconnect, missing supplies and reference balance')


if __name__ == '__main__':
    main()
