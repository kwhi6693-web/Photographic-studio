#!/usr/bin/env python3
"""Photographic Studio v1.1.0 - settle: step 6 strength calibration in one call.
Usage: python3 -I settle.py ORIGINAL FINISHED OUT_PNG [RECEIPT_JSON] [--genre=museum]
  ORIGINAL   the original photo;  FINISHED  the image finish.py delivered (or any later version)
Does what step 6 used to do by hand, round after round:
  1. too weak (intensity_check.py says a floor is not reached): adds the smallest amount of exposure / vibrance /
     clarity that reaches the floor (at most the full step below), and keeps it only if the physics check finds no
     new problem;
  2. too strong (a limit is exceeded): removes the smallest amount that brings the measure back under the limit,
     never more; if that would lose expressiveness (intensity_check.py --before says DO_NOT_DELIVER), it removes only
     as much as keeps the expressiveness, and the rest stays as a flag.
Every candidate is a grade.py pass on FINISHED with one scaled parameter set (bisection, about 6 tries per direction).
It never touches what is in range, never lowers a measure below its limit, and never stops to ask.
Deterministic. Needs numpy, Pillow (and what grade.py, intensity_check.py, physics_check.py need).
"""
import json, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PHYS_SERIOUS = ('spotlight_glow', 'darkening_patch', 'tone_order', 'halo', 'light_shade_sep')
# full step for each measure; the tool uses the smallest fraction of it that is enough
UP = {'L_mean_change': {'exposure_ev': 0.25}, 'chroma_ratio': {'vibrance': 0.35}, 'subject_chroma_ratio': {'vibrance': 0.35},
      'local_contrast_ratio': {'clarity': 0.25}, 'subject_local_contrast_ratio': {'clarity': 0.25},
      'sky_L_change': {'sky_lift': 18}}   # 'too weak' for the sky means it was darkened past the limit
DOWN = {'L_mean_change': {'exposure_ev': -0.3}, 'subject_L_change': {'exposure_ev': -0.3}, 'background_L_change': {'shadows': -6},
        'chroma_ratio': {'saturation': -0.25}, 'subject_chroma_ratio': {'saturation': -0.25},
        'lit_warmth_change': {'white_balance.temp': -0.35}, 'highlight_p99_change': {'highlights': -10},
        'sky_L_change': {'sky_lift': -8}}


def run(tool, *args):
    p = subprocess.run([sys.executable, '-B', str(HERE / tool), *map(str, args)], capture_output=True, text=True)
    try:
        return json.loads(p.stdout)
    except Exception:
        return {'verdict': 'TOOL_ERROR', 'stderr': p.stderr[-400:]}


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
    rec = {'tool': 'settle.py v1.1.0', 'steps': []}
    with tempfile.TemporaryDirectory() as td:
        td = Path(td); n = [0]

        def graded(base, p, before=None):
            n[0] += 1; pj = td / f'p{n[0]}.json'; o = td / f'c{n[0]}.png'
            pj.write_text(json.dumps(p), encoding='utf-8'); run('grade.py', base, o, pj)
            if not o.exists(): return None, None
            return o, run('intensity_check.py', src, o, *gopt, *([f'--before={before}'] if before else []))

        cur = td / 'start.png'; shutil.copy(fin, cur)
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
            cur = td / f'after_up{k_pass}.png'; shutil.copy(best[1], cur)

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
            if enough is None:
                o, it = graded(cur, params_for(step, 1.0), before=cur)
                if o is not None and ok(it): enough = (1.0, o, it)
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
                else: cur = td / 'after_down.png'; shutil.copy(pick[1], cur)
            else:
                entry['undone'] = 'any trim loses expressiveness: kept as it was'
            rec['steps'].append(entry)

        shutil.copy(cur, out)
        itf = run('intensity_check.py', src, out, *gopt)
        rec['final'] = itf.get('verdict')
        rec['physics_problems'] = serious(src, out)
        rec['grade_calls'] = n[0]
    t = json.dumps(rec, ensure_ascii=False, indent=1)
    if rec_p: Path(rec_p).write_text(t, encoding='utf-8')
    print(t); return 0


if __name__ == '__main__':
    raise SystemExit(main())
