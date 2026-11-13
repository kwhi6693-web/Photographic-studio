"""settle.py: step 6 in one call. It may only remove what is over a limit (never under a floor), add what is under a
floor, leave an in-range photo untouched, and never introduce a physics problem."""
import json
import numpy as np
from conftest import run_tool, load, ROOT

REAL = ROOT / 'tests' / 'fixtures' / 'real'


def checks(src, img, *opt):
    return json.loads(run_tool('intensity_check.py', src, img, *opt).stdout)


def graded(tmp_path, src, params, name):
    pj = tmp_path / f'{name}.json'; pj.write_text(json.dumps(params)); out = tmp_path / f'{name}.png'
    assert run_tool('grade.py', src, out, pj).returncode == 0
    return out


def settle(tmp_path, src, img, *opt):
    out = tmp_path / 'settled.png'
    p = run_tool('settle.py', src, img, out, *opt)
    assert p.returncode == 0, p.stderr
    return out, json.loads(p.stdout)


def test_too_bright_is_trimmed_back_under_the_limit_only(tmp_path):
    src = REAL / '03_canal.jpg'
    hot = graded(tmp_path, src, {'exposure_ev': 0.45, 'clarity': 0.15, 'vibrance': 0.15}, 'hot')
    before = checks(src, hot)['checks']['L_mean_change']
    assert before['ok'] is False and before['direction'] == 'too strong'
    out, rec = settle(tmp_path, src, hot)
    after = checks(src, out)['checks']
    assert after['L_mean_change']['ok'] is True
    assert after['L_mean_change']['value'] >= 2.0 - 0.3   # v1.0.6: lands in the day band (2..4), not below it
    assert not rec['physics_problems']


def test_settling_twice_changes_nothing(tmp_path):
    """v1.0.6: a settled photo is already inside every range and band, so a second pass leaves it exactly as it is."""
    src = REAL / '03_canal.jpg'
    hot = graded(tmp_path, src, {'exposure_ev': 0.3, 'vibrance': 0.3}, 'hot2')
    once, _ = settle(tmp_path, src, hot)
    twice = tmp_path / 'twice.png'
    p = run_tool('settle.py', src, once, twice)
    rec = json.loads(p.stdout)
    assert not rec['steps'] and np.array_equal(load(once), load(twice))


def test_flat_edit_gets_lifted_to_the_floor(tmp_path):
    src = REAL / '03_canal.jpg'
    flat = graded(tmp_path, src, {'saturation': 0.97}, 'flat')
    assert checks(src, flat)['verdict'].startswith('OUT_OF_RANGE')
    out, rec = settle(tmp_path, src, flat)
    assert any(s['direction'] == 'up' for s in rec['steps'])
    assert not rec['physics_problems']
    weak_after = [k for k, v in checks(src, out)['checks'].items() if isinstance(v, dict) and v.get('direction') == 'too weak']
    weak_before = [k for k, v in checks(src, flat)['checks'].items() if isinstance(v, dict) and v.get('direction') == 'too weak']
    assert len(weak_after) < len(weak_before)
