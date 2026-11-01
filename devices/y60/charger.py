"""Install the Y60 ETA6937 driver without changing any board DT or battery table."""
from pathlib import Path

HERE = Path(__file__).resolve().parent


def apply(kernel):
    kernel = Path(kernel)
    dest = kernel / 'drivers/power/supply'
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
