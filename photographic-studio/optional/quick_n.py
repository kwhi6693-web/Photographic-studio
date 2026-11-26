#!/usr/bin/env python3
"""Photographic Studio v1.5.0 - quick N: the fast, non-generative safety net.
Usage: python3 quick_n.py ORIGINAL PARAMS_JSON OUTPUT_PNG [RECEIPT_JSON]

Used when the user asks for non-generative / strictly faithful editing, when there is no G, or when both G draws
hit a hard failure (pipeline.py --g-direct calls it itself). A few seconds on a phone host, unlike the legacy
default route (2026-11-26: 300-600 s, timed out in the ChatGPT sandbox).
Steps: grade.py with the automatic base adjustment (white balance from near-neutral areas, dehaze, levels,
contrast, vibrance on a dull photo) plus the brief's key_light only if the params already have one (never
required) -> the brief's reframe (same limits as g-direct: keeps >= 75 % of the frame, long side >= 1000 px) ->
n_trim highlight shoulder. No G pixels, no generative step. Weaker than a good G draft by design.
"""
import json, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from pipeline import reframe_args, tool   # noqa: E402
from ps_common import load_rgb, save_png  # noqa: E402

MIN_AREA, MIN_LONG_SIDE = 0.75, 1000


def run(source, params, output):
    steps = {'tool': 'quick_n.py v1.5.0', 'grade': None, 'reframe': {'verdict': 'NO_REFRAME'},
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
