#!/usr/bin/env python3
"""Photographic Studio v1.6.0 - read-only sentinels for G direct: two numbers that say "look here again".
Usage: python3 sentinel.py ORIGINAL ALIGNED_G [RECEIPT_JSON]
  ALIGNED_G must already be registered onto ORIGINAL (same size), as g_first.py does before keep restore.

Measured on both photos scaled to a 1000 px long side (the scale the thresholds were set on):
  texture  fine detail (L* minus a Gaussian blur of sigma 1.5) in G, divided by the same in the original, over the
           whole frame. Above TEXTURE_MAX G has drawn texture the original does not have (2026-11-26, this tool on 16
           pairs: drafts the user rejected 1.14-1.69 - arcade plaster and pillars turned into pitted travertine
           1.44, the uniform-looking courtyard 1.24 and arcade 1.14, lantern drafts 1.42-1.69; accepted drafts and
           finals 0.90-1.06, one accepted lantern draft from v1.4.1 1.22).
  dark     the same ratio inside the original's near-black areas (L* < 12), only when they cover at least
           DARK_MIN_SHARE of the frame. Above DARK_MAX G has invented detail in the shadows (rejected lantern drafts
           2.65-3.94; accepted 0.98-1.62).
Report-only: nothing is changed and nothing is rejected. A flag tells the agent where to compare G with the
original by eye; only what the eye confirms there is a hard flaw. Thresholds are provisional (16 pairs from 7
photos); the values are kept in every receipt so they can be re-tuned after about 20 real photos.
Pure numpy + Pillow.
"""
import json, sys
from pathlib import Path
import numpy as np
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ps_common import load_rgb, srgb_to_lab

TEXTURE_MAX = 1.10
DARK_MAX = 2.0
DARK_L = 12.0
DARK_MIN_SHARE = 0.10
LONG_SIDE = 1000
SIGMA = 1.5
BORDER = 0.03      # the outer 3 % is ignored: registration leaves thin unpainted edges there
CELLS = (('上', '中', '下'), ('左', '中', '右'))


def _resize(rgb, size):
    img = Image.fromarray(np.uint8(np.clip(np.rint(rgb * 255), 0, 255)))
    return np.asarray(img.resize(size, Image.BOX), np.float32) / 255


def _gauss(x, sigma=SIGMA):
    r = int(np.ceil(3 * sigma))
    t = np.arange(-r, r + 1, dtype=np.float32)
    k = np.exp(-t * t / (2 * sigma * sigma)); k /= k.sum()
    p = np.pad(x, r, mode='reflect')
    p = sum(k[i] * p[i:i + x.shape[0], :] for i in range(2 * r + 1))
    return sum(k[i] * p[:, i:i + x.shape[1]] for i in range(2 * r + 1))


def _detail(L):
    return np.abs(L - _gauss(L))


def _where(ratio_map):
    i, j = np.unravel_index(int(np.nanargmax(ratio_map)), ratio_map.shape)
    row, col = CELLS[0][i], CELLS[1][j]
    return '正中' if (row, col) == ('中', '中') else f'{row}{col}'


def measure(original, aligned, coverage=None):
    """original, aligned: sRGB 0..1 arrays of the same size. coverage: optional 0..1 map of where G was painted."""
    h, w = original.shape[:2]
    scale = LONG_SIDE / max(h, w)
    size = (max(1, round(w * scale)), max(1, round(h * scale)))
    Lo = srgb_to_lab(_resize(original, size))[..., 0]
    Lg = srgb_to_lab(_resize(aligned, size))[..., 0]
    valid = np.ones(Lo.shape, bool)
    b = int(round(BORDER * min(Lo.shape)))
    valid[:b] = valid[-b:] = False; valid[:, :b] = valid[:, -b:] = False
    if coverage is not None:
        cov = np.asarray(Image.fromarray(np.float32(coverage)).resize(size, Image.BOX))
        valid &= cov > 0.999
    do, dg = _detail(Lo), _detail(Lg)
    texture = float(dg[valid].mean() / max(do[valid].mean(), 1e-6))
    # where: the 3x3 cell with the highest ratio (cells with almost no detail in the original are skipped)
    H, W = Lo.shape
    grid = np.full((3, 3), np.nan)
    for i in range(3):
        for j in range(3):
            sl = (slice(i * H // 3, (i + 1) * H // 3), slice(j * W // 3, (j + 1) * W // 3))
            v = valid[sl]
            if v.sum() > 500 and do[sl][v].mean() > 0.3:
                grid[i, j] = dg[sl][v].mean() / do[sl][v].mean()
    out = {'texture_ratio': round(texture, 2), 'texture_max': TEXTURE_MAX,
           'texture_where': _where(grid) if np.isfinite(grid).any() else None}
    dark = valid & (Lo < DARK_L)
    share = float(dark.mean())
    out['dark_share'] = round(share, 2)
    if share >= DARK_MIN_SHARE:
        out['dark_detail_ratio'] = round(float(dg[dark].mean() / max(do[dark].mean(), 1e-6)), 2)
    else:
        out['dark_detail_ratio'] = None
    out['dark_max'] = DARK_MAX
    flags = []
    if texture > TEXTURE_MAX:
        flags.append(f"TEXTURE {texture:.2f} > {TEXTURE_MAX} ({out['texture_where']})")
    if out['dark_detail_ratio'] is not None and out['dark_detail_ratio'] > DARK_MAX:
        flags.append(f"DARK_DETAIL {out['dark_detail_ratio']:.2f} > {DARK_MAX}")
    out['flags'] = flags
    out['verdict'] = ('LOOK_AGAIN: ' + '; '.join(flags)) if flags else 'OK'
    return out


def recheck_note(result):
    """The line pipeline.py puts into `next` when a sentinel fires."""
    parts = []
    for flag in result.get('flags', []):
        if flag.startswith('TEXTURE'):
            parts.append(f"G 的细纹理比原片强（{result['texture_ratio']}，主要在画面{result['texture_where']}）："
                         '对照原片看那里的墙面、石头、木头是不是被画成了另一种材质')
        elif flag.startswith('DARK_DETAIL'):
            parts.append(f"原片很暗的地方 G 多出了细节（{result['dark_detail_ratio']} 倍）："
                         '对照原片看暗部有没有凭空出现纹理、图案或光')
    if not parts:
        return None
    return '哨兵提醒（只报不拦）：' + '；'.join(parts) + '。确认是第④条硬伤才补抽第 2 张；没问题就照常交付，回执第二行写“复看了某处：无问题”。'


def main():
    a = [x for x in sys.argv[1:] if not x.startswith('--')]
    if len(a) < 2:
        sys.exit(__doc__)
    o, g = load_rgb(a[0]), load_rgb(a[1])
    if g.shape != o.shape:
        sys.exit('ALIGNED_G must be registered onto ORIGINAL (same size)')
    rec = {'tool': 'sentinel.py v1.6.0', **measure(o, g)}
    t = json.dumps(rec, ensure_ascii=False, indent=1)
    if len(a) > 2:
        Path(a[2]).write_text(t, encoding='utf-8')
    print(t)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
