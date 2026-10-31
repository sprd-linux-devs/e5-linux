"""Real ucode policy/board tests and offline build wiring; no hardware writes."""
from pathlib import Path
import os
import runpy
import subprocess
import tempfile

TOP = Path(__file__).resolve().parents[2]
OVERLAY = TOP/'openwrt/overlay'
HERE = Path(__file__).resolve().parent
FAMILY = 'e5' if (TOP/'devices/battery-guard.py').is_file() else 'mu300'


def main():
    with tempfile.TemporaryDirectory(prefix='battery-guard-test-') as directory:
        root = Path(directory)
        for name in ('battery', 'etc/e5', 'run/mu300',
                     'sys/firmware/devicetree/base/charger-manager', 'sys/firmware/devicetree/base/battery'):
            (root/name).mkdir(parents=True, exist_ok=True)
        runner = ['docker', 'run', '--pull', 'never', '--rm', '--network', 'none',
                  '--platform', 'linux/arm64',
                  '-v', str(OVERLAY/'usr/libexec/unisoc-battery')+':/guard:ro',
                  '-v', str(root)+':/fixtures',
                  '-v', str(HERE)+':/tests:ro', 'mu300-openwrt-base:25.12.5']
        subprocess.run([*runner, 'ucode', '/tests/battery-guard.uc'], check=True)
        subprocess.run([*runner, 'ucode', '/tests/battery-adapter.uc', FAMILY], check=True)
        if FAMILY == 'e5':
            subprocess.run([*runner, 'ucode', '/tests/battery-checkpoint.uc'], check=True)
        # Compile the actual service entrypoint, not only its policy imports.
        subprocess.run([*runner, 'ucode', '-c', '-o', '/tmp/watch.ucb', '/guard/watch.uc'], check=True)
        (root/'state.json').write_text('{"present":1,"capacity":40,"voltage":3800000}')
        events_runner = runner[:-1] + ['-v', str(OVERLAY/'etc/hotplug.d/power_supply/80-unisoc-battery')+
                                      ':/etc/hotplug.d/power_supply/80-unisoc-battery:ro', runner[-1]]
        subprocess.run([*events_runner, 'sh', '/tests/battery-events.sh'], check=True, timeout=30)

        if FAMILY == 'e5':
            stage = runpy.run_path(str(TOP/'devices/battery-guard.py'))['stage']
            offline = root/'offline'
            offline.mkdir()
            stage(offline)
            stage(offline)
            for name in ('S86unisoc-battery', 'K08unisoc-battery'):
                link = offline/'etc/rc.d'/name
                assert link.is_symlink() and os.readlink(link) == '../init.d/unisoc-battery'
            for name in ('devices/e5/stage.py', 'devices/m8/stage.py', 'devices/t551m/configure-rootfs.py'):
                assert "devices/battery-guard.py" in (TOP/name).read_text()
            # No Debian/base or profile assembler can leave only a dangling rc link.
            assert 'unisoc-battery' in (TOP/'openwrt/build-rootfs.sh').read_text()
            print('PASS: three model stagers, idempotent offline service deployment, full build entry')
        else:
            service = (OVERLAY/'etc/init.d/unisoc-battery').read_text()
            for model in ('f50', 'v50', 'mu300', 'u30air'):
                # Execute the real init function with a simulated model probe.
                body = service.replace('/opt/mu300/bin/mu300-device 2>/dev/null', 'printf "$BOARD"')
                shell = '''
procd_open_instance() { printf 'OPEN\n'; }
procd_set_param() { :; }
procd_close_instance() { :; }
''' + body + '\nstart_service\n'
                result = subprocess.run(['sh', '-c', shell], env={**os.environ, 'BOARD':model},
                                        capture_output=True, text=True, check=True)
                assert ('OPEN' in result.stdout) == (model == 'u30air'), model
            builder = (TOP/'openwrt/build-rootfs.sh').read_text()
            assert 'mu300-user-packages unisoc-battery ttyd' in builder
            assert 'K08unisoc-battery' in builder
            print('PASS: F50/V50 exclusion and both mainline kernel build paths')
        for name in ('etc/init.d/unisoc-battery', 'etc/hotplug.d/power_supply/80-unisoc-battery'):
            subprocess.run(['sh', '-n', str(OVERLAY/name)], check=True)


if __name__ == '__main__':
    main()
