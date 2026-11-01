#!/usr/bin/env python3
"""Build this profile in an explicit, reusable UMS9620 source/object workspace."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import tarfile

HERE=Path(__file__).resolve().parent
TOP=HERE.parents[1]


def config(base, here=HERE):
    if 'CONFIG_SPRD_UMS9620_CLK=y' not in base or 'CONFIG_PINCTRL_SPRD_QOGIRN6PRO=y' not in base:
        raise ValueError('Use the tested UMS9620 baseline, not an E5/T551M configuration')
    # Keep the caller's full tested platform baseline; override only board
    # deltas and remove the old RAM/userdata trial selector.
    text=base+'\n'+(here/'kernel.config').read_text()
    text=re.sub(r' e5\.openwrt=[^ "\n]+','',text)
    values={}
    for line in text.splitlines():
        if line.startswith('CONFIG_') and '=' in line:
            key,value=line.split('=',1);values[key]=value
        elif line.startswith('# CONFIG_') and line.endswith(' is not set'):
            values[line[2:-11]]='n'
    values['CONFIG_LOCALVERSION_AUTO']='n'
    return ''.join(k+'='+v+'\n' for k,v in values.items())


def main(*, profile='yuanhang41s', here=HERE):
    if profile not in ('yuanhang41s','changxing60','y60'):
        raise ValueError('Unsupported UMS9620 profile')
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('kernel','build','base-config','out'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--jobs',type=int,default=8)
    args=parser.parse_args()
    if os.name=='nt':parser.error('Use Linux/WSL and reuse the existing source/object directories')
    kernel,build,out=(p.resolve() for p in (args.kernel,args.build,args.out))
    baseline=args.base_config.read_bytes();wanted=config(baseline.decode(),here)
    if kernel==build or out==kernel or out==build or Path('/') in (build,out):
        parser.error('Source, object and delivery directories must be separate')
    runpy.run_path(str(here/'prepare-kernel.py'))['apply'](kernel)
    subprocess.run(['python3',str(TOP/'devices/common/test_power_probe.py'),
                    '--kernel',str(kernel)],check=True)
    tests=['test_boot_soc.py', 'test_battery_periodic.py', 'test_capacity_remap.py']
    # The BQ endpoint test is specific to the 41S/CX60 charger implementation.
    # Y60 has a different silicon/register map and executes its own real C callbacks.
    if profile!='y60':tests.append('test_charger_endpoint.py')
    for test in tests:
        extra = ['--kernel'] if test == 'test_charger_endpoint.py' else []
        subprocess.run(['python3', str(TOP/'devices/common'/test), *extra, str(kernel)], check=True)
    if profile=='y60':
        subprocess.run(['python3',str(here/'test-charger.py'),'--kernel',str(kernel)],check=True)
        subprocess.run(['python3',str(here/'test_audio.py'),'--kernel',str(kernel)],check=True)
    build.mkdir(parents=True,exist_ok=True);out.mkdir(parents=True,exist_ok=True)
    # Do not create another checkout, copy a rootfs or run modules_install into
    # a persistent duplicate root. Only the delivery module cohort is staged.
    (build/'.config').write_text(wanted)
    env=dict(os.environ,LOCALVERSION='')
    command=['make','-C',str(kernel),'O='+str(build),'ARCH=arm64','LLVM=1','LLVM_IAS=1','CROSS_COMPILE=aarch64-linux-gnu-']
    subprocess.run(command+['olddefconfig'],env=env,check=True)
    subprocess.run(command+['-j'+str(args.jobs),'Image','modules'],env=env,check=True)
    if profile=='y60' and (kernel/'drivers/power/supply/eta6937-charger.c').read_bytes()!=(here/'eta6937-charger.c').read_bytes():
        raise ValueError('Y60 charger input changed during compilation; rerun preparation/build before delivery')
    release=(build/'include/config/kernel.release').read_text().strip()
    tags=('-yuanhang41s-', '-yh41s-') if profile=='yuanhang41s' else ('-'+profile+'-',)
    if not any(tag in release for tag in tags):
        raise ValueError('Wrong profile release: '+release)
    for source,target in (('arch/arm64/boot/Image','Image'),('.config','config'),
            ('System.map','System.map'),('modules.builtin','modules.builtin'),
            ('modules.builtin.modinfo','modules.builtin.modinfo'),('include/config/kernel.release','kernel.release')):
        shutil.copy2(build/source,out/target)
    subprocess.run(['python3',str(TOP/'upstream/wrap-image.py'),str(out/'Image'),str(out/'Image.lk')],check=True)
    modules=out/'modules';modules.mkdir(exist_ok=True);names=set()
    for line in (build/'modules.order').read_text().splitlines():
        source=(build/line).with_suffix('.ko')
        if source.name in names:raise ValueError('Colliding module basename: '+source.name)
        names.add(source.name);target=modules/source.name;shutil.copy2(source,target)
        subprocess.run(['llvm-strip','--strip-debug',str(target)],check=True)
    for stale in modules.glob('*.ko'):
        if stale.name not in names:stale.unlink()
    resolve=runpy.run_path(str(TOP/'devices/common/bringup-probe.py'))['module_order']
    early=resolve(modules,(here/'module-order.txt').read_text().split(),release)
    (out/'module-order.txt').write_text('\n'.join(early)+'\n')
    def owned(info):
        info.uid=info.gid=0;info.uname=info.gname='root';return info
    with tarfile.open(out/'modules.tar','w') as archive:
        for name in sorted(names):archive.add(modules/name,arcname='lib/modules/'+release+'/'+name,filter=owned)
    (out/'baseline.json').write_text(json.dumps({'sha256':hashlib.sha256(baseline).hexdigest(),
        'profile':profile,'source_commit':subprocess.check_output(['git','-c','safe.directory='+str(kernel),'-C',str(kernel),'rev-parse','HEAD'],text=True).strip()},indent=2)+'\n')
    runpy.run_path(str(TOP/'upstream/check-container-support.py'))['check'](out,record=True)
    print('Verified complete profile kernel and module cohort:',out)


if __name__=='__main__':main()
