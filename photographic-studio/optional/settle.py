#!/usr/bin/env python3
"""Photographic Studio v2.1.0 - settle: step 6 strength calibration in one call.
Usage: python3 -I settle.py ORIGINAL FINISHED OUT_PNG [RECEIPT_JSON] [--genre=museum] [--n-direct]
  --n-direct  finish.py delivered an N direct route (G not used): lift to the middle of each band, not its edge
  ORIGINAL   the original photo;  FINISHED  the image finish.py delivered (or any later version)
Does what step 6 used to do by hand, round after round:
  1. too weak (intensity_check.py says a floor is not reached): adds the smallest amount of exposure / vibrance /
     clarity that reaches the floor (at most the full step below), and keeps it only if the physics check finds no
     new problem;
  2. too strong (a limit is exceeded): removes the smallest amount that brings the measure back under the limit,
     never more; if that would lose expressiveness (intensity_check.py --before says DO_NOT_DELIVER), it removes only
     as much as keeps the expressiveness, and the rest stays as a flag;
  3. (v1.0.6) anchor: pulls the overall brightness, warmth and colour into the narrow band the user's approved
     photos sit in (BANDS below), so two runs of the same photo - whose G drafts always differ - come out alike.
     Only measures outside their band move, and only to the band's nearest edge. Never adds a physics problem.
Every candidate is a grade.py pass on FINISHED with one scaled parameter set (bisection, about 6 tries per direction).
It never touches what is in range, never lowers a measure below its limit, and never stops to ask.
Deterministic. Needs numpy, Pillow (and what grade.py, intensity_check.py, physics_check.py need).
"""
import json, shutil, subprocess, sys, tempfile
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
SEARCH_EDGE = 640   # v2.1.0: long edge of the copies the parameter search runs on
PHYS_SERIOUS = ('spotlight_glow', 'darkening_patch', 'tone_order', 'halo', 'light_shade_sep')
# full step for each measure; the tool uses the smallest fraction of it that is enough
UP = {'L_mean_change': {'exposure_ev': 0.25}, 'chroma_ratio': {'vibrance': 0.35}, 'subject_chroma_ratio': {'vibrance': 0.35},
      'local_contrast_ratio': {'clarity': 0.25}, 'subject_local_contrast_ratio': {'clarity': 0.25},
      'sky_L_change': {'sky_lift': 18}}   # 'too weak' for the sky means it was darkened past the limit
# v1.0.6: the narrow bands two runs are pulled into (inside the user's ranges; from the approved samples).
# (measure, grade parameter, low, high); None = open. Stability first (user, 2026-11-14).
BANDS = {
    'day':       [('L_mean_change', 'exposure_ev', 2.0, 4.0), ('lit_warmth_change', 'temp', -1.5, 3.0), ('chroma_ratio', 'saturation', 1.12, 1.26), ('local_contrast_ratio', 'contrast', 1.03, 1.30), ('mid_L_change', 'exposure_ev', 1.0, 3.5)],
    'lowcolour': [('L_mean_change', 'exposure_ev', 2.0, 4.0), ('lit_warmth_change', 'temp', -1.5, 3.5), ('chroma_ratio', 'saturation', 1.30, 2.20), ('local_contrast_ratio', 'contrast', 1.03, 1.30), ('mid_L_change', 'exposure_ev', 1.0, 3.5)],
    'night':     [('L_mean_change', 'exposure_ev', 1.2, 3.2), ('lit_warmth_change', 'temp', -1.5, 4.5), ('local_contrast_ratio', 'contrast', 1.03, 1.35), ('mid_L_change', 'exposure_ev', 0.5, 2.5)],
    'museum':    [('subject_L_change', 'exposure_ev', -1.0, 3.5), ('lit_warmth_change', 'temp', -1.5, 4.0), ('subject_chroma_ratio', 'saturation', 1.35, 1.75), ('subject_local_contrast_ratio', 'contrast', 1.14, 1.40), ('mid_L_change', 'exposure_ev', 0.5, 3.0)],
}
SPAN = {'shadows': (-10.0, 15.0), 'exposure_ev': (-0.6, 0.6), 'temp': (-0.9, 0.9), 'saturation': (0.6, 1.5), 'contrast': (-0.4, 0.4)}
DOWN = {'L_mean_change': {'exposure_ev': -0.3}, 'subject_L_change': {'exposure_ev': -0.3}, 'background_L_change': {'shadows': -6},
        'chroma_ratio': {'saturation': -0.25}, 'subject_chroma_ratio': {'saturation': -0.25},
        'lit_warmth_change': {'white_balance.temp': -0.35}, 'highlight_p99_change': {'highlights': -10},
        'sky_L_change': {'sky_lift': -8}}


def mid_L_change(src, img):
    # v1.0.6: mean L* change of the original's middle 40% of tones - where two G drafts differ most
    import numpy as np
    from PIL import Image
    sys.path.insert(0, str(HERE)); from ps_common import load_rgb, srgb_to_lab
    o = load_rgb(src); f = load_rgb(img)
    if f.shape != o.shape:
        f = np.asarray(Image.fromarray(np.uint8(np.rint(f * 255))).resize((o.shape[1], o.shape[0]), Image.LANCZOS)).astype(np.float32) / 255
    Lo, Lf = srgb_to_lab(o)[..., 0], srgb_to_lab(f)[..., 0]
    lo, hi = np.percentile(Lo, 30), np.percentile(Lo, 70); m = (Lo >= lo) & (Lo < hi)
    return round(float((Lf - Lo)[m].mean()), 2)


def run(tool, *args):
    if str(HERE) not in sys.path: sys.path.insert(0, str(HERE))
    from ps_common import run_tool
    return run_tool(tool, *args)


def params_for(step, t):
    p = {}
    for k, v in step.items():
        if k == 'saturation': p['saturation'] = round(1 + v * t, 4)
        elif k == 'white_balance.temp': p['white_balance'] = {'temp': round(v * t, 4)}
        elif k == 'sky_lift': p['regions'] = [{'shape': 'gradient', 'from': 'top', 'end': 0.55, 'feather': 0.2, 'only_hue': 'blue', 'lift': round(v * t, 3)}]
        else: p[k] = round(v * t, 4)
    return p


def failing(it, direction):
    return {k: v for k, v in it.get('checks', {}).items()
            if isinstance(v, dict) and v.get('ok') is False and v.get('direction') == direction}


def serious(src, img):
    ph = run('physics_check.py', src, img)
    return sorted(k for k, v in ph.get('checks', {}).items() if k in PHYS_SERIOUS and isinstance(v, dict) and v.get('ok') is False)


def main():
    a = [x for x in sys.argv[1:] if not x.startswith('--')]
    opt = dict(x[2:].split('=', 1) for x in sys.argv[1:] if x.startswith('--') and '=' in x)
    if len(a) < 3: sys.exit(__doc__)
    src, fin, out = a[:3]; rec_p = a[3] if len(a) > 3 else None
    gopt = [f"--genre={opt['genre']}"] if opt.get('genre') else []
    center = opt.get('target') == 'center' or '--n-direct' in sys.argv
    rec = {'tool': 'settle.py v2.1.0', 'steps': []}
    with tempfile.TemporaryDirectory() as td:
        td = Path(td); n = [0]

        def graded(base, p, before=None):
            n[0] += 1; pj = td / f'p{n[0]}.json'; o = td / f'c{n[0]}.png'
            pj.write_text(json.dumps(p), encoding='utf-8'); run('grade.py', base, o, pj)
            if not o.exists(): return None, None
            return o, run('intensity_check.py', src, o, *gopt, *([f'--before={before}'] if before else []))

        # v2.1.0: search on small copies (SEARCH_EDGE px), apply each accepted step once at full size
        src_full, cur_full = src, td / 'start_full.png'
        shutil.copy(fin, cur_full)

        def small(path, name):
            im = Image.open(path).convert('RGB'); k = SEARCH_EDGE / max(im.size)
            if k < 1: im = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)
            o = td / name; im.save(o); return o

        src = str(small(src_full, 'src_small.png'))
        cur = small(cur_full, 'start.png')
        n_acc = [0]

        def accept(p):
            nonlocal cur, cur_full
            n_acc[0] += 1; pj = td / f'acc{n_acc[0]}.json'; o = td / f'full{n_acc[0]}.png'
            pj.write_text(json.dumps(p), encoding='utf-8'); run('grade.py', cur_full, o, pj)
            if o.exists():
                cur_full = o; cur = small(o, f'small{n_acc[0]}.png')

        it0 = run('intensity_check.py', src, cur, *gopt)
        rec['start'] = it0.get('verdict')
        base_phys = serious(src, cur)

        # 1. too weak: smallest lift that reaches every floor it can (two passes: the sky first, then the rest)
        for k_pass in range(2):
            weak = {k: v for k, v in failing(run('intensity_check.py', src, cur, *gopt), 'too weak').items() if k in UP}
            if not weak: break
            step = {}
            for k in weak:
                for pk, pv in UP[k].items(): step[pk] = max(step.get(pk, 0), pv)
            if 'sky_L_change' in weak: step.pop('exposure_ev', None)   # the sky first; a global lift would undo it only partly
            target = [k for k in weak if any(pk in step for pk in UP[k])]
            o, it = graded(cur, params_for(step, 1.0))
            if o is None: break
            best = (1.0, o, it) if not any(k in failing(it, 'too weak') for k in target) else None
            lo, hi = 0.0, 1.0
            for _ in range(5):
                m = (lo + hi) / 2; o2, it2 = graded(cur, params_for(step, m))
                if o2 is not None and not any(k in failing(it2, 'too weak') for k in target): best, hi = (m, o2, it2), m
                else: lo = m
            if best is None: best = (1.0, o, it)   # the floor cannot be reached with a full step: take the full step
            new_phys = [k for k in serious(src, best[1]) if k not in base_phys]
            entry = {'direction': 'up', 'for': sorted(target), 'params': params_for(step, best[0]), 'result': best[2].get('verdict')}
            rec['steps'].append(entry)
            if new_phys:
                entry['undone'] = 'new physics problem: ' + ', '.join(new_phys); break
            accept(params_for(step, best[0]))

        # 2. too strong: smallest trim that brings the measures under their limits, without losing expressiveness
        it1 = run('intensity_check.py', src, cur, *gopt)
        over = {k: v for k, v in failing(it1, 'too strong').items() if k in DOWN}
        if over:
            step = {}
            for k in over:
                for pk, pv in DOWN[k].items(): step[pk] = min(step.get(pk, 0), pv)
            weak_before = set(failing(it1, 'too weak'))
            ok = lambda it: not any(k in failing(it, 'too strong') for k in over) and set(failing(it, 'too weak')) <= weak_before   # never trim a measure under its floor
            kept = lambda it: not str(it.get('verdict', '')).startswith('DO_NOT_DELIVER')
            lo, hi, enough = 0.0, 1.0, None
            for _ in range(6):
                m = (lo + hi) / 2; o, it = graded(cur, params_for(step, m), before=cur)
                if o is not None and ok(it): enough, hi = (m, o, it), m
                else: lo = m
            for big in (1.0, 2.0, 3.0):   # v1.0.6: a full step may be too small (2026-11-13: warmth 13.4 against a limit of 6)
                if enough is not None: break
                o, it = graded(cur, params_for(step, big), before=cur)
                if o is not None and ok(it): enough = (big, o, it)
            pick = enough if enough is not None and kept(enough[2]) else None
            if pick is None:   # keep the expressiveness: the largest trim that still keeps it
                lo, hi = 0.0, enough[0] if enough else 1.0
                for _ in range(6):
                    m = (lo + hi) / 2; o, it = graded(cur, params_for(step, m), before=cur)
                    if o is not None and kept(it) and set(failing(it, 'too weak')) <= weak_before: pick, lo = (m, o, it), m
                    else: hi = m
            entry = {'direction': 'down', 'for': sorted(over)}
            if pick is not None and pick[0] > 0.02:
                new_phys = [k for k in serious(src, pick[1]) if k not in base_phys]
                entry.update(params=params_for(step, pick[0]), result=pick[2].get('verdict'))
                if new_phys: entry['undone'] = 'new physics problem: ' + ', '.join(new_phys)
                else: accept(params_for(step, pick[0]))
            else:
                entry['undone'] = 'any trim loses expressiveness: kept as it was'
            rec['steps'].append(entry)

        # 3. anchor into the narrow bands (v1.0.6; v1.0.7: no new out-of-range measure, shadows fallback, --n-direct)
        it3 = run('intensity_check.py', src, cur, *gopt)
        for key, par0, blo, bhi in BANDS.get(it3.get('genre'), []):
            meas = (lambda img, it, key=key: mid_L_change(src, img) if key == 'mid_L_change'
                    else (it.get('checks', {}).get(key) or {}).get('value') if it else None)
            v0 = meas(cur, it3)
            if v0 is None: continue
            edge = blo if (blo is not None and v0 < blo) else bhi if (bhi is not None and v0 > bhi) else None
            # N direct (G not used) has nothing from G to carry it: lift to the middle of the band (never warmth)
            if center and par0 != 'temp' and blo is not None and bhi is not None and v0 < (blo + bhi) / 2:
                edge = (blo + bhi) / 2
            if edge is None: continue
            for par in ([par0, 'shadows'] if par0 == 'exposure_ev' else [par0]):   # exposure blocked by sky/highlights -> shadows
                v0 = meas(cur, it3)
                tol = 0.15 if key.endswith('_change') else 0.01
                if v0 is None or abs(v0 - edge) <= tol or (par == 'shadows' and edge < v0): break
                if par == 'shadows' and abs(v0 - edge) <= 3 * tol: break
                up = edge > v0
                bad_before = set(failing(it3, 'too strong')) | set(failing(it3, 'too weak'))
                mk = (lambda x, par=par: {'white_balance': {'temp': round(x, 4)}} if par == 'temp' else {par: round(x, 4)})
                lo_, hi_ = SPAN[par]
                neutral = 1.0 if par == 'saturation' else 0.0
                lo_, hi_ = (neutral, hi_) if up else (lo_, neutral)
                best = None
                for _ in range(7):
                    m = (lo_ + hi_) / 2; o, it = graded(cur, mk(m))
                    if o is None: break
                    v = meas(o, it)
                    if v is None: break
                    breaks = (set(failing(it, 'too strong')) | set(failing(it, 'too weak'))) - bad_before   # never push another measure out of range
                    if breaks:
                        if up: hi_ = m
                        else: lo_ = m
                        continue
                    best = (m, o, v)
                    if v < edge: lo_ = m
                    else: hi_ = m
                if best is None: continue
                entry = {'direction': 'anchor', 'for': [key], 'from': v0, 'band': [blo, bhi], 'params': mk(best[0]), 'to': best[2]}
                new_phys = [k for k in serious(src, best[1]) if k not in base_phys]
                rec['steps'].append(entry)
                if new_phys:
                    entry['undone'] = 'new physics problem: ' + ', '.join(new_phys); break
                accept(mk(best[0])); it3 = run('intensity_check.py', src, cur, *gopt)

        shutil.copy(cur_full, out)
        itf = run('intensity_check.py', src_full, out, *gopt)
        rec['final'] = itf.get('verdict')
        rec['physics_problems'] = serious(src_full, out)
        rec['grade_calls'] = n[0]
    t = json.dumps(rec, ensure_ascii=False, indent=1)
    if rec_p: Path(rec_p).write_text(t, encoding='utf-8')
    print(t); return 0


if __name__ == '__main__':
    raise SystemExit(main())
