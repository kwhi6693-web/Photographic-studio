"""The same questions as test_checkers.py and test_pipeline.py, asked on the owner's real photos (fixtures/real/).
Every defect here was also judged by eye on a before/after sheet; a defect too faint to see is not tested.
A strict xfail is a recorded gap: a defect the eye sees and the tools let through."""
import json
import numpy as np
import pytest
import synth
from conftest import L, ROOT, detail, load, run_tool

REAL = ROOT / 'tests' / 'fixtures' / 'real'
FILES = {p.stem: p for p in sorted(REAL.iterdir()) if p.suffix in ('.png', '.jpg')}
PHOTOS = sorted(FILES)
SPOT = {'museum_glass_orchid_panels': (0.5, 0.12), 'museum_glass_sunflowers': (0.62, 0.22), '02_night_tower': (0.25, 0.15)}


def genre(name):
    return 'museum' if name.startswith('museum') else None


def physics(tmp_path, name, edited):
    out = synth.save(edited, tmp_path / 'e.png')
    return json.loads(run_tool('physics_check.py', FILES[name], out).stdout)['verdict']


def test_fixtures_present():
    assert len(PHOTOS) == 10


@pytest.mark.parametrize('name', PHOTOS)
def test_honest_edit_is_not_accused(tmp_path, name):
    assert physics(tmp_path, name, synth.good_edit(load(FILES[name]))).startswith('PHYSICALLY_PLAUSIBLE')


CAUGHT = [(n, d) for n in PHOTOS for d in ('tone_inversion', 'flat_hdr', 'rim_glow')] + \
         [('museum_glass_sunflowers', 'invented_spotlight'), ('02_night_tower', 'invented_spotlight'),
          ('museum_glass_sunflowers', 'edge_halo'), ('museum_glass_orchid_panels', 'edge_halo'), ('02_night_tower', 'edge_halo'), ('05_bronze_ox', 'edge_halo')]
GAPS = [
    ('museum_glass_orchid_panels', 'invented_spotlight', 'glowing oval on the dark wall above the panels: physics_check passes'),
    ('01_building', 'edge_halo', 'white band around the clock tower and the tower block: halo measures 0.8 L*, limit 6'),
    ('interior_arcade', 'edge_halo', 'crunchy rims along the roof grid: halo 5.2, limit 6'),
    ('museum_glass_lotus', 'edge_halo', 'white rims on the glass petals and stems: halo 5.5, limit 8'),
    ('03_canal', 'edge_halo', 'crunchy, posterised edges on the clouds and branches'),
    ('04_willow_lake', 'edge_halo', 'pale bands in the sky beside the willow strands'),
    ('06_blue_vase', 'edge_halo', 'black outline around the vase and lid on the dark background'),
]


def edit(name, defect):
    a = load(FILES[name])
    return synth.invented_spotlight(a, *SPOT[name]) if defect == 'invented_spotlight' else getattr(synth, defect)(a)


@pytest.mark.parametrize('name,defect', CAUGHT, ids=[f'{n}-{d}' for n, d in CAUGHT])
def test_defect_is_reported(tmp_path, name, defect):
    assert not physics(tmp_path, name, edit(name, defect)).startswith('PHYSICALLY_PLAUSIBLE')


@pytest.mark.parametrize('name,defect,why', GAPS, ids=[f'{n}-{d}' for n, d, _ in GAPS])
def test_known_gap(tmp_path, name, defect, why):
    if physics(tmp_path, name, edit(name, defect)).startswith('PHYSICALLY_PLAUSIBLE'):
        pytest.xfail(why)
    pytest.fail('this gap is closed: move the entry from GAPS to CAUGHT')


@pytest.mark.parametrize('name', ['01_building', 'interior_arcade'])
def test_final_keeps_the_original_detail_when_g_wipes_it(tmp_path, name, finish):
    src = FILES[name]
    g = synth.save(synth.smoothed_texture(synth.good_edit(load(src))), tmp_path / 'g.png')
    out, _ = finish(src, g)
    s, o = detail(load(src)), detail(load(out))
    m = np.abs(s) > 0.01
    assert load(out).shape == load(src).shape
    assert np.corrcoef(s[m], o[m])[0, 1] > 0.97 and o.std() > 0.8 * s.std()


def test_same_real_input_same_output(tmp_path, finish):
    src = REAL / '01_building.png'
    g = synth.save(synth.good_edit(load(src)), tmp_path / 'g.png')
    a, _ = finish(src, g, {'vibrance': 0.2}, tag='a')
    b, _ = finish(src, g, {'vibrance': 0.2}, tag='b')
    assert a.read_bytes() == b.read_bytes()


def glow_left(tmp_path, finish, name):
    src = FILES[name]; a = load(src)
    g = synth.save(synth.invented_spotlight(synth.good_edit(a), *SPOT[name]), tmp_path / 'g.png')
    out, rec = finish(src, g, genre=genre(name))
    h, w = a.shape[:2]; y, x = np.mgrid[0:h, 0:w]; s = w / 640.0
    core = ((x - SPOT[name][0] * w) / (80 * s)) ** 2 + ((y - SPOT[name][1] * h) / (60 * s)) ** 2 < 0.5
    return float((L(load(g)) - L(a))[core].mean()), float((L(load(out)) - L(a))[core].mean()), rec


def test_invented_glow_is_removed_orchid(tmp_path, finish):
    in_g, left, _ = glow_left(tmp_path, finish, 'museum_glass_orchid_panels')
    assert in_g > 15 and left < 3


def test_invented_glow_is_removed_sunflowers(tmp_path, finish):
    """v1.0.2: look_transfer.py measures the glow left on the output (G_GLOW_LEFT); finish.py then takes a safer route.
    Before v1.0.2 about 7 L* of the glow was delivered here."""
    in_g, left, rec = glow_left(tmp_path, finish, 'museum_glass_sunflowers')
    assert in_g > 15 and left < 3
    assert any('G_GLOW_LEFT' in f for a in rec['attempts'] for f in a.get('look_transfer_flags', []))


def test_known_gap_invented_glow_survives_night(tmp_path, finish):
    """Seen by eye: a faint oval in the night sky (about 5 L* in its core, 1 L* around it); the receipt says DELIVER.
    A robust trend fit removed it but also darkened the approved bronze-ox sample (19.2 approved, 17.7 before,
    14.8 after), and a trend-free measure scores approved samples as high as this glow; neither was adopted."""
    in_g, left, rec = glow_left(tmp_path, finish, '02_night_tower')
    assert in_g > 15
    if left >= 3:
        pytest.xfail(f'{left:.1f} L* of the invented glow is delivered; receipt verdict {rec["verdict"][:40]}')
    pytest.fail('this gap is closed: turn this test into a plain assertion')


TASTE = {'01_building': '01_building', '02_night': '02_night_tower', '03_canal': '03_canal', '04_willow_lake': '04_willow_lake',
         '05_bronze_ox': '05_bronze_ox', '06_blue_vase_museum': '06_blue_vase'}


@pytest.mark.parametrize('sample', sorted(TASTE))
def test_approved_look_is_not_called_a_glow(tmp_path, sample):
    """The user's approved finals (right half of each taste sample) used as G: the leftover-glow check must stay quiet,
    or finish.py would throw away a look the user approved."""
    from PIL import Image
    sheet = Image.open(next((ROOT / 'photographic-studio' / 'assets' / 'taste').glob(f'{sample}_*.jpg')))
    w, h = sheet.size; right = sheet.crop((w - w // 2 + 6, 0, w, h))
    src = FILES[TASTE[sample]]; sh = Image.open(src).size[1]
    g = tmp_path / 'g.png'; right.resize((round(right.size[0] * sh / right.size[1]), sh), Image.LANCZOS).save(g)
    p = run_tool('look_transfer.py', src, g, tmp_path / 'o.png', tmp_path / 'o.json')
    r = json.loads((tmp_path / 'o.json').read_text())
    assert p.returncode == 0 and not any(f.startswith('G_GLOW_LEFT') for f in r['flags']), r['measurements'].get('glow_left_L')
