"""How sharp are the checkers? Each defect breaks one rule of references/physics.md on a scene whose truth is known.
A defect physics_check.py does not report is kept here as a strict xfail: a recorded, visible gap. When a tool
change closes the gap, the xfail turns into a failure, and the entry must be moved to CAUGHT."""
import json
import pytest
import synth
from conftest import run_tool

CAUGHT = [
    ('day', 'invented_spotlight', {}), ('day', 'edge_halo', {}), ('day', 'rim_glow', {}), ('day', 'tone_inversion', {}),
    ('day', 'flat_hdr', {}), ('day', 'removed_light', {}), ('day', 'dark_blotch', {}),
    ('museum', 'invented_spotlight', {}), ('museum', 'tone_inversion', {}), ('museum', 'flat_hdr', {}),
    ('museum', 'dark_blotch', {'cx': 340, 'cy': 260}),
    ('night', 'invented_spotlight', {}), ('night', 'rim_glow', {}), ('night', 'tone_inversion', {}), ('night', 'removed_light', {}),
    ('night', 'flat_hdr', {}), ('day', 'warm_shade', {}),
]
GAPS = [
    ('museum', 'rim_glow', {}, 'ring of light around the synthetic exhibit: passes here, caught on all ten real photos (the synthetic exhibit is unlike real ones)'),
    ('museum', 'removed_light', {}, "highlights pressed down: not separable from grade.py's own highlight recovery (-25 lowers the top 0.5% by up to 25 L*); look_transfer.py puts back light G removed"),
]


def verdict(tmp_path, scene_name, defect, kw):
    a = synth.SCENES[scene_name]()
    src, bad = synth.save(a, tmp_path / 's.png'), synth.save(getattr(synth, defect)(a, **kw), tmp_path / 'd.png')
    return json.loads(run_tool('physics_check.py', src, bad).stdout)['verdict']


@pytest.mark.parametrize('scene_name', list(synth.SCENES))
def test_honest_edit_is_not_accused(tmp_path, scene_name):
    assert verdict(tmp_path, scene_name, 'good_edit', {}).startswith('PHYSICALLY_PLAUSIBLE')


@pytest.mark.parametrize('scene_name', list(synth.SCENES))
def test_unchanged_photo_is_not_accused(tmp_path, scene_name):
    a = synth.SCENES[scene_name]()
    src = synth.save(a, tmp_path / 's.png')
    assert json.loads(run_tool('physics_check.py', src, src).stdout)['verdict'].startswith('PHYSICALLY_PLAUSIBLE')


@pytest.mark.parametrize('scene_name,defect,kw', CAUGHT, ids=[f'{s}-{d}' for s, d, _ in CAUGHT])
def test_defect_is_reported(tmp_path, scene_name, defect, kw):
    assert not verdict(tmp_path, scene_name, defect, kw).startswith('PHYSICALLY_PLAUSIBLE')


@pytest.mark.parametrize('scene_name,defect,kw,why', GAPS, ids=[f'{s}-{d}' for s, d, _, _ in GAPS])
def test_known_gap(tmp_path, scene_name, defect, kw, why):
    if verdict(tmp_path, scene_name, defect, kw).startswith('PHYSICALLY_PLAUSIBLE'):
        pytest.xfail(why)
    pytest.fail('this gap is closed: move the entry from GAPS to CAUGHT')
