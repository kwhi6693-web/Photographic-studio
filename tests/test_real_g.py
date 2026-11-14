"""Real G outputs from the owner's agent runs (fixtures/real_g/): original, G intermediate, the director's grade
parameters and the agent's finish.py receipt. b1_*: 2026-11-13 batch under v1.0.1; b2_*: 2026-11-13 batch under v1.0.3.
They guard the main promise: a photo whose G route passes the physics checks keeps G's look, and a G route with a real
defect does not."""
import json
import pytest
from conftest import ROOT, run_tool

RG = ROOT / 'tests' / 'fixtures' / 'real_g'
CASES = sorted(p.name for p in RG.iterdir() if p.is_dir())


# The route each must take. b2_01: G repainted the screen (peonies that are not in the photo) and its colour came
# through as blotches; b2_05: G darkened a real light beam on the wall. Both were checked by eye; N direct is right.
# v1.0.9: museum photos are no longer raised to the fixed museum strength because a subject measure is under a floor,
# so the museum cases keep the same route without the '_museum_strength' step (G kept where it passes, N direct where not).
EXPECTED = {'b1_01': 'default', 'b1_02': 'default', 'b1_03': 'default', 'b1_04': 'default', 'b1_05': 'default',
            'b2_01': 'n_direct', 'b2_02': 'default', 'b2_03': 'default', 'b2_04': 'default', 'b2_05': 'n_direct',
            'b2_06': 'default', 'b2_07': 'default', 'b2_08': 'default', 'b2_09': 'default',
            'b2_10': 'default'}


def test_fixtures_present():
    assert set(CASES) == set(EXPECTED)


@pytest.mark.parametrize('case', sorted(EXPECTED))
def test_route(tmp_path, case):
    d = RG / case; old = json.loads((d / 'receipt.json').read_text())
    src = next(d.glob('original.*'))
    out, rec = tmp_path / 'f.png', tmp_path / 'f.json'
    p = run_tool('finish.py', src, d / 'g.png', d / 'params.json', out, rec, *([f"--genre={old['genre']}"] if old.get('genre') else []))
    assert p.returncode == 0, p.stderr[-500:]
    new = json.loads(rec.read_text())
    assert new['delivered'] == EXPECTED[case]
    if not EXPECTED[case].startswith('n_direct'):
        chosen = next(a for a in new['attempts'] if a['name'] == new['delivered'])
        assert chosen['problems'] == [], chosen['problems']


def test_clarity_does_not_stack_on_g_local_contrast(tmp_path):
    """v1.0.9: b2_02 (glass orchid frames): G's light already raised local contrast by about 29 %, so the brief's clarity
    0.12 is switched off on the G route instead of stacking into hard rims; the route stays the same."""
    d = RG / 'b2_02'
    out, rec = tmp_path / 'f.png', tmp_path / 'f.json'
    run_tool('finish.py', next(d.glob('original.*')), d / 'g.png', d / 'params.json', out, rec, '--genre=museum')
    r = json.loads(rec.read_text())
    a = next(x for x in r['attempts'] if x['name'] == 'default')
    assert r['delivered'] == 'default'
    assert a['clarity_unstacked']['g_local_contrast_gain'] > 1.25 and a['clarity_unstacked']['clarity'][1] == 0.0
