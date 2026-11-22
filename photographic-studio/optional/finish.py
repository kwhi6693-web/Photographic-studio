#!/usr/bin/env python3
"""Photographic Studio v1.4.0 - finish: run the default N chain and retry safer settings by itself, so one good photo comes out.
Usage: python3 finish.py SOURCE G_OUTPUT GRADE_JSON OUT_PNG [RECEIPT_JSON] [--genre=museum|night] [--no-g]
  SOURCE      original photo;  G_OUTPUT  the host's generative edit
  --no-g      v1.2.0: no G for this photo (the brief says every move can be done by N): only the N attempts run, with
              the brief's own parameters first. Passing the SOURCE as G_OUTPUT means the same.
  GRADE_JSON  director-brief parameters for grade.py ({} for none)
Chain: look_transfer -> grade -> physics_check + intensity_check. An attempt passes only when the physics check finds
no problem AND nothing is over a strength limit (v1.0.9: a strength floor is not a failure - the photo's own
parameters decide how light the edit is). Otherwise it retries, in order: (1) with --genre=museum, only when the
default attempt's sole problem is that nobody can see the change, the same grade raised to museum strength (level 3),
(2) the grade without positive region lifts, its vignette halved (v1.2.7: removed only if a darkening patch remains), (3) look_transfer --local=0, (4) N direct: the
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
v1.2.7: the automatic base adjustment (grade.py "auto": white balance from the greys, whole-frame veil, black and
white point and contrast from this photo's own tones, a little vibrance) runs on every attempt unless the brief says
"auto": false. On the G route it runs on the G-toned image, so what G already did is not done twice, and its white
balance runs at half strength (G's colour is part of the look). The user, 2026-11-20: auto tone, contrast and colour
were missing; the photo's expressiveness must come out.
v1.2.5: a G attempt whose only physics problems are local wrong light (a lamp put out, a darkening patch, a halo or
spotlight glow) is first repaired in place by harmonize.py --light-only; G is dropped only when the repair does not pass.
v1.4.0 (2026-11-22 courtyard/arcade receipts): an over-coloured G no longer skips the improvement check. An attempt
that is over a strength limit is first settled (settle.py, which only trims the excess - colour by zoned compression)
and improve_check.py then ALWAYS runs on the settled attempt: the moves, then four hard gates (subject separation
>= +3.5 L*, global light/shade separation >= 1.05x directional / 1.0x diffuse, black anchor -3.5..+1.5 L*, colour
order) and a texture check. When a light gate fails the remedy raises the key light (strength up to 1.2) and the
black anchor / a gentle S-curve - never clarity - and each step reruns the physics checks (tone order, halo, darkening
patch, ghost edges, sky glow) and the keep regions; any red line stops it and the step is undone.
Defaults added unless the brief sets them: "anchor": true, "split_tone": true (not museum), "texture": 0.24 minus
the brief's clarity (0.2 on a small photo).
Deterministic. Needs numpy, Pillow (OpenCV optional: cvlite).
"""
import json, sys, tempfile, shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
PHYS_SERIOUS = ('spotlight_glow', 'darkening_patch', 'tone_order', 'halo', 'light_shade_sep', 'lamps_kept', 'ghost_edges', 'sky_glow')
LIGHT_REPAIRABLE = {'spotlight_glow', 'darkening_patch', 'halo', 'lamps_kept'}   # v1.2.5: harmonize.py --light-only can fix these locally


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
    """v1.0.9: clarity minus what G already added (G +25 % local contrast or more -> no clarity).
    v1.2.7: the same for the automatic contrast: G's added contrast and auto's S-curve do not stack.
    v1.4.0: the same for the texture micro-contrast."""
    c = float(params.get('clarity', 0) or 0)
    if gain <= 1.0: return params, None
    k = max(0.0, 1.0 - (gain - 1.0) / 0.25)
    q = json.loads(json.dumps(params)); info = {'g_local_contrast_gain': round(gain, 3)}
    if c > 0: q['clarity'] = round(c * k, 3); info['clarity'] = [c, q['clarity']]
    tx = q.get('texture')
    if isinstance(tx, (int, float)) and not isinstance(tx, bool) and tx > 0: q['texture'] = round(float(tx) * k, 3); info['texture'] = [tx, q['texture']]
    if isinstance(q.get('auto'), dict):
        ac = float(q['auto'].get('contrast', 1)); q['auto']['contrast'] = round(ac * k, 3); info['auto_contrast'] = [ac, q['auto']['contrast']]
    return (q, info) if len(info) > 1 else (params, None)


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
        kk = min(k, 1.25) if mv.get('subdue') else k   # v1.2.6: a distraction is quieted in small steps (no grey patch)
        for key, (lo, hi) in MOVE_LIMITS.items():
            if key in mv: mv[key] = round(min(hi, max(lo, float(mv[key]) * kk)), 3)
        if 'sat' in mv: mv['sat'] = round(min(1.6, max(0.5, 1 + (float(mv['sat']) - 1) * kk)), 3)
        if q.get('_lowres') and float(mv.get('clarity', 0) or 0) > LOWRES_CLARITY: mv['clarity'] = LOWRES_CLARITY
    return q


def render(lt, params, pj, out, src, kj):
    """v1.2.3: grade, then protect the keep regions, then the moves. The keep regions undo what the look transfer and
    the global grade did there (colour spill, G's repaint); the improvement moves come after, so a move on a protected
    sign (2026-11-19 cafe: logo contrast move under a 'content' keep box, measured x1.00) is not undone by its own
    protection. Returns the keep_regions receipt or None."""
    if not params.get('keep') or not params.get('moves'):
        run('grade.py', lt, out, pj)
        if not Path(out).exists(): shutil.copy(lt, out)
        return run('keep_regions.py', src, out, out, kj) if params.get('keep') else None
    base = {k: v for k, v in params.items() if k != 'moves'}
    bj, bo = Path(str(pj) + '.base.json'), Path(str(out) + '.base.png')
    mj = Path(str(pj) + '.moves.json')
    bj.write_text(json.dumps(base), encoding='utf-8'); mj.write_text(json.dumps({'moves': params['moves']}), encoding='utf-8')
    run('grade.py', lt, bo, bj)
    if not bo.exists(): shutil.copy(lt, bo)
    kept = run('keep_regions.py', src, bo, bo, kj)
    run('grade.py', bo, out, mj)
    if not Path(out).exists(): shutil.copy(bo, out)
    return kept


def safer(params, drop_vignette=False):
    q = json.loads(json.dumps(params))
    for mv in q.get('moves', []):   # v1.2.0: a move is the point of the edit - kept, its added light halved
        if float(mv.get('lift', 0)) > 0: mv['lift'] = round(float(mv['lift']) / 2, 3)
    # v1.2.7 (user 2026-11-20): the vignette guides the eye - halved (at least 1.5), not removed; it goes only when a
    #   safer attempt with it still shows a darkening patch (the one physics problem a vignette can cause)
    vg = q.get('vignette')
    if drop_vignette: q.pop('vignette', None)
    elif isinstance(vg, dict) and float(vg.get('amount', 0) or 0) > 0:
        vg['amount'] = round(max(1.5, float(vg['amount']) / 2), 3) if float(vg['amount']) > 1.5 else float(vg['amount'])
    kl = q.get('key_light')   # v1.3.0: the key light stays (it is the photo's light), at half strength
    if isinstance(kl, dict): kl['strength'] = round(max(0.5, float(kl.get('strength', 1.0)) / 2), 3)
    tx = q.get('texture')   # v1.4.0: half the texture on a safer attempt
    if isinstance(tx, (int, float)) and not isinstance(tx, bool) and tx > 0: q['texture'] = round(float(tx) / 2, 3)
    regs = [r for r in q.get('regions', []) if float(r.get('lift', 0)) <= 0]
    if regs: q['regions'] = regs
    else: q.pop('regions', None)
    return q


GATE_LIGHT = ('subject_separation', 'global_separation', 'black_anchor')


def shortfall(g):
    """v1.4.0: how far the light gates are from passing (0 = all pass), so a remedy step is kept only if it helps."""
    if not g: return 9.0
    s = 0.0
    ss = g.get('subject_separation') or {}
    if ss.get('ok') is False: s += max(0.0, ss['min'] - ss['gain_L']) / 3.5
    gs = g.get('global_separation') or {}
    if gs.get('ok') is False: s += max(0.0, gs['min'] - gs['ratio']) / 0.1
    ba = g.get('black_anchor') or {}
    if ba.get('ok') is False:
        v = ba['fixed_dark_L_change']; s += max(0.0, v - ba['band'][1], ba['band'][0] - v) / 2.0
    return s


def remedy(params, gate):
    """v1.4.0: one step of the gate remedy - more key light (up to 1.2), a firmer black anchor and a gentle S-curve.
    Never clarity. A black anchor that went under -3.5 is eased instead."""
    q = json.loads(json.dumps(params)); did = {}
    fd = ((gate or {}).get('black_anchor') or {}).get('fixed_dark_L_change')
    if fd is not None and fd < -3.5:
        if q.get('anchor') is not False: q['anchor'] = {'target': -2.0}; did['anchor'] = -2.0
        return q, did
    kl = q.get('key_light')
    if isinstance(kl, dict) and kl.get('box'):
        s0 = float(kl.get('strength', 1.0)); kl['strength'] = round(min(1.2, max(s0, 1.0) + 0.1), 3); did['key_light_strength'] = [s0, kl['strength']]
    if q.get('anchor') is not False:
        an = q.get('anchor'); t0 = float(an.get('target', -2.5)) if isinstance(an, dict) else -2.5
        q['anchor'] = {'target': max(-3.0, t0 - 0.25)}; did['anchor_target'] = q['anchor']['target']
    c0 = float(q.get('contrast', 0) or 0); q['contrast'] = round(min(c0 + 0.04, max(c0, 0.12)), 3); did['contrast'] = [c0, q['contrast']]
    return q, did


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
    if 'auto' not in params:   # v1.2.7: on by default; the brief can switch it off with "auto": false
        params['auto'] = True
    if params['auto']: params['auto_ref'] = str(Path(src).resolve())   # the original decides what auto may correct
    if params['auto'] and genre == 'museum':
        # museum colour comes from the user's level-3 strength (MUSEUM_L3), which is the rescue for an edit nobody can
        #   see; auto's vibrance alone made a weak edit just visible and so blocked that rescue (2026-11-20 bronze ox:
        #   subject colour x1.26 instead of the level-3 result). No auto vibrance on museum photos.
        base_auto = params['auto'] if isinstance(params['auto'], dict) else {k: 1 for k in ('wb', 'dehaze', 'levels', 'contrast', 'vibrance')}
        params['auto'] = {**base_auto, 'vibrance': 0}
    # v1.2.7 on the G route G sets the look: no auto vibrance on top of G's colour, and the tones are opened up only for
    #   an original that asks for it (flat or veiled, tone_needs). On a normal photo a black/white point measured on
    #   the G-toned image would just undo what G did (2026-11-20, c1_05: G's dimmed lamps stretched back up, colour and
    #   warmth over their limits).
    if str(HERE) not in sys.path: sys.path.insert(0, str(HERE))
    from ps_common import load_rgb as _lr, srgb_to_lab as _sl, tone_needs as _tn
    _open = _tn(_sl(_lr(src))[..., 0])['stretch_ok']
    G_AUTO = {'wb': 0.5, 'dehaze': 1, 'levels': 1 if _open else 0, 'contrast': 1 if _open else 0, 'vibrance': 0}
    # v1.4.0 defaults: black anchor, warm/cool split, structure texture (the brief can switch each off with false)
    params.setdefault('anchor', {'target': 0.0} if genre == 'night' else True)   # night: only kept from rising
    if genre not in ('museum', 'night'): params.setdefault('split_tone', True)
    if 'texture' not in params:
        params['texture'] = round(max(0.0, (0.2 if lowres else 0.24) - float(params.get('clarity', 0) or 0)), 3)
    if no_g:   # v1.2.0: its own N route - no look_transfer of the original against itself
        tries = [('n_direct', params, [], None), ('n_direct_safer', safer(params), [], None)]
    else:
        if params['auto'] is True: params['auto'] = G_AUTO   # G's own colour is part of the look
        elif isinstance(params['auto'], dict): params['auto'] = {**params['auto'], **{k: min(float(params['auto'].get(k, 1)), v) for k, v in G_AUTO.items()}}
        tries = [('default', params, [], g)]
        if genre == 'museum': tries.append(('museum_strength', boost(params), [], g))
        tries += [('no_region_lift_no_vignette', safer(params), [], g), ('local0_safer_grade', safer(params), ['--local=0'], g),
                  ('n_direct', {**safer(params), 'auto': ({**params['auto'], 'wb': 1} if isinstance(params['auto'], dict) else params['auto'])}, [], None)]
    if genre == 'museum': tries.append(('n_direct_museum_strength', boost(safer(params)), [], None))
    if lowres:   # the museum-strength step raises clarity again: cap every attempt
        tries = [(nm, lowres_cap(pp, short_edge)[0], lo, gs) for nm, pp, lo, gs in tries]
    rec = {'tool': 'finish.py v1.4.0', 'genre': genre, 'route': 'no_g' if no_g else 'g', 'attempts': []}
    if lowres: rec['low_resolution'] = lowres
    if not params.get('moves'): rec['brief'] = 'NO_MOVES: v1.2.0 needs at least one improvement move per photo'
    elif not (params.get('key_light') or {}).get('box'):
        rec['brief'] = 'NO_KEY_LIGHT: v1.3.0 asks for one key_light per photo (where the subject is, where the light comes from)'

    best = None
    with tempfile.TemporaryDirectory() as td:
        td = Path(td); seen = set(); result = {}; remedy_used = [False]
        for i, (name, p, ltopt, gsrc) in enumerate(tries):
            if name.endswith('museum_strength'):
                # v1.0.9: museum strength is only a rescue for an edit nobody can see. A stronger grade cannot fix a
                # physics problem or an excess, so it is not tried for those (it was a floor-lift before v1.0.9).
                base = result.get('n_direct' if name.startswith('n_direct') else 'default')
                if base != ([], ['no_visible_change']): continue
            if gsrc is None and best is not None and best[0][0] == 0 and best[0][1] == 0:
                continue   # a clean, visible G attempt already exists: an N-direct attempt cannot outrank it (score order)
            if name in ('local0_safer_grade', 'n_direct') and p.get('vignette') and any(
                    'darkening_patch' in (result.get(nm) or ([], []))[0] for nm in ('no_region_lift_no_vignette', 'local0_safer_grade')):
                p = {k: v for k, v in p.items() if k != 'vignette'}   # v1.2.7: the halved vignette still made a dark patch
            key = json.dumps([p, ltopt, gsrc is None], sort_keys=True)
            if key in seen: continue
            seen.add(key)
            lt = td / f'lt{i}.png'; fin = td / f'fin{i}.png'; pj = td / f'p{i}.json'
            pj.write_text(json.dumps(p), encoding='utf-8')
            gc = None if gsrc is None else rec.get('g_chroma')   # v1.2.2: G's own colour raises the colour limit on the G route
            if gsrc is None:
                shutil.copy(src, lt); r1 = {'flags': ['N direct: G not used']}
            else:
                r1 = run('look_transfer.py', src, gsrc, lt, *ltopt, *(['--night'] if genre == 'night' else []))
                gcm = ((r1.get('measurements') or {}).get('chroma_ratio') or {}).get('G')
                if gcm and 'g_chroma' not in rec: rec['g_chroma'] = gcm   # v1.2.2: pass to settle.py as --g-chroma
                gc = rec.get('g_chroma')
            if not lt.exists():
                rec['attempts'].append({'name': name, 'result': r1.get('verdict')}); continue
            unstacked = None
            if gsrc is not None:
                p, unstacked = unstack(p, local_contrast_gain(src, lt))
                pj.write_text(json.dumps(p), encoding='utf-8')
            kj = td / f'k{i}.json'
            if p.get('keep'): kj.write_text(json.dumps({'keep': p['keep']}), encoding='utf-8')   # v1.1.0, before anything is judged
            kept = render(lt, p, pj, fin, src, kj)
            bad, weak, iv, pv = problems(src, fin, genre, gc)
            if gsrc is not None and ((r1.get('measurements') or {}).get('sky_kept_to_smooth_gradient')):
                # v1.2.8: smoothing G's sky must not be what lets a G through. Whether G is usable is judged as in
                #   v1.2.7, on the same attempt without the sky smoothing (2026-11-21, photo 03: with the sky smoothed,
                #   a G that v1.2.7 rightly refused passed and left a white patch on the water)
                lt_n, fin_n = td / f'lt{i}n.png', td / f'fin{i}n.png'
                run('look_transfer.py', src, gsrc, lt_n, *ltopt, '--no-sky-trend', *(['--night'] if genre == 'night' else []))
                if lt_n.exists():
                    render(lt_n, p, pj, fin_n, src, kj)
                    if fin_n.exists():
                        b_n = problems(src, fin_n, genre, gc)[0]
                        # v1.3.0: not sky_glow - the unsmoothed run carries G's raw sky on purpose, and the smoothing is
                        #   exactly what keeps G's sky light out of the photo (real_g b2_08 / b2_10)
                        extra = [k for k in b_n if k not in bad and k != 'sky_glow']
                        if extra: bad = bad + extra; r1.setdefault('flags', []).append('judged without sky smoothing: ' + ', '.join(extra))
            light_fix = None
            if gsrc is not None and bad and set(bad) <= LIGHT_REPAIRABLE:
                # v1.2.5: wrong light in one place (a lamp put out, a glow invented) is repaired there, on the
                #   low-frequency layer, instead of throwing the whole G look away; G is dropped only if that fails
                fin_r = td / f'fin{i}r.png'
                hz = run('harmonize.py', src, fin, fin_r, '--light-only', *([f'--genre={genre}'] if genre else []))
                if not fin_r.exists() or str(hz.get('verdict', '')).startswith('REGEN_G'):
                    light_fix = {'was': bad, 'action': (hz.get('light') or {}).get('action') or str(hz.get('verdict'))[:120], 'left': bad}
                else:
                    b2, w2, _iv, _pv = problems(src, fin_r, genre, gc)
                    light_fix = {'was': bad, 'action': (hz.get('light') or {}).get('action'), 'left': b2}
                    if not b2:
                        fin, bad, weak, iv, pv = fin_r, b2, w2, _iv, _pv
            sky_fix = None
            if bad == ['sky_glow'] and p.get('moves'):
                # v1.3.0: light spilled onto a plain sky comes from a move whose area covers the sky (the key light never
                #   touches it): a local lift goes on structure, a band gets a softer edge - the same repair as a halo
                p2 = json.loads(json.dumps(p)); idx = []
                for k, mv in enumerate(p2['moves']):
                    if float(mv.get('lift', 0) or 0) > 0 or mv.get('look') == 'light+':   # a glow is added light
                        if full_span(mv): mv['feather'] = max(0.3, float(mv.get('feather', 0.08)))
                        else: mv['on_structure'] = True
                        idx.append(k)
                if idx:
                    pj2 = td / f'p{i}g.json'; fin2 = td / f'fin{i}g.png'; pj2.write_text(json.dumps(p2), encoding='utf-8')
                    render(lt, p2, pj2, fin2, src, kj)
                    b2, w2, _iv, _pv = problems(src, fin2, genre, gc) if fin2.exists() else (['sky_glow'], [], None, None)
                    sky_fix = {'moves_on_structure': idx, **({'left': b2} if b2 else {})}
                    if not b2:
                        p, pj, fin, bad, weak, iv, pv = p2, pj2, fin2, b2, w2, _iv, _pv
            if any(f.startswith('G_GLOW_LEFT') for f in r1.get('flags', [])): bad.append('invented_glow_left')   # v1.0.2
            settled = None

            def judge(f_in, tag):
                """v1.4.0: settle an attempt that is over a strength limit (trim only), then judge it."""
                b_, w_, iv_, pv_ = problems(src, f_in, genre, gc)
                if not (set(w_) - {'no_visible_change'}): return f_in, b_, w_, iv_, pv_, None
                f_s = td / f'{tag}_settled.png'
                sr = run('settle.py', src, f_in, f_s, *([f'--genre={genre}'] if genre == 'museum' else []), *([f'--g-chroma={gc}'] if gc else []))
                if not f_s.exists(): return f_in, b_, w_, iv_, pv_, {'error': str(sr.get('verdict'))[:120]}
                b2_, w2_, iv2_, pv2_ = problems(src, f_s, genre, gc)
                if len(b2_) > len(b_): return f_in, b_, w_, iv_, pv_, {'undone': 'new physics problem: ' + ', '.join(b2_)}
                return f_s, b2_, w2_, iv2_, pv2_, {'was': [k for k in w_ if k != 'no_visible_change'], 'left': [k for k in w2_ if k != 'no_visible_change']}
            if not bad and set(weak) - {'no_visible_change'}:
                fin, bad, weak, iv, pv, settled = judge(fin, f'a{i}')
            ic = None
            only_subdue = bool(set(weak) - {'no_visible_change'})   # v1.2.6: over a range - only distractions may still be quieted
            allowed = set(weak) if only_subdue else set()   # v1.4.0: fixed for the whole loop (it was replaced mid-loop)
            if p.get('moves') and not bad and (not only_subdue or any(mv.get('subdue') for mv in p['moves'])):   # an invisible edit is exactly what to strengthen
                # v1.2.0: the improvement must show. Strengthen only the moves nobody can see, while nothing breaks.
                ic = run('improve_check.py', src, fin, pj, f'--base={lt}'); rounds = []
                if ic.get('halo'):   # a ring of light or colour: a local move goes on structure, a band gets a softer edge
                    p2 = json.loads(json.dumps(p))
                    for k in ic['halo']:
                        if full_span(p2['moves'][k]): p2['moves'][k]['feather'] = max(0.3, float(p2['moves'][k].get('feather', 0.08)))
                        else: p2['moves'][k]['on_structure'] = True
                    pj2 = td / f'p{i}h.json'; fin2 = td / f'fin{i}h.png'; pj2.write_text(json.dumps(p2), encoding='utf-8')
                    render(lt, p2, pj2, fin2, src, kj)
                    fin2, b2, w2, _iv, _pv, _s = judge(fin2, f'a{i}h')
                    rounds.append({'halo_fix': ic['halo'], **({'stopped_by': b2 + w2} if (b2 or w2) else {})})
                    if not (b2 or set(w2) - {'no_visible_change'}):
                        p, pj, fin, iv, pv, weak = p2, pj2, fin2, _iv, _pv, w2
                        ic = run('improve_check.py', src, fin, pj, f'--base={lt}')
                for rnd in range(3):   # v1.2.1: up to the target, not just over the floor
                    todo = ic.get('below_target', ic.get('weak')) or []
                    if only_subdue: todo = [j for j in todo if p['moves'][j].get('subdue')]
                    if not todo: break
                    p2 = strengthen(p, todo, 1.4); pj2 = td / f'p{i}s{rnd}.json'; fin2 = td / f'fin{i}s{rnd}.png'
                    pj2.write_text(json.dumps(p2), encoding='utf-8'); render(lt, p2, pj2, fin2, src, kj)
                    if not fin2.exists(): break
                    fin2, b2, w2, _iv, _pv, _s = judge(fin2, f'a{i}s{rnd}')
                    if b2 or (set(w2) - {'no_visible_change'}) - allowed:
                        rounds.append({'round': rnd + 1, 'stopped_by': b2 + w2}); break
                    p, pj, fin, iv, pv, weak = p2, pj2, fin2, _iv, _pv, w2
                    ic = run('improve_check.py', src, fin, pj, f'--base={lt}'); rounds.append({'round': rnd + 1, 'verdict': ic.get('verdict')})
                if ic.get('halo') and not only_subdue:
                    # v1.4.0: a halo that only shows once a move was strengthened (the first check now runs on the
                    #   settled attempt) gets the same fix: a local move on structure, a band a softer edge
                    p2 = json.loads(json.dumps(p))
                    for k in ic['halo']:
                        if full_span(p2['moves'][k]): p2['moves'][k]['feather'] = max(0.3, float(p2['moves'][k].get('feather', 0.08)))
                        else: p2['moves'][k]['on_structure'] = True
                    pj2 = td / f'p{i}h2.json'; fin2 = td / f'fin{i}h2.png'; pj2.write_text(json.dumps(p2), encoding='utf-8')
                    render(lt, p2, pj2, fin2, src, kj)
                    fin2, b2, w2, _iv, _pv, _s = judge(fin2, f'a{i}h2')
                    if not (b2 or set(w2) - {'no_visible_change'} - allowed):
                        ic2 = run('improve_check.py', src, fin2, pj2, f'--base={lt}')
                        rounds.append({'halo_fix_after_strengthening': ic['halo'], 'verdict': ic2.get('verdict')})
                        if not ic2.get('halo'):
                            p, pj, fin, iv, pv, weak, ic = p2, pj2, fin2, _iv, _pv, w2, ic2
                    else:
                        rounds.append({'halo_fix_after_strengthening': ic['halo'], 'stopped_by': b2 + w2})
                if ic.get('weak'): weak = weak + ['move_not_visible']
                if ic.get('halo') and not only_subdue: bad = bad + ['move_halo']
                ic = {'verdict': ic.get('verdict'), 'moves': ic.get('moves'), 'strengthened': rounds}
            # v1.4.0: the four hard gates, always, on the settled attempt; a failed light gate gets the remedy
            gate, gate_rounds = None, []
            if not bad:
                gate = run('improve_check.py', src, fin, pj, '--gates', *([f'--genre={genre}'] if genre else [])).get('gates')
                # the remedy runs once per photo, on the first attempt that passes the physics checks (the later rungs of
                #   the ladder are safer variants of it; harmonize.py's floors still apply to whatever is delivered)
                for rnd in range(0 if remedy_used[0] else 2):
                    remedy_used[0] = True
                    if not gate or not (set(gate.get('failed', [])) & set(GATE_LIGHT)): break
                    p2, did = remedy(p, gate)
                    if not did: break
                    pj2 = td / f'p{i}r{rnd}.json'; fin2 = td / f'fin{i}r{rnd}.png'
                    pj2.write_text(json.dumps(p2), encoding='utf-8'); render(lt, p2, pj2, fin2, src, kj)
                    if not fin2.exists(): break
                    fin2, b2, w2, _iv, _pv, _s = judge(fin2, f'a{i}r{rnd}')
                    if b2:   # a red line (light order, halo, darkening patch, ghost edges, sky glow): undo and stop
                        gate_rounds.append({'round': rnd + 1, 'did': did, 'stopped_by': b2}); break
                    g2 = run('improve_check.py', src, fin2, pj2, '--gates', *([f'--genre={genre}'] if genre else [])).get('gates')
                    better = g2 is not None and len(g2.get('failed', [])) <= len(gate.get('failed', [])) and \
                        shortfall(g2) < shortfall(gate) - 0.02   # kept only when it actually moved the light gates
                    gate_rounds.append({'round': rnd + 1, 'did': did, 'gates': (g2 or {}).get('verdict'), 'kept': bool(better)})
                    if not better: break
                    p, pj, fin, iv, pv, weak, gate = p2, pj2, fin2, _iv, _pv, w2 + [x for x in weak if x == 'move_not_visible'], g2
            gfail = ['gate:' + x for x in (gate or {}).get('failed', [])]
            rec['attempts'].append({'name': name, 'look_transfer_flags': r1.get('flags', []), 'physics': pv, 'intensity': iv, 'problems': bad, 'strength_problems': weak,
                                    **({'light_repair': light_fix} if light_fix else {}),
                                    **({'sky_glow_fix': sky_fix} if sky_fix else {}),
                                    **({'clarity_unstacked': unstacked} if unstacked else {}),
                                    **({'keep': kept.get('verdict')} if kept else {}),
                                    **({'settled_before_check': settled} if settled else {}),
                                    **({'gates': gate, 'gates_failed': gfail} if gate else {}), **({'gate_remedy': gate_rounds} if gate_rounds else {}),
                                    **({'improve': ic, 'params': p} if ic else {})})
            result[name] = (bad, weak)
            # v1.0.2: a G route that passes the physics checks and visibly changes the photo beats N direct whatever the
            #   strength ranges say: ranges trim the excess afterwards (step 6), they are not a reason to drop G's look.
            #   (2026-11-13 batch: four of five photos lost G this way and came out nearly unchanged; the user
            #   preferred the G route on all four.)
            score = (len(bad), 0 if (gsrc is not None and 'no_visible_change' not in weak) else 1, len(weak) + len(gfail), i)
            if best is None or score < best[0]: best = (score, fin, name, bad + weak + gfail)
            if not bad and (not weak or weak == ['move_not_visible']): break   # a safer attempt cannot show more (gates neither)
        shutil.copy(best[1], out)
    rec['delivered'] = best[2]
    dg = next((x.get('gates') for x in rec['attempts'] if x['name'] == best[2] and x.get('gates')), None)
    if dg: rec['gates'] = dg
    rec['verdict'] = 'DELIVER' if not best[3] else 'DELIVER_WITH_FLAGS: ' + ', '.join(best[3])
    t = json.dumps(rec, ensure_ascii=False, indent=1)
    if rec_p: Path(rec_p).write_text(t, encoding='utf-8')
    print(t); return 0


if __name__ == '__main__':
    raise SystemExit(main())
