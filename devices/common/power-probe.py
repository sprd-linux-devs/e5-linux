#!/usr/bin/env python3
"""Preserve deferred-provider errors in stock FGU and charger probe paths."""
from pathlib import Path

HERE = Path(__file__).resolve().parent
INCLUDE = '#include "power-probe.h"\n'


def edit(source, old, new, count=1):
    if source.count(new) == count:
        return source
    if source.count(old) != count:
        raise ValueError('Unsupported power probe source: ' + old[:95])
    return source.replace(old, new, count)


def gauge_core(source):
    source = edit(source, '''\tif (IS_ERR(data->fgu_info)) {
\t\tdev_err(data->dev, "failed to get fgu_info!!!\\n");
\t\treturn -EPROBE_DEFER;
\t}''', '''\tif (IS_ERR(data->fgu_info))
\t\treturn dev_err_probe(data->dev, PTR_ERR(data->fgu_info),
\t\t\t\t     "failed to get FGU hardware description\\n");''', count=2)
    source = edit(source, '''\tif (unlikely(!psy->initialized && atomic_read(&psy->use_cnt) > 0)) {
\t\tdev_err(data->dev, "%s psy is not ready\\n", __func__);
\t\treturn -ENODEV;
\t}''', '''\tif (unlikely(!psy->initialized && atomic_read(&psy->use_cnt) > 0)) {
\t\t/* Published supply, but power_supply registration is not complete. */
\t\treturn -EAGAIN;
\t}''', count=2)
    source = edit(source, '''\tdata->regmap = dev_get_regmap(dev->parent, NULL);
\tif (!data->regmap) {
\t\tdev_err(dev, "failed to get regmap\\n");
\t\treturn -ENODEV;
\t}''', '''\tdata->regmap = sprd_power_regmap(dev, dev->parent);
\tif (IS_ERR(data->regmap))
\t\treturn PTR_ERR(data->regmap);''')
    source = edit(source, '''\t\tif (IS_ERR(data->usb_phy)) {
\t\t\tdev_err(dev, "failed to find USB phy, ret = %ld\\n",
\t\t\t\tPTR_ERR(data->usb_phy));
\t\t\treturn -EPROBE_DEFER;
\t\t}''', '''\t\tif (IS_ERR(data->usb_phy))
\t\t\treturn dev_err_probe(dev, PTR_ERR(data->usb_phy),
\t\t\t\t\t     "failed to find USB phy\\n");''')
    source = edit(source, '''\tif (IS_ERR(data->gpiod)) {
\t\tdev_err(dev, "failed to get battery detection GPIO\\n");
\t\treturn -ENXIO;
\t}''', '''\tif (IS_ERR(data->gpiod))
\t\treturn dev_err_probe(dev, PTR_ERR(data->gpiod),
\t\t\t\t     "failed to get battery detection GPIO\\n");''')
    source = edit(source, '''\tif (IS_ERR(data->battery)) {
\t\tdev_err(dev, "failed to register power supply");
\t\tret = -ENXIO;
\t\tgoto err;
\t}''', '''\tif (IS_ERR(data->battery)) {
\t\tret = dev_err_probe(dev, PTR_ERR(data->battery),
\t\t\t\t    "failed to register FGU power supply\\n");
\t\tgoto err;
\t}''')
    return source if INCLUDE in source else INCLUDE + source


def gauge_hardware(source):
    source = edit(source, '''\t{ .compatible = "sprd,ump9620-fgu", .data = &ump96xx_fgu_info}
};''', '''\t{ .compatible = "sprd,ump9620-fgu", .data = &ump96xx_fgu_info},
\t{ }
};''')
    source = edit(source, '''\tint ret = 0, i;
\tconst char *value = {0};
\tstruct device_node *np = dev->of_node;''', '''\tint ret = 0;
\tconst struct of_device_id *match;''')
    source = edit(source, '''\tret = of_property_read_string_index(np, "compatible", 0, &value);
\tif (ret) {
\t\tdev_err(dev, "read_string failed!\\n");
\t\treturn ERR_PTR(ret);
\t}

\tfor (i = 0; i < ARRAY_SIZE(ump96xx_fgu_dev_match_arr); i++) {
\t\tif (strcmp(ump96xx_fgu_dev_match_arr[i].compatible, value) == 0) {
\t\t\tinfo->pdata = ump96xx_fgu_dev_match_arr[i].data;
\t\t\tbreak;
\t\t} else if (i == ARRAY_SIZE(ump96xx_fgu_dev_match_arr) - 1) {
\t\t\tdev_err(dev, "failed match ump96xx dev table!\\n");
\t\t\treturn ERR_PTR(-ENODATA);
\t\t}
\t}''', '''\t/* Honor the full DT compatible list, including a known fallback. */
\tmatch = of_match_node(ump96xx_fgu_dev_match_arr, dev->of_node);
\tif (!match)
\t\treturn ERR_PTR(dev_err_probe(dev, -ENODATA,
\t\t\t\t\t    "unsupported FGU compatible list\\n"));
\tinfo->pdata = match->data;''')
    source = edit(source, '''\tinfo->regmap = dev_get_regmap(dev->parent, NULL);
\tif (!info->regmap) {
\t\tdev_err(dev, "%s: %d failed to get regmap\\n", __func__, __LINE__);
\t\treturn ERR_PTR(-ENODEV);
\t}''', '''\tinfo->regmap = sprd_power_regmap(dev, dev->parent);
\tif (IS_ERR(info->regmap))
\t\treturn ERR_CAST(info->regmap);''')
    return source if INCLUDE in source else INCLUDE + source


def manager(source):
    # A named supply can be found while its own registration is still running.
    # Retry only that explicit transient status; keep real I/O/config errors.
    for call, message in (
        ('get_boot_cap(cm, &cm->desc->cap)', 'Failed to get initial battery capacity'),
        ('cm_get_battery_temperature(cm, &cm->desc->temperature)', 'failed to get battery temperature'),
    ):
        source = edit(source, f'''\tret = {call};
\tif (ret) {{
\t\tdev_err({'&pdev->dev' if call.startswith('get_boot') else 'cm->dev'}, "{message}\\n");
\t\treturn ret;
\t}}''', f'''\tret = {call};
\tif (ret) {{
\t\tpower_supply_put(fuel_gauge);
\t\treturn dev_err_probe(cm->dev,
\t\t\t\t     ret == -EAGAIN ? -EPROBE_DEFER : ret,
\t\t\t\t     "{message}\\n");
\t}}''')
    return source


def charger(source, name):
    # Chip-specific ID/address/encoding branches precede this block and stay
    # byte-for-byte unchanged. The caller owns its device-node reference.
    owner, failure = ('info', '\t\treturn -ENODEV;') if name == 'bq2560x-charger.c' else (
        'bq', '\t\tret =  -ENODEV;\n\t\tgoto error_1;')
    old = '''\tregmap_pdev = of_find_device_by_node(regmap_np);
\tif (!regmap_pdev) {
\t\tof_node_put(regmap_np);
\t\tdev_err(dev, "unable to get syscon device\\n");
FAILURE
\t}

\tof_node_put(regmap_np);
\tOWNER->pmic = dev_get_regmap(regmap_pdev->dev.parent, NULL);
\tif (!OWNER->pmic) {
\t\tdev_err(dev, "unable to get pmic regmap device\\n");
FAILURE
\t}'''.replace('OWNER', owner).replace('FAILURE', failure)
    error = '\t\treturn PTR_ERR(info->pmic);' if owner == 'info' else (
        '\t\tret = PTR_ERR(bq->pmic);\n\t\tgoto error_1;')
    new = '''\tOWNER->pmic = sprd_charger_pmic_regmap(dev, regmap_np);
\tof_node_put(regmap_np);
\tif (IS_ERR(OWNER->pmic)) {
ERROR
\t}'''.replace('OWNER', owner).replace('ERROR', error)
    source = edit(source, old, new)
    source = source.replace('\tstruct platform_device *regmap_pdev;\n', '')
    return source if INCLUDE in source else INCLUDE + source


def apply(kernel):
    directory = Path(kernel) / 'drivers/power/supply'
    changes = {
        'sprd_fuel_gauge_core.c': gauge_core((directory/'sprd_fuel_gauge_core.c').read_text()),
        'sprd_ump96xx_fuel_gauge.c': gauge_hardware((directory/'sprd_ump96xx_fuel_gauge.c').read_text()),
        'charger-manager.c': manager((directory/'charger-manager.c').read_text()),
    }
    for name in ('bq2560x-charger.c', 'aw32257_charger.c'):
        if (directory/name).exists():
            changes[name] = charger((directory/name).read_text(), name)
    # Validate all source shapes before changing any prepared source.
    for name, source in changes.items():
        if (directory/name).read_text() != source:
            (directory/name).write_text(source)
    header = directory/'power-probe.h'
    if not header.exists() or header.read_bytes() != (HERE/'power-probe.h').read_bytes():
        header.write_bytes((HERE/'power-probe.h').read_bytes())


if __name__ == '__main__':
    import sys
    apply(sys.argv[1])
