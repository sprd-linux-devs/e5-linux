"""P720S20 stock SQC charger variants, without another board's A6 encoding.

Evidence: captured 20240919 P720S20 sqc_bq2560x.ko, sqc_mp_set_cv at
0x3df8 and sqc_mp_get_cv at 0x3ef4; stock battery DT supplies the limits.
This prepares a module. The initial display probe does not load it.
"""
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent


def dcp_charge_policy(source):
    """P720S20 requested DCP input/CC policy, after native JEITA parsing."""
    # Replace the former input-only override rather than stacking a second
    # policy on it. The complete profile is checked in the shared loader's
    # board-specific hook, after all temperature/voltage tables are available.
    legacy = ('\n\t/* User-requested P720S20 DCP input ceiling; not battery charge current. */\n'
              '\tif (info->cur.dcp_limit > 0)\n\t\tinfo->cur.dcp_limit = 2500000;')
    source = source.replace(legacy, '')
    include = '#include "changxing60-charge-profile.h"'
    if include not in source:
        anchor = 'int sprd_battery_get_battery_info('
        if source.count(anchor) != 1:
            raise ValueError('Unexpected P720S20 battery-info loader')
        source = source.replace(anchor, include + '\n\n' + anchor, 1)
    if 'changxing60_dcp_profile(info)' not in source:
        anchor = '\tsprd_battery_parse_step_chg_table(info, battery_np, psy);'
        if source.count(anchor) != 1:
            raise ValueError('Unexpected P720S20 parsed battery profile')
        source = source.replace(anchor, anchor +
            '\n\tif (changxing60_dcp_profile(info))\n'
            '\t\tdev_info(&psy->dev, "P720S20 DCP: 2.5 A input and normal-temperature battery charge; thermal limits retained\\n");', 1)
    return source


def apply(kernel):
    kernel = Path(kernel)
    battery = kernel/'drivers/power/supply/sprd_battery_info.c'
    updated_battery = dcp_charge_policy(battery.read_text())
    replace = runpy.run_path(str(HERE.parent/'t551m/prepare-kernel.py'))['replace_function']
    path = kernel/'drivers/power/supply/bq2560x-charger.c'
    source = path.read_text().replace('GPL-2.0:', 'GPL-2.0-only')
    source = source.replace('#include <linux/gpio/consumer.h>',
                            '#include <linux/gpio/consumer.h>\n#include <linux/gpio.h>\n#include <linux/extcon.h>')
    source = source.replace('static int bq2560x_charger_probe(struct i2c_client *client,\n\t\tconst struct i2c_device_id *id)',
                            'static int bq2560x_charger_probe(struct i2c_client *client)')
    source = source.replace('static int bq2560x_charger_remove(struct i2c_client *client)',
                            'static void bq2560x_charger_remove(struct i2c_client *client)')
    source = source.replace('\tmutex_destroy(&info->lock);\n\n\treturn 0;\n}',
                            '\tmutex_destroy(&info->lock);\n}')
    source = source.replace('charger_cfg.of_node = dev->of_node;',
                            'charger_cfg.fwnode = dev_fwnode(dev);').replace('GPIOF_DIR_IN', 'GPIOF_IN')
    source = source.replace('.name\t\t\t= "charger",', '.name\t\t\t= "bq2560x_charger",')
    source = source.replace('struct bq2560x_charger_info {',
                            'struct bq2560x_charger_info {\n\tu8 stock_pn;')
    if '#include "cx60-charger-variants.h"' not in source:
        source = '#include "yh41s-charge-current.h"\n#include "cx60-charger-variants.h"\n' + source
    source = source.replace('static int bq2560x_write(',
                            (HERE/'charger-identify.c').read_text()+'\nstatic int bq2560x_write(', 1)
    start = source.index('\tret = bq2560x_read(info,BQ2560X_REG_B, &val);')
    end = source.index('\n\ti2c_set_clientdata(client, info);', start)
    source = source[:start] + '''
\tret = cx60_identify(info);
\tif (ret)
\t\treturn ret;
''' + source[end:]
    probe = source.index('static int bq2560x_charger_probe(')
    source = source[:probe] + source[probe:].replace('\tunsigned char val = 0;\n', '', 1)
    # Alternate address belongs to this original DT device's lifetime/IRQ.
    source = source.replace('devm_request_threaded_irq(&info->client->dev, info->client->irq,',
                            'devm_request_threaded_irq(info->dev, info->client->irq,')
    source = source.replace('enable_irq_wake(client->irq);', 'enable_irq_wake(info->client->irq);')
    source = replace(source, 'bq2560x_charger_set_current', '''
\tu8 code = cx60_charge_code(info->client->addr, info->stock_pn, cur / 1000);
\treturn bq2560x_update_bits(info, BQ2560X_REG_2, BQ2560X_REG_ICHG_MASK, code);''')
    source = replace(source, 'bq2560x_charger_get_current', '''
\tu8 value;
\tint ret = bq2560x_read(info, BQ2560X_REG_2, &value);
\tif (ret < 0)
\t\treturn ret;
\t*cur = cx60_charge_ma(info->client->addr, value) * 1000;
\treturn 0;''')
    source = replace(source, 'bq2560x_charger_set_termina_cur', '''
\tint ret;
\tif (info->client->addr == 0x1a) {
\t\tret = bq2560x_update_bits(info, 0x0d, BIT(0), cur > 240 ? 0 : BIT(0));
\t\tif (ret)
\t\t\treturn ret;
\t}
\treturn bq2560x_update_bits(info, BQ2560X_REG_3,
\t\tBQ2560X_REG_TERMINAL_CUR_MASK, cx60_term_code(info->client->addr, cur));''')
    source = replace(source, 'bq2560x_charger_set_termina_vol', '''
\tu8 code;
\t/* Actual stock SQC setter: same upward encoding and range. */
\tcode = vol < 3856 ? 0 : vol >= 4624 ? 24 : (vol - 3856) / 32 + 1;
\treturn bq2560x_update_bits(info, BQ2560X_REG_4,
\t\tBQ2560X_REG_TERMINAL_VOLTAGE_MASK, code << 3);''')
    source = replace(source, 'bq2560x_charger_get_termina_vol', '''
\tu8 value;
\tint ret = bq2560x_read(info, BQ2560X_REG_4, &value);
\tif (ret < 0)
\t\treturn ret;
\tvalue = (value >> 3) & 31;
\t*vol = value == 15 ? 4352 : 3856 + value * 32;
\treturn 0;''')
    # Avoid a donor's SGM41542 extended-register adjustments on this chip.
    source = replace(source, 'bq2560x_charger_set_vindpm', '''
\tu8 code = (clamp_val(vol, 3900, 5400) - 3900) / 100;
\treturn bq2560x_update_bits(info, BQ2560X_REG_6,
\t\tBQ2560X_REG_VINDPM_VOLTAGE_MASK, code);''')
    source = replace(source, 'bq2560x_charger_set_vindpmos', '\treturn -EOPNOTSUPP;')
    source = replace(source, 'bq2560x_charger_get_status', '''
\tu8 value;
\tint ret;
\tif (!info->charging)
\t\treturn POWER_SUPPLY_STATUS_NOT_CHARGING;
\tret = bq2560x_read(info, BQ2560X_REG_8, &value);
\tif (ret < 0)
\t\treturn ret;
\t/* Stock SQC reads CHRG_STAT rather than its software enable flag. */
\tif (!(value & BIT(2)))
\t\treturn POWER_SUPPLY_STATUS_DISCHARGING;
\tswitch ((value >> 3) & 3) {
\tcase 0: return POWER_SUPPLY_STATUS_NOT_CHARGING;
\tcase 3: return POWER_SUPPLY_STATUS_FULL;
\tdefault: return POWER_SUPPLY_STATUS_CHARGING;
\t}''')
    source = source.replace('\t\tval->intval = bq2560x_charger_get_status(info);', '''\t\tret = bq2560x_charger_get_status(info);
\t\tif (ret < 0)
\t\t\tgoto out;
\t\tval->intval = ret;
\t\tret = 0;''')
    source = replace(source, 'bq2560x_charger_register_vbus_regulator', '''
\tstruct regulator_config cfg = {
\t\t.dev = info->dev,
\t\t.of_node = info->dev->of_node,
\t\t.driver_data = info,
\t};
\tstruct regulator_dev *reg;
\tif (info->role != BQ2560X_ROLE_MASTER_DEFAULT)
\t\treturn 0;
\t/* The regulator belongs to this I2C device and its captured DT child. */
\treg = devm_regulator_register(info->dev, &bq2560x_charger_vbus_desc, &cfg);
\treturn PTR_ERR_OR_ZERO(reg);''')
    source = source.replace('bq2560x_charger_set_termina_vol(info, 4112)',
                            'bq2560x_charger_set_termina_vol(info, voltage_max_microvolt)')
    # Keep bootloader safety/recharge/boost settings until their own policy
    # takes ownership; the donor's register-A and timer block is another IC.
    start = source.index('\n\tret = bq2560x_update_bits(info, BQ2560X_REG_A,')
    end = source.index('\n\tinfo->current_charge_limit_cur', start)
    source = source[:start] + '''
\t/* Stock SQC starts with the watchdog disabled. */
\tret = bq2560x_update_bits(info, BQ2560X_REG_5,
\t\tBQ2560X_REG_WATCHDOG_TIMER_MASK, 0);
\tif (ret)
\t\treturn ret;
''' + source[end:]
    source = source.replace(
        '\tif (limit_cur >= BQ2560X_LIMIT_CURRENT_MAX)\n\t\tlimit_cur = BQ2560X_LIMIT_CURRENT_MAX;',
        '\tlimit_cur = clamp_val(limit_cur, BQ2560X_LIMIT_CURRENT_OFFSET, BQ2560X_LIMIT_CURRENT_MAX);')
    source = source.replace('val->intval = info->chip_type;',
        '{ u8 status; ret = bq2560x_read(info, BQ2560X_REG_8, &status);\n\t\t\tif (!ret) val->intval = !!(status & BIT(2)); }')
    source = source.replace('''\t\tret = bq2560x_charger_get_termina_vol(info, &vol);
\t\tval->intval = vol *1000;''', '''\t\tret = bq2560x_charger_get_termina_vol(info, &vol);
\t\tif (ret)
\t\t\tgoto out;
\t\tval->intval = vol * 1000;''')
    source = source.replace('\tPOWER_SUPPLY_PROP_CONSTANT_CHARGE_CURRENT,\n',
        '\tPOWER_SUPPLY_PROP_CONSTANT_CHARGE_CURRENT,\n\tPOWER_SUPPLY_PROP_CONSTANT_CHARGE_VOLTAGE_MAX,\n')
    source = source.replace('''\tcase POWER_SUPPLY_PROP_CONSTANT_CHARGE_CURRENT:
\tcase POWER_SUPPLY_PROP_INPUT_CURRENT_LIMIT:''', '''\tcase POWER_SUPPLY_PROP_CONSTANT_CHARGE_CURRENT:
\tcase POWER_SUPPLY_PROP_CONSTANT_CHARGE_VOLTAGE_MAX:
\tcase POWER_SUPPLY_PROP_INPUT_CURRENT_LIMIT:''')
    source = source.replace('#define BQ2560X_REG_NUM\t\t\t\t0x10',
                            '#define BQ2560X_REG_NUM\t\t\t\t0x0c')
    source = source.replace('for (i = 0; i < 0x10; i++)', 'for (i = 0; i <= 0x0b; i++)')
    path.write_text(source)
    battery.write_text(updated_battery)
    (battery.parent/'changxing60-charge-profile.h').write_bytes((HERE/'charge-profile.h').read_bytes())
    (battery.parent/'cx60-charger-variants.h').write_bytes((HERE/'charger-variants.h').read_bytes())
    # The stock P720S20 binary independently uses this same SGM41513 codec.
    (battery.parent/'yh41s-charge-current.h').write_bytes((HERE.parent/'yuanhang41s/charge-current.h').read_bytes())
    for name, marker, addition in (
        ('drivers/power/supply/Kconfig', 'config CHARGER_BQ2560X_SPRD',
         'config CHARGER_BQ2560X_SPRD\n\ttristate "Unisoc BQ2560x charger"\n\tdepends on I2C && CHARGER_MANAGER && GPIOLIB\n'),
        ('drivers/power/supply/Makefile', 'bq2560x-charger.o',
         'obj-$(CONFIG_CHARGER_BQ2560X_SPRD) += bq2560x-charger.o\n'),
    ):
        target=kernel/name
        text=target.read_text()
        if marker not in text:
            target.write_text(text+'\n'+addition)
