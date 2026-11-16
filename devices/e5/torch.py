"""Build the stock E5 AW3641 GPIO torch as a standard LED-class module."""
from pathlib import Path

HERE = Path(__file__).resolve().parent


def apply(kernel):
    folder = Path(kernel) / 'drivers/leds'
    (folder / 'e5-aw3641-torch.c').write_bytes(
        (HERE / 'port/torch/e5-aw3641-torch.c').read_bytes())
    path = folder / 'Makefile'
    source = path.read_text()
    rule = 'obj-$(CONFIG_LEDS_E5_AW3641) += e5-aw3641-torch.o'
    if rule not in source:
        source += '\n' + rule + '\n'
    path.write_text(source)
    path = folder / 'Kconfig'
    source = path.read_text()
    if 'config LEDS_E5_AW3641\n' not in source:
        marker = 'endif # NEW_LEDS'
        assert source.count(marker) == 1, 'Unexpected LED Kconfig boundary'
        source = source.replace(marker, '''config LEDS_E5_AW3641
\ttristate "RongYue E5 AW3641 torch"
\tdepends on LEDS_CLASS && OF && GPIOLIB
\thelp
\t  Expose the RongYue E5 stock AW3641 GPIO torch through the LED
\t  class. Starts off and turns off on shutdown or driver removal.
\t  Does not enable camera flash pulses or change other board LEDs.

''' + marker, 1)
    path.write_text(source)
