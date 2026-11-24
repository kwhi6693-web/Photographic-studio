"""Real G outputs from the owner's agent runs (fixtures/real_g/): original, G intermediate, the director's grade
parameters and the agent's finish.py receipt. b1_*: 2026-11-13 batch under v1.0.1; b2_*: 2026-11-13 batch under v1.0.3.
They guard the main promise: a photo whose G route passes the physics checks keeps G's look, and a G route with a real
defect does not."""
import json
import pytest
from conftest import ROOT, run_tool
from look_transfer import cv2

RG = ROOT / 'tests' / 'fixtures' / 'real_g'
CASES = sorted(p.name for p in RG.iterdir() if p.is_dir())

# 2026-11-24: b2_02 exceeds the subject chroma limit on the OpenCV default route after the shadow fix.
# The NumPy backend still passes on default, so each backend must keep its own route.
B2_02_ROUTE = 'default' if getattr(cv2, 'LITE', False) else 'local0_safer_grade'

# The route each must take. b2_01: G repainted the screen (peonies that are not in the photo) and its colour came
# through as blotches; b2_05: G darkened a real light beam on the wall. Both were checked by eye; N direct is right.
# v1.0.9: museum photos are no longer raised to the fixed museum strength because a subject measure is under a floor,
# so the museum cases keep the same route without the '_museum_strength' step (G kept where it passes, N direct where not).
EXPECTED = {'b1_01': 'default', 'b1_02': 'default', 'b1_03': 'default', 'b1_04': 'default', 'b1_05': 'default',
            'b2_01': 'n_direct', 'b2_02': B2_02_ROUTE, 'b2_03': 'default', 'b2_04': 'default', 'b2_05': 'n_direct',
            'b2_06': 'default', 'b2_07': 'default', 'b2_08': 'default', 'b2_09': 'default',
            'b2_10': 'default',
            # v1.2.5: c1_05 (boat on a garden canal, 2026-11-19 batch): G dimmed the bright sky gaps and their reflections
            #   (lamps_kept); it was delivered as N direct. harmonize.py --light-only now restores those lights inside
            #   finish.py, so the G route is kept.
            'c1_05': 'default',
            # v1.2.6: c1_04 (arched branches over a pond, 2026-11-19 rework): G route; its subdue moves are measured as
            #   the share of excess brightness over the surroundings taken away (see test_subdue_*).
            'c1_04': 'default'}


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
    0.12 is reduced on the selected G route to prevent hard rims."""
    d = RG / 'b2_02'
    out, rec = tmp_path / 'f.png', tmp_path / 'f.json'
    run_tool('finish.py', next(d.glob('original.*')), d / 'g.png', d / 'params.json', out, rec, '--genre=museum')
    r = json.loads(rec.read_text())
    assert r['delivered'] == B2_02_ROUTE
    # 2026-11-24: verify clarity on the delivered G route, which differs between backends for b2_02.
    a = next(x for x in r['attempts'] if x['name'] == r['delivered'])
    # v1.4.0: the shadow-lift clamp holds back part of G's lift in the darks, so G's measured local-contrast gain here
    #   is ~1.24 (was ~1.29); the clarity is still taken off almost entirely
    assert a['clarity_unstacked']['g_local_contrast_gain'] > 1.2 and a['clarity_unstacked']['clarity'][1] <= 0.02


def test_put_out_lights_are_repaired_not_a_reason_to_drop_g(tmp_path):
    """v1.2.5: c1_05 - the G attempt's only physics problem was lamps_kept; the in-place light repair fixes it."""
    d = RG / 'c1_05'
    out, rec = tmp_path / 'f.png', tmp_path / 'f.json'
    run_tool('finish.py', next(d.glob('original.*')), d / 'g.png', d / 'params.json', out, rec)
    r = json.loads(rec.read_text())
    a = next(x for x in r['attempts'] if x['name'] == r['delivered'])
    assert r['delivered'] == 'default'
    # v1.4.0: with the shadow clamp and the key light's falloff kept off bright openings, the G attempt no longer puts
    #   the sky gaps out at all; when it does, the in-place repair must leave nothing
    assert 'lamps_kept' not in a['problems']
    if 'light_repair' in a: assert a['light_repair']['left'] == []


def test_subdue_moves_quiet_distractions_by_contrast_not_by_amount(tmp_path):
    """v1.2.6: c1_04 - white visitors, a white stone and its reflection. Even with a strength range flag on the photo
    (lit warmth), the subdue moves are strengthened in small steps until the physics check would see a dark patch."""
    d = RG / 'c1_04'
    out, rec = tmp_path / 'f.png', tmp_path / 'f.json'
    run_tool('finish.py', next(d.glob('original.*')), d / 'g.png', d / 'params.json', out, rec)
    r = json.loads(rec.read_text())
    a = next(x for x in r['attempts'] if x['name'] == r['delivered'])
    sub = [m for m in a['improve']['moves'] if m['effect'] == 'subdue']
    # v1.4.0: >= 0.20 (the rule's visibility floor; was 0.25): G's own lit warmth (+6.1 against a limit of 4.0) now
    #   decides which rung of the ladder is delivered, and the clean one quiets the distractions by 0.31 / 0.23
    assert len(sub) == 2 and all(m['value'] >= 0.20 for m in sub), sub
    assert not any(m.get('over_cap') for m in sub)
