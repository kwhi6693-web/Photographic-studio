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
    assert a['improve']['verdict'].startswith('VISIBLE'), a['improve']   # every move over the floor (BELOW_TARGET may follow)
    assert all(not m['halo_found'] for m in a['improve']['moves'])
    diff = float(np.abs(load(out) - load(src)).mean() * 255)
    assert diff > MIN_DIFF[name], diff


def test_an_invisible_move_is_strengthened(tmp_path):
    p = json.loads((BRIEFS / '07_lake_frame.json').read_text())
    p['moves'] = [dict(p['moves'][2], clarity=0.08)]   # the water move, written too lightly to see
    _, _, r = finish(tmp_path, '07_lake_frame', p)
    imp = r['attempts'][0]['improve']
    assert imp['strengthened'] and imp['verdict'].startswith('VISIBLE'), imp
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


def test_a_sky_band_halo_gets_a_softer_edge_not_on_structure(tmp_path):
    """v1.2.1: the agent's own 2026-11-15 gate brief put the sunset colour on a band across the whole frame. Its edges
    in the smooth sky made a halo; putting it on structure (v1.2.0) left the smooth sky unchanged. Now the band keeps
    its colour with a softer edge."""
    p = {'moves': [{'what': 'sunset band', 'look': 'colour+', 'shape': 'rect', 'box': [0, 0.23, 1, 0.64], 'sat': 1.26, 'lift': -3}]}
    _, _, r = finish(tmp_path, '09_gate_sunset', p)
    a = r['attempts'][0]
    mv = a['params']['moves'][0]
    assert not mv.get('on_structure') and mv.get('feather', 0) >= 0.3, mv
    assert not a['problems'], a


def test_a_small_photo_gets_no_more_than_02_clarity(tmp_path):
    """v1.2.1: the 797 px book at clarity 0.4 turned grainy; under 900 px every clarity is capped at 0.2."""
    p = {'moves': [{'what': 'paper and ink', 'look': 'contrast+', 'shape': 'rect', 'box': [0.1, 0.32, 0.87, 0.7], 'clarity': 0.4}]}
    _, _, r = finish(tmp_path, '08_book_showcase', p, genre='museum')
    assert r['low_resolution']['capped'] == [['moves[0].clarity', 0.4]]
    for a in r['attempts']:
        if 'params' in a:
            assert all(float(m.get('clarity', 0)) <= 0.2 for m in a['params']['moves'])


def test_a_cropped_final_is_not_measured(tmp_path):
    src = REAL / '09_gate_sunset.jpg'
    crop = tmp_path / 'c.png'; run_tool('reframe.py', src, crop, '--box', '0,0.12,1,0.97', '--allow-aspect-change')
    r = json.loads(run_tool('improve_check.py', src, crop, BRIEFS / '09_gate_sunset.json').stdout)
    assert r['verdict'].startswith('SKIPPED')


def test_look_transfer_keeps_the_originals_texture_where_g_redrew_it(tmp_path):
    """v1.2.2: the 2026-11-19 lake G redrew the water ripples. A per-pixel colour fit averaged crests and troughs and
    flattened the original's own ripples to x0.67 (G itself x1.06); the mapping now works at ~2 px and above."""
    from ps_common import srgb_to_lab, blur
    src = REAL / '07_lake_frame.jpg'; out = tmp_path / 'lt.png'
    run_tool('look_transfer.py', src, REAL / '07_lake_frame_g.png', out)
    Ls, Lo = srgb_to_lab(load(src))[..., 0], srgb_to_lab(load(out))[..., 0]
    w = slice(int(Ls.shape[0] * 0.72), Ls.shape[0])
    lc = lambda L: np.abs(L - blur(L, 8))[w].mean()
    assert lc(Lo) / lc(Ls) > 0.9


def test_g_route_keeps_gs_own_colour(tmp_path):
    """v1.2.2 (user chose plan A, 2026-11-19): on the G route the colour limit is G's own colour, at most x1.65."""
    src = REAL / '07_lake_frame.jpg'
    out, rec = tmp_path / 'f.png', tmp_path / 'f.json'
    run_tool('finish.py', src, REAL / '07_lake_frame_g.png', REAL / '07_lake_frame_gpt_params.json', out, rec)
    r = json.loads(rec.read_text())
    assert r['delivered'] == 'default' and 1.5 < r['g_chroma'] < 1.7, r
    st = tmp_path / 's.png'
    run_tool('settle.py', src, out, st, tmp_path / 's.json', f"--g-chroma={r['g_chroma']}")
    it = json.loads(run_tool('intensity_check.py', src, st).stdout)
    assert it['checks']['chroma_ratio']['value'] > 1.4   # not trimmed back to the day limit x1.30


def test_a_move_on_a_protected_sign_is_not_undone_by_its_protection(tmp_path):
    """v1.2.3: 2026-11-19 cafe - the brief protected the logo (keep, content) and also asked for more contrast on it.
    The keep step ran after the moves and undid the move (x1.00). Now: grade, keep, then moves."""
    src = REAL / '10_cafe_counter.jpg'
    out, rec = tmp_path / 'f.png', tmp_path / 'f.json'
    run_tool('finish.py', src, REAL / '10_cafe_counter_g.png', REAL / '10_cafe_counter_gpt_params.json', out, rec)
    r = json.loads(rec.read_text())
    a = next(x for x in r['attempts'] if x['name'] == r['delivered'])
    assert str(a.get('keep', '')).startswith('KEPT')
    logo = a['improve']['moves'][0]
    assert logo['visible'], logo
