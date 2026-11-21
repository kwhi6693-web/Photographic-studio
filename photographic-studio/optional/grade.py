#!/usr/bin/env python3
"""Photographic Studio v1.2.0 - N as a directed, deterministic grading tool ("the hands that follow the brief").
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
                          edge_aware: bool, only_hue: name, only_L: [lo, hi], on_structure: bool (v1.2.0: skip smooth areas),
                          lift: -20..20 (L), sat: 0.5..1.6, warm: -8..8 (Lab b),
                          clarity: 0..0.5 (v1.2.0: mid-scale local contrast inside the region only)}
  moves:         v1.2.0 - the brief's improvement moves: the same fields as a region plus
                 {what: "deepen the sky towards the top", look: light+|light-|colour+|colour-|warm+|warm-|contrast+}.
                 They are graded exactly like regions; improve_check.py then measures whether each one is visible.
  vignette:      {amount: 0..10 (L at the corners), centre: [x, y] each 0.35..0.65, radius: 0.6..1.2} (v0.3.7: centred, no off-centre blotch)
  auto:          v1.2.7 - the automatic base adjustment, computed from THIS image before everything above:
                 true (all parts at full strength), false/absent (off), or {wb, dehaze, levels, contrast, vibrance: 0..1}.
                 wb: white balance from the near-neutral pixels (a warm low-sun scene keeps most of its warmth);
                 dehaze: evens out a grey veil that lifts the blacks in part of the frame; levels: black and white point
                 from this photo's own darkest / brightest tones (not a fixed scale); contrast: S-curve pivoted on this
                 photo's median; vibrance: a little more colour, more on a dull photo. A photo that already has clean
                 blacks, clean whites, neutral greys and normal contrast is left almost unchanged.
"""
import json, sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ps_common import load_rgb, save_png, to_linear, to_srgb, lin_to_lab, lab_to_lin, blur, guided, structure_corr, sha256, HUES, hue_weight, tone_needs, sky_mask

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
    if reg.get('also'):   # v1.2.6: the same edit on more boxes (a white stone and its reflection in the water)
        m = region_mask({**reg, 'also': None}, h, w, L01, hue, L)
        for bx in reg['also']:
            m = np.maximum(m, region_mask({**reg, 'also': None, 'box': bx}, h, w, L01, hue, L))
        return m
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
    if reg.get('on_structure'):
        # v1.2.0: only on things with structure (buildings, foliage, objects), not on smooth sky, water haze or walls -
        # a light or colour move feathered across a smooth area shows as a halo around the subject
        tex = blur(np.abs(L - blur(L, 3)), max(3, min(h, w) // 200))
        m = m * np.clip(guided(L01, smoothstep((tex - 0.6) / 2.0), max(3, min(h, w) // 150), 1e-3), 0, 1)
    return m


AUTO_PARTS = ('wb', 'dehaze', 'levels', 'contrast', 'vibrance')


def auto_strengths(v):
    if v is True: return {k: 1.0 for k in AUTO_PARTS}
    if isinstance(v, dict): return {k: cl(f'auto.{k}', v.get(k, 1.0), 0, 1) for k in AUTO_PARTS}
    return None


def auto_wb(lin, s, lab_ref):
    """v1.2.7: white balance only from the ORIGINAL's near-neutral areas (chroma < 8: grey stone, concrete, white walls,
    overcast sky - not foliage, not a blue sky). Returns (gains, info) or (None, info).
    It does nothing when: the original has too little near-neutral area; it is a night or blue-hour frame (cool there is
    the light, not a cast); the dark and light greys do not share the cast (a beige wall or a blue shadow alone is the
    scene's colour); the shared cast is warm and mild (warm stone, wood, low sun). It corrects at most 3/4 of the cast
    still present in THIS image at those same pixels, and never more than the original had - so on the G route a cast
    G already removed is not corrected twice."""
    Lr, ar, br = lab_ref[..., 0], lab_ref[..., 1], lab_ref[..., 2]
    neu = (np.hypot(ar, br) < 8) & (Lr > 15) & (Lr < 96)
    info = {'neutral_area_in_original': round(float(neu.mean()), 3)}
    if float(Lr.mean()) < 40 and float(np.percentile(Lr, 90)) < 70:
        info['skipped'] = 'night or blue-hour frame: its cool colour is the light, not a cast'; return None, info
    lo_b, hi_b = neu & (Lr < 55), neu & (Lr >= 55)
    if neu.mean() < 0.08 or lo_b.mean() < 0.02 or hi_b.mean() < 0.02:
        info['skipped'] = 'not enough near-neutral area (dark and light greys) in the original: no correction'; return None, info
    lab = lin_to_lab(lin); a, b = lab[..., 1], lab[..., 2]
    def shared(ax, bx):
        v1 = np.array([np.median(ax[lo_b]), np.median(bx[lo_b])]); v2 = np.array([np.median(ax[hi_b]), np.median(bx[hi_b])])
        return np.where(np.sign(v1) == np.sign(v2), np.sign(v1) * np.minimum(np.abs(v1), np.abs(v2)), 0.0), v1, v2
    c_ref, v1, v2 = shared(ar, br)
    c_now, _, _ = shared(a, b)
    info['cast_original_dark_light_greys'] = [[round(float(x), 2) for x in v1], [round(float(x), 2) for x in v2]]
    cast = np.where(np.sign(c_ref) == np.sign(c_now), np.sign(c_now) * np.minimum(np.abs(c_ref), np.abs(c_now)), 0.0)
    if cast[1] > 0 and cast[1] < 8:
        cast[1] = 0.0; info['warm_kept'] = 'mild warmth in the greys is kept (warm materials or warm light)'
    lit, shade = Lr > 60, (Lr > 15) & (Lr < 40)
    k_b = 0.75 * s
    if cast[1] > 0:
        k_b = 0.3 * s
        if lit.mean() > 0.03 and shade.mean() > 0.03 and float(br[lit].mean() - br[shade].mean()) > 4:
            k_b = 0.15 * s; info['warm_light_kept'] = 'lit areas clearly warmer than shade: low sun, its warmth is kept'
    corr = np.array([cast[0] * 0.75 * s, cast[1] * k_b])
    if float(np.hypot(*corr)) < 1.0:
        info.setdefault('skipped', 'no cast shared by the dark and light greys'); return None, info
    m = lin[neu].mean(0)
    lab_m = lin_to_lab(m[None, None, :].astype(np.float32))[0, 0]
    want = lab_to_lin(np.array([[[lab_m[0], lab_m[1] - corr[0], lab_m[2] - corr[1]]]], np.float32))[0, 0]
    g = np.clip(np.maximum(want, 1e-6) / np.maximum(m, 1e-6), 0.85, 1.18).astype(np.float32)
    g = g / float(g @ np.array([0.2126729, 0.7151522, 0.072175], np.float32))   # keep luminance
    info['removed_ab'] = [round(float(x), 2) for x in corr]; info['gains_rgb'] = [round(float(x), 4) for x in g]
    return g, info


def auto_tone(L, a, b, s, h, w, L_ref):
    """v1.2.7: dehaze, levels and pivoted contrast. WHETHER a photo may be opened up is decided by the ORIGINAL
    (tone_needs on L_ref: narrow range or lifted blacks); HOW MUCH is measured on this image, so on the G route what G
    already stretched is not stretched again. Haze here means a grey veil over the whole frame (behind glass, flare, a
    dull exposure): no true black anywhere. Weather fog that thickens with distance is the scene's mood: it has true
    darks in front, so it is left alone. Returns L, a, b, info."""
    info = {}
    L_start = L.copy()
    need_o = tone_needs(L_ref); need = tone_needs(L)
    info['original'] = {k: (round(v, 1) if isinstance(v, float) else v) for k, v in need_o.items()}
    if need_o['night']:
        info['skipped'] = 'night or low-key original: its darkness is kept'; return L, a, b, info
    if s['dehaze'] and need_o['veil'] > 0 and need['veil'] > 0:
        V = min(need['veil'], need_o['veil']) * 0.75 * s['dehaze']     # subtract the veil, restore the colour it washed out
        f = 100.0 / (100.0 - V)
        L = (L - V) * f; a = a * f; b = b * f
        info['dehaze'] = {'veil_removed_L': round(V, 1)}
    # a BRIGHT sky (starting above L* 80) is kept as it is while the land opens up; a grey sky in a veiled photo is part
    #   of the veil and opens up with everything else
    sky_lo = need_o.get('sky_p5') if ((need_o.get('sky_fraction') or 0) > 0.03 and (need_o.get('sky_p5') or 0) >= 80) else None
    if s['levels'] and sky_lo is not None and need_o['stretch_ok']:
        # v1.2.7: bright sky over grey land - open the LAND up with one global curve that stops below where the sky
        #   begins. One curve for the whole frame (no masks, so no rim along the treetops), and the sky's own tones are
        #   left as they are (nothing pushed to dead white).
        sm = sky_mask(L_ref, gaps=True) if L_ref.shape == L.shape else np.zeros(L.shape, bool)
        land = L[~sm] if (~sm).mean() > 0.3 else L.ravel()
        lo, hi = float(np.percentile(land, 0.5)), float(np.percentile(land, 99.7))
        top = min(sky_lo - 4.0, 94.0)
        tlo = lo + (2.0 - lo) * 0.9 * s['levels'] if lo > 4 else lo
        thi = hi + (top - hi) * 0.7 * s['levels'] if hi < top else hi
        if hi - lo > 5 and thi > tlo and (tlo != lo or thi > hi) and thi < sky_lo:
            xs = [0.0, lo, hi, sky_lo, 100.0]; ys = [0.0, tlo, thi, sky_lo, 100.0]
            if lo <= 0.5: xs, ys = xs[1:], ys[1:]
            L = np.interp(L, xs, ys).astype(np.float32)
            k = (thi - tlo) / (hi - lo); c = 1 + (min(k, 2.0) - 1) * 0.5
            land_w = np.clip((sky_lo - L) / 6.0, 0, 1)            # colour follows the land's stretch, the sky's stays
            a = a * (1 + (c - 1) * land_w); b = b * (1 + (c - 1) * land_w)
            info['levels'] = {'land_from': [round(lo, 1), round(hi, 1)], 'land_to': [round(tlo, 1), round(thi, 1)],
                              'sky_from_L': round(sky_lo, 1), 'sky': 'unchanged above this'}
        else:
            info['levels'] = {'skipped': 'land already open up to the sky'}
    elif s['levels']:
        lo, hi = float(np.percentile(L, 0.5)), float(np.percentile(L, 99.7))
        tlo = lo + (2.0 - lo) * 0.9 * s['levels'] if lo > 4 else lo
        if need_o['stretch_ok']:
            thi = hi + (94.0 - hi) * 0.7 * s['levels'] if hi < 88 else hi
        else:
            # normal photo: whites at most 2.5 L* above the ORIGINAL's (the 2026-11-11 limit is 3; the rest is left for
            #   the moves), and none at all when G already raised them - no stacking on the G route
            cap = need_o['p99.7'] + 2.5
            thi = max(hi, min(hi + (94.0 - hi) * 0.7 * s['levels'], cap)) if hi < 88 else hi
        if hi - lo > 5 and (tlo != lo or thi != hi):
            k = min((thi - tlo) / (hi - lo), 2.0)
            mid_to = (tlo + thi) / 2                              # a capped stretch opens out from the middle
            tlo, thi = mid_to - (hi - lo) * k / 2, mid_to + (hi - lo) * k / 2
            L = mid_to + (L - (lo + hi) / 2) * k
            c = 1 + (k - 1) * 0.5; a = a * c; b = b * c
            info['levels'] = {'from': [round(lo, 1), round(hi, 1)], 'to': [round(tlo, 1), round(thi, 1)], 'stretch': round(k, 3)}
        else:
            info['levels'] = {'skipped': 'blacks and whites already set'}
    med0, med1 = float(np.median(L_start)), float(np.median(L))
    if med1 < med0 - 3 and 5 < med1 < 95:
        # removing a veil darkens the midtones: give back all but 3 L* with a gamma that keeps black and white in place
        g = np.log((med0 - 3) / 100) / np.log(med1 / 100)
        L = np.where((L > 0) & (L < 100), 100 * np.clip(L / 100, 1e-6, 1) ** g, L)
        info['midtones_kept'] = {'median_before': round(med0, 1), 'after': round(med1, 1), 'gamma': round(float(g), 3)}
    if s['contrast']:
        sm = sky_mask(L_ref, gaps=True) if (sky_lo is not None and L_ref.shape == L.shape) else None
        land = L[~sm] if sm is not None and (~sm).mean() > 0.3 else L.ravel()
        sd = float(land.std())
        c = float(np.clip((22.0 - sd) / 40.0, 0, 0.18)) * s['contrast']     # flat photos get more, punchy ones none
        if c > 0.01:
            p = float(np.clip(np.median(land), 25, 75)) / 100
            g = np.log(0.5) / np.log(p)
            x = np.clip(L / 100, 0, 1) ** g
            x = x - c * np.sin(2 * np.pi * x) / (2 * np.pi)
            Ls = 100 * np.clip(x, 0, 1) ** (1 / g)
            wgt = np.ones_like(L) if sky_lo is None else np.clip((sky_lo - 2.0 - L) / 8.0, 0, 1)   # v1.2.7: the sky keeps its tones
            L = np.where((L >= 0) & (L <= 100), L + (Ls - L) * wgt, L)
            info['contrast'] = {'amount': round(c, 3), 'pivot_L': round(p * 100, 1), 'L_std_before': round(sd, 1),
                                **({'fades_out_from_L': round(sky_lo - 10, 1)} if sky_lo is not None else {})}
        else:
            info['contrast'] = {'skipped': f'contrast already normal (land L std {round(sd, 1)})'}
    return L, a, b, info


def main(inp, out, params_path, receipt=None):
    P = json.loads(Path(params_path).read_text(encoding='utf-8'))
    src = load_rgb(inp)
    h, w = src.shape[:2]
    lin = to_linear(src)
    used = {}
    A = auto_strengths(P.get('auto'))
    auto_info = {}
    if A:
        # v1.2.7: the original decides whether and what to correct; on the G route (finish.py passes "auto_ref") this
        #   image is G-toned and only measured for how much is still left to do
        ref = P.get('auto_ref')
        ref_rgb = load_rgb(ref) if ref and Path(ref).exists() else src
        if ref_rgb.shape != src.shape:
            from PIL import Image as _I
            ref_rgb = np.asarray(_I.fromarray(np.uint8(np.rint(ref_rgb * 255))).resize((w, h), _I.LANCZOS)).astype(np.float32) / 255
        lab_ref = lin_to_lab(to_linear(ref_rgb))
        if ref: auto_info['measured_against'] = 'original (auto_ref)'
    if A and A['wb']:
        g_auto, auto_info['wb'] = auto_wb(lin, A['wb'], lab_ref)
        if g_auto is not None: lin = lin * g_auto

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
    if A:
        L, a, b, info = auto_tone(L, a, b, A, h, w, lab_ref[..., 0]); auto_info.update(info)

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
    if A and A['vibrance'] and tone_needs(lab_ref[..., 0])['stretch_ok']:
        # v1.2.7: only for a flat or veiled original (the veil washed its colour out); a normal photo's colour is the
        #   brief's business (on the 2026-11-15 sunset gate an automatic vibrance pushed the warmth over its limit)
        av = (0.22 if float(np.hypot(lab_ref[..., 1], lab_ref[..., 2]).mean()) < 10 else 0.12) * A['vibrance']
        vib = min(0.8, vib + av); auto_info['vibrance'] = round(av, 3)
    if auto_info: used['auto'] = auto_info
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

    regs = (P.get('regions') or []) + (P.get('moves') or [])   # v1.2.0: moves are graded like regions
    if regs:
        used['regions'] = []
        L01 = np.clip(L_in / 100, 0, 1); hue_now = np.degrees(np.arctan2(b, a)) % 360
        for reg in regs:
            m = region_mask(reg, h, w, L01, hue_now, L)
            lift, rs, warm = cl('region.lift', reg.get('lift', 0), -20, 20), cl('region.sat', reg.get('sat', 1), 0.5, 1.6), cl('region.warm', reg.get('warm', 0), -8, 8)
            rcl = cl('region.clarity', reg.get('clarity', 0), 0, 0.5)
            if rcl:   # v1.2.0: local contrast inside this region only (midtones, same scale as global clarity)
                dloc = L - blur(L, max(8, min(h, w) // 50)); mid = 1 - np.abs(np.clip(L, 0, 100) - 50) / 50
                L = L + rcl * dloc * (0.4 + 0.6 * mid) * m
            if lift > 0 and not reg.get('lift_dark', False):
                # v0.3.7: light only brightens what it falls on. A lift acts in proportion to the surface's own brightness,
                # so a dark background (velvet, night sky, showcase black) is not turned into a visible glowing oval.
                m_l = m * np.clip((L_in - 6.0) / 30.0, 0, 1) ** 1.5
                m_l = np.clip(guided(L01, m_l, max(3, min(h, w) // 150), 1e-3), 0, 1)
            else:
                m_l = m
            L = L + lift * m_l; a *= 1 + (rs - 1) * m; b = b * (1 + (rs - 1) * m) + warm * m
            used['regions'].append({**{k: reg[k] for k in reg if k in ('what', 'look', 'shape', 'box', 'also', 'subdue', 'from', 'end', 'feather', 'edge_aware', 'only_hue', 'only_L', 'lift_dark', 'on_structure')},
                                    'lift': lift, 'sat': rs, 'warm': warm, 'clarity': rcl, 'mask_area_fraction': round(float(m.mean()), 3)})
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
    rec = {'tool': 'grade.py v1.2.7 (deterministic, non-generative)', 'input': {'file': Path(inp).name, 'sha256': sha256(inp), 'size': [w, h]},
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
