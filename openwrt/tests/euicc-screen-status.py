#!/usr/bin/env python3
"""Exercise the actual screen dependency gate with real ARM64 ucode fs.access."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

TOP = Path(__file__).resolve().parents[2]
docker = os.environ.get('DOCKER_EXE') or shutil.which('docker')
if not docker:
    raise SystemExit('Select the installed Docker CLI with DOCKER_EXE')
source = (TOP/'devices/common/infoscreen/esim/backend.uc').read_text()
source = source.replace("'/usr/lib/lpac'", "'/tmp/esim-lpac'").replace(
    "'/usr/libexec/unisoc-modem/euicc'", "'/tmp/esim-backend'")
runner = r'''import { writefile, chmod, unlink } from 'fs';
let routes=loadfile('/fixture/backend.uc',{raw_mode:true})()({sh:()=>''});
for(let mode in ['absent','both','missing_backend','not_executable']) {
 unlink('/tmp/esim-lpac');unlink('/tmp/esim-backend');
 if(mode!='absent'){writefile('/tmp/esim-lpac','#!/bin/sh\n');chmod('/tmp/esim-lpac',0755);}
 if(mode=='both'||mode=='not_executable'){
  writefile('/tmp/esim-backend','#!/bin/sh\n');chmod('/tmp/esim-backend',mode=='both'?0755:0644);
 }
 print(sprintf('%J\n',{mode,status:routes['GET /status']()}));
}
'''
(TOP/'work').mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix='euicc-status-',dir=TOP/'work') as temp:
    fixture=Path(temp)
    (fixture/'backend.uc').write_text(source)
    (fixture/'runner.uc').write_text(runner)
    p=subprocess.run([docker,'run','--rm','--pull=never','--network','none','--platform','linux/arm64',
        '--mount',f'type=bind,source={fixture.resolve()},target=/fixture,readonly',
        '--entrypoint','/usr/bin/ucode','mu300-openwrt-base:25.12.5','/fixture/runner.uc'],
        capture_output=True,text=True,timeout=35)
    assert p.returncode==0,p.stderr
    rows=[json.loads(s) for s in p.stdout.splitlines()]
    assert len(rows)==4,rows
    for row in rows:
        assert row['status']['installed']==(row['mode']=='both'),row
        assert row['status']['installing'] is False,row
print('PASS screen dependency gate: actual ARM64 ucode, installed/missing/non-executable cases')
