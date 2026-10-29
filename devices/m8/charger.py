"""Port the M8 factory charger's 0x11/0x12 current and REG0E voltage encoding."""
from pathlib import Path
import runpy
import re


def apply(kernel, *, max_voltage_mv=4250, board='M8', charger_ids=None):
    if type(max_voltage_mv) is not int or not 3856 <= max_voltage_mv <= 4624:
        raise ValueError('Voltage outside the verified stock register range')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,32}', board):
        raise ValueError('Invalid charger board label')
    if charger_ids is None:
        charger_ids = (0x11, 0x12) if board == 'M8' else (0x12,)
    charger_ids = tuple(charger_ids)
    if (not charger_ids or
            any(type(i) is not int or i not in (0x11, 0x12) for i in charger_ids)):
        raise ValueError('Unsupported charger revision set')
    helpers = runpy.run_path(str(Path(__file__).resolve().parent.parent / 't551m/prepare-kernel.py'))
    replace = helpers['replace_function']
    path = kernel / 'drivers/power/supply/bq2560x-charger.c'
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
    # Reuse only the verified A6 current/ID, PMIC and VBUS plumbing, not the
    # T551M kernel/charge profile. M8 has an extended voltage register map.
    source = helpers['board_charger'](source).replace('T551M', board)
    # The reference M8 reports REG0B=0x12; other units of the same model
    # report 0x11 (same BQ2560x family, DEV_REV=1). The stock 0x11 driver
    # uses the standard 60 mA/LSB current encoding; 0x12 keeps the verified
    # A6 piecewise table. K1 stays 0x12-only.
    if charger_ids != (0x12,):
        source = source.replace(
            'if (val != 0x12 || client->addr != 0x6b) {',
            'if ((' + ' && '.join('val != %#x' % i for i in charger_ids) +
            ') || client->addr != 0x6b) {')
    if 'u8 chip_rev;' not in source:
        source = source.replace('struct bq2560x_charger_info {',
                                'struct bq2560x_charger_info {\n\tu8 chip_rev;', 1)
    vendor = board + '-0x12'
    if 0x11 in charger_ids:
        vendor_name = 'val == 0x11 ? "%s-0x11" : "%s"' % (board, vendor)
    else:
        vendor_name = '"%s"' % vendor
    source = source.replace(
        'strscpy(info->charge_ic_vendor_name, "%s",' % vendor,
        'info->chip_rev = val;\n\tstrscpy(info->charge_ic_vendor_name, %s,' % vendor_name)
    source = source.replace('#define BQ2560X_REG_NUM\t\t\t\t0x0c',
                            '#define BQ2560X_REG_NUM\t\t\t\t0x12')
    source = source.replace('for (i = 0; i <= 0x0b; i++)', 'for (i = 0; i <= 0x11; i++)')
    source = replace(source, 'bq2560x_charger_get_termina_vol', '''
\tu8 value;
\tint ret = bq2560x_read(info, 0x0e, &value);
\tif (ret < 0) return ret;
\t*vol = (value >> 1) * 8 + 3856;
\treturn 0;''')
    source = replace(source, 'bq2560x_charger_set_termina_vol', '''
\t/* M8 stock ko: REG0E[7:1], 3856 mV + code * 8 mV.
\t * The factory battery DT specifies 4250 mV. Round down and
\t * retain REG0E[0]; never reuse the REG04-only voltage setter.
\t */
\tu8 code = (clamp_val(vol, 3856, 4250) - 3856) / 8;
\treturn bq2560x_update_bits(info, 0x0e, 0xfe, code << 1);'''.replace('M8', board).replace('4250', str(max_voltage_mv)))
    # REG0B=0x11 is the same charger family at DEV_REV=1. Its stock driver
    # uses the standard 60 mA/LSB map; the reference 0x12 unit uses the A6
    # piecewise map. Keep the shared 3047 mA ceiling: charger-manager owns
    # the battery and input limits.
    source = replace(source, 'bq2560x_charger_set_current', '''
\tu32 ma = min(cur / 1000, 3047U);
\tu8 code;
\tif (info->chip_rev == 0x11)
\t\tcode = min(ma / 60, 63U);   /* Stock 0x11: 60 mA/LSB. */
\telse
\t\tcode = ma <= 1170 ? ma / 90 : (ma - 805) / 57 + 14;
\treturn bq2560x_update_bits(info, BQ2560X_REG_2,
\t\tBQ2560X_REG_ICHG_MASK, code);''')
    source = replace(source, 'bq2560x_charger_get_current', '''
\tu8 value;
\tint ret = bq2560x_read(info, BQ2560X_REG_2, &value);
\tif (ret < 0) return ret;
\tvalue &= BQ2560X_REG_ICHG_MASK;
\tif (info->chip_rev == 0x11)
\t\t*cur = value * 60 * 1000;
\telse
\t\t*cur = (value <= 13 ? value * 90 :
\t\t\t(value - 14) * 115 / 2 + 805) * 1000;
\treturn 0;''')
    path.write_text(source)
    for name, marker, addition in (
        ('drivers/power/supply/Kconfig', 'config CHARGER_BQ2560X_SPRD',
         'config CHARGER_BQ2560X_SPRD\n\ttristate "Unisoc BQ2560x charger (M8 factory encoding)"\n\tdepends on I2C && CHARGER_MANAGER && GPIOLIB\n'),
        ('drivers/power/supply/Makefile', 'bq2560x-charger.o',
         'obj-$(CONFIG_CHARGER_BQ2560X_SPRD) += bq2560x-charger.o\n'),
    ):
        path = kernel / name
        text = path.read_text()
        if marker not in text:
            path.write_text(text + '\n' + addition)
