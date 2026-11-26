#!/usr/bin/env python3
"""Photographic Studio v1.6.0 - quick N: the fast, non-generative safety net.
Usage: python3 quick_n.py ORIGINAL PARAMS_JSON OUTPUT_PNG [RECEIPT_JSON]

Used when the user asks for non-generative / strictly faithful editing, when there is no G, or when both G draws
hit a hard failure (pipeline.py --g-direct calls it itself). A few seconds on a phone host, unlike the legacy
default route (2026-11-26: 300-600 s, timed out in the ChatGPT sandbox).
Steps: grade.py with the automatic base adjustment (white balance from near-neutral areas, dehaze, levels,
contrast, vibrance on a dull photo) plus the brief's key_light only if the params already have one (never
required) -> the brief's reframe (same limits as g-direct: keeps >= 75 % of the frame, long side >= 1000 px) ->
n_trim highlight shoulder. No G pixels, no generative step. Weaker than a good G draft by design.
v1.6.0: underexposed originals (median L* < 15 and more than 60 % of the frame below L* 20 - 2026-11-26 lantern
eaves: median 7, 78 %; every other regression original has a median of 24-56) get a lift after grade.py, which
leaves them alone because they already have a true black and clipped light sources. The lift is a smooth field
added to L*: computed on a blurred L* (so noise is not amplified), zero on the darkest 5 % (the black anchor),
fading out above L* 35-75 (lit areas and light sources stay as they are), and weaker towards the frame edges or away
from the brief's key_light box (the subject comes forward). In lifted shadows up to half of a blue or green cast
is removed (warm colours are kept). About 1 s.
"""
import json, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from pipeline import reframe_args, tool   # noqa: E402
from ps_common import load_rgb, save_png, srgb_to_lab, lin_to_lab, lab_to_lin, to_linear, to_srgb, blur  # noqa: E402
import numpy as np  # noqa: E402

MIN_AREA, MIN_LONG_SIDE = 0.75, 1000
UNDER_MEDIAN, UNDER_DARK_L, UNDER_DARK_SHARE = 15.0, 20.0, 0.60
LIFT_TARGET = 17.0       # where the median goes (20 made the lens-flare veil and the blue cast milky)
LIFT_FADE = (35.0, 75.0)  # the lift fades out between these L* values
UNCAST = 0.5             # lifted shadows lose up to half of a blue/green cast (it turns milky once visible)


def _smooth(x, a, b):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def underexposed(L):
    med, share = float(np.median(L)), float((L < UNDER_DARK_L).mean())
    return med < UNDER_MEDIAN and share > UNDER_DARK_SHARE, round(med, 1), round(share, 2)


def lift_underexposed(rgb, key_box=None):
    """rgb: sRGB 0..1. Returns (rgb, info). See the module notes (v1.6.0)."""
    lab = lin_to_lab(to_linear(rgb))
    L = lab[..., 0]
    h, w = L.shape
    base = blur(L, max(2, min(h, w) // 300))
    med = float(np.median(base))
    gamma = float(np.log(LIFT_TARGET / 100) / np.log(max(med, 1.0) / 100))
    gamma = min(1.0, max(0.55, gamma))
    curve = 100 * np.power(np.clip(base, 0, 100) / 100, gamma)
    p5 = float(np.percentile(base, 5))
    weight = _smooth(base, p5, p5 + 8) * (1 - _smooth(base, *LIFT_FADE))
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    if key_box:
        cx, cy = (key_box[0] + key_box[2]) / 2 * w, (key_box[1] + key_box[3]) / 2 * h
    else:
        cx, cy = w / 2, h / 2
    d = np.hypot((xx - cx) / w, (yy - cy) / h) / 0.75
    falloff = 1 - 0.4 * _smooth(d, 0.2, 1.0)            # 1 at the subject, 0.6 at the far corners
    delta = (curve - base) * weight * falloff
    lab[..., 0] = np.clip(L + delta, 0, 100)
    lifted = np.clip(delta / 10.0, 0, 1) * UNCAST
    lab[..., 2] = np.where(lab[..., 2] < 0, lab[..., 2] * (1 - lifted), lab[..., 2])
    lab[..., 1] = np.where(lab[..., 1] < 0, lab[..., 1] * (1 - lifted), lab[..., 1])
    out = np.clip(to_srgb(lab_to_lin(lab)), 0, 1)
    return out, {'median_before': round(med, 1), 'gamma': round(gamma, 2),
                 'median_after': round(float(np.median(blur(lab[..., 0], 2))), 1),
                 'black_anchor_L': round(p5, 1), 'max_lift_L': round(float(delta.max()), 1)}


def run(source, params, output):
    steps = {'tool': 'quick_n.py v1.6.0', 'grade': None, 'reframe': {'verdict': 'NO_REFRAME'},
             'n_trim': {'verdict': 'NOT_RUN'}}
    with tempfile.TemporaryDirectory() as name:
        folder = Path(name)
        grade_params = {'auto': True}
        if isinstance(params.get('key_light'), dict) and params['key_light'].get('box'):
            grade_params['key_light'] = params['key_light']
        params_file, graded = folder / 'grade.json', folder / 'graded.png'
        params_file.write_text(json.dumps(grade_params), encoding='utf-8')
        report = tool('grade.py', source, graded, params_file)
        steps['grade'] = {'used': sorted(grade_params), 'verdict': report.get('verdict', 'OK') if isinstance(report, dict) else 'OK'}
        if not graded.exists():
            steps['verdict'] = 'FAILED: grade.py'
            return steps
        current = graded
        # v1.6.0: underexposed originals get a lift (judged on the original, applied after grade.py)
        flag, med, share = underexposed(srgb_to_lab(load_rgb(source))[..., 0])
        steps['underexposed'] = {'median_L': med, 'dark_share': share, 'triggered': flag}
        if flag:
            box = params.get('key_light', {}).get('box') if isinstance(params.get('key_light'), dict) else None
            lifted_rgb, info = lift_underexposed(load_rgb(current), box)
            lifted = folder / 'lifted.png'
            save_png(lifted_rgb, lifted)
            steps['underexposed'].update(info)
            current = lifted
        geometry = reframe_args(params.get('reframe') or {})
        if geometry:
            framed = folder / 'framed.png'
            frame = tool('reframe.py', current, framed, *geometry)
            size = frame.get('output_size')
            area = frame.get('area_retained') or 0
            steps['reframe'] = {'args': geometry, 'output_size': size, 'area_retained': area}
            if not (framed.exists() and size):
                steps['reframe']['verdict'] = 'FAILED: delivered uncropped'
            elif area < MIN_AREA or max(size) < MIN_LONG_SIDE:
                steps['reframe']['verdict'] = 'SKIPPED_TOO_TIGHT: delivered uncropped'
            else:
                steps['reframe']['verdict'] = 'REFRAMED'
                current = framed
        trimmed = folder / 'trimmed.png'
        trim = tool('n_trim.py', current, trimmed)
        steps['n_trim'] = {'verdict': trim.get('verdict')}
        if str(trim.get('verdict', '')).startswith('PASS') and trimmed.exists():
            current = trimmed
        save_png(load_rgb(current), output)
    steps['verdict'] = 'DELIVER_QUICK_N'
    return steps


def main():
    args = sys.argv[1:]
    if len(args) not in (3, 4):
        sys.exit(__doc__)
    source, params_path, output = args[:3]
    path = Path(params_path)
    params = json.loads(path.read_text(encoding='utf-8') or '{}') if path.exists() else {}
    steps = run(source, params, output)
    text = json.dumps(steps, ensure_ascii=False, indent=1)
    if len(args) == 4:
        Path(args[3]).write_text(text, encoding='utf-8')
    print(text)


if __name__ == '__main__':
    main()
