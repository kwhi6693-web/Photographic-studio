"""The v1.1.0 judging-layer tools: reference_style.py ("参考这张"), style_params.py ("风格：xx"), make_pair.py ("记住这张").
They only produce grade parameters or sheets; these tests check they are deterministic, stay inside their caps, push in
the right direction, and that no named style breaks the physics checks on the real test photos."""
import json, re
import pytest
from conftest import PKG, ROOT, TOOLS, run_tool, load

REAL = ROOT / 'tests' / 'fixtures' / 'real'
PHOTOS = {p.stem: p for p in sorted(REAL.iterdir()) if p.suffix in ('.png', '.jpg')}
STYLES = json.loads((PKG / 'assets' / 'styles.json').read_text(encoding='utf-8'))['styles']
# combinations a style says to avoid ("avoid" in styles.json) and that do fail the physics checks
EXPECTED_AVOID = {('warm_film', '02_night_tower')}


def graded(tmp_path, src, params, name):
    pj = tmp_path / f'{name}.json'; pj.write_text(json.dumps(params))
    out = tmp_path / f'{name}.png'; rec = tmp_path / f'{name}_r.json'
    run_tool('grade.py', src, out, pj, rec)
    return out, json.loads(rec.read_text())


def ref_params(tmp_path, src, ref, name='rs'):
    out = tmp_path / f'{name}.json'
    p = run_tool('reference_style.py', src, ref, out)
    assert p.returncode == 0, p.stderr[-500:]
    return json.loads(out.read_text()), json.loads(p.stdout)


@pytest.mark.parametrize('temp,sign', [(0.5, 1), (-0.5, -1)])
def test_reference_style_follows_the_cast(tmp_path, temp, sign):
    src = PHOTOS['01_building']
    ref, _ = graded(tmp_path, src, {'white_balance': {'temp': temp}}, 'ref')
    params, _ = ref_params(tmp_path, src, ref)
    assert sign * params['white_balance']['temp'] > 0.1


def test_reference_style_same_photo_changes_little(tmp_path):
    params, _ = ref_params(tmp_path, PHOTOS['04_willow_lake'], PHOTOS['04_willow_lake'])
    assert abs(params.get('white_balance', {}).get('temp', 0)) < 0.05 and abs(params.get('vibrance', 0)) < 0.05


def test_reference_style_is_deterministic_and_capped(tmp_path):
    a, rep = ref_params(tmp_path, PHOTOS['museum_glass_sunflowers'], PHOTOS['01_building'], 'a')
    b, _ = ref_params(tmp_path, PHOTOS['museum_glass_sunflowers'], PHOTOS['01_building'], 'b')
    assert a == b
    wb = a.get('white_balance', {})
    assert abs(wb.get('temp', 0)) <= 0.6 and abs(wb.get('tint', 0)) <= 0.4 and -0.3 <= a.get('vibrance', 0) <= 0.45
    for k in ('shadows', 'highlights'):
        assert all(abs(v) <= 3 for v in a.get('tone_split', {}).get(k, [0, 0]))
    assert set(a) <= {'white_balance', 'vibrance', 'tone_split'}      # brightness and contrast are only reported
    assert 'for_the_brief' in rep


@pytest.mark.parametrize('style', sorted(STYLES))
def test_style_params_run_cleanly(tmp_path, style):
    out = tmp_path / 'p.json'
    p = run_tool('style_params.py', STYLES[style]['name'], out)
    assert p.returncode == 0 and json.loads(p.stdout)['style'] == style
    _, rec = graded(tmp_path, PHOTOS['01_building'], json.loads(out.read_text()), 's')
    assert rec['clamped'] == []


def test_style_params_keep_the_directors_own(tmp_path):
    base = tmp_path / 'base.json'; base.write_text(json.dumps({'regions': [{'shape': 'rect', 'box': [0, 0, 1, 0.3], 'lift': -4}], 'contrast': 0.3}))
    out = tmp_path / 'p.json'
    run_tool('style_params.py', 'natural_clear', out, f'--base={base}')
    p = json.loads(out.read_text())
    assert p['regions'][0]['lift'] == -4 and p['contrast'] == STYLES['natural_clear']['params']['contrast']


@pytest.mark.parametrize('style', sorted(STYLES))
def test_style_keeps_physics_on_real_photos(tmp_path, style):
    out = tmp_path / 'p.json'; run_tool('style_params.py', style, out)
    params = json.loads(out.read_text()); broken = set()
    for name, src in PHOTOS.items():
        g, _ = graded(tmp_path, src, params, name)
        checks = json.loads(run_tool('physics_check.py', src, g).stdout)['checks']
        if any(isinstance(v, dict) and v.get('ok') is False for v in checks.values()): broken.add((style, name))
    assert broken == {x for x in EXPECTED_AVOID if x[0] == style}


@pytest.mark.parametrize('kind,suffix', [('taste', 'before_after'), ('counter', 'before_bad')])
def test_make_pair_writes_the_package_format(tmp_path, kind, suffix):
    src = PHOTOS['01_building']; res, _ = graded(tmp_path, src, {'vibrance': 0.3}, 'r')
    p = run_tool('make_pair.py', src, res, tmp_path / 'out', 'new_sample', f'--kind={kind}')
    rep = json.loads(p.stdout); f = tmp_path / 'out' / f'new_sample_{suffix}.jpg'
    assert f.exists() and load(f).shape[0] == 900
    assert re.fullmatch(r'[\w]+_before_(?:after|bad)\.jpg', f.name)
    assert any(k.startswith('row_for_') for k in rep)
