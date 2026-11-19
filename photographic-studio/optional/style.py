#!/usr/bin/env python3
"""Photographic Studio v1.3.0 - personal style library (optional, off by default).

The style is a seasoning, not a different dish: after the director's brief has set this photo's own parameters, the
style pushes the global ones a little towards the user's taste. Moves, keep regions and every check stay as they are.

Usage:
  python3 -I style.py build OUT_PROFILE.json --pairs ORIG1 FINAL1 [ORIG2 FINAL2 ...] [--genre=night]
  python3 -I style.py build OUT_PROFILE.json --finals F1 F2 F3 ... [--genre=night]
  python3 -I style.py apply PARAMS.json PROFILE.json OUT_PARAMS.json [--genre=museum]
  python3 -I style.py feedback PROFILE.json --param=warm --dir=-1 --words="太暖了" [--genre=night] [--date=YYYY-MM-DD]
  python3 -I style.py show PROFILE.json
  python3 -I style.py words PROFILE.json [--genre=night]

build    3-10 samples. --pairs (an original and the user's own finished version) measures the edit itself and is the
         more reliable source; --finals (liked photos only) compares them with an ordinary phone photo (BASELINE).
         Samples are measured, never stored; the profile holds numbers only.
apply    writes the brief's parameters with the style pushed in, plus a "style" record of what changed.
feedback one sentence the user said after a delivery ("太暖了"), as a direction on one tendency: a small step, and
         more confidence each time the same direction comes back.
words    the one-line description for the G prompt (no numbers).

Tendencies (each an offset in grade.py parameter units, with a confidence 0..1):
  warm      -> white_balance.temp      colour    -> vibrance
  contrast  -> contrast                depth     -> shadows (negative = deeper darks)
  clarity   -> clarity (a positive push only adds; a negative one only takes away the brief's own)
"""
import datetime, json, sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ps_common import load_rgb, srgb_to_lab, blur

VERSION = 'style.py v1.3.0'
TEND = ('warm', 'colour', 'contrast', 'depth', 'clarity')
PARAM = {'warm': 'white_balance.temp', 'colour': 'vibrance', 'contrast': 'contrast', 'depth': 'shadows', 'clarity': 'clarity'}
# The most a style may push each parameter: one third of its half-range in grade.py (design doc, 2026-11-19).
CAP = {'warm': 1 / 3, 'colour': 0.8 / 3, 'contrast': 0.6 / 3, 'depth': 25 / 3, 'clarity': 0.6 / 3}
# Stat change per unit of the parameter, measured with grade.py on the 29 originals in tests/fixtures (median, see
# tests/test_style.py::test_gains_match_grade). Turns a measured difference into a parameter offset.
GAIN = {'warm': 5.902, 'colour': 8.087, 'contrast': 9.29, 'depth': 0.326, 'clarity': 2.272}
# An ordinary phone photo: the median stats of the same 29 originals (used only by --finals).
BASELINE = {'warm': 4.445, 'colour': 9.537, 'contrast': 30.731, 'depth': 2.86, 'clarity': 3.654}
STEP = {'warm': 0.06, 'colour': 0.05, 'contrast': 0.04, 'depth': 1.5, 'clarity': 0.03}   # one feedback sentence
WORDS = {'warm': ('偏暖', '偏冷'), 'colour': ('色彩浓郁', '色彩淡雅、低饱和'), 'contrast': ('反差强', '反差柔和'),
         'depth': ('暗部通透', '暗部压得深'), 'clarity': ('质感清晰', '质感柔和')}


def stats(img):
    """Five numbers that describe how a photo is graded (on a 512-px copy: fast, stable)."""
    h, w = img.shape[:2]
    s = max(1, max(h, w) // 512)
    lab = srgb_to_lab(img[::s, ::s])
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    mid = (L > 20) & (L < 90)
    C = np.hypot(a, b)
    p10 = float(np.percentile(L, 10))
    return {'warm': float(np.median(b[mid])) if mid.any() else 0.0,
            'colour': float(np.median(C[mid])) if mid.any() else 0.0,
            'contrast': float(np.mean(np.abs(L - 50))),   # grade.py's S-curve moves every tone away from 50
            'depth': float(p10),
            'clarity': float(np.mean(np.abs(L - blur(L, 6))))}


def _profile(deltas, n, source):
    tend = {}
    for k in TEND:
        d = np.array([x[k] for x in deltas], np.float64)
        g = GAIN[k] or 1.0
        off = float(np.median(d) / g)
        spread = float(np.std(d / g)) if len(d) > 1 else abs(off)
        conf = 0.0 if off == 0 else max(0.0, min(1.0, abs(off) / (abs(off) + spread + 1e-9))) * min(1.0, n / 5)
        off = max(-CAP[k], min(CAP[k], off))
        tend[k] = {'offset': round(off, 4), 'confidence': round(conf, 3)}
    return {'source': source, 'samples': n, 'tendencies': tend}


def build(out, files, mode, genre):
    if mode == 'pairs':
        if len(files) % 2: sys.exit('--pairs takes ORIGINAL FINAL pairs')
        pairs = [(files[i], files[i + 1]) for i in range(0, len(files), 2)]
        deltas = []
        for o, f in pairs:
            so, sf = stats(load_rgb(o)), stats(load_rgb(f))
            deltas.append({k: sf[k] - so[k] for k in TEND})
        n = len(pairs)
    else:
        deltas = [{k: v - BASELINE[k] for k, v in stats(load_rgb(f)).items()} for f in files]
        n = len(files)
    if not 3 <= n <= 10: sys.exit(f'build needs 3-10 samples, got {n}')
    prof = json.loads(Path(out).read_text(encoding='utf-8')) if Path(out).exists() else {}
    prof.setdefault('tool', VERSION); prof.setdefault('on', True); prof.setdefault('feedback', [])
    prof.setdefault('genres', {})
    p = _profile(deltas, n, mode)
    if genre: prof['genres'][genre] = p
    else: prof['general'] = p
    prof['updated'] = datetime.date.today().isoformat()
    Path(out).write_text(json.dumps(prof, ensure_ascii=False, indent=1), encoding='utf-8')
    return prof


def tendencies(prof, genre=None):
    """The genre's own profile when it has one, else the general one; feedback steps are already folded in."""
    p = (prof.get('genres') or {}).get(genre) if genre else None
    p = p or prof.get('general') or {'tendencies': {}}
    return {k: p['tendencies'].get(k, {'offset': 0.0, 'confidence': 0.0}) for k in TEND}


def apply(params, prof, genre=None):
    out = json.loads(json.dumps(params))
    rec = {'tool': VERSION, 'on': bool(prof.get('on', True)), 'genre': genre, 'changes': {}}
    if not rec['on']: out['style'] = rec; return out
    for k, t in tendencies(prof, genre).items():
        push = max(-CAP[k], min(CAP[k], float(t['offset']) * float(t['confidence'])))
        if abs(push) < 1e-4: continue
        if k == 'warm':
            wb = dict(out.get('white_balance') or {}); old = float(wb.get('temp', 0)); new = max(-1, min(1, old + push))
            wb['temp'] = round(new, 4); out['white_balance'] = wb
        else:
            key = PARAM[k]; old = float(out.get(key, 0)); new = old + push
            lo, hi = {'vibrance': (-0.5, 0.8), 'contrast': (-0.5, 0.6), 'shadows': (-25, 25), 'clarity': (0, 0.6)}[key]
            new = round(max(lo, min(hi, new)), 4); out[key] = new
        if abs(new - old) > 1e-6: rec['changes'][PARAM[k]] = [round(old, 4), round(new, 4)]
    rec['words'] = words(prof, genre)
    out['style'] = rec
    return out


def words(prof, genre=None):
    parts = [WORDS[k][0 if t['offset'] > 0 else 1] for k, t in tendencies(prof, genre).items()
             if t['confidence'] >= 0.3 and abs(t['offset']) >= CAP[k] * 0.15]
    return '，'.join(parts)


def feedback(prof, param, direction, said, genre=None, date=None):
    if param not in TEND: sys.exit(f'--param must be one of {TEND}')
    d = 1 if float(direction) > 0 else -1
    p = prof['genres'].setdefault(genre, {'source': 'feedback', 'samples': 0, 'tendencies': {}}) if genre else \
        prof.setdefault('general', {'source': 'feedback', 'samples': 0, 'tendencies': {}})
    t = p['tendencies'].setdefault(param, {'offset': 0.0, 'confidence': 0.0})
    t['offset'] = round(max(-CAP[param], min(CAP[param], t['offset'] + d * STEP[param])), 4)
    same = (t['offset'] > 0) == (d > 0)
    t['confidence'] = round(min(1.0, t['confidence'] + 0.15) if same else max(0.0, t['confidence'] - 0.15), 3)
    prof.setdefault('feedback', []).append({'date': date or datetime.date.today().isoformat(), 'words': said,
                                            'param': param, 'dir': d, **({'genre': genre} if genre else {})})
    prof['updated'] = date or datetime.date.today().isoformat()
    return prof


def main():
    a = [x for x in sys.argv[1:] if not x.startswith('--')]
    opt = {x[2:].split('=', 1)[0]: (x.split('=', 1)[1] if '=' in x else True) for x in sys.argv[1:] if x.startswith('--')}
    if not a: sys.exit(__doc__)
    cmd, genre = a[0], opt.get('genre')
    if cmd == 'build':
        mode = 'pairs' if opt.get('pairs') else 'finals'
        r = build(a[1], a[2:], mode, genre)
    elif cmd == 'apply':
        params = json.loads(Path(a[1]).read_text(encoding='utf-8') or '{}')
        r = apply(params, json.loads(Path(a[2]).read_text(encoding='utf-8')), genre)
        Path(a[3]).write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding='utf-8'); r = r['style']
    elif cmd == 'feedback':
        prof = json.loads(Path(a[1]).read_text(encoding='utf-8')) if Path(a[1]).exists() else {'tool': VERSION, 'on': True, 'genres': {}, 'feedback': []}
        prof.setdefault('genres', {})
        r = feedback(prof, opt.get('param'), opt.get('dir', 1), opt.get('words', ''), genre, opt.get('date'))
        Path(a[1]).write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding='utf-8')
    elif cmd == 'show':
        r = json.loads(Path(a[1]).read_text(encoding='utf-8'))
    elif cmd == 'words':
        r = {'words': words(json.loads(Path(a[1]).read_text(encoding='utf-8')), genre)}
    else:
        sys.exit(__doc__)
    print(json.dumps(r, ensure_ascii=False, indent=1)); return 0


if __name__ == '__main__':
    raise SystemExit(main())
