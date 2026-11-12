"""Real G outputs from the owner's ChatGPT runs (2026-11-13 batch, fixtures/real_g/): original, G intermediate, the
director's grade parameters and the receipt ChatGPT's finish.py wrote. These are the only real G outputs in the tests,
so they guard the main promise: a tool change must not move a real photo off the route v1.0.1 chose without someone
seeing why. (The batch also showed that v1.0.1 itself left G on 4 of 5 photos; that is recorded, not judged, here.)"""
import json
import pytest
from conftest import ROOT, run_tool

RG = ROOT / 'tests' / 'fixtures' / 'real_g'
CASES = sorted(p.name for p in RG.iterdir() if p.is_dir())


def test_fixtures_present():
    assert len(CASES) == 5


@pytest.mark.parametrize('case', CASES)
def test_same_route_as_chatgpt_run(tmp_path, case):
    d = RG / case; old = json.loads((d / 'receipt.json').read_text())
    out, rec = tmp_path / 'f.png', tmp_path / 'f.json'
    p = run_tool('finish.py', d / 'original.jpeg', d / 'g.png', d / 'params.json', out, rec, *([f"--genre={old['genre']}"] if old.get('genre') else []))
    assert p.returncode == 0, p.stderr[-500:]
    new = json.loads(rec.read_text())
    assert new['delivered'] == old['delivered']
    assert [a['name'] for a in new['attempts']] == [a['name'] for a in old['attempts']]
    assert not any(f.startswith('G_GLOW_LEFT') for a in new['attempts'] for f in a['look_transfer_flags'])
