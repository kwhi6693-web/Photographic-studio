"""Real G outputs from the owner's ChatGPT runs (2026-11-13 batch, fixtures/real_g/): original, G intermediate, the
director's grade parameters and the receipt ChatGPT's finish.py wrote. These are the only real G outputs in the tests,
so they guard the main promise: a photo whose G route passes the physics checks keeps G's look."""
import json
import pytest
from conftest import ROOT, run_tool

RG = ROOT / 'tests' / 'fixtures' / 'real_g'
CASES = sorted(p.name for p in RG.iterdir() if p.is_dir())


def test_fixtures_present():
    assert len(CASES) == 5


@pytest.mark.parametrize('case', CASES)
def test_g_route_is_kept(tmp_path, case):
    """v1.0.1 dropped G on four of these five (01 night misread on a backlit day frame; 02, 04, 05 strength ranges) and
    delivered photos nearly unchanged (mean ΔE 2.0-3.3 from the original). The user preferred the G route on all four.
    Now each must keep G, pass the physics checks and not raise the leftover-glow flag."""
    d = RG / case; old = json.loads((d / 'receipt.json').read_text())
    out, rec = tmp_path / 'f.png', tmp_path / 'f.json'
    p = run_tool('finish.py', d / 'original.jpeg', d / 'g.png', d / 'params.json', out, rec, *([f"--genre={old['genre']}"] if old.get('genre') else []))
    assert p.returncode == 0, p.stderr[-500:]
    new = json.loads(rec.read_text())
    assert not new['delivered'].startswith('n_direct'), new['delivered']
    chosen = next(a for a in new['attempts'] if a['name'] == new['delivered'])
    assert chosen['problems'] == [], chosen['problems']
    assert not any(f.startswith('G_GLOW_LEFT') for a in new['attempts'] for f in a['look_transfer_flags'])
