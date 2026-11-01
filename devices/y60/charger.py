"""Install Y60 ETA6937 and its requested, stock-profile-scoped DCP policy."""
from pathlib import Path

HERE = Path(__file__).resolve().parent


def dcp_charge_policy(source):
    include = '#include "y60-charge-profile.h"'
    if include not in source:
        anchor = 'int sprd_battery_get_battery_info('
        if source.count(anchor) != 1:
            raise ValueError('Unexpected Y60 battery-info loader')
        source = source.replace(anchor, include + '\n\n' + anchor, 1)
    if 'y60_dcp_profile(info)' not in source:
        anchor = '\tsprd_battery_parse_step_chg_table(info, battery_np, psy);'
        if source.count(anchor) != 1:
            raise ValueError('Unexpected Y60 parsed battery profile')
        source = source.replace(anchor, anchor +
            '\n\tif (y60_dcp_profile(info))\n'
            '\t\tdev_info(&psy->dev, "Y60 DCP: 2.5 A requested input/normal-temperature charge; ETA hardware steps and thermal limits retained\\n");', 1)
    return source


def apply(kernel):
    kernel = Path(kernel)
    dest = kernel / 'drivers/power/supply'
    battery = dest / 'sprd_battery_info.c'
    updated = dcp_charge_policy(battery.read_text(encoding='utf-8'))
    battery.write_text(updated, encoding='utf-8')
    (dest / 'y60-charge-profile.h').write_bytes((HERE / 'charge-profile.h').read_bytes())
    (dest / 'eta6937-charger.c').write_bytes((HERE / 'eta6937-charger.c').read_bytes())
    (dest / 'power-probe.h').write_bytes((HERE.parent / 'common/power-probe.h').read_bytes())
    for name, marker, addition in (
        ('Kconfig', 'config CHARGER_ETA6937_Y60', '''
config CHARGER_ETA6937_Y60
\ttristate "Y60 Unisoc ETA6937 charger"
\tdepends on I2C && CHARGER_MANAGER && GPIOLIB && OF && REGULATOR && EXTCON
'''),
        ('Makefile', 'CONFIG_CHARGER_ETA6937_Y60',
         '\nobj-$(CONFIG_CHARGER_ETA6937_Y60) += eta6937-charger.o\n'),
    ):
        target = dest / name
        text = target.read_text(encoding='utf-8')
        if marker not in text:
            target.write_text(text + addition, encoding='utf-8')
