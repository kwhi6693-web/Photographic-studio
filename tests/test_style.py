"""v1.3.0 personal style library: built from the user's own samples, applied as a small push on the brief's global
parameters, never touching moves or keep regions, and dropped for a photo when it breaks a physics check."""
import json
import numpy as np
from PIL import Image
from conftest import ROOT, TOOLS, run_tool, load
import style

REAL_G = ROOT / 'tests' / 'fixtures' / 'real_g'
TASTE = ROOT / 'docs' / 'history' / 'taste'


def _halves(tmp_path):
    """The six approved before/after samples: left half the original, right half the user's final."""
    files = []
    for f in sorted(TASTE.glob('*.jpg')):
        im = Image.open(f).convert('RGB'); w, h = im.size
        o, fi = tmp_path / f'{f.stem}_o.png', tmp_path / f'{f.stem}_f.png'
        im.crop((0, 0, w // 2, h)).save(o); im.crop((w // 2, 0, w, h)).save(fi)
        files += [o, fi]
    return files


def _warm_pairs(tmp_path, n=4):
    """Originals and the same photos graded warmer: a style built from them must lean warm."""
    files = []
    for i, d in enumerate(sorted(p for p in REAL_G.iterdir() if p.is_dir())[:n]):
        o = next(d.glob('original.*')); w = tmp_path / f'w{i}.png'; pj = tmp_path / 'warm.json'
        pj.write_text(json.dumps({'white_balance': {'temp': 0.3}}))
        assert run_tool('grade.py', o, w, pj).returncode == 0
        files += [o, w]
    return files


def test_build_from_pairs_finds_the_direction(tmp_path):
    prof = tmp_path / 'p.json'
    r = run_tool('style.py', 'build', prof, '--pairs', *_warm_pairs(tmp_path))
    assert r.returncode == 0, r.stderr
    t = json.loads(prof.read_text())['general']['tendencies']
    assert t['warm']['offset'] > 0.2 and t['warm']['confidence'] > 0.5
    assert abs(t['colour']['offset']) < t['warm']['offset']


def test_build_needs_three_to_ten_samples(tmp_path):
    files = _warm_pairs(tmp_path, 2)
    assert run_tool('style.py', 'build', tmp_path / 'p.json', '--pairs', *files).returncode != 0


def test_the_approved_samples_build_a_profile_and_words(tmp_path):
    prof = tmp_path / 'p.json'
    assert run_tool('style.py', 'build', prof, '--pairs', *_halves(tmp_path)).returncode == 0
    p = json.loads(prof.read_text())
    assert p['general']['samples'] == 6 and p['on'] is True
    w = json.loads(run_tool('style.py', 'words', prof).stdout)['words']
    assert w and not any(ch.isdigit() for ch in w)   # words for G carry no numbers


def test_apply_pushes_only_global_parameters_within_the_cap():
    params = {'contrast': 0.05, 'vibrance': 0.1,
              'moves': [{'what': 'sky', 'look': 'light-', 'shape': 'gradient', 'from': 'top', 'end': 0.5, 'lift': -4}],
              'keep': [{'box': [0.1, 0.1, 0.2, 0.2], 'mode': 'content'}]}
    prof = {'on': True, 'general': {'tendencies': {k: {'offset': 99 if k != 'depth' else -99, 'confidence': 1.0} for k in style.TEND}}}
    out = style.apply(params, prof)
    assert out['moves'] == params['moves'] and out['keep'] == params['keep']
    assert out['white_balance']['temp'] <= style.CAP['warm'] + 1e-6
    assert out['vibrance'] <= 0.1 + style.CAP['colour'] + 1e-3
    assert out['shadows'] >= -style.CAP['depth'] - 1e-6
    assert set(out['style']['changes']) == {'white_balance.temp', 'vibrance', 'contrast', 'shadows', 'clarity'}


def test_style_off_changes_nothing():
    out = style.apply({'contrast': 0.05}, {'on': False, 'general': {'tendencies': {'warm': {'offset': 0.3, 'confidence': 1}}}})
    assert out['contrast'] == 0.05 and 'white_balance' not in out and out['style']['on'] is False


def test_feedback_steps_and_builds_confidence(tmp_path):
    prof = tmp_path / 'p.json'
    for _ in range(3):
        assert run_tool('style.py', 'feedback', prof, '--param=warm', '--dir=-1', '--words=太暖了').returncode == 0
    p = json.loads(prof.read_text())
    t = p['general']['tendencies']['warm']
    assert t['offset'] < 0 and t['confidence'] >= 0.45 and len(p['feedback']) == 3
    run_tool('style.py', 'feedback', prof, '--param=warm', '--dir=1', '--words=太冷了')
    assert json.loads(prof.read_text())['general']['tendencies']['warm']['confidence'] < t['confidence']


def _b2_10():
    d = REAL_G / 'b2_10'
    return next(d.glob('original.*')), d / 'g.png', d / 'params.json'


def test_finish_uses_the_style_first(tmp_path):
    o, g, pj = _b2_10()
    prof = tmp_path / 'p.json'
    prof.write_text(json.dumps({'on': True, 'general': {'tendencies': {'warm': {'offset': 0.3, 'confidence': 1.0}}}}))
    run_tool('finish.py', o, g, pj, tmp_path / 'off.png', tmp_path / 'off.json')
    r = run_tool('finish.py', o, g, pj, tmp_path / 'on.png', tmp_path / 'on.json', f'--style={prof}')
    rec = json.loads((tmp_path / 'on.json').read_text())
    assert r.returncode == 0 and rec['delivered'] == 'default_style'
    assert rec['style']['changes']['white_balance.temp'][1] > 0
    b_on = style.stats(load(tmp_path / 'on.png'))['warm']; b_off = style.stats(load(tmp_path / 'off.png'))['warm']
    assert b_on > b_off + 0.5


def test_a_style_that_breaks_physics_falls_back_to_the_plain_brief(tmp_path):
    o, g, pj = _b2_10()
    prof = tmp_path / 'p.json'   # an absurd style: everything at the cap
    prof.write_text(json.dumps({'on': True, 'general': {'tendencies': {
        'warm': {'offset': 1, 'confidence': 1}, 'colour': {'offset': 1, 'confidence': 1}, 'contrast': {'offset': 1, 'confidence': 1},
        'depth': {'offset': 99, 'confidence': 1}, 'clarity': {'offset': 1, 'confidence': 1}}}}))
    run_tool('finish.py', o, g, pj, tmp_path / 'on.png', tmp_path / 'on.json', f'--style={prof}')
    rec = json.loads((tmp_path / 'on.json').read_text())
    first = rec['attempts'][0]
    assert first['name'] == 'default_style'
    if first['problems']:   # broke a physics check: the plain brief is what comes out
        assert rec['delivered'] != 'default_style'


def test_no_style_no_style_attempt(tmp_path):
    o, g, pj = _b2_10()
    run_tool('finish.py', o, g, pj, tmp_path / 'x.png', tmp_path / 'x.json')
    rec = json.loads((tmp_path / 'x.json').read_text())
    assert 'style' not in rec and not any(a['name'].endswith('_style') for a in rec['attempts'])


def test_gains_match_grade(tmp_path):
    """The calibration in style.GAIN still describes grade.py: the median over four originals (one photo alone can go
    the other way)."""
    import numpy as np
    units = {'warm': ({'white_balance': {'temp': 0.3}}, 0.3), 'colour': ({'vibrance': 0.25}, 0.25), 'contrast': ({'contrast': 0.2}, 0.2)}
    gains = {k: [] for k in units}
    for d in sorted(p for p in REAL_G.iterdir() if p.is_dir())[:4]:
        o = next(d.glob('original.*')); s0 = style.stats(load(o))
        for k, (p, u) in units.items():
            pj = tmp_path / 'u.json'; pj.write_text(json.dumps(p)); out = tmp_path / 'u.png'
            run_tool('grade.py', o, out, pj)
            gains[k].append((style.stats(load(out))[k] - s0[k]) / u)
    for k, g in gains.items():
        assert 0.4 * style.GAIN[k] < float(np.median(g)) < 2.5 * style.GAIN[k], (k, g)
