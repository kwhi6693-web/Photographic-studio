#!/usr/bin/env python3
"""Photographic Studio v1.2.0 - "记住这张" / "不要这样": a before/after sheet in the format of assets/taste and assets/counter.
Usage: python3 -I make_pair.py ORIGINAL RESULT OUT_DIR NAME --kind=taste|counter [--genre=museum] [--crop=x0,y0,x1,y1]
Writes OUT_DIR/NAME_before_after.jpg (taste) or OUT_DIR/NAME_before_bad.jpg (counter): original left, result right,
both 900 px high, 12 px white gap; --crop (fractions of the frame) cuts both to the same detail. Prints JSON with the
measured change (intensity_check.py) and a ready table row for references/taste_profile.md or counter_examples.md.
The host cannot change the installed package: the sheet and the row are what the user sends to the repository
maintainer to make the sample permanent.
"""
import json, re, subprocess, sys
from pathlib import Path
from PIL import Image

HERE = Path(__file__).resolve().parent


def main(orig, res, out_dir, name, kind, genre=None, crop=None):
    if kind not in ('taste', 'counter'): raise SystemExit('--kind must be taste or counter')
    if not re.fullmatch(r'[a-z0-9_]+', name): raise SystemExit('NAME: lowercase letters, digits and _ only')
    o = Image.open(orig).convert('RGB'); r = Image.open(res).convert('RGB').resize(o.size, Image.LANCZOS)
    if crop:
        x0, y0, x1, y1 = [float(v) for v in crop.split(',')]
        box = (round(x0 * o.size[0]), round(y0 * o.size[1]), round(x1 * o.size[0]), round(y1 * o.size[1]))
        o, r = o.crop(box), r.crop(box)
    H = 900
    a = o.resize((round(o.size[0] * H / o.size[1]), H), Image.LANCZOS); b = r.resize((round(r.size[0] * H / r.size[1]), H), Image.LANCZOS)
    sheet = Image.new('RGB', (a.size[0] + 12 + b.size[0], H), (255, 255, 255)); sheet.paste(a, (0, 0)); sheet.paste(b, (a.size[0] + 12, 0))
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    fn = f"{name}_{'before_after' if kind == 'taste' else 'before_bad'}.jpg"
    sheet.save(Path(out_dir) / fn, quality=88, optimize=True)
    it = json.loads(subprocess.run([sys.executable, '-I', str(HERE / 'intensity_check.py'), orig, res] + ([f'--genre={genre}'] if genre else []),
                                   capture_output=True, text=True).stdout or '{}')
    c = it.get('checks', {})
    val = lambda k: c.get(k, {}).get('value') if isinstance(c.get(k), dict) else None
    if val('subject_chroma_ratio') is not None:
        change = f"主角 L* {val('subject_L_change'):+.1f}，主角色度 ×{val('subject_chroma_ratio'):.2f}，主角局部反差 ×{val('subject_local_contrast_ratio'):.2f}"
    elif val('chroma_ratio') is not None:
        change = f"L* {val('L_mean_change'):+.1f}，色度 ×{val('chroma_ratio'):.2f}，局部反差 ×{val('local_contrast_ratio'):.2f}"
    else:
        change = '（未量到）'
    row = (f"| `{fn}` <照片> | <好在哪> | {change} |" if kind == 'taste' else f"| `{fn}` <照片> | <错在哪> | <怎么避免> |")
    rep = {'tool': 'make_pair.py v1.2.0', 'file': str(Path(out_dir) / fn), 'kind': kind, 'size': list(sheet.size),
           'measured_change': change, 'row_for_' + ('taste_profile.md' if kind == 'taste' else 'counter_examples.md'): row}
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    return rep


if __name__ == '__main__':
    args = [x for x in sys.argv[1:] if not x.startswith('--')]
    opt = {x.split('=')[0]: x.split('=', 1)[1] for x in sys.argv[1:] if x.startswith('--') and '=' in x}
    if len(args) != 4:
        print(__doc__); sys.exit(2)
    main(*args, kind=opt.get('--kind', ''), genre=opt.get('--genre'), crop=opt.get('--crop'))
