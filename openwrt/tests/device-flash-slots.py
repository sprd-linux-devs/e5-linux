"""Execute the real Linux updater against temporary boot/misc files, both roles."""
import ast
import hashlib
import os
from pathlib import Path
import runpy
import shlex
import subprocess
import tempfile
import unittest
from types import SimpleNamespace

TOP=Path(__file__).resolve().parents[2]
helper=runpy.run_path(str(TOP/'openwrt/tests/installer-slot-roles.py'))


class Flash(unittest.TestCase):
    def run_case(self,android,bad=None,kind='emmc',chain=None):
        linux='b' if android=='a' else 'a'
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);run=root/'run';run.mkdir();by=root/'by';by.mkdir()
            roles=helper['api']['role_files'](helper['control'](android),android)
            for name,data in roles.items():
                if name.startswith('etc/e5linux/'):(run/Path(name).name).write_bytes(data)
            declared=root/'linux-slot';declared.write_text(linux+'\n')
            if bad=='conflict':declared.write_text(android+'\n')
            if bad=='short':(run/'misc-bc-slot-b-trial.bin').write_bytes(('_'+linux).encode())
            nodes=root/'nodes';nodes.mkdir();sys=root/'sys';sys.mkdir()
            disk='mmcblk0' if kind=='emmc' else 'sda'
            controller=root/'devices'/('mmc-controller' if kind=='emmc' else '20200000.ufs')
            device=controller/'host0'/'device';device.mkdir(parents=True)
            block=device/'block'/disk;block.mkdir(parents=True)
            (block/'device').symlink_to(device,target_is_directory=True)
            (device/'type').write_text('MMC\n')
            (sys/disk).symlink_to(block,target_is_directory=True)
            def partition(label,index,data):
                name=disk+('p' if kind=='emmc' else '')+str(index)
                path=block/name;path.mkdir();(path/'partition').write_text(str(index))
                (path/'uevent').write_text('PARTNAME='+label+'\n')
                (path/'size').write_text(str(len(data)//512)+'\n')
                (sys/name).symlink_to(path,target_is_directory=True)
                node=nodes/name;node.write_bytes(data);return node
            for label,index,data in [('boot_a',5,b'A'*(2<<20)),('boot_b',6,b'B'*(2<<20)),('misc',3,b'M'*4096)]:
                (by/label).symlink_to(partition(label,index,data))
            misc=(by/'misc').resolve()
            (run/'misc-dev').write_text(str(misc)+'\n')
            if bad=='missing':(block/(disk+('p' if kind=='emmc' else '')+('5' if linux=='a' else '6'))/'uevent').write_text('PARTNAME=other\n')
            if bad=='duplicate':partition('boot_'+linux,7,b'KEEP')
            original={p.name:p.read_bytes() for p in by.iterdir()}
            footer=b'AVBf'+b'F'*60
            head=root/'boot-head.img';head.write_bytes(b'N'*(1<<20)+footer)
            if bad=='head-only':head.write_bytes(head.read_bytes()[:-64])
            if bad=='short-footer':head.write_bytes(head.read_bytes()[:-1])
            if bad=='footer-magic':head.write_bytes(head.read_bytes()[:-64]+b'BAD!'+footer[4:])
            code=(TOP/'openwrt/device-flash-boot.sh').read_text()
            # Keep real per-file dd fsync/readback, without syncing unrelated
            # host mounts (including Windows/WSL shares) from this fixture.
            code=code.replace('set -eu', 'set -eu\nsync() { :; }', 1)
            (root/'storage.sh').write_bytes((TOP/'boot/storage.sh').read_bytes())
            code=code.replace("printf '/dev/%s\\n'", "printf '"+str(nodes)+"/%s\\n'")
            code=code.replace('/run/e5linux',str(run)).replace('/etc/e5/linux-slot',str(declared))
            code=code.replace('/tmp/e5-boot-head.img',str(root/'temporary.img')).replace('[ -b ','[ -f ')
            # A real block device does not truncate on open; mirror that for
            # this regular-file fixture while keeping the actual dd/readback.
            code=code.replace('conv=fsync','conv=notrunc,fsync')
            if bad=='footer-readback':
                code=code.replace('dd of="$BOOTB" bs=1 seek="$FOOTER_AT" count=64 conv=notrunc,fsync',
                                  'dd of=/dev/null bs=1 count=64')
            script=root/'device-flash-boot.sh';script.write_text(code)
            command=['sh',str(script),str(head),hashlib.sha256(head.read_bytes()).hexdigest(),'1']
            if chain:
                # Use the updater's real command construction. Stub only the
                # already separately tested staging operation and final reboot;
                # run the actual storage resolver, boot writer, and shell gates.
                tree=ast.parse((TOP/'tools/e5-update.py').read_text())
                body=next(n.body for n in ast.walk(tree) if isinstance(n,ast.With)
                    and any(isinstance(s,ast.Assign) and any(isinstance(t,ast.Name)
                        and t.id=='command' for t in s.targets) for s in n.body))
                start=next(i for i,s in enumerate(body) if isinstance(s,ast.Assign)
                    and any(isinstance(t,ast.Name) and t.id=='command' for t in s.targets))
                stop=next(i for i in range(start,len(body)) if isinstance(body[i],ast.If)
                    and isinstance(body[i].test,ast.Name) and body[i].test.id=='GUI')
                scope=dict(stage=str(root),head=head,hashlib=hashlib,shlex=shlex,
                    capacity_env='',nv_policy='preserve',profile='changxing60',
                    source_profile='changxing60',layout='part',
                    a=SimpleNamespace(raw_size=1<<20,raw_sha256='0'*64),
                    boot={'persist_log_offset':1<<20})
                exec(compile(ast.Module(body=body[start:stop],type_ignores=[]),'updater-command','exec'),scope)
                pending=root/'pending';pending.mkdir()
                (root/'device-stage-part-update.sh').write_text(
                    'printf ready > '+shlex.quote(str(pending/'request.ready'))+'\n'+
                    ('exit 23\n' if chain=='stage-fail' else 'echo staged\n'))
                built=scope['command'].replace('/run/e5-upgrade',str(root/'upgrade'))
                # The target runs as root; local fixtures can run unprivileged.
                built=built.replace('= 0:700', '= '+str(os.getuid())+':700')
                built=built.replace('/.e5-update/',str(pending)+'/')
                built=built.replace('(sleep 3; reboot) </dev/null >/dev/null 2>&1 &',
                    ': > '+shlex.quote(str(root/'rebooted')))
                command=['sh','-c','set -eu\nsync() { :; }\n'+built]
            result=subprocess.run(['env','E5_STORAGE_SYS='+str(sys),*command],capture_output=True,text=True,timeout=20)
            if chain:
                success=not bad and chain!='stage-fail'
                self.assertEqual((pending/'request').exists(),success,result.stdout+result.stderr)
                self.assertEqual((root/'rebooted').exists(),success,result.stdout+result.stderr)
            if bad or chain=='stage-fail':
                self.assertNotEqual(result.returncode,0)
                if bad=='footer-readback':
                    self.assertEqual((by/('boot_'+linux)).read_bytes(),head.read_bytes()[:-64]+original['boot_'+linux][1<<20:])
                    self.assertEqual((by/('boot_'+android)).read_bytes(),original['boot_'+android])
                    self.assertEqual(misc.read_bytes(),original['misc'])
                else:self.assertEqual({p.name:p.read_bytes() for p in by.iterdir()},original)
            else:
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                self.assertEqual((by/('boot_'+android)).read_bytes(),original['boot_'+android])
                self.assertEqual((by/('boot_'+linux)).read_bytes(),head.read_bytes()[:-64]+original['boot_'+linux][1<<20:-64]+footer)
                self.assertEqual(misc.read_bytes(),original['misc'][:2048]+roles['etc/e5linux/misc-bc-slot-b-trial.bin']+original['misc'][2080:])

    def test_writes_only_the_identified_linux_slot(self):
        for kind in ('emmc','ufs'):
            for slot in ('a','b'):
                with self.subTest(android=slot,kind=kind):self.run_case(slot,kind=kind)

    def test_incomplete_and_conflicting_roles_stop_before_writes(self):
        for kind in ('emmc','ufs'):
            for slot in ('a','b'):
                for bad in ('short','conflict','missing','duplicate'):
                    with self.subTest(android=slot,bad=bad,kind=kind):self.run_case(slot,bad,kind)

    def test_missing_or_invalid_footer_stops_before_any_partition_write(self):
        for kind in ('emmc','ufs'):
            for slot in ('a','b'):
                for bad in ('head-only','short-footer','footer-magic'):
                    with self.subTest(android=slot,bad=bad,kind=kind):self.run_case(slot,bad,kind)

    def test_footer_readback_failure_does_not_arm_or_reboot(self):
        for kind in ('emmc','ufs'):
            for slot in ('a','b'):
                with self.subTest(android=slot,kind=kind):self.run_case(slot,'footer-readback',kind,'flash-fail')

    def test_updater_publishes_request_and_reboots_only_after_success(self):
        for kind in ('emmc','ufs'):
            for slot in ('a','b'):
                for chain,bad in [('success',None),('stage-fail',None),('flash-fail','missing')]:
                    with self.subTest(android=slot,kind=kind,chain=chain):
                        self.run_case(slot,bad,kind,chain)


if __name__=='__main__':unittest.main()
