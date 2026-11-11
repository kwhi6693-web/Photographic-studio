#!/usr/bin/env python3
"""[v0.2.0, approved 2026-11-10: aspect change is a flag; scene judged also after registration] Photographic Studio - post-generation check (informational + provisional gates).
Usage: python3 check_g_output.py SOURCE_IMAGE OUTPUT_IMAGE
Checks: (1) same aspect ratio, (2) scene correspondence (structure correlation + ORB/RANSAC inliers),
(3) strength report (L* mean change, chroma ratio), (4) verdict.
Provisional thresholds come from only 5 same-photo samples; adjust with more data.
v0.1.3: also reports framing drift (global scale / rotation / centre shift fitted from the ORB homography), so a
same-aspect zoom or shift is visible. Framing numbers are reported with a provisional warning, not a gate.
It does NOT check text/detail fidelity: always inspect 1:1 crops yourself."""
import sys, io, json
import numpy as np, cv2
from PIL import Image, ImageCms
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent))
from ps_common import rgb2lab   # v0.3.5: no scikit-image
SRGB = ImageCms.createProfile('sRGB')
def load(p):
    im = Image.open(p); icc = im.info.get('icc_profile'); im = im.convert('RGB')
    if icc:
        try: im = ImageCms.profileToProfile(im, ImageCms.ImageCmsProfile(io.BytesIO(icc)), SRGB, outputMode='RGB')
        except Exception: pass
    return np.asarray(im).astype(np.float64)
def luma(a): return 0.299*a[...,0]+0.587*a[...,1]+0.114*a[...,2]
def structure_corr(a, b, size=(120,160)):
    def f(x):
        l = cv2.resize(luma(x).astype(np.float32), size, interpolation=cv2.INTER_AREA)
        h = l - cv2.GaussianBlur(l, (0,0), 6); return (h-h.mean())/(h.std()+1e-9)
    return float((f(a)*f(b)).mean())
def orb_fit(a, b):
    g = lambda x: cv2.cvtColor(cv2.resize(x.astype(np.uint8), (543,724)), cv2.COLOR_RGB2GRAY)
    o = cv2.ORB_create(3000); ka, da = o.detectAndCompute(g(a), None); kb, db = o.detectAndCompute(g(b), None)
    if da is None or db is None: return 0, None
    m = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(da, db)
    if len(m) < 8: return 0, None
    s = np.float32([ka[x.queryIdx].pt for x in m]); d = np.float32([kb[x.trainIdx].pt for x in m])
    H, mask = cv2.findHomography(s, d, cv2.RANSAC, 6.0)
    return (int(mask.sum()) if mask is not None else 0), H
def framing(H, w=543, h=724):
    if H is None: return None
    A = H[:2,:2]; sc = float(np.sqrt(abs(np.linalg.det(A)))); rot = float(np.degrees(np.arctan2(H[1,0], H[0,0])))
    c = np.array([w/2, h/2, 1.0]); q = H @ c; q = q[:2]/q[2]
    return {'framing_scale': round(sc,3), 'framing_rotation_deg': round(rot,2),
            'framing_center_shift_x': round(float((q[0]-w/2)/w),3), 'framing_center_shift_y': round(float((q[1]-h/2)/h),3)}
def main(src_p, out_p):
    s, o = load(src_p), load(out_p)
    ar_s, ar_o = s.shape[1]/s.shape[0], o.shape[1]/o.shape[0]
    corr = structure_corr(s, o); inl, Hm = orb_fit(s, o); fr = framing(Hm)
    ls, lo = rgb2lab(s/255), rgb2lab(o/255)
    cs, co = np.hypot(ls[...,1], ls[...,2]).mean(), np.hypot(lo[...,1], lo[...,2]).mean()
    r = {'source_size': [s.shape[1], s.shape[0]], 'output_size': [o.shape[1], o.shape[0]],
         'aspect_source': round(ar_s,3), 'aspect_output': round(ar_o,3),
         'structure_corr': round(corr,3), 'orb_inliers': inl,
         'L_star_mean_change': round(float(lo[...,0].mean()-ls[...,0].mean()),2),
         'chroma_ratio': round(float(co/cs),2)}
    if fr:
        r.update(fr)
        fw = []
        if not (0.97 <= fr['framing_scale'] <= 1.03): fw.append('scale')
        if abs(fr['framing_rotation_deg']) > 1.0: fw.append('rotation')
        if abs(fr['framing_center_shift_x']) > 0.02 or abs(fr['framing_center_shift_y']) > 0.02: fw.append('shift')
        r['framing_warning'] = ('framing drift: ' + ', '.join(fw) + ' (provisional; 5 real outputs were all within scale 0.997-1.005, rot <=0.25 deg, shift 0.000)') if fw else None
    aspect_ok = abs(ar_s-ar_o) <= 0.02
    # v0.2.0: also measure structure after registering the source onto the output (via the ORB homography),
    # so a cropped / re-proportioned G is judged on content, not on a stretched resize
    corr_reg = None
    if Hm is not None:
        g = lambda x: cv2.resize(x.astype(np.uint8), (543, 724))
        wa = cv2.warpPerspective(g(s), Hm, (543, 724), borderMode=cv2.BORDER_REPLICATE).astype(np.float64)
        corr_reg = structure_corr(wa, g(o).astype(np.float64))
        r['structure_corr_registered'] = round(corr_reg, 3)
    scene_ok = max(corr, corr_reg or 0.0) >= 0.8 and inl >= 300
    r['aspect_ok'] = bool(aspect_ok); r['scene_correspondence_ok'] = bool(scene_ok)
    # v0.2.0: only scene correspondence is a gate; an aspect change is a flag for the human look
    r['flags'] = [] if aspect_ok else ['ASPECT_CHANGED: check by eye that nothing important was cut or stretched']
    r['verdict'] = ('PASS_AUTOMATIC_CHECKS (judge by eye at normal viewing; user decides)' + (' | FLAGS: ' + '; '.join(r['flags']) if r['flags'] else '')) if scene_ok else \
                   'STOP: output does not correspond to source scene'
    r['note_strength'] = 'Strength is reported, not gated: the tool has no strength parameter; compare with the user-approved range (L* +3..+8, chroma x1.4..1.8).'
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0 if scene_ok else 2   # STOP exits 2; v0.2.0: aspect is a flag, not a gate
if __name__ == '__main__':
    if len(sys.argv) != 3: sys.exit(__doc__)
    sys.exit(main(sys.argv[1], sys.argv[2]))
