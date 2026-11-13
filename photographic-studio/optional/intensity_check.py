#!/usr/bin/env python3
"""Photographic Studio v0.3.8 - intensity check: is the edit within the strength the user prefers?
Usage: python3 intensity_check.py ORIGINAL FINAL [RECEIPT_JSON] [--genre=day|night|lowcolour|museum] [--before=IMAGE]
  --before: the image before calibration; then the check also verifies the calibration kept the expressiveness
  (local contrast, subject brightness, colour) - it may only remove the excess.
Compares the final with the original (statistics only; a final of a different size is resampled for measuring).
Reports each measure against the user's range and, when outside it, which grade.py parameter to change.
Anchors come from images the user approved (see references/intensity.md). Pure numpy + Pillow."""
import json, sys
from pathlib import Path
import numpy as np
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ps_common import load_rgb, srgb_to_lab, blur, sha256, daylight_sky

ANCHORS = {   # (low, high); None = no limit. Units: L* and Lab b.
    'day':       {'L_mean_change': (1.0, 5.0), 'chroma_ratio': (1.08, 1.30), 'lit_warmth_change': (None, 4.0),
                  'highlight_p99_change': (None, 3.0), 'sky_L_change': (-4.0, 3.0), 'local_contrast_ratio': (1.0, None)},
    'lowcolour': {'L_mean_change': (1.0, 5.0), 'chroma_ratio': (1.20, 2.80), 'lit_warmth_change': (None, 5.0),
                  'highlight_p99_change': (None, 3.0), 'sky_L_change': (-6.0, 3.0), 'local_contrast_ratio': (1.0, None)},
    'night':     {'L_mean_change': (0.5, 4.0), 'chroma_ratio': (None, None), 'lit_warmth_change': (None, 6.0),
                  'highlight_p99_change': (None, None), 'sky_L_change': (None, 1.5), 'local_contrast_ratio': (1.0, None)},   # night: lighting the subject IS the edit; clipping is checked by n_trim
    # v0.3.8 museum / low-key still life (declared with --genre=museum): judged on the SUBJECT, not the whole frame.
    # Anchor: the user's chosen strength (level 3 of the 2026-11-11 strength ladder, vase and jar); results the user
    # could not tell from the original (subject colour x1.10-1.28, subject local contrast x1.16-1.34) fall below it.
    # The bronze ox the user adopted had subject local contrast x1.14 and background +2.6, so those limits are set there.
    'museum':    {'L_mean_change': (None, 5.0), 'chroma_ratio': (None, None), 'lit_warmth_change': (None, 6.0),
                  'highlight_p99_change': (None, None), 'sky_L_change': (None, None), 'local_contrast_ratio': (1.0, None),
                  'subject_chroma_ratio': (1.30, 1.85), 'subject_local_contrast_ratio': (1.14, None),
                  'subject_L_change': (None, 7.0), 'background_L_change': (None, 3.0)},
}
FIX = {
    'L_mean_change': ('exposure_ev / shadows up a little', 'exposure_ev / highlights down a little'),
    'chroma_ratio': ('vibrance up (0.1) or the main colour sat up', 'saturation 0.9-0.95 or vibrance down'),
    'lit_warmth_change': (None, 'white_balance.temp down (-0.1 to -0.2) or tone_split.highlights b down'),
    'highlight_p99_change': (None, 'highlights down (-4 to -8); levels.white up'),
    'sky_L_change': ('sky region lift up, or blue lum up', 'sky region lift less negative, or blue lum up (sky darkened too much)'),
    'local_contrast_ratio': ('clarity up (0.1-0.2) or contrast up; the edit is flatter than the original', None),
    'subject_chroma_ratio': ('the subject looks unchanged: vibrance up and the subject colours sat up (see genres/still_life.md level 3)', 'subject colour too strong: the subject colour sat down a little'),
    'subject_local_contrast_ratio': ('the subject looks unchanged: clarity 0.4-0.55 and contrast 0.2-0.3 (level 3)', None),
    'subject_L_change': (None, 'the subject was brightened too much: exposure_ev down'),
    'background_L_change': (None, 'the dark background was lifted: lower exposure_ev/shadows, or darken the background region'),
}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    opt = dict(a[2:].split('=', 1) for a in sys.argv[1:] if a.startswith('--') and '=' in a)
    if len(args) < 2: sys.exit(__doc__)
    o_p, f_p = args[:2]; rec_p = args[2] if len(args) > 2 else None
    o = load_rgb(o_p); f = load_rgb(f_p)
    if f.shape != o.shape:
        f = np.asarray(Image.fromarray(np.uint8(np.rint(f * 255))).resize((o.shape[1], o.shape[0]), Image.LANCZOS)).astype(np.float32) / 255
    lo, lf = srgb_to_lab(o), srgb_to_lab(f)
    Lo, Lf = lo[..., 0], lf[..., 0]
    Co, Cf = np.hypot(lo[..., 1], lo[..., 2]), np.hypot(lf[..., 1], lf[..., 2])
    genre = opt.get('genre') or ('night' if Lo.mean() < 22 and not daylight_sky(Lo) else 'lowcolour' if Co.mean() < 10 else 'day')   # v1.0.2: daylight sky
    if genre == 'still_life': genre = 'museum'
    lit = Lo > 55
    tex = np.abs(Lo - blur(Lo, 4)); h = Lo.shape[0]
    sky = (lo[..., 2] < -12) & (tex < 2.5); sky[h // 2:] = False
    m = {'L_mean_change': round(float(Lf.mean() - Lo.mean()), 2),
         'chroma_ratio': round(float(Cf.mean() / max(Co.mean(), 1e-6)), 3),
         'lit_warmth_change': round(float((lf[..., 2] - lo[..., 2])[lit].mean()), 2) if lit.mean() > 0.02 else None,
         'highlight_p99_change': round(float(np.percentile(Lf, 99) - np.percentile(Lo, 99)), 2),
         'sky_L_change': round(float((Lf - Lo)[sky].mean()), 2) if sky.mean() > 0.05 else None,
         'local_contrast_ratio': round(float(np.abs(Lf - blur(Lf, 8)).mean() / max(np.abs(Lo - blur(Lo, 8)).mean(), 1e-6)), 3)}
    if genre == 'museum':
        texm = np.sqrt(np.maximum(blur(Lo ** 2, 4) - blur(Lo, 4) ** 2, 0))
        bgm = (blur(Lo, 3) < 20) & (texm < 2.0); sub = ~bgm
        lc = lambda L: np.abs(L - blur(L, 8))
        if sub.mean() > 0.05:
            m['subject_chroma_ratio'] = round(float(Cf[sub].mean() / max(Co[sub].mean(), 1e-6)), 3)
            m['subject_local_contrast_ratio'] = round(float(lc(Lf)[sub].mean() / max(lc(Lo)[sub].mean(), 1e-6)), 3)
            m['subject_L_change'] = round(float((Lf - Lo)[sub].mean()), 2)
        m['background_L_change'] = round(float((Lf - Lo)[bgm].mean()), 2) if bgm.mean() > 0.05 else None
    # v0.3.7: a large plain dark background (showcase, black wall, night sky) is meant to stay dark. There the brightness
    # floor is not a target - expressiveness comes from the subject's own light, contrast and texture (local contrast).
    darkbg = float(((blur(Lo, 3) < 20) & (tex < 2.0)).mean())
    m_note = None
    if darkbg > 0.25:
        m_note = f'dark background {round(darkbg, 2)}: overall-brightness floor not applied; do not lift the background to reach it'
    res, out_of_range = {}, []
    for k, v in m.items():
        lo_, hi_ = ANCHORS[genre][k]
        if m_note and k == 'L_mean_change': lo_ = None
        if genre == 'museum' and k in ('L_mean_change',): lo_ = None
        if v is None or (lo_ is None and hi_ is None):
            res[k] = {'value': v, 'range': [lo_, hi_], 'ok': None}; continue
        ok = (lo_ is None or v >= lo_) and (hi_ is None or v <= hi_)
        r = {'value': v, 'range': [lo_, hi_], 'ok': ok}
        if not ok:
            weak = lo_ is not None and v < lo_
            r['direction'] = 'too weak' if weak else 'too strong'
            r['fix'] = FIX[k][0 if weak else 1]
            out_of_range.append(f"{k} {v} {'<' if weak else '>'} {lo_ if weak else hi_}")
        res[k] = r
    kept = None
    if opt.get('before'):
        b = load_rgb(opt['before'])
        if b.shape != o.shape:
            b = np.asarray(Image.fromarray(np.uint8(np.rint(b * 255))).resize((o.shape[1], o.shape[0]), Image.LANCZOS)).astype(np.float32) / 255
        lb = srgb_to_lab(b); Lb = lb[..., 0]; Cb = np.hypot(lb[..., 1], lb[..., 2])
        lcb, lcf = np.abs(Lb - blur(Lb, 8)).mean(), np.abs(Lf - blur(Lf, 8)).mean()
        # subject proxy: the brightest-contrast third of the frame before calibration
        sal = blur(np.abs(Lb - blur(Lb, 12)), 10); subj = sal >= np.percentile(sal, 67)
        kept = {'local_contrast_kept': round(float(lcf / max(lcb, 1e-6)), 3),
                'subject_L_change': round(float((Lf - Lb)[subj].mean()), 2),
                'chroma_kept': round(float(Cf.mean() / max(Cb.mean(), 1e-6)), 3)}
        lost = []
        if kept['local_contrast_kept'] < 0.97: lost.append('local contrast dropped')
        if kept['subject_L_change'] < -1.5: lost.append('subject got darker')
        # colour may only be reduced if it was over the limit BEFORE calibration
        cr_before = float(Cb.mean() / max(Co.mean(), 1e-6)); hi_c = ANCHORS[genre]['chroma_ratio'][1]
        was_over = hi_c is not None and cr_before > hi_c
        if kept['chroma_kept'] < 0.97 and not was_over: lost.append('colour reduced although it was not over the limit')
        if was_over and hi_c is not None and m['chroma_ratio'] < hi_c - 0.05: lost.append('colour cut further than needed (aim just under the limit)')
        kept['verdict'] = 'EXPRESSIVENESS_KEPT' if not lost else 'EXPRESSIVENESS_LOST: ' + '; '.join(lost) + ' - undo and correct only the items that were over'
    rec = {'tool': 'intensity_check.py v0.3.8', 'original': {'file': Path(o_p).name, 'sha256': sha256(o_p)}, 'final': {'file': Path(f_p).name, 'sha256': sha256(f_p)},
           'genre': genre, 'dark_background_note': m_note, 'checks': res, 'calibration': kept, 'verdict': 'IN_RANGE' if not out_of_range else 'OUT_OF_RANGE: ' + '; '.join(out_of_range)}
    # v0.3.8: a calibration that lost expressiveness may not be delivered - say so in the headline, not only in a sub-field
    if kept and str(kept.get('verdict', '')).startswith('EXPRESSIVENESS_LOST'):
        rec['verdict'] = 'DO_NOT_DELIVER: ' + kept['verdict'] + ' | ' + rec['verdict']
    text = json.dumps(rec, ensure_ascii=False, indent=1)
    if rec_p: Path(rec_p).write_text(text, encoding='utf-8')
    print(text)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
