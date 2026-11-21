"""Photographic Studio - shared colour and filter helpers. numpy + Pillow; OpenCV is used for speed when present
(v1.2.4: same results, the box filter falls back to numpy without it), so the measuring and grading tools still run
on any agent that has Python."""
import hashlib
from pathlib import Path
import numpy as np
from PIL import Image, ImageOps
try:
    import cv2 as _cv2
except ImportError:
    _cv2 = None


def daylight_sky(L):
    """v1.0.2: True when the upper half of the frame holds open bright sky or daylight (L* > 75 on at least 8%).
    A dark frame with daylight in it is a backlit day scene, not a night scene: its shadows are filled by the sky.
    (Ten test photos plus five real runs: night and museum frames reach at most 4.6%; a backlit garden 10.8%.)"""
    h = L.shape[0]
    return bool((L[: h // 2] > 75).mean() >= 0.08)


def sky_mask(L, gaps=False):
    """v1.2.7: the bright, smooth sky connected to the top edge (overcast or pale sky; from L* alone; rough). Found on a
    small copy by flooding from the top row through bright, untextured pixels, so overhanging branches at the top and
    trees in front do not stop it, and a white wall lower down that does not touch the sky is not taken for it."""
    h, w = L.shape
    k = max(1, int(round(max(h, w) / 240)))
    hs, ws = h // k, w // k
    Ls = L[:hs * k, :ws * k].reshape(hs, k, ws, k).mean((1, 3))
    tex = np.abs(Ls - blur(Ls, 2))
    ok = (Ls > 68) & (tex < 3.0)
    ok[int(hs * 0.75):] = False                      # the sky is not in the bottom quarter
    m = np.zeros_like(ok); m[0] = ok[0]
    for _ in range(4 * max(hs, ws)):
        g = m.copy()
        g[1:] |= m[:-1]; g[:-1] |= m[1:]; g[:, 1:] |= m[:, :-1]; g[:, :-1] |= m[:, 1:]
        g &= ok
        if (g == m).all(): break
        m = g
    if m.mean() < 0.03: return np.zeros((h, w), bool)
    big = np.repeat(np.repeat(m, k, 0), k, 1)
    out = np.zeros((h, w), bool); out[:big.shape[0], :big.shape[1]] = big
    if big.shape[0] < h: out[big.shape[0]:, :big.shape[1]] = big[-1:]
    if big.shape[1] < w: out[:, big.shape[1]:] = out[:, big.shape[1] - 1:big.shape[1]]
    out = out & (L > 60)
    if gaps and out.any():
        # bits of the same sky seen between leaves and branches, in the rows the sky reaches, are sky too
        low = int(np.nonzero(out.any(1))[0].max()) + 1
        g = np.zeros_like(out); g[:low] = L[:low] > max(78.0, float(np.percentile(L[out], 5)) - 4)
        out = out | g
    return out


def light_character(L, C=None):
    """v1.3.0 (key light): is the original's light directional (a side light, a window, a lamp - there is a light/shade
    structure to build the subject's light on) or diffuse (a flat overcast or grey-sky day, or a frame whose land has
    hardly any large-scale light difference)? Judged on a small copy, on the land only. A diffuse frame gets a quieter
    key light (user 2026-11-21: no spotlight on a rain-mist pagoda - mostly the edges and foreground recede)."""
    h, w = L.shape
    k = max(1, int(round(max(h, w) / 640)))
    sm = lambda z: z[:h // k * k, :w // k * k].reshape(h // k, k, w // k, k).mean((1, 3)) if k > 1 else z
    Ls = sm(L)
    sky = sky_mask(Ls, gaps=True); land = ~sky
    if land.mean() < 0.05: return {'light': 'diffuse', 'land_spread': 0.0, 'grey_sky': True, 'sky_fraction': round(float(sky.mean()), 3)}
    Lb = blur(Ls, max(8, min(Ls.shape) // 12))
    spread = float(np.percentile(Lb[land], 90) - np.percentile(Lb[land], 10))
    # a grey or white sky (overcast, rain, mist); a blue or sunset sky is daylight with a direction
    grey_sky = bool(sky.mean() > 0.10 and (C is None or float(sm(C)[sky].mean()) < 6.0))
    light = 'diffuse' if (grey_sky or spread < 18) else 'directional'
    return {'light': light, 'land_spread': round(spread, 1), 'grey_sky': grey_sky, 'sky_fraction': round(float(sky.mean()), 3)}


def tone_needs(L):
    """v1.2.7 (shared by grade.py "auto" and intensity_check.py): what an original's own tones ask for, judged on the
    land only - a bright sky above a grey forest or street would otherwise make the photo look "wide range" (user
    2026-11-20: everyday flat photos are mostly a bright sky over grey ground).
    veil: how far the land's darkest tones sit above black; flat: the land's darks-to-lights range is narrow.
    stretch_ok (narrow land range OR lifted blacks) is the only condition under which the tones may be opened up and
    the brightness/colour limits relax; every other photo keeps its limits. sky_p5: where the sky begins (the land's
    tones may be opened up to just below it, the sky itself stays as it is). A night or low-key frame (mean L* < 25)
    asks for none of this."""
    mean = float(L.mean())
    sky = sky_mask(L, gaps=True)
    land = L[~sky] if (~sky).mean() > 0.3 else L.ravel()
    lo, hi = float(np.percentile(land, 0.5)), float(np.percentile(land, 99.7))
    rng = float(np.percentile(land, 99) - np.percentile(land, 1))
    core = sky_mask(L)
    sk = {'sky_fraction': float(sky.mean()), 'sky_p5': float(np.percentile(L[core], 5)) if core.any() else None}
    if mean < 25:
        return {'veil': 0.0, 'flat': False, 'stretch_ok': False, 'night': True, 'p0.5': lo, 'p99.7': hi, 'range': rng, **sk}
    veil = max(0.0, lo - 6.0) if lo > 8 else 0.0
    return {'veil': veil, 'flat': rng < 60, 'stretch_ok': rng < 60 or veil > 0, 'night': False, 'p0.5': lo, 'p99.7': hi, 'range': rng, **sk}


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
    """Mean filter of radius r (window 2r+1) with reflected borders. v1.2.4: OpenCV when present - the same result
    (max difference 6e-8 on a 1152x1440 test) about ten times faster; numpy integral image otherwise."""
    r = int(max(1, r))
    if _cv2 is not None:
        return _cv2.blur(np.ascontiguousarray(x, np.float32), (2 * r + 1, 2 * r + 1), borderType=_cv2.BORDER_REFLECT_101)
    # v1.2.9: separable running sums (same result, about 30 % faster; this path is what a host without OpenCV runs)
    n = 2 * r + 1
    c = np.cumsum(np.pad(np.asarray(x, np.float32), ((r + 1, r), (0, 0)), mode='reflect'), 0, dtype=np.float64)
    y = c[n:] - c[:-n]
    c = np.cumsum(np.pad(y, ((0, 0), (r + 1, r)), mode='reflect'), 1)
    return ((c[:, n:] - c[:, :-n]) / (n * n)).astype(np.float32)


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


# v2.1.0: run a sibling tool in this process when it can (no interpreter start-up per call), else in a separate one.
_TOOL_MODS = {}
_INPROC = ('grade.py', 'intensity_check.py', 'physics_check.py', 'look_transfer.py', 'keep_regions.py')


def run_tool(tool, *args):
    import contextlib, importlib, io, json, subprocess, sys
    from pathlib import Path
    here = Path(__file__).resolve().parent
    sys.dont_write_bytecode = True   # v1.2.4: no __pycache__ inside the installed package (keeps its hash list exact)
    if tool in _INPROC:
        try:
            name = tool[:-3]
            if str(here) not in sys.path: sys.path.insert(0, str(here))
            if name not in _TOOL_MODS: _TOOL_MODS[name] = importlib.import_module(name)
            m, buf = _TOOL_MODS[name], io.StringIO()
            with contextlib.redirect_stdout(buf):
                if name == 'grade':
                    m.main(*map(str, args[:3]), *(map(str, args[3:4])))
                else:
                    old = sys.argv; sys.argv = [tool, *map(str, args)]
                    try: m.main()
                    finally: sys.argv = old
            return json.loads(buf.getvalue())
        except Exception:
            pass
    p = subprocess.run([sys.executable, '-B', str(here / tool), *map(str, args)], capture_output=True, text=True)
    try:
        return json.loads(p.stdout)
    except Exception:
        return {'verdict': 'TOOL_ERROR', 'stderr': p.stderr[-400:]}
