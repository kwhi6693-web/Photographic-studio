#!/usr/bin/env python3
"""Photographic Studio v1.6.2 - start-up self check. Usage: python3 selfcheck.py   (no -I: it can hide a user-installed OpenCV)
Reports which tools of this package can run here and the suggested capability tier (see references/capability_tiers.md).
It cannot see whether the host has an image-editing tool: the agent answers that part itself.
v1.6.2: lists only the tools left in the package (the v1.4 route is archived in the repository's legacy/v1.4).
Without OpenCV the main route still runs fully (cvlite): G alignment by scale search + phase correlation."""
from pathlib import Path
import importlib, json, sys
mods = {m: None for m in ('numpy', 'PIL', 'cv2')}   # v1.0.3: only what the tools import (scikit-image, scipy: not needed)
for m in mods:
    try:
        mods[m] = getattr(importlib.import_module(m), '__version__', 'ok')
    except Exception:
        mods[m] = None
base = bool(mods['numpy'] and mods['PIL'])
full = bool(base and mods['cv2'])
lite = bool(base and not mods['cv2'] and (Path(__file__).resolve().parent / 'cvlite.py').exists())   # v1.2.9: numpy + Pillow stand-in for OpenCV
geo = bool(base and (mods['cv2'] or lite))
r = {'python': sys.version.split()[0], 'modules': mods,
     'tools': {'pipeline.py': geo, 'g_first.py': geo, 'quick_n.py': geo, 'grade.py': base, 'reframe.py': geo, 'n_trim.py': geo,
               'check_g_output.py': geo, 'look_transfer.py': geo, 'physics_check.py': base, 'keep_regions.py': base,
               'keep_preview.py': bool(mods['PIL']), 'sentinel.py': base, 'to_jpeg.py': bool(mods['PIL'])},
     'opencv_stand_in': ('cvlite (numpy + Pillow): G alignment by scale search + phase correlation; same results otherwise' if lite else None),
     'suggested_tier_if_host_has_image_editing': 'T1' if (full or lite) else ('T1-degraded (no automatic scene check, no restore)' if base else 'T3'),
     'suggested_tier_if_host_has_no_image_editing': 'T2' if base else 'T4',
     'install_hint': None if (full or lite) else 'pip install opencv-python-headless numpy pillow (only if the host allows it)'}
print(json.dumps(r, ensure_ascii=False, indent=1))
