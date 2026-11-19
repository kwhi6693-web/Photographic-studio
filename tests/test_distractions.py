"""v1.2.6: measure.py lists bright whitish distractions; improve_check judges a subdue move by the share of its
excess brightness over the surroundings that is gone; grade.py applies a move to its 'also' boxes too."""
import json
import numpy as np
from PIL import Image
from conftest import ROOT, run_tool, load, L
from ps_common import save_png

RG = ROOT / 'tests' / 'fixtures' / 'real_g'


def test_measure_lists_the_white_stone_and_the_white_visitor():
    o = next((RG / 'c1_04').glob('original.*'))
    r = json.loads(run_tool('measure.py', o).stdout)
    cands = r['distractions']['candidates']
    inside = lambda c, x, y: c['box'][0] <= x <= c['box'][2] and c['box'][1] <= y <= c['box'][3]
    assert any(inside(c, 0.52, 0.585) for c in cands), [c['box'] for c in cands]     # white stone on the boat
    assert any(inside(c, 0.30, 0.38) for c in cands)                                  # white visitor, left
    assert all(c['L'] > 74 for c in cands)


def test_sunlit_leaves_are_not_distractions(tmp_path):
    rng = np.random.default_rng(1)
    img = np.zeros((600, 800, 3), np.float32); img[...] = (0.15, 0.25, 0.1)
    for _ in range(80):    # bright but green: sunlit leaves
        y, x = rng.integers(0, 580), rng.integers(0, 780); img[y:y + 12, x:x + 12] = (0.55, 0.85, 0.2)
    img[300:330, 400:420] = 0.97                                   # one white thing
    p = tmp_path / 's.png'; save_png(img, p)
    cands = json.loads(run_tool('measure.py', p).stdout)['distractions']['candidates']
    assert len(cands) == 1 and cands[0]['box'][0] <= 0.5 <= cands[0]['box'][2]


def test_also_boxes_get_the_same_edit(tmp_path):
    img = np.full((400, 400, 3), 0.5, np.float32); p = tmp_path / 'g.png'; save_png(img, p)
    pj = tmp_path / 'p.json'
    pj.write_text(json.dumps({'moves': [{'what': 'x', 'shape': 'rect', 'box': [0.1, 0.1, 0.2, 0.2], 'also': [[0.7, 0.7, 0.8, 0.8]], 'lift': -10, 'feather': 0.01}]}))
    out = tmp_path / 'o.png'; run_tool('grade.py', p, out, pj)
    Lo = L(load(out))
    assert Lo[60, 60] < Lo[200, 200] - 6 and Lo[300, 300] < Lo[200, 200] - 6


def test_subdue_is_measured_against_the_surroundings(tmp_path):
    img = np.full((500, 500, 3), 0.15, np.float32); img[200:260, 220:260] = 0.95
    o = tmp_path / 'o.png'; save_png(img, o)
    f = img.copy(); f[200:260, 220:260] = 0.70                         # about half the excess gone
    fp = tmp_path / 'f.png'; save_png(f, fp)
    pj = tmp_path / 'p.json'
    pj.write_text(json.dumps({'moves': [{'what': 'white shirt', 'look': 'light-', 'subdue': True, 'shape': 'rect', 'box': [0.42, 0.38, 0.54, 0.54], 'only_L': [60, 100], 'lift': -10, 'feather': 0.01}]}))
    r = json.loads(run_tool('improve_check.py', o, fp, pj).stdout)
    m = r['moves'][0]
    assert m['effect'] == 'subdue' and 0.25 < m['value'] < 0.6 and m['visible']
