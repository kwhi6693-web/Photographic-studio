"""v1.4.0 expressiveness: the shadow-lift clamp and colour pre-scale in look_transfer.py, the luminance-masked key
light, black anchor, split toning and structure texture in grade.py, zoned colour in settle.py, the highlight shoulder
in n_trim.py, harmonize.py's 1.0/1.05 separation floor and black guard, and the four hard gates in improve_check.py
that finish.py now always runs (2026-11-22 courtyard/arcade receipts)."""
import json
from pathlib import Path
import numpy as np
from PIL import Image
from conftest import ROOT, run_tool, load, L
from ps_common import srgb_to_lab, lab_to_lin, to_srgb, save_png, blur, dark_anchor_mask, fixed_dark_delta, global_sep

RG = ROOT / 'tests' / 'fixtures' / 'real_g'


def save(a, p):
    Image.fromarray(np.uint8(np.clip(np.rint(a * 255), 0, 255))).save(p)
    return p


def from_lab(x, p):
    save_png(np.clip(to_srgb(lab_to_lin(x.astype(np.float32))), 0, 1), p)
    return p


def lab(p):
    return srgb_to_lab(load(p))


def textured(h, w, seed, base, amp):
    rng = np.random.default_rng(seed)
    Y, X = np.mgrid[0:h, 0:w] / np.array([h, w])[:, None, None]
    t = base + amp * np.sin(X * 90) * np.sin(Y * 70) + 0.04 * rng.standard_normal((h, w))
    return t, Y, X


def courtyard(h=600, w=800):
    """Lit stone in the middle, dark foreground and corners, a white wall on the left, colourful plants on the right."""
    t, Y, X = textured(h, w, 11, 0.0, 0.05)
    light = 0.20 + 0.50 * np.exp(-(((X - 0.55) / 0.22) ** 2 + ((Y - 0.45) / 0.25) ** 2))
    img = np.repeat((light + t)[..., None], 3, -1) * np.array([1.0, 0.93, 0.80])
    wall = (X < 0.18) & (Y > 0.15) & (Y < 0.7)
    img[wall] = (0.78 + t[wall, None] * 0.3) * np.array([0.97, 0.97, 0.96])
    plant = (X > 0.78) & (Y > 0.3) & (Y < 0.8)
    img[plant] = (0.35 + t[plant, None]) * np.array([0.45, 0.85, 0.35])
    return np.clip(img, 0, 1), Y, X, wall, plant


def hdr_g(img, Y, X):
    """A G that lifts the darks evenly (+~12 L*) and over-colours everything: the habit seen on the courtyard."""
    lb = srgb_to_lab(img)
    Lw = lb[..., 0]
    lift = 13.0 * np.clip((45 - Lw) / 30, 0, 1)
    lb[..., 0] = Lw + lift
    lb[..., 1] *= 1.9; lb[..., 2] = lb[..., 2] * 1.9 + 5.0      # warm cast on everything, white wall included
    return np.clip(to_srgb(lab_to_lin(lb)), 0, 1)


def test_shadow_lift_clamp_and_colour_prescale(tmp_path):
    img, Y, X, wall, plant = courtyard()
    s, g = save(img, tmp_path / 's.png'), save(hdr_g(img, Y, X), tmp_path / 'g.png')
    out, rec = tmp_path / 'o.png', tmp_path / 'r.json'
    run_tool('look_transfer.py', s, g, out, rec)
    r = json.loads(rec.read_text()); m = r['measurements']
    Lo, lo_ = L(load(s)), lab(s)
    lf = lab(out)
    dk = dark_anchor_mask(Lo, 0.2)
    assert float((lf[..., 0] - Lo)[dk].mean()) <= 2.2, m['shadow_lift_clamp']                 # was ~+12 from G
    raw = tmp_path / 'raw.png'
    run_tool('look_transfer.py', s, g, raw, tmp_path / 'r2.json', '--no-shadow-clamp')
    assert float((lab(raw)[..., 0] - Lo)[dk].mean()) > 6.0                                     # the clamp is what held it
    nt = tmp_path / 'night.png'
    run_tool('look_transfer.py', s, g, nt, tmp_path / 'r3.json', '--night')                    # a declared night photo:
    assert float((lab(nt)[..., 0] - Lo)[dk].mean()) > 6.0                                      #   lifting the darks is the edit
    C = lambda z: np.hypot(z[..., 1], z[..., 2])
    assert m['colour_prescale']['chroma_ratio_after'] <= 1.655 and float(C(lf).mean() / C(lo_).mean()) <= 1.67
    # near-neutral white wall: G's warm cast is halved there (and then scaled with the rest)
    gb = float((lab(g)[..., 2] - lo_[..., 2])[wall].mean()); ob = float((lf[..., 2] - lo_[..., 2])[wall].mean())
    assert ob <= 0.5 * gb + 0.3, (gb, ob)


def test_g_fine_detail_never_reaches_the_output(tmp_path):
    img, Y, X, _, _ = courtyard()
    rng = np.random.default_rng(5)
    gimg = np.clip(img * 1.05 + 0.06 * rng.standard_normal(img.shape[:2])[..., None], 0, 1)   # G invents a crisp grain
    s, g = save(img, tmp_path / 's.png'), save(gimg, tmp_path / 'g.png')
    out, rec = tmp_path / 'o.png', tmp_path / 'r.json'
    run_tool('look_transfer.py', s, g, out, rec)
    m = json.loads(rec.read_text())['measurements']
    assert abs(m['g_high_freq_leak']) < 0.1, m['g_high_freq_leak']
    o, f = L(load(s)), L(load(out))
    hp = lambda x: x - blur(x, 1.5)
    assert np.corrcoef(hp(o).ravel(), hp(f).ravel())[0, 1] > 0.97          # the fine detail is the photo's own


def test_sun_patches_make_a_low_spread_frame_directional_and_shadow_gaps_stay_dark(tmp_path):
    h, w = 600, 800
    t, Y, X = textured(h, w, 4, 0.30, 0.03)
    img = np.repeat(t[..., None], 3, -1) * np.array([1.0, 0.95, 0.85])
    for cx, cy in ((0.2, 0.7), (0.32, 0.8), (0.45, 0.72), (0.3, 0.58), (0.6, 0.85), (0.15, 0.85)):   # sun patches on the floor
        p = (np.abs(X - cx) < 0.04) & (np.abs(Y - cy) < 0.025)
        img[p] = np.array([0.92, 0.85, 0.70])
    gap = (np.abs(X - 0.5) < 0.01) & (Y > 0.35) & (Y < 0.65)                           # a dark seam inside the subject
    img[gap] = 0.06
    img = np.clip(img, 0, 1)
    sp = save(img, tmp_path / 'i.png'); out = tmp_path / 'o.png'; pj = tmp_path / 'p.json'
    pj.write_text(json.dumps({'key_light': {'box': [0.3, 0.3, 0.7, 0.7], 'from': 'left'}}))
    r = json.loads(run_tool('grade.py', sp, out, pj).stdout)['params_used']['key_light']
    assert r['light_in_original']['land_spread'] < 18 and r['light_in_original']['sun_patches'] >= 0.015
    assert r['mode'] == 'directional', r
    assert 4.5 <= r['lift_L'] <= 6.0 + 1e-6 and r['falloff_L'] <= 7.5 + 1e-6
    D = L(load(out)) - L(load(sp))
    assert abs(float(D[gap].mean())) < 1.0                                               # the seam is not lifted


def test_brief_can_lock_directional_only_where_there_is_sun(tmp_path):
    h, w = 600, 800
    t, Y, X = textured(h, w, 6, 0.40, 0.02)
    flat = np.clip(np.repeat(t[..., None], 3, -1), 0, 1)
    sp = save(flat, tmp_path / 'f.png'); pj = tmp_path / 'p.json'
    pj.write_text(json.dumps({'key_light': {'box': [0.3, 0.3, 0.7, 0.7], 'from': 'left', 'light': 'directional'}}))
    r = json.loads(run_tool('grade.py', sp, tmp_path / 'o.png', pj).stdout)['params_used']['key_light']
    assert r['mode'] == 'diffuse' and 'lock_refused' in r['light_in_original']


def test_grade_anchor_leaves_raised_shadows_and_recovers_over_dark_shadows(tmp_path):
    img, Y, X, _, _ = courtyard()
    lb = srgb_to_lab(img); lb[..., 0] += 4.0 * np.clip((45 - lb[..., 0]) / 30, 0, 1)   # what is left after the shadow clamp
    s, c = save(img, tmp_path / 's.png'), from_lab(lb, tmp_path / 'c.png')
    pj = tmp_path / 'p.json'; out = tmp_path / 'o.png'
    pj.write_text(json.dumps({'anchor': True, 'auto_ref': str(s)}))
    r = json.loads(run_tool('grade.py', c, out, pj).stdout)['params_used']['anchor']
    fd = fixed_dark_delta(L(load(s)), L(load(out)))
    assert abs(fd - fixed_dark_delta(L(load(s)), L(load(c)))) < 0.1, (fd, r)
    # already far too dark: brought back up to -3.0, never left under -3.5
    dark = srgb_to_lab(img); dark[..., 0] = np.where(dark[..., 0] < 40, dark[..., 0] * 0.6, dark[..., 0])
    d = from_lab(dark, tmp_path / 'd.png'); out2 = tmp_path / 'o2.png'
    run_tool('grade.py', d, out2, pj)
    assert fixed_dark_delta(L(load(s)), L(load(out2))) >= -3.6


def test_split_tone_leaves_white_walls_and_does_not_stack(tmp_path):
    img, Y, X, wall, plant = courtyard()
    s = save(img, tmp_path / 's.png'); pj = tmp_path / 'p.json'; out = tmp_path / 'o.png'
    pj.write_text(json.dumps({'split_tone': True}))
    r = json.loads(run_tool('grade.py', s, out, pj).stdout)['params_used']['split_tone']
    db = lab(out)[..., 2] - lab(s)[..., 2]
    assert abs(float(db[wall].mean())) < 0.4                       # near-neutral wall: not dyed
    assert r['warm_added_b'] == 1.75 and r['cool_added_b'] == -1.25
    # a G that already warmed the lit faces by 3: nothing more is added there
    lb = lab(s); lb[..., 2] = lb[..., 2] + 3.0 * np.clip((lb[..., 0] - 50) / 20, 0, 1)
    c = from_lab(lb, tmp_path / 'c.png'); pj.write_text(json.dumps({'split_tone': True, 'auto_ref': str(s)}))
    r2 = json.loads(run_tool('grade.py', c, tmp_path / 'o2.png', pj).stdout)['params_used']['split_tone']
    assert r2['warm_added_b'] < 0.5


def test_texture_only_on_structure_and_limited(tmp_path):
    h, w = 600, 800
    t, Y, X = textured(h, w, 8, 0.45, 0.10)
    img = np.repeat(t[..., None], 3, -1)
    sky = Y < 0.35
    img[sky] = 0.88 - 0.05 * Y[sky, None]
    sp = save(np.clip(img, 0, 1), tmp_path / 'i.png'); pj = tmp_path / 'p.json'; out = tmp_path / 'o.png'
    pj.write_text(json.dumps({'texture': 0.26}))
    r = json.loads(run_tool('grade.py', sp, out, pj).stdout)['params_used']['texture']
    D = L(load(out)) - L(load(sp))
    assert np.abs(D[sky & (Y < 0.3)]).max() < 0.6                 # the plain sky: nothing
    assert np.abs(D).max() <= 3.5 + 0.7                            # +-3.5 per pixel (plus 8-bit rounding)
    from ps_common import midfreq, structure_mask
    Lo, Lf = L(load(sp)), L(load(out)); m = structure_mask(Lo) > 0.5
    ratio = float(np.abs(midfreq(Lf))[m].mean() / np.abs(midfreq(Lo))[m].mean())
    assert 1.1 <= ratio <= 1.4, (ratio, r)


def test_settle_trims_colour_only_where_it_overflows(tmp_path):
    img, Y, X, wall, plant = courtyard()
    lb = srgb_to_lab(img)
    fl = (X > 0.72) & (Y > 0.25) & (Y < 0.85)                     # a bed of red flowers on the right
    lb[..., 1] = np.where(fl, 18.0, lb[..., 1] + 4); lb[..., 2] = np.where(fl, 9.0, lb[..., 2] + 6)
    lb[..., 0] = np.where(fl, 48 + lb[..., 0] * 0.1, lb[..., 0])
    s = from_lab(lb, tmp_path / 's.png')
    l2 = lab(s); lit = (l2[..., 0] > 55) & ~fl & ~wall
    f = np.where(fl, 3.0, 1.12); l2[..., 1] *= f; l2[..., 2] *= f   # the flowers far over, the lit stone mildly up
    c = from_lab(l2, tmp_path / 'c.png'); out = tmp_path / 'o.png'
    r = json.loads(run_tool('settle.py', s, c, out, tmp_path / 'r.json').stdout)
    assert any('chroma_ratio' in st.get('for', []) for st in r['steps']), r
    C = lambda z: np.hypot(z[..., 1], z[..., 2])
    lc, lo = lab(c), lab(out)
    assert float(C(lo)[lit].mean() / C(lc)[lit].mean()) >= 0.97      # lit stone keeps its colour
    assert float(C(lo)[fl].mean() / C(lc)[fl].mean()) < 0.92         # the overflow came down
    it = json.loads(run_tool('intensity_check.py', s, out).stdout)
    assert it['checks']['chroma_ratio']['ok'] is not False


def test_n_trim_rolls_off_only_the_top_highlights(tmp_path):
    img, Y, X, wall, plant = courtyard()
    hot = img.copy(); spot = (np.abs(X - 0.55) < 0.06) & (np.abs(Y - 0.45) < 0.06)
    hot[spot] = 1.0
    sp = save(np.clip(hot, 0, 1), tmp_path / 'h.png'); out = tmp_path / 't.png'
    r = json.loads(run_tool('n_trim.py', sp, out, tmp_path / 'r.json').stdout)
    assert r['verdict'].startswith('PASS'), r
    m = r['measurements']
    assert m['midtone_max_abs_dL'] <= 0.5 and 0.985 <= m['chroma_ratio'] <= 1.005


def test_harmonize_separation_floor_and_black_guard(tmp_path):
    img, Y, X, _, _ = courtyard()
    s = save(img, tmp_path / 's.png')
    lb = srgb_to_lab(img); Lo = lb[..., 0].copy()
    lb[..., 0] = 50 + (Lo - 50) * 0.85 + 4.0 * (Lo < 35)         # flatter, darks lifted (+~6 in the darkest)
    c = from_lab(lb, tmp_path / 'c.png'); out, rec = tmp_path / 'h.png', tmp_path / 'h.json'
    run_tool('harmonize.py', s, c, out, rec)
    r = json.loads(rec.read_text())
    Lf = L(load(out))
    assert global_sep(Lf) / global_sep(Lo) >= 1.015, r['depth']
    fd = fixed_dark_delta(Lo, Lf)
    assert -3.6 <= fd <= 1.6, (fd, r['depth'])


def test_gates_report_and_finish_always_checks_after_settling(tmp_path):
    """An over-coloured G (the arcade case) used to skip improve_check; now the attempt is settled first and the
    gates run on it."""
    img, Y, X, wall, plant = courtyard()
    s, g = save(img, tmp_path / 's.png'), save(hdr_g(img, Y, X), tmp_path / 'g.png')
    pj = tmp_path / 'p.json'
    pj.write_text(json.dumps({'key_light': {'box': [0.35, 0.2, 0.75, 0.7], 'from': 'top'},
                              'moves': [{'what': 'stone texture', 'shape': 'rect', 'box': [0.35, 0.2, 0.75, 0.7], 'clarity': 0.15, 'look': 'contrast+'}]}))
    out, rec = tmp_path / 'f.png', tmp_path / 'f.json'
    p = run_tool('finish.py', s, g, pj, out, rec)
    assert p.returncode == 0, p.stderr[-600:]
    r = json.loads(rec.read_text())
    a = next(x for x in r['attempts'] if x['name'] == r['delivered'])
    assert 'gates' in a and set(a['gates']) >= {'subject_separation', 'global_separation', 'black_anchor', 'colour_order', 'texture'}
    assert a['gates']['black_anchor']['ok'] is True, a['gates']['black_anchor']
    assert a['gates']['subject_separation']['ok'] is True, a['gates']['subject_separation']
    # the 1.65x colour ceiling is harmonize.py's (the last step), not finish.py's
    h = tmp_path / 'h.png'
    run_tool('harmonize.py', s, out, h, tmp_path / 'h.json', f'--params={pj}')
    g2 = json.loads(run_tool('improve_check.py', s, h, pj, '--gates').stdout)['gates']
    assert g2['colour_order']['chroma_ratio'] <= 1.655


def test_gate_remedy_never_uses_clarity():
    import sys
    sys.path.insert(0, str(ROOT / 'photographic-studio' / 'optional'))
    import finish
    p = {'key_light': {'box': [0.3, 0.3, 0.6, 0.6]}, 'anchor': True, 'clarity': 0.1}
    q, did = finish.remedy(p, {'global_separation': {'ok': False}, 'black_anchor': {'fixed_dark_L_change': 0.3}})
    assert q['key_light']['strength'] == 1.1 and q['clarity'] == 0.1 and q['anchor']['target'] == -2.75
    q2, _ = finish.remedy(q, {})
    q3, _ = finish.remedy(q2, {})
    assert q3['key_light']['strength'] == 1.2 and q3['contrast'] <= 0.12
    q4, did4 = finish.remedy(p, {'black_anchor': {'fixed_dark_L_change': -4.2}})
    assert q4['anchor'] == {'target': -2.0} and 'key_light_strength' not in did4
