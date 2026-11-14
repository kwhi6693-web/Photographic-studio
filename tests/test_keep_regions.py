"""keep_regions.py (v1.1.0): what the brief says must not change does not change, without a visible seam."""
import json
import numpy as np
from conftest import ROOT, run_tool, load
from ps_common import srgb_to_lab, blur

REAL = ROOT / 'tests' / 'fixtures' / 'real'
RG = ROOT / 'tests' / 'fixtures' / 'real_g'


def lab(p):
    return srgb_to_lab(load(p))


def region(a, box):
    h, w = a.shape[:2]
    x0, y0, x1, y1 = box
    return a[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]


def test_colour_mode_stops_a_whole_frame_cast_inside_the_region(tmp_path):
    """A warm cast over the whole frame (the 'global colour chase' that spills): inside the region the original's
    colour comes back, the edit's brightness stays, and outside nothing changes."""
    src = REAL / '01_building.png'
    pj = tmp_path / 'cast.json'; pj.write_text(json.dumps({'tone_split': {'shadows': [4, 8], 'highlights': [4, 8]}, 'exposure_ev': 0.2}))
    edited = tmp_path / 'edited.png'; run_tool('grade.py', src, edited, pj)
    box = [0.3, 0.3, 0.7, 0.7]
    rj = tmp_path / 'r.json'; rj.write_text(json.dumps({'keep': [{'what': 'test', 'box': box, 'mode': 'colour'}]}))
    out = tmp_path / 'out.png'
    rec = json.loads(run_tool('keep_regions.py', src, edited, out, rj).stdout)
    o, e, k = lab(src), lab(edited), lab(out)
    inner = [0.35, 0.35, 0.65, 0.65]
    d_ab_before = np.abs(region(e, inner)[..., 1:] - region(o, inner)[..., 1:]).mean()
    d_ab_after = np.abs(region(k, inner)[..., 1:] - region(o, inner)[..., 1:]).mean()
    assert d_ab_before > 2 and d_ab_after < 0.25 * d_ab_before   # the cast is gone inside
    assert abs(region(k, inner)[..., 0].mean() - region(e, inner)[..., 0].mean()) < 1.0   # brightness follows the edit
    corner = [0.0, 0.0, 0.15, 0.15]
    assert np.abs(region(k, corner) - region(e, corner)).max() < 0.5   # outside untouched
    # this box cuts straight through smooth sky, so keeping the old colour there leaves a step the eye can see: the
    # seam check must say so (a real brief draws the box around an object, whose own edge hides the step)
    assert rec['flags'] and rec['flags'][0].startswith('KEEP_SEAM'), rec


def test_content_mode_removes_what_g_repainted_and_keeps_the_scene_tone(tmp_path):
    """b2_01: G repainted the left screen panel (peonies that are not in the photo). In content mode the panel keeps the
    original's own detail; only G's large-scale warmth comes in, and there is no visible seam."""
    d = RG / 'b2_01'; src = next(d.glob('original.*'))
    lt = tmp_path / 'lt.png'; run_tool('look_transfer.py', src, d / 'g.png', lt)
    box = [0.03, 0.23, 0.21, 0.6]
    rj = tmp_path / 'r.json'; rj.write_text(json.dumps([{'what': 'left screen panel', 'box': box, 'mode': 'content'}]))
    out = tmp_path / 'out.png'
    rec = json.loads(run_tool('keep_regions.py', src, lt, out, rj).stdout)
    o, t, k = lab(src), lab(lt), lab(out)
    inner = [0.06, 0.28, 0.18, 0.55]
    hp = lambda a: a[..., 0] - blur(a[..., 0], 6)   # the panel's own detail (and anything painted at that scale)
    err_before = np.abs(hp(region(t, inner)) - hp(region(o, inner))).mean()
    err_after = np.abs(hp(region(k, inner)) - hp(region(o, inner))).mean()
    assert err_after < 0.5 * err_before
    warm = region(k, inner)[..., 2].mean() - region(o, inner)[..., 2].mean()
    assert warm > 2   # the scene's warmth still reaches the panel
    assert rec['regions'][0]['seam_dE'] <= 3.0 and not rec['flags'], rec


def test_no_regions_changes_nothing(tmp_path):
    src = REAL / '03_canal.jpg'
    rj = tmp_path / 'r.json'; rj.write_text('{"keep": []}')
    out = tmp_path / 'o.png'; run_tool('keep_regions.py', src, src, out, rj)
    assert np.abs(load(out) - load(src)).max() <= 1 / 255


def test_finish_applies_keep_before_the_checks(tmp_path):
    d = RG / 'b2_01'; src = next(d.glob('original.*'))
    p = json.loads((d / 'params.json').read_text()); p['keep'] = [{'what': 'left panel', 'box': [0.03, 0.23, 0.21, 0.6], 'mode': 'content'}]
    pj = tmp_path / 'p.json'; pj.write_text(json.dumps(p))
    rec = tmp_path / 'f.json'
    run_tool('finish.py', src, d / 'g.png', pj, tmp_path / 'f.png', rec, '--genre=museum')
    r = json.loads(rec.read_text())
    assert all(str(a.get('keep', '')).startswith('KEPT') for a in r['attempts'] if 'physics' in a)
