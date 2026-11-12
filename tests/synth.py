"""Synthetic scenes with known ground truth, and defect injectors, for testing the Photographic Studio tools.
Everything is generated from fixed seeds: no photo, no download, identical on every machine."""
import numpy as np
from PIL import Image, ImageFilter

H, W = 480, 640


def _tex(seed, scale):
    return np.random.default_rng(seed).normal(0, scale, (H, W)).astype(np.float32)


def _blur(a, r):
    im = Image.fromarray(np.uint8(np.clip(a, 0, 1) * 255))
    return np.asarray(im.filter(ImageFilter.GaussianBlur(r))).astype(np.float32) / 255.0


def _details(img, seed, mask, n, lo, hi):
    """Small rectangles ('windows', ornaments) inside mask: multiply the local colour, so light and shade stay ordered.
    They give the scene corners and edges, which the alignment step of look_transfer.py needs."""
    rng = np.random.default_rng(seed)
    ys, xs = np.nonzero(mask)
    for _ in range(n):
        k = rng.integers(len(ys)); y0, x0 = ys[k], xs[k]
        h, w = rng.integers(5, 16), rng.integers(5, 16)
        sl = (slice(y0, min(y0 + h, H)), slice(x0, min(x0 + w, W)))
        img[sl] = np.where(mask[sl][..., None], img[sl] * rng.uniform(lo, hi), img[sl])
    return img


def day():
    """Blue sky (lighter towards the horizon), warm sunlit wall on the right, cooler shaded wall on the left."""
    y, x = np.mgrid[0:H, 0:W]
    img = np.zeros((H, W, 3), np.float32)
    sky = y < 180
    g = y / 180.0
    for c, (a, b) in enumerate([(0.35, 0.35), (0.55, 0.25), (0.85, 0.10)]):
        img[..., c] = np.where(sky, a + b * g, 0)
    lit, shade = (~sky) & (x >= 320), (~sky) & (x < 320)
    t = _tex(1, 0.03)
    for c, (a, b) in enumerate([(0.78, 0.20), (0.62, 0.24), (0.42, 0.32)]):
        img[..., c] = np.where(lit, a + t, img[..., c])
        img[..., c] = np.where(shade, b + 0.5 * t, img[..., c])
    img = _details(img, 11, lit | shade, 260, 0.55, 0.9)
    return np.clip(img, 0, 1)


def museum():
    """Near-black background with one lit, coloured, textured object in the middle. No other light exists."""
    y, x = np.mgrid[0:H, 0:W]
    img = np.full((H, W, 3), 0.025, np.float32) + _tex(2, 0.004)[..., None]
    d = ((x - 320) / 110.0) ** 2 + ((y - 250) / 150.0) ** 2
    obj = d < 1
    shade = np.clip(1.15 - 0.6 * d + (320 - x) / 500.0, 0.25, 1.2)
    t = _tex(3, 0.04)
    for c, v in enumerate((0.16, 0.30, 0.70)):
        img[..., c] = np.where(obj, v * shade + t, img[..., c])
    img = _details(img, 12, obj, 220, 0.5, 1.25)
    return np.clip(img, 0, 1)


def night():
    """Black sky, a lit tower, small warm lamps, dark ground."""
    y, x = np.mgrid[0:H, 0:W]
    img = np.full((H, W, 3), 0.012, np.float32) + _tex(4, 0.003)[..., None]
    tower = (abs(x - 320) < 30) & (y > 80) & (y < 380)
    img[tower] = np.array([0.80, 0.84, 0.90], np.float32)
    blocks = (y > 300) & (y < 410) & ((x < 250) | (x > 390))
    img[blocks] = np.array([0.10, 0.09, 0.08], np.float32)
    img = _details(img, 13, tower, 90, 0.35, 0.8)
    img = _details(img, 14, blocks, 200, 1.8, 6.0)
    for cx in (90, 200, 450, 560):
        lamp = (x - cx) ** 2 + (y - 400) ** 2 < 30
        img[lamp] = np.array([1.0, 0.75, 0.35], np.float32)
    ground = (y > 410)
    img[ground] += 0.03 + _tex(5, 0.01)[ground][..., None]
    return np.clip(img, 0, 1)


SCENES = {'day': day, 'museum': museum, 'night': night}

# ---- honest edits (should pass) -------------------------------------------------------------------------------


def good_edit(a):
    """A plain, global, monotonic lift of contrast and colour: what a careful retoucher would do."""
    m = a.mean(-1, keepdims=True)
    b = m + (a - m) * 1.25
    return np.clip(b, 0, 1) ** 0.92

# ---- defects (each breaks one stated rule; a checker should object) -------------------------------------------


def invented_spotlight(a):
    """A glowing oval on a part of the frame where the original has no light."""
    y, x = np.mgrid[0:H, 0:W]
    glow = np.exp(-(((x - 120) / 80.0) ** 2 + ((y - 120) / 60.0) ** 2))
    return np.clip(a + 0.22 * glow[..., None], 0, 1)


def rim_glow(a):
    """Light bleeding from bright things onto the dark around them (the 'fake ring of light' around an exhibit)."""
    L = a.mean(-1)
    return np.clip(a + 0.9 * np.maximum(_blur(L, 16) - L, 0)[..., None], 0, 1)


def edge_halo(a):
    """Bright rims hugging strong edges (over-done local contrast)."""
    L = a.mean(-1)
    return np.clip(a + 2.2 * (L - _blur(L, 14))[..., None] * (np.abs(L - _blur(L, 14)) > 0.02)[..., None], 0, 1)


def tone_inversion(a):
    """Shadows lifted above the lights: the order of bright and dark areas flips."""
    L = a.mean(-1, keepdims=True)
    return np.clip(a * (0.35 / np.maximum(_blur(L[..., 0], 25), 0.02))[..., None], 0, 1)


def flat_hdr(a):
    """Lit and shaded areas pulled to the same brightness."""
    L = _blur(a.mean(-1), 30)[..., None]
    return np.clip(a * (0.45 / np.maximum(L, 0.03)) ** 0.85, 0, 1)


def removed_light(a):
    """Real highlights and lamps pressed down so they are no longer the brightest things."""
    return np.minimum(a, 0.45)


def dark_blotch(a, cx=480, cy=330):
    """An off-centre dark patch no light would cause (put it on something that is lit, or it shows nothing)."""
    y, x = np.mgrid[0:H, 0:W]
    hole = np.exp(-(((x - cx) / 90.0) ** 2 + ((y - cy) / 70.0) ** 2))
    return np.clip(a * (1 - 0.55 * hole[..., None]), 0, 1)


def warm_shade(a):
    """Shade turned warmer than the sunlit side."""
    b = a.copy()
    y, x = np.mgrid[0:H, 0:W]
    m = ((y >= 180) & (x < 320))
    b[..., 0] = np.where(m, b[..., 0] * 1.5, b[..., 0])
    b[..., 2] = np.where(m, b[..., 2] * 0.55, b[..., 2])
    return np.clip(b, 0, 1)


def smoothed_texture(a):
    """Fine texture wiped (the 'AI look')."""
    return np.stack([_blur(a[..., c], 2.5) for c in range(3)], -1)


def save(a, path):
    Image.fromarray(np.uint8(np.clip(np.rint(a * 255), 0, 255))).save(path)
    return path
