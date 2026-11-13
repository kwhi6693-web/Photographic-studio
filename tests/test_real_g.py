"""Real G outputs from the owner's ChatGPT runs (fixtures/real_g/): original, G intermediate, the director's grade
parameters and ChatGPT's finish.py receipt. b1_*: 2026-11-13 batch under v1.0.1; b2_*: 2026-11-13 batch under v1.0.3.
They guard the main promise: a photo whose G route passes the physics checks keeps G's look, and a G route with a real
defect does not."""
import json
import pytest
from conftest import ROOT, run_tool

RG = ROOT / 'tests' / 'fixtures' / 'real_g'
CASES = sorted(p.name for p in RG.iterdir() if p.is_dir())


# The route each must take. b2_01: G repainted the screen (peonies that are not in the photo) and its colour came
# through as blotches; b2_05: G darkened a real light beam on the wall. Both were checked by eye; N direct is right.
EXPECTED = {'b1_01': 'default', 'b1_02': 'default', 'b1_03': 'default', 'b1_04': 'default', 'b1_05': 'default',
            'b2_01': 'n_direct_museum_strength', 'b2_02': 'default', 'b2_05': 'n_direct_museum_strength',
            'b2_06': 'museum_strength', 'b2_07': 'museum_strength', 'b2_08': 'default', 'b2_09': 'default',
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
