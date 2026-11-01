#!/usr/bin/env python3
"""Build locally using private overlay views of the existing pinned kernel.

Run through tools/build-release.py run. The prepared donor is never rewritten;
only its Git changes are replaced in a small, profile-owned overlay upperdir.
Each profile retains its own Git index, object output and complete module cohort.
"""
from contextlib import contextmanager
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess

TOP = Path(__file__).resolve().parents[1]
OWNER = 'e5-profile-kernel-overlay-v1'
PROFILES = ('e5', 't551m', 'm8', 't512n', 'lym10k', 'changxing60', 'y60')


def git(tree, *args):
    return subprocess.check_output(['git', '-c', 'safe.directory='+str(tree),
                                    '-C', str(tree), *args])


def inventory(lower):
    # Git's default abbreviation grows when a partial clone fills its object
    # store. Fingerprint full IDs so that metadata growth is not a source edit.
    diff = git(lower, 'diff', '--binary', '--full-index', 'HEAD', '--')
    changed = git(lower, 'diff', '--name-only', '-z', 'HEAD', '--').split(b'\0')
    extra = git(lower, 'ls-files', '--others', '-z').split(b'\0')
    digest = hashlib.sha256(diff)
    for raw in sorted(filter(None, extra)):
        p = lower/os.fsdecode(raw)
        if not p.is_symlink() and not p.is_file():
            raise ValueError('Unexpected non-file in the source cache: '+str(p))
        digest.update(raw+b'\0')
        digest.update(os.fsencode(os.readlink(p)) if p.is_symlink() else p.read_bytes())
    return digest.hexdigest(), [os.fsdecode(p) for p in changed if p], [os.fsdecode(p) for p in extra if p]


def owned_path(root, name):
    relative = Path(name)
    if relative.is_absolute() or '..' in relative.parts or relative.parts[0] == '.git':
        raise ValueError('Unsafe source path: '+name)
    p = root/relative
    for parent in p.parents:
        if parent == root:
            break
        if parent.is_symlink():
            raise ValueError('Symlink source parent: '+str(parent))
    return p


def review_shadowed_lower(workspace, lower, profile, revision):
    """Refresh registration only when every donor edit is fully shadowed.

    The private upperdir already stores the baseline/board adaptation or a
    whiteout for each donor path. A donor change behind such an entry cannot
    alter the build view. Unknown/unshadowed paths still require manual review.
    Run under build-release.py's workspace lock, with the view unmounted.
    """
    workspace, lower = workspace.resolve(), lower.resolve()
    if profile not in PROFILES or not lower.is_relative_to(workspace):
        raise ValueError('Use a registered model and existing workspace kernel')
    if git(lower, 'rev-parse', 'HEAD').decode().strip() != revision:
        raise ValueError('Kernel revision differs from the registered baseline')
    parent = workspace/'kernel-views'/profile
    upper, view, marker = parent/'upper', parent/'source', parent/'owner.json'
    if any(p.is_symlink() for p in (workspace/'kernel-views', parent, upper, view, marker)) or os.path.ismount(view):
        raise ValueError('Unsafe or active profile view')
    record = json.loads(marker.read_text())
    expected = {'owner': OWNER, 'profile': profile, 'lower': str(lower), 'revision': revision}
    if any(record.get(k) != v for k, v in expected.items()):
        raise ValueError('Profile view identity differs from registered inputs')
    if (upper/'.git').read_bytes() != (view/'.git').read_bytes():
        raise ValueError('Private profile indexes differ')
    fingerprint, changed, extra = inventory(lower)
    audit = []
    for name in sorted(set(changed + extra)):
        path = owned_path(upper, name)
        if not os.path.lexists(path):
            raise ValueError('Unshadowed donor change: '+name)
        mode = path.lstat().st_mode
        whiteout = stat.S_ISCHR(mode) and path.lstat().st_rdev == os.makedev(0, 0)
        if not (stat.S_ISREG(mode) or stat.S_ISLNK(mode) or whiteout):
            raise ValueError('Unsupported upper entry: '+name)
        audit.append({'path': name, 'kind': 'whiteout' if whiteout else 'private-file'})
    # Recheck before the sole write: no source/objects or patch contents change.
    if inventory(lower)[0] != fingerprint:
        raise ValueError('Donor changed during review')
    print(json.dumps({'profile': profile, 'old': record['lower_fingerprint'],
                      'new': fingerprint, 'shadowed': audit}), flush=True)
    record['lower_fingerprint'] = fingerprint
    marker.write_text(json.dumps(record, indent=2)+'\n')


@contextmanager
def source_view(workspace, lower, profile, revision):
    workspace, lower = workspace.resolve(), lower.resolve()
    if profile not in PROFILES or not lower.is_relative_to(workspace):
        raise ValueError('Use a registered model and existing workspace kernel')
    if git(lower, 'rev-parse', 'HEAD').decode().strip() != revision:
        raise ValueError('Kernel revision differs from the registered baseline')
    fingerprint, changed, extra = inventory(lower)
    parent = workspace/'kernel-views'/profile
    for p in (workspace/'kernel-views', parent):
        if p.is_symlink():
            raise ValueError('Overlay directories must not be symlinks')
    parent.mkdir(parents=True, exist_ok=True)
    marker = parent/'owner.json'
    record = {'owner': OWNER, 'profile': profile, 'lower': str(lower),
              'revision': revision, 'lower_fingerprint': fingerprint}
    if marker.exists() and json.loads(marker.read_text()) != record:
        raise ValueError('Lower source changed; review the existing profile view before reusing it')
    upper, work, view = (parent/n for n in ('upper', 'work', 'source'))
    fresh = not marker.exists()
    if fresh:
        if any(p.exists() for p in (upper, work, view)):
            raise ValueError('Refusing to reuse an incomplete/unowned overlay')
        subprocess.run(['git', '-c', 'safe.directory='+str(lower), '-C', str(lower),
                        'worktree', 'add', '--detach', '--no-checkout', str(view), revision], check=True)
        upper.mkdir(); work.mkdir()
        (upper/'.git').write_bytes((view/'.git').read_bytes())
    for p in (lower, upper, work, view):
        if p.is_symlink() or any(c in str(p) for c in ',:\n='):
            raise ValueError('Unsafe overlay mount path')
    if os.path.ismount(view):
        raise ValueError('Profile view is already mounted; another task may own it')
    options=f'lowerdir={lower},upperdir={upper},workdir={work},index=off,redirect_dir=off'
    subprocess.run(['mount', '-t', 'overlay', 'overlay', '-o', options, str(view)], check=True)
    try:
        assert os.path.ismount(view)
        if fresh:
            git(view, 'read-tree', 'HEAD')
            for name in extra:
                p = owned_path(view, name)
                if p.is_symlink() or p.is_file():
                    p.unlink()  # Overlay whiteout; lower data is untouched.
                elif p.exists():
                    raise ValueError('Unexpected untracked source directory: '+name)
            for name in changed:
                p = owned_path(view, name)
                entry = git(lower, 'ls-tree', revision, '--', name)
                if p.is_symlink() or p.is_file():
                    p.unlink()
                if not entry:
                    continue
                mode = entry.split(None, 1)[0]
                data = git(lower, 'cat-file', 'blob', revision+':'+name)
                p.parent.mkdir(parents=True, exist_ok=True)
                if mode == b'120000':
                    p.symlink_to(os.fsdecode(data))
                elif mode in (b'100644', b'100755'):
                    p.write_bytes(data); p.chmod(int(mode, 8)&0o777)
                else:
                    raise ValueError('Unsupported baseline entry: '+name)
            git(view, 'diff', '--quiet', 'HEAD', '--')
            if git(view, 'ls-files', '--others', '--exclude-standard', '-z'):
                raise ValueError('Model view is not a pristine source baseline')
            marker.write_text(json.dumps(record, indent=2)+'\n')
        yield view
    finally:
        subprocess.run(['umount', str(view)], check=True)
        if inventory(lower)[0] != fingerprint:
            raise ValueError('The shared lower source changed during the build')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workspace', type=Path, required=True)
    p.add_argument('--profile', choices=PROFILES, required=True)
    p.add_argument('--jobs', type=int, default=8)
    p.add_argument('--review-shadowed-lower', action='store_true',
                   help='audit shadowed donor edits and refresh only view registration; do not build')
    args=p.parse_args()
    if os.geteuid()!=0 or args.jobs<1:
        raise ValueError('Use Linux root for overlayfs and a positive job count')
    config=json.loads((TOP/'tools/build-layout.json').read_text())
    local=config['local_kernel_build']
    workspace=args.workspace.resolve()
    lower=Path(local['source'].format(workspace=workspace, repo=TOP))
    if args.review_shadowed_lower:
        review_shadowed_lower(workspace, lower, args.profile, local['revision'])
        return
    out=Path(config['profiles'][args.profile]['kernel'].format(workspace=workspace,repo=TOP))
    objects=workspace/'objects'/args.profile
    if objects.is_symlink() or out.is_symlink():
        raise ValueError('Kernel output paths must not be symlinks')
    objects.mkdir(parents=True,exist_ok=True)
    owner=objects/'profile-owner.json'
    identity={'owner':OWNER,'profile':args.profile}
    if owner.exists() and json.loads(owner.read_text()) != identity:
        raise ValueError('Object cache belongs to another model')
    if not owner.exists() and any(objects.iterdir()):
        raise ValueError('Refusing an unregistered existing object cache')
    owner.write_text(json.dumps(identity))
    env=dict(os.environ,LOCALVERSION='',JOBS=str(args.jobs))
    with source_view(workspace,lower,args.profile,local['revision']) as source:
        # Scope Git ownership exceptions to these child processes only.
        count=int(env.get('GIT_CONFIG_COUNT','0'))
        for directory in (source,TOP):
            env['GIT_CONFIG_KEY_'+str(count)]='safe.directory'
            env['GIT_CONFIG_VALUE_'+str(count)]=str(directory)
            count+=1
        env['GIT_CONFIG_COUNT']=str(count)
        if args.profile=='e5':
            env.update(E5_KERNEL_TREE=str(source),E5_OUTDIR=str(objects),E5_FEATURE_OUT=str(out))
            command=['bash','devices/e5/build-kernel.sh']
        elif args.profile=='m8':
            env.update(M8_KERNEL=str(source),M8_BUILD=str(objects),M8_OUT=str(out))
            command=['bash','devices/m8/build-probe.sh']
        elif args.profile in ('changxing60', 'y60'):
            baseline=Path(config['profiles'][args.profile]['platform_config'].format(workspace=workspace,repo=TOP))
            if not baseline.is_file():raise ValueError('Missing registered UMS9620 baseline: '+str(baseline))
            command=['python3',str(TOP/'devices'/args.profile/'build-kernel.py'),'--kernel',str(source),
                     '--build',str(objects),'--base-config',str(baseline),'--out',str(out),'--jobs',str(args.jobs)]
        else:
            prefix=args.profile.upper()
            env.update({prefix+'_KERNEL':str(source),prefix+'_BUILD':str(objects),
                        prefix+'_OUT':str(out),prefix+'_RELEASE':'1'})
            command=['bash','devices/'+args.profile+'/build-kernel.sh']
        subprocess.run(command,cwd=TOP,env=env,check=True)
        if args.profile=='m8':
            subprocess.run(['python3','devices/m8/package-kernel.py','--build',str(objects),
                            '--out',str(out)],cwd=TOP,env=env,check=True)
        if args.profile == 'm8':
            subprocess.run(['python3', str(TOP/'devices/common/test_dwc3_host_sink.py')],
                           env=dict(os.environ, E5_TEST_KERNEL=str(source)), check=True)
        if args.profile in ('e5', 't551m', 't512n', 'lym10k'):
            subprocess.run(['python3', str(TOP/'devices/common/test_musb_host_sink.py')],
                           env=dict(os.environ, MUSB_TEST_KERNEL=str(source)), check=True)
        for test in ('test_fuel_gauge.py','test_fgu_latch.py','test_charger_jeita.py',
                     'test_boot_soc.py','test_battery_periodic.py','test_capacity_remap.py','test_usb_ncm.py'):
            subprocess.run(['python3',str(TOP/'devices/common'/test),str(source)],check=True)
        subprocess.run(['python3',str(TOP/'devices/common/test_power_probe.py'),
                        '--kernel',str(source)],check=True)
        if args.profile=='e5':
            subprocess.run(['python3',str(TOP/'devices/e5/test_charger.py'),str(source)],check=True)
            subprocess.run(['python3',str(TOP/'devices/e5/test_charger_readback.py'),str(source)],check=True)
        subprocess.run(['python3',str(TOP/'upstream/check-container-support.py'),str(out)],check=True)
        (out/'repository-commit').write_bytes(git(TOP,'rev-parse','HEAD'))
        (out/'kernel-source-commit').write_text(local['revision']+'\n')
        (out/'local-build.json').write_text(json.dumps({'profile':args.profile,
            'source_view':str(source),'objects':str(objects),'revision':local['revision']},indent=2)+'\n')


if __name__=='__main__':
    main()
