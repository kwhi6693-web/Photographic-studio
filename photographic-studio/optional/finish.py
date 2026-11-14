#!/usr/bin/env python3
"""Photographic Studio v1.0.2 - finish: run the default N chain and retry safer settings by itself, so one good photo comes out.
Usage: python3 finish.py SOURCE G_OUTPUT GRADE_JSON OUT_PNG [RECEIPT_JSON] [--genre=museum]
  SOURCE      original photo;  G_OUTPUT  the host's generative edit (or the SOURCE itself for N-only)
  GRADE_JSON  director-brief parameters for grade.py ({} for none)
Chain: look_transfer -> grade -> physics_check + intensity_check. An attempt passes only when the physics check finds
no problem AND the strength is in range. Otherwise it retries, in order: (1) with --genre=museum and the subject too
weak, the same grade raised to the user's chosen museum strength (level 3), (2) the grade without positive region
lifts and without vignette, (3) look_transfer --local=0, (4) N direct: the original graded without G, (5) N direct at
museum strength. The first attempt that passes is delivered; if none passes, the one with the fewest physics problems,
then the fewest strength problems, is delivered and its problems are listed (v0.3.8). It never stops to ask.
Deterministic. Needs numpy, Pillow, OpenCV.
"""
import json, subprocess, sys, tempfile, shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
PHYS_SERIOUS = ('spotlight_glow', 'darkening_patch', 'tone_order', 'halo', 'light_shade_sep')


def run(tool, *args):
    if str(HERE) not in sys.path: sys.path.insert(0, str(HERE))
    from ps_common import run_tool
    return run_tool(tool, *args)


MUSEUM_L3 = {'exposure_ev': 0.32, 'contrast': 0.28, 'clarity': 0.40,  # level 3 had 0.55; 0.40 avoids bright rims on bright-on-black edges
             'vibrance': 0.45, 'highlights': -5,
             'hues': {'blue': {'sat': 1.38}, 'green': {'sat': 1.38}, 'cyan': {'sat': 1.38}, 'yellow': {'sat': 1.25}, 'orange': {'sat': 1.25}}}


def boost(params):
    # raise to the user's chosen museum strength, never lower anything the director already asked for
    q = json.loads(json.dumps(params))
    for k in ('exposure_ev', 'contrast', 'clarity', 'vibrance'):
        q[k] = max(float(q.get(k, 0)), MUSEUM_L3[k])
    q['highlights'] = min(float(q.get('highlights', 0)), MUSEUM_L3['highlights'])
    hs = q.setdefault('hues', {})
    for name, v in MUSEUM_L3['hues'].items():
        cur = hs.setdefault(name, {}); cur['sat'] = max(float(cur.get('sat', 1)), v['sat'])
    return q


def safer(params):
    q = json.loads(json.dumps(params))
    q.pop('vignette', None)
    regs = [r for r in q.get('regions', []) if float(r.get('lift', 0)) <= 0]
    if regs: q['regions'] = regs
    else: q.pop('regions', None)
    return q


def problems(src, out, genre):
    ph = run('physics_check.py', src, out)
    bad = [k for k, v in ph.get('checks', {}).items() if k in PHYS_SERIOUS and v.get('ok') is False]
    it = run('intensity_check.py', src, out, *([f'--genre={genre}'] if genre else []))
    weak = [k for k, v in it.get('checks', {}).items() if isinstance(v, dict) and v.get('ok') is False]
    # v1.0: an edit nobody can see is a failure ("改了等于没改"), whatever the ranges say
    import numpy as np
    from PIL import Image
    a = np.asarray(Image.open(src).convert('RGB'), np.float32); b = np.asarray(Image.open(out).convert('RGB').resize((a.shape[1], a.shape[0])), np.float32)
    if float(np.abs(a - b).mean()) < 1.5: weak.append('no_visible_change')
    return bad, weak, it.get('verdict', '?'), ph.get('verdict', '?')


def main():
    a = [x for x in sys.argv[1:] if not x.startswith('--')]
    opt = {x.split('=')[0]: x.split('=')[1] for x in sys.argv[1:] if x.startswith('--') and '=' in x}
    genre = opt.get('--genre')
    if genre == 'still_life': genre = 'museum'
    if len(a) < 4: sys.exit(__doc__)
    src, g, gj, out = a[:4]; rec_p = a[4] if len(a) > 4 else None
    txt = Path(gj).read_text(encoding='utf-8').strip() if Path(gj).exists() else ''
    params = json.loads(txt) if txt else {}   # v1.0: a missing or empty parameter file means no extra grading
    tries = [('default', params, [], g)]
    if genre == 'museum': tries.append(('museum_strength', boost(params), [], g))
    tries += [('no_region_lift_no_vignette', safer(params), [], g), ('local0_safer_grade', safer(params), ['--local=0'], g),
              ('n_direct', safer(params), [], None)]
    if genre == 'museum': tries.append(('n_direct_museum_strength', boost(safer(params)), [], None))
    rec = {'tool': 'finish.py v1.0.2', 'genre': genre, 'attempts': []}
    best = None
    with tempfile.TemporaryDirectory() as td:
        td = Path(td); seen = set()
        for i, (name, p, ltopt, gsrc) in enumerate(tries):
            key = json.dumps([p, ltopt, gsrc is None], sort_keys=True)
            if key in seen: continue
            seen.add(key)
            lt = td / f'lt{i}.png'; fin = td / f'fin{i}.png'; pj = td / f'p{i}.json'
            pj.write_text(json.dumps(p), encoding='utf-8')
            if gsrc is None:
                shutil.copy(src, lt); r1 = {'flags': ['N direct: G not used']}
            else:
                r1 = run('look_transfer.py', src, gsrc, lt, *ltopt)
            if not lt.exists():
                rec['attempts'].append({'name': name, 'result': r1.get('verdict')}); continue
            run('grade.py', lt, fin, pj)
            if not fin.exists(): shutil.copy(lt, fin)
            bad, weak, iv, pv = problems(src, fin, genre)
            if any(f.startswith('G_GLOW_LEFT') for f in r1.get('flags', [])): bad.append('invented_glow_left')   # v1.0.2
            rec['attempts'].append({'name': name, 'look_transfer_flags': r1.get('flags', []), 'physics': pv, 'intensity': iv, 'problems': bad, 'strength_problems': weak})
            # v1.0.2: a G route that passes the physics checks and visibly changes the photo beats N direct whatever the
            #   strength ranges say: ranges trim the excess afterwards (step 6), they are not a reason to drop G's look.
            #   (2026-11-13 batch: four of five photos lost G this way and came out nearly unchanged; the user
            #   preferred the G route on all four.)
            score = (len(bad), 0 if (gsrc is not None and 'no_visible_change' not in weak) else 1, len(weak), i)
            if best is None or score < best[0]: best = (score, fin, name, bad + weak)
            if not bad and not weak: break
        shutil.copy(best[1], out)
    rec['delivered'] = best[2]
    rec['verdict'] = 'DELIVER' if not best[3] else 'DELIVER_WITH_FLAGS: ' + ', '.join(best[3])
    t = json.dumps(rec, ensure_ascii=False, indent=1)
    if rec_p: Path(rec_p).write_text(t, encoding='utf-8')
    print(t); return 0


if __name__ == '__main__':
    raise SystemExit(main())
