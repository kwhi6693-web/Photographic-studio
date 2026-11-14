#!/usr/bin/env python3
"""Photographic Studio v2.1.0 - full_res: carry a finished edit from the working size back to the full-resolution original.
Usage: python3 -I full_res.py ORIGINAL_FULL WORK_ORIGINAL WORK_FINAL OUT_IMAGE [--quality=95]
  ORIGINAL_FULL  the photo as shot (any size; EXIF orientation applied)
  WORK_ORIGINAL  the downscaled copy the pipeline worked on;  WORK_FINAL  the pipeline's finished image at that size
How: the edit is measured as a per-pixel change in CIELAB at the working size (final - original), upsampled, and
then made to follow the full-resolution edges with a guided filter (guide: the full-resolution L*), so no colour or
light bleeds across an edge. The change is added to the full-resolution original: every fine detail in the output is
the original's own; only light and colour come from the edit. Deterministic. Needs numpy, Pillow, OpenCV.
Prints a JSON report (sizes, the scale, and how well the result reproduces the edit at the working size).
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ps_common import lab_to_lin, srgb_to_lab, to_srgb  # noqa: E402


def load(path):
    return np.asarray(ImageOps.exif_transpose(Image.open(path)).convert('RGB'), np.float32) / 255.0


def guided(I, p, r, eps):
    """He et al. guided filter, grey guide I, input p (same size), box radius r."""
    k = (2 * r + 1, 2 * r + 1)
    mI = cv2.boxFilter(I, -1, k); mp = cv2.boxFilter(p, -1, k)
    cov = cv2.boxFilter(I * p, -1, k) - mI * mp
    var = cv2.boxFilter(I * I, -1, k) - mI * mI
    a = cov / (var + eps); b = mp - a * mI
    return cv2.boxFilter(a, -1, k) * I + cv2.boxFilter(b, -1, k)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    opt = dict(a[2:].split('=', 1) for a in sys.argv[1:] if a.startswith('--') and '=' in a)
    if len(args) < 4:
        sys.exit(__doc__)
    full_p, wo_p, wf_p, out_p = args[:4]
    F = load(full_p); WO = load(wo_p); WF = load(wf_p)
    if WF.shape != WO.shape:
        WF = np.asarray(Image.fromarray(np.uint8(np.rint(WF * 255))).resize((WO.shape[1], WO.shape[0]), Image.LANCZOS), np.float32) / 255
    H, W = F.shape[:2]
    scale = W / WO.shape[1]
    d = srgb_to_lab(WF) - srgb_to_lab(WO)                       # the edit, per pixel, at the working size
    up = cv2.resize(d, (W, H), interpolation=cv2.INTER_CUBIC)
    LF = srgb_to_lab(F)
    guide = (LF[..., 0] / 100.0).astype(np.float32)
    r = max(2, int(round(scale * 1.5)))                         # about one working pixel and a half
    out = LF.copy()
    for c in range(3):
        out[..., c] = LF[..., c] + guided(guide, up[..., c].astype(np.float32), r, 1e-3)
    out[..., 0] = np.clip(out[..., 0], 0, 100)
    rgb = np.clip(to_srgb(np.clip(lab_to_lin(out), 0, None)), 0, 1)
    im = Image.fromarray(np.uint8(np.rint(rgb * 255)))
    if out_p.lower().endswith(('.jpg', '.jpeg')):
        im.save(out_p, quality=int(opt.get('quality', 95)), subsampling=0)
    else:
        im.save(out_p)
    # self-check: the full-size result, brought back to the working size, should match the working final
    back = np.asarray(im.resize((WO.shape[1], WO.shape[0]), Image.LANCZOS), np.float32) / 255
    err = float(np.abs(back - WF).mean() * 255)
    rep = {'tool': 'full_res.py v2.1.0', 'full_size': [W, H], 'work_size': [WO.shape[1], WO.shape[0]],
           'scale': round(scale, 3), 'guided_radius': r, 'mean_abs_error_at_work_size_0_255': round(err, 2),
           'verdict': 'PASS' if err < 3.0 else 'CHECK_BY_EYE: the full-size result differs from the working final'}
    print(json.dumps(rep, indent=1))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
