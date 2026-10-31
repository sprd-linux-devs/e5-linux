#!/usr/bin/env python3
"""Preserve deferred-provider errors in stock FGU and charger probe paths."""
from pathlib import Path

HERE = Path(__file__).resolve().parent
INCLUDE = '#include "power-probe.h"\n'


def edit(source, old, new):
    if new in source:
        return source
    if source.count(old) != 1:
        raise ValueError('Unsupported power probe source: ' + old[:95])
    return source.replace(old, new, 1)


def gauge_core(source):
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
    source = edit(source, '''\tinfo->regmap = dev_get_regmap(dev->parent, NULL);
\tif (!info->regmap) {
\t\tdev_err(dev, "%s: %d failed to get regmap\\n", __func__, __LINE__);
\t\treturn ERR_PTR(-ENODEV);
\t}''', '''\tinfo->regmap = sprd_power_regmap(dev, dev->parent);
\tif (IS_ERR(info->regmap))
\t\treturn ERR_CAST(info->regmap);''')
    return source if INCLUDE in source else INCLUDE + source


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
