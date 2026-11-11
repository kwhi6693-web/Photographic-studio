#!/usr/bin/env python3
"""Photographic Studio v0.1.5 - deterministic, non-generative N trim after G.
Usage: python3 -I n_trim.py INPUT_IMAGE OUTPUT_PNG [RECEIPT_JSON] [--force]
v0.1.5: runs only when the input has clipping overshoot (any channel == 255 on more than 0.1% of pixels).
Otherwise prints verdict SKIP, writes NO output image: deliver the INPUT and label it G. --force overrides.
Does: reduce warm/golden chroma (max 12%) and soften highlights (L* and a gentle RGB knee).
Does NOT: sharpen, add grain/texture, resize, crop, or call any generative model.
Prints a JSON report with the actual parameters, environment versions and checks (n_trim.md section 3)
and a PASS/FAIL verdict. On FAIL, deliver the INPUT image (label it 'G'), not the output.
Initial values come from ONE test (R1, water photo). Limits are provisional, not validated."""
import hashlib, json, platform, sys
from pathlib import Path
import cv2
import numpy as np
from PIL import Image
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent))
from ps_common import rgb2lab, lab2rgb   # v0.3.5: no scikit-image

PARAMS = {
    'warm_b_start': 6.0, 'warm_b_ramp': 12.0,
    'warm_a_start': -6.0, 'warm_a_ramp': 12.0,
    'warm_chroma_reduction_max': 0.12,
    'highlight_L_start': 60.0, 'highlight_L_ramp': 25.0,
    'highlight_L_reduction_max': 1.8,
    'rgb_knee_start': 0.965, 'rgb_knee_slope': 0.50,
    'sharpness': 0, 'grain': 0, 'resize': False, 'crop': False,
}
LIMITS = {'abs_mean_dL_max': 3.0, 'chroma_ratio_min': 0.80, 'chroma_ratio_max': 1.00,
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
    warm = (np.clip((b - p['warm_b_start']) / p['warm_b_ramp'], 0, 1)
            * np.clip((a - p['warm_a_start']) / p['warm_a_ramp'], 0, 1))
    cf = 1.0 - p['warm_chroma_reduction_max'] * warm
    t = np.clip((L - p['highlight_L_start']) / p['highlight_L_ramp'], 0, 1)
    L_new = L - p['highlight_L_reduction_max'] * smoothstep(t)
    rgb = lab2rgb(np.stack((L_new, a * cf, b * cf), axis=-1))
    k, s = p['rgb_knee_start'], p['rgb_knee_slope']
    rgb = np.where(rgb > k, k + s * (rgb - k), rgb)
    out8 = np.uint8(np.clip(np.rint(rgb * 255.0), 0, 255))
    Image.fromarray(out8, mode='RGB').save(dst, format='PNG')
    assert Image.open(dst).size == img.size, 'dimensions changed'

    act = rgb2lab(out8.astype(np.float64) / 255.0)
    dL = act[..., 0] - L
    c0, c1 = np.hypot(a, b), np.hypot(act[..., 1], act[..., 2])
    g = lambda x: cv2.resize(cv2.cvtColor(x, cv2.COLOR_RGB2GRAY), (288, 384),
                             interpolation=cv2.INTER_AREA).astype(np.float64)
    m = {
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
        'chroma_ratio': LIMITS['chroma_ratio_min'] <= m['chroma_ratio'] <= LIMITS['chroma_ratio_max'],
        'clipping': m['clip_any255_fraction_out'] <= LIMITS['clip_fraction_max']
                    and m['clip_any255_fraction_out'] <= m['clip_any255_fraction_in'],
        'structure': m['structure_corr_288x384'] >= LIMITS['structure_corr_min'],
    }
    ok = all(checks.values())
    report = {
        'input': {'file': src.name, 'sha256': sha256(src), 'size': list(img.size)},
        'output': {'file': dst.name, 'sha256': sha256(dst), 'size': list(Image.open(dst).size)},
        'trigger': {'clip_any255_fraction_in': clip_in, 'threshold': LIMITS['clip_fraction_max'], 'forced': force},
        'parameters': PARAMS, 'limits': LIMITS, 'measurements': m, 'checks': checks,
        'verdict': 'PASS: N executed and within limits (label may be G->N)' if ok
                   else 'FAIL: deliver the INPUT image and label it G (not G->N)',
        'environment': {'python': platform.python_version(), 'pillow': Image.__version__,
                        'numpy': np.__version__, 'opencv': cv2.__version__},
        'note': 'Provisional values from one water-photo test; hashes identify files, they do not prove cross-environment byte reproducibility.',
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if receipt:
        receipt.write_text(text, encoding='utf-8')
    print(text)


if __name__ == '__main__':
    main()
