#!/usr/bin/env python3
"""Shared SIPA backpressure, completion and CP power-reference fixes."""
from pathlib import Path
import subprocess
import tempfile


PATCH = Path(__file__).with_name('sipa-data-path.patch')
PATCHES = (PATCH, Path(__file__).with_name('sipa-tx-retry.patch'),
           Path(__file__).with_name('sipa-completion-events.patch'),
           Path(__file__).with_name('sipa-rm-order.patch'))


def apply(kernel):
    kernel = Path(kernel).resolve()
    paths = sorted({line[6:] for patch in PATCHES for line in patch.read_text().splitlines()
                    if line.startswith('+++ b/')})
    # Check the entire patch before writing any source. A different vendor
    # revision must fail explicitly rather than build a partial adaptation.
    with tempfile.TemporaryDirectory(prefix='e5-sipa-') as directory:
        stage = Path(directory)
        for name in paths:
            target = stage/name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((kernel/name).read_bytes())
        args = ['git', 'apply', '--whitespace=nowarn']
        # Normalize a clean, previously patched or current tree in scratch.
        # Reverse in dependency order, then validate/reapply the whole series.
        # A partial/unknown vendor change must never leak a half-applied update.
        for patch in reversed(PATCHES):
            if subprocess.run(args + ['--reverse', '--check', str(patch)], cwd=stage,
                              capture_output=True).returncode == 0:
                subprocess.run(args + ['--reverse', str(patch)], cwd=stage, check=True)
        for patch in PATCHES:
            result = subprocess.run(args + ['--check', str(patch)], cwd=stage,
                                    capture_output=True, text=True)
            if result.returncode:
                raise ValueError('SIPA source differs from the supported revision: ' + result.stderr.strip())
            subprocess.run(args + [str(patch)], cwd=stage, check=True)
        for name in paths:
            data = (stage/name).read_bytes()
            if data != (kernel/name).read_bytes():
                (kernel/name).write_bytes(data)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kernel', type=Path)
    apply(parser.parse_args().kernel)
