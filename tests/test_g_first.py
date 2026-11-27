"""g-direct (and the standalone light route) keep G pixels; hard failures ask for a redraw or deliver quick N."""
import json

import numpy as np
import pytest

import g_first
from conftest import ROOT, load, load_legacy, run_tool, synth

# v1.6.2: the standalone light route and the --g-first ghost gate were removed from the package's g_first.py; their
# tests run on the pre-slim snapshot in legacy/v1.4 (same assertions).
g_first_v14 = load_legacy('g_first')

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
    g_first = g_first_v14
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
    assert 'g_first.py' in receipt['next'][0]
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
    args = (source, generated, params, output, receipt, '--genre=museum')
    result = run_cli('g_first.py', *args)   # v1.4.6: the light route stays a standalone tool; pipeline --g-first is gone
    steps = result['steps']['g_first']
    assert set(result['steps']) == {'g_first'}
    assert steps['museum_gate'] == 'pass'
    assert steps['physics_final']['serious'] == []
    assert steps['reframe']['original_reframed_same_way']
    assert steps['restore']['boxes']
    if LITE:
        assert 'texture_skipped_no_opencv' in steps['degraded']
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
    run_cli('g_first.py', *args)
    assert first == (output.read_bytes(), receipt.read_bytes())


@pytest.mark.parametrize('defect', [
    'wrong_scene', 'edge_halo', 'ghost_edges', 'shifted_ghost', 'invented_spotlight',
    'wrong_composition', 'redrawn_texture', 'synth_rim_glow',
])
def test_light_route_falls_back_on_defects(tmp_path, defect):
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
    output.write_bytes(b'previous delivery')
    trial = run_cli('g_first.py', source, generated, params, output, receipt, *flags)
    steps = trial['steps']['g_first']
    assert steps['verdict'].startswith('FALLBACK:')
    assert 'g_first.py' in steps['next'][0]
    assert output.read_bytes() == b'previous delivery'
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
    receipt = g_first_v14.run(source, draft, params, tmp_path / 'out.png')
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
    receipt = g_first_v14.run(source, draft, params, tmp_path / 'out.png')
    assert receipt['verdict'].startswith('FALLBACK: precheck: ghost_edges')
    report = receipt['steps']['g_first']['precheck']['physics_g']
    assert 'ghost_edges' in report['serious']
    ghost = next(h for h in report['hints'] if isinstance(h, dict) and 'ghost_raw' in h)
    assert ghost['ghost_residual_limit'] == 0
    assert ghost['ghost_decision'] == 'FALLBACK'
    assert ghost['ghost_raw'] == ghost['ghost_amplified'] + ghost['ghost_residual']


@pytest.mark.parametrize('params, cli, expected, source', [
    ({}, None, 0.02, 'default'),
    ({'g_first': {'ghost_residual_limit': 0.5}}, None, 0.02, 'default'),
    ({'g_first': {'ghost_residual_limit': 0.01}}, None, 0.01, 'params'),
    ({'g_first': {'ghost_residual_limit': None}}, None, None, 'params'),
    ({}, 0.05, 0.05, 'command_line'),
    ({'g_first': {'ghost_residual_limit': 0.01}}, 0.05, 0.05, 'command_line'),
    ({'g_first': {'ghost_residual_limit': 0.02}}, 0.01, 0.01, 'command_line'),
    ({'g_first': {'ghost_residual_limit': 0.5}}, 0.3, 0.3, 'command_line'),
])
def test_params_only_tighten_and_command_line_wins(params, cli, expected, source):
    setting = g_first.resolve_ghost_limit(params, cli)
    assert setting['value'] == expected
    assert setting['source'] == source
    assert ('ignored_params_value' in setting) == (cli is None and expected == 0.02 and source == 'default'
                                                  and 'g_first' in params)


@pytest.mark.parametrize('params, cli', [
    ({'g_first': {'ghost_residual_limit': 1.5}}, None),
    ({'g_first': {'ghost_residual_limit': -0.1}}, None),
    ({'g_first': {'ghost_residual_limit': 'loose'}}, None),
    ({}, 1.5),
    ({}, -0.01),
])
def test_out_of_range_ghost_limit_is_an_error(params, cli):
    with pytest.raises(ValueError):
        g_first.resolve_ghost_limit(params, cli)


def test_loosening_in_params_is_ignored_and_recorded(tmp_path):
    source, draft, _ = real_g('b1_01')
    receipt = g_first_v14.run(source, draft, {'g_first': {'ghost_residual_limit': 0.5}}, tmp_path / 'out.png')
    steps = receipt['steps']['g_first']
    setting = steps['ghost_residual_limit']
    assert setting['value'] == 0.02 and setting['source'] == 'default'
    assert setting['ignored_params_value'] == 0.5 and '参数放宽被忽略' in setting['note']
    ghost = next(h for h in steps['precheck']['physics_g']['hints'] if isinstance(h, dict) and 'ghost_raw' in h)
    assert ghost['ghost_residual_limit'] == 0.02


def test_command_line_limit_beats_params_through_pipeline(tmp_path):
    source, draft, _ = real_g('b1_04')   # v1.6.3: b1_01 is very dark and goes to the look route; b1_04 stays on G direct
    params = tmp_path / 'params.json'
    params.write_text(json.dumps({'g_first': {'ghost_residual_limit': 0}}))
    output, receipt = tmp_path / 'final.png', tmp_path / 'receipt.json'
    result = run_cli('pipeline.py', source, draft, params, output, receipt, '--g-direct',
                     '--ghost-residual-limit=0.05')
    setting = result['steps']['g_first']['ghost_residual_limit']
    assert setting == {'value': 0.05, 'source': 'command_line'}
    ghost = next(h for h in result['steps']['g_first']['physics_final']['hints']
                 if isinstance(h, dict) and 'ghost_raw' in h)   # v1.5.0: g-direct reports only the final check
    assert ghost['ghost_residual_limit'] == 0.05


@pytest.mark.parametrize('tool_name', ['pipeline.py', 'g_first.py'])
def test_out_of_range_command_line_limit_exits_nonzero(tmp_path, tool_name):
    source, draft, params = real_g('b1_01')
    extra = ('--g-direct',) if tool_name == 'pipeline.py' else ()
    process = run_tool(tool_name, source, draft, params, tmp_path / 'o.png', tmp_path / 'r.json',
                       *extra, '--ghost-residual-limit=1.5')
    assert process.returncode != 0
    assert 'ghost-residual-limit' in process.stderr


# --g-direct (v1.5.0): G's own pixels, no texture blend; only hard failures stop it.

def test_direct_delivers_without_texture(tmp_path):
    source, generated, params = real_g('b1_05')   # v1.6.3: b1_02 is very dark and goes to the look route
    output, receipt = tmp_path / 'direct.png', tmp_path / 'direct.json'
    result = run_cli('pipeline.py', source, generated, params, output, receipt, '--g-direct')
    steps = result['steps']['g_first']
    assert set(result['steps']) == {'look_trigger', 'g_first'}   # v1.6.3: the trigger is computed and recorded
    assert not result['steps']['look_trigger']['straight_to_look']
    assert result['backend'] == ('cvlite' if LITE else 'opencv')
    assert steps['mode'] == 'g-direct' and steps['g_draw'] == 1
    assert steps['texture'] == 'OFF_G_DIRECT'
    assert steps['verdict'] == 'DELIVER_G_DIRECT'
    # v1.5.0: only the thin margin G did not reach is trimmed
    left, top, right, bottom = steps['edge_trim']['px_trimmed_left_top_right_bottom']
    assert max(left, top, right, bottom) <= 0.02 * max(load(source).shape)
    assert load(output).shape[:2] == (load(source).shape[0] - top - bottom, load(source).shape[1] - left - right)


def serious_physics(monkeypatch, scene_ok=True, chroma=1.0):
    real_tool = g_first.tool

    def tool(name, *args):
        if name == 'physics_check.py':
            return {'checks': {problem: {'ok': problem != 'halo'} for problem in g_first.SERIOUS_PHYSICS}}
        if name == 'check_g_output.py':
            return {'verdict': 'PASS', 'scene_correspondence_ok': scene_ok}
        return real_tool(name, *args)

    monkeypatch.setattr(g_first, 'tool', tool)


def test_direct_optical_problems_are_report_only(tmp_path, monkeypatch):
    """v1.5.0: physics never stops g-direct; the precheck is skipped and the final check only reports."""
    source, generated, _ = real_g('b1_02')
    serious_physics(monkeypatch)
    for draw in (1, 2):
        target = tmp_path / f'out{draw}.png'
        receipt = g_first.run(source, generated, {}, target, direct=True, draw=draw)
        steps = receipt['steps']['g_first']
        assert receipt['verdict'] == 'DELIVER_G_DIRECT' and target.exists()
        assert steps['precheck']['physics_g']['verdict'] == 'SKIPPED_G_DIRECT'
        assert steps['precheck']['confidence']['verdict'] == 'SKIPPED_G_DIRECT'
        assert steps['physics_final']['serious'] == ['halo']
        assert steps['physics_final']['verdict'] == 'REPORT_ONLY_G_DIRECT'


def test_direct_keeps_hard_fallbacks(tmp_path, monkeypatch):
    source, generated, _ = real_g('b1_02')
    museum = g_first.run(source, generated, {}, tmp_path / 'm.png', 'museum', direct=True)
    assert museum['verdict'] == 'FALLBACK: museum without keep'
    assert any('快速 N 直出' in line for line in museum['next'])
    serious_physics(monkeypatch, scene_ok=False)
    # a scene mismatch in draw 1 is the G's fault (collage, new framing) - ask for one more draw
    scene = g_first.run(source, generated, {}, tmp_path / 's.png', direct=True)
    assert scene['verdict'].startswith('REDRAW_G: precheck: scene correspondence')
    assert scene['output'] is None and any('拼图' in line for line in scene['next'])
    scene = g_first.run(source, generated, {}, tmp_path / 's.png', direct=True, draw=2)
    assert scene['verdict'].startswith('FALLBACK: precheck: scene correspondence')


def test_direct_chroma_ratio_is_report_only(tmp_path):
    """v1.5.0: on grey originals the 1.65x ratio rejected every good first draw (2026-11-26)."""
    source = synth.save(synth.day(), tmp_path / 'day.png')
    photo = load(source)
    grey = photo.mean(axis=-1, keepdims=True)
    loud = np.clip(grey + (photo - grey) * 2.6, 0, 1)
    generated = synth.save(loud, tmp_path / 'loud.png')
    receipt = g_first.run(source, generated, {}, tmp_path / 'out.png', direct=True)
    drift = receipt['steps']['g_first']['precheck']['drift']
    assert drift['chroma_ratio_nonsky'] > 1.65
    assert drift['verdict'] == 'REPORT: non-sky chroma ratio'
    assert receipt['verdict'] == 'DELIVER_G_DIRECT'
    assert not any('颜色不要比原片浓' in line for line in receipt['next'])
    light = g_first_v14.run(source, generated, {}, tmp_path / 'light.png')
    assert 'non-sky chroma ratio' in light['verdict']   # the standalone light route keeps its ceiling


def test_covered_rect_trims_only_uncovered_lines():
    coverage = np.ones((100, 80), np.float32)
    coverage[-7:, :] = 0          # G did not reach the bottom 7 rows
    coverage[:, :2] = 0.5         # nor fully the first two columns
    assert g_first.covered_rect(coverage) == (2, 0, 80, 93)
    assert g_first.covered_rect(np.ones((10, 10), np.float32)) == (0, 0, 10, 10)


def test_direct_skips_too_tight_crop(tmp_path):
    source, generated, _ = real_g('b1_02')
    tight = {'reframe': {'box': [0.2, 0.2, 0.7, 0.7], 'allow_aspect_change': True}}
    receipt = g_first.run(source, generated, tight, tmp_path / 'tight.png', direct=True)
    reframe = receipt['steps']['g_first']['reframe']
    assert receipt['verdict'] == 'DELIVER_G_DIRECT'
    assert reframe['verdict'].startswith('SKIPPED_TOO_TIGHT')
    assert load(tmp_path / 'tight.png').shape[0] > 0.9 * load(source).shape[0]
    fine = {'reframe': {'box': [0, 0.1, 1, 1], 'allow_aspect_change': True}}
    receipt = g_first.run(source, generated, fine, tmp_path / 'fine.png', direct=True)
    assert receipt['steps']['g_first']['reframe']['verdict'] == 'REFRAMED'


def test_pipeline_redraw_does_not_run_default_route(tmp_path, monkeypatch):
    import pipeline
    source, generated, params = real_g('b1_05')   # v1.6.3: b1_02 is very dark and would go to the look route
    monkeypatch.setattr(g_first, 'run', lambda *a, **k: {
        'verdict': 'REDRAW_G: precheck: scene correspondence', 'next': [g_first.REDRAW_HINTS['scene correspondence']],
        'steps': {'g_first': {'mode': 'g-direct'}}, 'output': None})
    receipt = tmp_path / 'r.json'
    monkeypatch.setattr('sys.argv', ['pipeline.py', str(source), str(generated), str(params),
                                     str(tmp_path / 'o.png'), str(receipt), '--g-direct'])
    assert pipeline.main() == 0
    result = json.loads(receipt.read_text())
    assert set(result['steps']) == {'look_trigger', 'g_first'}
    assert result['output'] is None and result['verdict'].startswith('REDRAW_G')
    assert not (tmp_path / 'o.png').exists()


def test_default_route_receipt_names_backend(tmp_path):
    source, generated, params = real_g('b1_02')
    result = run_cli('pipeline.py', source, generated, params, tmp_path / 'o.png', tmp_path / 'r.json')
    assert result['backend'] == ('cvlite' if LITE else 'opencv')


def test_direct_restore_is_backend_independent(tmp_path, monkeypatch):
    """v1.4.5: g-direct always restores keep boxes with keep_regions content mode, never text_restore."""
    source, generated, _ = real_g('b1_02')
    calls = []
    real_tool = g_first.tool

    def tool(name, *args):
        calls.append(name)
        return real_tool(name, *args)

    monkeypatch.setattr(g_first, 'tool', tool)
    params = {'keep': [{'what': 'sign', 'box': [0.40, 0.40, 0.45, 0.43], 'mode': 'content'}]}
    receipt = g_first.run(source, generated, params, tmp_path / 'out.png', direct=True)
    steps = receipt['steps']['g_first']
    assert 'text_restore.py' not in calls and 'keep_regions.py' in calls
    assert steps['restore']['tool'] == 'keep_regions_content'
    assert receipt['verdict'] in ('DELIVER_G_DIRECT',) or receipt['verdict'].startswith('REDRAW_G')


def test_pipeline_fallback_delivers_quick_n(tmp_path, monkeypatch):
    """v1.5.0: a hard G failure delivers quick N in the same command, never the legacy default route.
    v1.6.3 (approved 2026-11-26): the look route is tried first; quick N follows only when it cannot be done."""
    import pipeline
    import look_route
    source, generated, params = real_g('b1_05')
    monkeypatch.setattr(look_route, 'run', lambda *a, **k: {'verdict': 'FAILED: G cannot be aligned'})
    monkeypatch.setattr(g_first, 'run', lambda *a, **k: {
        'verdict': 'FALLBACK: museum without keep', 'next': [g_first.QUICK_N],
        'steps': {'g_first': {'mode': 'g-direct'}}, 'output': None})
    receipt = tmp_path / 'r.json'
    target = tmp_path / 'o.png'
    target.write_bytes(b'stale')
    monkeypatch.setattr('sys.argv', ['pipeline.py', str(source), str(generated), str(params),
                                     str(target), str(receipt), '--g-direct'])
    assert pipeline.main() == 0
    result = json.loads(receipt.read_text())
    assert set(result['steps']) == {'look_trigger', 'g_first', 'look', 'quick_n'}
    assert result['verdict'] == 'DELIVER_QUICK_N (G hard failure: museum without keep)'
    assert load(target).shape == load(source).shape


def test_quick_n_is_fast_and_non_generative(tmp_path):
    import time
    source, _, _ = real_g('b1_02')
    params = tmp_path / 'p.json'
    params.write_text('{}')
    start = time.time()
    result = run_cli('pipeline.py', source, source, params, tmp_path / 'q.png', tmp_path / 'q.json', '--quick-n')
    assert time.time() - start < 30
    assert result['verdict'] == 'DELIVER_QUICK_N'
    assert result['steps']['quick_n']['grade']['used'] == ['auto']
    assert load(tmp_path / 'q.png').shape == load(source).shape


def test_pipeline_rejects_removed_g_first(tmp_path):
    source, generated, params = real_g('b1_02')
    process = run_tool('pipeline.py', source, generated, params, tmp_path / 'o.png', tmp_path / 'r.json', '--g-first')
    assert process.returncode != 0 and 'removed' in process.stderr


def test_direct_drops_aspect_flag_after_alignment(tmp_path, monkeypatch):
    """v1.4.6: hosts draw G at fixed sizes; once registered, a changed aspect is not a warning."""
    source, generated, _ = real_g('b1_02')
    real_tool = g_first.tool
    flag = ' | FLAGS: ASPECT_CHANGED: check by eye that nothing important was cut or stretched'

    def tool(name, *args):
        if name == 'check_g_output.py':
            report = real_tool(name, *args)
            report.update(aspect_ok=False, verdict='PASS_AUTOMATIC_CHECKS (judge by eye at normal viewing; user decides)' + flag)
            return report
        return real_tool(name, *args)

    monkeypatch.setattr(g_first, 'tool', tool)
    monkeypatch.setattr(g_first_v14, 'tool', tool)
    direct = g_first.run(source, generated, {}, tmp_path / 'd.png', direct=True)['steps']['g_first']
    assert 'ASPECT_CHANGED' not in direct['precheck']['check_g_output']['verdict']
    assert direct['precheck']['check_g_output']['aspect_note']
    light = g_first_v14.run(source, generated, {}, tmp_path / 'l.png')['steps']['g_first']
    assert 'ASPECT_CHANGED' in light['precheck']['check_g_output']['verdict']


def test_keep_preview_draws_boxes_and_grid(tmp_path):
    source, _, _ = real_g('b1_02')
    params = tmp_path / 'p.json'
    params.write_text(json.dumps({'keep': [{'what': 'sign', 'box': [0.1, 0.2, 0.3, 0.4], 'mode': 'content'}]}))
    preview = tmp_path / 'preview.png'
    report = run_cli('keep_preview.py', source, params, preview)
    assert report['boxes'][0]['number'] == 1 and report['verdict'].startswith('LOOK')
    image = load(preview)
    assert max(image.shape[:2]) <= 1600
    h, w = image.shape[:2]
    edge = image[int(0.2 * h):int(0.4 * h), int(0.1 * w) + 1]
    assert (edge[..., 0] > 0.9).mean() > 0.8   # the red box edge is drawn
    params.write_text('{}')
    assert run_cli('keep_preview.py', source, params, preview)['verdict'].startswith('NO_REGIONS')


def test_pipeline_fallback_tries_the_look_route_first(tmp_path, monkeypatch):
    """v1.6.3 (approved 2026-11-26): a hard G failure on a normal photo delivers 'original pixels + G light/colour'."""
    import pipeline
    source, generated, params = real_g('b1_05')
    monkeypatch.setattr(g_first, 'run', lambda *a, **k: {
        'verdict': 'FALLBACK: museum without keep', 'next': [g_first.QUICK_N],
        'steps': {'g_first': {'mode': 'g-direct'}}, 'output': None})
    receipt, target = tmp_path / 'r.json', tmp_path / 'o.png'
    monkeypatch.setattr('sys.argv', ['pipeline.py', str(source), str(generated), str(params),
                                     str(target), str(receipt), '--g-direct'])
    assert pipeline.main() == 0
    result = json.loads(receipt.read_text())
    assert result['verdict'] == 'DELIVER_LOOK (G hard failure: museum without keep)'
    assert 'quick_n' not in result['steps'] and target.exists()


def test_bad_options_fail_before_the_look_route(tmp_path):
    """v1.6.3 fix: on a very dark original the look route ran before the options were checked."""
    source, draft, params = real_g('b1_01')
    process = run_tool('pipeline.py', source, draft, params, tmp_path / 'o.png', tmp_path / 'r.json',
                       '--g-direct', '--g-draw=3')
    assert process.returncode != 0 and 'g-draw' in process.stderr
