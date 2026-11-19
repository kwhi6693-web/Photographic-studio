"""v1.2.5 harmonize.py: the last step on the delivered file. Light (only where physics_check finds it wrong), then
depth floors, then colour (neutral drift, warm light / cool shade, saturated patches, 1.65x ceiling), then one check."""
import json
import numpy as np
from PIL import Image
from conftest import ROOT, run_tool, load, L
from ps_common import srgb_to_lab, lab_to_lin, to_srgb, save_png, blur

REAL_G = ROOT / 'tests' / 'fixtures' / 'real_g'


def orig(name):
    return next((REAL_G / name).glob('original.*'))


def lab(p):
    return srgb_to_lab(load(p))


def from_lab(x, p):
    save_png(np.clip(to_srgb(lab_to_lin(x)), 0, 1), p)


def run(o, c, tmp_path, *extra):
    out, rec = tmp_path / 'h.png', tmp_path / 'h.json'
    r = run_tool('harmonize.py', o, c, out, rec, *extra)
    assert r.returncode == 0, r.stderr
    return out, json.loads(rec.read_text())


def test_a_clean_edit_is_left_alone(tmp_path):
    o = orig('b2_06')
    c = tmp_path / 'c.png'
    run_tool('grade.py', o, c, _params(tmp_path, {'contrast': 0.08, 'vibrance': 0.1, 'clarity': 0.1}))
    out, rec = run(o, c, tmp_path, '--genre=museum')
    assert rec['light']['action'].startswith('none')
    assert rec['mean_change_8bit'] < 1.5 and rec['verdict'].startswith('DELIVER')


def _params(tmp_path, p):
    f = tmp_path / 'p.json'; f.write_text(json.dumps(p)); return f


def test_shade_turned_warmer_than_light_is_put_back(tmp_path):
    o = orig('b1_03')
    x = lab(o); Lo, bo = x[..., 0], x[..., 2]
    so = blur(Lo, 12); shade = so < np.percentile(so, 40)
    y = x.copy(); y[..., 2] = np.where(shade, bo + 14, bo)          # shade made much warmer
    c = tmp_path / 'c.png'; from_lab(y, c)
    out, rec = run(o, c, tmp_path)
    w = rec['colour'].get('warm_light_cool_shade', '')
    assert w, rec['colour']
    assert 'shade_coolness' not in rec['check']['failed_physics']


def test_lifted_black_point_is_pulled_back(tmp_path):
    o = orig('b2_10')
    x = lab(o); y = x.copy(); y[..., 0] = 14 + x[..., 0] * (1 - 14 / 100)   # milky blacks
    c = tmp_path / 'c.png'; from_lab(y, c)
    out, rec = run(o, c, tmp_path)
    assert 'black_point' in rec['depth']
    q5o, q5 = np.percentile(L(load(o)), 5), np.percentile(L(load(out)), 5)
    assert q5 <= q5o + 6.5


def test_softened_photo_gets_its_local_contrast_back(tmp_path):
    o = orig('b1_05')
    im = load(o); soft = 0.5 * im + 0.5 * np.stack([blur(im[..., i], 2) for i in range(3)], -1)
    c = tmp_path / 'c.png'; save_png(soft, c)
    out, rec = run(o, c, tmp_path)
    lc = lambda a: float(np.abs(L(a) - blur(L(a), 8)).mean())
    assert lc(load(out)) >= 0.99 * lc(load(o)), rec['depth']


def test_a_white_wall_turning_yellow_is_limited_to_its_drift(tmp_path):
    o = orig('b2_08')
    x = lab(o); C = np.hypot(x[..., 1], x[..., 2])
    y = x.copy(); y[..., 2] = x[..., 2] + 9                          # everything, the neutral areas too, +9 b*
    c = tmp_path / 'c.png'; from_lab(y, c)
    out, rec = run(o, c, tmp_path, '--genre=museum')
    N = (C < 6) & (x[..., 0] > 35) & (x[..., 0] < 97)
    if N.mean() > 0.02:
        assert 'neutral_drift' in rec['colour']
        z = lab(out)
        assert float((z[..., 2] - x[..., 2])[N].mean()) < 9 - 2


def test_chroma_ceiling_is_the_users_1_65(tmp_path):
    o = orig('b1_04')
    x = lab(o); y = x.copy(); y[..., 1:] *= 2.4
    c = tmp_path / 'c.png'; from_lab(y, c)
    out, rec = run(o, c, tmp_path)
    Co = np.hypot(x[..., 1], x[..., 2]).mean(); z = lab(out)
    assert np.hypot(z[..., 1], z[..., 2]).mean() / Co <= 1.70


def test_darkened_lantern_is_relit_without_dropping_the_rest(tmp_path):
    o = orig('b1_01')   # two lit lanterns in a dark eave
    x = lab(o); Lo = x[..., 0]
    lamp = (Lo - blur(Lo, 30) > 20) & (Lo > 55)
    assert lamp.mean() > 0.0005
    y = x.copy(); y[..., 0] = np.where(blur(lamp.astype(np.float32), 3) > 0.2, Lo * 0.45, Lo)
    c = tmp_path / 'c.png'; from_lab(y, c)
    pre = run_tool('physics_check.py', o, c)
    out, rec = run(o, c, tmp_path)
    if 'lamps_kept' in rec['candidate_physics']:
        assert rec['light']['action'].startswith('patched')
        z = lab(out)
        assert float(z[..., 0][lamp].mean()) > float(y[..., 0][lamp].mean()) + 5


def test_check_only_writes_no_image(tmp_path):
    o = orig('b2_06')
    out, rec = tmp_path / 'h.png', tmp_path / 'h.json'
    r = run_tool('harmonize.py', o, o, out, rec, '--check-only')
    assert r.returncode == 0 and not out.exists()
    assert json.loads(rec.read_text())['verdict'] == 'CHECK_ONLY'


def test_framing_mismatch_is_reported(tmp_path):
    o = orig('b2_06'); im = Image.open(o); w, h = im.size
    c = tmp_path / 'crop.png'; im.crop((0, 0, int(w * 0.7), h)).save(c)
    out, rec = run(o, c, tmp_path)
    assert 'framing' in rec


def test_flattened_light_and_shade_come_back_to_0_9(tmp_path):
    """v1.2.5b: 01 and 02 of the 2026-11-19 garden batch kept only 0.75 of the original's light/shade separation."""
    o = orig('b1_03')
    x = lab(o); base = blur(x[..., 0], 12); m = float(np.median(base))
    y = x.copy(); y[..., 0] = x[..., 0] - (base - m) * 0.3          # sunlit and shade pulled together
    c = tmp_path / 'c.png'; from_lab(y, c)
    out, rec = run(o, c, tmp_path)
    s = lambda L_: float(np.percentile(blur(L_, 12), 85) - np.percentile(blur(L_, 12), 15))
    assert s(L(load(out))) / s(L(load(o))) >= 0.88, rec['depth']


def test_dimmed_highlights_come_back_unless_the_brief_darkens_them(tmp_path):
    o = orig('b2_10')                                                # bright sky at the top
    x = lab(o); y = x.copy(); top = x[..., 0] > np.percentile(x[..., 0], 90)
    y[..., 0] = np.where(top, x[..., 0] - 10, x[..., 0])
    c = tmp_path / 'c.png'; from_lab(y, c)
    out, rec = run(o, c, tmp_path)
    p99 = lambda f: float(np.percentile(L(load(f)), 99))
    assert p99(out) >= p99(o) - 3.5, (rec['light'], rec['depth'])      # by the light step or the highlight floor
    pj = tmp_path / 'p.json'
    pj.write_text(json.dumps({'moves': [{'what': 'sky darker at the top', 'look': 'light-', 'shape': 'gradient', 'from': 'top', 'end': 1.0, 'lift': -6}]}))
    out2, rec2 = run(o, c, tmp_path, f'--params={pj}')
    assert p99(out2) < p99(o) - 4, (rec2['light'], rec2['depth'])        # the brief's own darkening stays
