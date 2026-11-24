"""The experimental route keeps G pixels and leaves default delivery available."""
import json

import numpy as np
import pytest

import g_first
from conftest import ROOT, load, run_tool, synth

FIXTURES = ROOT / 'tests' / 'fixtures'
LITE = getattr(g_first.cv2, 'LITE', False)


def run_cli(name, *args):
    process = run_tool(name, *args)
    assert process.returncode == 0, process.stderr[-1500:]
    return json.loads(process.stdout)


def real_g(name):
    folder = FIXTURES / 'real_g' / name
    return next(folder.glob('original.*')), folder / 'g.png', folder / 'params.json'


def test_alignment_uses_source_to_g_map_once(monkeypatch):
    shape = (20, 32, 3)
    source = np.zeros(shape, dtype=np.float32)
    generated = source.copy()
    generated[7, 13] = 1
    homography = np.array([[1, 0, 3], [0, 1, 2], [0, 0, 1]], dtype=float)
    if LITE:
        monkeypatch.setattr(g_first.cv2, 'register', lambda *_: (homography, 0.8))
    else:
        monkeypatch.setattr(g_first, 'register', lambda *_: (homography, 100))
    actual, report = g_first.align_g(source, generated)
    assert report['ok']
    assert actual.shape == source.shape
    assert (actual[5, 10] == 1).all()


def test_all_prechecks_run_even_when_scene_fails(tmp_path, monkeypatch):
    source, generated, _ = real_g('b1_02')
    photo = load(source)
    monkeypatch.setattr(g_first, 'align_g', lambda *_: (photo, {'ok': True}))
    calls = []

    def tool(name, *args):
        calls.append((name, args))
        if name == 'check_g_output.py':
            return {'verdict': 'STOP', 'scene_correspondence_ok': False}
        return {'checks': {problem: {'ok': False} for problem in g_first.SERIOUS_PHYSICS}}

    monkeypatch.setattr(g_first, 'tool', tool)
    target = tmp_path / 'output.png'
    receipt = g_first.run(source, generated, {}, target)
    check = receipt['steps']['g_first']['precheck']
    assert calls[0] == ('check_g_output.py', (source, generated))
    assert check['check_g_output']['verdict'] == 'STOP'
    assert set(check['physics_g']['serious']) == g_first.SERIOUS_PHYSICS
    assert check['drift']['chroma_ratio_nonsky'] == pytest.approx(1)
    assert check['confidence']['low_area_outside_keep'] is not None
    assert receipt['verdict'].startswith('FALLBACK: precheck: scene correspondence')
    assert '--g-first' in receipt['next'][0]
    assert not target.exists()


def test_standalone_accepted_real_g(tmp_path):
    source, generated, params = real_g('b1_02')
    output, receipt = tmp_path / 'light.png', tmp_path / 'light.json'
    result = run_cli('g_first.py', source, generated, params, output, receipt)
    assert result == json.loads(receipt.read_text())
    assert result['verdict'] == 'DELIVER_G_FIRST'
    steps = result['steps']['g_first']
    assert steps['restore']['verdict'] == 'NO_REGIONS'
    assert steps['physics_final']['serious'] == []
    assert load(output).shape == load(source).shape


def test_museum_gate_without_keep_leaves_output_untouched(tmp_path):
    source, generated, params = real_g('b1_02')
    output, receipt = tmp_path / 'existing.png', tmp_path / 'light.json'
    output.write_bytes(b'previous delivery')
    result = run_cli('g_first.py', source, generated, params, output, receipt, '--genre=museum')
    assert result['verdict'] == 'FALLBACK: museum without keep'
    assert output.read_bytes() == b'previous delivery'
    steps = result['steps']['g_first']
    assert steps['museum_gate'] == 'fallback: museum without keep'
    assert steps['precheck']['drift']['dL_median_nonsky'] is None


def test_museum_with_keep_restores_and_frames_deterministically(tmp_path):
    source, generated, _ = real_g('b1_02')
    params = tmp_path / 'params.json'
    params.write_text(json.dumps({
        'keep': [{'what': 'bronze sword and mount', 'box': [0.43, 0.38, 0.56, 0.52], 'mode': 'colour'}],
        'reframe': {'zoom': 1.1},
        'g_first': {'texture_strength': 0.85},
    }))
    output, receipt = tmp_path / 'light.png', tmp_path / 'light.json'
    args = (source, generated, params, output, receipt, '--genre=museum', '--g-first')
    result = run_cli('pipeline.py', *args)
    steps = result['steps']['g_first']
    assert set(result['steps']) == {'g_first'}
    assert steps['museum_gate'] == 'pass'
    assert steps['physics_final']['serious'] == []
    assert steps['reframe']['original_reframed_same_way']
    assert steps['restore']['boxes']
    if LITE:
        assert 'G_FIRST_DEGRADED' in result['verdict']
        assert steps['restore']['tool'] == 'keep_regions_content'
        assert steps['texture'] == 'NOT_RUN_NO_OPENCV'
        assert 'texture_skipped_no_opencv' in steps['degraded']

        aligned, _ = g_first.align_g(load(source), load(generated))
        plain = tmp_path / 'aligned.png'
        framed = tmp_path / 'aligned-framed.png'
        synth.save(aligned, plain)
        run_cli('reframe.py', plain, framed, '--zoom=1.1')
        pixels, reference = load(output), load(framed)
        h, w = pixels.shape[:2]
        protected = np.s_[int(h * 0.4):int(h * 0.5), int(w * 0.45):int(w * 0.55)]
        assert np.any(pixels[protected] != reference[protected])
    else:
        assert result['verdict'] == 'DELIVER_G_FIRST'
        assert steps['restore']['tool'] == 'text_restore'
        assert steps['texture']['strength'] == 0.5
    first = output.read_bytes(), receipt.read_bytes()
    run_cli('pipeline.py', *args)
    assert first == (output.read_bytes(), receipt.read_bytes())


@pytest.mark.parametrize('defect', [
    'wrong_scene', 'edge_halo', 'ghost_edges', 'shifted_ghost', 'invented_spotlight',
    'wrong_composition', 'redrawn_texture', 'synth_rim_glow',
])
def test_fallback_delivers_legacy_bytes(tmp_path, defect):
    real = FIXTURES / 'real'
    building, tower = real / '01_building.png', real / '02_night_tower.png'
    flags = ()
    if defect == 'wrong_scene':
        source, generated = building, tower
    else:
        source = building
        if defect in ('edge_halo', 'invented_spotlight'):
            source, flags = tower, ('--genre=night',)
        elif defect == 'synth_rim_glow':
            source = synth.save(synth.day(), tmp_path / 'day.png')
        original = load(source)
        if defect in ('edge_halo', 'ghost_edges'):
            image = synth.edge_halo(original)
        elif defect == 'shifted_ghost':
            image = 0.58 * original + 0.42 * np.roll(original, 28, axis=1)
        elif defect == 'invented_spotlight':
            image = synth.invented_spotlight(original, 0.23, 0.27)
        elif defect == 'wrong_composition':
            image = np.roll(original, original.shape[1] // 3, axis=1)
        elif defect == 'redrawn_texture':
            image = synth.smoothed_texture(original)
        else:
            image = synth.rim_glow(original)
        generated = synth.save(image, tmp_path / f'{defect}.png')
    params = tmp_path / 'params.json'
    params.write_text('{}')
    output, receipt = tmp_path / 'final.png', tmp_path / 'receipt.json'
    args = (source, generated, params, output, receipt, *flags)
    legacy = run_cli('pipeline.py', *args)
    old_bytes = output.read_bytes()
    trial = run_cli('pipeline.py', *args, '--g-first')
    steps = trial['steps'].pop('g_first')
    assert steps['verdict'].startswith('FALLBACK:')
    assert '--g-first' in steps['next'][0]
    assert legacy['steps'] == trial['steps']
    assert output.read_bytes() == old_bytes
    if defect in ('ghost_edges', 'shifted_ghost'):
        physics = steps['precheck']['physics_g']
        assert 'ghost_edges' in physics['serious']
        ghost = next(h for h in physics['hints'] if isinstance(h, dict) and 'ghost_raw' in h)
        assert ghost['ghost_residual_limit'] == 0.02
        assert ghost['ghost_decision'] == 'FALLBACK'
        assert ghost['ghost_raw'] == ghost['ghost_amplified'] + ghost['ghost_residual']


def test_weak_same_position_structure_is_amplified():
    lighting = np.full((42, 42), 0.2, dtype=np.float32)
    lighting[:, :16] += 0.01
    change = np.zeros((*lighting.shape, 2), dtype=np.float32)
    raw = np.zeros(lighting.shape, dtype=bool)
    raw[20, 16] = raw[20, 32] = True
    change[raw, 1] = -2
    _, ys, xs, amplified = g_first.local_ghost_match(lighting, change, raw)
    assert amplified == 1
    assert list(zip(ys, xs)) == [(20, 32)]


def test_displaced_patch_must_beat_same_position():
    structure = np.zeros((48, 48, 2), dtype=np.float32)
    change = np.zeros_like(structure)
    patch = np.random.default_rng(131).normal(size=(5, 5, 2)).astype(np.float32)
    structure[10:15, 12:17] = patch
    change[10:15, 20:25] = patch
    ys, xs = np.array([12]), np.array([22])
    assert g_first.shifted_ghost_count(structure, change, ys, xs) == 1
    structure[10:15, 20:25] = patch
    assert g_first.shifted_ghost_count(structure, change, ys, xs) == 0


@pytest.mark.parametrize('name', ['b1_01', 'b1_04', 'b1_05'])
def test_narrow_ghost_gate_accepts_supported_real_edges(tmp_path, name):
    source, draft, params_file = real_g(name)
    params = json.loads(params_file.read_text())
    assert 'ghost_residual_limit' not in params.get('g_first', {})
    receipt = g_first.run(source, draft, params, tmp_path / 'out.png')
    steps = receipt['steps']['g_first']
    physics = steps['precheck']['physics_g']
    ghost = next(h for h in physics['hints'] if isinstance(h, dict) and 'ghost_raw' in h)
    assert ghost['ghost_residual_limit'] == 0.02
    assert ghost['ghost_raw'] == ghost['ghost_amplified'] + ghost['ghost_residual']
    assert ghost['ghost_decision'] == 'PASS'
    assert 'ghost_edges' not in physics['serious']
    assert 'ghost_edges' not in (steps['physics_final']['serious'] or [])


def test_explicit_ghost_residual_limit_overrides_default(tmp_path):
    source, draft, _ = real_g('b1_01')
    params = {'g_first': {'ghost_residual_limit': 0}}
    receipt = g_first.run(source, draft, params, tmp_path / 'out.png')
    assert receipt['verdict'].startswith('FALLBACK: precheck: ghost_edges')
    report = receipt['steps']['g_first']['precheck']['physics_g']
    assert 'ghost_edges' in report['serious']
    ghost = next(h for h in report['hints'] if isinstance(h, dict) and 'ghost_raw' in h)
    assert ghost['ghost_residual_limit'] == 0
    assert ghost['ghost_decision'] == 'FALLBACK'
    assert ghost['ghost_raw'] == ghost['ghost_amplified'] + ghost['ghost_residual']
