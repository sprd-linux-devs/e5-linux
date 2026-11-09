"""Execute the shell read-error policy without touching a kernel cache/device."""
import runpy
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

TOP = Path(__file__).resolve().parents[2]
POLICY = runpy.run_path(str(TOP/'devices/common/thermal.py'))

SOURCE = r'''#include <linux/kernel.h>
static int sample(struct thermal_zone_device *tz, int *temp)
{
 int ret = thermal_zone_get_temp(tz, temp);
 if (ret || *temp >= 120000) {
  pr_err("get thermal %s temp failed\n", thermal_zone_device_type(tz));
  return thermal_zone_get_temp(&board, temp);
 }
 return 0;
}
'''


class ShellThermalLogging(unittest.TestCase):
    def test_adapter_is_idempotent_and_rejects_unknown_shapes(self):
        changed = POLICY['quiet_shell_reads'](SOURCE)
        self.assertEqual(POLICY['quiet_shell_reads'](changed), changed)
        with self.assertRaisesRegex(ValueError, 'Unexpected stock shell'):
            POLICY['quiet_shell_reads'](SOURCE.replace('pr_err(', 'unknown_logger('))
        # Each platform's preparation path already applies this common policy.
        for profile in ('e5', 'm8', 't551m'):
            self.assertIn('common/thermal.py', (TOP/f'devices/{profile}/prepare-kernel.py').read_text())

    @unittest.skipUnless(shutil.which('cc'), 'requires host C compiler')
    def test_only_wcn_read_errors_are_quiet_and_fallback_stays_real(self):
        source = POLICY['quiet_shell_reads'](SOURCE)
        source = '\n'.join(line for line in source.splitlines() if not line.startswith('#include'))
        prelude = r'''
#include <errno.h>
#include <string.h>
static int warnings, debug_messages;
struct thermal_zone_device { const char *name; int value, error; };
static struct thermal_zone_device board = {"board-thmzone", 43000, 0};
#define thermal_zone_device_type(tz) ((tz)->name)
#define pr_err(...) (++warnings)
#define pr_err_ratelimited(...) (++warnings)
#define pr_debug(...) (++debug_messages)
static int thermal_zone_get_temp(struct thermal_zone_device *tz, int *temp) {
 if (tz->error) return tz->error;
 *temp=tz->value; return 0;
}
'''
        checks = r'''
int main(void) {
 struct thermal_zone_device wcn={"wcn-thmzone", 40000, -EIO}; int value=0;
 for (int i=0;i<100;i++) if(sample(&wcn,&value)||value!=43000)return 1;
 if(warnings || debug_messages!=100)return 2;
 wcn.error=0;
 if(sample(&wcn,&value)||value!=40000)return 3;
 wcn.value=125000;
 if(sample(&wcn,&value)||value!=43000||warnings!=1)return 4;
 wcn.name="pa-thmzone"; wcn.error=-EIO;
 if(sample(&wcn,&value)||value!=43000||warnings!=2)return 5;
 board.error=-EIO;
 if(sample(&wcn,&value)!=-EIO)return 6;
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); source_path=root/'logging.c'; binary=root/'logging'
            source_path.write_text(prelude+source+checks)
            subprocess.run(['cc','-std=c99','-Wall','-Werror',str(source_path),'-o',str(binary)],check=True,capture_output=True)
            subprocess.run([str(binary)],check=True)


if __name__ == '__main__': unittest.main()
