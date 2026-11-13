#!/usr/bin/env python3
"""Photographic Studio v1.1.0 - reference style ("参考这张"): grade parameters that move a photo toward a reference look.
Usage: python3 -I reference_style.py ORIGINAL REFERENCE OUT_PARAMS_JSON [--strength=0.6]
Takes only the part of a look that does not depend on what is in the picture: the colour cast and the split toning,
read on near-neutral pixels (clouds, walls, stone, grey shadows), plus a mild share of the reference's colourfulness.
Brightness and contrast depend on the scene (a bright wall, a night sky) and are only reported, for the director's
brief. The main carrier of a reference look is G: SKILL.md gives G the reference image with the original.
Moves the ORIGINAL `strength` (0..1, default 0.6) of the way, with tight caps. OUT_PARAMS_JSON is a grade.py params
file for finish.py / grade.py; the physics and intensity checks still decide. A report is printed as JSON.
Deterministic: the same inputs give the same parameters (each one is found by bisection with grade.py itself).
"""
import contextlib, io, json, sys, tempfile
from pathlib import Path
import numpy as np
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ps_common import load_rgb, save_png, srgb_to_lab
import grade

def small(a, side=512):
    h, w = a.shape[:2]; s = side / max(h, w)
    if s >= 1: return a
    im = Image.fromarray(np.uint8(np.clip(np.rint(a * 255), 0, 255)))
    return np.asarray(im.resize((max(1, round(w * s)), max(1, round(h * s))), Image.LANCZOS)).astype(np.float32) / 255


def stats(rgb):
    lab = srgb_to_lab(rgb); L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    lit = L > 15; lit = lit if lit.sum() > 100 else np.ones_like(L, bool)
    C = np.hypot(a, b)
    # near-neutral pixels: there the colour is the photo's cast or grade, not the colour of the things in it
    neu = (C < 14) & (L > 8) & (L < 95)
    nmid, ndk, nhi = neu & (L > 25) & (L < 80), neu & (L <= 35), neu & (L >= 70)
    enough = lambda m: m.sum() > max(200, 0.01 * L.size)
    base = nmid if enough(nmid) else (neu if enough(neu) else lit)
    ma, mb = float(a[base].mean()), float(b[base].mean())
    split = lambda m: [round(float(a[m].mean()) - ma, 2), round(float(b[m].mean()) - mb, 2)] if enough(m) else [0.0, 0.0]
    return {'warm': round(mb, 2), 'tint': round(ma, 2), 'chroma': round(float(C[lit].mean()), 2),
            'neutral_share': round(float(neu.mean()), 3), 'split_shadows': split(ndk), 'split_highlights': split(nhi),
            'contrast': round(float(L.std()), 2), 'dark': round(float(np.percentile(L, 10)), 2),
            'light': round(float(np.percentile(L, 90)), 2)}


CAPS = {'warm': 5.0, 'tint': 2.5, 'chroma': (0.85, 1.3), 'split': 3.0}
RANGES = {'temp': (-0.6, 0.6), 'tint': (-0.4, 0.4), 'vibrance': (-0.3, 0.45)}


def targets(o, r, s):
    c = lambda d, cap: float(np.clip(d, -cap, cap))
    t = {'warm': o['warm'] + c(s * (r['warm'] - o['warm']), CAPS['warm']),
         'tint': o['tint'] + c(s * (r['tint'] - o['tint']), CAPS['tint']),
         'chroma': o['chroma'] * float(np.clip(1 + s * (r['chroma'] / max(o['chroma'], 1e-3) - 1), *CAPS['chroma']))}
    split = {k: [round(c(s * (r[k][i] - o[k][i]), CAPS['split']), 2) for i in (0, 1)] for k in ('split_shadows', 'split_highlights')}
    return t, split


def main(orig_p, ref_p, out_p, strength=0.6):
    strength = float(np.clip(strength, 0, 1))
    o_img, r_img = small(load_rgb(orig_p)), small(load_rgb(ref_p))
    o, r = stats(o_img), stats(r_img)
    t, split = targets(o, r, strength)
    with tempfile.TemporaryDirectory() as td:
        td = Path(td); src = td / 'src.png'; save_png(o_img, src)
        params = {}
        if any(split['split_shadows']) or any(split['split_highlights']):
            params['tone_split'] = {'shadows': split['split_shadows'], 'highlights': split['split_highlights']}

        def measure(p):
            grade.clamps.clear()
            pj = td / 'p.json'; pj.write_text(json.dumps(p)); outp = td / 'o.png'
            with contextlib.redirect_stdout(io.StringIO()):
                grade.main(str(src), str(outp), str(pj))
            return stats(load_rgb(outp))

        def solve(set_value, key, lo, hi, target, increasing=True):
            a, b = lo, hi
            for _ in range(14):
                m = (a + b) / 2; v = measure(set_value(m))[key]
                if (v < target) == increasing: a = m
                else: b = m
            return round((a + b) / 2, 3)

        def setter(path):
            def f(v):
                p = json.loads(json.dumps(params)); d = p
                for k in path[:-1]: d = d.setdefault(k, {})
                d[path[-1]] = v; return p
            return f

        for path, key, rng in ((('white_balance', 'temp'), 'warm', RANGES['temp']), (('white_balance', 'tint'), 'tint', RANGES['tint']),
                               (('vibrance',), 'chroma', RANGES['vibrance'])):
            v = solve(setter(path), key, rng[0], rng[1], t[key])
            if abs(v) >= 0.02: params = setter(path)(v)
        achieved = measure(params)
    Path(out_p).write_text(json.dumps(params, ensure_ascii=False, indent=1), encoding='utf-8')
    rep = {'tool': 'reference_style.py v1.1.0', 'strength': strength, 'original': o, 'reference': r,
           'target': {k: round(v, 2) for k, v in t.items()}, 'achieved_on_preview': achieved, 'params': params,
           'for_the_brief': {k: [o[k], r[k]] for k in ('contrast', 'dark', 'light')},
           'note': 'cast, split toning and a mild colourfulness share only; brightness and contrast are for the director to judge (for_the_brief: original, reference). Run finish.py with these params so the physics and intensity checks decide'}
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    return rep


if __name__ == '__main__':
    args = [x for x in sys.argv[1:] if not x.startswith('--')]
    opt = {x.split('=')[0]: x.split('=')[1] for x in sys.argv[1:] if x.startswith('--') and '=' in x}
    if len(args) != 3:
        print(__doc__); sys.exit(2)
    main(args[0], args[1], args[2], float(opt.get('--strength', 0.6)))
