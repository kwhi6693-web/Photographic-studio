#!/usr/bin/env python3
"""Photographic Studio v1.0.3 - start-up self check. Usage: python3 -I selfcheck.py
Reports which tools of this package can run here and the suggested capability tier (see references/capability_tiers.md).
It cannot see whether the host has an image-editing tool: the agent answers that part itself.
v1.4.1 audit: G drift diagnostics use the same backend support as look transfer."""
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
     'tools': {'measure.py': base, 'grade.py': base, 'settle.py': geo, 'full_res.py': geo, 'n_trim.py': geo, 'reframe.py': geo,
               'check_g_output.py': geo, 'text_restore.py': full, 'texture_blend.py': full, 'intensity_check.py': base, 'physics_check.py': base, 'finish.py': geo, 'look_transfer.py': geo, 'keep_regions.py': base, 'improve_check.py': base, 'harmonize.py': base, 'pipeline.py': geo, 'g_drift.py': geo},
     'opencv_stand_in': ('cvlite (numpy + Pillow): G alignment by scale search + phase correlation; text restore and texture blend skipped' if lite else None),
     'suggested_tier_if_host_has_image_editing': 'T1' if full else ('T1-lite (cvlite: no text restore, no texture blend)' if lite else ('T1-degraded (no automatic scene check, no restore)' if base else 'T3')),
     'suggested_tier_if_host_has_no_image_editing': 'T2' if base else 'T4',
     'install_hint': None if (full or lite) else 'pip install opencv-python-headless numpy pillow (only if the host allows it)'}
print(json.dumps(r, ensure_ascii=False, indent=1))
