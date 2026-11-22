#!/usr/bin/env python3
"""Photographic Studio v1.4.0 - harmonize: the last step, run on the file that is actually delivered.

Usage: python3 -I harmonize.py ORIGINAL CANDIDATE OUT.png [RECEIPT.json] [--genre=museum|night] [--params=PARAMS.json]
                                [--check-only] [--light-only]

ORIGINAL must be framed like CANDIDATE: when reframe.py cropped or straightened the photo, run reframe.py with the
same arguments on the original too and pass that copy here.

Why (2026-11-19): checks ran only inside finish.py; settle, reframe and n_trim came after them and were never checked
again, and settle only trims what is over a limit. Two v1.3.0 runs of one garden photo were delivered with the shade
turned warmer than the sunlight (lit-minus-shade b* 7.32 -> -3.43) and with local contrast 0.90 (< 1.0). What the eye
reads first is light, then colour, then depth; this step repairs those locally instead of dropping G, in a fixed order
(brightness and contrast move colour, so colour is settled last), then checks the result once.

1 Light   only when physics_check flags wrong light on the candidate (halo, spotlight glow, darkened lamps or
          patches, highlight order); low-frequency only, edge-aware: the image is split into large-scale light (guided filter) and detail. A
          local bump of light that the original did not have (invented glow) is pulled back; a light the original had
          (lamp, sun patch, lit lattice) that the candidate darkened is brought back. Broad changes - the brief's moves,
          G's overall look - are not touched: only the part that stands out from its surroundings is corrected. Detail
          stays as it is; chroma follows the light change. Fuse: when more than 20% of the frame would need it, the
          light is not patched (it would look dirty) and the receipt asks for G to be called again.
2 Depth   black point (p5 of L*) may rise at most 3 (low-key original) or 6 L* over the original; light/shade
          separation (as physics_check) at least 0.90 of the original (v1.2.5b; 0.75 let photos go flat); the brightest 1%
          at most 3 L* darker than in the original, except inside the brief's own light- moves (--params); local
          contrast at least 1.0x the original.
3 Colour  areas that are near-neutral in the original (white wall, grey stone; not the sky) may drift at most 3 in a*/b* (their
          real light colour is kept - drift, not absolute grey); in daylight the sunlit-minus-shade warmth keeps at least
          half of the original's; a patch (>1% of the frame) that became 1.35x more saturated than its own surroundings, compared with the
          original, is calmed (a frame-wide boost is not a patch); mean chroma
          stays within 1.65x the original (the user's ceiling for G's own colour, 2026-11-19).
4 Check   physics_check.py and intensity_check.py on the result; their verdicts go into the receipt.

v1.4.0 (2026-11-22 courtyard: the final's light/shade separation was held only at 0.90x the original's, so G's
grey HDR shadows were delivered 10.5 % flatter than the photo):
  - light/shade separation at least 1.0x the original's - not flatter - for flat/overcast/rain light (user
    2026-11-22: 1.02 made rainy photos ask for contrast their light does not have), 1.05x when the original's light is directional, as
    grade.py's key light judges it from the brief's key_light). With a key light the added light goes into the subject;
    lit faces are lifted only in the mid-tones (fading out from L* 60 to 85) and at most 6 L*, the shade pressed at most
    3 L* and never below L* 10 - when that is not enough the floor is left short and reported
    (light_shade_floor_not_reached): crushed shadows or washed-out sunlit colour are worse than a missed ratio
    (b1_03, 2026-11-22). Colour follows the lifts; out-of-gamut colours go towards their own grey;
  - black guard: the original's darkest 15 % (fixed_dark_L) may end at most +1.5 L* above the original and at most
    3.5 below; outside that band the dark anchor is set again on the large-scale light (grade.black_anchor);
  - the 1.65x colour ceiling is reached by compressing only the over-saturated top of the chroma, not by scaling
    all colour down.
--check-only writes nothing but the receipt: steps 1-3 report what they would change.
--light-only runs step 1 only (finish.py uses it to repair a G attempt instead of dropping G).
Deterministic. Needs numpy, Pillow, OpenCV (via ps_common).
"""
import json, sys
from pathlib import Path
import numpy as np
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ps_common import load_rgb, save_png, srgb_to_lab, lab_to_lin, to_srgb, blur, guided, sha256, run_tool, sky_surfaces

VERSION = 'harmonize.py v1.4.0'
FUSE_AREA = 0.20
SEP_FLOOR = 1.00   # v1.4.0: light/shade separation vs the original, flat light (was 0.90; 1.02 until 2026-11-22)
SEP_FLOOR_V125 = 0.90
SEP_FLOOR_DIRECTIONAL = 1.05
DARK_UP, DARK_DOWN = 1.5, -3.5   # v1.4.0 black guard on fixed_dark_L
HI_DROP = 3.0      # the brightest 1% may fall at most this much in L*


def smooth(x, a, b):
    t = np.clip((x - a) / max(b - a, 1e-6), 0, 1)
    return t * t * (3 - 2 * t)


def lit_shade(Lo, bo):
    """The same lit / shade split physics_check.py uses (v1.0.2: sky left out)."""
    so = blur(Lo, 12); h = Lo.shape[0]
    skyish = (bo < -12) & (np.abs(Lo - blur(Lo, 4)) < 2.5); skyish[h // 2:] = False
    land = ~skyish
    ref = so[land] if land.mean() > 0.3 else so.ravel()
    p15, p30, p50, p70, p85 = np.percentile(ref, [15, 30, 50, 70, 85])
    lit = (so > p70) & land if land.mean() > 0.3 else so > p70
    shade = (so < p30) & land if land.mean() > 0.3 else so < p30
    wl = smooth(so, p50, p85) * land; ws = (1 - smooth(so, p15, p50)) * land
    return lit, shade, wl.astype(np.float32), ws.astype(np.float32)


def step_light(Lo, L, a, b, r, want_inv=True, want_dark=True, ao=None, bo=None, protect=None):
    eps = 25.0
    base_o, base_c = guided(Lo, Lo, r, eps), guided(L, L, r, eps)
    D = base_c - base_o
    # v1.2.7: remove the global tone curve first (the same original brightness moving the same way everywhere). Opening up
    #   a flat photo brightens all of the sky and darkens all of the buildings; at every sky/building edge that step
    #   looked like a local bump of light and was 'repaired' into a dark smudge over the rooftops (2026-11-20 test).
    bins = np.linspace(0, 100, 41); it = np.clip(np.digitize(base_o, bins) - 1, 0, 39)
    cnt = np.bincount(it.ravel(), minlength=40); xs = (bins[:-1] + bins[1:]) / 2; med = np.zeros(40)
    for i_ in np.nonzero(cnt > 50)[0]: med[i_] = np.median(D[it == i_])
    ok_ = cnt > 50
    if ok_.any(): D = D - np.interp(base_o, xs, np.interp(xs, xs[ok_], med[ok_])).astype(np.float32)
    bump = D - blur(D, 3 * r)                                  # what stands out from its surroundings
    src = (base_o - blur(base_o, 3 * r))                       # where the original itself had a local light
    invented = smooth(bump, 3.0, 8.0) * smooth(D, 2.0, 6.0) * (1 - smooth(src, 3.0, 8.0))   # brighter than the original AND than around it
    corr_inv = -np.maximum(bump - 1.5, 0) * invented
    h, w = Lo.shape                                            # the original's own small lights, as physics_check finds them
    src_px = Lo - blur(Lo, max(6, min(h, w) // 60))            #   (lamps_kept: L* > 80 and > 25 above their surroundings)
    light_src = smooth(src_px, 18.0, 25.0) * smooth(Lo, 72.0, 80.0)
    light_src = np.maximum(light_src, blur(light_src, 2))
    # v1.2.8: a light counts as put out only when it went darker than the rest of the frame at its brightness. When the
    #   whole sky and its reflection go down together (G's smooth gradient on a grey sky, allowed to -7), restoring every
    #   bright patch to the original left white blotches on the water and a pale ring in a sky gap (2026-11-21, photo 03)
    dk_all = Lo - L
    bins_d = np.linspace(0, 100, 41); id_ = np.clip(np.digitize(Lo, bins_d) - 1, 0, 39)
    cnt_d = np.bincount(id_.ravel(), minlength=40); xs_d = (bins_d[:-1] + bins_d[1:]) / 2; med_d = np.zeros(40)
    for i_ in np.nonzero(cnt_d > 200)[0]: med_d[i_] = np.median(dk_all[id_ == i_])
    ok_d = cnt_d > 200
    curve_d = np.interp(Lo, xs_d, np.interp(xs_d, xs_d[ok_d], med_d[ok_d])).astype(np.float32) if ok_d.any() else 0 * Lo
    excess = dk_all - np.maximum(curve_d, 0)                   # darker than the frame's own darkening at that brightness
    darkened = smooth(excess, 4.0, 10.0) * light_src
    corr_inv = corr_inv if want_inv else 0 * corr_inv
    corr_inv = guided(L, corr_inv.astype(np.float32), max(4, r // 2), eps)   # edge-aware, no grey patches
    # a real light the candidate put out comes back at the original's own brightness (it is the original's light),
    # feathered so the edge of the mask does not show
    # the whole bright opening around a put-out light comes back, not just its rim (a half-restored sky gap shows a ring)
    zone = blur((darkened > 0.3).astype(np.float32), r) > 0.02
    opening = smooth(Lo, 68.0, 82.0) * smooth(excess, 2.0, 6.0) * zone
    darkened = np.maximum(darkened, opening)
    if protect is not None: darkened = darkened * ~protect      # the brief darkens there on purpose
    m = np.maximum(darkened, blur(darkened, max(2, r // 8)))
    corr_dark = (np.maximum(excess, 0) * m) if want_dark else 0 * Lo
    corr = (corr_inv + corr_dark).astype(np.float32)
    area = float((np.abs(corr) > 2.0).mean())
    info = {'invented_glow_area': round(float((corr_inv < -2).mean()), 4), 'darkened_light_area': round(float((corr_dark > 2).mean()), 4),
            'area': round(area, 4)}
    if area > FUSE_AREA:
        info['action'] = 'not patched: too large to repair cleanly - call G once more (regen_g)'
        return L, a, b, info, True
    if area < 1e-4:
        info['action'] = 'none'
        return L, a, b, info, False
    L2 = np.clip(L + corr, 0, 100)
    k = np.clip((L2 + 8) / (L + 8), 0.75, 1.3)                 # chroma follows the light change
    if want_dark and ao is not None:                           # a restored light is the original's light: its colour too
        md = np.clip(m, 0, 1)
        a = a * (1 - md) + ao * md / np.maximum(k, 1e-3); b = b * (1 - md) + bo * md / np.maximum(k, 1e-3)
    info['action'] = f'patched {area:.1%} of the frame (max |dL| {float(np.abs(corr).max()):.1f})'
    return L2, a * k, b * k, info, False


def darken_mask(params_path, shape):
    """Where the brief darkens on purpose (moves with look light-): those highlights may go down."""
    if not params_path or not Path(params_path).exists(): return None
    try: P = json.loads(Path(params_path).read_text(encoding='utf-8') or '{}')
    except Exception: return None
    h, w = shape; m = np.zeros(shape, bool)
    for mv in P.get('moves') or []:
        if mv.get('look') != 'light-' and float(mv.get('lift', 0) or 0) >= 0: continue
        if mv.get('shape') == 'gradient':
            e = float(mv.get('end', 0.5)); fr = mv.get('from', 'top')
            if fr == 'top': m[:int(h * e)] = True
            elif fr == 'bottom': m[int(h * (1 - e)):] = True
            elif fr == 'left': m[:, :int(w * e)] = True
            else: m[:, int(w * (1 - e)):] = True
        elif mv.get('box'):
            l, t, r, b = mv['box']; m[int(h * t):int(h * b), int(w * l):int(w * r)] = True
    return m


def has_key_light(params_path):
    """v1.3.0: does the brief set a key light (grade.py key_light)?"""
    return key_light_of(params_path) is not None


def key_light_of(params_path):
    if not params_path or not Path(params_path).exists(): return None
    try: P = json.loads(Path(params_path).read_text(encoding='utf-8') or '{}')
    except Exception: return None
    kl = P.get('key_light') or {}
    return kl if kl.get('box') else None


def directional(Lo, ao, bo, params_path):
    """v1.4.0: is the original's light directional, the way grade.py's key light judges it (brief 'diffuse' wins)?"""
    from ps_common import light_character
    kl = key_light_of(params_path) or {}
    if kl.get('light') == 'diffuse': return False
    ch = light_character(Lo, np.hypot(ao, bo), kl.get('from'), bo)
    if ch['light'] == 'directional': return True
    return kl.get('light') == 'directional' and (ch.get('sun_patches', 0) >= 0.005 or ch.get('gradient_L', 0) >= 3.0)


def colour_mask(params_path, shape):
    """v1.2.7: where the brief raises colour on purpose (moves with look colour+ or sat > 1.05): the subject's own colour."""
    if not params_path or not Path(params_path).exists(): return None
    try: P = json.loads(Path(params_path).read_text(encoding='utf-8') or '{}')
    except Exception: return None
    h, w = shape; m = np.zeros(shape, bool)
    for mv in P.get('moves') or []:
        if mv.get('look') != 'colour+' and float(mv.get('sat', 1) or 1) <= 1.05: continue
        boxes = [mv['box']] if mv.get('box') else []
        boxes += list(mv.get('also') or [])
        if mv.get('shape') == 'gradient':
            e = float(mv.get('end', 0.5)); fr = mv.get('from', 'top')
            if fr == 'top': m[:int(h * e)] = True
            elif fr == 'bottom': m[int(h * (1 - e)):] = True
            elif fr == 'left': m[:, :int(w * e)] = True
            else: m[:, int(w * (1 - e)):] = True
        for bx in boxes:
            l, t, r, b = bx; m[int(h * t):int(h * b), int(w * l):int(w * r)] = True
    return m if m.any() else None


def sep(L):
    s = blur(L, 12)
    return float(np.percentile(s, 85) - np.percentile(s, 15))


def lc(L):
    return float(np.abs(L - blur(L, 8)).mean())


def subject_weight(kl, shape):
    """v1.4.0: the key light's subject area (the same ellipse grade.py and the gates use), soft, 0..1."""
    h, w = shape
    x0, y0, x1, y1 = [float(v) for v in kl['box']]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32); yy /= max(h - 1, 1); xx /= max(w - 1, 1)
    d = np.sqrt(((xx - (x0 + x1) / 2) / max((x1 - x0) / 2, 0.05)) ** 2 + ((yy - (y0 + y1) / 2) / max((y1 - y0) / 2, 0.05)) ** 2)
    return (1 - smooth(d, 0.7, 1.8)).astype(np.float32)


def step_depth(Lo, L, genre, protect=None, key_light=False, floor=SEP_FLOOR, kl=None, sky=None):
    info = {'light_shade_floor': floor}
    Sw = subject_weight(kl, L.shape) if kl else None
    # v1.2.8: the plain, bright sky of the original (2026-11-21, photo 03: after G's smooth sky deepening the
    #   light/shade floor lifted the whole sky back +9 L* and clipped its blue channel)
    sky_w = None
    if sky is not None and sky.any():
        sky_w = np.clip(blur(sky.astype(np.float32), 6) * 1.5, 0, 1)
        sky_w[sky] = 1
    q5o, q5 = float(np.percentile(Lo, 5)), float(np.percentile(L, 5))
    lowkey = float(np.median(Lo)) < 35 or genre in ('museum', 'night')
    lim = q5o + (3.0 if lowkey else 6.0)
    if q5 > lim:
        knee = max(float(np.percentile(L, 35)), q5 + 8)
        excess = q5 - lim
        L = L - excess * np.clip(1 - L / knee, 0, 1) ** 1.2 / max((1 - q5 / knee) ** 1.2, 0.2)
        L = np.clip(L, 0, 100)
        info['black_point'] = f'{q5:.1f} -> {float(np.percentile(L, 5)):.1f} (limit {lim:.1f})'
    ratio = sep(L) / max(sep(Lo), 1e-6)
    if ratio < floor:   # v1.2.5b: lit and shade must stay apart; v1.4.0: at least 1.0x (directional 1.05x)
        r0 = ratio; L_start = L.copy()
        for _ in range(8):
            base = blur(L, 12); m = float(np.median(base)); g = min(floor / ratio, 1.3)
            d = (base - m) * (g - 1)
            if floor > SEP_FLOOR_V125:
                # v1.4.0: the lit side comes up only in the mid-tones (fading out from L* 60 to 85: a sunlit orange
                #   lifted towards white turns pale - b1_03 sun patches +14 L*, colour x0.75) and at most 6 L* in all;
                #   the shade carries more of it (the black guard below bounds it)
                hi_fade = 1 - smooth(L, 60.0, 85.0)
                if Sw is not None:
                    d = np.where(d > 0, d * 1.2 * (0.25 + 0.75 * Sw) * hi_fade, d * 0.8 * (1 - 0.5 * Sw))
                else:
                    d = np.where(d > 0, d * 1.2 * hi_fade, d * 0.8)
                if sky_w is not None: d = d * (1 - sky_w)
                if protect is not None: d = np.where(protect & (d > 0), 0.0, d)
                # a shade pressed at most 3 L* and never below L* 10 (unless it already was): the floor is not worth
                #   dead black, muddy shadows (b1_03 cabinet: -4.5 and its wood colour gone) - then it is reported
                low = np.minimum(L_start, np.maximum(L_start - 3.0, 10.0))
                L = np.clip(np.clip(L + d, low, L_start + 6.0), 0, 100)
                ratio = sep(L) / max(sep(Lo), 1e-6)
                if ratio >= floor - 0.002: break
                continue
            # mostly the sunlit side comes up (what reads as sunlight); the shade only a little, so darks are not crushed
            # v1.3.0: with a key light the brief already set where the shade falls - pushing the shade down again on
            #   top of it made a dark patch (2026-11-21 vase); only the lit side comes up
            if Sw is not None:
                # v1.4.0: with a key light the extra light goes into the subject, and outside it the lit side only a
                #   little (lifting a bright window or sky beyond the subject undid the key light: b1_03); the
                #   surroundings may recede a little, the black guard below keeps them from going dead
                d = np.where(d > 0, d * 1.6 * (0.25 + 0.75 * Sw), d * 0.3 * (1 - Sw)) * (1 - smooth(L, 92.0, 99.0))
            else:
                d = np.where(d > 0, d * 1.6, d * (0.0 if key_light else 0.4)) * (1 - smooth(L, 92.0, 99.0))
            if sky_w is not None: d = d * (1 - sky_w)   # v1.2.8: a plain sky is not the sunlit side; it keeps G's gradient
            if protect is not None: d = np.where(protect & (d > 0), 0.0, d)   # v1.4.0: the brief's own darkening stays
            L = np.clip(L + d, 0, 100)
            ratio = sep(L) / max(sep(Lo), 1e-6)
            if ratio >= floor - 0.002: break
        info['light_shade_sep'] = f'{r0:.3f} -> {ratio:.3f}'
        if ratio < floor - 0.01: info['light_shade_floor_not_reached'] = 'stopped short: more would crush the shadows or wash out the lit colour'
    # highlights: the brightest 1% may not end up much darker than in the original, except where the brief
    #   darkens on purpose (a light- move: a sky graded darker at the top)
    keep_dark = protect if protect is not None else np.zeros_like(L, bool)
    if sky_w is not None: keep_dark = keep_dark | (sky_w > 0.5)   # v1.2.8: a grey sky may sit up to 7 L* lower (intensity_check)
    free = ~keep_dark
    if free.mean() > 0.2:
        t99o, t99 = float(np.percentile(Lo[free], 99)), float(np.percentile(L[free], 99))
        if t99 < t99o - HI_DROP:
            lift = t99o - HI_DROP - t99
            w = smooth(L, float(np.percentile(L[free], 85)), t99) * free
            L = np.clip(L + lift * w, 0, 100)
            info['highlights'] = f'top 1% {t99:.1f} -> {float(np.percentile(L[free], 99)):.1f} (original {t99o:.1f})'
    if sky_w is not None and genre != 'night':
        # v1.2.8: the plain sky may sit up to 7 L* lower (intensity_check's grey-sky floor), not more
        sk = (sky_w > 0.5) & ~(protect if protect is not None else np.zeros_like(L, bool))
        if sk.mean() > 0.02:
            so, sc = float(np.percentile(Lo[sk], 90)), float(np.percentile(L[sk], 90))
            if sc < so - 7.0:
                L = np.clip(L + (so - 7.0 - sc) * sky_w * sk, 0, 100)
                info['sky_floor'] = f'sky {sc:.1f} -> {float(np.percentile(L[sk], 90)):.1f} (original {so:.1f}, may sit 7 lower)'
    r0 = r = lc(L) / max(lc(Lo), 1e-6)
    for _ in range(3):   # up to three small passes: one large unsharp step would halo
        if r >= 1.0: break
        k = min(1.0 / r - 1.0 + 0.02, 0.35)
        L = np.clip(L + k * (L - blur(L, 8)), 0, 100)
        r = lc(L) / max(lc(Lo), 1e-6)
    if r0 < 1.0:
        info['local_contrast'] = f'{r0:.3f} -> {r:.3f}'
    # v1.4.0 black guard: the original's darkest 15 % - no grey lift (> +1.5) and no dead black (< -3.5)
    from ps_common import fixed_dark_delta
    fd = fixed_dark_delta(Lo, L)
    info['fixed_dark_L'] = round(fd, 2)
    if fd > DARK_UP or fd < DARK_DOWN:
        from grade import black_anchor
        h, w = L.shape
        L, an = black_anchor({'target': -2.0 if fd > DARK_UP else -2.5}, L.astype(np.float32), Lo, h, w)
        L = np.clip(L, 0, 100)
        info['black_guard'] = f'fixed_dark_L {fd:+.2f} -> {fixed_dark_delta(Lo, L):+.2f} (band {DARK_DOWN}..+{DARK_UP})'
        r2 = sep(L) / max(sep(Lo), 1e-6)
        if r2 < floor - 0.01: info['black_guard'] += f'; separation {r2:.3f}'
    return L, info


def step_colour(Lo, ao, bo, L, a, b, colour_moves=None):
    info = {}
    Co = np.hypot(ao, bo)
    # neutral drift: only where the original was near-neutral, feathered
    h = Lo.shape[0]
    flat = np.abs(Lo - blur(Lo, 4)) < 2.5
    sky = flat & (Lo > 70); sky[h // 2:] = False                # bright, untextured, upper half: sky, not a wall
    N = ((Co < 6) & (Lo > 35) & (Lo < 92) & ~sky).astype(np.float32)
    if N.mean() > 0.02:
        da, db = float((a - ao)[N > 0].mean()), float((b - bo)[N > 0].mean())
        w = blur(N, 6) * np.clip(1 - np.hypot(a, b) / 25.0, 0, 1)
        wm = max(float(w[N > 0].mean()), 0.3)
        for _ in range(2):   # v1.4.0: two passes, aiming just under 3 (one pass left 3.0-3.6 because w < 1 on the area)
            da_, db_ = float((a - ao)[N > 0].mean()), float((b - bo)[N > 0].mean())
            sa = np.sign(da_) * max(abs(da_) - 2.8, 0); sb = np.sign(db_) * max(abs(db_) - 2.8, 0)
            if not (sa or sb): break
            a = a - sa * w / wm; b = b - sb * w / wm
        da2, db2 = float((a - ao)[N > 0].mean()), float((b - bo)[N > 0].mean())
        if abs(da2 - da) > 0.05 or abs(db2 - db) > 0.05:
            info['neutral_drift'] = f'a {da:+.1f}, b {db:+.1f} -> {da2:+.1f}, {db2:+.1f}'
    # warm light / cool shade (daylight only)
    if Lo.mean() >= 22:
        lit, shade, wl, ws = lit_shade(Lo, bo)
        if lit.mean() > 0.05 and shade.mean() > 0.05:
            do_ = float(bo[lit].mean() - bo[shade].mean())
            if do_ > 2.0:
                df0 = float(b[lit].mean() - b[shade].mean())
                for _ in range(3):
                    df_ = float(b[lit].mean() - b[shade].mean())
                    need = 0.5 * do_ - df_
                    if need <= 0.05: break
                    b = b - 0.7 * need * ws / max(float(ws[shade].mean()), 0.3) + 0.3 * need * wl / max(float(wl[lit].mean()), 0.3)
                if 0.5 * do_ - df0 > 0.05:
                    info['warm_light_cool_shade'] = f'original {do_:.2f}, candidate {df0:.2f} -> {float(b[lit].mean() - b[shade].mean()):.2f} (keeps >= {0.5 * do_:.2f})'
    # a patch that became much more saturated than its own surroundings (a frame-wide boost - the lake's G blue -
    #   is not a patch: it is judged by the 1.65x ceiling below)
    C = np.hypot(a, b); r = 24
    rel_c = blur(C, r) / np.maximum(blur(C, 4 * r), 3.0)
    rel_o = blur(Co, r) / np.maximum(blur(Co, 4 * r), 3.0)
    jump = rel_c / np.maximum(rel_o, 0.3)
    # v1.2.7 (user 2026-11-20): inside the brief's colour+ moves the subject's main colour is the point of the edit,
    #   so a patch there may stand out up to 1.55x before it is calmed (1.35x elsewhere; the 1.65x frame ceiling holds)
    lim = np.full(jump.shape, 1.35, np.float32)
    if colour_moves is not None and colour_moves.shape == jump.shape:
        lim = np.where(blur(colour_moves.astype(np.float32), 6) > 0.5, 1.55, 1.35).astype(np.float32)
        info['colour_moves_limit'] = f'{float((lim > 1.4).mean()):.1%} of the frame (colour+ moves) allowed up to 1.55x'
    # v1.4.0: only a patch that is really saturated is calmed - a lit face that the split toning warmed from near-grey
    #   is 'more saturated than its surroundings' in ratio but not a garish patch (b1_03: 8.6 % of the frame calmed)
    over = (jump > lim) & (blur(C, r) > max(18.0, 1.3 * float(np.median(C))))
    if over.mean() > 0.01:
        f = np.where(over, lim / np.maximum(jump, 1e-6), 1.0).astype(np.float32)
        f = np.minimum(blur(f, r // 2), 1.0)
        a, b = a * f, b * f
        info['saturated_patches'] = f'{float(over.mean()):.1%} of the frame stood out from its surroundings, calmed'
    # whole-frame ceiling (the user's 1.65x, 2026-11-19)
    ratio = float(np.hypot(a, b).mean()) / max(float(Co.mean()), 1e-6)
    if ratio > 1.65:
        # v1.4.0: only the over-saturated top of the chroma comes down (the lit surfaces keep their colour)
        from ps_common import zoned_chroma
        lo_, hi_ = 0.0, 3.0
        cm = max(float(Co.mean()), 1e-6)
        if float(np.hypot(*zoned_chroma(a, b, hi_)[:2]).mean()) / cm > 1.65:
            s = 1.65 / ratio; a, b = a * s, b * s; how = 'global (zoned compression was not enough)'
        else:
            for _ in range(12):
                mid = (lo_ + hi_) / 2
                if float(np.hypot(*zoned_chroma(a, b, mid)[:2]).mean()) / cm > 1.65: lo_ = mid
                else: hi_ = mid
            a, b, zi = zoned_chroma(a, b, hi_); how = f"zoned above C* {zi['knee_C']}"
        info['chroma_ceiling'] = f'{ratio:.2f}x -> {float(np.hypot(a, b).mean()) / cm:.2f}x, {how}'
    return a, b, info


def main():
    args = [x for x in sys.argv[1:] if not x.startswith('--')]
    opt = {x.split('=')[0]: (x.split('=', 1)[1] if '=' in x else True) for x in sys.argv[1:] if x.startswith('--')}
    if len(args) < 3: sys.exit(__doc__)
    o_p, c_p, out_p = args[:3]; rec_p = args[3] if len(args) > 3 else None
    genre = opt.get('--genre'); check_only = bool(opt.get('--check-only')); light_only = bool(opt.get('--light-only'))
    c = load_rgb(c_p); o = load_rgb(o_p)
    framing_note = None
    if o.shape != c.shape:
        if abs(o.shape[1] / o.shape[0] - c.shape[1] / c.shape[0]) > 0.01:
            framing_note = 'ORIGINAL is framed differently from CANDIDATE: run reframe.py with the same arguments on the original first'
        o = np.asarray(Image.fromarray(np.uint8(np.rint(o * 255))).resize((c.shape[1], c.shape[0]), Image.LANCZOS)).astype(np.float32) / 255
    lo, lc_ = srgb_to_lab(o), srgb_to_lab(c)
    Lo, ao, bo = lo[..., 0], lo[..., 1], lo[..., 2]
    L, a, b = lc_[..., 0].copy(), lc_[..., 1].copy(), lc_[..., 2].copy()
    r = max(8, int(round(0.03 * max(L.shape))))
    rec = {'tool': VERSION, 'original': {'path': o_p, 'sha256': sha256(o_p)}, 'candidate': {'path': c_p, 'sha256': sha256(c_p)},
           'genre': genre, 'order': ['light', 'depth', 'colour', 'check']}
    if framing_note: rec['framing'] = framing_note
    pre = run_tool('physics_check.py', o_p, c_p)
    pre_fail = [k for k, v in (pre.get('checks') or {}).items() if isinstance(v, dict) and v.get('ok') is False]
    rec['candidate_physics'] = pre_fail
    want_inv = bool(set(pre_fail) & {'halo', 'spotlight_glow', 'highlight_order'})
    want_dark = bool(set(pre_fail) & {'lamps_kept', 'darkening_patch', 'highlight_order'})
    if want_inv or want_dark:   # only light that physics_check found wrong is touched; G's intended look stays
        L, a, b, rec['light'], regen = step_light(Lo, L, a, b, r, want_inv, want_dark, ao, bo, darken_mask(opt.get('--params'), L.shape))
    else:
        rec['light'], regen = {'action': 'none (physics_check found no wrong light)'}, False
    if light_only:   # finish.py v1.2.5: repair a G attempt's wrong light before deciding whether to keep G
        rec['depth'], rec['colour'] = 'skipped (--light-only)', 'skipped (--light-only)'
    else:
        dirl = genre not in ('night', 'museum') and directional(Lo, ao, bo, opt.get('--params'))
        floor0 = SEP_FLOOR_DIRECTIONAL if dirl else SEP_FLOOR
        L_in, a_in, b_in = L, a, b
        # v1.4.0: the depth floor must not create a physics problem the candidate did not have (c1_04: lifting the
        #   mid-tones made them outshine highlights G had dimmed - highlight_order). Then the floor steps back.
        import tempfile
        sky = sky_surfaces(lo) if genre != 'museum' else None
        for fl in dict.fromkeys((floor0, 1.0, SEP_FLOOR_V125)):
            L, dinfo = step_depth(Lo, L_in, genre, darken_mask(opt.get('--params'), L_in.shape), has_key_light(opt.get('--params')),
                                  fl, key_light_of(opt.get('--params')), sky=sky)
            kd = np.clip((L + 8.0) / (L_in + 8.0), 1.0, 1.15) ** 0.5   # colour follows the lifts (+15 % at most)
            a, b = a_in * kd, b_in * kd
            with tempfile.TemporaryDirectory() as td_:
                tp = str(Path(td_) / 'd.png'); save_png(np.clip(to_srgb(lab_to_lin(np.stack([L, a, b], -1))), 0, 1), tp)
                ph_ = run_tool('physics_check.py', o_p, tp)
            new = [k for k, v in (ph_.get('checks') or {}).items() if isinstance(v, dict) and v.get('ok') is False and k not in pre_fail]
            # an already failing highlight order must not get worse either (c1_04: 0.699 -> 0.624)
            ho0 = ((pre.get('checks') or {}).get('highlight_order') or {}).get('top_lights_still_brightest')
            ho1 = ((ph_.get('checks') or {}).get('highlight_order') or {}).get('top_lights_still_brightest')
            if 'highlight_order' in pre_fail and ho0 is not None and ho1 is not None and ho1 < ho0 - 0.02: new.append('highlight_order (worse)')
            if not new: break
            dinfo['stepped_back'] = f'floor {fl} made {", ".join(new)}'
            rec.setdefault('depth_backoff', []).append(dinfo['stepped_back'])
        else:
            L, a, b = L_in, a_in, b_in
            dinfo = {'action': 'kept input depth after every trial introduced a physics warning'}
        rec['depth'] = dinfo
        a, b, rec['colour'] = step_colour(Lo, ao, bo, L, a, b, colour_mask(opt.get('--params'), L.shape))
    lin2 = lab_to_lin(np.stack([L, a, b], -1))
    # v1.4.0: out-of-gamut colours go towards their own grey (as grade.py does), not clipped channel by channel - a
    #   clipped bright orange turns pale and pink
    grey = np.clip(lin2 @ np.array([0.2126729, 0.7151522, 0.072175], np.float32), 0, 1)[..., None]
    mx, mn = lin2.max(-1, keepdims=True), lin2.min(-1, keepdims=True)
    tt = np.ones_like(mx)
    tt = np.where(mx > 1, np.minimum(tt, (1 - grey) / np.maximum(mx - grey, 1e-6)), tt)
    tt = np.where(mn < 0, np.minimum(tt, grey / np.maximum(grey - mn, 1e-6)), tt)
    out = np.clip(to_srgb(grey + (lin2 - grey) * np.clip(tt, 0, 1)), 0, 1)
    changed = float(np.abs(out - c).mean() * 255)
    rec['mean_change_8bit'] = round(changed, 2)
    if check_only:
        rec['verdict'] = 'CHECK_ONLY'; target = c_p
    else:
        save_png(out, out_p); rec['out'] = {'path': out_p, 'sha256': sha256(out_p)}; target = out_p
        rec['framing_original'] = o_p
    phys = run_tool('physics_check.py', o_p if not framing_note else o_p, target)
    inten = run_tool('intensity_check.py', o_p, target, *(['--genre=' + genre] if genre else []))
    pv, iv = phys.get('verdict', '?'), inten.get('verdict', '?')
    rec['check'] = {'physics': pv, 'intensity': iv,
                    'failed_physics': [k for k, v in (phys.get('checks') or {}).items() if isinstance(v, dict) and v.get('ok') is False]}
    if not check_only:
        if regen: rec['verdict'] = 'REGEN_G: light too wrong to patch; call G once more, then run the chain again'
        elif rec['check']['failed_physics']: rec['verdict'] = 'DELIVER_WITH_FLAGS: ' + ', '.join(rec['check']['failed_physics'])
        else: rec['verdict'] = 'DELIVER'
    if rec_p: Path(rec_p).write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(rec, ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
