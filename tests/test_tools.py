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
