#!/usr/bin/env python3
"""Photographic Studio v1.2.5 - harmonize: the last step, run on the file that is actually delivered.

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

--check-only writes nothing but the receipt: steps 1-3 report what they would change.
--light-only runs step 1 only (finish.py uses it to repair a G attempt instead of dropping G).
Deterministic. Needs numpy, Pillow, OpenCV (via ps_common).
"""
import json, sys
from pathlib import Path
import numpy as np
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ps_common import load_rgb, save_png, srgb_to_lab, lab_to_lin, to_srgb, blur, guided, sha256, run_tool

VERSION = 'harmonize.py v1.2.5'
FUSE_AREA = 0.20
SEP_FLOOR = 0.90   # light/shade separation vs the original (03 and 05 of the 2026-11-19 batch kept 0.95)
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
    bump = D - blur(D, 3 * r)                                  # what stands out from its surroundings
    src = (base_o - blur(base_o, 3 * r))                       # where the original itself had a local light
    invented = smooth(bump, 3.0, 8.0) * smooth(D, 2.0, 6.0) * (1 - smooth(src, 3.0, 8.0))   # brighter than the original AND than around it
    corr_inv = -np.maximum(bump - 1.5, 0) * invented
    h, w = Lo.shape                                            # the original's own small lights, as physics_check finds them
    src_px = Lo - blur(Lo, max(6, min(h, w) // 60))            #   (lamps_kept: L* > 80 and > 25 above their surroundings)
    light_src = smooth(src_px, 18.0, 25.0) * smooth(Lo, 72.0, 80.0)
    light_src = np.maximum(light_src, blur(light_src, 2))
    darkened = smooth(Lo - L, 4.0, 10.0) * light_src
    corr_inv = corr_inv if want_inv else 0 * corr_inv
    corr_inv = guided(L, corr_inv.astype(np.float32), max(4, r // 2), eps)   # edge-aware, no grey patches
    # a real light the candidate put out comes back at the original's own brightness (it is the original's light),
    # feathered so the edge of the mask does not show
    # the whole bright opening around a put-out light comes back, not just its rim (a half-restored sky gap shows a ring)
    zone = blur((darkened > 0.3).astype(np.float32), r) > 0.02
    opening = smooth(Lo, 68.0, 82.0) * smooth(Lo - L, 2.0, 6.0) * zone
    darkened = np.maximum(darkened, opening)
    if protect is not None: darkened = darkened * ~protect      # the brief darkens there on purpose
    m = np.maximum(darkened, blur(darkened, max(2, r // 8)))
    corr_dark = (np.maximum(Lo - L, 0) * m) if want_dark else 0 * Lo
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


def sep(L):
    s = blur(L, 12)
    return float(np.percentile(s, 85) - np.percentile(s, 15))


def lc(L):
    return float(np.abs(L - blur(L, 8)).mean())


def step_depth(Lo, L, genre, protect=None):
    info = {}
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
    if ratio < SEP_FLOOR:   # v1.2.5b: lit and shade must stay apart (0.75 let two of five garden photos go flat)
        r0 = ratio
        for _ in range(3):
            base = blur(L, 12); m = float(np.median(base)); g = min(SEP_FLOOR / ratio, 1.3)
            d = (base - m) * (g - 1)
            # mostly the sunlit side comes up (what reads as sunlight); the shade only a little, so darks are not crushed
            d = np.where(d > 0, d * 1.6, d * 0.4) * (1 - smooth(L, 92.0, 99.0))
            L = np.clip(L + d, 0, 100)
            ratio = sep(L) / max(sep(Lo), 1e-6)
            if ratio >= SEP_FLOOR - 0.005: break
        info['light_shade_sep'] = f'{r0:.3f} -> {ratio:.3f}'
    # highlights: the brightest 1% may not end up much darker than in the original, except where the brief
    #   darkens on purpose (a light- move: a sky graded darker at the top)
    keep_dark = protect if protect is not None else np.zeros_like(L, bool)
    free = ~keep_dark
    if free.mean() > 0.2:
        t99o, t99 = float(np.percentile(Lo[free], 99)), float(np.percentile(L[free], 99))
        if t99 < t99o - HI_DROP:
            lift = t99o - HI_DROP - t99
            w = smooth(L, float(np.percentile(L[free], 85)), t99) * free
            L = np.clip(L + lift * w, 0, 100)
            info['highlights'] = f'top 1% {t99:.1f} -> {float(np.percentile(L[free], 99)):.1f} (original {t99o:.1f})'
    r0 = r = lc(L) / max(lc(Lo), 1e-6)
    for _ in range(3):   # up to three small passes: one large unsharp step would halo
        if r >= 1.0: break
        k = min(1.0 / r - 1.0 + 0.02, 0.35)
        L = np.clip(L + k * (L - blur(L, 8)), 0, 100)
        r = lc(L) / max(lc(Lo), 1e-6)
    if r0 < 1.0:
        info['local_contrast'] = f'{r0:.3f} -> {r:.3f}'
    return L, info


def step_colour(Lo, ao, bo, L, a, b):
    info = {}
    Co = np.hypot(ao, bo)
    # neutral drift: only where the original was near-neutral, feathered
    h = Lo.shape[0]
    flat = np.abs(Lo - blur(Lo, 4)) < 2.5
    sky = flat & (Lo > 70); sky[h // 2:] = False                # bright, untextured, upper half: sky, not a wall
    N = ((Co < 6) & (Lo > 35) & (Lo < 92) & ~sky).astype(np.float32)
    if N.mean() > 0.02:
        da, db = float((a - ao)[N > 0].mean()), float((b - bo)[N > 0].mean())
        sa = np.sign(da) * max(abs(da) - 3.0, 0); sb = np.sign(db) * max(abs(db) - 3.0, 0)
        if sa or sb:
            w = blur(N, 6) * np.clip(1 - np.hypot(a, b) / 25.0, 0, 1)
            a = a - sa * w; b = b - sb * w
            info['neutral_drift'] = f'a {da:+.1f}, b {db:+.1f} -> pulled back {(-sa):+.1f}, {(-sb):+.1f}'
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
    over = jump > 1.35
    if over.mean() > 0.01:
        f = np.where(over, 1.35 / np.maximum(jump, 1e-6), 1.0).astype(np.float32)
        f = np.minimum(blur(f, r // 2), 1.0)
        a, b = a * f, b * f
        info['saturated_patches'] = f'{float(over.mean()):.1%} of the frame stood out from its surroundings, calmed'
    # whole-frame ceiling (the user's 1.65x, 2026-11-19)
    ratio = float(np.hypot(a, b).mean()) / max(float(Co.mean()), 1e-6)
    if ratio > 1.65:
        s = 1.65 / ratio; a, b = a * s, b * s
        info['chroma_ceiling'] = f'{ratio:.2f}x -> 1.65x'
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
        L, rec['depth'] = step_depth(Lo, L, genre, darken_mask(opt.get('--params'), L.shape))
        a, b, rec['colour'] = step_colour(Lo, ao, bo, L, a, b)
    out = np.clip(to_srgb(lab_to_lin(np.stack([L, a, b], -1))), 0, 1)
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
