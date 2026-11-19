#!/usr/bin/env python3
"""Photographic Studio v0.3.0 - objective measurements of a photo, to ground the reading ("the eye").
Usage: python3 -I measure.py IMAGE [OUT_JSON]
Pure numpy + Pillow. Numbers only: it does not judge the photo; the agent reads them next to the image.
Positions are fractions of the frame (x from left, y from top)."""
import json, sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ps_common import load_rgb, srgb_to_lab, blur, sha256, HUES, hue_weight


def pct(x, q):
    return round(float(np.percentile(x, q)), 1)


def distractions(L, C, h, w):
    """v1.2.6: candidate bright distractions for the brief - small bright things well above their surroundings (a
    white-clad visitor, a white stone, a railing glint, a dead-white sky gap). Light sources (lamps, lit windows) show up
    here too: the agent decides which to quiet and leaves real lights alone. A bright spot straight below another one is
    reported as its reflection ("reflection_of"): quiet both, or the water shows a light the bank no longer has.
    Whitish only (L* > 74, chroma < 18, 20 above the surroundings): sunlit leaves and flowers are bright but colourful."""
    import cv2
    k = max(6, min(h, w) // 60)
    exc = L - blur(L, 3 * k)
    core = (L > 74) & (exc > 20) & (C < 18)            # whitish: sunlit leaves are bright too, but colourful
    g = max(3, k // 3)
    m = cv2.dilate(core.astype(np.uint8), np.ones((g, g), np.uint8))   # a figure broken by leaves stays one item
    n, lab_, st, cen = cv2.connectedComponentsWithStats(m, 8)
    A = h * w; found = []
    for i in range(1, n):
        x, y, bw, bh, area = st[i]
        sel = (lab_ == i) & core
        area = int(sel.sum())
        if not (0.00015 * A <= area <= 0.02 * A): continue
        if bw > 0.2 * w or bh > 0.2 * h: continue      # a scatter of glints across the frame, not one thing
        ring = (cv2.dilate(sel.astype(np.uint8), np.ones((2 * k + 1, 2 * k + 1), np.uint8)) > 0) & ~sel
        surround = float(np.median(L[ring])) if ring.any() else float(L.mean())
        Lm = float(L[sel].mean())
        pad_x, pad_y = max(2, int(bw * 0.2)), max(2, int(bh * 0.2))
        box = [max(0, x - pad_x) / w, max(0, y - pad_y) / h, min(w, x + bw + pad_x) / w, min(h, y + bh + pad_y) / h]
        found.append({'box': [round(v, 3) for v in box], 'L': round(Lm, 1), 'surround_L': round(surround, 1),
                      'above_surround': round(Lm - surround, 1), 'area': round(area / A, 4),
                      'centre': [round(float(cen[i][0] / w), 3), round(float(cen[i][1] / h), 3)],
                      'solid': round(float(area / max(bw * bh, 1)), 2),
                      'chroma': round(float(C[sel].mean()), 1)})
    found = found  # (sorted below)
    for d in found:   # sky seen through leaves near the top, or glints on water: listed after the single objects
        near = sum(1 for e in found if e is not d and abs(e['centre'][0] - d['centre'][0]) < 0.15 and abs(e['centre'][1] - d['centre'][1]) < 0.15)
        d['kind'] = 'sky_gap' if d['centre'][1] < 0.3 and d['L'] > 85 else ('glints' if near >= 3 and d['centre'][1] > 0.65 else 'object')
    order = {'object': 0, 'sky_gap': 1, 'glints': 2}
    # a person or a stone is one solid shape; sparkle on water and sky through leaves are broken and scattered
    found.sort(key=lambda d: (order[d['kind']], -d['above_surround'] * d['area'] ** 0.5 * min(1.0, d['solid'] / 0.35)))
    glints = sum(1 for d in found if d['kind'] == 'glints')
    found = [d for d in found if d['kind'] == 'object'][:8] + [d for d in found if d['kind'] == 'sky_gap'][:2]   # v1.2.6b: the few that pull hardest
    for i, d in enumerate(found):          # a reflection: the same column a little further down, a little darker
        if not 0.25 < d['centre'][1] < 0.75 or d['kind'] != 'object': continue
        for j, e in enumerate(found):
            dy = e['centre'][1] - d['centre'][1]
            if j != i and 0.02 < dy < 0.3 and abs(e['centre'][0] - d['centre'][0]) < 0.03 and e['L'] <= d['L'] + 2 \
                    and 'reflection_of' not in e:
                e['reflection_of'] = i; break
    for i, d in enumerate(found): d['id'] = i
    return {'candidates': found, 'water_glints': glints,
            'note': 'candidates only - most are NOT distractions. Quiet only what pulls the eye away from the subject '
                    '(a white-clad visitor, a stray white stone, a railing glint, a dead-white sky gap). Parts of the subject '
                    '(its white wall or gable, plaques, window paper, lamps) stay. Usually 0-3 things; with reflection_of, '
                    'quiet the water image with its object (also). director_brief.md'}


def main(path, out=None):
    rgb = load_rgb(path)
    h, w = rgb.shape[:2]
    lab = srgb_to_lab(rgb)
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    C = np.hypot(a, b)
    hue = np.degrees(np.arctan2(b, a)) % 360
    u8 = np.uint8(np.clip(np.rint(rgb * 255), 0, 255))
    r = {'file': Path(path).name, 'sha256': sha256(path), 'size': [w, h], 'aspect': round(w / h, 3)}

    r['tone'] = {'L_mean': round(float(L.mean()), 1), 'L_p1': pct(L, 1), 'L_p5': pct(L, 5), 'L_p50': pct(L, 50), 'L_p95': pct(L, 95), 'L_p99': pct(L, 99),
                 'dynamic_range_p1_p99': round(pct(L, 99) - pct(L, 1), 1), 'global_contrast_L_std': round(float(L.std()), 1),
                 'shadows_fraction_L_below_20': round(float((L < 20).mean()), 3), 'highlights_fraction_L_above_85': round(float((L > 85).mean()), 3),
                 'clipped_white_fraction': round(float(np.any(u8 == 255, 2).mean()), 4), 'clipped_black_fraction': round(float(np.all(u8 <= 2, 2).mean()), 4)}
    key = 'low-key' if L.mean() < 38 else 'high-key' if L.mean() > 68 else 'mid-key'
    r['tone']['key'] = key
    r['tone']['hint'] = ('flat: little separation between darks and lights' if r['tone']['dynamic_range_p1_p99'] < 60 else
                         'wide range: protect highlights and shadows' if r['tone']['dynamic_range_p1_p99'] > 88 else 'normal range')

    # local contrast ("clarity") and sharpness proxies
    step = max(1, min(h, w) // 600)
    Ls = L[::step, ::step]
    r['detail'] = {'local_contrast': round(float(np.abs(Ls - blur(Ls, 8)).mean()), 2), 'fine_detail': round(float(np.abs(Ls - blur(Ls, 1.5)).mean()), 2)}

    # colour
    wC = C / (C.sum() + 1e-9)
    r['colour'] = {'chroma_mean': round(float(C.mean()), 1), 'chroma_p95': pct(C, 95), 'a_mean': round(float(a.mean()), 1), 'b_mean': round(float(b.mean()), 1),
                   'temperature_hint': 'warm cast' if b.mean() > 8 else 'cool cast' if b.mean() < -4 else 'near neutral',
                   'shadows_b_mean': round(float(b[L < 30].mean()) if (L < 30).any() else 0.0, 1), 'highlights_b_mean': round(float(b[L > 70].mean()) if (L > 70).any() else 0.0, 1)}
    fam = {}
    for name, centre in HUES.items():
        m = hue_weight(hue, centre) * (C > 8)
        share = float((m * wC).sum())
        if share > 0.03:
            sel = m > 0.5
            fam[name] = {'share_of_colour': round(share, 2), 'area_fraction': round(float(sel.mean()), 3),
                         'chroma_mean': round(float(C[sel].mean()) if sel.any() else 0.0, 1), 'L_mean': round(float(L[sel].mean()) if sel.any() else 0.0, 1),
                         'centre_xy': [round(float(np.nonzero(sel)[1].mean() / w), 2), round(float(np.nonzero(sel)[0].mean() / h), 2)] if sel.any() else None}
    r['colour']['families'] = dict(sorted(fam.items(), key=lambda kv: -kv[1]['share_of_colour']))
    r['colour']['neutral_area_fraction'] = round(float((C < 8).mean()), 3)

    # where the light and the weight are
    thirds = lambda arr: [[round(float(arr[i * h // 3:(i + 1) * h // 3, j * w // 3:(j + 1) * w // 3].mean()), 1) for j in range(3)] for i in range(3)]
    r['layout'] = {'L_mean_3x3': thirds(L), 'chroma_mean_3x3': thirds(C),
                   'brightest_cell_row_col': list(map(int, np.unravel_index(int(np.argmax(np.array(thirds(L)))), (3, 3)))),
                   'top_minus_bottom_L': round(float(L[:h // 2].mean() - L[h // 2:].mean()), 1), 'left_minus_right_L': round(float(L[:, :w // 2].mean() - L[:, w // 2:].mean()), 1)}

    # sky estimate: bright, low-texture, blue-to-neutral pixels connected to the top edge (rough)
    tex = np.abs(L - blur(L, 4))
    skyish = (tex < 2.5) & ((b < -5) | ((L > 60) & (C < 15)))            # blue of any brightness, or bright and near-neutral (overcast)
    col_run = np.cumprod(skyish.astype(np.uint8), axis=0).astype(bool)      # stays true from the top until first non-sky pixel
    r['sky'] = {'estimated_area_fraction': round(float(col_run.mean()), 3)}
    if col_run.mean() > 0.03:
        r['sky'].update({'L_mean': round(float(L[col_run].mean()), 1), 'chroma_mean': round(float(C[col_run].mean()), 1), 'b_mean': round(float(b[col_run].mean()), 1),
                         'lowest_y': round(float(np.nonzero(col_run.any(1))[0].max() / h), 2),
                         'hint': 'pale / washed sky' if L[col_run].mean() > 78 and C[col_run].mean() < 14 else 'sky has colour',
                         'note': 'rough estimate from smooth blue or bright-neutral pixels reaching the top edge; confirm by eye'})

    # attention estimate: local contrast + colourfulness, to suggest where the eye lands now (not what the subject is)
    s = max(1, min(h, w) // 200)
    Lq, Cq = L[::s, ::s], C[::s, ::s]
    sal = np.abs(Lq - blur(Lq, 12)) / 12 + np.abs(Cq - Cq.mean()) / 30
    sal = blur(sal, 6)
    thr = np.percentile(sal, 85)
    ys, xs = np.nonzero(sal >= thr)
    wts = sal[ys, xs]
    hq, wq = sal.shape
    r['attention'] = {'centroid_xy': [round(float((xs * wts).sum() / wts.sum() / wq), 2), round(float((ys * wts).sum() / wts.sum() / hq), 2)],
                      'box_xyxy': [round(float(np.percentile(xs, 5) / wq), 2), round(float(np.percentile(ys, 5) / hq), 2), round(float(np.percentile(xs, 95) / wq), 2), round(float(np.percentile(ys, 95) / hq), 2)],
                      'note': 'where contrast and colour concentrate now; the agent decides what the subject actually is'}
    edge = np.concatenate([sal[:hq // 12].ravel(), sal[-hq // 12:].ravel(), sal[:, :wq // 12].ravel(), sal[:, -wq // 12:].ravel()])
    r['attention']['edge_pull'] = round(float(edge.mean() / (sal.mean() + 1e-9)), 2)
    r['attention']['edge_hint'] = 'strong pull at the frame edges: consider vignette or crop' if r['attention']['edge_pull'] > 1.15 else 'edges are quiet'

    r['distractions'] = distractions(L, C, h, w)
    ab = r['attention']['box_xyxy']
    for c in r['distractions']['candidates']:   # inside the area that already holds the eye: often part of the subject itself
        cx, cy = c['centre']
        c['in_attention_area'] = bool(ab[0] <= cx <= ab[2] and ab[1] <= cy <= ab[3])

    text = json.dumps(r, ensure_ascii=False, indent=1)
    if out:
        Path(out).write_text(text, encoding='utf-8')
    print(text)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
