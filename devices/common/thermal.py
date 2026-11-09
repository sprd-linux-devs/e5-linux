#!/usr/bin/env python3
"""PR #190: valid hot sensors must survive another sensor's read failure."""
import argparse
from pathlib import Path


def adapt(text):
    marker = 'PR #190: retain valid thermal readings'
    if marker in text:
        return text
    # M8 installs its own replacement driver, which implements the same rule.
    if 'No valid sensor: do not fabricate a cold temperature.' in text:
        return text
    start = text.index('static int virtual_thm_get_temp(')
    end = text.index('\nstatic void virtual_thm_unregister', start)
    original = text[start:end]
    body = original
    replacements = {
        '\t\tif (!tz || IS_ERR(tz))\n\t\t\treturn -EINVAL;':
        '\t\tif (!tz || IS_ERR(tz))\n\t\t\tcontinue;',
        '\t\t\tdev_err(dev, "fail to get temp\\n");\n\t\t\treturn ret;':
        '\t\t\tdev_err_ratelimited(dev, "fail to get temp\\n");\n\t\t\tcontinue;',
        '\t*temp = max_temp;':
        '\t/* ' + marker + '. */\n\tif (max_temp == INT_MIN)\n\t\treturn -EIO;\n\t*temp = max_temp;',
        '\treturn ret;': '\treturn 0;',
    }
    for old, new in replacements.items():
        if old not in body:
            raise ValueError('Unexpected stock virtual thermal callback: ' + old)
        body = body.replace(old, new)
    return text[:start] + body + text[end:]


def apply(kernel):
    kernel = Path(kernel)
    path = kernel / 'drivers/unisoc_platform/thermal/sprd_soc_thm.c'
    old = path.read_text()
    new = adapt(old)
    shell = kernel / 'drivers/thermal/sprd_shell_thm.c'
    shell_old = shell.read_text()
    shell_new = quiet_shell_reads(shell_old)
    if new != old:
        path.write_text(new)
    if shell_new != shell_old:
        shell.write_text(shell_new)


def quiet_shell_reads(text):
    """Quiet only WCN read errors; preserve fallback and high-temp warnings."""
    marker = 'WCN read errors are debug-only; retain abnormal temperature warnings.'
    if marker in text:
        return text
    call = 'pr_err("get thermal %s temp failed\\n", thermal_zone_device_type(tz));'
    include = '#include <linux/kernel.h>'
    if text.count(call) != 1 or text.count(include) != 1:
        raise ValueError('Unexpected stock shell thermal read-error logging')
    replacement = (
        '/* ' + marker + ' */\n'
        '\t\t\tif (ret && !strcmp(thermal_zone_device_type(tz), "wcn-thmzone"))\n'
        '\t\t\t\tpr_debug("get thermal %s temp failed\\n", thermal_zone_device_type(tz));\n'
        '\t\t\telse\n'
        '\t\t\t\tpr_err_ratelimited("get thermal %s temp failed\\n", thermal_zone_device_type(tz));'
    )
    text = text.replace(call, replacement)
    if '#include <linux/string.h>' not in text:
        text = text.replace(include, include+'\n#include <linux/string.h>')
    return text


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kernel', type=Path)
    apply(parser.parse_args().kernel)
