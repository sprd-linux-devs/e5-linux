"""Opt-in SQC full-endpoint policy verified on P720S11 and P720S20."""
from pathlib import Path
import subprocess
import tempfile

PATCH = Path(__file__).with_suffix('.patch')
LEGACY_COMMENT = 'P720S11 hardware termination endpoint (SGM41513, stock SQC STATUS).'
COMMENT = 'Stock SQC hardware termination endpoint (opt-in board policy).'


def restore(kernel):
    path = Path(kernel)/'drivers/power/supply/charger-manager.c'
    source = path.read_text()
    if COMMENT not in source and LEGACY_COMMENT not in source:
        return
    migrated = source.replace(LEGACY_COMMENT, COMMENT).replace(
        'P720S11 hardware full endpoint: vbat=', 'SQC hardware full endpoint: vbat=')
    with tempfile.TemporaryDirectory(prefix='sqc-full-') as tmp:
        stage = Path(tmp)
        target = stage/'drivers/power/supply/charger-manager.c'
        target.parent.mkdir(parents=True)
        target.write_text(migrated)
        args = ['git', 'apply', '--whitespace=nowarn', '--reverse']
        subprocess.run(args+['--check', str(PATCH)], cwd=stage, check=True)
        subprocess.run(args+[str(PATCH)], cwd=stage, check=True)
        path.write_bytes(target.read_bytes())


def apply(kernel):
    args = ['git', 'apply', '--whitespace=nowarn']
    if subprocess.run(args+['--reverse', '--check', str(PATCH)], cwd=kernel,
                      capture_output=True).returncode == 0:
        return
    subprocess.run(args+['--check', str(PATCH)], cwd=kernel, check=True)
    subprocess.run(args+[str(PATCH)], cwd=kernel, check=True)
