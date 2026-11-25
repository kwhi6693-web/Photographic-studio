#!/usr/bin/env python3
"""Experimental G-first route. The caller owns the legacy fallback."""
import argparse
import json
import shutil
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

from keep_regions import regions_of
from look_transfer import confidence, cv2, register
from pipeline import reframe_args, tool
from ps_common import blur, box, load_rgb, save_png, sky_mask, srgb_to_lab, structure_mask

SERIOUS_PHYSICS = frozenset(('halo', 'ghost_edges', 'sky_glow', 'tone_order', 'spotlight_glow'))
RETRY_G = '重抽一次 G 后再用 --g-first 重跑；第二次仍失败就交付旧链路结果。'
GHOST_RESIDUAL_LIMIT = 0.02
GHOST_LIMITATION = (
    'G 稿局部鬼影（平移复制、重影）无法自动检测，尤其是暗部重复纹理和密集枝叶；'
    'ghost_edges 窄判定只用于去除提亮暗部造成的误报。交付前需肉眼复核 1:1。'
)


def align_g(source, generated):
    """Map the generated image back to the original's grid."""
    lite = getattr(cv2, 'LITE', False)
    if lite:
        homography, score = cv2.register(source, generated)
        inliers = cv2.lite_inliers(score, 60)
    else:
        homography, inliers = register(source, generated)
        score = inliers
    ok = homography is not None and inliers >= 60 and bool(np.isfinite(homography).all())
    report = {'method': 'phase_correlation' if lite else 'ORB+RANSAC',
              'inliers_or_ncc': float(score) if lite else score, 'ok': ok}
    if not ok:
        return None, report
    height, width = source.shape[:2]
    aligned = cv2.warpPerspective(generated, homography, (width, height),
                                  flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                                  borderMode=cv2.BORDER_REPLICATE)
    return aligned, report


def ghost_fields(source, edited, slope_limit):
    """Reproduce the existing check's grid and off-edge population."""
    original = srgb_to_lab(load_rgb(source))[..., 0]
    final = srgb_to_lab(load_rgb(edited))[..., 0]
    height, width = original.shape
    scale = 1024 / max(height, width)
    size = (max(16, round(width * scale)), max(16, round(height * scale)))

    def resize(luma):
        image = Image.fromarray(np.ascontiguousarray(luma, np.float32))
        return np.asarray(image.resize(size, Image.BOX), np.float32)

    light = resize(original)
    change = np.stack(np.gradient(blur(resize(final - original), 2)), axis=-1)
    source_edges = np.hypot(*np.gradient(blur(light, 2)))
    eligible = blur((source_edges > 1.2).astype(np.float32), 6) <= 0.02
    raw = eligible & (np.linalg.norm(change, axis=-1) > slope_limit)
    return light, change, eligible, raw


def local_ghost_match(light, change, raw):
    """Use signed direction and local contrast to recognize weak original edges."""
    log_light = np.log1p(np.maximum(light, 0))
    mean = box(log_light, 4)
    deviation = np.sqrt(np.maximum(box(log_light * log_light, 4) - mean * mean, 1e-12))
    structure = np.stack(np.gradient(blur(log_light, 2)), axis=-1) / deviation[..., None]
    ys, xs = np.nonzero(raw)
    sample = change[ys, xs]
    minimum_cosine = np.cos(np.deg2rad(20))
    strength = np.linalg.norm(sample, axis=-1)
    matched = np.zeros(len(xs), dtype=bool)
    h, w = raw.shape
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            neighbor = structure[np.clip(ys + dy, 0, h - 1), np.clip(xs + dx, 0, w - 1)]
            contrast = np.linalg.norm(neighbor, axis=-1)
            same_direction = (sample * neighbor).sum(axis=-1) >= minimum_cosine * strength * contrast
            matched |= (contrast > 0.10) & same_direction
    return structure, ys[~matched], xs[~matched], int(matched.sum())


def shifted_ghost_count(structure, change, ys, xs):
    """Corroborate displacement among unmatched pixels with direction-sensitive patch NCC."""
    radius = 2
    offsets = np.arange(-15, 16)
    dy, dx = np.meshgrid(offsets, offsets, indexing='ij')
    distances = dx * dx + dy * dy
    search = (distances >= 4) & (distances <= 225)
    # Include the same-position correlation in column zero as the reference.
    dy, dx = np.r_[0, dy[search]], np.r_[0, dx[search]]
    h, w = change.shape[:2]
    interior = (ys >= radius) & (ys < h - radius) & (xs >= radius) & (xs < w - radius)
    ys, xs = ys[interior], xs[interior]
    source_patches = np.lib.stride_tricks.sliding_window_view(structure, (5, 5), axis=(0, 1))
    change_patches = np.lib.stride_tricks.sliding_window_view(change, (5, 5), axis=(0, 1))
    confirmed = 0
    for start in range(0, len(xs), 64):
        y, x = ys[start:start + 64] - radius, xs[start:start + 64] - radius
        yy, xx = y[:, None] + dy, x[:, None] + dx
        valid = (yy >= 0) & (yy < h - 4) & (xx >= 0) & (xx < w - 4)
        neighbors = source_patches[np.clip(yy, 0, h - 5), np.clip(xx, 0, w - 5)].reshape(len(x), len(dx), -1)
        target = change_patches[y, x].reshape(len(x), -1)
        cross = np.einsum('bsi,bi->bs', neighbors, target)
        norm = np.einsum('bsi,bsi->bs', neighbors, neighbors) * np.einsum('bi,bi->b', target, target)[:, None]
        corr = np.where(valid, cross / np.sqrt(np.maximum(norm, 1e-12)), -1)
        peak = corr[:, 1:].max(axis=1)
        ratio = peak / np.maximum(corr[:, 0], 0.10)
        confirmed += int(((peak >= 0.80) & (ratio >= 1.25)).sum())
    return confirmed


def ghost_diagnostic(source, edited, slope_limit, residual_limit):
    light, change, eligible, raw = ghost_fields(source, edited, slope_limit)
    structure, ys, xs, amplified = local_ghost_match(light, change, raw)
    population = int(eligible.sum())
    fraction = len(xs) / population if population else 0.0
    if residual_limit is None:
        decision = 'KEEP_LEGACY_GATE'
    else:
        decision = 'FALLBACK' if fraction > residual_limit else 'PASS'
    return {'ghost_raw': int(raw.sum()), 'ghost_amplified': amplified, 'ghost_residual': len(xs),
            'ghost_shifted': shifted_ghost_count(structure, change, ys, xs),
            'ghost_eligible': population, 'ghost_residual_fraction': fraction,
            'ghost_residual_limit': residual_limit, 'ghost_decision': decision}


def physics(source, edited, ghost_residual_limit=None):
    report = tool('physics_check.py', source, edited)
    checks = report.get('checks', {})
    failed = [name for name, result in checks.items() if result.get('ok') is False]
    result = {'serious': [name for name in failed if name in SERIOUS_PHYSICS],
              'hints': [name for name in failed if name not in SERIOUS_PHYSICS]}
    if not SERIOUS_PHYSICS.issubset(checks):
        result['error'] = 'missing physics checks'
    if 'ghost_edges' in failed and 'limit' in checks['ghost_edges']:
        diagnostic = ghost_diagnostic(source, edited, checks['ghost_edges']['limit'], ghost_residual_limit)
        result['hints'].append(diagnostic)
        if diagnostic['ghost_decision'] == 'PASS':
            result['serious'].remove('ghost_edges')
    return result


def measure_drift(source_lab, generated_lab, land, darkening_thresholds):
    chroma_ratio = delta_l = None
    verdict = 'NO_NONSKY_PIXELS'
    if land.any():
        source_chroma = np.hypot(source_lab[..., 1], source_lab[..., 2])[land].mean()
        g_chroma = np.hypot(generated_lab[..., 1], generated_lab[..., 2])[land].mean()
        chroma_ratio = float(max(g_chroma, 1e-6) / max(source_chroma, 1e-6))
        delta_l = float(np.median(generated_lab[..., 0][land]) - np.median(source_lab[..., 0][land]))
        warn, limit = darkening_thresholds
        if chroma_ratio > 1.65:
            verdict = 'FALLBACK: non-sky chroma ratio'
        elif limit is not None and delta_l <= limit:
            verdict = 'FALLBACK: non-sky median darkening'
        elif warn is not None and delta_l <= warn:
            verdict = 'WARN: non-sky median darkening'
        else:
            verdict = 'PASS'
    return {'chroma_ratio_nonsky': chroma_ratio, 'dL_median_nonsky': delta_l, 'verdict': verdict}


def pixel_boxes(regions, shape):
    height, width = shape[:2]
    return [[int(x0 * width), int(y0 * height), int(np.ceil(x1 * width)), int(np.ceil(y1 * height))]
            for x0, y0, x1, y1 in (region['box'] for region in regions)]


def check_confidence(source_l, generated_l, sky, boxes, fallback_area):
    eligible = ~sky
    for x0, y0, x1, y1 in boxes:
        eligible[y0:y1, x0:x1] = False
    low = (confidence(source_l, generated_l) < 0.3) & eligible
    area = float(low.sum() / eligible.sum()) if eligible.any() else None
    flags = []
    if low.any():
        _, labels, stats, _ = cv2.connectedComponentsWithStats(low.astype(np.uint8), connectivity=8)
        contrast = structure_mask(source_l, sky)
        contrast_by_label = np.bincount(labels.ravel(), weights=contrast.ravel(), minlength=len(stats))
        for label, (x, y, w, h, count) in enumerate(stats[1:], 1):
            share = float(count / low.size)
            if share < 0.005 and contrast_by_label[label] / count >= 0.5:
                flags.append({'box': [int(x), int(y), int(x + w), int(y + h)], 'area': share})
        flags.sort(key=lambda flag: flag['box'])
    if area is None:
        verdict = 'NO_ELIGIBLE_PIXELS'
    elif fallback_area is not None and area > fallback_area:
        verdict = 'FALLBACK: low confidence area'
    else:
        verdict = 'WARN: low confidence pixels' if area else 'PASS'
    return {'low_area_outside_keep': area, 'small_flags': flags, 'verdict': verdict}


def restore_details(source, aligned, destination, folder, regions, boxes, lite):
    tool_name = 'keep_regions_content' if lite else 'text_restore'
    if not boxes:
        return {'tool': tool_name, 'boxes': [], 'verdict': 'NO_REGIONS', 'seam_flags': []}
    if lite:
        regions_file = folder / 'keep.json'
        regions_file.write_text(json.dumps([{**region, 'mode': 'content'} for region in regions]),
                                encoding='utf-8')
        report = tool('keep_regions.py', source, aligned, destination, regions_file)
    else:
        report = tool('text_restore.py', source, aligned, destination, folder / 'restore.json',
                      *(','.join(map(str, box)) for box in boxes))
    return {'tool': tool_name, 'boxes': boxes, 'verdict': report.get('verdict'),
            'seam_flags': report.get('flags', [])}


def fraction(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
        raise ValueError(f'{name} must be a fraction in [0, 1]')
    return float(value)


def resolve_ghost_limit(params, cli_value=None):
    """The params file (written by the agent) may only tighten; loosening needs the command line."""
    if cli_value is not None:
        return {'value': fraction(cli_value, '--ghost-residual-limit'), 'source': 'command_line'}
    settings = params.get('g_first') or {}
    if 'ghost_residual_limit' not in settings:
        return {'value': GHOST_RESIDUAL_LIMIT, 'source': 'default'}
    value = settings['ghost_residual_limit']
    if value is None:  # the strictest setting: any ghost_edges hit falls back
        return {'value': None, 'source': 'params'}
    value = fraction(value, 'g_first.ghost_residual_limit')
    if value > GHOST_RESIDUAL_LIMIT:
        return {'value': GHOST_RESIDUAL_LIMIT, 'source': 'default', 'ignored_params_value': value,
                'note': f'参数放宽被忽略：参数文件只能收紧（≤ {GHOST_RESIDUAL_LIMIT}），放宽须用命令行 --ghost-residual-limit'}
    return {'value': value, 'source': 'params'}


def run(source, generated, params, output, genre=None, *, confidence_fallback_area=None,
        darkening_thresholds=(None, None), skip_reason=None, ghost_residual_limit_cli=None):
    """Return the light-route receipt. dL gates stay unset pending fixture review."""
    lite = getattr(cv2, 'LITE', False)
    regions = regions_of(params)
    ghost_setting = resolve_ghost_limit(params, ghost_residual_limit_cli)
    ghost_residual_limit = ghost_setting['value']
    restore_tool = 'keep_regions_content' if lite else 'text_restore'
    steps = {
        'backend': 'cvlite' if lite else 'opencv',
        'ghost_residual_limit': ghost_setting,
        'museum_gate': 'fallback: museum without keep' if genre == 'museum' and not regions else 'pass',
        'align': {'method': None, 'inliers_or_ncc': None, 'ok': False},
        'precheck': {
            'check_g_output': {'verdict': 'NOT_RUN', 'structure_corr': None, 'orb_inliers': None},
            'physics_g': {'serious': None, 'hints': None},
            'drift': {'chroma_ratio_nonsky': None, 'dL_median_nonsky': None, 'verdict': 'NOT_RUN'},
            'confidence': {'low_area_outside_keep': None, 'small_flags': [], 'verdict': 'NOT_RUN'},
        },
        'restore': {'tool': restore_tool, 'boxes': [], 'verdict': 'NOT_RUN', 'seam_flags': []},
        'texture': {'strength': None, 'verdict': 'NOT_RUN'},
        'reframe': {'verdict': 'NOT_RUN'},
        'n_trim': {'verdict': 'NOT_RUN'},
        'physics_final': {'serious': None, 'hints': None},
        'degraded': [],
        'next': [],
    }

    def finish(reason=None):
        verdict = f'FALLBACK: {reason}' if reason else 'DELIVER_G_FIRST'
        steps['verdict'] = verdict
        if reason:
            steps['next'].append(RETRY_G)
        return {'tool': 'g_first.py', 'steps': {'g_first': steps}, 'verdict': verdict,
                'next': steps['next'], 'output': None if reason else str(output)}

    if steps['museum_gate'] != 'pass':
        return finish('museum without keep')
    if skip_reason:
        return finish(skip_reason)
    try:
        original, draft = load_rgb(source), load_rgb(generated)
    except (OSError, ValueError):
        return finish('cannot read source or G')
    aligned, steps['align'] = align_g(original, draft)
    # The raw-draft scene check is independent of our registration.
    scene = tool('check_g_output.py', source, generated)
    precheck = steps['precheck']
    precheck['check_g_output'].update({field: scene[field] for field in
                                      ('verdict', 'structure_corr', 'orb_inliers',
                                       'structure_corr_registered', 'aspect_ok', 'framing_warning')
                                      if field in scene})
    if aligned is None:
        return finish('cannot align')

    with tempfile.TemporaryDirectory() as folder_name:
        folder = Path(folder_name)
        source_grid, current = folder / 'source.png', folder / 'aligned.png'
        save_png(original, source_grid)
        save_png(aligned, current)
        precheck['physics_g'] = physics(source_grid, current, ghost_residual_limit)
        lab_source, lab_g = srgb_to_lab(original), srgb_to_lab(load_rgb(current))
        sky = sky_mask(lab_source[..., 0])
        boxes = pixel_boxes(regions, original.shape)
        precheck['drift'] = measure_drift(lab_source, lab_g, ~sky, darkening_thresholds)
        precheck['confidence'] = check_confidence(lab_source[..., 0], lab_g[..., 0], sky, boxes,
                                                 confidence_fallback_area)

        failures = []
        if scene.get('scene_correspondence_ok') is not True:
            failures.append('scene correspondence')
        if precheck['physics_g'].get('error'):
            failures.append('G physics check unavailable')
        failures.extend(precheck['physics_g']['serious'])
        for name in ('drift', 'confidence'):
            verdict = precheck[name]['verdict']
            if verdict.startswith('FALLBACK: '):
                failures.append(verdict.removeprefix('FALLBACK: '))
        if failures:
            return finish('precheck: ' + ', '.join(failures))

        restored = folder / 'restored.png'
        steps['restore'] = restore_details(source_grid, current, restored, folder, regions, boxes, lite)
        if boxes:
            if not restored.exists() or str(steps['restore']['verdict']).startswith('STOP'):
                return finish('keep restore failed')
            current = restored
        if lite:
            steps['texture'] = 'NOT_RUN_NO_OPENCV'
            steps['degraded'].append('texture_skipped_no_opencv')
        else:
            strength = float(np.clip(float((params.get('g_first') or {}).get('texture_strength', 0.5)), 0, 0.5))
            textured = folder / 'textured.png'
            texture = tool('texture_blend.py', source_grid, current, textured, '--mode=auto',
                           f'--strength={strength}')
            steps['texture'] = {'strength': strength, 'verdict': texture.get('verdict')}
            if textured.exists():
                current = textured
            else:
                steps['degraded'].append('texture_not_applied')

        geometry = reframe_args(params.get('reframe') or {})
        if geometry:
            framed, source_framed = folder / 'framed.png', folder / 'source_framed.png'
            frame_report = tool('reframe.py', current, framed, *geometry)
            source_report = tool('reframe.py', source_grid, source_framed, *geometry)
            size = frame_report.get('output_size')
            ok = bool(size and size == source_report.get('output_size') and framed.exists() and source_framed.exists())
            steps['reframe'] = {'verdict': 'REFRAMED' if ok else 'FAILED', 'args': geometry,
                                'output_size': size, 'original_reframed_same_way': ok,
                                'warnings': frame_report.get('warnings', [])}
            if not ok:
                return finish('reframe failed')
            current, source_grid = framed, source_framed
        else:
            steps['reframe'] = {'verdict': 'NO_REFRAME'}

        trimmed = folder / 'trimmed.png'
        trim = tool('n_trim.py', current, trimmed)
        steps['n_trim'] = {'verdict': trim.get('verdict'), 'trigger': trim.get('trigger')}
        if str(trim.get('verdict', '')).startswith('PASS') and trimmed.exists():
            current = trimmed
        elif not str(trim.get('verdict', '')).startswith(('SKIP', 'FAIL')):
            steps['degraded'].append('n_trim_not_applied')

        # Use the exact bytes checked below. reframe's generated ICC profile
        # can carry a timestamp, so serialize the already-sRGB pixels without it.
        candidate = folder / 'candidate.png'
        save_png(load_rgb(current), candidate)
        final = steps['physics_final'] = physics(source_grid, candidate, ghost_residual_limit)
        if final.get('error'):
            return finish('final physics check unavailable')
        if final['serious']:
            return finish('final physics: ' + ', '.join(final['serious']))
        shutil.copyfile(candidate, output)
        return finish()


def main():
    parser = argparse.ArgumentParser(description=__doc__, epilog=GHOST_LIMITATION)
    for name in ('source', 'g_output', 'params_json', 'out_png', 'receipt_json'):
        parser.add_argument(name)
    parser.add_argument('--genre', choices=('museum', 'night'))
    parser.add_argument('--ghost-residual-limit', type=float, default=None,
                        help='loosen or tighten the ghost residual limit (0-1); only the user or a work order '
                             'may loosen it, and it always wins over params g_first.ghost_residual_limit, '
                             f'which may only tighten (<= {GHOST_RESIDUAL_LIMIT})')
    args = parser.parse_args()
    params = json.loads(Path(args.params_json).read_text(encoding='utf-8') or '{}')
    try:
        receipt = run(args.source, args.g_output, params, args.out_png, args.genre,
                      ghost_residual_limit_cli=args.ghost_residual_limit)
    except ValueError as exc:
        parser.error(str(exc))
    report = json.dumps(receipt, ensure_ascii=False, indent=1)
    Path(args.receipt_json).write_text(report, encoding='utf-8')
    print(report)


if __name__ == '__main__':
    main()
