#!/usr/bin/env python3
"""Photographic Studio - key-detail restore after G (v0.2.0, approved 2026-11-10: judged by eye - size, total-area and seam numbers are FLAGS; only failed alignment stops; any region - text, people, animals, vehicles, artworks, small fixtures; total-area cap; frame-edge boxes; edge-aware local colour match + automatic seam check).
Puts ORIGINAL pixels back into small text regions of the G output, with G's local light/colour,
and leaves every other pixel of G unchanged. Deterministic; no generative call.
Usage: text_restore.py SOURCE G_OUTPUT OUT_PNG RECEIPT_JSON x0,y0,x1,y1 [x0,y0,x1,y1 ...]
Boxes are in SOURCE pixel coordinates and should cover the text with a small margin.
"""
import hashlib, json, sys
from pathlib import Path
import numpy as np, cv2
from PIL import Image
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent))
from ps_common import rgb2lab, lab2rgb   # v0.3.5: no scikit-image

FEATHER = 6          # px soft edge (G grid)
SEARCH = 10          # px local re-alignment search (G grid)
MAX_BOX_AREA = 0.03
TOTAL_MAX = 0.10     # all boxes together at most 10% of the frame (v0.1.8, provisional)
SEAM_MAX = 4.0      # worst 16-px border stretch, low-frequency CIELAB dE (provisional)  # each box at most 3% of the frame; bigger means this is not a "small text" fix


def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def gray(a): return (0.299*a[..., 0] + 0.587*a[..., 1] + 0.114*a[..., 2]).astype(np.float32)


def box(x, r): return cv2.blur(x, (2*r+1, 2*r+1), borderType=cv2.BORDER_REFLECT)


def guided(I, p, r, eps):
    mI, mp = box(I, r), box(p, r)
    a = (box(I*p, r)-mI*mp)/(box(I*I, r)-mI*mI+eps); b = mp-a*mI
    return box(a, r)*I + box(b, r)


def global_h(src, g):
    hs, ws = src.shape[:2]; hg, wg = g.shape[:2]
    s = cv2.resize(src, (wg, hg), interpolation=cv2.INTER_AREA)
    orb = cv2.ORB_create(8000)
    ka, da = orb.detectAndCompute(gray(s).astype(np.uint8), None)
    kb, db = orb.detectAndCompute(gray(g).astype(np.uint8), None)
    m = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(da, db)
    a = np.float32([ka[x.queryIdx].pt for x in m]); b = np.float32([kb[x.trainIdx].pt for x in m])
    H, mask = cv2.findHomography(a, b, cv2.RANSAC, 3.0)
    return H @ np.diag([wg/ws, hg/hs, 1.0]), int(mask.sum())   # source px -> G px


def main():
    src_p, g_p, out_p, rec_p = sys.argv[1:5]
    boxes = [tuple(int(v) for v in b.split(',')) for b in sys.argv[5:]]
    src = np.asarray(Image.open(src_p).convert('RGB')).astype(np.float32)
    g = np.asarray(Image.open(g_p).convert('RGB')).astype(np.float32)
    hg, wg = g.shape[:2]
    H, inl = global_h(src, g)
    warped = cv2.warpPerspective(src, H, (wg, hg), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    out = g.copy(); rec = {'source_sha256': sha(src_p), 'g_sha256': sha(g_p), 'registration_inliers': inl,
                          'params': {'total_area_max': TOTAL_MAX, 'feather_px': FEATHER, 'search_px': SEARCH, 'max_box_area': MAX_BOX_AREA, 'colour_match': 'edge-aware local (guided r=8, eps=0.002)', 'seam_deltaE_max': SEAM_MAX}, 'tool_version': 'text_restore v5 (eye-judged flags)', 'regions': [], 'stop_reasons': [], 'flags': []}
    for (x0, y0, x1, y1) in boxes:
        c = cv2.perspectiveTransform(np.float32([[[x0, y0]], [[x1, y0]], [[x1, y1]], [[x0, y1]]]), H).reshape(-1, 2)
        X0, Y0 = np.floor(c.min(0)).astype(int); X1, Y1 = np.ceil(c.max(0)).astype(int)
        X0, Y0, X1, Y1 = max(X0, 0), max(Y0, 0), min(X1, wg), min(Y1, hg)
        area = (X1-X0)*(Y1-Y0)/(wg*hg)
        r = {'box_source': [x0, y0, x1, y1], 'box_g': [int(X0), int(Y0), int(X1), int(Y1)], 'area_fraction': round(area, 4)}
        if area > MAX_BOX_AREA:
            rec['flags'].append(f'BOX_LARGE {r["box_g"]} {area:.3f}: check by eye that G\'s look is not visibly lost')
        # local re-alignment: shift the warped source patch to best match G's structure inside the box
        pad = SEARCH
        gy0, gx0 = max(Y0-pad, 0), max(X0-pad, 0)
        tmpl = gray(warped[Y0:Y1, X0:X1]); win = gray(g[gy0:min(Y1+pad, hg), gx0:min(X1+pad, wg)])
        hp = lambda x: x - cv2.GaussianBlur(x, (0, 0), 4)
        res = cv2.matchTemplate(hp(win), hp(tmpl), cv2.TM_CCOEFF_NORMED)
        _, score, _, loc = cv2.minMaxLoc(res)
        dx, dy = loc[0] - (X0-gx0), loc[1] - (Y0-gy0)
        patch = np.roll(warped, (-dy, -dx), axis=(0, 1))[Y0-dy:Y1-dy, X0-dx:X1-dx] if False else warped[Y0-dy:Y1-dy, X0-dx:X1-dx]
        if patch.shape[:2] != (Y1-Y0, X1-X0):
            dx = dy = 0; patch = warped[Y0:Y1, X0:X1]
        # v2: edge-aware LOCAL light/colour match. Within the box, take original pixels and add G's
        # low-frequency Lab difference, filtered with the original's luminance as guide, so a box that
        # spans two surfaces (e.g. gold panel + sky) gets each surface's own correction.
        P2 = 24
        yy0, xx0, yy1, xx1 = max(Y0-P2, 0), max(X0-P2, 0), min(Y1+P2, hg), min(X1+P2, wg)
        srcw = warped[yy0-dy:yy1-dy, xx0-dx:xx1-dx] if (yy0-dy >= 0 and xx0-dx >= 0 and yy1-dy <= hg and xx1-dx <= wg) else warped[yy0:yy1, xx0:xx1]
        ls, lg = rgb2lab(srcw/255.0).astype(np.float32), rgb2lab(g[yy0:yy1, xx0:xx1]/255.0).astype(np.float32)
        guide = ls[..., 0]/100.0
        lab = np.empty_like(ls)
        for k in range(3):
            lab[..., k] = ls[..., k] + guided(guide, lg[..., k]-ls[..., k], 8, 0.002)
        fixed_full = np.clip(lab2rgb(lab.astype(np.float64))*255.0, 0, 255)
        fixed = fixed_full[Y0-yy0:Y1-yy0, X0-xx0:X1-xx0]
        # feathered mask
        m = np.zeros((Y1-Y0, X1-X0), np.float32); f = FEATHER
        # v0.1.7: no feather on a side that lies on the frame edge (there is nothing outside to blend with)
        et, eb, el, er = Y0 == 0, Y1 == hg, X0 == 0, X1 == wg
        mt, mb, ml, mr = (0 if et else f), (0 if eb else f), (0 if el else f), (0 if er else f)
        if (Y1-Y0) > mt+mb+1 and (X1-X0) > ml+mr+1:
            m[mt:(Y1-Y0)-mb, ml:(X1-X0)-mr] = 1.0
        m = cv2.GaussianBlur(m, (0, 0), f/2.0, borderType=cv2.BORDER_REPLICATE)
        m = m[..., None]
        r['frame_edges'] = [s for s, e in (('top', et), ('bottom', eb), ('left', el), ('right', er)) if e]
        out[Y0:Y1, X0:X1] = m*fixed + (1-m)*out[Y0:Y1, X0:X1]
        # seam check: low-frequency colour step between the restored band just inside the edge and G just outside
        bl = lambda a: cv2.GaussianBlur(rgb2lab(np.clip(a, 0, 255)/255.0).astype(np.float32), (0, 0), 3)
        Ro, Rg = bl(out[yy0:yy1, xx0:xx1]), bl(g[yy0:yy1, xx0:xx1])
        ring = np.zeros(Ro.shape[:2], bool); iy0, ix0 = Y0-yy0, X0-xx0; iy1, ix1 = Y1-yy0, X1-xx0
        ring[max(iy0-2, 0):iy1+2, max(ix0-2, 0):ix1+2] = True
        # inner rectangle reaches the frame edge on edge sides, so those sides carry no seam band
        ring[(0 if et else iy0+f+2):(Ro.shape[0] if eb else iy1-f-2), (0 if el else ix0+f+2):(Ro.shape[1] if er else ix1-f-2)] = False
        dmap = np.sqrt(((Ro-Rg)**2).sum(-1)); cells = []
        for cy in range(0, dmap.shape[0], 16):          # worst 16-px stretch of the border, not the average:
            for cx in range(0, dmap.shape[1], 16):      # a block visible on one side only must still be caught
                rr = ring[cy:cy+16, cx:cx+16]
                if rr.sum() >= 30: cells.append(float(dmap[cy:cy+16, cx:cx+16][rr].mean()))
        seam = max(cells) if cells else 0.0
        r['seam_deltaE'] = round(seam, 2)
        if seam > SEAM_MAX: rec['flags'].append(f'SEAM_HIGH {r["box_g"]} dE={seam:.1f}: look at 100% - visible seam means STOP or tighten the box')
        r.update({'local_shift_px': [int(dx), int(dy)], 'local_match_score': round(float(score), 3)})
        if score < 0.3: rec['stop_reasons'].append(f'LOW_ALIGNMENT {r["box_g"]} score={score:.2f}')
        rec['regions'].append(r)
    total = round(sum(r['area_fraction'] for r in rec['regions']), 4)
    rec['total_area_fraction'] = total
    if total > TOTAL_MAX: rec['flags'].append(f'TOTAL_AREA_LARGE {total:.3f} > {TOTAL_MAX}: check by eye')
    o8 = np.uint8(np.clip(np.rint(out), 0, 255))
    Image.fromarray(o8).save(out_p)
    g8 = np.uint8(g); changed = np.any(o8 != g8, axis=2)
    inside = np.zeros_like(changed)
    for r in rec['regions']:
        X0, Y0, X1, Y1 = r['box_g']; inside[Y0:Y1, X0:X1] = True
    rec['output'] = {'file': Path(out_p).name, 'sha256': sha(out_p), 'size': [wg, hg]}
    rec['pixels_changed_outside_boxes'] = int((changed & ~inside).sum())
    rec['pixels_changed_fraction'] = round(float(changed.mean()), 5)
    rec['verdict'] = 'STOP: ' + '; '.join(rec['stop_reasons']) if rec['stop_reasons'] else ('RESTORED: judge seams and look by eye at normal viewing' + (' | FLAGS: ' + '; '.join(rec['flags']) if rec['flags'] else ''))
    Path(rec_p).write_text(json.dumps(rec, ensure_ascii=False, indent=1))
    print(json.dumps(rec, ensure_ascii=False))
    return 2 if rec['stop_reasons'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
