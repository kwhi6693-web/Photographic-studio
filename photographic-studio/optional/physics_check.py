#!/usr/bin/env python3
"""Photographic Studio v1.0.4 - physical plausibility check: does the edit obey how light behaves?
Usage: python3 physics_check.py ORIGINAL FINAL [RECEIPT_JSON]
Compares final with original (a final of another size is resampled for measuring). Pure numpy + Pillow.
Checks (each a number + pass/flag; the agent still judges by eye):
  tone_order        bright and dark areas keep their order (no tone inversion; light still comes from where it came from)
  light_shade_sep   lit areas stay clearly brighter than shade (no flat fake-HDR)
  shade_coolness    in daylight, shade does not become warmer than the sunlit areas when it was cooler before
  sky_gradient      the sky keeps its natural brightness gradient (towards the horizon not darker than at the top)
  halo              no bright/dark rims along strong edges created by the edit
  highlight_order   the brightest light sources stay the brightest (nothing outshines the light that lights it)
"""
import json, sys
from pathlib import Path
import numpy as np
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ps_common import load_rgb, srgb_to_lab, blur, sha256, daylight_sky


def rank(x):
    r = np.empty(len(x)); r[np.argsort(x)] = np.arange(len(x)); return r


def edge_gain(Lo, Lf, grid=6):
    """Largest regional unsharp-mask gain the edit added across strong edges, after removing a global tone curve."""
    h, w = Lo.shape
    bins = np.linspace(0, 100, 41); idx = np.clip(np.digitize(Lo, bins) - 1, 0, 39)
    cnt = np.bincount(idx.ravel(), minlength=40); xs = (bins[:-1] + bins[1:]) / 2; med = np.zeros(40)
    for i in np.nonzero(cnt > 50)[0]: med[i] = np.median((Lf - Lo)[idx == i])
    good = cnt > 50
    if good.any(): med = np.interp(xs, xs[good], med[good])
    Rz = Lf - (Lo + np.interp(Lo, xs, med))
    best = 0.0
    for frac in (100, 50, 25):
        H = Lo - blur(Lo, max(4, min(h, w) // frac)); band = np.abs(H) > 6
        for i in range(grid):
            for j in range(grid):
                sl = (slice(i * h // grid, (i + 1) * h // grid), slice(j * w // grid, (j + 1) * w // grid))
                m = band[sl]
                if m.sum() < 300: continue
                hh = H[sl][m]; best = max(best, float((hh * Rz[sl][m]).sum() / (hh * hh).sum()))
    return round(best, 2)


def colour_explained(Lo, ao, bo, D):
    """D minus the median change of all pixels with the same original colour (L*, a*, b* bins; bins with fewer than
    200 pixels are left as they are)."""
    q = lambda x, a, b, n: np.clip(((x - a) / (b - a) * n).astype(int), 0, n - 1)
    key = (q(Lo, 0, 100, 10) * 256 + q(ao, -60, 60, 16) * 16 + q(bo, -60, 60, 16)).ravel()
    cnt = np.bincount(key, minlength=2560); order = np.argsort(key, kind='stable'); ks = key[order]; ds = D.ravel()[order]
    starts = np.searchsorted(ks, np.arange(2560)); med = np.zeros(2560, np.float32)
    for k in np.nonzero(cnt > 200)[0]: med[k] = np.median(ds[starts[k]:starts[k] + cnt[k]])
    return D - np.where(cnt[key] > 200, med[key], 0).reshape(D.shape)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if len(args) < 2: sys.exit(__doc__)
    o_p, f_p = args[:2]; rec_p = args[2] if len(args) > 2 else None
    o = load_rgb(o_p); f = load_rgb(f_p)
    if f.shape != o.shape:
        f = np.asarray(Image.fromarray(np.uint8(np.rint(f * 255))).resize((o.shape[1], o.shape[0]), Image.LANCZOS)).astype(np.float32) / 255
    lo, lf = srgb_to_lab(o), srgb_to_lab(f)
    Lo, Lf, bo, bf = lo[..., 0], lf[..., 0], lo[..., 2], lf[..., 2]
    h, w = Lo.shape; checks = {}

    # 1 tone order: 16x16 block means, Spearman correlation and count of clear inversions
    gh, gw = 16, 16
    bm = lambda L: np.array([[L[i * h // gh:(i + 1) * h // gh, j * w // gw:(j + 1) * w // gw].mean() for j in range(gw)] for i in range(gh)]).ravel()
    a, b = bm(Lo), bm(Lf)
    rho = float(np.corrcoef(rank(a), rank(b))[0, 1])
    ia, ib = np.triu_indices(len(a), 1)
    clear = np.abs(a[ia] - a[ib]) > 8                        # pairs clearly different in the original
    flips = float((np.sign(a[ia] - a[ib]) != np.sign(b[ia] - b[ib]))[clear].mean()) if clear.any() else 0.0
    night = bool(Lo.mean() < 22)      # in night shots many dark blocks are nearly equal; only clear inversions count
    checks['tone_order'] = {'rank_corr': round(rho, 3), 'clear_pairs_flipped': round(flips, 4), 'ok': bool(flips <= 0.04 and (night or rho >= 0.85)),
                            'meaning': 'areas that were clearly brighter must stay brighter'}

    # 2 light/shade separation (mid-scale): difference between bright and dark thirds of the smoothed image
    so, sf = blur(Lo, 12), blur(Lf, 12)
    sep = lambda s: float(np.percentile(s, 85) - np.percentile(s, 15))
    ratio = sep(sf) / max(sep(so), 1e-6)
    checks['light_shade_sep'] = {'ratio': round(ratio, 3), 'ok': bool(ratio >= 0.70), 'meaning': 'lit areas stay clearly brighter than shade (no flat HDR)'}

    # 3 shade coolness (daylight only): sunlit vs shade warmth order
    day = Lo.mean() >= 22
    # v1.0.2: leave the sky out - it is usually the brightest and the bluest area, so counted as "lit" it made the
    #   sunlit areas look cool and the check skipped scenes where it mattered
    skyish = (bo < -12) & (np.abs(Lo - blur(Lo, 4)) < 2.5); skyish[h // 2:] = False
    land = ~skyish
    if land.mean() > 0.3:
        lit, shade = (so > np.percentile(so[land], 70)) & land, (so < np.percentile(so[land], 30)) & land
    else:
        lit, shade = so > np.percentile(so, 70), so < np.percentile(so, 30)
    if day and lit.mean() > 0.05 and shade.mean() > 0.05:
        do_, df_ = float(bo[lit].mean() - bo[shade].mean()), float(bf[lit].mean() - bf[shade].mean())
        ok = not (do_ > 1.0 and df_ < -1.0)
        checks['shade_coolness'] = {'lit_minus_shade_b': {'original': round(do_, 2), 'final': round(df_, 2)}, 'ok': bool(ok),
                                    'meaning': 'sunlight is warmer than shade; shade must not turn warmer than the light'}
    else:
        checks['shade_coolness'] = {'ok': None, 'note': 'not a daylight scene, or no clear light/shade'}

    # 4 sky gradient: inside the sky, brightness should not start falling towards the horizon if it was rising
    tex = np.abs(Lo - blur(Lo, 4))
    sky = (bo < -12) & (tex < 2.5); sky[h // 2:] = False
    rows = np.nonzero(sky.sum(1) > w * 0.1)[0]
    if len(rows) > h * 0.08:
        top, bot = rows[:max(1, len(rows) // 3)], rows[-max(1, len(rows) // 3):]
        g = lambda L: float(L[bot][:, :][sky[bot]].mean() - L[top][sky[top]].mean())
        go, gf = g(Lo), g(Lf)
        checks['sky_gradient'] = {'horizon_minus_top_L': {'original': round(go, 2), 'final': round(gf, 2)}, 'ok': bool(not (go > 1.0 and gf < -1.0)),
                                  'meaning': 'sky is lighter towards the horizon; do not reverse it'}
    else:
        checks['sky_gradient'] = {'ok': None, 'note': 'no clear sky band'}

    # 5 halo: a glow (or dark rim) hugging strong edges that the edit created. Compare the edit's brightening right next to
    #   strong edges (2-10 px) with the brightening of the same side a little further away (16-36 px), on the dark side
    #   (glow) and on the bright side (dark rim). Ordinary clarity/contrast changes both distances alike and does not count.
    D = blur(Lf - Lo, 1.5)
    gy, gx = np.gradient(blur(Lo, 1.5)); grad = np.hypot(gx, gy)
    edge = (grad > np.percentile(grad, 98)).astype(np.float32)
    d_near = blur(edge, 6) > 0.03
    d_far = (blur(edge, 26) > 0.01) & ~(blur(edge, 10) > 0.01)
    side = Lo - blur(Lo, 10)                                   # <0: darker side of the edge, >0: brighter side
    dk, br = side < -1.5, side > 1.5
    m = lambda mask: float(D[mask].mean()) if mask.sum() > 200 else 0.0
    glow = m(d_near & dk) - m(d_far & (Lo < blur(Lo, 30)))
    rim = m(d_far & (Lo > blur(Lo, 30))) - m(d_near & br)
    # sign tells the kind: glow>0 dark side lifted at the edge (glow); glow<0 dark side pushed down (dark rim, over-sharpening);
    # rim>0 bright side dimmed at the edge; rim<0 bright side pushed up (bright rim). Any of them strong = visible halo.
    lim = 8.0 if night else 6.0
    # v1.0.2: edge_contrast_gain_info is reported only. It catches strong edge halos the measure above misses, but on
    #   real G outputs (2026-11-13 batch) it scored G's own shadow detail as high as visible halos, so it does not decide.
    eg = edge_gain(Lo, Lf)
    checks['halo'] = {'glow_on_dark_side_L': round(glow, 2), 'dark_rim_on_bright_side_L': round(rim, 2), 'limit': lim,
                      'edge_contrast_gain_info': eg,
                      'ok': bool(abs(glow) <= lim and abs(rim) <= lim),
                      'meaning': 'no glowing or dark rims hugging strong edges'}

    # 7 artificial spotlight: a large smooth brightening confined to part of a dark background (an oval "glow" around
    #   the subject with no light source causing it). 8 local darkening patch: a strong dark blotch or off-centre vignette.
    Ds = blur(Lf - Lo, max(8, min(h, w) // 40))
    darkbg = (blur(Lo, 3) < max(18.0, float(np.percentile(Lo, 20)))) & (np.abs(Lo - blur(Lo, 6)) < 2.5)
    if daylight_sky(Lo):
        # v1.0.2: with daylight in the frame, the dark areas are shade the sky fills; lifting them is fill light, not a
        #   spotlight (a backlit garden's eaves were refused for this, 2026-11-13 batch)
        checks['spotlight_glow'] = {'ok': None, 'note': 'daylight scene: shade lift is fill light'}
    elif darkbg.mean() > 0.05:
        med = float(np.median(Ds[darkbg])); top = float(np.percentile(Ds[darkbg], 98))
        bump = top - med; hot = darkbg & (Ds > med + 0.5 * bump); area = float(hot.mean())
        # v0.3.8: light falling on a surface multiplies its pattern; a glow only adds haze. If the brightened dark area's
        # fine texture grows with its brightness, it is a lit surface (e.g. the subject's shaded side), not a glow.
        edge = blur((np.abs(Lo - blur(Lo, 3)) > 3).astype(np.float32), 5) > 0.02
        hc = hot & ~edge
        if hc.mean() > 0.002:
            hp = lambda x: np.abs(x - blur(x, 2))
            mult = float((hp(Lf)[hc].mean() / max(hp(Lo)[hc].mean(), 1e-3)) / ((Lf[hc].mean() + 1) / (Lo[hc].mean() + 1)))
        else:
            mult = 0.0
        checks['spotlight_glow'] = {'dark_background_lift_spread_L': round(bump, 2), 'area': round(area, 3), 'texture_follows_light': round(mult, 2),
                                    'ok': bool(not (bump > 5.0 and bump * area > 0.25 and mult < 0.6)),
                                    'meaning': 'a dark background must not get a glowing patch or oval that no light would cause'}
    else:
        checks['spotlight_glow'] = {'ok': None, 'note': 'no large dark background'}
    # a natural edge falloff is symmetric about the frame centre; what is left after removing the symmetric part is a blotch
    # v1.0.4: also measure what is left after removing what the original pixel's colour explains (a grade that deepens
    #   all of the sky or all of a red wall darkens every pixel of that colour; a blotch darkens one place and not the
    #   rest of the same colour). Flag a very strong uneven darkening (< -20) whatever the colour says - removed lamps
    #   darken all lamp-coloured pixels together - and a moderate one (< -14) only if the colour does not explain it
    #   (< -9 after removing it). Provisional lines from four cases: real G sky/bronze deepening (-15.7/-7.4,
    #   -14.9/-5.2) pass; removed night lamps (-24.4) and a museum frame lifted flat (-18.0/-11.1) are flagged.
    yy, xx = np.mgrid[0:h, 0:w]; rr = np.hypot((xx - w / 2) / (w / 2), (yy - h / 2) / (h / 2))
    bins = np.minimum((rr / 1.42 * 12).astype(int), 11)

    def uneven_low(D):
        Dl = blur(D, max(12, min(h, w) // 20))
        prof = np.array([np.median(Dl[bins == k]) if (bins == k).any() else 0 for k in range(12)], np.float32)
        return float(np.percentile(Dl - prof[bins], 0.5))
    low = uneven_low(Lf - Lo)
    low_c = uneven_low(colour_explained(Lo, lo[..., 1], lo[..., 2], Lf - Lo))
    checks['darkening_patch'] = {'deepest_uneven_darkening_L': round(low, 2), 'not_explained_by_colour_L': round(low_c, 2),
                                 'ok': bool(not (low <= -20.0 or (low <= -14.0 and low_c <= -9.0))),
                                 'meaning': 'no dark blotch or off-centre vignette (an even edge falloff, or deepening all of one colour, is fine)'}

    # 6 highlight order: the top 1% brightest areas stay among the brightest
    tb = so >= np.percentile(so, 99)
    share = float((sf[tb] >= np.percentile(sf, 95)).mean())
    checks['highlight_order'] = {'top_lights_still_brightest': round(share, 3), 'ok': bool(share >= 0.7),
                                 'meaning': 'the light sources and brightest highlights stay the brightest things in the frame'}

    bad = [k for k, v in checks.items() if v.get('ok') is False]
    rec = {'tool': 'physics_check.py v0.3.8', 'original': {'file': Path(o_p).name, 'sha256': sha256(o_p)}, 'final': {'file': Path(f_p).name, 'sha256': sha256(f_p)},
           'checks': checks, 'verdict': 'PHYSICALLY_PLAUSIBLE' if not bad else 'CHECK_BY_EYE: ' + ', '.join(bad)}
    text = json.dumps(rec, ensure_ascii=False, indent=1)
    if rec_p: Path(rec_p).write_text(text, encoding='utf-8')
    print(text); return 0


if __name__ == '__main__':
    raise SystemExit(main())
