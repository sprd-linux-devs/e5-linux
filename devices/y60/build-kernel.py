#!/usr/bin/env python3
"""Build the experimental Y60 Image and complete matching module cohort."""
from pathlib import Path
import runpy

if __name__=='__main__':
    here=Path(__file__).resolve().parent
    runpy.run_path(str(here.parent/'yuanhang41s/build-kernel.py'))['main'](profile='y60',here=here)
