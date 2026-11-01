#!/usr/bin/env python3
"""Read selected Y60 driver/config evidence from super, without unpacking it."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


def extents(super_image):
    text=subprocess.check_output(['lpdump',str(super_image)],text=True)
    result={}
    for name,body in re.findall(r'  Name: (\S+)\n(.*?)(?=------------------------)',text,re.S):
        if name not in ('vendor_a','odm_a','vendor_dlkm_a'):continue
        found=re.findall(r'^\s+(\d+) \.\. (\d+) linear super (\d+)\s*$',body,re.M)
        if not found:continue
        if len(found)!=1 or int(found[0][0])!=0:raise ValueError('Fragmented evidence partition: '+name)
        first,last,start=map(int,found[0]);offset=start*512;size=(last-first+1)*512
        if offset<0 or size<=0 or offset+size>super_image.stat().st_size:raise ValueError('Extent outside super')
        result[name]={'offset':offset,'size':size}
    if not result:raise ValueError('No vendor evidence extents')
    return result


def extract(source,output):
    source=source.resolve();output=output.resolve()
    if os.name=='nt' or os.geteuid()!=0:raise ValueError('Run in WSL as root; loop devices stay read-only')
    if source.is_relative_to(output) or output.is_relative_to(source.parent):raise ValueError('Output overlaps backup')
    output.mkdir(parents=True,exist_ok=True)
    report={'source':str(source),'partitions':extents(source),'modules':{},'copied':{},'public_assets':[]}
    wanted=re.compile(r'eta6937|fgu|sprd.battery|sprd.charger|charger.manager|tlsc|hyn|bq256|aw87|aw88|snd-soc-sprd-(card|codec-ump9620)|sprd.panel|sprd.dpu|sprd.drm|sc2355|sprd.wlan|sipc.wwan|sprd.typec|sprd.usb',re.I)
    with tempfile.TemporaryDirectory(prefix='y60-ro-',dir=output) as temporary:
        mountpoint=Path(temporary)
        for part,geometry in report['partitions'].items():
            loop=subprocess.check_output(['losetup','--find','--show','--read-only','--offset',str(geometry['offset']),
                                          '--sizelimit',str(geometry['size']),str(source)],text=True).strip()
            mounted=False
            try:
                if not re.fullmatch('/dev/loop[0-9]+',loop):raise ValueError('Unexpected loop device')
                if (Path('/sys/class/block')/Path(loop).name/'ro').read_text().strip()!='1':raise ValueError('Loop is not read-only')
                with open(loop,'rb') as stream:stream.seek(1024);magic=stream.read(64)
                kind='ext4' if magic[56:58]==b'\x53\xef' else 'erofs' if magic[:4]==b'\xe2\xe1\xf5\xe0' else None
                if kind is None:raise ValueError('Unknown vendor filesystem')
                subprocess.run(['mount','-t',kind,'-o','ro,noload' if kind=='ext4' else 'ro',loop,str(mountpoint)],check=True)
                mounted=True
                for path in mountpoint.rglob('*'):
                    if (path.name in ('dsp_vbc.xml','cvs.xml','wcnmodem.bin','gnssmodem.bin')
                            or path.name.startswith(('bt_configure','wifi_board_config'))):
                        report['public_assets'].append(part+'/'+path.relative_to(mountpoint).as_posix())
                    if path.is_symlink() or not path.is_file():continue
                    relative=path.relative_to(mountpoint);name=relative.as_posix();key=part+'/'+name
                    choose=False
                    if path.suffix=='.ko':
                        data=path.read_bytes();digest=hashlib.sha256(data).hexdigest()
                        report['modules'][key]={'bytes':len(data),'sha256':digest,
                            'vermagic':[x.decode(errors='replace') for x in re.findall(rb'\x00vermagic=([^\x00]+)',data)]}
                        choose=bool(wanted.search(path.name))
                    elif name in ('build.prop','etc/build.prop') or path.name.startswith('fstab'):
                        choose=True
                    elif path.suffix=='.xml' and (path.name.startswith('audio') or path.name in ('codec.xml','dsp_vbc.xml','cvs.xml')):
                        choose=True
                    elif path.name=='libimpl-ril.so':choose=True
                    elif path.name.startswith('audio.primary.') and path.suffix=='.so':choose=True
                    elif name in ('bin/modem_control','bin/cp_diskserver','bin/refnotify',
                                  'etc/modem_cp_info.xml','etc/modem_sp_info.xml','etc/modem_ch_info.xml',
                                  'etc/cp_dump_info.xml','etc/ueventd.rc',
                                  'firmware/aw87xxx_acf.bin','firmware/bt_configure_pskey.xpe.ini',
                                  'firmware/bt_configure_rf.xpe.ini'):
                        # Public firmware/configuration only, never prodnv/NV,
                        # property areas, addresses or subscriber identities.
                        choose=True
                    if not choose:continue
                    target=output/key;target.parent.mkdir(parents=True,exist_ok=True)
                    if target.exists() and target.read_bytes()!=path.read_bytes():raise ValueError('Evidence target already differs: '+key)
                    if not target.exists():shutil.copyfile(path,target)
                    report['copied'][key]={'bytes':target.stat().st_size,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}
            finally:
                # Never detach a mounted loop after a failed unmount.
                if mounted:subprocess.run(['umount',str(mountpoint)],check=True)
                subprocess.run(['losetup','-d',loop],check=True)
    (output/'super-evidence.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'report':str(output/'super-evidence.json'),'modules':len(report['modules']),'copied':len(report['copied'])}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('super',type=Path);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();extract(args.super,args.output)
