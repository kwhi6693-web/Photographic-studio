#!/usr/bin/env python3
"""Photographic Studio v1.6.2 - pipeline: everything after the G call, in one command.
Usage: python3 pipeline.py SOURCE G_OUTPUT PARAMS_JSON OUT_PNG [RECEIPT_JSON] --g-direct [--g-draw=2] [--genre=museum|night]
       python3 pipeline.py SOURCE SOURCE PARAMS_JSON OUT_PNG [RECEIPT_JSON] --quick-n
  SOURCE      the original photo;  G_OUTPUT  the host's generative edit (SOURCE / --no-g when there is no G)
  PARAMS_JSON the reading's parameters: "keep", "moves", optionally "key_light" and
              "reframe": {"rotate": deg, "persp": [8 numbers], "box": [l, t, r, b], "zoom": z, "center": [x, y],
                          "allow_aspect_change": true}   - the chosen crop (reframe_rules.md)
  --g-direct  main route ("修"): G's own pixels with keep restore, read-only sentinels, reframe (keeps >= 75 % of the
              frame and a long side >= 1000 px, else delivered uncropped) and highlight trim. Only hard failures
              count: a scene mismatch (collage, new framing) or no alignment in draw 1 stops with REDRAW_G (call G
              once more, rerun with --g-draw=2); draw 2 failing, or any other hard failure (unreadable input, museum
              without keep, failed restore or reframe), delivers quick N in the same command. Colour ratio and
              physics are report-only. (--ghost-residual-limit=F only changes the reported ghost check)
  --quick-n   non-generative / strictly faithful, or no G: quick_n.py, a few seconds.
v1.6.2: the v1.4 default route (no flag: finish.py -> settle.py -> harmonize.py ...) and its options (--g-drift,
--lt-opts, --texture, --settled) were removed from the package; the scripts are archived in the repository's
legacy/v1.4 folder. Results of --g-direct and --quick-n are unchanged (checked pixel by pixel on the regression set).
Deterministic; never asks; does not call G.
"""
import json, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def tool(name, *args):
    """Run a tool as its own process, the same way ps_common.run_tool does, and return its JSON report (or the error).
    No -I: hosts often install OpenCV in the user's site-packages, which -I hides (2026-11-21: cv2 'missing' in ChatGPT)."""
    p = subprocess.run([sys.executable, '-B', str(HERE / name), *map(str, args)], capture_output=True, text=True)
    try:
        return json.loads(p.stdout)
    except Exception:
        return {'verdict': f'TOOL_ERROR (exit {p.returncode})', 'stderr': p.stderr[-400:]}


def reframe_args(rf):
    a = []
    if rf.get('persp'): a += ['--persp', ','.join(str(x) for x in rf['persp'])]
    if rf.get('rotate'): a += ['--rotate', str(rf['rotate'])]
    if rf.get('box'): a += ['--box', ','.join(str(x) for x in rf['box'])]
    elif rf.get('zoom'): a += ['--zoom', str(rf['zoom'])] + (['--center', ','.join(str(x) for x in rf['center'])] if rf.get('center') else [])
    if rf.get('allow_aspect_change'): a += ['--allow-aspect-change']
    return a


def backend():
    """v1.4.4: which image backend this host ran (opencv, or the numpy cvlite stand-in)."""
    try:
        import cv2  # noqa: F401
        return 'opencv'
    except ImportError:
        return 'cvlite'


def main():
    a = [x for x in sys.argv[1:] if not x.startswith('--')]
    opt = dict(x[2:].split('=', 1) for x in sys.argv[1:] if x.startswith('--') and '=' in x)
    if len(a) < 4: sys.exit(__doc__)
    src, g, pj, out = a[:4]; rec_p = a[4] if len(a) > 4 else None
    genre = opt.get('genre')
    params = json.loads(Path(pj).read_text(encoding='utf-8') or '{}') if Path(pj).exists() else {}
    rec = {'tool': 'pipeline.py v1.6.2', 'backend': backend(), 'steps': {}, 'next': []}
    direct = '--g-direct' in sys.argv

    def emit():
        text = json.dumps(rec, ensure_ascii=False, indent=1)
        if rec_p: Path(rec_p).write_text(text, encoding='utf-8')
        print(text)
        return 0

    def deliver_quick_n(reason):
        # v1.5.0: the fast non-generative safety net (seconds, not the legacy default route's minutes)
        from quick_n import run as quick
        rec['steps']['quick_n'] = quick(src, params, out)
        ok = rec['steps']['quick_n']['verdict'] == 'DELIVER_QUICK_N'
        rec['output'] = str(out) if ok else None
        rec['verdict'] = ('DELIVER_QUICK_N' if ok else 'STOP: quick N failed') + (f' ({reason})' if reason else '')
        return emit()

    if '--quick-n' in sys.argv:
        return deliver_quick_n(None)
    if not direct:
        sys.exit('pipeline.py: give --g-direct (main route) or --quick-n. The v1.4 default route (finish.py, '
                 'settle.py, harmonize.py ...) was removed from the package in v1.6.2; it is archived in the '
                 "repository's legacy/v1.4 folder.")
    if direct:
        from g_first import run

        skip_reason = None
        if '--no-g' in sys.argv or Path(src).resolve() == Path(g).resolve():
            skip_reason = 'no G'
        cli_limit = opt.get('ghost-residual-limit')
        try:
            cli_limit = None if cli_limit is None else float(cli_limit)
            draw = int(opt.get('g-draw', 1))
            if draw not in (1, 2):
                raise ValueError('--g-draw must be 1 or 2')
            trial = run(src, g, params, out, genre, skip_reason=skip_reason,
                        ghost_residual_limit_cli=cli_limit, direct=direct, draw=draw)
        except ValueError as exc:
            sys.exit(f'pipeline.py: {exc}')
        rec['steps'].update(trial['steps'])
        rec['next'].extend(trial['next'])
        if trial['verdict'].startswith('REDRAW_G'):
            Path(out).unlink(missing_ok=True)
            rec['output'] = None
            rec['verdict'] = trial['verdict'] + ' | NEXT: ' + ' / '.join(rec['next'])
            text = json.dumps(rec, ensure_ascii=False, indent=1)
            if rec_p: Path(rec_p).write_text(text, encoding='utf-8')
            print(text)
            return 0
        if trial['verdict'].startswith('FALLBACK'):
            # v1.5.0: a hard G failure delivers quick N in the same command (a few seconds)
            Path(out).unlink(missing_ok=True)
            return deliver_quick_n('G hard failure: ' + trial['verdict'].removeprefix('FALLBACK: '))
        if trial['verdict'] in ('DELIVER_G_FIRST', 'DELIVER_G_DIRECT'):
            rec['output'] = str(out)
            degraded = trial['steps']['g_first']['degraded']
            rec['verdict'] = ('DELIVER | G_FIRST_DEGRADED: ' + ', '.join(degraded)
                              if degraded else trial['verdict'])
            text = json.dumps(rec, ensure_ascii=False, indent=1)
            if rec_p: Path(rec_p).write_text(text, encoding='utf-8')
            print(text)
            return 0
        rec['output'] = None
        rec['verdict'] = 'STOP: unexpected g_first verdict ' + str(trial['verdict'])
        return emit()


if __name__ == '__main__':
    raise SystemExit(main())
