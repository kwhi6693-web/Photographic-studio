#!/usr/bin/env python3
"""Photographic Studio v1.4.0 - improve check: is each of the brief's improvement moves visible in the finished photo?
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
v1.2.6 - a move with "subdue": true (a bright distraction to quiet) is measured as the share of its excess brightness
over its surroundings that the edit took away: floor 0.20, target 0.50 for small spots and 0.40 for patches the size of
clothing (cap 0.45 - more turns them into dull grey patches).
v1.4.0 - gates (--gates; finish.py always runs them, after the attempt is settled): four hard low-frequency gates and
one texture check, all in CIELAB against the original of the same framing. A local micro-contrast measure alone let
flat, grey-shadowed finals through (2026-11-22 courtyard/arcade):
  subject_separation  (L_subject - L_surround) rises by >= 3.5 L* (key_light box; skipped without one)
  global_separation   global_sep(final) / global_sep(original) >= 1.05 (directional light) or 1.02 (diffuse)
  black_anchor        fixed_dark_L (the original's darkest 15 %) changes by -3.5 .. +1.5 L*: no grey lift, no dead black
  colour_order        chroma ratio <= 1.65; near-neutral areas drift <= 3 in a*/b*; in daylight the lit-minus-shade
                      warmth (b*) is kept (~90 % of the original's) and clear (>= 1.0)
  texture (info)      mid-frequency micro-contrast on the original's structure 1.15 .. 1.35x (reported, not a gate)
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


SUBDUE_FLOOR, SUBDUE_SMALL, SUBDUE_PATCH, SUBDUE_CAP = 0.20, 0.50, 0.40, 0.45


def subdue_measure(lo, lf, m):
    """v1.2.6: share of a distraction's excess brightness over its surroundings that the edit took away.
    The eye reads a white shirt at L* 90 among leaves at 30 by the difference (60), not by the 11 L* taken off it
    (2026-11-19, garden 04). Small spots should lose half of it; a patch the size of clothing about 40% (at most 45%),
    or it turns into a dull grey patch. Returns (reduction or None, small)."""
    try:
        import cv2
    except ImportError:   # v1.2.9: no OpenCV - numpy + Pillow stand-in
        import cvlite as cv2
    h, w = m.shape
    core = m > 0.5
    if core.sum() < 20: return None, True
    k = max(6, min(h, w) // 60)
    ring = (cv2.dilate(core.astype(np.uint8), np.ones((2 * k + 1, 2 * k + 1), np.uint8)) > 0) & ~core & (m < 0.1)
    if ring.sum() < 20: return None, True
    eo = float(lo[..., 0][core].mean() - np.median(lo[..., 0][ring]))
    ef = float(lf[..., 0][core].mean() - np.median(lf[..., 0][ring]))
    small = core.mean() < 0.003
    if eo < 5: return None, small
    return 1 - ef / eo, small


def visible(effect, sign, v, T=VISIBLE):
    if v is None: return False
    if effect == 'light': return v * sign >= T['light']
    if effect == 'colour': return v >= T['colour'] if sign > 0 else v <= T['colour-']
    if effect == 'warm': return v * sign >= T['warm']
    if effect == 'contrast': return v >= T['contrast']
    return False


def own_share(base, params, k, lf):
    """Lab of the edit with move k minus the edit without it (None if it cannot be rendered). Same order as finish.py
    v1.2.3: global grade, keep regions, then the moves."""
    import tempfile, contextlib, io, grade as G
    others = [m for j, m in enumerate(params['moves']) if j != k]
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        def grade(inp, prm, out):
            pj = td / 'p.json'; pj.write_text(json.dumps(prm), encoding='utf-8')
            with contextlib.redirect_stdout(io.StringIO()):
                G.clamps.clear(); G.main(str(inp), str(out), str(pj))
        if params.get('keep'):
            import keep_regions as K
            from ps_common import save_png
            grade(base, {kk: v for kk, v in params.items() if kk != 'moves'}, td / 'b.png')
            res, _ = K.apply(load_rgb(src_global[0]), load_rgb(td / 'b.png'), K.regions_of(params))
            save_png(res, td / 'k.png')
            grade(td / 'k.png', {'moves': others}, td / 'o.png')
        else:
            grade(base, {**params, 'moves': others}, td / 'o.png')
        return srgb_to_lab(load_rgb(td / 'o.png'))


src_global = [None]


def auto_reference(base, params):
    """v1.2.7: with the automatic base adjustment on, a move is measured against the photo after auto (and the rest of
    the global grade, and the keep regions) but before any move. Otherwise auto's own change counts for or against
    the move: on a flat photo auto lifts the whole sky while a move deepens its top (2026-11-20 test: "top deeper"
    read as +7.6 brighter and was pushed three rounds harder), and a contrast move would get auto's contrast for free."""
    import tempfile, contextlib, io, grade as G
    with tempfile.TemporaryDirectory() as td:
        td = Path(td); pj = td / 'p.json'
        pj.write_text(json.dumps({k: v for k, v in params.items() if k != 'moves'}), encoding='utf-8')
        with contextlib.redirect_stdout(io.StringIO()):
            G.clamps.clear(); G.main(str(base), str(td / 'b.png'), str(pj))
        if params.get('keep'):
            import keep_regions as K
            from ps_common import save_png
            res, _ = K.apply(load_rgb(src_global[0]), load_rgb(td / 'b.png'), K.regions_of(params))
            save_png(res, td / 'b.png')
        return srgb_to_lab(load_rgb(td / 'b.png'))


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
    lm = lo   # what each move is measured against
    if base and params.get('auto'):
        try:
            r = auto_reference(base, params)
            if r.shape == lo.shape: lm = r
        except Exception:
            pass
    hue = np.degrees(np.arctan2(lo[..., 2], lo[..., 1])) % 360
    out = []
    for i, mv in enumerate(params.get('moves') or []):
        effect, sign = main_effect(mv)
        try:
            m = G.region_mask(mv, h, w, np.clip(lo[..., 0] / 100, 0, 1), hue, lo[..., 0])
            mg = m if not mv.get('on_structure') else G.region_mask({**mv, 'on_structure': False}, h, w, np.clip(lo[..., 0] / 100, 0, 1), hue, lo[..., 0])
        except (KeyError, ValueError, TypeError):
            out.append({'move': i, 'what': mv.get('what', ''), 'result': 'BAD_REGION'}); continue
        if mv.get('subdue'):   # v1.2.6: a distraction is judged by how much brighter than its surroundings it stays
            vals = []   # v1.2.6b: each box on its own (a union of many boxes has no meaningful 'surroundings')
            for bx in [mv.get('box')] + list(mv.get('also') or []):
                if not bx: continue
                mb = G.region_mask({**mv, 'also': None, 'box': bx}, h, w, np.clip(lo[..., 0] / 100, 0, 1), hue, lo[..., 0])
                vb, sb = subdue_measure(lm, lf, mb)
                if vb is not None: vals.append((vb, sb))
            v = float(np.median([x[0] for x in vals])) if vals else None
            small = all(x[1] for x in vals) if vals else True
            tgt = SUBDUE_SMALL if small else SUBDUE_PATCH
            out.append({'move': i, 'what': mv.get('what', ''), 'effect': 'subdue', 'sign': -1,
                        'value': None if v is None else round(v, 3), 'visible': v is None or v >= SUBDUE_FLOOR,
                        'at_target': v is None or v >= tgt, 'over_cap': bool(v is not None and not small and v > SUBDUE_CAP),
                        'target': tgt, 'halo': [0.0, 0.0], 'halo_found': False, 'area': round(float(m.mean()), 4)})
            continue
        v = measure(lm, lf, m, effect, sign) if effect else None
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


SUBJECT_MIN, SEP_DIRECTIONAL, SEP_DIFFUSE = 3.5, 1.05, 1.02
DARK_BAND = (-3.5, 1.5)
CHROMA_MAX, NEUTRAL_DRIFT, TEXTURE_BAND = 1.65, 3.0, (1.15, 1.35)


def gates(src, fin, params, genre=None, subject=True):
    """v1.4.0: the four hard expressiveness gates and the texture check. FINISHED must have ORIGINAL's framing (it is
    resized if needed); a different aspect ratio returns None."""
    from ps_common import global_sep, fixed_dark_delta, structure_mask, midfreq, light_character, sky_mask
    o = load_rgb(src); f = load_rgb(fin)
    if abs(f.shape[1] / f.shape[0] - o.shape[1] / o.shape[0]) > 0.01: return None
    if f.shape != o.shape:
        f = np.asarray(Image.fromarray(np.uint8(np.rint(f * 255))).resize((o.shape[1], o.shape[0]), Image.LANCZOS)).astype(np.float32) / 255
    lo, lf = srgb_to_lab(o), srgb_to_lab(f)
    Lo, Lf = lo[..., 0], lf[..., 0]
    Co, Cf = np.hypot(lo[..., 1], lo[..., 2]), np.hypot(lf[..., 1], lf[..., 2])
    h, w = Lo.shape
    kl = params.get('key_light') if isinstance(params.get('key_light'), dict) else None
    sky = sky_mask(Lo, gaps=True)
    out = {}
    # 1 subject separation
    if subject and kl and kl.get('box'):
        x0, y0, x1, y1 = [float(v) for v in kl['box']]
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32); yy /= max(h - 1, 1); xx /= max(w - 1, 1)
        d = np.sqrt(((xx - (x0 + x1) / 2) / max((x1 - x0) / 2, 0.05)) ** 2 + ((yy - (y0 + y1) / 2) / max((y1 - y0) / 2, 0.05)) ** 2)
        t = np.clip((d - 0.7) / 1.1, 0, 1); S = 1 - t * t * (3 - 2 * t)
        sub, sur = (S > 0.7) & ~sky, (S < 0.25) & ~sky
        if sub.mean() > 0.005 and sur.mean() > 0.02:
            so, sf = float(Lo[sub].mean() - Lo[sur].mean()), float(Lf[sub].mean() - Lf[sur].mean())
            out['subject_separation'] = {'original': round(so, 2), 'final': round(sf, 2), 'gain_L': round(sf - so, 2),
                                         'min': SUBJECT_MIN, 'ok': bool(sf - so >= SUBJECT_MIN)}
        else:
            out['subject_separation'] = {'ok': None, 'note': 'subject or surroundings too small to measure'}
    else:
        out['subject_separation'] = {'ok': None, 'note': 'no key_light box' if subject else 'framing changed: the box no longer applies'}
    # 2 global light/shade separation
    ch = light_character(Lo, Co, (kl or {}).get('from'), lo[..., 2])
    dirl = ch['light'] == 'directional' and (kl or {}).get('light') != 'diffuse' and genre not in ('night', 'museum')
    floor = SEP_DIRECTIONAL if dirl else SEP_DIFFUSE
    r = global_sep(Lf) / max(global_sep(Lo), 1e-6)
    out['global_separation'] = {'ratio': round(r, 3), 'min': floor, 'light': 'directional' if dirl else 'diffuse', 'ok': bool(r >= floor - 0.005)}
    # 3 black anchor
    fd = fixed_dark_delta(Lo, Lf)
    out['black_anchor'] = {'fixed_dark_L_change': round(fd, 2), 'band': list(DARK_BAND), 'ok': bool(DARK_BAND[0] <= fd <= DARK_BAND[1])}
    # 4 colour order
    cr = float(Cf.mean() / max(Co.mean(), 1e-6))
    flat = np.abs(Lo - blur(Lo, 4)) < 2.5
    N = (Co < 6) & (Lo > 35) & (Lo < 92) & ~sky & ~(flat & (Lo > 70) & (np.arange(h)[:, None] < h // 2))
    drift = None
    if N.mean() > 0.02:
        drift = [round(float((lf[..., 1] - lo[..., 1])[N].mean()), 2), round(float((lf[..., 2] - lo[..., 2])[N].mean()), 2)]
    split = None
    if float(Lo.mean()) >= 22 and genre not in ('night', 'museum'):
        from harmonize import lit_shade
        lit, shade, _, _ = lit_shade(Lo, lo[..., 2])
        if lit.mean() > 0.05 and shade.mean() > 0.05:
            do_ = float(lo[..., 2][lit].mean() - lo[..., 2][shade].mean()); df_ = float(lf[..., 2][lit].mean() - lf[..., 2][shade].mean())
            want = max(min(0.9 * do_, do_ - 0.5), 1.0) if do_ > -1.0 else do_   # kept (~90 %) and clear (>= 1)
            split = {'original': round(do_, 2), 'final': round(df_, 2), 'want': round(want, 2), 'ok': bool(df_ >= want - 0.25)}
    ok_c = cr <= CHROMA_MAX + 0.005 and (drift is None or max(abs(drift[0]), abs(drift[1])) <= NEUTRAL_DRIFT) and (split is None or split['ok'])
    out['colour_order'] = {'chroma_ratio': round(cr, 3), 'max': CHROMA_MAX, 'neutral_drift_ab': drift, 'lit_minus_shade_b': split, 'ok': bool(ok_c)}
    # 5 texture (info)
    m = structure_mask(Lo, sky) > 0.5
    if m.mean() > 0.02:
        tr = float(np.abs(midfreq(Lf))[m].mean() / max(np.abs(midfreq(Lo))[m].mean(), 1e-6))
        out['texture'] = {'structure_midfreq_ratio': round(tr, 3), 'band': list(TEXTURE_BAND), 'ok': bool(TEXTURE_BAND[0] <= tr <= TEXTURE_BAND[1]), 'gate': False}
    else:
        out['texture'] = {'ok': None, 'note': 'little structure in the frame', 'gate': False}
    failed = [k for k in ('subject_separation', 'global_separation', 'black_anchor', 'colour_order') if out[k].get('ok') is False]
    out['failed'] = failed
    out['verdict'] = 'GATES_PASS' if not failed else 'GATES_FAIL: ' + ', '.join(failed)
    return out


def main():
    a = [x for x in sys.argv[1:] if not x.startswith('--')]
    if len(a) < 3: sys.exit(__doc__)
    src, fin, pj = a[:3]; rec_p = a[3] if len(a) > 3 else None
    params = json.loads(Path(pj).read_text(encoding='utf-8') or '{}')
    opt = {x.split('=')[0]: x.split('=', 1)[1] for x in sys.argv[1:] if x.startswith('--') and '=' in x}
    if '--gates' in sys.argv:   # v1.4.0
        g = gates(src, fin, params, opt.get('--genre'), subject='--no-subject' not in sys.argv)
        rec = {'tool': 'improve_check.py v1.4.0', 'gates': g, 'verdict': (g or {}).get('verdict', 'SKIPPED: other framing')}
        t = json.dumps(rec, ensure_ascii=False, indent=1)
        if rec_p: Path(rec_p).write_text(t, encoding='utf-8')
        print(t); return 0
    moves = check(src, fin, params, opt.get('--base'))
    if moves is None:
        rec = {'tool': 'improve_check.py v1.4.0', 'verdict': 'SKIPPED: the finished photo has another framing (cropped); measure before the crop - the finish.py receipt is the record'}
        print(json.dumps(rec, ensure_ascii=False, indent=1)); return 0
    weak = [m['move'] for m in moves if not m.get('visible')]
    below = [m['move'] for m in moves if not m.get('at_target')]
    halos = [m['move'] for m in moves if m.get('halo_found')]
    verdict = 'NO_MOVES: the brief promised no visible improvement' if not moves else \
              ('VISIBLE' if not weak else 'WEAK: ' + '; '.join(f"{m['what'] or m['move']} ({m.get('effect')} {m.get('value')})" for m in moves if not m.get('visible')))
    if halos: verdict += ' | HALO: ' + '; '.join(m['what'] or str(m['move']) for m in moves if m.get('halo_found'))
    if not weak and below: verdict += ' | BELOW_TARGET: ' + '; '.join(m['what'] or str(m['move']) for m in moves if not m.get('at_target'))
    rec = {'tool': 'improve_check.py v1.4.0', 'source_sha256': sha256(src), 'moves': moves, 'weak': weak, 'below_target': below, 'halo': halos, 'verdict': verdict}
    t = json.dumps(rec, ensure_ascii=False, indent=1)
    if rec_p: Path(rec_p).write_text(t, encoding='utf-8')
    print(t); return 0


if __name__ == '__main__':
    raise SystemExit(main())
