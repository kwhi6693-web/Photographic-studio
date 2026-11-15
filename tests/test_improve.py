"""v1.2.0: "修得好" before "别改坏" - every improvement move of the brief has to show, without a halo.

The three originals are from the owner's 2026-11-15 run under v1.1.0, where all three were judged "light already good",
G was skipped and two came out with no visible change (mean difference 2.9 and 2.2 of 255). The briefs next to
them (fixtures/improve/*.json) are written under the v1.2.0 rules (director_brief.md section 1 step 4).
"""
import json
import numpy as np
import pytest
from conftest import ROOT, run_tool, load

REAL = BRIEFS = ROOT / 'tests' / 'fixtures' / 'improve'
CASES = {'07_lake_frame': None, '08_book_showcase': 'museum', '09_gate_sunset': None}
# mean difference from the original (of 255) that the v1.1.0 run reached on the same photo before its crop: lake 3.3,
# book 8.2 (the one that did show), gate 2.1. v1.2.0 must clearly beat the two invisible ones and keep the book visible.
MIN_DIFF = {'07_lake_frame': 3.3 * 1.3, '08_book_showcase': 5.0, '09_gate_sunset': 2.1 * 1.3}


def finish(tmp_path, name, params=None, genre=None):
    src = REAL / f'{name}.jpg'
    pj = BRIEFS / f'{name}.json'
    if params is not None:
        pj = tmp_path / 'p.json'; pj.write_text(json.dumps(params, ensure_ascii=False))
    out, rec = tmp_path / 'f.png', tmp_path / 'f.json'
    run_tool('finish.py', src, src, pj, out, rec, *([f'--genre={genre}'] if genre else []))
    return src, out, json.loads(rec.read_text())


@pytest.mark.parametrize('name', list(CASES))
def test_every_move_shows_and_nothing_breaks(tmp_path, name):
    src, out, r = finish(tmp_path, name, genre=CASES[name])
    assert r['route'] == 'no_g'   # the original passed as G: its own N route, no look transfer of the photo onto itself
    a = next(x for x in r['attempts'] if x['name'] == r['delivered'])
    assert not a['problems'] and not a['strength_problems'], a
    assert a['improve']['verdict'] == 'VISIBLE', a['improve']
    assert all(not m['halo_found'] for m in a['improve']['moves'])
    diff = float(np.abs(load(out) - load(src)).mean() * 255)
    assert diff > MIN_DIFF[name], diff


def test_an_invisible_move_is_strengthened(tmp_path):
    p = json.loads((BRIEFS / '07_lake_frame.json').read_text())
    p['moves'] = [dict(p['moves'][2], clarity=0.08)]   # the water move, written too lightly to see
    _, _, r = finish(tmp_path, '07_lake_frame', p)
    imp = r['attempts'][0]['improve']
    assert imp['strengthened'] and imp['verdict'] == 'VISIBLE', imp
    assert r['attempts'][0]['params']['moves'][0]['clarity'] > 0.08


def test_a_halo_in_the_sky_is_found_and_moved_onto_the_building(tmp_path):
    """The first gate brief lifted an ellipse around the pavilion: a warm ring in the smooth sky that the physics checks
    did not catch. The halo check finds it and the move is put on structure only."""
    p = json.loads((BRIEFS / '09_gate_sunset.json').read_text())
    mv = p['moves'][1]; mv.pop('on_structure'); mv.update({'look': 'light+', 'lift': 3, 'sat': 1.2})
    _, _, r = finish(tmp_path, '09_gate_sunset', p)
    a = r['attempts'][0]
    assert a['improve']['strengthened'][0].get('halo_fix') == [1], a['improve']
    assert r['attempts'][0]['params']['moves'][1].get('on_structure') is True
    assert not a['problems'], a


def test_a_brief_without_moves_is_reported(tmp_path):
    src = REAL / '07_lake_frame.jpg'
    pj = tmp_path / 'p.json'; pj.write_text('{"vibrance": 0.1}')
    r = json.loads(run_tool('improve_check.py', src, src, pj).stdout)
    assert r['verdict'].startswith('NO_MOVES')
    run_tool('finish.py', src, src, pj, tmp_path / 'f.png', tmp_path / 'f.json')
    assert json.loads((tmp_path / 'f.json').read_text())['brief'].startswith('NO_MOVES')
