#!/usr/bin/env python3
"""Y60 hook 0 calls its stock AW87xxx profile API, not the donor GPIO pulse.

CP21.20240108.0S.GCY snd-soc-sprd-card.ko: hook_spk_aw87xxx at 0x2674,
aw87xxx_set_profile(0, on ? "Music" : "Off") at 0x26c0. Keep the original
DT GPIO acquisition/high initial level, matching stock parse_ext_hook.
"""
from pathlib import Path

RELATIVE = 'sound/soc/sprd/unisoc/machine/sprd-asoc-card-utils-hook.c'
MARKER = '/* Y60 stock hook 0: AW87xxx I2C profile; no GPIO mode pulses. */'


def transform(source):
    if MARKER in source:
        return source
    start = source.index('static void hook_gpio_pulse_control(')
    end = source.index('extern int gPA_type;', start)
    declaration = 'extern int aw87xxx_set_profile(int dev_index, char *profile);'
    if source.count(declaration) != 1 or source.count(
            '{"general_speaker", hook_general_spk, EN_LEVEL}') != 1:
        raise ValueError('Unexpected Y60 speaker hook source')
    # Leave the table and the complete DT GPIO request/free lifecycle intact.
    result = source[:start] + declaration + '\n\n' + MARKER + '''
static int hook_general_spk(int id, int on)
{
\tint ret = aw87xxx_set_profile(0, on ? "Music" : "Off");

\tif (ret < 0) {
\t\tpr_err("Y60 speaker profile failed: id=%d on=%d error=%d\\n", id, on, ret);
\t\treturn ret;
\t}
\treturn HOOK_OK;
}

''' + source[end:].replace(declaration + '\n', '', 1)
    return result


def apply(kernel):
    path = Path(kernel) / RELATIVE
    source = path.read_text()
    changed = transform(source)
    if source != changed:
        path.write_text(changed)


if __name__ == '__main__':
    import sys
    apply(sys.argv[1])
