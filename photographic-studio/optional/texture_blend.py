#!/usr/bin/env python3
"""Photographic Studio v0.3.2 (approved 2026-11-11) - naturalness fine-tune: give real texture back to areas G made too smooth.
Keeps G's look (light, colour, tone, everything above ~4 px) and replaces only G's finest luminance detail
with the original photo's, where G is clearly smoother than the original AND the structure still matches
(so nothing ghosts where G redrew shapes).
Usage: python3 texture_blend.py SOURCE G_IMAGE OUT_PNG [RECEIPT_JSON] [--strength=0..1] [--mode=auto|boxes] [--boxes=x0,y0,x1,y1;...]
  G_IMAGE: the current candidate on G's grid (G output, or G after detail restore).
  --mode=auto (default): only where G's fine detail < 80% of the original's.  --mode=boxes: the given boxes
  (fractions of the frame), wherever the structure matches.  --strength default 0.85.
Output has G_IMAGE's size. Pixels with zero weight are left exactly as in G_IMAGE. Deterministic.
Needs numpy, Pillow, OpenCV."""
import json, sys
from pathlib import Path
import numpy as np, cv2
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ps_common import load_rgb, save_png, to_linear, to_srgb, lin_to_lab, lab_to_lin, box, blur, structure_corr, sha256


def align(src, g):
    hg, wg = g.shape[:2]
    s = cv2.resize(src, (wg, hg), interpolation=cv2.INTER_AREA)
    g8 = lambda x: cv2.cvtColor(np.uint8(np.clip(x * 255, 0, 255)), cv2.COLOR_RGB2GRAY)
    orb = cv2.ORB_create(8000)
    ka, da = orb.detectAndCompute(g8(s), None); kb, db = orb.detectAndCompute(g8(g), None)
    if da is None or db is None: return None, 0
    m = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(da, db)
    if len(m) < 30: return None, len(m)
    a = np.float32([ka[x.queryIdx].pt for x in m]); b = np.float32([kb[x.trainIdx].pt for x in m])
    H, mask = cv2.findHomography(a, b, cv2.RANSAC, 3.0)
    if H is None or mask.sum() < 60: return None, int(0 if mask is None else mask.sum())
    sw = cv2.warpPerspective(s, H, (wg, hg), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    # sub-pixel local alignment with dense flow, limited to small displacements
    dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    f = dis.calc(g8(g), g8(sw), None)
    mag = np.hypot(f[..., 0], f[..., 1]); f[mag > 4] = 0
    yy, xx = np.mgrid[0:hg, 0:wg].astype(np.float32)
    sw = cv2.remap(sw, xx + f[..., 0], yy + f[..., 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    valid = cv2.warpPerspective(np.ones(s.shape[:2], np.float32), H, (wg, hg)) > 0.99
    return (sw, valid), int(mask.sum())


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    opt = dict(a[2:].split('=', 1) for a in sys.argv[1:] if a.startswith('--') and '=' in a)
    if len(args) < 3: sys.exit(__doc__)
    src_p, g_p, out_p = args[:3]; rec_p = args[3] if len(args) > 3 else None
    strength = min(max(float(opt.get('strength', 0.85)), 0), 1); mode = opt.get('mode', 'auto')
    src, g = load_rgb(src_p), load_rgb(g_p); hg, wg = g.shape[:2]
    rec = {'tool': 'texture_blend.py v0.3.2 (deterministic; keeps G\'s look, returns original fine texture where G is too smooth)',
           'source': {'file': Path(src_p).name, 'sha256': sha256(src_p)}, 'input': {'file': Path(g_p).name, 'sha256': sha256(g_p), 'size': [wg, hg]},
           'params': {'strength': strength, 'mode': mode, 'boxes': opt.get('boxes')}, 'flags': [], 'stop_reasons': []}
    al, inl = align(src, g); rec['registration_inliers'] = inl
    if al is None:
        rec['stop_reasons'].append('CANNOT_ALIGN'); rec['verdict'] = 'STOP: CANNOT_ALIGN - the candidate does not line up with the source; skip this step'
        text = json.dumps(rec, ensure_ascii=False, indent=1)
        if rec_p: Path(rec_p).write_text(text, encoding='utf-8')
        print(text); return 2
    sw, valid = al
    labG, labS = lin_to_lab(to_linear(g)), lin_to_lab(to_linear(sw))
    LG, LS = labG[..., 0], labS[..., 0]
    hp = lambda x: x - blur(x, 2)
    mid = lambda x: blur(x, 3) - blur(x, 14)          # shape band: survives smoothing, so a smoothed G can still be matched
    fG, fS = hp(LG), hp(LS)
    # structure agreement on the mid band (shapes the same?), local NCC
    mG, mS = mid(LG), mid(LS); r = 6
    a1, b1 = box(mG, r), box(mS, r)
    vG, vS, cv = box(mG * mG, r) - a1 * a1, box(mS * mS, r) - b1 * b1, box(mG * mS, r) - a1 * b1
    ncc = cv / np.sqrt(np.maximum(vG * vS, 1e-6))
    vG, vS = np.maximum(vG, 0), np.maximum(vS, 0)
    agree = np.where((vG < 0.3) & (vS < 0.3), 1.0, np.clip((ncc - 0.45) / 0.3, 0, 1))
    agree = cv2.erode(agree.astype(np.float32), np.ones((5, 5), np.uint8))
    # fine-detail energy ratio (is G smoother here?)
    eG, eS = np.sqrt(np.maximum(box(fG * fG, 8), 0)), np.sqrt(np.maximum(box(fS * fS, 8), 0))
    ratio = eG / (eS + 0.15)
    if mode == 'boxes' and opt.get('boxes'):
        sel = np.zeros((hg, wg), np.float32); yy, xx = np.mgrid[0:hg, 0:wg].astype(np.float32); yy /= hg; xx /= wg
        for bx in opt['boxes'].split(';'):
            x0, y0, x1, y1 = map(float, bx.split(','))
            sel = np.maximum(sel, ((xx >= x0) & (xx <= x1) & (yy >= y0) & (yy <= y1)).astype(np.float32))
        need = sel * (eS > 0.4)
    else:
        need = np.clip((0.8 - ratio) / 0.3, 0, 1) * (eS > 0.6)
    w = np.clip(blur(need * agree * valid, 4), 0, 1) * strength
    w[w < 0.02] = 0
    # match the original texture's amplitude to G's local tone slope (G may have changed contrast)
    gain = np.clip(blur(np.sqrt(np.maximum(vG, 1e-4)), 8) / (blur(np.sqrt(np.maximum(vS, 1e-4)), 8) + 1e-3), 0.85, 1.5)
    L = LG + w * (gain * fS - fG)
    out_lab = np.stack([np.clip(L, 0, 100), labG[..., 1], labG[..., 2]], -1)
    out = np.clip(to_srgb(lab_to_lin(out_lab)), 0, 1)
    out = np.where((w > 0)[..., None], out, g)                                       # untouched pixels exactly as input
    save_png(out, out_p)
    lab1 = lin_to_lab(to_linear(out)); f1 = hp(lab1[..., 0])
    ch = w > 0.2
    u_in, u_out = np.uint8(np.rint(g * 255)), np.uint8(np.rint(out * 255))
    m = {'changed_area': round(float((w > 0).mean()), 4), 'strongly_changed_area': round(float(ch.mean()), 4), 'mean_weight': round(float(w.mean()), 4),
         'fine_detail_vs_source_in_changed_area': {'before': round(float(np.abs(fG[ch]).mean() / (np.abs(fS[ch]).mean() + 1e-6)), 2) if ch.any() else None,
                                                   'after': round(float(np.abs(f1[ch]).mean() / (np.abs(fS[ch]).mean() + 1e-6)), 2) if ch.any() else None},
         'fine_detail_vs_source_whole_frame': round(float(np.abs(fG[valid]).mean() / (np.abs(fS[valid]).mean() + 1e-6)), 2),
         'structure_corr_with_input': round(structure_corr(labG[..., 0], lab1[..., 0]), 4),
         'L_mean_change_vs_input': round(float((lab1[..., 0] - LG).mean()), 3),
         'max_abs_rgb_change': int(np.abs(u_out.astype(int) - u_in.astype(int)).max())}
    rec['output'] = {'file': Path(out_p).name, 'sha256': sha256(out_p), 'size': [wg, hg]}; rec['measurements'] = m
    if m['changed_area'] < 0.005 and mode == 'auto': rec['flags'].append('NOTHING_TOO_SMOOTH: G is not smoother than the original anywhere; if it still looks AI, the cause is elsewhere (fake detail, halos, plastic colour)')
    if m['structure_corr_with_input'] < 0.97: rec['flags'].append('LOOK_CHANGED: check by eye that G\'s look is intact')
    rec['verdict'] = 'DONE' + (' | FLAGS: ' + '; '.join(rec['flags']) if rec['flags'] else '') + ' - compare at 100% with the input'
    text = json.dumps(rec, ensure_ascii=False, indent=1)
    if rec_p: Path(rec_p).write_text(text, encoding='utf-8')
    print(text); return 0


if __name__ == '__main__':
    raise SystemExit(main())
