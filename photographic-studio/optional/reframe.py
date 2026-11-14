#!/usr/bin/env python3
"""Photographic Studio v1.0.9 - geometric reframing (non-generative; crop / straighten / perspective).

Usage:
  python3 reframe.py INPUT OUTPUT.png [--rotate DEG] [--persp x1,y1,x2,y2,x3,y3,x4,y4]
                     [--zoom Z] [--center CX,CY] [--box L,T,R,B --allow-aspect-change]

Order of operations: perspective -> rotate (straighten) -> crop.
 --persp   four source points as fractions of width/height, clockwise from top-left
           (TL, TR, BR, BL), that should become the corners of an upright rectangle.
 --rotate  degrees; positive turns the image counter-clockwise (use to level a tilted horizon/verticals).
           Blank corners are removed by auto-cropping the largest inscribed rectangle of the SAME aspect.
 --zoom    crop to 1/Z of the frame, same aspect (default 1.0 = no crop); --center is the crop centre
           as fractions of the (rotated) frame, default 0.5,0.5; the crop is clamped inside the frame.
 --box     free crop L,T,R,B in fractions (of the straightened frame); a new aspect needs --allow-aspect-change.

No pixels are invented: the output is resampled (Lanczos) from the input only. It writes OUTPUT.png (lossless)
and OUTPUT.png.json with source SHA-256, parameters, sizes, area retained, and warnings.
v1.0.9 (owner, 2026-11-14): reframing is there to present the photo at its best, from the original only - any crop
and any common aspect are allowed, extending the frame is not. The old 0.80 retained-area limit is gone (the owner's
own example crop kept about 0.64 and went from 3:4 to 1:1). What still limits a crop is the photo itself:
the output's short edge should stay >= 900 px so detail survives, and |rotate| <= 5 deg (larger tilts are usually
part of the scene). Both only warn; the agent decides."""
import sys, io, json, math, hashlib, argparse
import numpy as np, cv2
from PIL import Image, ImageCms, ImageOps

SRGB = ImageCms.createProfile('sRGB')

def load_srgb(p):
    im = Image.open(p); im = ImageOps.exif_transpose(im); icc = im.info.get('icc_profile'); im = im.convert('RGB')
    if icc:
        try: im = ImageCms.profileToProfile(im, ImageCms.ImageCmsProfile(io.BytesIO(icc)), SRGB, outputMode='RGB')
        except Exception: pass
    return np.asarray(im)

def sha256(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for c in iter(lambda: f.read(1 << 20), b''): h.update(c)
    return h.hexdigest()

def largest_rect_same_aspect(w, h, theta):
    """Largest axis-aligned rectangle with aspect w:h inside a w x h rectangle rotated by theta (radians)."""
    t = abs(theta) % math.pi
    if t > math.pi / 2: t = math.pi - t
    c, s = math.cos(t), math.sin(t)
    # scale k so that rect (k*w, k*h) fits: k*(w*c + h*s) <= w and k*(w*s + h*c) <= h
    k = min(w / (w * c + h * s), h / (w * s + h * c))
    return k * w, k * h

def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument('inp'); ap.add_argument('out')
    ap.add_argument('--rotate', type=float, default=0.0)
    ap.add_argument('--persp', type=str, default=None)
    ap.add_argument('--zoom', type=float, default=1.0)
    ap.add_argument('--center', type=str, default='0.5,0.5')
    ap.add_argument('--box', type=str, default=None)
    ap.add_argument('--allow-aspect-change', action='store_true')
    a = ap.parse_args()
    img = load_srgb(a.inp); H0, W0 = img.shape[:2]
    warn = []; params = {'rotate_deg': a.rotate, 'persp': a.persp, 'zoom': a.zoom, 'center': a.center, 'box': a.box}
    cur = img
    if a.persp:
        v = [float(x) for x in a.persp.split(',')]
        if len(v) != 8: sys.exit('--persp needs 8 numbers')
        src = np.float32([[v[0] * W0, v[1] * H0], [v[2] * W0, v[3] * H0], [v[4] * W0, v[5] * H0], [v[6] * W0, v[7] * H0]])
        dst = np.float32([[0, 0], [W0, 0], [W0, H0], [0, H0]])
        M = cv2.getPerspectiveTransform(src, dst)
        cur = cv2.warpPerspective(cur, M, (W0, H0), flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REPLICATE)
        # content outside the chosen quad is stretched, so the quad itself should be near the frame edges
    H, W = cur.shape[:2]
    if abs(a.rotate) > 1e-9:
        if abs(a.rotate) > 5: warn.append('rotation > 5 deg (provisional limit)')
        M = cv2.getRotationMatrix2D((W / 2, H / 2), a.rotate, 1.0)
        cur = cv2.warpAffine(cur, M, (W, H), flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))
        cw, ch = largest_rect_same_aspect(W, H, math.radians(a.rotate))
        x0, y0 = (W - cw) / 2, (H - ch) / 2
        m = 3  # safety margin (px) so resampling at the rotated border never leaks into the result
        cur = cur[int(math.ceil(y0)) + m:int(math.floor(y0 + ch)) - m, int(math.ceil(x0)) + m:int(math.floor(x0 + cw)) - m]
    H, W = cur.shape[:2]
    if a.box:
        L, T, R, B = [float(x) for x in a.box.split(',')]
        l, t, r, b = int(round(L * W)), int(round(T * H)), int(round(R * W)), int(round(B * H))
        if abs((r - l) / (b - t) - W / H) > 0.01 and not a.allow_aspect_change:
            sys.exit('box changes aspect; add --allow-aspect-change (allowed whenever the new aspect presents the photo better)')
        if not (0 <= l < r <= W and 0 <= t < b <= H):
            sys.exit('box must lie inside the frame: reframing never extends the photo')
        cur = cur[t:b, l:r]
    elif a.zoom > 1.0 + 1e-9:
        cx, cy = [float(x) for x in a.center.split(',')]
        cw, ch = W / a.zoom, H / a.zoom
        x0 = min(max(cx * W - cw / 2, 0), W - cw); y0 = min(max(cy * H - ch / 2, 0), H - ch)
        cur = cur[int(round(y0)):int(round(y0 + ch)), int(round(x0)):int(round(x0 + cw))]
    Ho, Wo = cur.shape[:2]
    area = (Wo * Ho) / (W0 * H0)
    if min(Wo, Ho) < 900: warn.append(f'short edge {min(Wo, Ho)} px < 900: detail may look soft at full view; crop less if the subject allows')
    if abs(Wo / Ho - W0 / H0) > 0.01: warn.append('aspect changed from source')
    Image.fromarray(np.ascontiguousarray(cur)).save(a.out, format='PNG', icc_profile=ImageCms.ImageCmsProfile(SRGB).tobytes())
    log = {'tool': 'reframe.py (Photographic Studio v1.0.9)', 'source_sha256': sha256(a.inp), 'output_sha256': sha256(a.out),
           'source_size': [W0, H0], 'output_size': [Wo, Ho], 'params': params,
           'area_retained': round(area, 4), 'aspect_source': round(W0 / H0, 4), 'aspect_output': round(Wo / Ho, 4),
           'resampling': 'Lanczos (persp/rotate), integer crop', 'generative': False, 'warnings': warn}
    json.dump(log, open(a.out + '.json', 'w'), ensure_ascii=False, indent=2)
    print(json.dumps(log, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
