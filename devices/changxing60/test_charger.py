"""Execute the prepared charger's actual register helpers against bus stubs."""
from pathlib import Path
import os
import re
import runpy
import subprocess
import tempfile
import unittest

HERE=Path(__file__).resolve().parent


def battery_fixture():
    return ('int sprd_battery_get_battery_info(void) {\n' +
        ''.join('\tof_property_read_u32_index(battery_np, "charge-'+kind+'-current-microamp", '+str(index)+',\n'
            '\t\t\t\t   &info->cur.'+kind+('_cur' if index==0 else '_limit')+');\n'
            for kind in ('sdp','dcp','cdp','unknown') for index in (0,1)) +
        '\tsprd_battery_parse_step_chg_table(info, battery_np, psy);\n}\n')


def function(source,name):
    match=re.search(r'static (?:int|bool|u32)\s+'+name+r'\([^;{}]*\)\s*\{',source)
    if not match:raise ValueError('Missing helper '+name)
    end=source.index('{',match.start())+1
    depth=1
    while depth:
        depth+=(source[end]=='{')-(source[end]=='}')
        end+=1
    return source[match.start():end]


class Charger(unittest.TestCase):
    @unittest.skipIf(os.name=='nt','Linux C compiler required')
    def test_factory_voltage_and_hardware_status_with_bus_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            supply=root/'drivers/power/supply'
            supply.mkdir(parents=True)
            target=supply/'bq2560x-charger.c'
            (supply/'sprd_battery_info.c').write_text(battery_fixture())
            target.write_bytes((HERE.parent/'m8/port/drivers/power/supply/bq2560x-charger.c').read_bytes())
            for name in ('Kconfig','Makefile'):(supply/name).write_text('')
            runpy.run_path(str(HERE/'charger.py'))['apply'](root)
            code=target.read_text()
            fixture='''#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdbool.h>
typedef uint8_t u8;
typedef uint32_t u32;
struct bq2560x_charger_info { bool charging;int chip_type,input_limit_cur_lock;u32 last_limit_cur,actual_limit_cur; };
#define BIT(n) (1u<<(n))
#define GENMASK(h,l) (((1u<<((h)-(l)+1))-1)<<(l))
#define clamp_val(v,lo,hi) ((v)<(lo)?(lo):((v)>(hi)?(hi):(v)))
#define dev_dbg(...) ((void)0)
#define dev_err(...) ((void)0)
#define dev_info(...) ((void)0)
#define CHIP_SGM41511 1
#define CHIP_SGM41542 2
#define BQ2560X_REG_0 0
#define BQ2560X_REG_2 2
#define BQ2560X_REG_4 4
#define BQ2560X_REG_8 8
#define BQ2560X_REG_TERMINAL_VOLTAGE_MASK 0xf8
#define POWER_SUPPLY_STATUS_CHARGING 1
#define POWER_SUPPLY_STATUS_DISCHARGING 2
#define POWER_SUPPLY_STATUS_NOT_CHARGING 3
#define POWER_SUPPLY_STATUS_FULL 4
static u8 regs[12];
static int bus_error;
static void mutex_lock(int *lock) {assert(!*lock);*lock=1;}
static void mutex_unlock(int *lock) {assert(*lock);*lock=0;}
static int bq2560x_read(struct bq2560x_charger_info *i, u8 reg, u8 *value) {
    (void)i; assert(reg<12); if(bus_error) return -EIO; *value=regs[reg]; return 0;
}
static int bq2560x_update_bits(struct bq2560x_charger_info *i, u8 reg, u8 mask, u8 value) {
    (void)i; assert(reg<12); if(bus_error) return -EIO;
    regs[reg]=(regs[reg]&~mask)|(value&mask); return 0;
}
'''
            fixture+='\n'.join(line for line in code.splitlines() if re.match(
                r'#define\s+BQ2560X_(REG_ICHG_LSB|REG_ICHG_MASK|REG_LIMIT_CURRENT_MASK|LIMIT_CURRENT_MAX|LIMIT_CURRENT_OFFSET|REG_IINLIM_BASE)\s',line))+'\n'
            for name in ('bq2560x_charger_get_limit_current','bq2560x_charger_set_limit_current',
                         'bq2560x_charger_set_current','bq2560x_charger_get_current',
                         'bq2560x_charger_set_termina_vol',
                         'bq2560x_charger_get_termina_vol','bq2560x_charger_get_status'):
                fixture+=function(code,name)+'\n'
            fixture+='''int main(void) {
    struct bq2560x_charger_info i={.chip_type=CHIP_SGM41511,.charging=true}; u32 value;
    regs[0]=0xe0;regs[2]=0xc0;
    assert(!bq2560x_charger_set_limit_current(&i,2500000,false));
    assert(regs[0]==0xf8 && !i.input_limit_cur_lock);
    assert(!bq2560x_charger_get_limit_current(&i,&value) && value==2500000);
    assert(!bq2560x_charger_set_current(&i,2500000));
    assert(regs[2]==0xe9);
    assert(!bq2560x_charger_get_current(&i,&value) && value==2460000);
    for (u32 mv=0; mv<=6000; mv++) {
        /* Replay the captured AArch64 setter arithmetic (3e20..3e54). */
        unsigned packed=mv<3856?0:(mv>>4)>0x120?0xc0:(((mv+0xf0)>>2)+8)&~7u;
        regs[4]=7;
        assert(!bq2560x_charger_set_termina_vol(&i,mv));
        assert(regs[4]==((packed&0xf8)|7));
    }
    assert(!bq2560x_charger_set_termina_vol(&i,4400));
    assert(!bq2560x_charger_get_termina_vol(&i,&value) && value==4432);
    for(unsigned code=0; code<32; code++) {
        regs[4]=code<<3;
        assert(!bq2560x_charger_get_termina_vol(&i,&value));
        assert(value==(code==15?4352:3856+code*32));
    }
    for(unsigned reg=0; reg<256; reg++) {
        unsigned state=(reg>>3)&3;
        int want=!(reg&4)?2:state==0?3:state==3?4:1;
        regs[8]=reg;
        assert(bq2560x_charger_get_status(&i)==want);
    }
    bus_error=1; regs[4]=0x97;
    assert(bq2560x_charger_set_termina_vol(&i,4400)==-EIO && regs[4]==0x97);
    assert(bq2560x_charger_get_termina_vol(&i,&value)==-EIO);
    assert(bq2560x_charger_get_status(&i)==-EIO);
    i.charging=false;
    assert(bq2560x_charger_get_status(&i)==POWER_SUPPLY_STATUS_NOT_CHARGING);
    i.charging=true;
    assert(bq2560x_charger_set_current(&i,2500000)==-EIO);
    assert(bq2560x_charger_set_limit_current(&i,2500000,false)==-EIO && !i.input_limit_cur_lock);
    return 0;
}
'''
            source=root/'test.c';source.write_text(fixture)
            binary=root/'test'
            subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror',str(source),'-o',str(binary)],check=True)
            subprocess.run([str(binary)],check=True)


    def test_policy_integration_replaces_old_override_and_is_idempotent(self):
        policy=runpy.run_path(str(HERE/'charger.py'))['dcp_charge_policy']
        original=battery_fixture()
        changed=policy(original)
        self.assertEqual(policy(changed),changed)
        self.assertEqual(changed.count('changxing60_dcp_profile(info)'),1)
        self.assertLess(changed.index('sprd_battery_parse_step_chg_table'),changed.index('changxing60_dcp_profile(info)'))
        legacy=('\n\t/* User-requested P720S20 DCP input ceiling; not battery charge current. */\n'
                '\tif (info->cur.dcp_limit > 0)\n\t\tinfo->cur.dcp_limit = 2500000;')
        old=original.replace('\t\t\t\t   &info->cur.dcp_limit);','\t\t\t\t   &info->cur.dcp_limit);'+legacy)
        self.assertEqual(policy(old),changed)
        self.assertNotIn('info->cur.dcp_limit = 2500000;',changed)
        with self.assertRaises(ValueError):policy('unrecognized parser')
        with self.assertRaises(ValueError):policy(original.replace('sprd_battery_parse_step_chg_table','unknown_loader'))

    @unittest.skipIf(os.name=='nt','Linux C compiler required')
    def test_dcp_profile_changes_both_limits_and_preserves_thermal_protection(self):
        fixture='''#include <assert.h>
#include <stdbool.h>
#include <string.h>
#define ARRAY_SIZE(a) (sizeof(a)/sizeof(*(a)))
#define SPRD_BATTERY_JEITA_DCP 0
struct sprd_battery_jeita_table {int temp,recovery_temp,current_ua,term_volt;};
struct sprd_battery_info {
 int charge_full_design_uah,constant_charge_voltage_max_uv,voltage_min_design_uv,constant_charge_current_max_ua;
 struct {int dcp_cur,dcp_limit,sdp_cur,sdp_limit,cdp_cur,cdp_limit,unknown_cur,unknown_limit;} cur;
 struct sprd_battery_jeita_table *jeita_table[1];
 unsigned int sprd_battery_jeita_size[1],max_current_jeita_index[1];
};
'''+(HERE/'charge-profile.h').read_text()+'''
int main(void) {
    struct sprd_battery_jeita_table rows[]={
      {0,30,0,4400000},{100,130,600000,4400000},{150,180,600000,4400000},
      {450,420,1000000,4400000},{550,520,900000,4100000}};
    struct sprd_battery_jeita_table original[5];memcpy(original,rows,sizeof(rows));
    struct sprd_battery_info info={3000000,4400000,3450000,1000000,
      {1000000,1000000,700000,500000,1000000,1000000,1000000,1000000},{rows},{5},{3}};
    struct sprd_battery_info native=info;
    assert(changxing60_dcp_profile(&info));
    assert(info.cur.dcp_limit==2500000 && info.cur.dcp_cur==2500000 && info.constant_charge_current_max_ua==2500000);
    assert(info.cur.sdp_cur==700000 && info.cur.sdp_limit==500000 && info.cur.cdp_cur==1000000 && info.cur.cdp_limit==1000000);
    assert(info.cur.unknown_cur==1000000 && info.cur.unknown_limit==1000000 && info.max_current_jeita_index[0]==3);
    for(int i=0;i<5;i++) {
      assert(rows[i].temp==original[i].temp && rows[i].recovery_temp==original[i].recovery_temp);
      assert(rows[i].term_volt==original[i].term_volt);
      assert(rows[i].current_ua==(i==3?2500000:original[i].current_ua));
    }
    assert(!changxing60_dcp_profile(&info));
    for(int n=0;n<9+5*4;n++) {
      info=native;memcpy(rows,original,sizeof(rows));
      switch(n) {
      case 0:info.charge_full_design_uah++;break;
      case 1:info.constant_charge_voltage_max_uv++;break;
      case 2:info.voltage_min_design_uv++;break;
      case 3:info.constant_charge_current_max_ua=-22;break;
      case 4:info.cur.dcp_cur=-22;break;
      case 5:info.cur.dcp_limit=-22;break;
      case 6:info.jeita_table[0]=0;break;
      case 7:info.sprd_battery_jeita_size[0]--;break;
      case 8:info.sprd_battery_jeita_size[0]++;break;
      default: {
        int row=(n-9)/4;
        switch((n-9)%4) {
        case 0:rows[row].temp++;break;
        case 1:rows[row].recovery_temp++;break;
        case 2:rows[row].current_ua++;break;
        case 3:rows[row].term_volt++;break;
        }
      }}
      struct sprd_battery_info saved=info;
      struct sprd_battery_jeita_table saved_rows[5];memcpy(saved_rows,rows,sizeof(rows));
      assert(!changxing60_dcp_profile(&info));
      assert(!memcmp(&saved,&info,sizeof(info)) && !memcmp(saved_rows,rows,sizeof(rows)));
    }
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'test.c').write_text(fixture)
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(root/'test.c'),'-o',str(root/'test')],check=True)
            subprocess.run([str(root/'test')],check=True)


if __name__=='__main__':unittest.main()
