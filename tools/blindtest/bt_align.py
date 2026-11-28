"""Blind-test helper: load photos and bring two versions of one photo into the same frame.

tone mode  -> the second image is warped into the first one's frame (ORB features + homography, OpenCV), and both
              are cut to the region they share, so only light and colour differ.
full mode  -> nothing is aligned or cut; each version keeps its own framing (composition changes, hand edits).

Without OpenCV, tone mode only accepts versions that already share a frame (same size, or the same aspect so one can
be resized); anything else stops with a clear message instead of guessing.
"""
import numpy as np
from PIL import Image, ImageOps

try:
    import cv2
except ImportError:   # no OpenCV on this host
    cv2 = None


class AlignError(RuntimeError):
    pass


def load(path):
    """RGB float32 0..1, phone EXIF rotation applied."""
    im = ImageOps.exif_transpose(Image.open(path)).convert('RGB')
    return np.asarray(im, dtype=np.float32) / 255.0


def to_image(arr):
    return Image.fromarray((np.clip(arr, 0, 1) * 255 + 0.5).astype('uint8'))


def _homography(ref, src):
    def gray(a):
        g = cv2.cvtColor((a * 255).astype('uint8'), cv2.COLOR_RGB2GRAY)
        return cv2.equalizeHist(g)
    # work on <= 1600 px for speed; scale the result back
    s = min(1.0, 1600 / max(ref.shape[:2]), 1600 / max(src.shape[:2]))
    r = cv2.resize(ref, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else ref
    q = cv2.resize(src, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else src
    orb = cv2.ORB_create(6000)
    k1, d1 = orb.detectAndCompute(gray(r), None)
    k2, d2 = orb.detectAndCompute(gray(q), None)
    if d1 is None or d2 is None:
        raise AlignError('no features found to align the two versions')
    m = sorted(cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(d1, d2), key=lambda x: x.distance)[:1500]
    if len(m) < 30:
        raise AlignError(f'too few feature matches ({len(m)}) to align the two versions')
    p1 = np.float32([k1[x.queryIdx].pt for x in m]) / s
    p2 = np.float32([k2[x.trainIdx].pt for x in m]) / s
    H, inl = cv2.findHomography(p2, p1, cv2.RANSAC, 3.0 / s)
    n = int(inl.sum()) if inl is not None else 0
    if H is None or n < 50:
        raise AlignError(f'alignment unreliable ({n} inliers); check that both files are the same photo')
    sx = float(np.hypot(H[0, 0], H[1, 0]))
    if not 0.5 < sx < 2.0:
        raise AlignError(f'alignment scale {sx:.2f} is implausible; check that both files are the same photo')
    return H, n


def _inner_box(mask):
    """Largest centred-ish axis-aligned box fully inside a boolean mask (shrinks evenly until it fits)."""
    h, w = mask.shape
    rows = np.where(mask[:, w // 4: 3 * w // 4].all(1))[0]
    cols = np.where(mask[h // 4: 3 * h // 4, :].all(0))[0]
    if len(rows) == 0 or len(cols) == 0:
        raise AlignError('the two versions share too little of the frame')
    y0, y1, x0, x1 = rows[0], rows[-1] + 1, cols[0], cols[-1] + 1
    while y1 - y0 > 10 and x1 - x0 > 10 and not mask[y0:y1, x0:x1].all():
        y0, y1, x0, x1 = y0 + 1, y1 - 1, x0 + 1, x1 - 1
    m = 2   # keep resampling edges out
    return y0 + m, y1 - m, x0 + m, x1 - m


def same_frame(a, b, mode='tone'):
    """Return (a_out, b_out, info). tone: common region only; full: untouched."""
    info = {'mode': mode}
    if mode == 'full':
        return a, b, info
    if mode != 'tone':
        raise ValueError('mode must be tone or full')
    ha, wa = a.shape[:2]
    hb, wb = b.shape[:2]
    if cv2 is None:
        if (ha, wa) == (hb, wb):
            info['method'] = 'same size (no OpenCV)'
            return a, b, info
        if abs(wa / ha - wb / hb) <= 0.01 * (wa / ha):
            info['method'] = 'resized, same aspect (no OpenCV)'
            b2 = np.asarray(to_image(b).resize((wa, ha), Image.LANCZOS), dtype=np.float32) / 255.0
            return a, b2, info
        raise AlignError('tone mode needs OpenCV to align different frames; install opencv-python-headless, '
                         'or compare versions that share the same frame, or use --mode full')
    H, n = _homography(a, b)
    bw = cv2.warpPerspective(b, H, (wa, ha), flags=cv2.INTER_LANCZOS4)
    valid = cv2.warpPerspective(np.ones((hb, wb), np.float32), H, (wa, ha), flags=cv2.INTER_NEAREST) > 0.5
    y0, y1, x0, x1 = _inner_box(valid)
    share = (y1 - y0) * (x1 - x0) / float(ha * wa)
    info.update(method='ORB homography', inliers=n, box=[int(x0), int(y0), int(x1), int(y1)], share=round(share, 3))
    if share < 0.5:
        info['warning'] = f'only {share:.0%} of the frame is shared; framing differs a lot - consider --mode full'
    return a[y0:y1, x0:x1], np.clip(bw[y0:y1, x0:x1], 0, 1), info


def fit_long_edge(img, long_edge):
    """PIL image scaled down so its long edge is at most long_edge."""
    w, h = img.size
    s = long_edge / max(w, h)
    return img.resize((round(w * s), round(h * s)), Image.LANCZOS) if s < 1 else img
