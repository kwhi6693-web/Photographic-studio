"""Final lightness-only recovery for the v1.4.2 delivery pipeline."""
from pathlib import Path
import shutil

import numpy as np
from PIL import Image

from ps_common import lab_to_lin, load_rgb, srgb_to_lab, to_srgb

MAX_LIFT = 8.0
HIGHLIGHT_LIMIT = 80.0
LUMA = np.array([.2126729, .7151522, .072175], dtype=np.float32)


def smoothstep(x):
    t = np.clip(x, 0, 1)
    return t * t * (3 - 2 * t)


def render(lab, original, weight, lift):
    adjusted = lab.copy()
    adjusted[..., 0] += weight * lift
    linear = lab_to_lin(adjusted)
    grey = np.clip(linear @ LUMA, 0, 1)[..., None]
    high, low = linear.max(-1, keepdims=True), linear.min(-1, keepdims=True)
    gain = np.minimum(1, np.minimum(
        np.where(high > 1, (1 - grey) / np.maximum(high - grey, 1e-6), 1),
        np.where(low < 0, grey / np.maximum(grey - low, 1e-6), 1),
    ))
    rgb = np.clip(to_srgb(grey + (linear - grey) * gain), 0, 1)
    rgb = np.where((weight > 0)[..., None], rgb, original)
    return np.rint(rgb * 255).clip(0, 255).astype(np.uint8)


def recover(source, candidate, output, land, sky, reference=None):
    """Apply a monotone L* curve. Spatial masks are used only for measurements."""
    original = load_rgb(candidate)
    lab = srgb_to_lab(original)
    light = lab[..., 0]
    report = {
        'reference': 'G' if reference is not None else 'original',
        'triggered': False, 'applied': False, 'lift_L': 0.0, 'max_lift_L': MAX_LIFT,
        'sky_median_change_L': 0.0,
    }

    def unchanged(reason):
        if Path(candidate).resolve() != Path(output).resolve():
            shutil.copyfile(candidate, output)
        return {**report, 'reason': reason}

    if not land.any():
        return unchanged('no valid non-sky pixels')
    toe, median = map(float, np.percentile(light[land], (15, 50)))
    ref = srgb_to_lab(load_rgb(reference if reference is not None else source))[..., 0]
    line = float(np.median(ref[land])) - 3.0
    report.update(trigger_line_L=line, median_before_L=median, median_after_L=median, protected_dark_L=toe)
    if median >= line:
        return unchanged('at or above trigger line')
    report['triggered'] = True
    if toe >= median or median >= HIGHLIGHT_LIMIT:
        return unchanged('protected blacks or highlights leave no room at the median')
    # The descending smoothstep has maximum slope 1.5. Bound its amplitude
    # so the resulting lightness curve cannot reverse tonal order.
    limit = min(MAX_LIFT, (HIGHLIGHT_LIMIT - median) / 1.5)
    requested = min(line - median, limit)
    target = median + requested
    report.update(target_L=target, capped=line - median > limit, curve_limit_L=limit)
    weight = smoothstep((light - toe) / (median - toe)) * (1 - smoothstep((light - median) / (HIGHLIGHT_LIMIT - median)))

    def evaluate(amplitude):
        pixels = render(lab, original, weight, amplitude)
        quantized = srgb_to_lab(pixels[land].astype(np.float32) / 255)
        return float(np.median(quantized[:, 0])), pixels

    def reaches(value):
        return target <= value <= median + MAX_LIFT

    lo, hi = max(0.0, requested - .4), min(limit, requested + .4)
    value, pixels = evaluate(hi)
    if value >= target or value > median + MAX_LIFT:
        # Leave the last below-target value available for 8-bit quantization
        # gaps and to avoid rounding past the hard per-photo lift limit.
        while hi - lo > .003:
            mid = (lo + hi) / 2
            measured, _ = evaluate(mid)
            if measured >= target:
                hi = mid
            else:
                lo = mid
        value, pixels = evaluate(hi)
        if not reaches(value) or value - target >= .05:
            lower, lower_pixels = evaluate(lo)
            if not reaches(value) or abs(lower - target) < abs(value - target):
                value, pixels = lower, lower_pixels
    if value <= median or value > median + MAX_LIFT:
        return unchanged('no usable positive lift after output quantization')
    candidate_light = srgb_to_lab(pixels.astype(np.float32) / 255)[..., 0]
    Image.fromarray(pixels).save(output)
    report.update(applied=True, lift_L=value - median, median_after_L=value,
                  target_error_L=value - target,
                  sky_median_change_L=float(np.median(candidate_light[sky]) - np.median(light[sky])) if sky.any() else None)
    return report
