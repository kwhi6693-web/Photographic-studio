#!/usr/bin/env python3
"""Photographic Studio v1.0.3 - start-up self check. Usage: python3 -I selfcheck.py
Reports which tools of this package can run here and the suggested capability tier (see references/capability_tiers.md).
It cannot see whether the host has an image-editing tool: the agent answers that part itself."""
import importlib, json, sys
mods = {m: None for m in ('numpy', 'PIL', 'cv2')}   # v1.0.3: only what the tools import (scikit-image, scipy: not needed)
for m in mods:
    try:
        mods[m] = getattr(importlib.import_module(m), '__version__', 'ok')
    except Exception:
        mods[m] = None
base = bool(mods['numpy'] and mods['PIL'])
full = bool(base and mods['cv2'])
r = {'python': sys.version.split()[0], 'modules': mods,
     'tools': {'measure.py': base, 'grade.py': base, 'n_trim.py': full, 'reframe.py': bool(base and mods['cv2']),
               'check_g_output.py': full, 'text_restore.py': full, 'texture_blend.py': bool(base and mods['cv2']), 'intensity_check.py': base, 'physics_check.py': base, 'finish.py': bool(base and mods['cv2']), 'look_transfer.py': bool(base and mods['cv2'])},
     'suggested_tier_if_host_has_image_editing': 'T1' if full else ('T1-degraded (no automatic scene check, no restore)' if base else 'T3'),
     'suggested_tier_if_host_has_no_image_editing': 'T2' if base else 'T4',
     'install_hint': None if full else 'pip install opencv-python-headless numpy pillow (only if the host allows it)'}
print(json.dumps(r, ensure_ascii=False, indent=1))
