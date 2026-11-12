#!/usr/bin/env python3
"""Photographic Studio v1.0.2 - look transfer: every output pixel is the ORIGINAL photo's pixel,
re-toned with the light and colour of the generative result G. Nothing G drew is kept, so no AI texture.
Usage: python3 look_transfer.py SOURCE G_OUTPUT OUT_PNG [RECEIPT_JSON] [--strength 0..1] [--local 0..1]
Output has the SOURCE's size and framing. Deterministic. Needs numpy, Pillow, OpenCV.

How G's look is taken over (three smooth layers, all functions of the source pixel and its neighbourhood):
  L0  colour mapping: what G did to each kind of colour and brightness (a smoothed 3-D table)
  L1  large-scale light: broad relighting, gradients, vignette (edge-aware, radius ~6% of the frame)
  L2  local light: finer shaping, used only where G and the source agree in structure (confidence map)
--strength scales everything; --local scales L2 only (0 = safest against halos).
"""
import json, sys
from pathlib import Path
import numpy as np, cv2
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ps_common import load_rgb, save_png, to_linear, to_srgb, lin_to_lab, lab_to_lin, box, blur, structure_corr, sha256

NL, NA, NB = 21, 17, 17
AB = 90.0


def register(src, g):
    hs, ws = src.shape[:2]; hg, wg = g.shape[:2]
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
    rec = {'tool': 'look_transfer.py v0.3.8 (deterministic; output pixels are the source photo, re-toned)',
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
    D = labG - labS
    lut = fit_lut(labS[::2, ::2], D[::2, ::2], valid[::2, ::2])
    R1 = (D - apply_lut(lut, labS)) * valid[..., None]
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
    delta = apply_lut(lut, lab0)
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
    dk = dk * (1 - surf)
    flat = (dk * tx > 0.5).astype(np.float32)
    glow_area = 0.0; trend_L = None
    if flat.mean() > 0.03:
        wgt = np.clip(blur(dk * tx, 10) * 1.6, 0, 1) * dk           # smooth weight: no patchy edges
        # what G may do to a dark background is a broad, smooth change - a gradient (sky deeper at the top, brighter
        # towards the horizon), not a bump. Fit that broad trend (1, x, y, y^2) and keep G within it.
        hh, ww = delta.shape[:2]; yy, xx = np.mgrid[0:hh, 0:ww].astype(np.float32); xx /= ww; yy /= hh
        basis = np.stack([np.ones_like(xx), xx, yy, yy * yy], -1)
        sel = (flat > 0); sel[::1, :] &= ((np.arange(ww) % 3) == 0)[None, :]; sel &= ((np.arange(hh) % 3) == 0)[:, None]
        trend_L = None
        for k in range(3):
            coef = np.linalg.lstsq(basis[sel], delta[..., k][sel], rcond=None)[0]
            trend = basis @ coef; tol = 1.5 if k == 0 else 1.0
            if k == 0: trend_L = trend
            cl = np.minimum(delta[..., k], trend + tol) if k == 0 else np.clip(delta[..., k], trend - tol, trend + tol)  # deepening a dark background is allowed; adding light is not
            if k == 0: glow_area = float(((np.abs(delta[..., 0] - cl) > 2.0) & (wgt > 0.5)).mean())
            delta[..., k] = delta[..., k] * (1 - wgt) + cl * wgt
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
    m['invented_light_removed_area'] = round(glow_area, 3); m['deleted_light_restored_area'] = round(removed_area, 3)
    # v1.0.2: check the result, not the intention - how much light above the background's smooth trend is left on the
    # flat dark background of the OUTPUT (a glow G invented that the clamp did not fully remove)
    glow_left = 0.0
    if trend_L is not None:
        # measured only inside the background, away from its edges: averaging only background pixels, so the real lift
        # of a lit subject next to the background is not smeared into it and mistaken for a glow
        wmask = (wgt > 0.5).astype(np.float32); rr = max(6, min(hs, ws) // 60)
        den = blur(wmask, rr); inner = blur(wmask, 2 * rr) > 0.98
        if inner.mean() > 0.01:
            bump = blur((lab1[..., 0] - lab0[..., 0] - trend_L) * wmask, rr) / np.maximum(den, 1e-6)
            glow_left = float(np.percentile(bump[inner], 99.5))
    m['glow_left_L'] = round(glow_left, 2)
    if glow_left > 2.5: rec['flags'].append(f'G_GLOW_LEFT {round(glow_left, 2)}: a glow G invented on the dark background is still {round(glow_left, 1)} L* above it in the output (v1.0.2)')
    if removed_area > 0.01: rec['flags'].append(f'G_LIGHT_REMOVAL_NOT_CARRIED {round(removed_area, 3)}: G blacked out a real light patch; kept the original light there (v0.3.8)')
    if glow_area > 0.01: rec['flags'].append(f'G_GLOW_NOT_CARRIED {round(glow_area, 3)}: G lit part of a flat dark background with no light source (glow, spotlight oval); not carried over (v0.3.7)')
    rec['verdict'] = 'DONE' + (' | FLAGS: ' + '; '.join(rec['flags']) if rec['flags'] else '') + ' - judge by eye against the brief'
    text = json.dumps(rec, ensure_ascii=False, indent=1)
    if rec_p: Path(rec_p).write_text(text, encoding='utf-8')
    print(text); return 0


if __name__ == '__main__':
    raise SystemExit(main())
