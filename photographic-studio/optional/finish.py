#!/usr/bin/env python3
"""Photographic Studio v1.2.2 - finish: run the default N chain and retry safer settings by itself, so one good photo comes out.
Usage: python3 finish.py SOURCE G_OUTPUT GRADE_JSON OUT_PNG [RECEIPT_JSON] [--genre=museum] [--no-g]
  SOURCE      original photo;  G_OUTPUT  the host's generative edit
  --no-g      v1.2.0: no G for this photo (the brief says every move can be done by N): only the N attempts run, with
              the brief's own parameters first. Passing the SOURCE as G_OUTPUT means the same.
  GRADE_JSON  director-brief parameters for grade.py ({} for none)
Chain: look_transfer -> grade -> physics_check + intensity_check. An attempt passes only when the physics check finds
no problem AND nothing is over a strength limit (v1.0.9: a strength floor is not a failure - the photo's own
parameters decide how light the edit is). Otherwise it retries, in order: (1) with --genre=museum, only when the
default attempt's sole problem is that nobody can see the change, the same grade raised to museum strength (level 3),
(2) the grade without positive region lifts and without vignette, (3) look_transfer --local=0, (4) N direct: the
original graded without G, (5) N direct at museum strength (again only when N direct's sole problem is no visible
change). The first attempt that passes is delivered; if none passes, the one with the fewest physics problems,
then the fewest strength problems, is delivered and its problems are listed (v0.3.8). It never stops to ask.
v1.0.9: no stacked clarity - where G's light already raised the local contrast, the grade's clarity is reduced by the
same amount (fully off once G added 25 % or more), so G's local contrast and N's clarity do not stack into hard,
bright rims (the approved blue vase: gold rims with edge gain 0.86).
v1.1.0: GRADE_JSON may carry "keep": the brief's must-not-change regions (keep_regions.py). They are applied to every
attempt right after the grade and BEFORE the checks, so a G whose only fault was repainting a kept region is judged
without it.
v1.2.0 (the user: "修得好" before "别改坏"): GRADE_JSON carries the brief's improvement "moves" (grade.py). An attempt
that passes the checks is then measured by improve_check.py; a move nobody can see is strengthened (x1.5, at most two
rounds) as long as the physics checks still pass and nothing goes over a strength limit. An attempt whose moves stay
invisible counts as weaker than one whose moves show. A brief without moves is reported (NO_MOVES).
v1.2.1: moves are strengthened (x1.4, up to three rounds) until they reach improve_check.py's TARGET (the level of the
finals the user approved), not just its floor. A halo from a band that spans the whole frame (a sky or water band) is
fixed by a wider feather, not by "on structure" (that removed the sunset band's colour altogether); a local move keeps
the on-structure fix. Photos with a short edge under 900 px get clarity at most 0.2 everywhere (local contrast on a
small photo turns into grain: the 2026-11-15 book at clarity 0.4).
v1.2.2: on the G route the colour upper limit is G's own colour (at most x1.65; intensity_check.py --g-chroma), and the
receipt records it as "g_chroma" for settle.py. The user chose this on 2026-11-19 (lake: G x1.61 was trimmed to x1.30).
Deterministic. Needs numpy, Pillow, OpenCV.
"""
import json, sys, tempfile, shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
PHYS_SERIOUS = ('spotlight_glow', 'darkening_patch', 'tone_order', 'halo', 'light_shade_sep', 'lamps_kept')


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


def local_contrast_gain(src, img):
    """Mean local contrast (L*, 8 px scale) of img over that of src."""
    if str(HERE) not in sys.path: sys.path.insert(0, str(HERE))
    from ps_common import load_rgb, srgb_to_lab, blur
    import numpy as np
    from PIL import Image
    o = load_rgb(src); f = load_rgb(img)
    if f.shape != o.shape:
        f = np.asarray(Image.fromarray(np.uint8(np.rint(f * 255))).resize((o.shape[1], o.shape[0]), Image.LANCZOS)).astype(np.float32) / 255
    Lo, Lf = srgb_to_lab(o)[..., 0], srgb_to_lab(f)[..., 0]
    return float(np.abs(Lf - blur(Lf, 8)).mean() / max(np.abs(Lo - blur(Lo, 8)).mean(), 1e-6))


def unstack(params, gain):
    """v1.0.9: clarity minus what G already added (G +25 % local contrast or more -> no clarity)."""
    c = float(params.get('clarity', 0) or 0)
    if c <= 0 or gain <= 1.0: return params, None
    q = json.loads(json.dumps(params)); q['clarity'] = round(c * max(0.0, 1.0 - (gain - 1.0) / 0.25), 3)
    return q, {'g_local_contrast_gain': round(gain, 3), 'clarity': [c, q['clarity']]}


MOVE_LIMITS = {'lift': (-20, 20), 'warm': (-8, 8), 'clarity': (0, 0.5)}
LOWRES_EDGE, LOWRES_CLARITY = 900, 0.2


def lowres_cap(params, short_edge):
    """v1.2.1: clarity at most 0.2 (global and in every move/region) on a photo with a short edge under 900 px."""
    if short_edge >= LOWRES_EDGE: return params, None
    q = json.loads(json.dumps(params)); capped = []
    if float(q.get('clarity', 0) or 0) > LOWRES_CLARITY: capped.append(['clarity', q['clarity']]); q['clarity'] = LOWRES_CLARITY
    for key in ('moves', 'regions'):
        for j, r in enumerate(q.get(key, [])):
            if float(r.get('clarity', 0) or 0) > LOWRES_CLARITY: capped.append([f'{key}[{j}].clarity', r['clarity']]); r['clarity'] = LOWRES_CLARITY
    return q, ({'short_edge': short_edge, 'capped': capped} if capped else None)


def full_span(mv):
    """A band across the whole frame (sky, water): its edges run through smooth areas by design."""
    if mv.get('shape') == 'gradient': return True
    b = mv.get('box') or [0, 0, 1, 1]
    return (b[0] <= 0.02 and b[2] >= 0.98) or (b[1] <= 0.02 and b[3] >= 0.98)


def strengthen(params, idx, k=1.5):
    """v1.2.0: the moves in idx, k times stronger (sat about 1), within grade.py's ranges."""
    q = json.loads(json.dumps(params))
    for i in idx:
        mv = q['moves'][i]
        for key, (lo, hi) in MOVE_LIMITS.items():
            if key in mv: mv[key] = round(min(hi, max(lo, float(mv[key]) * k)), 3)
        if 'sat' in mv: mv['sat'] = round(min(1.6, max(0.5, 1 + (float(mv['sat']) - 1) * k)), 3)
        if q.get('_lowres') and float(mv.get('clarity', 0) or 0) > LOWRES_CLARITY: mv['clarity'] = LOWRES_CLARITY
    return q


def safer(params):
    q = json.loads(json.dumps(params))
    for mv in q.get('moves', []):   # v1.2.0: a move is the point of the edit - kept, its added light halved
        if float(mv.get('lift', 0)) > 0: mv['lift'] = round(float(mv['lift']) / 2, 3)
    q.pop('vignette', None)
    regs = [r for r in q.get('regions', []) if float(r.get('lift', 0)) <= 0]
    if regs: q['regions'] = regs
    else: q.pop('regions', None)
    return q


def problems(src, out, genre, g_chroma=None):
    ph = run('physics_check.py', src, out)
    bad = [k for k, v in ph.get('checks', {}).items() if k in PHYS_SERIOUS and v.get('ok') is False]
    it = run('intensity_check.py', src, out, *([f'--genre={genre}'] if genre else []), *([f'--g-chroma={g_chroma}'] if g_chroma else []))
    # v1.0.9: only an excess counts against an attempt; a light edit the brief chose for this photo is not 'too weak'
    weak = [k for k, v in it.get('checks', {}).items() if isinstance(v, dict) and v.get('ok') is False and v.get('direction') == 'too strong']
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
    from PIL import Image as _Image
    with _Image.open(src) as _im: short_edge = min(_im.size)
    params, lowres = lowres_cap(params, short_edge)
    if lowres: params['_lowres'] = True
    no_g = '--no-g' in sys.argv or Path(g).resolve() == Path(src).resolve()
    if not no_g:
        if str(HERE) not in sys.path: sys.path.insert(0, str(HERE))
        from ps_common import sha256 as _sha
        no_g = _sha(g) == _sha(src)
    if no_g:   # v1.2.0: its own N route - no look_transfer of the original against itself
        tries = [('n_direct', params, [], None), ('n_direct_safer', safer(params), [], None)]
    else:
        tries = [('default', params, [], g)]
        if genre == 'museum': tries.append(('museum_strength', boost(params), [], g))
        tries += [('no_region_lift_no_vignette', safer(params), [], g), ('local0_safer_grade', safer(params), ['--local=0'], g),
                  ('n_direct', safer(params), [], None)]
    if genre == 'museum': tries.append(('n_direct_museum_strength', boost(safer(params)), [], None))
    if lowres:   # the museum-strength step raises clarity again: cap every attempt
        tries = [(nm, lowres_cap(pp, short_edge)[0], lo, gs) for nm, pp, lo, gs in tries]
    rec = {'tool': 'finish.py v1.2.2', 'genre': genre, 'route': 'no_g' if no_g else 'g', 'attempts': []}
    if lowres: rec['low_resolution'] = lowres
    if not params.get('moves'): rec['brief'] = 'NO_MOVES: v1.2.0 needs at least one improvement move per photo'

    best = None
    with tempfile.TemporaryDirectory() as td:
        td = Path(td); seen = set(); result = {}
        for i, (name, p, ltopt, gsrc) in enumerate(tries):
            if name.endswith('museum_strength'):
                # v1.0.9: museum strength is only a rescue for an edit nobody can see. A stronger grade cannot fix a
                # physics problem or an excess, so it is not tried for those (it was a floor-lift before v1.0.9).
                base = result.get('n_direct' if name.startswith('n_direct') else 'default')
                if base != ([], ['no_visible_change']): continue
            key = json.dumps([p, ltopt, gsrc is None], sort_keys=True)
            if key in seen: continue
            seen.add(key)
            lt = td / f'lt{i}.png'; fin = td / f'fin{i}.png'; pj = td / f'p{i}.json'
            pj.write_text(json.dumps(p), encoding='utf-8')
            gc = None if gsrc is None else rec.get('g_chroma')   # v1.2.2: G's own colour raises the colour limit on the G route
            if gsrc is None:
                shutil.copy(src, lt); r1 = {'flags': ['N direct: G not used']}
            else:
                r1 = run('look_transfer.py', src, gsrc, lt, *ltopt)
                gcm = ((r1.get('measurements') or {}).get('chroma_ratio') or {}).get('G')
                if gcm and 'g_chroma' not in rec: rec['g_chroma'] = gcm   # v1.2.2: pass to settle.py as --g-chroma
                gc = rec.get('g_chroma')
            if not lt.exists():
                rec['attempts'].append({'name': name, 'result': r1.get('verdict')}); continue
            unstacked = None
            if gsrc is not None:
                p, unstacked = unstack(p, local_contrast_gain(src, lt))
                pj.write_text(json.dumps(p), encoding='utf-8')
            run('grade.py', lt, fin, pj)
            if not fin.exists(): shutil.copy(lt, fin)
            kept = None
            if p.get('keep'):   # v1.1.0: the brief's must-not-change regions, before anything is judged
                kj = td / f'k{i}.json'; kj.write_text(json.dumps({'keep': p['keep']}), encoding='utf-8')
                kept = run('keep_regions.py', src, fin, fin, kj)
            bad, weak, iv, pv = problems(src, fin, genre, gc)
            if any(f.startswith('G_GLOW_LEFT') for f in r1.get('flags', [])): bad.append('invented_glow_left')   # v1.0.2
            ic = None
            if p.get('moves') and not bad and set(weak) <= {'no_visible_change'}:   # an invisible edit is exactly what to strengthen
                # v1.2.0: the improvement must show. Strengthen only the moves nobody can see, while nothing breaks.
                ic = run('improve_check.py', src, fin, pj, f'--base={lt}'); rounds = []
                if ic.get('halo'):   # a ring of light or colour: a local move goes on structure, a band gets a softer edge
                    p2 = json.loads(json.dumps(p))
                    for k in ic['halo']:
                        if full_span(p2['moves'][k]): p2['moves'][k]['feather'] = max(0.3, float(p2['moves'][k].get('feather', 0.08)))
                        else: p2['moves'][k]['on_structure'] = True
                    pj2 = td / f'p{i}h.json'; fin2 = td / f'fin{i}h.png'; pj2.write_text(json.dumps(p2), encoding='utf-8')
                    run('grade.py', lt, fin2, pj2)
                    if p2.get('keep'): run('keep_regions.py', src, fin2, fin2, kj)
                    b2, w2, _iv, _pv = problems(src, fin2, genre, gc)
                    rounds.append({'halo_fix': ic['halo'], **({'stopped_by': b2 + w2} if (b2 or w2) else {})})
                    if not (b2 or set(w2) - {'no_visible_change'}):
                        p, pj, fin, iv, pv, weak = p2, pj2, fin2, _iv, _pv, w2
                        ic = run('improve_check.py', src, fin, pj, f'--base={lt}')
                for rnd in range(3):   # v1.2.1: up to the target, not just over the floor
                    todo = ic.get('below_target', ic.get('weak')) or []
                    if not todo: break
                    p2 = strengthen(p, todo, 1.4); pj2 = td / f'p{i}s{rnd}.json'; fin2 = td / f'fin{i}s{rnd}.png'
                    pj2.write_text(json.dumps(p2), encoding='utf-8'); run('grade.py', lt, fin2, pj2)
                    if not fin2.exists(): break
                    if p2.get('keep'): run('keep_regions.py', src, fin2, fin2, kj)
                    b2, w2, _iv, _pv = problems(src, fin2, genre, gc)
                    if b2 or set(w2) - {'no_visible_change'}:
                        rounds.append({'round': rnd + 1, 'stopped_by': b2 + w2}); break
                    p, pj, fin, iv, pv, weak = p2, pj2, fin2, _iv, _pv, w2
                    ic = run('improve_check.py', src, fin, pj, f'--base={lt}'); rounds.append({'round': rnd + 1, 'verdict': ic.get('verdict')})
                if ic.get('weak'): weak = weak + ['move_not_visible']
                if ic.get('halo'): bad = bad + ['move_halo']
                ic = {'verdict': ic.get('verdict'), 'moves': ic.get('moves'), 'strengthened': rounds}
            rec['attempts'].append({'name': name, 'look_transfer_flags': r1.get('flags', []), 'physics': pv, 'intensity': iv, 'problems': bad, 'strength_problems': weak,
                                    **({'clarity_unstacked': unstacked} if unstacked else {}),
                                    **({'keep': kept.get('verdict')} if kept else {}),
                                    **({'improve': ic, 'params': p} if ic else {})})
            result[name] = (bad, weak)
            # v1.0.2: a G route that passes the physics checks and visibly changes the photo beats N direct whatever the
            #   strength ranges say: ranges trim the excess afterwards (step 6), they are not a reason to drop G's look.
            #   (2026-11-13 batch: four of five photos lost G this way and came out nearly unchanged; the user
            #   preferred the G route on all four.)
            score = (len(bad), 0 if (gsrc is not None and 'no_visible_change' not in weak) else 1, len(weak), i)
            if best is None or score < best[0]: best = (score, fin, name, bad + weak)
            if not bad and (not weak or weak == ['move_not_visible']): break   # a safer attempt cannot show more
        shutil.copy(best[1], out)
    rec['delivered'] = best[2]
    rec['verdict'] = 'DELIVER' if not best[3] else 'DELIVER_WITH_FLAGS: ' + ', '.join(best[3])
    t = json.dumps(rec, ensure_ascii=False, indent=1)
    if rec_p: Path(rec_p).write_text(t, encoding='utf-8')
    print(t); return 0


if __name__ == '__main__':
    raise SystemExit(main())
