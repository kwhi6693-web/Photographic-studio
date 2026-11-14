"""Every tool starts, and the grading tool is a deterministic function that respects its own limits."""
import hashlib, json
import synth
from conftest import TOOLS, load, run_tool


def test_selfcheck_reports_all_tools_runnable():
    r = json.loads(run_tool('selfcheck.py').stdout)
    assert all(r['tools'].values()), r['tools']
    assert set(r['tools']) | {'ps_common.py', 'selfcheck.py'} == {p.name for p in TOOLS.glob('*.py')}


def test_measure_runs_on_every_scene(scene):
    for name in synth.SCENES:
        r = json.loads(run_tool('measure.py', scene(name)).stdout)
        assert r['size'] == [synth.W, synth.H]


def test_grade_is_deterministic_and_clamps(tmp_path, scene):
    src = scene('day'); pj = tmp_path / 'p.json'
    pj.write_text(json.dumps({'exposure_ev': 9, 'contrast': 0.2}))
    outs = []
    for t in 'ab':
        p = run_tool('grade.py', src, tmp_path / f'{t}.png', pj, tmp_path / f'{t}.json')
        assert p.returncode == 0, p.stderr[-500:]
        outs.append(hashlib.sha256((tmp_path / f'{t}.png').read_bytes()).hexdigest())
    assert outs[0] == outs[1]
    assert 'exposure_ev' in json.dumps(json.loads((tmp_path / 'a.json').read_text())) and load(tmp_path / 'a.png').shape == load(src).shape


def test_empty_grade_changes_nothing(tmp_path, scene):
    src = scene('day'); pj = tmp_path / 'p.json'; pj.write_text('{}')
    run_tool('grade.py', src, tmp_path / 'o.png', pj)
    assert abs(load(tmp_path / 'o.png') - load(src)).max() <= 1.5 / 255


def test_reframe_square_crop_allowed_and_never_extends(tmp_path):
    """v1.0.9 (owner's example): straighten ~1 degree, keep the top, go 3:4 -> 1:1 (about 0.64-0.7 kept) is allowed;
    a crop box outside the frame (extending the photo) is refused."""
    import json as _json
    from conftest import ROOT, run_tool
    src = sorted((ROOT / 'tests' / 'fixtures' / 'real').glob('*.jpg'))[0]
    out = tmp_path / 'sq.png'
    p = run_tool('reframe.py', src, out, '--rotate', '-1.06', '--box', '0,0,1,0.75', '--allow-aspect-change')
    assert p.returncode == 0, p.stderr
    log = _json.loads((tmp_path / 'sq.png.json').read_text())
    w, h = log['output_size']
    assert abs(w / h - 1) < 0.01 and log['area_retained'] < 0.8 and not any('900' in x for x in log['warnings'])
    bad = run_tool('reframe.py', src, tmp_path / 'x.png', '--box', '0,0,1.1,0.8', '--allow-aspect-change')
    assert bad.returncode != 0 and 'never extends' in (bad.stderr + bad.stdout)
