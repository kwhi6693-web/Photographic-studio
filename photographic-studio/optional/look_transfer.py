#!/usr/bin/env python3
"""Photographic Studio v1.4.1 - look transfer: every output pixel is the ORIGINAL photo's pixel,
re-toned with the light and colour of the generative result G. Nothing G drew is kept, so no AI texture.
Usage: python3 look_transfer.py SOURCE G_OUTPUT OUT_PNG [RECEIPT_JSON] [--strength 0..1] [--local 0..1] [--no-sky-trend] [--no-shadow-clamp] [--night] [--pale-sky-mask]
Output has the SOURCE's size and framing. Deterministic. Needs numpy, Pillow, OpenCV.

How G's look is taken over (three smooth layers, all functions of the source pixel and its neighbourhood):
  L0  colour mapping: what G did to each kind of colour and brightness (a smoothed 3-D table)
  L1  large-scale light: broad relighting, gradients, vignette (edge-aware, radius ~6% of the frame)
  L2  local light: finer shaping, used only where G and the source agree in structure (confidence map)
--strength scales everything; --local scales L2 only (0 = safest against halos).
v1.4.0 (2026-11-22 courtyard/arcade receipts: G lifted the darks +11.6..+14.5 L* - habitual HDR - and over-coloured):
  shadow-lift clamp  on the original's darkest ~20 % (L* < 38, smooth edge) G's positive brightness change is held to
                     about +1.75 L* (soft); deepening is allowed. Not with --night or on a frame where nothing is
                     properly exposed (median L* < 12 and p95 < 45).
  colour pre-scale   G's colour change is first halved on bright near-neutral areas (white walls, grey stone: C* < 8,
                     L* > ~45), then
                     the whole colour change is scaled so the output's mean chroma stays within 1.65x the original
                     (G's own colour is kept up to the user's 1.65x ceiling: 2026-11-19, reconfirmed 2026-11-22 after a
                     1.40x cap dulled the greens of three rainy garden photos).
  high frequency     every pixel's fine detail is the original's: the transferred change is built only from smooth
                     maps applied to the original's own pixels. The receipt measures what is left of G's own fine detail
                     in the output (g_high_freq_leak: correlation of the fine-scale change with G's after removing the
                     photo's own detail; ~0 means none; real G drafts 0.1). A tried guard that halved the local layer
                     when G is sharper only moved this from 0.13 to 0.11 and let G's light spread onto a dark museum
                     background (b2_08 leftover glow 1.7 -> 2.5 L*), so it was not kept.
"""
import json, sys
from pathlib import Path
import numpy as np
try:
    import cv2
except ImportError:   # v1.2.9: no OpenCV on the host - numpy + Pillow stand-in
    sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__))); import cvlite as cv2
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ps_common import load_rgb, save_png, to_linear, to_srgb, lin_to_lab, lab_to_lin, box, blur, structure_corr, sha256, sky_mask, sky_surfaces

NL, NA, NB = 21, 17, 17
AB = 90.0


GLOW_RAISE = 15.0   # v1.0.2: L* above the dark background's trend that only an invented glow reaches
SHADOW_T, SHADOW_CAP = 38.0, 1.75   # v1.4.0: the darkest ~20 % (L* < 38) may rise at most ~1.75 L*
CHROMA_PRESCALE = 1.65              # v1.4.0: output mean chroma at most 1.65x the original (user 2026-11-22: 1.40 dulled G's greens)
NEUTRAL_C = 8.0                     # v1.4.0: near-neutral in the original - G's colour change halved there
GLOW_REVIEW_L = 2.5


def source_light_support(L, texture):
    """Support for existing lights and adjacent structured surfaces, on the source grid."""
    radius = max(4, min(L.shape) // 45)
    background = blur(L, radius)
    lights = (L > max(60, np.percentile(L, 90))) & (L - background > 12)
    near = np.clip(blur(lights.astype(np.float32), radius) * 12, 0, 1)
    surface = np.clip(blur(texture, 3) / 4, 0, 1)
    return np.maximum(lights, near * surface)


def glow_region(residual, valid):
    """Source pixel coordinates for the residual selected for visual review."""
    ys, xs = np.nonzero(valid & (residual > GLOW_REVIEW_L))
    if not xs.size:
        return None
    i = int(np.argmax(residual[ys, xs]))
    return {'box_xyxy': [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1],
            'peak_xy': [int(xs[i]), int(ys[i])], 'peak_L': round(float(residual[ys[i], xs[i]]), 2)}


def sky_delta(lab, delta, sky):
    """Project G's sky change onto a broad trend, independently for L*, a*, b*."""
    hh, ww = sky.shape
    yy, xx = np.mgrid[0:hh, 0:ww].astype(np.float32)
    basis = np.stack([np.ones_like(xx), xx / ww, yy / hh, (yy / hh) ** 2], -1)
    sample = sky.copy()
    sample &= ((np.arange(ww) % 3) == 0)[None, :]
    sample &= ((np.arange(hh) % 3) == 0)[:, None]
    if sample.sum() < basis.shape[-1]:
        sample = sky
    core = blur(sky.astype(np.float32), max(3, min(hh, ww) // 150)) > 0.2
    weight = np.clip(blur(core.astype(np.float32), max(3, min(hh, ww) // 200)) * 2, 0, 1)
    # Sky colour is judged on the source's median, independent of G's colour.
    blue = float(np.median(lab[..., 2][sky])) < -NEUTRAL_C
    info = {'sky_area': round(float(sky.mean()), 3), 'source_sky': 'blue' if blue else 'pale'}
    info['g_sky_mottle_L'] = round(float(np.std(
        (delta[..., 0] - blur(delta[..., 0], max(8, min(hh, ww) // 6)))[sky])), 2)
    restrained = []
    for k in range(3):
        values = delta[..., k][sample]
        design = basis[sample]
        fit = np.linalg.lstsq(design, values, rcond=None)[0]
        residual = values - design @ fit
        center = np.median(residual)
        spread = np.median(np.abs(residual - center))
        clean = np.abs(residual - center) <= max(2, 3 * spread)
        if clean.sum() >= len(fit):
            fit = np.linalg.lstsq(design[clean], values[clean], rcond=None)[0]
        trend = basis @ fit
        mean = float(trend[sky].mean())
        if k == 0:
            shift = float(np.clip(mean, -6.5, 3.0) - mean)
            trend += shift
            # Preserve the broad gradient while capping a sky-only bright
            # patch, even if some of that patch influenced the fit.
            trend = np.minimum(trend, 3.0)
            info['deepening_held_back_L'] = round(max(shift, 0), 2)
            info['brightening_held_back_L'] = round(max(-shift, 0), 2)
        elif not blue and abs(mean) > 4:
            trend += np.clip(mean, -4, 4) - mean
            restrained.append(round(mean, 1))
        tolerance = 0.75 if k == 0 else 0.5
        clipped = np.clip(delta[..., k], trend - tolerance, trend + tolerance)
        if k == 0:
            info['blotch_area_of_sky'] = round(float((np.abs(delta[..., k] - clipped)[sky] > 2).mean()), 3)
        delta[..., k] += weight * (clipped - delta[..., k])
    if restrained:
        info['g_colour_shift_held_to_4'] = restrained
    return info


def register(src, g):
    hs, ws = src.shape[:2]; hg, wg = g.shape[:2]
    if getattr(cv2, 'LITE', False):
        # v1.2.9: no OpenCV - scale search + phase correlation (cvlite.register); the inlier number is on the ORB scale
        #   (60 needed below), reached at a high-pass correlation of 0.40 after alignment
        H, ncc = cv2.register(src, g)
        return H, cv2.lite_inliers(ncc, 60)
    s = cv2.resize(src, (wg, hg), interpolation=cv2.INTER_AREA)
    g8 = lambda x: cv2.cvtColor(np.uint8(np.clip(x * 255, 0, 255)), cv2.COLOR_RGB2GRAY)
    orb = cv2.ORB_create(8000)
    ka, da = orb.detectAndCompute(g8(s), None); kb, db = orb.detectAndCompute(g8(g), None)
    if da is None or db is None: return None, 0
    m = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(da, db)
    if len(m) < 30: return None, len(m)
    a = np.float32([ka[x.queryIdx].pt for x in m]); b = np.float32([kb[x.trainIdx].pt for x in m])
    H, mask = cv2.findHomography(a, b, cv2.RANSAC, 3.0)
    if H is None: return None, 0
    return H @ np.diag([wg / ws, hg / hs, 1.0]), int(mask.sum())


def lut_index(lab):
    return (np.clip(lab[..., 0] / 100, 0, 1) * (NL - 1), np.clip((lab[..., 1] + AB) / (2 * AB), 0, 1) * (NA - 1), np.clip((lab[..., 2] + AB) / (2 * AB), 0, 1) * (NB - 1))


def fit_lut(labS, D, valid):
    li, ai, bi = lut_index(labS[valid]); d = D[valid]
    idx = (np.rint(li).astype(int), np.rint(ai).astype(int), np.rint(bi).astype(int))
    sums = np.zeros((NL, NA, NB, 3), np.float64); cnt = np.zeros((NL, NA, NB), np.float64)
    np.add.at(cnt, idx, 1.0)
    for k in range(3): np.add.at(sums[..., k], idx, d[:, k])
    def smooth(x):
        for ax in range(3):
            for _ in range(2):
                p = np.pad(x, [(1, 1) if i == ax else (0, 0) for i in range(x.ndim)], mode='edge')
                sl = lambda o: tuple(slice(o, o + x.shape[i]) if i == ax else slice(None) for i in range(x.ndim))
                x = 0.25 * p[sl(0)] + 0.5 * p[sl(1)] + 0.25 * p[sl(2)]
        return x
    sums, cnt = smooth(sums), smooth(cnt)
    lut = sums / (cnt[..., None] + 1e-6)
    cl = sums.sum((1, 2)) / (cnt.sum((1, 2))[:, None] + 1e-6)                 # brightness-only curve as fallback for rare colours
    w = (cnt / (cnt + 12.0))[..., None]
    return (w * lut + (1 - w) * cl[:, None, None, :]).astype(np.float32)


def apply_lut(lut, lab):
    li, ai, bi = lut_index(lab)
    l0, a0, b0 = np.floor(li).astype(int), np.floor(ai).astype(int), np.floor(bi).astype(int)
    l1, a1, b1 = np.minimum(l0 + 1, NL - 1), np.minimum(a0 + 1, NA - 1), np.minimum(b0 + 1, NB - 1)
    fl, fa, fb = (li - l0)[..., None], (ai - a0)[..., None], (bi - b0)[..., None]
    out = 0
    for L_, wl in ((l0, 1 - fl), (l1, fl)):
        for A_, wa in ((a0, 1 - fa), (a1, fa)):
            for B_, wb in ((b0, 1 - fb), (b1, fb)):
                out = out + lut[L_, A_, B_] * (wl * wa * wb)
    return out.astype(np.float32)


def guided_coeffs(I, p, w, r, eps):
    """Edge-aware smoothing coefficients; pixels with low weight w (where G redrew the content) do not
    contribute, so a redrawn bright shape cannot bleed a glow into its surroundings."""
    sw = box(w, r) + 1e-4
    mI, mp = box(w * I, r) / sw, box(w * p, r) / sw
    a = (box(w * I * p, r) / sw - mI * mp) / (box(w * I * I, r) / sw - mI * mI + eps)
    b = mp - a * mI
    return box(a, r), box(b, r)


def confidence(Ls, Lg):
    hp = lambda x: x - blur(x, 2)
    a, b = hp(Ls), hp(Lg); r = 5
    ma, mb = box(a, r), box(b, r)
    va, vb, cv = box(a * a, r) - ma * ma, box(b * b, r) - mb * mb, box(a * b, r) - ma * mb
    ncc = cv / np.sqrt(np.maximum(va * vb, 1e-6))
    c = np.where((va < 2.0) & (vb < 2.0), 1.0, np.clip((ncc - 0.25) / 0.45, 0, 1)).astype(np.float32)
    c = cv2.erode(c, np.ones((7, 7), np.uint8))                      # distrust the pixels right next to redrawn structure too
    return np.clip(blur(c, 6), 0, 1)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    opt = {a.split('=')[0]: float(a.split('=')[1]) for a in sys.argv[1:] if a.startswith('--') and '=' in a}
    if len(args) < 3: sys.exit(__doc__)
    src_p, g_p, out_p = args[:3]; rec_p = args[3] if len(args) > 3 else None
    strength = min(max(opt.get('--strength', 1.0), 0), 1); local = min(max(opt.get('--local', 1.0), 0), 1)
    src, g = load_rgb(src_p), load_rgb(g_p)
    hs, ws = src.shape[:2]; hg, wg = g.shape[:2]
    rec = {'tool': 'look_transfer.py v1.4.0 (deterministic; output pixels are the source photo, re-toned)',
           'source': {'file': Path(src_p).name, 'sha256': sha256(src_p), 'size': [ws, hs]}, 'g': {'file': Path(g_p).name, 'sha256': sha256(g_p), 'size': [wg, hg]},
           'params': {'strength': strength, 'local': local}, 'flags': [], 'stop_reasons': []}
    H, inl = register(src, g); rec['registration_inliers'] = inl
    if H is None or inl < 60:
        rec['stop_reasons'].append('CANNOT_ALIGN: G does not line up with the source'); rec['verdict'] = 'STOP: ' + rec['stop_reasons'][0]
        if rec_p: Path(rec_p).write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding='utf-8')
        print(json.dumps(rec, ensure_ascii=False, indent=1)); return 2
    Sg = cv2.warpPerspective(src, H, (wg, hg), flags=cv2.INTER_AREA, borderMode=cv2.BORDER_REPLICATE)
    valid = cv2.warpPerspective(np.ones((hs, ws), np.float32), H, (wg, hg)) > 0.99
    labS, labG = lin_to_lab(to_linear(Sg)), lin_to_lab(to_linear(g))
    # v1.2.2: the colour mapping is fitted and applied on slightly smoothed images. Where G redraws fine texture
    # (ripples, foliage), its crests and troughs no longer sit on the source's, and a per-pixel fit of "what G did to
    # this colour" averages them out: bright crests get darkened, dark troughs lightened, and the original's own
    # texture comes out flatter than in both the source and G (2026-11-15 lake water: local contrast x0.67, G x1.06).
    # The mapping now sees only the tones at ~2 px and above; the source's finer texture passes through unchanged.
    sb = 2.0
    sm = lambda x: np.stack([blur(x[..., k], sb) for k in range(3)], -1)
    labSb = sm(labS)
    D = sm(labG) - labSb
    lut = fit_lut(labSb[::2, ::2], D[::2, ::2], valid[::2, ::2])
    R1 = (D - apply_lut(lut, labSb)) * valid[..., None]
    I = labS[..., 0] / 100.0
    conf = confidence(labS[..., 0], labG[..., 0]) * valid
    # L1: large-scale light, computed at 1/8 size
    f = 8; small = (max(wg // f, 8), max(hg // f, 8))
    Is = cv2.resize(I, small, interpolation=cv2.INTER_AREA); r1 = max(3, round(0.06 * min(small)))
    ws_ = cv2.resize(conf, small, interpolation=cv2.INTER_AREA) + 0.02
    A = np.zeros((hg, wg, 3), np.float32); B = np.zeros((hg, wg, 3), np.float32); L1 = np.zeros_like(D)
    for k in range(3):
        a, b = guided_coeffs(Is, cv2.resize(R1[..., k], small, interpolation=cv2.INTER_AREA), ws_, r1, 0.01)
        a, b = cv2.resize(a, (wg, hg), interpolation=cv2.INTER_LINEAR), cv2.resize(b, (wg, hg), interpolation=cv2.INTER_LINEAR)
        A[..., k], B[..., k] = a, b; L1[..., k] = a * I + b
    # L2: local light where structure agrees
    if local > 0:
        r2 = max(4, round(0.011 * min(hg, wg))); R2 = R1 - L1 * valid[..., None]
        for k in range(3):
            a, b = guided_coeffs(I, R2[..., k], conf + 0.02, r2, 0.002)
            A[..., k] += local * conf * a; B[..., k] += local * conf * b
    # carry the smooth coefficient maps back to the source grid and apply to the full-resolution source
    back = lambda x: cv2.warpPerspective(x, H, (ws, hs), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_REPLICATE)
    lab0 = lin_to_lab(to_linear(src)); I0 = lab0[..., 0] / 100.0
    s0 = sb * ws / max(wg, 1)   # the same smoothing on the source grid
    delta = apply_lut(lut, np.stack([blur(lab0[..., k], s0) for k in range(3)], -1))
    Af, Bf = back(A), back(B)
    for k in range(3): delta[..., k] += Af[..., k] * I0 + Bf[..., k]
    delta *= strength
    # v0.3.7 no invented light: on a flat dark background (showcase black, night sky, dark wall) G may only shift the
    # background as a whole. A glow or spotlight oval there has no light source, so it is not carried over.
    Lb = blur(lab0[..., 0], 3); tex = np.sqrt(np.maximum(blur(lab0[..., 0] ** 2, 4) - blur(lab0[..., 0], 4) ** 2, 0))
    thr = max(20.0, float(np.percentile(Lb, 25)))
    dk = np.clip((thr + 4 - Lb) / 8.0, 0, 1)                      # how dark (1 = clearly dark)
    tx = np.clip((4.0 - tex) / 3.0, 0, 1)                         # how plain (1 = no texture)
    # v0.3.8: a dark, plain area can also be the shaded side of the subject (a jar's shadow side, a bronze cylinder).
    # Light falling on a surface multiplies its pattern; a glow only adds haze. Where G brings out a pattern that the
    # source holds faintly, it is lighting a surface, not a background, so G's light there is kept.
    hpf = lambda x: blur(np.abs(x - blur(x, 2)), 6)
    # the pattern must be the source's own pattern made visible (locally correlated with it), not one G invented
    hs_, hg_ = labS[..., 0] - blur(labS[..., 0], 2), labG[..., 0] - blur(labG[..., 0], 2)
    lcorr = blur(hs_ * hg_, 6) / np.sqrt(blur(hs_ * hs_, 6) * blur(hg_ * hg_, 6) + 1e-6)
    surf_g = np.clip((hpf(labG[..., 0]) - 2.5 * hpf(labS[..., 0]) - 0.6) / 1.0, 0, 1) * np.clip((lcorr - 0.3) / 0.3, 0, 1) * valid
    surf = np.clip(blur(back(surf_g.astype(np.float32)), 4) * 1.5, 0, 1)
    light_support = source_light_support(lab0[..., 0], tex)
    dk *= (1 - surf) * (1 - light_support)
    flat = (dk * tx > 0.5).astype(np.float32)
    glow_area = 0.0; trend_L = None
    if flat.mean() > 0.03:
        wgt = np.clip(blur(dk * tx, 10) * 1.6, 0, 1) * dk           # smooth weight: no patchy edges
        # what G may do to a dark background is a broad, smooth change - a gradient (sky deeper at the top, brighter
        # towards the horizon), not a bump. Fit that broad trend (1, x, y, y^2) and keep G within it.
        hh, ww = delta.shape[:2]; yy, xx = np.mgrid[0:hh, 0:ww].astype(np.float32); xx /= ww; yy /= hh
        basis = np.stack([np.ones_like(xx), xx, yy, yy * yy], -1)
        sel = (flat > 0); sel[::1, :] &= ((np.arange(ww) % 3) == 0)[None, :]; sel &= ((np.arange(hh) % 3) == 0)[:, None]
        # v1.0.2: a glow G invents stands 15-25 L* above the background's trend; a lift G gives a real surface there is a
        # few L*. Leave such strongly raised pixels - and the fading rim around them - out of the trend fit, so the
        # glow cannot pull the trend up around itself, and hold them to the trend at full weight even where the
        # background is only partly dark. Tuned so that the six approved taste samples, fed in as G, stay unchanged.
        sel0 = sel.copy()
        for _ in range(3):
            c0 = np.linalg.lstsq(basis[sel], delta[..., 0][sel], rcond=None)[0]
            hi = ((delta[..., 0] - basis @ c0) > GLOW_RAISE).astype(np.float32)
            keep = blur(hi, max(8, min(hh, ww) // 12)) < 0.02
            if (sel0 & keep).sum() < 0.5 * sel0.sum(): break
            sel = sel0 & keep
        c0 = np.linalg.lstsq(basis[sel], delta[..., 0][sel], rcond=None)[0]
        hi = ((delta[..., 0] - basis @ c0) > GLOW_RAISE).astype(np.float32)
        wgt = np.maximum(wgt, np.clip(blur(hi, max(8, min(hh, ww) // 24)) * 4, 0, 1) * np.clip(dk * 2, 0, 1) * tx)
        trend_L = None
        for k in range(3):
            coef = np.linalg.lstsq(basis[sel], delta[..., k][sel], rcond=None)[0]
            trend = basis @ coef; tol = 1.5 if k == 0 else 1.0
            if k == 0: trend_L = trend
            cl = np.minimum(delta[..., k], trend + tol) if k == 0 else np.clip(delta[..., k], trend - tol, trend + tol)  # deepening a dark background is allowed; adding light is not
            if k == 0: glow_area = float(((np.abs(delta[..., 0] - cl) > 2.0) & (wgt > 0.5)).mean())
            delta[..., k] = delta[..., k] * (1 - wgt) + cl * wgt
    sky_trend = {}
    # Museum screens and diffuse windows retain conservative pale-surface segmentation.
    sky = sky_mask(lab0[..., 0], gaps=True) if '--pale-sky-mask' in sys.argv else sky_surfaces(lab0)
    if sky.any() and '--no-sky-trend' not in sys.argv:
        sky_trend = sky_delta(lab0, delta, sky)
    # v0.3.8 no deleted light: G sometimes "cleans up" a scene by blacking out a real light patch (a lit haze in a
    # showcase, a warm-lit cabinet, a glaze sheen). Broad darkening over the whole frame is allowed; a local darkening
    # of more than 8 L* below that broad trend, where the source has light, is not carried over.
    hh, ww = delta.shape[:2]; yy, xx = np.mgrid[0:hh, 0:ww].astype(np.float32); xx /= ww; yy /= hh
    basis2 = np.stack([np.ones_like(xx), xx, yy, xx * xx, yy * yy, xx * yy], -1)
    Dlf = blur(delta[..., 0], max(6, min(hh, ww) // 30)); Llf = blur(lab0[..., 0], max(6, min(hh, ww) // 30))
    sel2 = np.zeros((hh, ww), bool); sel2[::4, ::4] = True
    coef2 = np.linalg.lstsq(basis2[sel2], Dlf[sel2], rcond=None)[0]; R = Dlf - basis2 @ coef2
    give = np.clip(-8.0 - R, 0, None) * np.clip((Llf - 10.0) / 15.0, 0, 1)
    removed_area = float((give > 2.0).mean())
    delta[..., 0] += give
    # v1.4.0 shadow-lift clamp: no habitual HDR. On the original's darkest ~20 % G's added brightness is held to ~+1.75
    #   L* (soft, tanh); deepening is untouched. A night or badly under-exposed original is excepted (lifting is the edit).
    Lo_s = blur(lab0[..., 0], max(3, min(hs, ws) // 100))
    L0m = lab0[..., 0]
    # night (declared: --night, which finish.py passes for --genre=night) or a frame where nothing is properly exposed
    #   (median L* < 12 and even the brightest 5 % under 45). Statistics alone cannot tell a night scene from a dim
    #   interior lit by sun patches (b1_03: mean 24.9, p95 72) or a backlit garden - and on those G's even shadow lift
    #   is exactly the HDR habit to hold back
    from ps_common import unexposed
    night_like = '--night' in sys.argv or unexposed(L0m)
    shadow_clamp = {}
    if not night_like and '--no-shadow-clamp' not in sys.argv:
        T = min(SHADOW_T, float(np.percentile(Lo_s, 20)) + 4.0)
        wd = 1 - np.clip((Lo_s - (T - 6.0)) / 12.0, 0, 1); wd = wd * wd * (3 - 2 * wd)
        pos = np.maximum(delta[..., 0], 0); kept = SHADOW_CAP * np.tanh(pos / SHADOW_CAP)
        cut = wd * (pos - kept)
        dark = wd > 0.5
        before_dk = float(delta[..., 0][dark].mean()) if dark.any() else 0.0
        delta[..., 0] -= cut
        k_ab = np.clip((8.0 + lab0[..., 0] + delta[..., 0]) / np.maximum(8.0 + lab0[..., 0] + delta[..., 0] + cut, 1e-3), 0.6, 1)
        delta[..., 1] = (lab0[..., 1] + delta[..., 1]) * k_ab - lab0[..., 1]; delta[..., 2] = (lab0[..., 2] + delta[..., 2]) * k_ab - lab0[..., 2]
        shadow_clamp = {'threshold_L': round(T, 1), 'area': round(float(dark.mean()), 3),
                        'g_lift_in_darks_L': round(before_dk, 2), 'kept_L': round(float(delta[..., 0][dark].mean()) if dark.any() else 0.0, 2)}
    else:
        shadow_clamp = {'skipped': 'night or badly under-exposed original: lifting the darks is the edit' if night_like else '--no-shadow-clamp'}
    # v1.4.0 colour pre-scale: G's colour change halved on near-neutral areas, then the output's mean chroma held to 1.65x
    C0 = np.hypot(lab0[..., 1], lab0[..., 2]); Cn = blur(C0, 3)
    # near-neutral AND reasonably bright (white walls, stone pillars, grey stone): a dark, low-chroma shadow is not a
    #   white wall, and G's warmth there is the scene's light (b1_03: 69 % of the frame was 'near-neutral' shadow)
    Lb0 = blur(lab0[..., 0], 3)
    wn = 0.5 * np.clip((NEUTRAL_C + 2.0 - Cn) / 4.0, 0, 1) * np.clip((Lb0 - 40.0) / 15.0, 0, 1)
    delta[..., 1] *= (1 - wn); delta[..., 2] *= (1 - wn)
    cmean0 = float(C0.mean()) + 1e-6
    ratio_at = lambda s_: float(np.hypot(lab0[..., 1] + s_ * delta[..., 1], lab0[..., 2] + s_ * delta[..., 2]).mean()) / cmean0
    r_full = ratio_at(1.0); s_ab = 1.0
    if r_full > CHROMA_PRESCALE:
        lo_, hi_ = 0.0, 1.0
        for _ in range(14):
            mid = (lo_ + hi_) / 2
            if ratio_at(mid) > CHROMA_PRESCALE: hi_ = mid
            else: lo_ = mid
        s_ab = lo_; delta[..., 1] *= s_ab; delta[..., 2] *= s_ab
    colour_prescale = {'neutral_area_halved': round(float((wn > 0.25).mean()), 3), 'chroma_ratio_full': round(r_full, 3),
                       'scale': round(s_ab, 3), 'chroma_ratio_after': round(ratio_at(1.0), 3)}
    # a lift larger than the original's shadow detail can carry turns milky: limit it, and keep local contrast under strong lifts
    dL = delta[..., 0]; lim = 24.0
    dLc = np.where(dL > 0, lim * np.tanh(dL / lim), dL)
    capped = float((dL - dLc > 3).mean()); delta[..., 0] = dLc
    rb = max(3, round(0.006 * min(hs, ws)))
    detail = lab0[..., 0] - blur(lab0[..., 0], rb)
    gain = 0.4 * np.clip(blur(dLc, rb) / 20.0, 0, 1)
    L = lab0[..., 0] + delta[..., 0] + detail * gain
    # v0.3.8: where G lifts deep shadow, the detail boost must not leave the darkest specks behind as dark blotches
    L = np.where(dLc > 0, np.maximum(L, lab0[..., 0] + 0.6 * dLc), L)
    a_, b_ = lab0[..., 1] + delta[..., 1], lab0[..., 2] + delta[..., 2]
    Lin = lab0[..., 0]
    L = np.where((L > 93) & (L > Lin), np.maximum(93 + 5 * np.tanh((L - 93) / 5), np.minimum(Lin, 100)), L)
    L = np.where((L < 3) & (L < Lin), np.minimum(3 * np.exp((L - 3) / 3), np.maximum(Lin, 0)), L)
    lin2 = lab_to_lin(np.stack([L, a_, b_], -1))
    grey = np.clip(lin2 @ np.array([0.2126729, 0.7151522, 0.072175], np.float32), 0, 1)[..., None]
    mx, mn = lin2.max(-1, keepdims=True), lin2.min(-1, keepdims=True)
    ceil = np.maximum(0.955, to_linear(src).max(-1, keepdims=True)); grey = np.minimum(grey, ceil)
    tt = np.ones_like(mx)
    tt = np.where(mx > ceil, np.minimum(tt, (ceil - grey) / np.maximum(mx - grey, 1e-6)), tt)
    tt = np.where(mn < 0, np.minimum(tt, grey / np.maximum(grey - mn, 1e-6)), tt)
    out = np.clip(to_srgb(grey + (lin2 - grey) * np.clip(tt, 0, 1)), 0, 1)
    save_png(out, out_p)

    lab1 = lin_to_lab(to_linear(out))
    og = lin_to_lab(to_linear(cv2.warpPerspective(out, H, (wg, hg), flags=cv2.INTER_AREA, borderMode=cv2.BORDER_REPLICATE)))
    lowdE = lambda x, y: float(np.sqrt(sum((blur(x[..., k], 8) - blur(y[..., k], 8)) ** 2 for k in range(3)))[valid].mean())
    d_src, d_out = lowdE(labS, labG), lowdE(og, labG)
    chroma = lambda z: float(np.hypot(z[..., 1], z[..., 2]).mean())
    fine = lambda Lx: np.abs(Lx - blur(Lx, 1.5))
    fs, fg = fine(labS[..., 0]), fine(labG[..., 0])
    cells = [[round(float(fg[i * hg // 3:(i + 1) * hg // 3, j * wg // 3:(j + 1) * wg // 3].mean() / (fs[i * hg // 3:(i + 1) * hg // 3, j * wg // 3:(j + 1) * wg // 3].mean() + 1e-6)), 2) for j in range(3)] for i in range(3)]
    u0, u1 = np.uint8(np.rint(src * 255)), np.uint8(np.rint(out * 255))
    m = {'L_mean_change': {'G': round(float((labG[..., 0] - labS[..., 0])[valid].mean()), 2), 'output': round(float(lab1[..., 0].mean() - lab0[..., 0].mean()), 2)},
         'chroma_ratio': {'G': round(chroma(labG) / max(chroma(labS), 1e-6), 3), 'output': round(chroma(lab1) / max(chroma(lab0), 1e-6), 3)},
         'look_captured': round(1 - d_out / max(d_src, 1e-6), 3), 'lowfreq_deltaE_to_G': {'source': round(d_src, 2), 'output': round(d_out, 2)},
         'structure_corr_with_source': round(structure_corr(lab0[..., 0], lab1[..., 0]), 4),
         'g_fine_structure_differs_area': round(float((conf < 0.5)[valid].mean()), 3), 'lift_capped_area': round(capped, 3),
         'clipped_white': {'source': round(float(np.any(u0 == 255, 2).mean()), 5), 'output': round(float(np.any(u1 == 255, 2).mean()), 5)},
         'g_fine_detail_vs_source': {'overall': round(float(fg[valid].mean() / (fs[valid].mean() + 1e-6)), 2), 'grid_3x3': cells}}
    rec['output'] = {'file': Path(out_p).name, 'sha256': sha256(out_p), 'size': [ws, hs]}; rec['measurements'] = m
    t = m['g_fine_detail_vs_source']['overall']
    if t < 0.8: rec['flags'].append(f'G_SMOOTHER_THAN_SOURCE {t}: G lost real texture (AI-smooth risk)')
    if t > 1.35: rec['flags'].append(f'G_SHARPER_THAN_SOURCE {t}: G added detail that is not in the photo')
    if m['look_captured'] < 0.5: rec['flags'].append(f"LOOK_ONLY_PARTLY_CAPTURED {m['look_captured']}: much of what G did is redrawn content or fine relighting that original pixels cannot carry")
    if capped > 0.05: rec['flags'].append(f'LIFT_LIMITED {round(capped, 3)}: G brightened dark areas more than the original detail can carry')
    if m['structure_corr_with_source'] < 0.9: rec['flags'].append('STRUCTURE_LOW')
    if sky_trend: m['sky_kept_to_smooth_gradient'] = sky_trend
    m['shadow_lift_clamp'] = shadow_clamp; m['colour_prescale'] = colour_prescale
    # v1.4.0: how much of G's own fine detail reached the output (correlation of the fine-scale change with G's)
    #   only the part of G's fine detail that the photo does not have counts: both changes are first cleared of the
    #   photo's own fine detail (G and the output may both scale it - that is the photo's texture, not G's)
    hpf2 = lambda x: x - blur(x, 1.5)
    vv = valid & (blur(valid.astype(np.float32), 3) > 0.99)
    leak = 0.0
    if vv.any():
        hs2 = hpf2(labS[..., 0])[vv]
        res = lambda x: x - hs2 * float((x * hs2).sum() / max(float((hs2 * hs2).sum()), 1e-9))
        dg, do = res(hpf2(labG[..., 0] - labS[..., 0])[vv]), res(hpf2(og[..., 0] - labS[..., 0])[vv])
        leak = float((dg * do).mean() / (np.sqrt((dg ** 2).mean() * (do ** 2).mean()) + 1e-9))
    m['g_high_freq_leak'] = round(leak, 3)

    m['invented_light_removed_area'] = round(glow_area, 3); m['deleted_light_restored_area'] = round(removed_area, 3)
    # v1.0.2: check the result, not the intention - how much light above the background's smooth trend is left on the
    # flat dark background of the OUTPUT (a glow G invented that the clamp did not fully remove)
    glow_left = 0.0
    hit = None
    if trend_L is not None:
        # measured only inside the background, away from its edges: averaging only background pixels, so the real lift
        # of a lit subject next to the background is not smeared into it and mistaken for a glow
        wmask = (wgt > 0.5).astype(np.float32); rr = max(6, min(hs, ws) // 60)
        den = blur(wmask, rr); inner = blur(wmask, 2 * rr) > 0.98
        if inner.mean() > 0.01:
            bump = blur((lab1[..., 0] - lab0[..., 0] - trend_L) * wmask, rr) / np.maximum(den, 1e-6)
            glow_left = float(np.percentile(bump[inner], 99.5))
            if glow_left > GLOW_REVIEW_L:
                hit = glow_region(bump, inner)
    m['glow_left_L'] = round(glow_left, 2)
    m['source_light_support_area'] = round(float((light_support > 0.5).mean()), 4)
    if hit:
        m['glow_review_region'] = hit
        rec['flags'].append(f'G_GLOW_LEFT {glow_left:.2f}: residual brightness on unsupported dark background; review source coordinates')
    if removed_area > 0.01: rec['flags'].append(f'G_LIGHT_REMOVAL_NOT_CARRIED {round(removed_area, 3)}: G blacked out a real light patch; kept the original light there (v0.3.8)')
    if sky_trend.get('blotch_area_of_sky', 0) > 0.05: rec['flags'].append(f"G_SKY_BLOTCHES_NOT_CARRIED {sky_trend['blotch_area_of_sky']}: G drew cloud-like blotches on a plain sky; only its smooth gradient was carried over (v1.2.8)")
    if glow_area > 0.01: rec['flags'].append(f'G_GLOW_NOT_CARRIED {round(glow_area, 3)}: G lit part of a flat dark background with no light source (glow, spotlight oval); not carried over (v0.3.7)')
    rec['verdict'] = 'DONE' + (' | FLAGS: ' + '; '.join(rec['flags']) if rec['flags'] else '') + ' - judge by eye against the brief'
    text = json.dumps(rec, ensure_ascii=False, indent=1)
    if rec_p: Path(rec_p).write_text(text, encoding='utf-8')
    print(text); return 0


if __name__ == '__main__':
    raise SystemExit(main())
