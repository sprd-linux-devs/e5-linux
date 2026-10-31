#!/usr/bin/env python3
"""Exercise real boot calibration/restore C, including old prepared-tree migration.

Mock PMIC/RTC inputs only; this does not validate battery accuracy on hardware.
"""
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
shared = runpy.run_path(str(HERE/'fuel-gauge.py'))
tests = runpy.run_path(str(HERE/'test_fuel_gauge.py'))
CORE = 'drivers/power/supply/sprd_fuel_gauge_core.c'

EXTRA = r'''
typedef long long s64;
#define dev_warn(...) ((void)0)
#define SPRD_FGU_CAP_CALIB_TEMP_LOW 100
#define SPRD_FGU_CAP_CALIB_TEMP_HI 450
#define SPRD_FGU_MISCDATA_RTC_TIME 1621355101LL
#define SPRD_FGU_SHUTDOWN_TIME (15*60)
'''
STUBS = r'''
static int live_mv,live_error,rtc_error,live_reads;
static s64 rtc_now;
static bool density_ok;
static bool sprd_fgu_is_in_low_energy_dens(struct sprd_fgu_data *d,int v,int t,int n)
{(void)d;(void)v;(void)t;(void)n;return density_ok;}
static int sprd_fgu_get_rtc_time(struct sprd_fgu_data *d,s64 *v)
{(void)d;*v=rtc_now;return rtc_error;}
static int sprd_fgu_get_vbat_ocv(struct sprd_fgu_data *d,int *v)
{(void)d;live_reads++;*v=live_mv;return live_error;}
static struct sprd_fgu_data ready(void) {
 struct sprd_fgu_data d=fresh();d.support_boot_calib=true;d.bat_temp=250;
 rtc_now=1793377005;d.shutdown_rtc_time=rtc_now-900;
 live_mv=3800;live_error=rtc_error=live_reads=0;density_ok=true;return d;
}
'''
MAIN = r'''
int main(void) {
 struct sprd_fgu_data d;int cap;
 /* A stale high AND low latch must not alter saved SOC or tracking state. */
 int volts[]={3499999,3500000,3800000,4100000,4100001};
 for(unsigned i=0;i<sizeof(volts)/sizeof(volts[0]);i++) {
  d=ready();cap=254;sprd_fgu_boot_cap_calibration(&d,946,volts[i],&cap);
  bool valid=i>=1&&i<=3;
  assert(d.track.pocv_info.valid==valid&&cap==(valid?916:254));
  if(valid)assert(d.track.pocv_info.ocv_uv==volts[i]&&d.track.pocv_info.ocv_time_stamp==rtc_now);
 }
 d=ready();cap=946;sprd_fgu_boot_cap_calibration(&d,254,3800000,&cap);assert(cap==284);
 for(int difference=-30;difference<=30;difference++) {
  d=ready();cap=500;sprd_fgu_boot_cap_calibration(&d,500+difference,3800000,&cap);assert(cap==500);
 }
 d=ready();live_error=-EIO;cap=254;sprd_fgu_boot_cap_calibration(&d,946,3800000,&cap);
 assert(cap==254&&!d.track.pocv_info.valid);
 /* Existing vendor gates, including the 113-second observed boot, stay intact. */
 for(int gate=0;gate<11;gate++) {
  d=ready();cap=254;
  switch(gate) {
   case 0:d.support_boot_calib=false;break;
   case 1:d.sw_pocv_flag=true;break;
   case 2:d.shutdown_rtc_time=0;break;
   case 3:d.shutdown_rtc_time=-1;break;
   case 4:d.shutdown_rtc_time=SPRD_FGU_MISCDATA_RTC_TIME-1;break;
   case 5:density_ok=false;break;
   case 6:d.bat_temp=99;break;
   case 7:d.bat_temp=451;break;
   case 8:rtc_error=-EIO;break;
   case 9:rtc_now=SPRD_FGU_MISCDATA_RTC_TIME-1;break;
   case 10:d.shutdown_rtc_time=rtc_now-113;break;
  }
  sprd_fgu_boot_cap_calibration(&d,946,3800000,&cap);
  assert(cap==254&&!d.track.pocv_info.valid&&!live_reads);
 }
 for(int age=899;age<=900;age++) {
  d=ready();d.shutdown_rtc_time=rtc_now-age;cap=254;
  sprd_fgu_boot_cap_calibration(&d,946,3800000,&cap);
  assert(cap==(age==900?916:254));
 }
 for(int temp=100;temp<=450;temp+=350) {
  d=ready();d.bat_temp=temp;cap=254;sprd_fgu_boot_cap_calibration(&d,946,3800000,&cap);assert(cap==916);
 }
 /* Actual restore function: discard stale calibration, never invent a percent. */
 d=ready();live_mv=3400;retained_ui=254;retained_normal=300;
 assert(!sprd_fgu_get_boot_capacity(&d,&cap));
 assert(cap==300&&d.normal_temp_cap==300&&d.boot_cap==254&&!ui_writes&&!d.track.pocv_info.valid);
 /* Old corrupted but correctly encoded pairs cannot be repaired by guessing. */
 d=ready();live_mv=3400;retained_ui=254;retained_normal=946;
 assert(!sprd_fgu_get_boot_capacity(&d,&cap)&&cap==946&&d.boot_cap==254);
 d=ready();retained_ui=254;retained_normal=300;
 assert(!sprd_fgu_get_boot_capacity(&d,&cap)&&cap==390&&d.boot_cap==254&&d.track.pocv_info.valid);
 d=ready();live_error=-EIO;retained_ui=254;retained_normal=300;
 assert(!sprd_fgu_get_boot_capacity(&d,&cap)&&cap==300&&d.boot_cap==254);
 d=ready();retained_ui=254;retained_normal=300;normal_read_error=-EIO;
 assert(sprd_fgu_get_boot_capacity(&d,&cap)==-EIO&&!ui_writes&&!normal_writes);
 d=ready();retained_ui=254;retained_normal=300;voltage_error=-EIO;
 assert(sprd_fgu_get_boot_capacity(&d,&cap)==-EIO&&!normal_writes);
 puts("PASS: real boot SOC restore/calibration, +/-300mV boundaries, RTC/temperature/time gates, bus failures and retained UI/raw separation");
}
'''


def main():
    kernel = Path(sys.argv[1]).resolve()
    paths = [line[6:] for line in shared['PATCH'].read_text().splitlines()
             if line.startswith('+++ b/')]
    with tempfile.TemporaryDirectory(prefix='boot-soc-') as tmp:
        root = Path(tmp)
        for name in paths:
            target = root/name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(subprocess.check_output([
                'git', '-c', 'safe.directory='+str(kernel), '-C', str(kernel), 'show', 'HEAD:'+name]))
        shared['apply'](root)
        core = (root/CORE).read_text()
        canonical = {name:(root/name).read_bytes() for name in paths}
        shared['apply'](root)
        assert canonical == {name:(root/name).read_bytes() for name in paths}
        # Upgrade a cache prepared by the former board-specific adapter.
        begin = core.index('\t/* Stock UMP96xx boot-OCV consistency')
        end = core.index('\tdata->track.pocv_info.valid = true;', begin)
        (root/CORE).write_text(core[:begin]+shared['LEGACY_BOOT_OCV']+core[end:])
        shared['apply'](root)
        assert canonical == {name:(root/name).read_bytes() for name in paths}
        # An unfamiliar legacy block must fail atomically, not accumulate checks.
        (root/CORE).write_text(core[:begin]+shared['LEGACY_BOOT_OCV'].replace('300000','300001')+core[end:])
        broken = {name:(root/name).read_bytes() for name in paths}
        try:
            shared['apply'](root)
        except ValueError:
            pass
        else:
            raise AssertionError('unknown legacy block accepted')
        assert broken == {name:(root/name).read_bytes() for name in paths}
        print('PASS: legacy 41S migration, repeat preparation, unknown source rejected atomically')

        stubs = tests['CORE_STUBS']
        empty = 'static void sprd_fgu_boot_cap_calibration(struct sprd_fgu_data *d,int ocv,int voltage,int *cap){(void)d;(void)ocv;(void)voltage;(void)cap;}'
        assert stubs.count(empty) == 1
        stubs = stubs.replace(empty, '').replace('bool is_first_poweron;', '''bool is_first_poweron;
 bool support_boot_calib,sw_pocv_flag;int bat_temp,cap_calib_dens_ocv_table,cap_calib_dens_ocv_table_len;
 s64 shutdown_rtc_time;struct {struct {bool valid;int ocv_uv;s64 ocv_time_stamp;} pocv_info;} track;''')
        body = '\n'.join(tests['function'](core, name) for name in (
            'sprd_fgu_boot_cap_calibration', 'sprd_fgu_get_boot_capacity'))
        for fixed in (True, False):
            code = body if fixed else body.replace(core[begin:end], '')
            fixture = root/'boot.c'
            fixture.write_text(tests['PRELUDE']+EXTRA+stubs+STUBS+code+MAIN)
            exe = root/'boot'
            subprocess.run(['cc', '-std=gnu11', '-Wall', '-Werror', '-Wno-unused-function',
                            '-Wno-unused-but-set-variable',
                            str(fixture), '-o', str(exe)], check=True)
            result = subprocess.run([str(exe)], capture_output=True, text=True)
            if fixed:
                assert result.returncode == 0, result.stderr
                print(result.stdout, end='')
            else:
                assert result.returncode != 0, 'old stale-POCV defect was not detected'
                print('PASS: negative control reproduces missing stale-POCV gate')


if __name__ == '__main__':
    main()
