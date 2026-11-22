#!/usr/bin/env python3
"""Photographic Studio v1.4.0 - N as a directed, deterministic grading tool ("the hands that follow the brief").
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
  key_light:     v1.3.0 - {box: subject [x0,y0,x1,y1], from: left|right|top|bottom|front, light: auto|diffuse, strength: 0..1,
                 what: text}. The frame's light gathers on the subject and the surroundings fall off; the size comes from
                 the original's own light (directional about 7 L* of separation, diffuse/overcast about 4, mostly by the
                 edges receding). A plain sky is never lifted or darkened.
                 v1.4.0: lift only on the original's lit mid-tones, wide falloff kept off bright sky; strength up to 1.2
                 (finish.py's gate remedy); "light": "directional" locks directional mode where the original has sun.
  anchor:        v1.4.0 - true | {target: -3..0}: the original's darkest 15 % pressed ~2.5 L* (base layer only)
  split_tone:    v1.4.0 - true | {warm: 0..2, cool: -1.5..0}: lit faces warmer, shadows neutral/cool (not near-neutral)
  texture:       v1.4.0 - 0..0.28: structure-aware mid-frequency micro-contrast (+-3.5 L* per pixel, never on sky)
  chroma_compress: v1.4.0 - 0..3: compress only the over-saturated top of the chroma (settle.py uses it)
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


KEY_TARGET = {'directional': 9.0, 'diffuse': 4.0}      # L* added between the subject and its surroundings (v1.4.0: 7 -> 9)
KEY_SPLIT = {'directional': 0.45, 'diffuse': 0.25}     # share of that done by lifting the subject (the rest: surroundings fall off)
KEY_LIFT_MAX = {'directional': 6.0, 'diffuse': 3.0}    # v1.4.0: the lit side of the subject +4.5..6 L* (directional)
KEY_FALL_MAX = {'directional': 7.5, 'diffuse': 7.5}    # v1.4.0: the surroundings -4.5..7.5 L*
KEY_RAMP = {'left': lambda xx, yy: 1 - xx, 'right': lambda xx, yy: xx, 'top': lambda xx, yy: 1 - yy, 'bottom': lambda xx, yy: yy}


def key_light(kl, L, L_in, lab0, ref, h, w):
    """v1.3.0: the key light - the frame's light gathers on the subject and its surroundings fall off, the way the
    light in the scene already runs. One move for the whole frame, in place of scattered small region lifts.
      box: the subject [x0, y0, x1, y1]; from: left|right|top|bottom|front (where the light in the original comes
      from); light: auto|directional|diffuse; strength 0..1 (v1.4.0: finish.py may raise it to 1.2 when a gate fails).
    How much is set by the ORIGINAL's light (ps_common.light_character), not by the brief: a directional light gets
    about 9 L* more separation between the subject and its surroundings (v1.4.0), a diffuse overcast light about 4,
    done mostly by letting the edges and foreground recede (user 2026-11-21: no spotlight on a flat rain sky). The brief
    can make it quieter ("light": "diffuse", or a lower strength). v1.4.0: "light": "directional" locks directional
    mode, but only when the original shows direct sun (sun patches or a clear gradient towards "from"; an overcast frame
    stays diffuse whatever the brief says).
    v1.4.0 - driven by two luminance masks of the ORIGINAL:
      lift  only the subject's lit mid-tones (L* about 35..88, smooth), so the shadow gaps inside the subject box are
            not lifted - the light falls on the lit faces, the dark seams stay dark;
      fall  a wide, soft falloff around the subject that fades out on bright sky and highlights (L* > 80), so a sky
            gets no ring and the corners no dirty vignette.
    Guards: a plain bright sky gets neither light nor shade; the light follows the surfaces (edge-aware); near-black
    and clipped tones are left alone."""
    from ps_common import light_character
    ref_lab = lab0
    if ref and Path(ref).exists():
        rr = load_rgb(ref)
        if rr.shape[:2] == (h, w): ref_lab = lin_to_lab(to_linear(rr))
    src_dir = kl.get('from', 'front')
    ch = light_character(ref_lab[..., 0], np.hypot(ref_lab[..., 1], ref_lab[..., 2]), src_dir, ref_lab[..., 2])
    mode = ch['light']
    if kl.get('light') == 'diffuse': mode = 'diffuse'          # the brief may make it quieter
    elif kl.get('light') == 'directional' and mode == 'diffuse':
        # v1.4.0: the brief may lock directional only where the original shows direct sun
        if ch.get('sun_patches', 0) >= 0.005 or ch.get('gradient_L', 0) >= 3.0:
            mode = 'directional'; ch['locked_by_brief'] = True
        else:
            ch['lock_refused'] = 'no sun patches and no gradient towards "from" in the original: kept diffuse'
    st = cl('key_light.strength', kl.get('strength', 1.0), 0, 1.2)
    x0, y0, x1, y1 = [float(v) for v in kl['box']]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32); yy /= max(h - 1, 1); xx /= max(w - 1, 1)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    rx, ry = max((x1 - x0) / 2, 0.05), max((y1 - y0) / 2, 0.05)
    d = np.sqrt(((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2)
    S = 1 - smoothstep((d - 0.7) / 1.1)                         # full on the subject, falling off over about one subject width
    So = 1 - smoothstep((d - 0.8) / 1.8)                        # v1.4.0: the falloff starts later and is much softer
    if src_dir in KEY_RAMP:                                     # the side the light comes from stays a little brighter
        S = np.clip(0.8 * S + 0.2 * KEY_RAMP[src_dir](xx, yy), 0, 1)
        So = np.clip(0.8 * So + 0.2 * KEY_RAMP[src_dir](xx, yy), 0, 1)
    L01 = np.clip(L_in / 100, 0, 1); r = max(6, min(h, w) // 30)
    S = np.clip(guided(L01, S.astype(np.float32), r, 1e-3), 0, 1)       # the light stops at object edges, not in mid-air
    So = np.clip(blur(So.astype(np.float32), max(8, min(h, w) // 12)), 0, 1)   # wide feather: no edge to the falloff
    sky = sky_mask(L_in, gaps=True)
    surf = (~sky).astype(np.float32)
    if sky.any():
        surf = np.clip(guided(L01, surf, max(3, min(h, w) // 200), 1e-4), 0, 1) * (~sky)   # never any change on the plain sky
    tot = KEY_TARGET[mode] * st; lift = tot * KEY_SPLIT[mode]; fall = tot - lift
    Lr = ref_lab[..., 0]                                                   # masks from the ORIGINAL's light
    Lrs = guided(np.clip(Lr / 100, 0, 1), Lr, max(3, min(h, w) // 200), 4e-3)
    lit_mid = smoothstep((Lrs - 30.0) / 10.0) * (1 - smoothstep((Lrs - 84.0) / 8.0))   # L* ~35..88: the lit faces
    sub = S * surf * lit_mid
    out_w = (1 - So) * surf * smoothstep((L_in - 4.0) / 20.0)              # near-black shadows are not pushed into black
    if mode == 'diffuse':
        # overcast: the eye is led by the frame edges and the foreground receding, not by a pool of light
        edge = np.clip(np.maximum(np.abs(xx - 0.5), np.abs(yy - 0.5)) * 2, 0, 1)
        out_w = out_w * (0.45 + 0.55 * smoothstep(np.maximum(edge, yy * 1.2 - 0.3)))
    out_w = out_w * (1 - smoothstep((Lrs - 76.0) / 8.0))                    # v1.4.0: bright sky, lamps, white reflections: no falloff
    # on the G route the input already carries G's light: where G already let the surroundings fall off (or already
    #   lifted the subject) that counts towards the key light (2026-11-21 vase: G had darkened the left screens by up to
    #   20 L*; another 6 on top read as a dark patch)
    g_dark = np.clip(blur(ref_lab[..., 0] - L_in, max(8, min(h, w) // 40)), 0, None) if ref_lab is not lab0 else 0.0
    g_lift = np.clip(blur(L_in - ref_lab[..., 0], max(8, min(h, w) // 40)), 0, None) if ref_lab is not lab0 else 0.0
    sub_m, sur_m = (S > 0.7) & ~sky, (S < 0.25) & ~sky
    sep = lambda X: float(X[sub_m].mean() - X[sur_m].mean()) if sub_m.any() and sur_m.any() else 0.0
    # the masks follow the surfaces and their brightness, so the separation actually gained is less than lift + fall:
    #   measure it once and scale to the target (at most 2.2x; the lift never over 6 L*, the falloff never over 8)
    shape = lambda li, fa: L + np.clip(li - g_lift, 0, None) * sub - np.clip(fa - g_dark, 0, None) * out_w
    gain = sep(shape(lift, fall)) - sep(L)
    lmax, fmax = KEY_LIFT_MAX[mode] * max(st, 1.0), KEY_FALL_MAX[mode] * max(st, 1.0)
    if gain > 0.3:
        k = min(2.2, tot / gain); lift, fall = min(lmax, lift * k), min(fmax, fall * k)
    Lk = shape(lift, fall)
    info = {'light_in_original': ch, 'mode': mode, 'from': src_dir, 'strength': st, 'lift_L': round(lift, 2), 'falloff_L': round(fall, 2),
            'subject_minus_surroundings_L': {'before': round(sep(L), 2), 'after': round(sep(Lk), 2)},
            'sky_untouched': bool(sky.any()), 'box': [x0, y0, x1, y1]}
    if kl.get('what'): info['what'] = kl['what']
    return Lk, info


def _ref_lab(ref, lab0, h, w):
    if ref and Path(ref).exists():
        rr = load_rgb(ref)
        if rr.shape[:2] == (h, w): return lin_to_lab(to_linear(rr))
    return lab0


def black_anchor(an, L, Lref, h, w):
    """v1.4.0: the black anchor. The darkest 15 % of the ORIGINAL (a fixed region, "fixed_dark_L") is pressed about
    2.5 L* below the original - as a tone curve of the original's own brightness, so no patch can appear - which
    gives the frame its depth instead of the lifted, grey HDR shadows G tends to make (2026-11-22 courtyard: darks
    +11.6..+14.5 from G, the final's light/shade separation 10.5 % under the original's). Bounds: never more than
    3.5 under the original (no dead black screen); a night photo (finish.py: target 0) or a frame where nothing is
    properly exposed is only kept from rising.
      anchor: true | {target: -3..0 (L*, default -2.5)}"""
    from ps_common import dark_anchor_mask, unexposed
    tgt = -2.5 if an is True else cl('anchor.target', (an or {}).get('target', -2.5), -3.0, 0.0)
    night = unexposed(Lref) or tgt >= 0      # finish.py passes target 0 for a declared night photo
    if night: tgt = max(tgt, 0.0)
    m = dark_anchor_mask(Lref)
    if not m.any(): return L, {'skipped': 'no dark region'}
    cur = float(L[m].mean() - Lref[m].mean())
    # band: pressed to the target from above; from below (G or the key light already pressed the darks deeper) it is
    #   eased back to just under the target - the later steps (texture, toe) take a little more, and -3.5 is the floor
    lower = -3.0 if night else tgt - 0.6
    want = cur
    if cur > tgt: want = tgt
    elif cur < lower: want = lower + 0.35
    info = {'fixed_dark_L_before': round(cur, 2), 'target': tgt}
    if abs(want - cur) < 0.1:
        info['action'] = 'already anchored'; return L, info
    # a tone curve of the ORIGINAL's brightness - the same change for the same original tone everywhere, so it can
    #   never read as a dark patch (a spatial mask, or a curve of the current smoothed light, did on the b2_08 museum
    #   background: physics_check removes exactly such a curve before it looks for blotches)
    base = blur(Lref, 1.5)
    q_mid, q45 = np.percentile(base[m], 50), np.percentile(base, 45)
    # the curve fades out over at least 12 L* of original brightness: a steeper one turned smooth gradients into a
    #   visible step on a very dark frame (b1_01: ghost_edges 1.32)
    wgt = np.clip(1 - smoothstep((base - q_mid) / max(q45 - q_mid, 12.0)), 0, 1)
    if want < cur: wgt = wgt * smoothstep((L - 1.5) / 8.0)          # the very blackest is not pushed into dead black
    k = want - cur
    for _ in range(4):   # the weight is < 1 in parts of the region: scale until the region's mean lands on the target
        Ln = L + np.clip(k * wgt, -7.0, 7.0)      # per pixel at most 7 L* (base layer only)
        got = float(Ln[m].mean() - Lref[m].mean())
        if abs(got - want) < 0.15 or abs(got - cur) < 1e-3: break
        k = float(np.clip(k * (want - cur) / (got - cur), -12.0, 12.0))
    info.update({'fixed_dark_L_after': round(float(Ln[m].mean() - Lref[m].mean()), 2), 'action': f'{round(want - cur, 2)} L* as a tone curve of the original'})
    return Ln, info


def split_tone(sp, L, a, b, lab_ref, h, w):
    """v1.4.0: a light warm/cool split. Lit faces +1.5..2.0 b* (not near-neutral white walls and grey stone, which stay
    as they are), shadows neutral to slightly cool (-1.0..1.5 b*). What G already did counts: no stacking.
      split_tone: true | {warm: 0..2, cool: -1.5..0}"""
    Lr, ar, br = lab_ref[..., 0], lab_ref[..., 1], lab_ref[..., 2]
    from ps_common import unexposed
    if unexposed(Lr): return a, b, {'skipped': 'nothing in the frame is properly exposed'}   # night: finish.py leaves it out
    warm = 1.75 if sp is True else cl('split_tone.warm', (sp or {}).get('warm', 1.75), 0, 2.0)
    cool = -1.25 if sp is True else cl('split_tone.cool', (sp or {}).get('cool', -1.25), -1.5, 0)
    L01 = np.clip(L / 100, 0, 1)
    base = guided(L01, L, max(6, min(h, w) // 40), 4.0)
    Cr = blur(np.hypot(ar, br), 3)
    colourful = np.clip((Cr - 6.0) / 4.0, 0, 1)                     # near-neutral (C* < ~8) gets nothing
    lit_w = smoothstep((base - 55.0) / 20.0) * colourful
    sh_w = (1 - smoothstep((base - 15.0) / 25.0)) * smoothstep((base - 3.0) / 8.0)
    from ps_common import sky_mask as _sm
    sky = _sm(Lr, gaps=True)
    lit_w = lit_w * (~sky); sh_w = sh_w * (~sky)
    gw = float(((b - br) * lit_w).sum() / max(lit_w.sum(), 1e-6)) if lit_w.sum() > 50 else 0.0
    gc = float(((b - br) * sh_w).sum() / max(sh_w.sum(), 1e-6)) if sh_w.sum() > 50 else 0.0
    w_add = float(np.clip(warm - max(gw, 0.0), 0, warm)); c_add = float(np.clip(cool - min(gc, 0.0), cool, 0))
    # stay inside the lit-warmth limit (intensity_check: mean b* change on the original's L* > 55, at most 4.0): an
    #   excess made here is taken off by settle.py with a GLOBAL white-balance shift, which drained the lanterns'
    #   colour on b1_01 (2026-11-22). Budget 3.5.
    lit_i = (Lr > 55) & (~sky)
    budget = None
    if lit_i.mean() > 0.02:
        cur = float((b - br)[lit_i].mean()); per = float(lit_w[lit_i].mean())
        budget = round(3.5 - cur, 2)
        if per > 1e-3: w_add = float(np.clip(min(w_add, (3.5 - cur) / per), 0, w_add))
    b = b + w_add * lit_w + c_add * sh_w
    return a, b, {'warm_added_b': round(w_add, 2), 'cool_added_b': round(c_add, 2), 'already_from_earlier_steps': [round(gw, 2), round(gc, 2)],
                  **({'lit_warmth_budget_b': budget} if budget is not None else {})}


TEXTURE_AIM = 1.22   # v1.4.0: structure mid-frequency contrast vs the original (the gate's band is 1.15..1.35)


def texture(tx, L, Lref, h, w):
    """v1.4.0: material texture by structure-aware mid-frequency micro-contrast. Radius about 1.4 % of the short edge,
    low amount (<= 0.28), each pixel's change soft-limited to +-3.5 L*, and only on the original's structure (stone,
    wood, leaves): 0 on a plain sky and on flat shadow, damped on strong edges - no sharpening rims.
      texture: 0..0.28 | {amount: 0..0.28}"""
    from ps_common import structure_mask, midfreq
    cap = cl('texture', tx.get('amount', 0.24) if isinstance(tx, dict) else tx, 0, 0.28)
    if cap <= 0: return L, None
    m = structure_mask(Lref)
    d = midfreq(L)
    damp = np.clip(1 - (np.abs(blur(d, 2)) - 8.0) / 12.0, 0.3, 1.0)   # big edges: already strong, damped
    add_at = lambda k: 3.5 * np.tanh(k * d * damp / 3.5)
    # the amount aims the structure's mid-frequency contrast at ~1.22x the original's (the brief's value is the cap):
    #   where G or the grade already added texture, less is added; where G smoothed it, up to the cap
    sel = m > 0.5
    info = {'cap': cap, 'structure_area': round(float(sel.mean()), 3)}
    amt = cap
    if sel.mean() > 0.02:
        ref = float(np.abs(midfreq(Lref))[sel].mean()) + 1e-6
        r0 = float(np.abs(d)[sel].mean()) / ref
        r1 = float(np.abs(midfreq(L + add_at(cap) * m))[sel].mean()) / ref
        eff = (r1 - r0) / cap if r1 > r0 else 0.0
        amt = float(np.clip((TEXTURE_AIM - r0) / eff, 0, cap)) if eff > 1e-3 else 0.0
        info.update({'ratio_before': round(r0, 3), 'aim': TEXTURE_AIM})
    add = add_at(amt)
    L = L + add * m
    info.update({'amount': round(amt, 3), 'max_abs_change_L': round(float(np.abs(add * m).max()), 2)})
    return L, info


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
    kl = P.get('key_light')
    if isinstance(kl, dict) and kl.get('box'):
        L, used['key_light'] = key_light(kl, L, L_in, lab0, P.get('auto_ref'), h, w)
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

    # v1.4.0: depth, colour order and texture - measured against the ORIGINAL (auto_ref on the G route)
    if any(P.get(k) for k in ('anchor', 'split_tone', 'texture', 'chroma_compress')):
        lab_r = _ref_lab(P.get('auto_ref'), lab0, h, w)
        if P.get('anchor'):
            L, used['anchor'] = black_anchor(P['anchor'], L, lab_r[..., 0], h, w)
        if P.get('split_tone'):
            a, b, used['split_tone'] = split_tone(P['split_tone'], L, a, b, lab_r, h, w)
        if P.get('texture'):
            L, ti = texture(P['texture'], L, lab_r[..., 0], h, w)
            if ti: used['texture'] = ti
        if P.get('chroma_compress'):
            from ps_common import zoned_chroma
            a, b, used['chroma_compress'] = zoned_chroma(a, b, cl('chroma_compress', P['chroma_compress'], 0, 3))

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
    rec = {'tool': 'grade.py v1.4.0 (deterministic, non-generative)', 'input': {'file': Path(inp).name, 'sha256': sha256(inp), 'size': [w, h]},
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
