#!/usr/bin/env python3
"""Apply the pinned T551M board adaptations to linux-lts-e5."""
import argparse
import hashlib
from pathlib import Path
import re
import runpy
import subprocess
import shutil
import urllib.request

VENDOR_COMMIT = '63b8011056a5060e274fc1dcc9051c94d9a7bab8'
CHARGER_SHA256 = 'e7a99ea539a66a5dfcf2b25f8a275c8eb0567a675ed029fdb0b087133822dd51'
KERNEL_COMMIT = '020b970e351e'


def replace_function(source, name, body):
    match = re.search(r'\b' + name + r'\([^;{}]*\)\s*\{', source)
    if not match:
        raise ValueError('Missing function: ' + name)
    start = source.index('{', match.start())
    depth = 1
    end = start + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[:start] + '{\n' + body + '\n}' + source[end:]


def board_charger(source):
    # Shared A6 port, also used as the base by M8/K1/41S adapters.
    # T551M batch selection is applied separately after this shared port.
    source = source.replace('.name\t\t\t= "charger",', '.name\t\t\t= "bq2560x_charger",')
    source = source.replace('#define BQ2560X_REG_NUM\t\t\t\t0x10', '#define BQ2560X_REG_NUM\t\t\t\t0x0c')
    source = source.replace('val->intval = info->chip_type;',
                            '{ u8 status; ret = bq2560x_read(info, BQ2560X_REG_8, &status);\n\t\t\tif (!ret) val->intval = !!(status & BIT(2)); }')
    bodies = {
        'bq2560x_charger_set_vindpm': '''
\tu8 code = (clamp_val(vol, 3900, 5400) - 3900) / 100;
\treturn bq2560x_update_bits(info, BQ2560X_REG_6,
\t\tBQ2560X_REG_VINDPM_VOLTAGE_MASK, code);''',
        'bq2560x_charger_get_termina_vol': '''
\tu8 value;
\tint ret = bq2560x_read(info, BQ2560X_REG_4, &value);
\tif (ret < 0) return ret;
\t*vol = ((value >> 3) & 0x1f) * 32 + 3856;
\treturn 0;''',
        'bq2560x_charger_set_termina_vol': '''
\t/* The factory battery/JEITA tables request up to 4.4 V. */
\tu8 code = (clamp_val(vol, 3856, 4400) - 3856) / 32;
\treturn bq2560x_update_bits(info, BQ2560X_REG_4,
\t\tBQ2560X_REG_TERMINAL_VOLTAGE_MASK, code << 3);''',
        'bq2560x_charger_set_current': '''
\t/* Factory REG0B=0x12 path: <=1170 mA uses 90 mA steps;
\t * the upper range uses the stock (mA - 805) / 57 + 14 mapping.
\t * 3047 mA is the original setter's ceiling (code 53).
\t */
\tu32 ma = min(cur / 1000, 3047U);
\tu8 code = ma <= 1170 ? ma / 90 : (ma - 805) / 57 + 14;
\treturn bq2560x_update_bits(info, BQ2560X_REG_2,
\t\tBQ2560X_REG_ICHG_MASK, code);''',
        'bq2560x_charger_get_current': '''
\tu8 value;
\tint ret = bq2560x_read(info, BQ2560X_REG_2, &value);
\tif (ret < 0) return ret;
\tvalue &= BQ2560X_REG_ICHG_MASK;
\t/* Preserve the factory getter's integer-mA rounding at 57.5 mA/step. */
\t*cur = (value <= 13 ? value * 90 : (value - 14) * 115 / 2 + 805) * 1000;
\treturn 0;''',
        'bq2560x_charger_register_vbus_regulator': '''
\tstatic struct regulator_consumer_supply supply = {
\t\t.supply = "vddvbus",
\t};
\tstruct regulator_init_data *init;
\tstruct regulator_config cfg = {
\t\t.dev = info->dev,
\t\t.of_node = info->dev->of_node,
\t\t.driver_data = info,
\t};
\tstruct regulator_dev *reg;
\t/* Mirror the user's working A-slot OTG supply lookup in memory.
\t * A DT phandle takes precedence; B-slot otherwise lacks this mapping.
\t */
\tinit = devm_kzalloc(info->dev, sizeof(*init), GFP_KERNEL);
\tif (!init)
\t\treturn -ENOMEM;
\tinit->constraints.valid_ops_mask = REGULATOR_CHANGE_STATUS;
\tinit->constraints.min_uV = 5000000;
\tinit->constraints.max_uV = 5000000;
\tinit->num_consumer_supplies = 1;
\tinit->consumer_supplies = &supply;
\tcfg.init_data = init;
\treg = devm_regulator_register(info->dev, &bq2560x_charger_vbus_desc, &cfg);
\treturn PTR_ERR_OR_ZERO(reg);''',
    }
    for name, body in bodies.items():
        source = replace_function(source, name, body)
    start = source.index('\tret = bq2560x_read(info,BQ2560X_REG_B, &val);')
    end = source.index('\n\ti2c_set_clientdata(client, info);', start)
    source = source[:start] + '''
\tret = bq2560x_read(info, BQ2560X_REG_B, &val);
\tif (ret < 0) return ret;
\tif (val != 0x12 || client->addr != 0x6b) {
\t\tdev_err(dev, "unsupported T551M charger ID %#x at %#x\\n", val, client->addr);
\t\treturn -ENODEV;
\t}
\tstrscpy(info->charge_ic_vendor_name, "T551M-0x12",
\t\tsizeof(info->charge_ic_vendor_name));
''' + source[end:]
    # Remove SGM-specific register 0x0f helpers (the T551M register map ends at B).
    source = replace_function(source, 'bq2560x_charger_set_vindpmos', '\treturn -EOPNOTSUPP;')
    # REG00[4:0] is 100 mA + code * 100 mA: 3.2 A is the register range,
    # not a bring-up cap. Keep SDP/DCP and temperature policy in charger-manager.
    # Clamp the lower end as well so requests below 100 mA cannot underflow.
    source = source.replace(
        '\tif (limit_cur >= BQ2560X_LIMIT_CURRENT_MAX)\n\t\tlimit_cur = BQ2560X_LIMIT_CURRENT_MAX;',
        '\tlimit_cur = clamp_val(limit_cur, BQ2560X_LIMIT_CURRENT_OFFSET, BQ2560X_LIMIT_CURRENT_MAX);')
    # Retain the stock safety-timer, recharge and boost-current configuration.
    start = source.index('\n\tret = bq2560x_update_bits(info, BQ2560X_REG_A,')
    end = source.index('\n\tinfo->current_charge_limit_cur', start)
    source = source[:start] + source[end:]
    source = source.replace('for (i = 0; i < 0x10; i++)', 'for (i = 0; i <= 0x0b; i++)')
    return source


def board_charger_variants(source):
    """T551M-only A5/A6 codecs; never broaden another board's silicon gate."""
    source = source.replace('struct bq2560x_charger_info {',
                            '#include "t551m-charger-variants.h"\n\n'
                            'struct bq2560x_charger_info {\n\tu8 stock_id;', 1)
    source = replace_function(source, 'bq2560x_charger_set_current', '''
\tu8 code = t551m_charge_code(info->stock_id, cur / 1000);
\treturn bq2560x_update_bits(info, BQ2560X_REG_2,
\t\tBQ2560X_REG_ICHG_MASK, code);''')
    source = replace_function(source, 'bq2560x_charger_get_current', '''
\tu8 value;
\tint ret = bq2560x_read(info, BQ2560X_REG_2, &value);
\tif (ret < 0) return ret;
\tvalue &= BQ2560X_REG_ICHG_MASK;
\t/* Preserve the matching stock revision's integer-mA rounding. */
\t*cur = t551m_charge_ma(info->stock_id, value) * 1000;
\treturn 0;''')
    old = '\tif (val != 0x12 || client->addr != 0x6b) {'
    name = ('\tstrscpy(info->charge_ic_vendor_name, "T551M-0x12",\n'
            '\t\tsizeof(info->charge_ic_vendor_name));')
    if source.count(old) != 1 or source.count(name) != 1:
        raise ValueError('T551M stock charger identification anchor changed')
    source = source.replace(old, '\tif (!t551m_charger_supported(client->addr, val)) {')
    return source.replace(name, '''\tinfo->stock_id = val;
\tsnprintf(info->charge_ic_vendor_name, sizeof(info->charge_ic_vendor_name),
\t\t "T551M-0x%02x", val);
\tdev_info(dev, "T551M charger REG0B=%#x at %#x\\n", val, client->addr);''')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('kernel', type=Path)
    ap.add_argument('--preserve-board-current', action='store_true',
                    help='Reuse the driver port without T551M DCP table changes')
    ap.add_argument('--base-charger-port', action='store_true',
                    help='A recipient model supplies its own silicon/current adaptation')
    ap.add_argument('--host-sink', action='store_true',
                    help='Enable tested MUSB external-power host policy for this profile')
    args = ap.parse_args()
    k = args.kernel
    head = subprocess.check_output(['git', '-C', str(k), 'rev-parse', 'HEAD']).decode().strip()
    if not head.startswith(KERNEL_COMMIT):
        raise SystemExit('Expected linux-lts-e5 commit ' + KERNEL_COMMIT)
    runpy.run_path(str(Path(__file__).resolve().parents[1] / 'common/display.py'))['apply'](k)
    runpy.run_path(str(Path(__file__).resolve().parents[1] / 'common/usb-ncm.py'))['apply'](k)
    runpy.run_path(str(Path(__file__).resolve().parents[1] / 'common/boot-optimization.py'))['apply'](k)
    runpy.run_path(str(Path(__file__).resolve().parents[1] / 'common/power.py'))['apply'](k)
    runpy.run_path(str(Path(__file__).resolve().parents[1] / 'common/wcn-firmware.py'))['apply'](k)
    runpy.run_path(str(Path(__file__).resolve().parents[1] / 'common/charger-capabilities.py'))['apply'](k)
    runpy.run_path(str(Path(__file__).resolve().parents[1] / 'common/emmc.py'))['apply'](k)
    runpy.run_path(str(Path(__file__).resolve().parents[1] / 'common/sd-power.py'))['apply'](k)
    runpy.run_path(str(Path(__file__).resolve().parents[1] / 'common/eic.py'))['apply'](k)
    runpy.run_path(str(Path(__file__).resolve().parents[1] / 'common/thermal.py'))['apply'](k)
    runpy.run_path(str(Path(__file__).resolve().parents[1] / 'common/sipa.py'))['apply'](k)
    runpy.run_path(str(Path(__file__).resolve().parents[1] / 'common/fuel-gauge.py'))['apply'](k)
    runpy.run_path(str(Path(__file__).resolve().parents[1] / 'common/wifi-sae.py'))['apply'](k)
    runpy.run_path(str(Path(__file__).resolve().parents[1] / 'common/wifi-stations.py'))['apply'](k)
    url = ('https://raw.githubusercontent.com/Enceka/kernel_sprd_ums9158/'
           + VENDOR_COMMIT + '/drivers/power/supply/bq2560x-charger.c')
    source = urllib.request.urlopen(url, timeout=60).read()
    if hashlib.sha256(source).hexdigest() != CHARGER_SHA256:
        raise SystemExit('Charger source checksum mismatch')
    text = source.decode().replace('GPL-2.0:', 'GPL-2.0-only')
    text = text.replace('#include <linux/gpio/consumer.h>',
                        '#include <linux/gpio/consumer.h>\n#include <linux/gpio.h>\n#include <linux/extcon.h>')
    text = text.replace('static int bq2560x_charger_probe(struct i2c_client *client,\n\t\tconst struct i2c_device_id *id)',
                        'static int bq2560x_charger_probe(struct i2c_client *client)')
    text = text.replace('static int bq2560x_charger_remove(struct i2c_client *client)',
                        'static void bq2560x_charger_remove(struct i2c_client *client)')
    text = text.replace('\tmutex_destroy(&info->lock);\n\n\treturn 0;\n}',
                        '\tmutex_destroy(&info->lock);\n}')
    text = text.replace('charger_cfg.of_node = dev->of_node;',
                        'charger_cfg.fwnode = dev_fwnode(dev);')
    text = text.replace('GPIOF_DIR_IN', 'GPIOF_IN')
    text = board_charger(text)
    if not args.base_charger_port:
        text = board_charger_variants(text)
    (k / 'drivers/power/supply/bq2560x-charger.c').write_text(text)
    if not args.base_charger_port:
        (k / 'drivers/power/supply/t551m-charger-variants.h').write_bytes(
            Path(__file__).with_name('charger-variants.h').read_bytes())
    additions = {
        'drivers/power/supply/Kconfig': '\nconfig CHARGER_BQ2560X_SPRD\n\ttristate "Unisoc BQ2560x charger (T551M)"\n\tdepends on I2C && CHARGER_MANAGER && GPIOLIB\n',
        'drivers/power/supply/Makefile': '\nobj-$(CONFIG_CHARGER_BQ2560X_SPRD) += bq2560x-charger.o\n',
    }
    for name, addition in additions.items():
        path = k / name
        text = path.read_text()
        if 'CHARGER_BQ2560X_SPRD' not in text:
            path.write_text(text + addition)
    # E5's compiled-in touch firmware is board-specific. Never burn it into a
    # T551M controller on probe; use the factory firmware already on the IC.
    path = k / 'drivers/input/touchscreen/tlsc6x/tlsc6x_main.c'
    text = path.read_text().replace('\ttlsc6x_do_update_ifneed();',
                                   '\t/* T551M: preserve factory touch firmware. */')
    path.write_text(text)
    path = k / 'sound/soc/sprd/unisoc/machine/sprd-asoc-card-utils-hook.c'
    text = path.read_text()
    text = re.sub(r'ret = (aw87xxx_set_profile\([^;]*);',
                  r'ret = IS_REACHABLE(CONFIG_SND_SOC_UNISOC_PA_AW87XXX) ? \1 : 0;', text)
    path.write_text(text)
    # Android DT requests the vendor PD extcon, which is not built in this port.
    # Fall back to the already-working USB PHY BC1.2 notifications.
    path = k / 'drivers/power/supply/sprd_vchg_detect.c'
    text = path.read_text()
    marker = '\tinfo->use_typec_extcon = device_property_read_bool(info->dev, "use-typec-extcon");'
    if 'T551M BC1.2 fallback' not in text:
        text = text.replace(marker, marker + '\n\t/* T551M BC1.2 fallback without the vendor PD stack. */\n\tif (!IS_ENABLED(CONFIG_SC27XX_PD))\n\t\tinfo->use_typec_extcon = false;')
    path.write_text(text)
    runpy.run_path(str(Path(__file__).with_name('usb_charger.py')))['apply'](
        k, replace_function, restore_board_current=not args.preserve_board_current)
    runpy.run_path(str(Path(__file__).with_name('otg.py')))['apply'](k)
    if args.host_sink:
        runpy.run_path(str(Path(__file__).resolve().parents[1] / 'common/musb-host-sink.py'))['apply'](k, charger='bq2560x')
    runpy.run_path(str(Path(__file__).with_name('cpufreq.py')))['apply'](k)
    runpy.run_path(str(Path(__file__).with_name('wifi.py')))['apply'](k)
    # mu300-linux f0323bf: keep firmware debug traffic off across WCN power
    # cycles. This board uses the integrated WCN stack, not MU300's PCIe path;
    # its resume does not force armlog on, so only the shared default applies.
    path = k / 'drivers/unisoc_platform/sprdwcn/platform/sysfs.c'
    text = path.read_text()
    if 'Default firmware debug log off' not in text:
        old = '\t\tsysfs_info.armlog_status = 1;\n#endif'
        if text.count(old) != 1:
            raise SystemExit('Unexpected WCN firmware log default')
        text = text.replace(old, old + '\n\t/* Default firmware debug log off; sysfs may enable it explicitly. */\n\tsysfs_info.armlog_status = 0;')
        path.write_text(text)
    # The factory DT uses "qogirn6l" and a GPIO pulse backlight, not PWM.
    disp = k / 'drivers/unisoc_platform/sprd_disp'
    shutil.copy2(Path(__file__).with_name('t551m-backlight.h'), disp / 't551m-backlight.h')
    path = disp / 'sprd_bl.h'
    text = path.read_text()
    if 'step_gpio' not in text:
        text = text.replace('struct sprd_backlight {', 'struct sprd_backlight {\n\tstruct gpio_desc *step_gpio;\n\tint step_level;')
    path.write_text(text)
    path = disp / 'sprd_bl.c'
    text = path.read_text()
    if '#include "t551m-backlight.h"' not in text:
        text = text.replace('int sprd_cabc_backlight_update', '#include "t551m-backlight.h"\n\nint sprd_cabc_backlight_update', 1)
        text = text.replace('\tmutex_lock(&bd->update_lock);', '\tif (bl->step_gpio)\n\t\treturn 0;\n\n\tmutex_lock(&bd->update_lock);', 1)
        text = text.replace('\tsprd_backlight_normalize_map(bd, &level);', '\tif (bl->step_gpio)\n\t\treturn t551m_backlight_update(bd);\n\n\tsprd_backlight_normalize_map(bd, &level);', 1)
        start = text.index('\tbl->pwm = devm_pwm_get')
        end = text.index('\tbd = devm_backlight_device_register', start)
        pwm = text[start:end]
        text = text[:start] + '''
\tif (of_device_is_compatible(pdev->dev.of_node, "sprd,qogirn6l-backlight")) {
\t\tbl->step_gpio = devm_gpiod_get(&pdev->dev, "lcm_backlight", GPIOD_OUT_LOW);
\t\tif (IS_ERR(bl->step_gpio)) return PTR_ERR(bl->step_gpio);
\t\tif (gpiod_cansleep(bl->step_gpio)) return -EINVAL;
\t\tbl->step_level = -1;
\t} else {
''' + pwm + '\t}\n' + text[end:]
        text = text.replace('\t{ .compatible = "sprd,sharkl3-backlight" },', '\t{ .compatible = "sprd,qogirn6l-backlight" },\n\t{ .compatible = "sprd,sharkl3-backlight" },', 1)
    path.write_text(text)
    runpy.run_path(str(Path(__file__).resolve().parents[1] / 'common/power-probe.py'))['apply'](k)


if __name__ == '__main__':
    main()
