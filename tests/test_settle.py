"""settle.py: step 6 in one call. By default (v1.0.9) it only removes what is over a limit (never under a floor) and
leaves everything else as the photo's own parameters made it; --bands (removed in v1.2.7) is ignored.
Neither mode may introduce a physics problem."""
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
    assert after['L_mean_change']['value'] >= 5.0 - 0.6   # v1.0.9: only the excess goes, it is not pulled lower
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


def test_light_edit_is_left_as_the_brief_chose(tmp_path):
    """v1.0.9: a deliberately light edit is not lifted to a common floor - the photo's own parameters stand."""
    src = REAL / '03_canal.jpg'
    flat = graded(tmp_path, src, {'saturation': 0.97}, 'flat')
    out, rec = settle(tmp_path, src, flat)
    assert not rec['steps'] and np.array_equal(load(out), load(flat))


def test_bands_flag_is_ignored(tmp_path):
    """v2.3.0 (v1.2.7): the unused floor lift and band anchoring are gone; --bands is accepted and changes nothing."""
    src = REAL / '03_canal.jpg'
    flat = graded(tmp_path, src, {'saturation': 0.97}, 'flat')
    out1, _ = settle(tmp_path, src, flat)
    (tmp_path / 'b').mkdir()
    out2, rec = settle(tmp_path / 'b', src, flat, '--bands')
    assert not any(s['direction'] in ('up', 'anchor') for s in rec['steps'])
    assert np.array_equal(load(out1), load(out2))

