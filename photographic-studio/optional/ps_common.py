"""Photographic Studio - shared colour and filter helpers. Pure numpy + Pillow (no OpenCV / scikit-image),
so the measuring and grading tools run on any agent that has Python."""
import hashlib
from pathlib import Path
import numpy as np
from PIL import Image, ImageOps


def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def load_rgb(p):
    """sRGB float array 0..1, EXIF orientation applied, alpha dropped."""
    im = ImageOps.exif_transpose(Image.open(p)).convert('RGB')
    return np.asarray(im).astype(np.float32) / 255.0


def save_png(a, p):
    Image.fromarray(np.uint8(np.clip(np.rint(a * 255.0), 0, 255))).save(p)


def to_linear(s):
    return np.where(s <= 0.04045, s / 12.92, ((s + 0.055) / 1.055) ** 2.4).astype(np.float32)


def to_srgb(l):
    l = np.clip(l, 0, None)
    return np.where(l <= 0.0031308, l * 12.92, 1.055 * np.power(l, 1 / 2.4) - 0.055).astype(np.float32)


_M = np.array([[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]], np.float32)
_MI = np.linalg.inv(_M).astype(np.float32)
_WHITE = np.array([0.95047, 1.0, 1.08883], np.float32)


def lin_to_lab(lin):
    xyz = lin @ _M.T / _WHITE
    f = np.where(xyz > 0.008856, np.cbrt(np.clip(xyz, 0, None)), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1).astype(np.float32)


def lab_to_lin(lab):
    fy = (lab[..., 0] + 16) / 116
    fx, fz = fy + lab[..., 1] / 500, fy - lab[..., 2] / 200
    f = np.stack([fx, fy, fz], -1)
    xyz = np.where(f > 0.206893, f ** 3, (f - 16 / 116) / 7.787) * _WHITE
    return (xyz @ _MI.T).astype(np.float32)


def srgb_to_lab(s):
    return lin_to_lab(to_linear(s))


def box(x, r):
    """Mean filter of radius r (window 2r+1) with reflected borders, via an integral image."""
    r = int(max(1, r))
    p = np.pad(x.astype(np.float64), ((r + 1, r), (r + 1, r)), mode='reflect')
    c = p.cumsum(0).cumsum(1)
    n = 2 * r + 1
    return ((c[n:, n:] - c[:-n, n:] - c[n:, :-n] + c[:-n, :-n]) / (n * n)).astype(np.float32)


def blur(x, r):
    """Three box passes: close to a Gaussian of sigma ~ r."""
    r = int(max(1, round(r * 0.6)))
    return box(box(box(x, r), r), r)


def guided(I, p, r, eps):
    """Edge-aware smoothing of p guided by I (I in 0..1)."""
    mI, mp = box(I, r), box(p, r)
    a = (box(I * p, r) - mI * mp) / (box(I * I, r) - mI * mI + eps)
    b = mp - a * mI
    return box(a, r) * I + box(b, r)


def structure_corr(a_L, b_L):
    """Correlation of mid-scale structure between two L images of the same size."""
    step = max(1, min(a_L.shape) // 300)
    a, b = a_L[::step, ::step], b_L[::step, ::step]
    ha, hb = a - blur(a, 6), b - blur(b, 6)
    ha, hb = ha - ha.mean(), hb - hb.mean()
    return float((ha * hb).mean() / (ha.std() * hb.std() + 1e-9))


HUES = {'red': 30, 'orange': 60, 'yellow': 95, 'green': 140, 'cyan': 200, 'blue': 275, 'purple': 310, 'magenta': 345}


def hue_weight(h_deg, centre, width=30.0):
    d = np.abs((h_deg - centre + 180) % 360 - 180)
    return np.where(d < width, 0.5 * (1 + np.cos(np.pi * d / width)), 0.0).astype(np.float32)


# --- drop-in replacements for skimage.color.rgb2lab / lab2rgb (v0.3.5: removes the scikit-image dependency) ---
_M64 = np.array([[0.412453, 0.357580, 0.180423], [0.212671, 0.715160, 0.072169], [0.019334, 0.119193, 0.950227]], np.float64)
_MI64 = np.linalg.inv(_M64)
_W64 = np.array([0.95047, 1.0, 1.08883], np.float64)


def _ft(x):
    x = np.asarray(x)
    return x.astype(np.float32, copy=False) if x.dtype == np.float32 else x.astype(np.float64)       # keep float32 like scikit-image does


def rgb2lab(rgb):
    """sRGB in 0..1 -> CIELAB (D65, 2 deg). Same formulas, constants and precision as scikit-image."""
    rgb = _ft(rgb); dt = rgb.dtype
    lin = rgb / 12.92
    m = rgb > 0.04045
    lin[m] = np.power((rgb[m] + 0.055) / 1.055, 2.4)
    xyz = lin @ _M64.T.astype(dt)
    xyz = xyz / _W64.astype(dt)
    f = 7.787 * xyz + 16.0 / 116.0
    m = xyz > 0.008856
    f[m] = np.cbrt(xyz[m])
    return np.stack([116.0 * f[..., 1] - 16.0, 500.0 * (f[..., 0] - f[..., 1]), 200.0 * (f[..., 1] - f[..., 2])], -1).astype(dt)


def lab2rgb(lab):
    """CIELAB -> sRGB in 0..1 (clipped). Same formulas, constants and precision as scikit-image."""
    lab = _ft(lab); dt = lab.dtype
    fy = (lab[..., 0] + 16.0) / 116.0
    fx, fz = lab[..., 1] / 500.0 + fy, fy - lab[..., 2] / 200.0
    fz = np.maximum(fz, 0)
    f = np.stack([fx, fy, fz], -1)
    xyz = (f - 16.0 / 116.0) / 7.787
    m = f > 0.2068966
    xyz[m] = np.power(f[m], 3.0)
    xyz = xyz * _W64.astype(dt)
    lin = xyz @ _MI64.T.astype(dt)
    rgb = lin * 12.92
    m = lin > 0.0031308
    rgb[m] = 1.055 * np.power(lin[m], 1 / 2.4) - 0.055
    return np.clip(rgb, 0, 1).astype(dt)
