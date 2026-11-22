#!/usr/bin/env python3
"""Photographic Studio v1.4.0 - pipeline: SKILL.md steps 5-7 (everything after the G call) in one command.
Usage: python3 pipeline.py SOURCE G_OUTPUT PARAMS_JSON OUT_PNG [RECEIPT_JSON]
                              [--genre=museum|night] [--no-g] [--texture=auto|x0,y0,x1,y1;...] [--settled=PNG]
  SOURCE      the original photo;  G_OUTPUT  the host's generative edit (or SOURCE / --no-g when there is no G)
  PARAMS_JSON the director brief's parameters (grade.py, "moves", "keep", "auto"), plus optionally
              "reframe": {"rotate": deg, "persp": [8 numbers], "box": [l, t, r, b], "zoom": z, "center": [x, y],
                          "allow_aspect_change": true}   - the chosen crop (reframe_rules.md)
  --texture   naturalness fix (naturalness.md section 2) after the agent's acceptance: auto, or boxes in fractions
  --settled   resume from the settled image this command wrote before (OUT_PNG.settled.png): skips finish + settle,
              e.g. to rerun with --texture or another crop after looking at the result
It is a thin wrapper (user 2026-11-20): it calls the existing tools in the order SKILL.md gives and changes none of
them. Order: finish.py -> settle.py -> [texture_blend.py] -> reframe.py on the result AND, with the same arguments, on
the original (so harmonize.py always compares like with like - this was a manual step that could be missed) ->
n_trim.py (only acts when highlights clip) -> harmonize.py (the last step; nothing changes the photo after it).
It does not call G and does not judge by eye: the receipt's "next" says when SKILL.md asks for G to be called once
more (finish.py fell back to N direct with G used once, or harmonize.py says REGEN_G). Deterministic; never asks.
v1.4.0: after harmonize.py the four expressiveness gates (improve_check.py --gates) are measured once more on the file
that is delivered, against the original framed the same way, and written to the receipt ("gates"); after a crop the
subject gate is skipped (the brief's box no longer applies).
"""
import json, shutil, subprocess, sys, tempfile
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


def main():
    a = [x for x in sys.argv[1:] if not x.startswith('--')]
    opt = dict(x[2:].split('=', 1) for x in sys.argv[1:] if x.startswith('--') and '=' in x)
    if len(a) < 4: sys.exit(__doc__)
    src, g, pj, out = a[:4]; rec_p = a[4] if len(a) > 4 else None
    genre = opt.get('genre')
    params = json.loads(Path(pj).read_text(encoding='utf-8') or '{}') if Path(pj).exists() else {}
    rec = {'tool': 'pipeline.py v1.4.0', 'steps': {}, 'next': []}
    settled = Path(str(out) + '.settled.png')
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        if opt.get('settled'):
            if not Path(opt['settled']).exists(): sys.exit('--settled: file not found')
            if Path(opt['settled']).resolve() != settled.resolve(): shutil.copy(opt['settled'], settled)
            rec['steps']['finish'] = rec['steps']['settle'] = 'resumed from ' + Path(opt['settled']).name
        else:
            fin = td / 'finish.png'
            r = tool('finish.py', src, g, pj, fin, td / 'finish.json', *(['--no-g'] if '--no-g' in sys.argv else []),
                     *([f'--genre={genre}'] if genre in ('museum', 'night') else []))   # v1.4.0: night too (shadow clamp)
            if not fin.exists(): sys.exit('finish.py produced no image: ' + json.dumps(r, ensure_ascii=False)[:400])
            rec['steps']['finish'] = {'delivered': r.get('delivered'), 'verdict': r.get('verdict'), 'g_chroma': r.get('g_chroma'),
                                      'attempts': r.get('attempts')}
            used_g = r.get('route') == 'g'
            if used_g and str(r.get('delivered', '')).startswith('n_direct'):
                rec['next'].append('finish.py fell back to N direct: if G was called only once, call G once more with the '
                                   'SKILL.md step 5 wording and rerun this command (two refusals -> deliver as is)')
            s = tool('settle.py', src, fin, settled, td / 'settle.json', *([f'--genre={genre}'] if genre == 'museum' else []),
                     *([f"--g-chroma={r['g_chroma']}"] if r.get('g_chroma') else []))
            if not settled.exists(): shutil.copy(fin, settled)
            rec['steps']['settle'] = {'final': s.get('final', s.get('verdict')), 'steps': s.get('steps')}
        cur = settled
        if opt.get('texture'):
            t_out = td / 'texture.png'; v = opt['texture']
            t = tool('texture_blend.py', src, cur, t_out, *(['--mode=auto'] if v == 'auto' else ['--mode=boxes', f'--boxes={v}']))
            rec['steps']['texture'] = t.get('verdict')
            if t_out.exists(): cur = t_out
        src_framed = Path(src)
        rf = params.get('reframe')
        if rf:
            ra = reframe_args(rf)
            f_out, s_out = td / 'framed.png', td / 'original_framed.png'
            r1, r2 = tool('reframe.py', cur, f_out, *ra), tool('reframe.py', src, s_out, *ra)
            if f_out.exists() and s_out.exists():
                cur, src_framed = f_out, s_out
                rec['steps']['reframe'] = {'args': ra, 'output_size': r1.get('output_size'), 'area_retained': r1.get('area_retained'),
                                           'warnings': r1.get('warnings'), 'original_reframed_same_way': True}
            else:
                rec['steps']['reframe'] = {'args': ra, 'error': 'reframe failed, original framing kept', 'detail': [r1.get('stderr'), r2.get('stderr')]}
        else:
            rec['steps']['reframe'] = 'not asked (original framing kept)'
        tr_out = td / 'trim.png'
        n = tool('n_trim.py', cur, tr_out, td / 'trim.json')
        if str(n.get('verdict', '')).startswith('PASS') and tr_out.exists(): cur = tr_out
        rec['steps']['n_trim'] = n.get('verdict')
        h = tool('harmonize.py', src_framed, cur, out, td / 'harmonize.json', f'--params={pj}',
                 *([f'--genre={genre}'] if genre in ('museum', 'night') else []))
        if not Path(out).exists(): shutil.copy(cur, out)
        rec['steps']['harmonize'] = {'verdict': h.get('verdict'), **{k: h.get(k) for k in ('light', 'depth', 'colour') if h.get(k)}}
        gt = tool('improve_check.py', src_framed, out, pj, '--gates', *(['--no-subject'] if rf else []),
                  *([f'--genre={genre}'] if genre in ('museum', 'night') else []))
        rec['gates'] = gt.get('gates') or gt.get('verdict')
        if str(h.get('verdict', '')).startswith('REGEN_G'):
            rec['next'].append('harmonize.py says REGEN_G: if G has not been re-called yet, call G once more and rerun this command')
    rec['output'] = str(out)
    rec['verdict'] = 'DELIVER' + (' | NEXT: ' + ' / '.join(rec['next']) if rec['next'] else '')
    text = json.dumps(rec, ensure_ascii=False, indent=1)
    if rec_p: Path(rec_p).write_text(text, encoding='utf-8')
    print(text)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
