#!/usr/bin/env python3
"""Do not lose completed SC2355 SDIO buffers when deferred-work allocation fails."""
from pathlib import Path

MARKER = 'Reclaim completed SDIO buffers even when work allocation fails.'


def apply(kernel):
    path = Path(kernel) / 'drivers/unisoc_platform/sprd_wlan_combo/sc2355/sdio.c'
    text = path.read_text(encoding='utf-8')
    start = text.index('int sc2355_add_topop_list(')
    end = text.index('\n}', start) + 2
    body = text[start:end]
    old = '''\tif (!misc_work) {
\t\twl_err("%s out of memory\\n", __func__);
\t\treturn -1;
\t}'''
    new = '''\tif (!misc_work) {
\t\t/* Reclaim completed SDIO buffers even when work allocation fails.
\t\t * The bus has already finished with this list. Returning an error
\t\t * here loses its only completion, eventually exhausting the pool.
\t\t * This reclaim path uses spinlocks and frees, not firmware commands.
\t\t */
\t\tsc2355_handle_pop_list(&pop_work);
\t\treturn 0;
\t}'''
    if MARKER in body:
        if new not in body or old in body:
            raise ValueError('Unexpected partial SC2355 SDIO completion fix')
        return
    if body.count(old) != 1 or 'pop_work.head = (void *)head;' not in body:
        raise ValueError('Unexpected SC2355 SDIO completion source')
    body = body.replace(old, new, 1)
    path.write_text(text[:start] + body + text[end:], encoding='utf-8')


if __name__ == '__main__':
    import sys
    apply(sys.argv[1])
