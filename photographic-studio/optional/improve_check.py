#!/usr/bin/env python3
"""Photographic Studio v1.2.1 - improve check: is each of the brief's improvement moves visible in the finished photo?
Usage: python3 improve_check.py ORIGINAL FINISHED PARAMS_JSON [RECEIPT_JSON] [--base=GRADE_INPUT]
  PARAMS_JSON  the grade parameters with "moves" (grade.py). FINISHED must have the original's framing (run it before
               any crop), it is resized to the original if needed.
v1.2.0 turns the question round: first "can a viewer see the improvement the brief promised", then "is nothing broken".
For each move the region is the move's own mask (as grade.py draws it) and its main effect - the largest of lift,
sat, warm and clarity, or the move's "look" - is measured there between the original and the finished photo:
  light   mean L* change          >= 2.5 (in the move's direction)
  colour  mean chroma ratio       >= 1.10 (colour+) or <= 0.91 (colour-)
  warm    mean Lab b change       >= 1.5 (in the move's direction)
  contrast local contrast ratio   >= 1.08
The thresholds sit just under the most restrained final the user approved (willow lake: whole frame chroma x1.10,
local contrast x1.06, L +1.6; a move acts on its own region, where the change is larger than the whole-frame mean).
v1.2.1 - a floor is not a target. Agents wrote moves just over the floor (2026-11-15 run: every move "visible", the
sunset gate unchanged as a whole). So each move also has a TARGET at the level of the finals the user approved (median
of the six taste samples: colour x1.39, local contrast x1.19, L +2.6 over the whole frame; a move's own area changes
more): light 4.0 L*, colour x1.25 (colour- x0.85), warm 2.5, local contrast x1.18. finish.py strengthens a move until it
reaches its target, as long as the physics checks hold and nothing goes over a strength limit; only a move under the
floor counts as a failure.
FINISHED with a different framing than ORIGINAL (cropped) is not measured (SKIPPED): run this before the crop; the
finish.py receipt is the record.
A brief without moves is reported NO_MOVES: v1.2.0 requires at least one visible improvement per photo.
Halo: a rect or ellipse move whose soft edge crosses a smooth area (sky, haze, a plain wall) leaves a ring of light or
colour around the subject. Where the original is smooth inside the move's feather zone, the change of the edit across
1/20 of the frame is measured (95th percentile); over HALO_L (L*) or HALO_C (chroma) the move is reported in "halo".
With --base (the image grade.py was applied to) only the move's own share of the edit is measured: the photo is
graded once more without that move and the difference is used, so a sky gradient move next to it does not count.
(Calibrated on the sunset gate: ellipse around the pavilion 3.8 / 6.0 = a visible ring; the same move on structure only
2.0 / 3.1 = none; the book page lift 3.7 / - = none.) finish.py then puts the move on structure only.
Deterministic, numpy + Pillow (+ grade.py's mask code).
"""
import json, sys
from pathlib import Path
import numpy as np
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ps_common import load_rgb, srgb_to_lab, blur, sha256

VISIBLE = {'light': 2.5, 'colour': 1.10, 'colour-': 0.91, 'warm': 1.5, 'contrast': 1.08}   # floor: under it = failure
TARGET = {'light': 4.0, 'colour': 1.25, 'colour-': 0.85, 'warm': 2.5, 'contrast': 1.18}    # v1.2.1: what to reach
NORM = {'lift': 6.0, 'sat': 0.15, 'warm': 3.0, 'clarity': 0.2}
EFFECT = {'lift': 'light', 'sat': 'colour', 'warm': 'warm', 'clarity': 'contrast'}
HALO_L, HALO_C = 4.0, 4.5


def halo(lo, lf, m):
    """(L, chroma) change across 1/20 of the frame in the move's feather zone where the original is smooth."""
    L = lo[..., 0]; s = min(L.shape)
    smooth = (np.abs(L - blur(L, 3)) < 1.0) & (np.abs(blur(L, 2) - blur(L, 12)) < 2.0)
    smooth = blur(smooth.astype(np.float32), max(4, s // 40)) > 0.97   # away from structure: a change ON an object is not a halo
    z = (m > 0.05) & (m < 0.95) & smooth
    if z.sum() < 200: return 0.0, 0.0
    out = []
    for a, b in ((lf[..., 0], L), (np.hypot(lf[..., 1], lf[..., 2]), np.hypot(lo[..., 1], lo[..., 2]))):
        D = blur(a - b, max(4, s // 40)); gy, gx = np.gradient(D)
        out.append(round(float(np.percentile((np.hypot(gx, gy) * (s / 20))[z], 95)), 2))
    return tuple(out)


def main_effect(mv):
    """(effect, sign) of a move: its 'look' if given, else its largest parameter."""
    look = str(mv.get('look', ''))
    for e in ('light', 'colour', 'warm', 'contrast'):
        if look.startswith(e):
            return e, (-1 if look.endswith('-') else 1)
    best = None
    for k, n in NORM.items():
        v = float(mv.get(k, 1 if k == 'sat' else 0)) - (1 if k == 'sat' else 0)
        if v and (best is None or abs(v) / n > best[0]):
            best = (abs(v) / n, EFFECT[k], 1 if v > 0 else -1)
    return (best[1], best[2]) if best else (None, 0)


def measure(lo, lf, m, effect, sign):
    w = m / max(float(m.sum()), 1e-6)
    if effect == 'light':
        return float(((lf[..., 0] - lo[..., 0]) * w).sum())
    if effect == 'colour':
        co, cf = np.hypot(lo[..., 1], lo[..., 2]), np.hypot(lf[..., 1], lf[..., 2])
        return float((cf * w).sum() / max(float((co * w).sum()), 1e-6))
    if effect == 'warm':
        return float(((lf[..., 2] - lo[..., 2]) * w).sum())
    if effect == 'contrast':
        lc = lambda L: np.abs(L - blur(L, 8))
        return float((lc(lf[..., 0]) * w).sum() / max(float((lc(lo[..., 0]) * w).sum()), 1e-6))
    return None


def visible(effect, sign, v, T=VISIBLE):
    if v is None: return False
    if effect == 'light': return v * sign >= T['light']
    if effect == 'colour': return v >= T['colour'] if sign > 0 else v <= T['colour-']
    if effect == 'warm': return v * sign >= T['warm']
    if effect == 'contrast': return v >= T['contrast']
    return False


def own_share(base, params, k, lf):
    """Lab of the edit with move k minus the edit without it (None if it cannot be rendered)."""
    import tempfile, grade as G
    q = json.loads(json.dumps(params)); q['moves'] = [m for j, m in enumerate(q['moves']) if j != k]
    with tempfile.TemporaryDirectory() as td:
        pj, out = Path(td) / 'p.json', Path(td) / 'o.png'
        pj.write_text(json.dumps(q), encoding='utf-8')
        import contextlib, io
        with contextlib.redirect_stdout(io.StringIO()):
            G.clamps.clear(); G.main(str(base), str(out), str(pj))
        if params.get('keep'):
            import keep_regions as K
            o = load_rgb(src_global[0]); e = load_rgb(out)
            res, _ = K.apply(o, e, K.regions_of(params)); return srgb_to_lab(res)
        return srgb_to_lab(load_rgb(out))


src_global = [None]


def check(src, fin, params, base=None):
    src_global[0] = src
    import grade as G
    o = load_rgb(src); f = load_rgb(fin)
    if abs(f.shape[1] / f.shape[0] - o.shape[1] / o.shape[0]) > 0.01:
        return None   # v1.2.1: a cropped final cannot be measured against the brief's boxes
    if f.shape != o.shape:
        f = np.asarray(Image.fromarray(np.uint8(np.rint(f * 255))).resize((o.shape[1], o.shape[0]), Image.LANCZOS)).astype(np.float32) / 255
    lo, lf = srgb_to_lab(o), srgb_to_lab(f)
    h, w = o.shape[:2]
    hue = np.degrees(np.arctan2(lo[..., 2], lo[..., 1])) % 360
    out = []
    for i, mv in enumerate(params.get('moves') or []):
        effect, sign = main_effect(mv)
        try:
            m = G.region_mask(mv, h, w, np.clip(lo[..., 0] / 100, 0, 1), hue, lo[..., 0])
            mg = m if not mv.get('on_structure') else G.region_mask({**mv, 'on_structure': False}, h, w, np.clip(lo[..., 0] / 100, 0, 1), hue, lo[..., 0])
        except (KeyError, ValueError, TypeError):
            out.append({'move': i, 'what': mv.get('what', ''), 'result': 'BAD_REGION'}); continue
        v = measure(lo, lf, m, effect, sign) if effect else None
        hl, hc = 0.0, 0.0
        if mv.get('shape', 'rect') in ('rect', 'ellipse'):
            if base:
                lw = own_share(base, params, i, lf)
                hl, hc = halo(lw, lf, mg) if lw is not None and lw.shape == lf.shape else halo(lo, lf, mg)
            else:
                hl, hc = halo(lo, lf, mg)
        out.append({'move': i, 'what': mv.get('what', ''), 'effect': effect, 'sign': sign,
                    'value': None if v is None else round(v, 3), 'visible': visible(effect, sign, v),
                    'at_target': visible(effect, sign, v, TARGET),
                    'halo': [hl, hc], 'halo_found': bool(hl > HALO_L or hc > HALO_C), 'area': round(float(m.mean()), 3)})
    return out


def main():
    a = [x for x in sys.argv[1:] if not x.startswith('--')]
    if len(a) < 3: sys.exit(__doc__)
    src, fin, pj = a[:3]; rec_p = a[3] if len(a) > 3 else None
    params = json.loads(Path(pj).read_text(encoding='utf-8') or '{}')
    opt = {x.split('=')[0]: x.split('=', 1)[1] for x in sys.argv[1:] if x.startswith('--') and '=' in x}
    moves = check(src, fin, params, opt.get('--base'))
    if moves is None:
        rec = {'tool': 'improve_check.py v1.2.1', 'verdict': 'SKIPPED: the finished photo has another framing (cropped); measure before the crop - the finish.py receipt is the record'}
        print(json.dumps(rec, ensure_ascii=False, indent=1)); return 0
    weak = [m['move'] for m in moves if not m.get('visible')]
    below = [m['move'] for m in moves if not m.get('at_target')]
    halos = [m['move'] for m in moves if m.get('halo_found')]
    verdict = 'NO_MOVES: the brief promised no visible improvement' if not moves else \
              ('VISIBLE' if not weak else 'WEAK: ' + '; '.join(f"{m['what'] or m['move']} ({m.get('effect')} {m.get('value')})" for m in moves if not m.get('visible')))
    if halos: verdict += ' | HALO: ' + '; '.join(m['what'] or str(m['move']) for m in moves if m.get('halo_found'))
    if not weak and below: verdict += ' | BELOW_TARGET: ' + '; '.join(m['what'] or str(m['move']) for m in moves if not m.get('at_target'))
    rec = {'tool': 'improve_check.py v1.2.1', 'source_sha256': sha256(src), 'moves': moves, 'weak': weak, 'below_target': below, 'halo': halos, 'verdict': verdict}
    t = json.dumps(rec, ensure_ascii=False, indent=1)
    if rec_p: Path(rec_p).write_text(t, encoding='utf-8')
    print(t); return 0


if __name__ == '__main__':
    raise SystemExit(main())
