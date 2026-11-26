#!/usr/bin/env python3
"""Photographic Studio v2.4.0 (package v1.4.0) - settle: step 6 safety trim in one call.
Usage: python3 -I settle.py ORIGINAL FINISHED OUT_PNG [RECEIPT_JSON] [--genre=museum] [--g-chroma=X]
  ORIGINAL   the original photo;  FINISHED  the image finish.py delivered (or any later version)
  --g-chroma=X  v1.2.2: the finish.py receipt's "g_chroma" on the G route: the colour limit becomes G's own colour (max x1.65)
It ONLY removes what is over a limit (v1.0.9, user 2026-11-14 "每张照片都有最适合它的参数"): the smallest amount that
brings each measure back under its limit, never more; if that would lose expressiveness (intensity_check.py --before
says DO_NOT_DELIVER), only as much as keeps it, and the rest stays as a flag. Each candidate is a grade.py pass on
FINISHED with one scaled parameter set (bisection, about 6 tries). It never touches what is in range and never stops to ask.
v2.3.0 (v1.2.7, user 2026-11-20): the unused floor lift and band anchoring (--bands, --n-direct, from v1.0.6) are
removed; the default behaviour is unchanged. --bands and --n-direct are accepted and ignored.
v1.4.0 (2026-11-22 arcade: a global saturation 0.75 took 40.2 % of the colour off the sunlit surfaces): colour over
its limit is brought down by grade.py "chroma_compress" - only the over-saturated top of the chroma (above this image's
own upper chroma) is compressed, so the mid and low saturations and the lit surfaces keep their colour. The 1.65x
ceiling is unchanged. The same for warmth over its limit: a b* shift on the lit tones only (grade.py tone_split
highlights), not a global white-balance shift - on b1_01 a global temp -0.7 drained the lanterns' colour.
Deterministic. Needs numpy, Pillow (and what grade.py, intensity_check.py, physics_check.py need).
"""
import json, shutil, sys, tempfile
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
SEARCH_EDGE = 640   # v2.1.0: long edge of the copies the parameter search runs on
PHYS_SERIOUS = ('spotlight_glow', 'darkening_patch', 'tone_order', 'halo', 'light_shade_sep', 'ghost_edges', 'sky_glow')
# full step for each measure; the tool uses the smallest fraction of it that is enough
DOWN = {'L_mean_change': {'exposure_ev': -0.3}, 'subject_L_change': {'exposure_ev': -0.3}, 'background_L_change': {'shadows': -6},
        'chroma_ratio': {'chroma_compress': 1.0}, 'subject_chroma_ratio': {'chroma_compress': 1.0},   # v1.4.0: zoned, not global
        'lit_warmth_change': {'tone_split.highlights_b': -4.0},   # v1.4.0: only the lit tones, not a global white balance
        'highlight_p99_change': {'highlights': -10},
        'sky_L_change': {'sky_lift': -8}}


def run(tool, *args):
    if str(HERE) not in sys.path: sys.path.insert(0, str(HERE))
    from ps_common import run_tool
    return run_tool(tool, *args)


def params_for(step, t):
    p = {}
    for k, v in step.items():
        if k == 'saturation': p['saturation'] = round(1 + v * t, 4)
        elif k == 'white_balance.temp': p['white_balance'] = {'temp': round(v * t, 4)}
        elif k == 'tone_split.highlights_b': p['tone_split'] = {'highlights': [0.0, round(max(-8.0, v * t), 3)]}
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
    gopt = ([f"--genre={opt['genre']}"] if opt.get('genre') else []) + ([f"--g-chroma={opt['g-chroma']}"] if opt.get('g-chroma') else [])
    rec = {'tool': 'settle.py v2.4.0', 'steps': [], 'mode': 'trim_only'}
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

        # too strong: smallest trim that brings the measures under their limits, without losing expressiveness
        it1 = it0
        over = {k: v for k, v in failing(it1, 'too strong').items() if k in DOWN}
        if over:
            step = {}
            for k in over:
                for pk, pv in DOWN[k].items():   # the larger step of the two, whatever its sign (chroma_compress is positive)
                    step[pk] = pv if pk not in step else (max(step[pk], pv) if pv > 0 else min(step[pk], pv))
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
