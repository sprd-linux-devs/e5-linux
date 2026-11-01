#!/usr/bin/env python3
"""Compile real probe helpers/error branches against late-provider stubs.

Only small source fixtures are copied. No device, regulator or NV is written.
Run: python3 devices/common/test_power_probe.py --kernel <prepared kernel>
"""
from pathlib import Path
import argparse
import os
import runpy
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
PATCH = runpy.run_path(str(HERE/'power-probe.py'))
CORE = 'sprd_fuel_gauge_core.c'
HARDWARE = 'sprd_ump96xx_fuel_gauge.c'

PRELUDE = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <errno.h>
#define EPROBE_DEFER 517
#define ERR_PTR(n) ((void *)(intptr_t)(n))
#define PTR_ERR(p) ((long)(intptr_t)(p))
#define IS_ERR(p) ((uintptr_t)(p) >= (uintptr_t)-4095)
#define ERR_CAST(p) ((void *)(p))
struct regmap { int unused; } map;
struct device { struct device *parent; bool ready; } pmic,consumer;
struct platform_device { struct device dev; } supplier;
struct device_node { bool available; } node;
static bool registered;
static int gets,releases,refs,node_puts,diagnostic;
static int dev_err_probe(struct device *d,int error,const char *msg,...) {
 (void)d;(void)msg;diagnostic=error;return error;
}
static struct regmap *dev_get_regmap(struct device *d,void *name) {
 (void)name;return d->ready?&map:NULL;
}
static bool of_device_is_available(struct device_node *n){return n->available;}
static struct platform_device *of_find_device_by_node(struct device_node *n){
 assert(n==&node);if(!registered)return NULL;gets++;refs++;return &supplier;
}
static void platform_device_put(struct platform_device *p){assert(p==&supplier);releases++;refs--;}
static void of_node_put(struct device_node *n){assert(n==&node);node_puts++;}
struct sprd_fgu_data { struct regmap *regmap;void *gpiod,*usb_phy,*battery; } gauge;
struct sprd_fgu_hw { struct regmap *regmap; } hardware;
struct charger { struct regmap *pmic; } chg;
'''

CHECKS = r'''
static void reset(void) {
 pmic=(struct device){0};consumer=(struct device){.parent=&pmic};
 supplier=(struct platform_device){.dev={.parent=&pmic}};
 node.available=true;registered=false;gets=releases=refs=node_puts=diagnostic=0;
}
int main(void) {
 reset();
 assert(PTR_ERR(sprd_charger_pmic_regmap(&consumer,NULL))==-ENODEV);
 node.available=false;
 assert(PTR_ERR(sprd_charger_pmic_regmap(&consumer,&node))==-ENODEV);
 assert(!gets&&!refs);
 node.available=true;
 assert(PTR_ERR(sprd_charger_pmic_regmap(&consumer,&node))==-EPROBE_DEFER);
 assert(!gets&&!refs);
 registered=true;
 for(int i=0;i<10000;i++) {
  assert(PTR_ERR(sprd_charger_pmic_regmap(&consumer,&node))==-EPROBE_DEFER);
  assert(refs==0&&gets==releases);
 }
 pmic.ready=true;
 assert(sprd_charger_pmic_regmap(&consumer,&node)==&map);
 assert(refs==0&&gets==releases);
 supplier.dev.parent=NULL;
 assert(PTR_ERR(sprd_charger_pmic_regmap(&consumer,&node))==-ENODEV);
 assert(refs==0&&gets==releases);
 assert(core_regmap(&consumer)==0);
 assert(hw_regmap(&consumer)==&hardware);
 consumer.parent=NULL;
 assert(core_regmap(&consumer)==-ENODEV);
 assert(PTR_ERR(hw_regmap(&consumer))==-ENODEV);
 consumer.parent=&pmic;pmic.ready=false;
 assert(core_regmap(&consumer)==-EPROBE_DEFER);
 assert(PTR_ERR(hw_regmap(&consumer))==-EPROBE_DEFER);
 for(unsigned i=0;i<sizeof(errors)/sizeof(errors[0]);i++) {
  int e=errors[i];
  assert(gpio_error(e)==e);
  assert(phy_error(e)==e);
  assert(battery_error(e)==e);
 }
 assert(gpio_error(0)==0&&phy_error(0)==0&&battery_error(0)==0);
 for(int i=0;i<2;i++) {
  reset();
  assert(charger_probe(&consumer)==-EPROBE_DEFER);
  assert(node_puts==1&&refs==0);
  registered=true;
  assert(charger_probe(&consumer)==-EPROBE_DEFER);
  assert(node_puts==2&&gets==releases&&refs==0);
  pmic.ready=true;
  assert(charger_probe(&consumer)==0);
  assert(node_puts==3&&gets==releases&&refs==0);
  node.available=false;
  assert(charger_probe(&consumer)==-ENODEV);
  assert(node_puts==4&&gets==releases&&refs==0);
 }
 puts_result();
 return 0;
}
'''


def between(source, start, end):
    at = source.index(start)
    return source[at:source.index(end, at)]


def provider_checks(root, after):
    hardware = after[HARDWARE].decode()
    core = after[CORE].decode()
    cm = after['charger-manager.c'].decode()
    table = between(hardware, 'static const struct of_device_id ump96xx_fgu_dev_match_arr[]', '\n\nstatic inline')
    match = between(hardware, '\t/* Honor the full DT compatible list', '\n\tret = device_property_read_u32')
    gate = between(core, '\tif (unlikely(!psy->initialized && atomic_read(&psy->use_cnt) > 0))',
                   '\n\tif (!sprd_fgu_probe_is_ready')
    fgu_error = between(core, '\tif (IS_ERR(data->fgu_info))', '\n#elif')
    assert core.count(gate) == 2  # get_property and set_property
    prelude = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <errno.h>
#include <string.h>
#define EPROBE_DEFER 517
#define ERR_PTR(n) ((void *)(intptr_t)(n))
#define PTR_ERR(p) ((long)(intptr_t)(p))
#define IS_ERR(p) ((uintptr_t)(p) >= (uintptr_t)-4095)
#define unlikely(n) (n)
#define atomic_read(p) (*(p))
struct device_node { const char *compatible[4]; } node;
struct device { struct device_node *of_node; } device={&node};
struct of_device_id { const char *compatible; const void *data; };
static const int ump96xx_fgu_info=9620;
struct sprd_fgu_info { const void *pdata; } gauge;
static const struct of_device_id *of_match_node(const struct of_device_id *table,
                                              struct device_node *np) {
 if(!np)return 0;
 for(;table->compatible;table++)
  for(int i=0;i<4&&np->compatible[i];i++)
   if(!strcmp(table->compatible,np->compatible[i]))return table;
 return 0;
}
static int dev_err_probe(struct device *dev,int error,const char *message,...) {
 (void)dev;(void)message;return error;
}
struct power_supply { bool initialized; int use_cnt; } supply;
struct charger_desc { int cap,temperature; } desc;
struct charger_manager { struct device *dev; struct charger_desc *desc; } manager={&device,&desc};
static int puts,provider_error;
static void power_supply_put(struct power_supply *p){assert(p==&supply);puts++;}
static int get_boot_cap(struct charger_manager *cm,int *cap){assert(cm==&manager);*cap=730;return provider_error;}
static int cm_get_battery_temperature(struct charger_manager *cm,int *temp){assert(cm==&manager);*temp=250;return provider_error;}
'''
    code = prelude + table + '\nstatic void *match_fgu(struct device *dev){\n'
    code += 'struct sprd_fgu_info *info=&gauge;const struct of_device_id *match;\n'+match+'\nreturn info;}\n'
    code += 'static int supply_ready(struct power_supply *psy){\n'+gate+'\nreturn 0;}\n'
    code += ('static int hardware_error(int error){struct {struct device *dev;void *fgu_info;} gauge_error={&device,error?ERR_PTR(error):&gauge},*data=&gauge_error;\n'
             + fgu_error+'\nreturn 0;}\n')
    for label, call, ending in (
        ('capacity', 'get_boot_cap(cm, &cm->desc->cap)', '\n\tif (device_property_read_bool'),
        ('temperature', 'cm_get_battery_temperature(cm, &cm->desc->temperature)', '\n\tcur_time ='),
    ):
        body = between(cm, '\tret = '+call+';', ending)
        code += f'static int probe_{label}(void){{struct charger_manager *cm=&manager;struct power_supply *fuel_gauge=&supply;int ret;\n'+body+'\nreturn 0;}\n'
    code += r'''
int main(void) {
 const char *known="sprd,ump9620-fgu";
 node=(struct device_node){{known,0}};
 assert(match_fgu(&device)==&gauge&&gauge.pdata==&ump96xx_fgu_info);
 node=(struct device_node){{"vendor,batch-specific-fgu",known,0}};
 assert(match_fgu(&device)==&gauge);
 node=(struct device_node){{"vendor,unknown-fgu",0}};
 assert(PTR_ERR(match_fgu(&device))==-ENODATA);
 node=(struct device_node){{0}};
 assert(PTR_ERR(match_fgu(&device))==-ENODATA);
 device.of_node=0;
 assert(PTR_ERR(match_fgu(&device))==-ENODATA);
 supply=(struct power_supply){false,1};
 assert(supply_ready(&supply)==-EAGAIN);
 supply.initialized=true;
 assert(supply_ready(&supply)==0);
 int errors[]={-EAGAIN,-EPROBE_DEFER,-EINVAL,-EIO,-ENODEV,-ENOMEM};
 for(unsigned i=0;i<sizeof(errors)/sizeof(errors[0]);i++) {
  provider_error=errors[i];puts=0;
  assert(hardware_error(provider_error)==provider_error);
  int expected=provider_error==-EAGAIN?-EPROBE_DEFER:provider_error;
  assert(probe_capacity()==expected&&puts==1);
  assert(probe_temperature()==expected&&puts==2);
 }
 provider_error=0;puts=0;
 assert(hardware_error(0)==0&&hardware_error(-ENODATA)==-ENODATA);
 assert(probe_capacity()==0&&probe_temperature()==0&&!puts);
 assert(desc.cap==730&&desc.temperature==250);
 return 0;
}
'''
    source=root/'provider.c';binary=root/'provider'
    source.write_text(code)
    subprocess.run(['gcc','-Wall','-Wextra','-Werror','-std=gnu11','-fsanitize=undefined',
                    str(source),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
    print('PASS: DT fallback, unknown FGU rejection, not-ready supply and CM reference/error handling')


def branches(core, hardware, charger, name):
    regmap = between(core, '\tdata->regmap = sprd_power_regmap(', '\n\tdata->use_typec_extcon')
    hw = between(hardware, '\tinfo->regmap = sprd_power_regmap(', '\n\t/* Honor the full DT compatible list')
    result = 'static int core_regmap(struct device *dev){struct sprd_fgu_data *data=&gauge;\n'+regmap+'\nreturn 0;}\n'
    result += 'static void *hw_regmap(struct device *dev){struct sprd_fgu_hw *info=&hardware;\n'+hw+'\nreturn info;}\n'
    specs = [('gpio','gpiod','\n\tret = gpiod_get_value_cansleep'),
             ('phy','usb_phy','\n\t}\n\n\tdata->channel'),
             ('battery','battery','\n\tret = devm_add_action_or_reset')]
    for label, field, end in specs:
        prefix = '\t\t' if field == 'usb_phy' else '\t'
        body = between(core, prefix+'if (IS_ERR(data->'+field+'))', end)
        returns = 'return 0;err:return ret;' if field == 'battery' else 'return 0;'
        declaration = 'int ret;' if field == 'battery' else ''
        result += f'static int {label}_error(int e){{ struct device *dev=&consumer;struct sprd_fgu_data *data=&gauge;{declaration}\n'
        result += f'data->{field}=e?ERR_PTR(e):&map;\n'+body+'\n'+returns+'}\n'
    owner='info' if name=='bq2560x-charger.c' else 'bq'
    body=between(charger, '\t'+owner+'->pmic = sprd_charger_pmic_regmap(', '\n\tmutex_init(')
    declaration='' if owner=='info' else 'int ret;'
    ending='return 0;' if owner=='info' else 'return 0;error_1:return ret;'
    result += f'static int charger_probe(struct device *dev){{struct charger *{owner}=&chg;struct device_node *regmap_np=&node;{declaration}\n'+body+'\n'+ending+'}\n'
    result += 'static int errors[]={-EPROBE_DEFER,-ENOENT,-EINVAL,-ENODEV,-EIO,-ENOMEM,-EBUSY};\n'
    result += 'static void puts_result(void){printf("PASS: '+name+' late suppliers, FGU errors and balanced references\\n");}\n'
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel',type=Path,required=True)
    parser.add_argument('--objects',type=Path,help='Compile changed C with this existing matching kernel object tree')
    args=parser.parse_args()
    original=args.kernel/'drivers/power/supply'
    chargers=[n for n in ('bq2560x-charger.c','aw32257_charger.c') if (original/n).is_file()]
    names=[CORE,HARDWARE,'charger-manager.c',*chargers]
    with tempfile.TemporaryDirectory(prefix='e5-power-probe-') as temporary:
        root=Path(temporary);directory=root/'drivers/power/supply';directory.mkdir(parents=True)
        before={name:(original/name).read_text() for name in names}
        for name,source in before.items():(directory/name).write_text(source)
        PATCH['apply'](root)
        after={name:(directory/name).read_bytes() for name in names}
        PATCH['apply'](root)
        assert after=={name:(directory/name).read_bytes() for name in names},'patch is not idempotent'
        # Unknown source shapes must not half-apply the preparation.
        (directory/HARDWARE).write_text('unsupported source\n')
        retained={p.name:p.read_bytes() for p in directory.iterdir()}
        try:PATCH['apply'](root)
        except ValueError:pass
        else:raise AssertionError('unknown source accepted')
        assert retained=={p.name:p.read_bytes() for p in directory.iterdir()}
        (directory/HARDWARE).write_bytes(after[HARDWARE])
        # The common SOC stack is replayed before board adapters on every
        # build. Verify it neither rejects nor erases these probe fixes.
        fuel=runpy.run_path(str(HERE/'fuel-gauge.py'))
        patches={v for v in fuel.values() if isinstance(v,Path) and v.suffix=='.patch'}
        paths={line[6:] for patch in patches for line in patch.read_text().splitlines()
               if line.startswith('+++ b/')}
        for name in paths:
            target=root/name
            if not target.exists():
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes((args.kernel/name).read_bytes())
        full=runpy.run_path(str(HERE/'charger-hardware-full.py'))
        cm=root/'drivers/power/supply/charger-manager.c'
        opt_in=any(comment in cm.read_text() for comment in (full['COMMENT'],full['LEGACY_COMMENT']))
        if opt_in:full['restore'](root)
        fuel['apply'](root)
        if opt_in:full['apply'](root)
        assert after=={name:(directory/name).read_bytes() for name in names},'SOC preparation overwrote probe fixes'
        inc=root/'linux';inc.mkdir()
        for n in ('device.h','err.h','errno.h','of.h','of_platform.h','platform_device.h','regmap.h'):
            (inc/n).write_text('')
        (inc/'errno.h').write_text('#include_next <linux/errno.h>\n')
        for name in chargers:
            source=after[name].decode()
            prefix='bq2560x_charger_probe' if name.startswith('bq') else 'aw32257_probe'
            # Match/ID checks before PMIC acquisition must also stay intact.
            if '\tregmap_pdev = of_find_device_by_node(' in before[name]:
                previous=between(before[name], 'static int '+prefix+'(', '\tregmap_pdev = of_find_device_by_node(')
                current=between(source, 'static int '+prefix+'(', '\t'+('info' if name.startswith('bq') else 'bq')+'->pmic = sprd_charger_pmic_regmap(')
                assert previous.replace('\tstruct platform_device *regmap_pdev;\n','')==current
            else:
                assert before[name]==source
            # No chip/address match or current/voltage register helper edits.
            for fn in ('charger_set_current','charger_get_current','charger_set_termina_vol','charger_get_termina_vol'):
                if name.startswith('bq'):
                    extract=runpy.run_path(str(HERE/'test_charger_endpoint.py'))['function']
                    assert extract(before[name],'bq2560x_'+fn)==extract(source,'bq2560x_'+fn)
            program=root/'probe.c';binary=root/'probe'
            program.write_text(PRELUDE+'\n#include "power-probe.h"\n'+
                branches(after[CORE].decode(),after[HARDWARE].decode(),source,name)+CHECKS)
            subprocess.run(['gcc','-Wall','-Wextra','-Werror','-std=gnu11','-O2',
                '-I',str(root),'-I',str(directory),str(program),'-o',str(binary)],check=True)
            subprocess.run([str(binary)],check=True)
        provider_checks(root, after)
        if args.objects:
            # Small external-module fixture, reusing the registered source,
            # config and generated headers. No new full tree or deliverable.
            for p in original.glob('*.h'):
                if p.name!='power-probe.h':(directory/p.name).write_bytes(p.read_bytes())
            (directory/'Makefile').write_text('obj-m += '+' '.join(Path(n).stem+'.o' for n in names)+'\n')
            subprocess.run(['make','-C',str(args.kernel.resolve()),'O='+str(args.objects.resolve()),
                'M='+str(directory),'ARCH=arm64','LLVM=1','LLVM_IAS=1',
                'CROSS_COMPILE=aarch64-linux-gnu-','-j4',*[Path(n).stem+'.o' for n in names]],
                env=dict(os.environ,LOCALVERSION=''),check=True)
    print('PASS: source validation and repeated preparation; charger encoding unchanged')


if __name__=='__main__':main()
