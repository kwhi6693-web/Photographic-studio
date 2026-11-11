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

    text = json.dumps(r, ensure_ascii=False, indent=1)
    if out:
        Path(out).write_text(text, encoding='utf-8')
    print(text)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
