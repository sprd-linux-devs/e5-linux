#!/usr/bin/env python3
"""Inspect a Y60 backup offline; never execute its binaries or access hardware."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct


def fdt_nodes(data):
    if len(data) < 40:
        raise ValueError('Truncated FDT')
    magic,total,structure,strings,_,version,_,_,string_size,structure_size = struct.unpack_from('>10I',data)
    if magic != 0xd00dfeed or version < 17 or not 40 <= total <= len(data):
        raise ValueError('Invalid FDT header')
    if any(start < 40 or start+size > total for start,size in ((structure,structure_size),(strings,string_size))):
        raise ValueError('FDT blocks out of range')
    names=data[strings:strings+string_size];at=structure;end=at+structure_size;stack=[];nodes={}
    while at+4 <= end:
        token=struct.unpack_from('>I',data,at)[0];at+=4
        if token==1:
            stop=data.find(b'\0',at,end)
            if stop<0:raise ValueError('Unterminated FDT node')
            stack.append(data[at:stop].decode('utf-8'));at=(stop+4)&~3
            path='/'.join(stack) or '/'
            if path in nodes:raise ValueError('Duplicate FDT node')
            nodes[path]={}
        elif token==2:
            if not stack:raise ValueError('FDT node underflow')
            stack.pop()
        elif token==3:
            if not stack or at+8>end:raise ValueError('Invalid FDT property')
            size,index=struct.unpack_from('>II',data,at);at+=8
            stop=names.find(b'\0',index)
            if index>=len(names) or stop<0 or at+size>end:raise ValueError('FDT property out of range')
            name=names[index:stop].decode('utf-8');props=nodes['/'.join(stack) or '/']
            if name in props:raise ValueError('Duplicate FDT property')
            props[name]=data[at:at+size];at=(at+size+3)&~3
        elif token==4:continue
        elif token==9:
            if stack:raise ValueError('Unclosed FDT node')
            return nodes
        else:raise ValueError('Unknown FDT token')
    raise ValueError('Missing FDT terminator')


def fdt_blobs(data):
    at=0;found=[]
    while (at:=data.find(b'\xd0\x0d\xfe\xed',at))>=0:
        if at+8<=len(data):
            size=struct.unpack_from('>I',data,at+4)[0]
            if 40<=size<=len(data)-at:
                try:fdt_nodes(data[at:at+size])
                except (ValueError,UnicodeError,struct.error):pass
                else:found.append((at,data[at:at+size]))
        at+=4
    return found


def dtbo_entries(data):
    if len(data)<32:raise ValueError('Truncated DTBO table')
    magic,total,header,entry_size,count,offset,page,version=struct.unpack_from('>8I',data)
    if (magic!=0xd7b7ab1e or not 32<=header<=offset or not 32<=entry_size or
            not 1<=count<=256 or offset+count*entry_size>total or total>len(data) or version!=0):
        raise ValueError('Invalid DTBO table')
    entries=[]
    for index in range(count):
        size,start,ident,rev,*custom=struct.unpack_from('>8I',data,offset+index*entry_size)
        if start<offset+count*entry_size or size<40 or start+size>total:
            raise ValueError('DTBO payload out of range')
        blob=data[start:start+size];nodes=fdt_nodes(blob)
        entries.append((dict(index=index,id=ident,revision=rev,custom=custom,offset=start,size=size),blob,nodes))
    spans=sorted((meta['offset'],meta['offset']+meta['size']) for meta,_,_ in entries)
    if any(a[1]>b[0] for a,b in zip(spans,spans[1:])):raise ValueError('Overlapping DTBO payloads')
    return entries


def display(data):
    if not data:return True
    # An integer cell containing zero (or e.g. 0x20000000) is not a list
    # of empty strings. FDT string lists consist of nonempty NUL-terminated
    # strings; keep numeric GPIO/reg cells numeric in the evidence report.
    parts=data[:-1].split(b'\0') if data[-1:]==b'\0' else []
    if parts and all(part and all(32<=b<127 for b in part) for part in parts):
        return [part.decode('ascii') for part in parts]
    if len(data)%4==0 and len(data)<=64:return list(struct.unpack('>'+str(len(data)//4)+'I',data))
    return data[:96].hex()+('...' if len(data)>96 else '')


def boot_selection(data):
    """Keep public board-selection evidence, never the full boot command line.

    Some logs first print a placeholder dtbo_idx=0. Report observations and
    the last reported selection, rather than silently selecting overlay zero.
    A backup log still cannot establish the identity of a future live unit.
    """
    indices=[int(v) for v in re.findall(rb'androidboot\.dtbo_idx=([0-9]{1,3})(?![0-9])',data)]
    panels=[v.decode('ascii') for v in re.findall(rb'lcd_name=(LCD_[A-Za-z0-9_]{1,120})',data)]
    return dict(reported_dtbo_indices=list(dict.fromkeys(indices)),
                dtbo_index_observations=len(indices), reported_panels=list(dict.fromkeys(panels)),
                last_reported_dtbo_index=indices[-1] if indices else None,
                last_reported_panel=panels[-1] if panels else None,
                live_identity_verified=False)


def summary(nodes):
    selected={}
    interest=re.compile(r'panel|lcd|backlight|touch|i2c|spi|charger|battery|fgu|fuel|usb|typec|aw87|aw88|codec|audio|sound|sdio|sdhci|mmc|ufs|wcn|marlin|thermal|cpufreq|dvfs|vibrator',re.I)
    omit=re.compile(r'imei|serial-number|mac-address',re.I)
    for path,props in nodes.items():
        compat=props.get('compatible',b'').decode(errors='replace')
        if path=='/' or interest.search(path+' '+compat):
            selected[path]={key:display(value) for key,value in props.items()
                            if not omit.search(key) and key not in ('phandle','linux,phandle') and len(value)<=512}
    return selected


def inspect(root,out):
    root=Path(root).resolve();out=Path(out).resolve()
    if out==root or out.is_relative_to(root):raise ValueError('Output must be outside the backup')
    if not (root/'boot_a.img').is_file() and (root/'Image').is_dir():root=root/'Image'
    out.mkdir(parents=True,exist_ok=True)
    report={'backup':str(root),'hardware_validated':False,'files':{},'overlays':[]}
    log=root/'uboot_log.img'
    if log.is_file():
        if log.stat().st_size>32<<20:raise ValueError('Unexpected boot log size')
        report['boot_selection']=boot_selection(log.read_bytes())
    for name in ('boot_a.img','boot_b.img','vendor_boot_a.img','vendor_boot_b.img','dtb_a.img','dtb_b.img','dtbo_a.img','dtbo_b.img','sml_a.img','sml_b.img'):
        path=root/name
        if not path.is_file():continue
        if path.stat().st_size>128<<20:raise ValueError('Unexpected boot input size')
        data=path.read_bytes();row={'size':len(data),'sha256':hashlib.sha256(data).hexdigest()}
        if data.startswith(b'ANDROID!'):
            row['header_version']=struct.unpack_from('<I',data,40)[0]
            versions=re.findall(rb'Linux version [0-9][^\0\n]{1,350}',data)
            row['kernel_versions']=[v.decode(errors='replace') for v in versions]
        if name=='vendor_boot_a.img':
            blobs=fdt_blobs(data)
            row['base_fdt_count']=len(blobs)
            for index,(offset,blob) in enumerate(blobs):
                (out/('base-'+str(index)+'.dtb')).write_bytes(blob)
                nodes=fdt_nodes(blob)
                report.setdefault('base_trees',[]).append({'offset':offset,'sha256':hashlib.sha256(blob).hexdigest(),'nodes':summary(nodes)})
        if name=='dtbo_a.img':
            for meta,blob,nodes in dtbo_entries(data):
                (out/('overlay-'+str(meta['index'])+'.dtbo')).write_bytes(blob)
                report['overlays'].append({**meta,'sha256':hashlib.sha256(blob).hexdigest(),'nodes':summary(nodes)})
        report['files'][name]=row
    (out/'inspection.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'report':str(out/'inspection.json'),'base_trees':len(report.get('base_trees',[])),
                      'overlays':len(report['overlays']),'kernel':report['files'].get('boot_a.img',{}).get('kernel_versions')},ensure_ascii=False))
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('backup',type=Path);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();inspect(args.backup,args.output)
