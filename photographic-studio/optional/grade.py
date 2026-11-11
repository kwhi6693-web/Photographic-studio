#!/usr/bin/env python3
"""Photographic Studio v0.3.0 - N as a directed, deterministic grading tool ("the hands that follow the brief").
Usage: python3 -I grade.py INPUT_IMAGE OUTPUT_PNG PARAMS_JSON [RECEIPT_JSON]
Pure numpy + Pillow. No generative step, no resampling, no sharpening of fine detail, no added texture:
every output pixel is a tone/colour function of the input pixel and its smooth neighbourhood.

PARAMS_JSON (all keys optional; values outside the range are clamped and reported):
  white_balance: {temp: -1..1 (+ warmer), tint: -1..1 (+ magenta)}
  exposure_ev:   -1.0..1.0
  levels:        {black: 0..25, white: 75..100}     L values that become 0 and 100
  shadows:       -25..25   (L units added in the darks, edge-aware)
  highlights:    -25..25   (L units added in the lights; negative recovers)
  contrast:      -0.5..0.6 (S-curve on L; endpoints fixed)
  clarity:       0..0.6    (mid-scale local contrast in the midtones)
  saturation:    0..1.6    vibrance: -0.5..0.8 (acts more on weak colours)
  hues:          {red|orange|yellow|green|cyan|blue|purple|magenta: {sat: 0..1.8, lum: -15..15, shift: -20..20 deg}}
  tone_split:    {shadows: [a, b], highlights: [a, b]}   Lab a/b offsets, each -8..8
  regions:       list of {shape: rect|ellipse|gradient, box: [x0,y0,x1,y1] fractions (rect/ellipse),
                          (v0.3.7: a positive lift follows the light - it scales with each pixel's own brightness and the
                          object edges, so dark backgrounds are not lifted into a glow; set lift_dark: true to override)
                          from: top|bottom|left|right and end: 0..1 (gradient), feather: 0..0.5,
                          edge_aware: bool, only_hue: name, only_L: [lo, hi],
                          lift: -20..20 (L), sat: 0.5..1.6, warm: -8..8 (Lab b)}
  vignette:      {amount: 0..10 (L at the corners), centre: [x, y] each 0.35..0.65, radius: 0.6..1.2} (v0.3.7: centred, no off-centre blotch)
"""
import json, sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ps_common import load_rgb, save_png, to_linear, to_srgb, lin_to_lab, lab_to_lin, box, blur, guided, structure_corr, sha256, HUES, hue_weight

clamps = []


def cl(name, v, lo, hi):
    v = float(v)
    if v < lo or v > hi:
        clamps.append(f'{name}: {v} -> {min(max(v, lo), hi)}')
    return min(max(v, lo), hi)


def smoothstep(x):
    x = np.clip(x, 0, 1)
    return x * x * (3 - 2 * x)


def region_mask(reg, h, w, L01, hue, L):
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    yy /= max(h - 1, 1); xx /= max(w - 1, 1)
    f = max(cl('region.feather', reg.get('feather', 0.08), 0, 0.5), 1e-3)
    shape = reg.get('shape', 'rect')
    if shape == 'gradient':
        end = cl('region.end', reg.get('end', 0.4), 0.02, 1)
        d = {'top': yy, 'bottom': 1 - yy, 'left': xx, 'right': 1 - xx}[reg.get('from', 'top')]
        m = 1 - smoothstep(d / end)
    else:
        x0, y0, x1, y1 = reg['box']
        if shape == 'ellipse':
            cx, cy, rx, ry = (x0 + x1) / 2, (y0 + y1) / 2, max((x1 - x0) / 2, 1e-3), max((y1 - y0) / 2, 1e-3)
            d = np.sqrt(((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2)
            m = 1 - smoothstep((d - (1 - f * 2)) / (f * 2))
        else:
            m = smoothstep((xx - x0) / f + 0.5) * smoothstep((x1 - xx) / f + 0.5) * smoothstep((yy - y0) / f + 0.5) * smoothstep((y1 - yy) / f + 0.5)
    m = m.astype(np.float32)
    if reg.get('only_hue') in HUES:
        m = m * hue_weight(hue, HUES[reg['only_hue']], 40)
    if reg.get('only_L'):
        lo, hi = reg['only_L']
        m = m * smoothstep((L - lo) / 8 + 0.5) * smoothstep((hi - L) / 8 + 0.5)
    if reg.get('edge_aware'):
        m = np.clip(guided(L01, m, max(4, min(h, w) // 60), 1e-3), 0, 1)
    return m


def main(inp, out, params_path, receipt=None):
    P = json.loads(Path(params_path).read_text(encoding='utf-8'))
    src = load_rgb(inp)
    h, w = src.shape[:2]
    lin = to_linear(src)
    used = {}

    wb = P.get('white_balance') or {}
    t, ti = cl('temp', wb.get('temp', 0), -1, 1), cl('tint', wb.get('tint', 0), -1, 1)
    if t or ti:
        g = np.array([1 + 0.18 * t + 0.06 * ti, 1 - 0.10 * ti, 1 - 0.18 * t + 0.06 * ti], np.float32)
        g = g / float(g @ np.array([0.2126729, 0.7151522, 0.072175], np.float32))      # keep luminance
        lin = lin * g
        used['white_balance'] = {'temp': t, 'tint': ti}
    ev = cl('exposure_ev', P.get('exposure_ev', 0), -1, 1)
    if ev:
        lin = lin * (2.0 ** ev); used['exposure_ev'] = ev

    lab = lin_to_lab(lin)
    L, a, b = lab[..., 0].copy(), lab[..., 1].copy(), lab[..., 2].copy()
    lab0 = lin_to_lab(to_linear(src))
    L_in = lab0[..., 0]

    lv = P.get('levels') or {}
    bp, wp = cl('levels.black', lv.get('black', 0), 0, 25), cl('levels.white', lv.get('white', 100), 75, 100)
    if bp or wp < 100:
        k = 100.0 / (wp - bp)
        L = (L - bp) * k; a *= (1 + (k - 1) * 0.5); b *= (1 + (k - 1) * 0.5)
        used['levels'] = {'black': bp, 'white': wp}

    r_loc = max(6, min(h, w) // 40)
    sh, hi = cl('shadows', P.get('shadows', 0), -25, 25), cl('highlights', P.get('highlights', 0), -25, 25)
    if sh or hi:
        base = guided(np.clip(L_in / 100, 0, 1), np.clip(L, 0, 100), r_loc, 2e-3)       # edge-aware local brightness
        if sh:
            L = L + sh * smoothstep(1 - base / 55.0); used['shadows'] = sh
        if hi:
            L = L + hi * smoothstep((base - 45.0) / 55.0); used['highlights'] = hi

    c = cl('contrast', P.get('contrast', 0), -0.5, 0.6)
    if c:
        x = np.clip(L / 100, 0, 1)
        L = np.where((L >= 0) & (L <= 100), 100 * (x - c * np.sin(2 * np.pi * x) / (2 * np.pi)), L); used['contrast'] = c

    cy = cl('clarity', P.get('clarity', 0), 0, 0.6)
    if cy:
        d = L - blur(L, max(8, min(h, w) // 50))
        mid = 1 - np.abs(np.clip(L, 0, 100) - 50) / 50
        L = L + cy * d * (0.4 + 0.6 * mid); used['clarity'] = cy

    C = np.hypot(a, b); hue = np.degrees(np.arctan2(b, a)) % 360
    sat, vib = cl('saturation', P.get('saturation', 1), 0, 1.6), cl('vibrance', P.get('vibrance', 0), -0.5, 0.8)
    if sat != 1 or vib:
        m = sat * (1 + vib * np.clip(1 - C / 60.0, 0, 1))
        a *= m; b *= m; C = C * m
        used.update({'saturation': sat, 'vibrance': vib})
    hp = P.get('hues') or {}
    if hp:
        used['hues'] = {}
        sm, dl, dh = np.ones_like(L), np.zeros_like(L), np.zeros_like(L)
        for name, v in hp.items():
            if name not in HUES: clamps.append(f'hues.{name}: unknown, ignored'); continue
            wgt = hue_weight(hue, HUES[name]) * smoothstep((C - 4.0) / 14.0)
            s_, l_, h_ = cl(f'hues.{name}.sat', v.get('sat', 1), 0, 1.8), cl(f'hues.{name}.lum', v.get('lum', 0), -15, 15), cl(f'hues.{name}.shift', v.get('shift', 0), -20, 20)
            sm += wgt * (s_ - 1); dl += wgt * l_; dh += wgt * h_
            used['hues'][name] = {'sat': s_, 'lum': l_, 'shift': h_}
        # v0.3.8: in pale, smooth areas (sky, water, white walls) the hue of each pixel is noisy, so a per-colour
        # adjustment would flicker pixel to pixel and show as blotches. Smooth the adjustment maps along the image.
        rr = max(4, min(h, w) // 150); L01h = np.clip(L / 100, 0, 1)
        sm = 1 + guided(L01h, sm - 1, rr, 1e-3); dl = guided(L01h, dl, rr, 1e-3); dh = guided(L01h, dh, rr, 1e-3)
        Cn = np.hypot(a, b) * sm; hn = np.radians(hue + dh)
        a, b = Cn * np.cos(hn), Cn * np.sin(hn); L = L + dl
    ts = P.get('tone_split') or {}
    if ts:
        used['tone_split'] = {}
        Ln = np.clip(L / 100, 0, 1)
        for key, wgt in (('shadows', smoothstep(1 - Ln * 2)), ('highlights', smoothstep(Ln * 2 - 1))):
            if key in ts:
                da, db = cl(f'tone_split.{key}.a', ts[key][0], -8, 8), cl(f'tone_split.{key}.b', ts[key][1], -8, 8)
                a += da * wgt; b += db * wgt; used['tone_split'][key] = [da, db]

    regs = P.get('regions') or []
    if regs:
        used['regions'] = []
        L01 = np.clip(L_in / 100, 0, 1); hue_now = np.degrees(np.arctan2(b, a)) % 360
        for reg in regs:
            m = region_mask(reg, h, w, L01, hue_now, L)
            lift, rs, warm = cl('region.lift', reg.get('lift', 0), -20, 20), cl('region.sat', reg.get('sat', 1), 0.5, 1.6), cl('region.warm', reg.get('warm', 0), -8, 8)
            if lift > 0 and not reg.get('lift_dark', False):
                # v0.3.7: light only brightens what it falls on. A lift acts in proportion to the surface's own brightness,
                # so a dark background (velvet, night sky, showcase black) is not turned into a visible glowing oval.
                m_l = m * np.clip((L_in - 6.0) / 30.0, 0, 1) ** 1.5
                m_l = np.clip(guided(L01, m_l, max(3, min(h, w) // 150), 1e-3), 0, 1)
            else:
                m_l = m
            L = L + lift * m_l; a *= 1 + (rs - 1) * m; b = b * (1 + (rs - 1) * m) + warm * m
            used['regions'].append({**{k: reg[k] for k in reg if k in ('shape', 'box', 'from', 'end', 'feather', 'edge_aware', 'only_hue', 'only_L', 'lift_dark')},
                                    'lift': lift, 'sat': rs, 'warm': warm, 'mask_area_fraction': round(float(m.mean()), 3)})
    vg = P.get('vignette') or {}
    va = cl('vignette.amount', vg.get('amount', 0), 0, 10)
    if va:
        # v0.3.7: a vignette is light falling off towards the frame edge - centred near the middle,
        # so it cannot press a dark blotch into one side of the picture.
        cx0, cy0 = vg.get('centre', [0.5, 0.5]); rad = cl('vignette.radius', vg.get('radius', 0.8), 0.6, 1.2)
        cx, cyy = cl('vignette.centre.x', cx0, 0.35, 0.65), cl('vignette.centre.y', cy0, 0.35, 0.65)
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        d = np.sqrt(((xx / max(w - 1, 1) - cx)) ** 2 + ((yy / max(h - 1, 1) - cyy)) ** 2) / (0.7071 * rad)
        L = L - va * smoothstep((d - 0.45) / 0.75); used['vignette'] = {'amount': va, 'centre': [cx, cyy], 'radius': rad}

    # soft shoulder and toe: no hard clipping introduced by the grade
    # (only where the grade itself pushed a pixel further out than it was; untouched pixels stay as they are)
    L = np.where((L > 94) & (L > L_in), np.maximum(93 + 5 * np.tanh((L - 93) / 5), np.minimum(L_in, 100)), L)
    L = np.where((L < 3) & (L < L_in), np.minimum(3 * np.exp((L - 3) / 3), np.maximum(L_in, 0)), L)
    lin2 = lab_to_lin(np.stack([L, a, b], -1))
    # bring out-of-gamut colours back by reducing chroma towards the pixel's own grey
    grey = np.clip((lin2 @ np.array([0.2126729, 0.7151522, 0.072175], np.float32)), 0, 1)[..., None]
    mx, mn = lin2.max(-1, keepdims=True), lin2.min(-1, keepdims=True)
    tt = np.ones_like(mx)
    ceil = np.maximum(0.955, to_linear(src).max(-1, keepdims=True))     # a graded pixel may not end brighter than ~sRGB 250 unless it already was
    grey = np.minimum(grey, ceil)
    over = mx > ceil; tt = np.where(over, np.minimum(tt, (ceil - grey) / np.maximum(mx - grey, 1e-6)), tt)
    under = mn < 0; tt = np.where(under, np.minimum(tt, grey / np.maximum(grey - mn, 1e-6)), tt)
    out_rgb = np.clip(to_srgb(grey + (lin2 - grey) * np.clip(tt, 0, 1)), 0, 1)
    save_png(out_rgb, out)

    lab1 = lin_to_lab(to_linear(out_rgb))
    u0, u1 = np.uint8(np.rint(src * 255)), np.uint8(np.rint(out_rgb * 255))
    chroma = lambda z: float(np.hypot(z[..., 1], z[..., 2]).mean())
    m = {'L_mean_change': round(float(lab1[..., 0].mean() - lab0[..., 0].mean()), 2), 'L_max_abs_change': round(float(np.abs(lab1[..., 0] - lab0[..., 0]).max()), 1),
         'chroma_ratio': round(chroma(lab1) / max(chroma(lab0), 1e-6), 3),
         'clipped_white_in': round(float(np.any(u0 == 255, 2).mean()), 5), 'clipped_white_out': round(float(np.any(u1 == 255, 2).mean()), 5),
         'clipped_black_in': round(float(np.all(u0 <= 2, 2).mean()), 5), 'clipped_black_out': round(float(np.all(u1 <= 2, 2).mean()), 5),
         'structure_corr': round(structure_corr(lab0[..., 0], lab1[..., 0]), 4)}
    flags = []
    if m['structure_corr'] < 0.90: flags.append(f"STRUCTURE_LOW {m['structure_corr']}: the grade changed local structure; reduce clarity / regions")
    if m['clipped_white_out'] > max(m['clipped_white_in'], 0.001) * 1.5: flags.append('NEW_HIGHLIGHT_CLIPPING')
    if m['clipped_black_out'] > max(m['clipped_black_in'], 0.002) * 2: flags.append('NEW_SHADOW_CLIPPING')
    if clamps: flags.append('PARAMS_CLAMPED')
    rec = {'tool': 'grade.py v0.3.8 (deterministic, non-generative)', 'input': {'file': Path(inp).name, 'sha256': sha256(inp), 'size': [w, h]},
           'output': {'file': Path(out).name, 'sha256': sha256(out), 'size': [w, h]}, 'params_used': used, 'clamped': clamps, 'measurements': m, 'flags': flags,
           'verdict': 'DONE' + (' | FLAGS: ' + '; '.join(flags) if flags else '') + ' - judge by eye against the brief'}
    text = json.dumps(rec, ensure_ascii=False, indent=1)
    if receipt:
        Path(receipt).write_text(text, encoding='utf-8')
    print(text)


if __name__ == '__main__':
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else None)
