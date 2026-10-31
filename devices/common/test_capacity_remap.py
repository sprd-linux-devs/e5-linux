#!/usr/bin/env python3
"""Exercise the real CM parser/remap; compare all K1 SOCs to its stock binary."""
from pathlib import Path
import hashlib
import runpy
import shutil
import struct
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
extract = runpy.run_path(str(HERE/'test_fuel_gauge.py'))['function']
apply = runpy.run_path(str(HERE/'fuel-gauge.py'))['apply']

PRELUDE = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <limits.h>
#include <errno.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
typedef int64_t s64;
typedef uint32_t __be32;
#define GFP_KERNEL 0
#define CM_CAP_FULL_PERCENT 1000
#define DIV_ROUND_CLOSEST(n,d) (((n)+(d)/2)/(d))
#define be32_to_cpu(v) __builtin_bswap32(v)
struct cap_remap_table {int cnt,lcap,hcap,lb,hb;};
struct charger_desc {struct cap_remap_table *cap_remap_table;
 int cap_remap_table_len,cap_remap_total_cnt,cap_remap_full_percent;};
struct charger_manager {struct charger_desc *desc;};
struct device {int *of_node;};
static __be32 cells[30];
static int bytes;
static bool present,oom;
static const __be32 *of_get_property(int *node,const char *name,int *length){
 (void)node;assert(!strcmp(name,"cm-cap-remap-table"));*length=bytes;
 return present?cells:NULL;
}
static void *devm_kcalloc(struct device *dev,size_t n,size_t size,int flags){
 (void)dev;(void)flags;return oom?NULL:calloc(n,size);
}
static void set_table(const int *values,size_t n){
 assert(n<=30);present=true;bytes=n*4;
 for(size_t i=0;i<n;i++)cells[i]=__builtin_bswap32((uint32_t)values[i]);
}
'''

MAIN = r'''
int main(void){
 struct device dev={0};struct charger_desc d={0};struct charger_manager cm={&d};
 assert(cm_init_capacity_remap(&dev,&d)==0);
 for(int raw=-1;raw<=1001;raw++)assert(cm_cap_advance_full(&cm,raw)==raw);
 int k1[]={1,2,3,2,3,2,98,99,2,99,100,3};
 set_table(k1,12);assert(cm_init_capacity_remap(&dev,&d)==0);
 assert(d.cap_remap_total_cnt==106 && d.cap_remap_table_len==4);
 assert(cm_cap_advance_full(&cm,48)==25);
 int previous=-1;
 for(int raw=-1;raw<=1001;raw++){
  int mapped=cm_cap_advance_full(&cm,raw);
  assert(mapped>=previous && mapped>=0 && mapped<=1000);previous=mapped;
  printf("%d\n",mapped);
 }
 for(int raw=0;raw<=1000;raw++){
  d.cap_remap_full_percent=80;
  int expected=raw*100/80;if(expected>1000)expected=1000;
  assert(cm_cap_advance_full(&cm,raw)==cm_capacity_remap(&cm,expected));
 }
 free(d.cap_remap_table);memset(&d,0,sizeof(d));
 int gap[]={10,20,2,80,90,3};
 set_table(gap,6);assert(cm_init_capacity_remap(&dev,&d)==0);
 assert(cm_capacity_remap(&cm,1000)==1000);
 assert(cm_capacity_remap(&cm,0)==0);
 previous=-1;for(int raw=0;raw<=1000;raw++){
  int mapped=cm_capacity_remap(&cm,raw);assert(mapped>=previous);previous=mapped;
 }
 free(d.cap_remap_table);memset(&d,0,sizeof(d));
 bytes=0;assert(cm_init_capacity_remap(&dev,&d)==-EINVAL);
 bytes=4;assert(cm_init_capacity_remap(&dev,&d)==-EINVAL);
 set_table(k1,12);oom=true;assert(cm_init_capacity_remap(&dev,&d)==-ENOMEM);oom=false;
 int bad[][6]={{1,2,0,2,3,1},{1,2,-1,2,3,1},{1,2,1,1,3,1},
  {1,1,1,2,3,1},{1,101,1,2,3,1},{-1,2,1,2,3,1}};
 for(unsigned i=0;i<sizeof(bad)/sizeof(bad[0]);i++){
  set_table(bad[i],6);assert(cm_init_capacity_remap(&dev,&d)==-EINVAL);
  free(d.cap_remap_table);memset(&d,0,sizeof(d));
 }
 int overflow[]={0,100,INT_MAX};set_table(overflow,3);
 assert(cm_init_capacity_remap(&dev,&d)==-ERANGE);free(d.cap_remap_table);
 return 0;
}
'''


def main():
    kernel = Path(sys.argv[1])
    with tempfile.TemporaryDirectory(prefix='e5-cap-remap-') as directory:
        stage = Path(directory)
        for name in ('charger-manager.c', 'sprd_fuel_gauge_core.c', 'sprd_ump96xx_fuel_gauge.c'):
            dest = stage/'drivers/power/supply'/name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(kernel/'drivers/power/supply'/name, dest)
        runpy.run_path(str(HERE/'charger-hardware-full.py'))['restore'](stage)
        apply(stage)
        cm = stage/'drivers/power/supply/charger-manager.c'
        source = cm.read_text()
        apply(stage)
        assert cm.read_text() == source, 'Preparation must be idempotent'
        parser = source[source.index('static struct charger_desc *of_cm_parse_desc'):]
        assert 'i = cm_init_capacity_remap(dev, desc);' in parser.split('static inline', 1)[0]
        assert 'cm_capacity_remap' not in extract(source, 'get_batt_cap'), 'Do not remap raw FGU twice'
        functions = '\n'.join(extract(source, n) for n in
                              ('cm_init_capacity_remap', 'cm_capacity_remap', 'cm_cap_advance_full'))
        cfile, binary = stage/'check.c', stage/'check'
        cfile.write_text(PRELUDE+functions+MAIN)
        subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(cfile),'-o',str(binary)],check=True)
        result = subprocess.run([str(binary)],capture_output=True,text=True,check=True)
        values = [int(s) for s in result.stdout.splitlines()]
        assert len(values) == 1003
        # K1 stock sprd-charger-manager.ko SHA256 27a78770442c2ebd2165d2d5088b5b9728f286db77798b5214696e0eacee9ba1.
        # Unmodified AArch64 text 0xa204..0xa2e0 (branches through 0xa574..0xa630),
        # emulated for -1..1001, actual DT table (1,2,3),(2,3,2),(98,99,2),(99,100,3).
        expected = 'bb2ccde9da59581f79c97c5102351ea2c1fed0423a14122d11d90eb02f4bfa76'
        assert hashlib.sha256(struct.pack('<1003i',*values)).hexdigest() == expected
        print('Stock CM SOC remap: 1003 native binary outputs, parser errors/gaps, single mapping and replay passed')


if __name__ == '__main__':
    main()
