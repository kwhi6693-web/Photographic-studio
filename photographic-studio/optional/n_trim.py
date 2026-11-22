#!/usr/bin/env python3
"""Photographic Studio v1.4.0 - deterministic, non-generative N trim after G: a highlight shoulder only.
Usage: python3 -I n_trim.py INPUT_IMAGE OUTPUT_PNG [RECEIPT_JSON] [--force]
Runs only when the input has clipping overshoot (any channel == 255 on more than 0.1% of pixels).
Otherwise prints verdict SKIP, writes NO output image: deliver the INPUT. --force overrides.
v1.4.0 (2026-11-22 courtyard: to remove 0.2 % clipped pixels the old trim lowered every lit face by 1.8 L* and cut
7.3 % of the colour): it now rolls off only the very top of the highlights - L* above 92, softly compressed towards
~98.5 - and the RGB knee acts only on those pixels. Mid-tones (L* < 88) are not touched; chroma is not reduced.
Does NOT: sharpen, add grain/texture, resize, crop, or call any generative model.
On FAIL, deliver the INPUT image, not the output."""
import hashlib, json, platform, sys
from pathlib import Path
try:
    import cv2
except ImportError:   # v1.2.9: no OpenCV on the host - numpy + Pillow stand-in
    sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__))); import cvlite as cv2
import numpy as np
from PIL import Image
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent))
from ps_common import rgb2lab, lab2rgb   # v0.3.5: no scikit-image

PARAMS = {
    'shoulder_L': 92.0, 'shoulder_room': 6.5,        # L* above 92 rolls off towards 98.5
    'knee_weight_L': [88.0, 94.0],                   # the RGB knee fades in over these L*
    'rgb_knee_start': 0.965, 'rgb_knee_slope': 0.50,
    'sharpness': 0, 'grain': 0, 'resize': False, 'crop': False,
}
LIMITS = {'abs_mean_dL_max': 1.0, 'midtone_max_abs_dL': 0.5, 'chroma_ratio_min': 0.985, 'chroma_ratio_max': 1.005,
          'clip_fraction_max': 0.001, 'structure_corr_min': 0.98}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def smoothstep(t):
    return t * t * (3.0 - 2.0 * t)


def clip_frac(rgb8):
    return float(np.mean(np.any(rgb8 == 255, axis=2)))


def main():
    force = '--force' in sys.argv
    args = [a for a in sys.argv[1:] if a != '--force']
    src, dst = Path(args[0]), Path(args[1])
    receipt = Path(args[2]) if len(args) > 2 else None
    img = Image.open(src).convert('RGB')
    rgb8 = np.asarray(img, dtype=np.uint8)
    clip_in = clip_frac(rgb8)
    if clip_in <= LIMITS['clip_fraction_max'] and not force:
        report = {'input': {'file': src.name, 'sha256': sha256(src), 'size': list(img.size)}, 'output': None,
                  'trigger': {'clip_any255_fraction_in': clip_in, 'threshold': LIMITS['clip_fraction_max'], 'forced': False},
                  'verdict': 'SKIP: no clipping overshoot; N not executed, deliver the INPUT image and label it G'}
        text = json.dumps(report, ensure_ascii=False, indent=2)
        if receipt:
            receipt.write_text(text, encoding='utf-8')
        print(text)
        return
    lab = rgb2lab(rgb8.astype(np.float64) / 255.0)
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    p = PARAMS
    s0, room = p['shoulder_L'], p['shoulder_room']
    L_new = np.where(L > s0, s0 + room * np.tanh((L - s0) / room), L)
    rgb = lab2rgb(np.stack((L_new, a, b), axis=-1))
    k, s = p['rgb_knee_start'], p['rgb_knee_slope']
    lo_, hi_ = p['knee_weight_L']
    wk = np.clip((L - lo_) / (hi_ - lo_), 0, 1)[..., None]
    rgb = np.where(rgb > k, rgb + wk * ((k + s * (rgb - k)) - rgb), rgb)
    out8 = np.uint8(np.clip(np.rint(rgb * 255.0), 0, 255))
    Image.fromarray(out8, mode='RGB').save(dst, format='PNG')
    assert Image.open(dst).size == img.size, 'dimensions changed'

    act = rgb2lab(out8.astype(np.float64) / 255.0)
    dL = act[..., 0] - L
    c0, c1 = np.hypot(a, b), np.hypot(act[..., 1], act[..., 2])
    g = lambda x: cv2.resize(cv2.cvtColor(x, cv2.COLOR_RGB2GRAY), (288, 384),
                             interpolation=cv2.INTER_AREA).astype(np.float64)
    mid = L < 88.0
    m = {
        'midtone_max_abs_dL': float(np.abs(dL[mid]).max()) if mid.any() else 0.0,
        'L_star_mean_change': float(dL.mean()),
        'L_star_mean_abs_change': float(np.abs(dL).mean()),
        'L_star_max_abs_change': float(np.abs(dL).max()),
        'chroma_ratio': float(c1.mean() / c0.mean()),
        'clip_any255_fraction_in': clip_frac(rgb8),
        'clip_any255_fraction_out': clip_frac(out8),
        'structure_corr_288x384': float(np.corrcoef(g(rgb8).ravel(), g(out8).ravel())[0, 1]),
    }
    checks = {
        'abs_mean_dL': abs(m['L_star_mean_change']) <= LIMITS['abs_mean_dL_max'],
        'midtones_untouched': m['midtone_max_abs_dL'] <= LIMITS['midtone_max_abs_dL'],
        'chroma_ratio': LIMITS['chroma_ratio_min'] <= m['chroma_ratio'] <= LIMITS['chroma_ratio_max'],
        'clipping': m['clip_any255_fraction_out'] <= m['clip_any255_fraction_in']
                    and (m['clip_any255_fraction_out'] <= LIMITS['clip_fraction_max']
                         or m['clip_any255_fraction_out'] <= 0.5 * m['clip_any255_fraction_in']),
        'structure': m['structure_corr_288x384'] >= LIMITS['structure_corr_min'],
    }
    ok = all(checks.values())
    report = {
        'input': {'file': src.name, 'sha256': sha256(src), 'size': list(img.size)},
        'output': {'file': dst.name, 'sha256': sha256(dst), 'size': list(Image.open(dst).size)},
        'trigger': {'clip_any255_fraction_in': clip_in, 'threshold': LIMITS['clip_fraction_max'], 'forced': force},
        'parameters': PARAMS, 'limits': LIMITS, 'measurements': m, 'checks': checks,
        'verdict': 'PASS: highlight shoulder applied (L* > 92 only)' if ok
                   else 'FAIL: deliver the INPUT image',
        'environment': {'python': platform.python_version(), 'pillow': Image.__version__,
                        'numpy': np.__version__, 'opencv': getattr(cv2, '__version__', '?')},
        'tool': 'n_trim.py v1.4.0 (highlight shoulder only)',
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if receipt:
        receipt.write_text(text, encoding='utf-8')
    print(text)


if __name__ == '__main__':
    main()
