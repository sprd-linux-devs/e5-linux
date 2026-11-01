"""41S stock SQC charger variants; keep each address's register encoding."""
from pathlib import Path
import runpy
HERE=Path(__file__).resolve().parent

def probe_identity(source):
 # Stock module PN dispatch: 0/1/2/9 only. Never infer the chip from DT alone.
 marker='/* 41S stock variant identification before any charger writes. */'
 if marker in source:return source
 probe=source.index('static int bq2560x_charger_probe(')
 markers=('\t/* 41S stock address selection; identify before any charger writes. */',
          '\t/* P720S11 SGM41513: factory driver switches this DT alias to 0x1a. */',
          '\tret = bq2560x_read(info, BQ2560X_REG_B, &val);')
 start=next(source.index(m,probe) for m in markers if m in source[probe:])
 end=source.index('\n\ti2c_set_clientdata(client, info);', start)
 source=source[:start]+'''\t/* 41S stock variant identification before any charger writes. */
\tret = yh41s_identify(info);
\tif (ret)
\t\treturn ret;
''' + source[end:]
 # Remove only probe's obsolete ID variable, not other register helpers'.
 source=source[:probe]+source[probe:].replace('\tunsigned char val = 0;\n','',1)
 return source

def apply(kernel):
 replace=runpy.run_path(str(HERE.parent/'t551m/prepare-kernel.py'))['replace_function']
 path=Path(kernel)/'drivers/power/supply/bq2560x-charger.c';s=path.read_text(encoding="utf-8")
 variants=(HERE/'charger-variants.h').read_bytes()
 obsolete=path.parent/'yh41s-charger-variants.h'
 if obsolete.is_symlink() or (obsolete.exists() and obsolete.read_bytes()!=variants):
  raise ValueError('Unrecognized generated 41S charger header; retain for review')
 if 'yh41s-charge-current.h' not in s:s='#include "yh41s-charge-current.h"\n'+s
 s=s.replace('#include "yh41s-charger-variants.h"\n','')
 if 'static int yh41s_identify(' not in s:
  s=s.replace('static int bq2560x_write(',
              (HERE/'charger-identify.c').read_text()+'\nstatic int bq2560x_write(',1)
 s=s.replace('#define BQ2560X_REG_NUM\t\t\t\t0x12','#define BQ2560X_REG_NUM\t\t\t\t0x0e')
 s=s.replace('for (i = 0; i <= 0x11; i++)','for (i = 0; i <= 0x0d; i++)')
 s=probe_identity(s)
 # The alternate I2C client transports registers; original DT device owns IRQ.
 s=s.replace('devm_request_threaded_irq(&info->client->dev, info->client->irq,',
             'devm_request_threaded_irq(info->dev, info->client->irq,')
 s=s.replace('enable_irq_wake(client->irq);', 'enable_irq_wake(info->client->irq);')
 # Use this handset's battery DT, never the donor's initial 4112 mV.
 s=s.replace('bq2560x_charger_set_termina_vol(info, 4112)',
             'bq2560x_charger_set_termina_vol(info, voltage_max_microvolt)')
 # SQC leaves the hardware watchdog disabled until its policy takes ownership.
 # Keep that startup behavior when the probe has not loaded charger-manager.
 marker='\tinfo->current_charge_limit_cur = BQ2560X_REG_ICHG_LSB * 1000;'
 if '41S factory watchdog startup' not in s:
  start=s.index('static int bq2560x_charger_hw_init(')
  pos=s.index(marker,start)
  s=s[:pos]+'''\t/* 41S factory watchdog startup: SQC hw_init uses timeout=0. */
\tret = bq2560x_update_bits(info, BQ2560X_REG_5,
\t\tBQ2560X_REG_WATCHDOG_TIMER_MASK, 0);
\tif (ret)
\t\treturn ret;

'''+s[pos:]
 s=replace(s,'bq2560x_charger_set_current','''
    return bq2560x_update_bits(info, BQ2560X_REG_2,
        BQ2560X_REG_ICHG_MASK, yh41s_variant_charge_code(info->client->addr, cur / 1000));''')
 s=replace(s,'bq2560x_charger_get_current','''
    u8 value;
    int ret = bq2560x_read(info, BQ2560X_REG_2, &value);
    if (ret < 0) return ret;
    *cur = yh41s_variant_charge_ma(info->client->addr, value) * 1000;
    return 0;''')
 # Stock sqc_bq2560x.ko usb_get_property 0x4ed4..0x4f10 reads CHRG_STAT.
 # The donor's software flag never reports FULL, even after HW termination.
 s=replace(s,'bq2560x_charger_get_status','''
    u8 value;
    int ret;

    ret = bq2560x_read(info, BQ2560X_REG_8, &value);
    if (ret < 0)
        return ret;
    /* This donor uses hardware PG, not stock SQC's cached input limit. */
    if (!(value & BIT(2)))
        return POWER_SUPPLY_STATUS_DISCHARGING;
    if (!info->charging)
        return POWER_SUPPLY_STATUS_NOT_CHARGING;
    switch ((value >> 3) & 3) {
    case 0:
        return POWER_SUPPLY_STATUS_NOT_CHARGING;
    case 3:
        return POWER_SUPPLY_STATUS_FULL;
    default:
        return POWER_SUPPLY_STATUS_CHARGING;
    }''')
 old='\t\tval->intval = bq2560x_charger_get_status(info);'
 new='''\t\tret = bq2560x_charger_get_status(info);
\t\tif (ret < 0)
\t\t\tgoto out;
\t\tval->intval = ret;
\t\tret = 0;'''
 if new not in s:
  if s.count(old)!=1:raise ValueError('Charger STATUS error handling anchor changed')
  s=s.replace(old,new)
 s=replace(s,'bq2560x_charger_set_termina_vol','''
    u8 code;
    /* Same rounding and REG04 range as this unit's stock SQC driver. */
    code = vol < 3856 ? 0 : vol >= 4624 ? 24 : (vol - 3856) / 32 + 1;
    return bq2560x_update_bits(info, BQ2560X_REG_4,
        BQ2560X_REG_TERMINAL_VOLTAGE_MASK, code << 3);''')
 s=replace(s,'bq2560x_charger_get_termina_vol','''
    u8 value;
    int ret = bq2560x_read(info, BQ2560X_REG_4, &value);
    if (ret < 0) return ret;
    value = (value >> 3) & 31;
    *vol = value == 15 ? 4352 : value * 32 + 3856;
    return 0;''')
 s=replace(s,'bq2560x_charger_set_termina_cur','''
    u8 code, offset = 0;
    int ret;
    /* Stock sqc_mp_set_ieoc: 0x6b has linear 60 mA steps and no REG0D. */
    if (info->client->addr != 0x1a)
        return bq2560x_update_bits(info, BQ2560X_REG_3,
            BQ2560X_REG_TERMINAL_CUR_MASK, yh41s_linear_term_code(cur));
    ret = bq2560x_update_bits(info, 0x0d, BIT(0), cur > 240 ? 0 : BIT(0));
    if (ret) return ret;
    if (cur > 240) {
        if (cur <= 360) { offset = 5; code = (cur - 240) / 60; }
        else if (cur < 480) code = 7;
        else if (cur <= 1200) { offset = 8; code = (cur - 480) / 120; }
        else code = 15;
    } else {
        if (cur < 5) code = 0;
        else if (cur <= 20) code = (cur - 5) / 5;
        else if (cur <= 60) { offset = 3; code = (cur - 20) / 10; }
        else if (cur < 80) code = 7;
        else { offset = 8; code = (cur - 80) / 20; }
    }
    code = min_t(u8, code + offset, 15);
    return bq2560x_update_bits(info, BQ2560X_REG_3,
        BQ2560X_REG_TERMINAL_CUR_MASK, code);''')
 path.write_text(s)
 # Reuse this profile's existing generated codec header. No extra native-only
 # kernel input can leak into another model's shared lower source view.
 (path.parent/'yh41s-charge-current.h').write_bytes((HERE/'charge-current.h').read_bytes()+b'\n'+variants)
 if obsolete.exists():obsolete.unlink()  # Only the exact output owned above.
if __name__=='__main__':
 import sys
 apply(sys.argv[1])
