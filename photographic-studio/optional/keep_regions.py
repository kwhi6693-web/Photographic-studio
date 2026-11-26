#!/usr/bin/env python3
"""Photographic Studio v1.1.0 - keep regions: what the director brief says must not change really does not change.
Usage: python3 -I keep_regions.py ORIGINAL EDITED OUT_PNG REGIONS_JSON [RECEIPT_JSON]
  ORIGINAL      the original photo;  EDITED  the edited photo (same scene; resized to the original if needed)
  REGIONS_JSON  a list, or {"keep": [...]} (the grade parameters of finish.py), of
                {"what": "painted screen", "box": [x0, y0, x1, y1] (fractions of the frame), "mode": "colour" | "content"}
  mode colour  (default) the region keeps the ORIGINAL's colour (Lab a, b); its brightness follows the edit, so it
               lights up with the rest of the photo and does not stand out as a patch. For colours the edit must not
               carry into this region (a whole-frame colour shift spilling onto a sign, glass, a wall that must stay).
  mode content the region keeps the original's own detail, local brightness and local colour; only the edit's
               large-scale change of light and colour (about 1/15 of the short edge and wider) is carried over, so the
               region still sits in the new light and tone. For content the edit repainted (G drew something that is
               not there): what G drew does not come through, the overall warmth of the scene does.
Boxes from the brief are rough: each mask is pulled to the original's own edges (edge-aware, guided by the original)
and feathered. A seam check compares the colour step across each region's border with the step in the original;
a step above 3 dE is retried once with a wider transition; only a step above 6 dE is flagged (KEEP_SEAM, v1.6.0).
v1.6.0: boxes smaller than 16 px on a side are widened around their centre (recorded as widened_to), not dropped;
each region is computed in a padded window around its box (same result, much faster with many boxes).
Deterministic, pure numpy + Pillow. No pixel is invented: inside a region every value comes from the original or is
the edit's own brightness.
"""
import json, sys
from pathlib import Path
import numpy as np
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ps_common import load_rgb, save_png, to_linear, to_srgb, lin_to_lab, lab_to_lin, blur, guided, sha256

SEAM_MAX = 3.0     # above this a wider transition is tried once
SEAM_FLAG = 6.0    # v1.6.0: only a step above this is flagged (3-6 dE on a smooth border was not visible in accepted finals)
MIN_BOX_PX = 16    # v1.6.0: boxes smaller than this (either side) are widened around their centre instead of dropped


def regions_of(obj):
    regs = obj.get('keep', []) if isinstance(obj, dict) else (obj or [])
    out = []
    for r in regs:
        try:
            x0, y0, x1, y1 = [min(1.0, max(0.0, float(v))) for v in r['box']]
        except (KeyError, TypeError, ValueError):
            continue
        if x1 <= x0 or y1 <= y0:
            continue                      # v1.6.0: only empty boxes are dropped; small ones are widened in apply()
        out.append({'what': str(r.get('what', ''))[:80], 'box': [x0, y0, x1, y1],
                    'mode': 'content' if r.get('mode') == 'content' else 'colour'})
    return out


def mask_for(Lo, box, wide=False, s=None, pixels=None):
    """Box -> soft mask that follows the original's edges. v1.6.0: Lo may be a window of the frame; then s is the
    full frame's short side and pixels the box in window pixels (so the edges land on exactly the same pixels)."""
    h, w = Lo.shape
    s = s or min(h, w)
    if pixels is not None:
        x0, y0, x1, y1 = pixels
    else:
        x0, y0, x1, y1 = int(box[0] * w), int(box[1] * h), int(np.ceil(box[2] * w)), int(np.ceil(box[3] * h))
    m = np.zeros((h, w), np.float32); m[y0:y1, x0:x1] = 1.0
    r = max(2, int(s * (0.02 if wide else 0.012)))
    g = guided(Lo / 100.0, m, r, 1e-3)               # snaps the box edge to the object's own edges nearby
    g = np.clip(g, 0, 1)
    g = blur(g, max(1, r // 3))                       # soft transition, so no hard line
    return np.clip(g, 0, 1).astype(np.float32)


def seam_step(lab_a, lab_b, m):
    """Colour step across the mask border in lab_a, minus the same step in lab_b (the original), in dE."""
    inner, outer = (m > 0.85), (m < 0.15)
    band = (blur(m, 6) > 0.05) & (blur(m, 6) < 0.95)
    L = lab_b[..., 0]
    band &= np.abs(L - blur(L, 3)) < 2.0   # only where the original is smooth: a step at an object's own edge is not a seam
    lo_a = np.stack([blur(lab_a[..., c], 6) for c in range(3)], -1)
    lo_b = np.stack([blur(lab_b[..., c], 6) for c in range(3)], -1)
    ring_in, ring_out = inner & band, outer & band
    if ring_in.sum() < 50 or ring_out.sum() < 50:
        return 0.0
    da = lo_a[ring_in].mean(0) - lo_a[ring_out].mean(0)
    db = lo_b[ring_in].mean(0) - lo_b[ring_out].mean(0)
    return float(np.linalg.norm(da - db))


def _widen(box, h, w):
    """v1.6.0: a box narrower or shorter than MIN_BOX_PX is widened around its centre (clipped to the frame)."""
    x0, y0, x1, y1 = box
    out = [x0, y0, x1, y1]; widened = False
    for lo_i, hi_i, size in ((0, 2, w), (1, 3, h)):
        need = MIN_BOX_PX / size
        if out[hi_i] - out[lo_i] < need:
            c = (out[lo_i] + out[hi_i]) / 2
            a, b = max(0.0, c - need / 2), min(1.0, c + need / 2)
            if a == 0.0:
                b = need
            elif b == 1.0:
                a = 1.0 - need
            out[lo_i], out[hi_i] = a, b; widened = True
    return out, widened


def apply(o, e, regs):
    """o, e: sRGB 0..1 arrays of the same size. Returns (result, per-region records).
    v1.6.0: each region is computed in a window around its box (padded wider than every filter it uses), not on the
    whole frame - the same result, many times faster with many boxes (39 signs: about 14 s -> about 1 s)."""
    lo, le = lin_to_lab(to_linear(o)), lin_to_lab(to_linear(e))
    res = le.copy(); recs = []
    H, W = o.shape[:2]
    s = min(H, W)
    k = max(4, s // 15)
    r_wide = max(2, int(s * 0.02))
    pad = int(2 * k + 3 * r_wide + 40)
    for r in regs:
        box, widened = _widen(r['box'], H, W)
        bx0, by0 = int(box[0] * W), int(box[1] * H)
        bx1, by1 = int(np.ceil(box[2] * W)), int(np.ceil(box[3] * H))
        X0, Y0, X1, Y1 = max(0, bx0 - pad), max(0, by0 - pad), min(W, bx1 + pad), min(H, by1 + pad)
        lo_w, le_w, res_w = lo[Y0:Y1, X0:X1], le[Y0:Y1, X0:X1], res[Y0:Y1, X0:X1]
        pixels = (bx0 - X0, by0 - Y0, bx1 - X0, by1 - Y0)
        best = None
        for wide in (False, True):
            m = mask_for(lo_w[..., 0], None, wide, s, pixels)
            tgt = le_w.copy()
            tgt[..., 1:] = lo_w[..., 1:]                                  # the original's colour
            if r['mode'] == 'content':   # the original's content plus only the edit's large-scale light and colour
                tgt = lo_w + np.stack([blur(le_w[..., c] - lo_w[..., c], k) for c in range(3)], -1)
            cand = res_w * (1 - m[..., None]) + tgt * m[..., None]
            seam = seam_step(cand, lo_w, m)
            if best is None or seam < best[0]:
                best = (seam, cand, m, wide)
            if seam <= SEAM_MAX:
                break
        seam, cand, m, wide = best
        res[Y0:Y1, X0:X1] = cand
        recs.append({**r, 'area': round(float(m.sum() / (H * W)), 4), 'seam_dE': round(seam, 2), 'wide_transition': wide,
                     **({'widened_to': [round(v, 4) for v in box]} if widened else {}),
                     **({'flag': f'KEEP_SEAM {seam:.1f}'} if seam > SEAM_FLAG else {})})
    out = np.clip(to_srgb(lab_to_lin(res)), 0, 1)
    return out, recs


def main():
    a = [x for x in sys.argv[1:] if not x.startswith('--')]
    if len(a) < 4: sys.exit(__doc__)
    src, edited, out_p, rj = a[:4]; rec_p = a[4] if len(a) > 4 else None
    regs = regions_of(json.loads(Path(rj).read_text(encoding='utf-8')))
    o = load_rgb(src); e = load_rgb(edited)
    if e.shape != o.shape:
        e = np.asarray(Image.fromarray(np.uint8(np.rint(e * 255))).resize((o.shape[1], o.shape[0]), Image.LANCZOS)).astype(np.float32) / 255
    if not regs:
        save_png(e, out_p); recs = []
    else:
        res, recs = apply(o, e, regs); save_png(res, out_p)
    flags = [r['flag'] for r in recs if 'flag' in r]
    rec = {'tool': 'keep_regions.py v1.6.0', 'source_sha256': sha256(src), 'regions': recs, 'flags': flags,
           'verdict': ('KEPT' if recs else 'NO_REGIONS') + (' | FLAGS: ' + '; '.join(flags) if flags else '')}
    t = json.dumps(rec, ensure_ascii=False, indent=1)
    if rec_p: Path(rec_p).write_text(t, encoding='utf-8')
    print(t); return 0


if __name__ == '__main__':
    raise SystemExit(main())
