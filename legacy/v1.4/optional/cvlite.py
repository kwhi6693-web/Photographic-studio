#!/usr/bin/env python3
"""Photographic Studio v1.2.9 - cvlite: the small part of OpenCV the tools use, in numpy + Pillow only.
Used automatically when OpenCV is not installed (2026-11-21: ChatGPT's sandbox has numpy and Pillow but no cv2, so
the G route could not run). Every tool does `try: import cv2 / except ImportError: import cvlite as cv2`.

What it covers (same call signatures as OpenCV, for the arguments the tools pass):
  resize, cvtColor(COLOR_RGB2GRAY), GaussianBlur, blur, boxFilter, erode, dilate, warpPerspective, warpAffine,
  getPerspectiveTransform, getRotationMatrix2D, perspectiveTransform, connectedComponentsWithStats.
What it does NOT cover: ORB feature matching, findHomography, optical flow, template matching. Instead:
  register(src_rgb, g_rgb) aligns a G draft to the photo by scale search + FFT phase correlation (G drafts keep the
  source framing; a rotated or warped G is not matched and is refused, as an ORB failure would be). Tools that need
  optical flow or template matching (texture_blend.py, text_restore.py) report SKIPPED_NO_OPENCV and change nothing.
Deterministic. Needs numpy, Pillow.
"""
import numpy as np
from PIL import Image

LITE = True
__version__ = 'cvlite-1.2.9 (numpy+Pillow)'

INTER_NEAREST, INTER_LINEAR, INTER_CUBIC, INTER_AREA, INTER_LANCZOS4 = 0, 1, 2, 3, 4
WARP_INVERSE_MAP = 16
BORDER_CONSTANT, BORDER_REPLICATE, BORDER_REFLECT, BORDER_REFLECT_101 = 0, 1, 2, 4
BORDER_REFLECT_ = BORDER_REFLECT_101
COLOR_RGB2GRAY = 7
NORM_HAMMING = 6
RANSAC = 8
TM_CCOEFF_NORMED = 5
DISOPTICAL_FLOW_PRESET_MEDIUM = 1

_PIL = {INTER_NEAREST: Image.NEAREST, INTER_LINEAR: Image.BILINEAR, INTER_CUBIC: Image.BICUBIC,
        INTER_AREA: Image.BOX, INTER_LANCZOS4: Image.LANCZOS}


def _per_channel(x, fn):
    if x.ndim == 2: return fn(x)
    return np.stack([fn(x[..., k]) for k in range(x.shape[2])], -1)


def _as_out(y, like):
    if like.dtype == np.uint8: return np.clip(np.rint(y), 0, 255).astype(np.uint8)
    return y.astype(like.dtype)


def resize(x, size, interpolation=INTER_LINEAR, **kw):
    w, h = int(size[0]), int(size[1])
    if (x.shape[1], x.shape[0]) == (w, h): return x.copy()
    rs = _PIL.get(interpolation, Image.BILINEAR)
    if rs == Image.BOX and (w > x.shape[1] or h > x.shape[0]): rs = Image.BILINEAR   # INTER_AREA upscales bilinearly
    f = lambda c: np.asarray(Image.fromarray(np.ascontiguousarray(c, np.float32), 'F').resize((w, h), rs), np.float32)
    return _as_out(_per_channel(x.astype(np.float32), f), x)


def cvtColor(x, code):
    y = x[..., 0].astype(np.float32) * 0.299 + x[..., 1].astype(np.float32) * 0.587 + x[..., 2].astype(np.float32) * 0.114
    return _as_out(y, x)


def _pad(x, r, axis, mode):
    pw = [(0, 0)] * x.ndim; pw[axis] = (r, r)
    return np.pad(x, pw, mode={BORDER_REFLECT_101: 'reflect', BORDER_REFLECT: 'symmetric', BORDER_REPLICATE: 'edge'}.get(mode, 'reflect'))


def _conv1d(x, k, axis, mode):
    r = len(k) // 2
    p = _pad(x, r, axis, mode)
    out = np.zeros_like(x, np.float32)
    n = x.shape[axis]
    for i, kv in enumerate(k):
        sl = [slice(None)] * x.ndim; sl[axis] = slice(i, i + n)
        out += kv * p[tuple(sl)]
    return out


def _box1d(x, r, axis, mode):
    p = _pad(x.astype(np.float64), r, axis, mode)
    c = np.cumsum(p, axis=axis)
    c = np.concatenate([np.zeros_like(np.take(c, [0], axis=axis)), c], axis=axis)
    n = x.shape[axis]
    hi = np.take(c, np.arange(2 * r + 1, 2 * r + 1 + n), axis=axis); lo = np.take(c, np.arange(0, n), axis=axis)
    return ((hi - lo) / (2 * r + 1)).astype(np.float32)


def GaussianBlur(x, ksize, sigmaX, sigmaY=0, borderType=BORDER_REFLECT_101):
    kx = ksize[0] if ksize and ksize[0] else 0
    s = sigmaX if sigmaX and sigmaX > 0 else 0.3 * ((kx - 1) * 0.5 - 1) + 0.8
    r = (kx // 2) if kx else max(1, int(np.ceil(3 * s)))
    t = np.arange(-r, r + 1, dtype=np.float64); k = np.exp(-t * t / (2 * s * s)); k /= k.sum()
    y = x.astype(np.float32)
    y = _conv1d(_conv1d(y, k, 0, borderType), k, 1, borderType)
    return _as_out(y, x)


def blur(x, ksize, borderType=BORDER_REFLECT_101, **kw):
    y = x.astype(np.float32)
    y = _box1d(_box1d(y, ksize[1] // 2, 0, borderType), ksize[0] // 2, 1, borderType)
    return _as_out(y, x)


def boxFilter(x, ddepth, ksize, **kw):
    return blur(x, ksize, kw.get('borderType', BORDER_REFLECT_101))


def _rank(x, kernel, op):
    ky, kx = kernel.shape[:2]
    y = x
    for axis, k in ((0, ky), (1, kx)):
        r = k // 2
        p = _pad(y, r, axis, BORDER_REPLICATE)
        n = y.shape[axis]
        acc = None
        for i in range(k):
            sl = [slice(None)] * y.ndim; sl[axis] = slice(i, i + n)
            v = p[tuple(sl)]
            acc = v if acc is None else op(acc, v)
        y = acc
    return y


def erode(x, kernel, **kw): return _rank(x, kernel, np.minimum)
def dilate(x, kernel, **kw): return _rank(x, kernel, np.maximum)


def getPerspectiveTransform(src, dst):
    A, b = [], []
    for (x, y), (u, v) in zip(np.asarray(src, np.float64), np.asarray(dst, np.float64)):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y]); b.append(u)
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y]); b.append(v)
    h = np.linalg.solve(np.array(A), np.array(b))
    return np.append(h, 1.0).reshape(3, 3)


def getRotationMatrix2D(center, angle, scale):
    a = np.radians(angle); al, be = scale * np.cos(a), scale * np.sin(a)
    cx, cy = center
    return np.array([[al, be, (1 - al) * cx - be * cy], [-be, al, be * cx + (1 - al) * cy]])


def perspectiveTransform(pts, H):
    p = np.asarray(pts, np.float64).reshape(-1, 2)
    q = np.c_[p, np.ones(len(p))] @ np.asarray(H, np.float64).T
    return (q[:, :2] / q[:, 2:3]).reshape(np.asarray(pts).shape).astype(np.float32)


def _sample_bilinear(c, X, Y, border, value):
    h, w = c.shape
    if border == BORDER_REPLICATE:
        X = np.clip(X, 0, w - 1); Y = np.clip(Y, 0, h - 1)
    x0 = np.floor(X).astype(np.int64); y0 = np.floor(Y).astype(np.int64); fx = X - x0; fy = Y - y0
    inside = (X >= -0.5) & (X <= w - 0.5) & (Y >= -0.5) & (Y <= h - 0.5)
    x0c, x1c = np.clip(x0, 0, w - 1), np.clip(x0 + 1, 0, w - 1); y0c, y1c = np.clip(y0, 0, h - 1), np.clip(y0 + 1, 0, h - 1)
    out = (c[y0c, x0c] * (1 - fx) * (1 - fy) + c[y0c, x1c] * fx * (1 - fy) + c[y1c, x0c] * (1 - fx) * fy + c[y1c, x1c] * fx * fy)
    if border == BORDER_CONSTANT: out = np.where(inside, out, value)
    return out.astype(np.float32)


def warpPerspective(x, M, dsize, flags=INTER_LINEAR, borderMode=BORDER_CONSTANT, borderValue=0):
    w, h = int(dsize[0]), int(dsize[1])
    M = np.asarray(M, np.float64)
    Minv = M if (flags & WARP_INVERSE_MAP) else np.linalg.inv(M)      # dst -> src
    interp = flags & 15
    bv = borderValue[0] if isinstance(borderValue, (tuple, list)) else borderValue
    xf = x.astype(np.float32)
    if True:
        # Pillow's transform (output -> input coefficients, C speed); the source is padded so the border can follow
        pad = 8
        mode = {BORDER_REPLICATE: 'edge', BORDER_CONSTANT: 'constant'}.get(borderMode, 'reflect')
        pw = [(pad, pad), (pad, pad)] + ([(0, 0)] if xf.ndim == 3 else [])
        xp = np.pad(xf, pw, mode=mode, **({'constant_values': bv} if mode == 'constant' else {}))
        T = np.array([[1, 0, pad], [0, 1, pad], [0, 0, 1]], np.float64) @ Minv
        T = T / T[2, 2]
        coeffs = tuple(T.ravel()[:8])
        f = lambda c: np.asarray(Image.fromarray(np.ascontiguousarray(c, np.float32), 'F').transform(
            (w, h), Image.PERSPECTIVE, coeffs, Image.BICUBIC if interp in (INTER_CUBIC, INTER_LANCZOS4) else
            (Image.NEAREST if interp == INTER_NEAREST else Image.BILINEAR), fillcolor=float(bv)), np.float32)
        return _as_out(_per_channel(xp, f), x)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    den = Minv[2, 0] * xx + Minv[2, 1] * yy + Minv[2, 2]
    X = (Minv[0, 0] * xx + Minv[0, 1] * yy + Minv[0, 2]) / den
    Y = (Minv[1, 0] * xx + Minv[1, 1] * yy + Minv[1, 2]) / den
    f = lambda c: _sample_bilinear(c, X, Y, borderMode, bv)
    return _as_out(_per_channel(xf, f), x)


def warpAffine(x, M, dsize, flags=INTER_LINEAR, borderMode=BORDER_CONSTANT, borderValue=0):
    return warpPerspective(x, np.vstack([np.asarray(M, np.float64), [0, 0, 1]]), dsize, flags, borderMode, borderValue)


def connectedComponentsWithStats(m, connectivity=8):
    """Labels of the non-zero pixels (8-connected), with OpenCV's stats [x, y, w, h, area] and centroids."""
    m = np.asarray(m) > 0
    h, w = m.shape
    lab = np.zeros((h, w), np.int32)
    parent = [0]

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]; a = parent[a]
        return a
    prev_runs = []
    for y in range(h):
        row = m[y]
        if not row.any(): prev_runs = []; continue
        d = np.diff(np.r_[0, row.astype(np.int8), 0]); starts = np.nonzero(d == 1)[0]; ends = np.nonzero(d == -1)[0]
        runs = []
        for s, e in zip(starts, ends):
            ids = [pid for ps, pe, pid in prev_runs if ps <= e and pe >= s]   # 8-connected: touching diagonally too
            if ids:
                root = min(find(i) for i in ids)
                for i in ids: parent[find(i)] = root
                lid = root
            else:
                lid = len(parent); parent.append(lid)
            lab[y, s:e] = lid; runs.append((s, e, lid))
        prev_runs = runs
    roots = np.array([find(i) for i in range(len(parent))], np.int32)
    uniq = np.unique(roots[1:]) if len(parent) > 1 else np.array([], np.int32)
    remap = np.zeros(len(parent), np.int32); remap[uniq] = np.arange(1, len(uniq) + 1)
    lab = remap[roots[lab]] * (lab > 0)
    n = len(uniq) + 1
    stats = np.zeros((n, 5), np.int32); cen = np.zeros((n, 2), np.float64)
    ys, xs = np.nonzero(lab)
    L = lab[ys, xs]
    stats[0] = [0, 0, w, h, int((lab == 0).sum())]
    for i in range(1, n):
        sel = L == i; xi, yi = xs[sel], ys[sel]
        stats[i] = [xi.min(), yi.min(), xi.max() - xi.min() + 1, yi.max() - yi.min() + 1, len(xi)]
        cen[i] = [xi.mean(), yi.mean()]
    return n, lab, stats, cen


# ---- alignment without feature matching -------------------------------------------------------------------------

def _hp(g):
    g = g.astype(np.float64)
    return g - _box1d(_box1d(g, 6, 0, BORDER_REFLECT_101), 6, 1, BORDER_REFLECT_101)


def _phase(a, b):
    """Shift (dx, dy) that moves b onto a (sub-pixel, parabolic peak), and the peak height."""
    h, w = a.shape
    win = np.outer(np.hanning(h), np.hanning(w))
    A, B = np.fft.fft2(a * win), np.fft.fft2(b * win)
    R = A * np.conj(B); R /= np.abs(R) + 1e-9
    r = np.fft.ifft2(R).real
    py, px = np.unravel_index(int(np.argmax(r)), r.shape)
    def sub(m, c, p_):
        den = m - 2 * c + p_
        return 0.0 if abs(den) < 1e-12 else 0.5 * (m - p_) / den
    oy = sub(r[(py - 1) % h, px], r[py, px], r[(py + 1) % h, px]); ox = sub(r[py, (px - 1) % w], r[py, px], r[py, (px + 1) % w])
    dy = py if py <= h // 2 else py - h; dx = px if px <= w // 2 else px - w
    return float(dx + ox), float(dy + oy), float(r.max())


def _fit_h(src_pts, dst_pts):
    A = []
    for (x, y), (u, v) in zip(src_pts, dst_pts):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y, -u]); A.append([0, 0, 0, x, y, 1, -v * x, -v * y, -v])
    _, _, Vt = np.linalg.svd(np.array(A, np.float64))
    H = Vt[-1].reshape(3, 3)
    return H / H[2, 2]


def _refine(S, G0, T, sw, sh, grid=5):
    """After the global scale + shift, measure the remaining shift block by block (phase correlation on a grid) and fit
    a homography to the block centres - a small G warp (a slight shear or keystone) is then followed too."""
    Ga = _hp(warpPerspective(G0, T, (sw, sh), INTER_LINEAR, BORDER_REPLICATE))
    bw, bh = sw // grid, sh // grid
    src_pts, dst_pts, pk = [], [], []
    for j in range(grid):
        for i in range(grid):
            ys, xs = slice(j * bh, (j + 1) * bh), slice(i * bw, (i + 1) * bw)
            a, b = S[ys, xs], Ga[ys, xs]
            if a.std() < 1.0 or b.std() < 1.0: continue
            dx, dy, p_ = _phase(a, b)
            if p_ < 0.08 or abs(dx) > bw / 4 or abs(dy) > bh / 4: continue
            cx, cy = (i + 0.5) * bw, (j + 0.5) * bh
            src_pts.append((cx - dx, cy - dy)); dst_pts.append((cx, cy)); pk.append(p_)   # aligned-G point -> source point
    if len(src_pts) < 8: return T
    src_pts, dst_pts = np.array(src_pts), np.array(dst_pts)
    keep = np.ones(len(src_pts), bool)
    for _ in range(3):                                            # drop blocks that disagree (redrawn content)
        Hc = _fit_h(src_pts[keep], dst_pts[keep])
        q = np.c_[src_pts, np.ones(len(src_pts))] @ Hc.T; q = q[:, :2] / q[:, 2:3]
        err = np.hypot(*(q - dst_pts).T)
        keep = err < max(1.0, 2.5 * float(np.median(err[keep])))
        if keep.sum() < 8: return T
    Hc = _fit_h(src_pts[keep], dst_pts[keep])
    return Hc @ T


def register(src, g, long_edge=640):
    """Align G to the source photo: G is first brought to the source's size (hosts often return a slightly different
    size), then a small scale search (0.92..1.08) with FFT phase correlation for the shift. Returns (H, score, ncc):
    H maps source pixels to G pixels (as look_transfer.register's ORB homography does), ncc is the high-pass
    correlation after alignment (a re-toned G of the same scene: about 0.5-0.9; another scene: below 0.2)."""
    hs, ws = src.shape[:2]; hg, wg = g.shape[:2]
    k = long_edge / max(hs, ws)
    sw, sh = max(32, int(round(ws * k))), max(32, int(round(hs * k)))
    gray = lambda x: cvtColor(np.clip(x * 255 if x.dtype != np.uint8 else x, 0, 255).astype(np.float32), COLOR_RGB2GRAY)
    S = _hp(resize(gray(src), (sw, sh), INTER_AREA)); G0 = resize(gray(g), (sw, sh), INTER_AREA)
    best = None
    for sc in np.arange(0.92, 1.0801, 0.01):
        M = np.array([[sc, 0, (1 - sc) * sw / 2], [0, sc, (1 - sc) * sh / 2]])   # G scaled about its centre
        Gs = _hp(warpAffine(G0, M, (sw, sh), INTER_LINEAR, BORDER_REPLICATE))
        dx, dy, pk = _phase(S, Gs)
        T = np.array([[1, 0, dx], [0, 1, dy], [0, 0, 1.0]]) @ np.vstack([M, [0, 0, 1]])
        Ga = _hp(warpPerspective(G0, T, (sw, sh), INTER_LINEAR, BORDER_REPLICATE))
        mg = 0.08; ys, xs = slice(int(sh * mg), int(sh * (1 - mg))), slice(int(sw * mg), int(sw * (1 - mg)))
        a, b = S[ys, xs].ravel(), Ga[ys, xs].ravel()
        ncc = float(np.dot(a - a.mean(), b - b.mean()) / (np.linalg.norm(a - a.mean()) * np.linalg.norm(b - b.mean()) + 1e-9))
        if best is None or ncc > best[0]: best = (ncc, T)
    ncc, T = best
    T2 = _refine(S, G0, T, sw, sh)
    if T2 is not T:
        Ga = _hp(warpPerspective(G0, T2, (sw, sh), INTER_LINEAR, BORDER_REPLICATE))
        mg = 0.08; ys, xs = slice(int(sh * mg), int(sh * (1 - mg))), slice(int(sw * mg), int(sw * (1 - mg)))
        a, b = S[ys, xs].ravel(), Ga[ys, xs].ravel()
        n2 = float(np.dot(a - a.mean(), b - b.mean()) / (np.linalg.norm(a - a.mean()) * np.linalg.norm(b - b.mean()) + 1e-9))
        if n2 >= ncc: ncc, T = n2, T2
    # T maps G (at the small source-shaped grid) onto the source; invert it, then scale to full-size pixels
    Hs = np.linalg.inv(T)                                                     # source (small) -> G (small, source-shaped)
    H = np.diag([wg / sw, hg / sh, 1.0]) @ Hs @ np.diag([sw / ws, sh / hs, 1.0])
    return H, ncc


def lite_inliers(ncc, need):
    """A pass/fail number on the same scale as the ORB inlier counts the tools compare against ('need' is the ORB
    threshold): need is reached at ncc 0.40, zero at ncc 0.20."""
    return int(round(max(0.0, (ncc - 0.20) / 0.20) * need))
