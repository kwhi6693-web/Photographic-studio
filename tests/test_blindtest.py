"""tools/blindtest: batch planning, page output, alignment and scoring - on synthetic pictures only (no real photos)."""
import json, re, sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

BT = Path(__file__).resolve().parent.parent / 'tools' / 'blindtest'
sys.path.insert(0, str(BT))
import bt_align  # noqa: E402
import make_set  # noqa: E402
import score  # noqa: E402


def scene(w=900, h=1200, seed=0):
    """A textured synthetic photo with plenty of corners for feature matching."""
    rng = np.random.default_rng(seed)
    img = np.zeros((h, w, 3), np.float32) + 0.35
    for _ in range(220):
        x0, y0 = rng.integers(0, w - 40), rng.integers(0, h - 40)
        x1, y1 = x0 + rng.integers(10, 140), y0 + rng.integers(10, 140)
        img[y0:y1, x0:x1] = rng.random(3) * 0.9 + 0.05
    img += rng.normal(0, 0.01, img.shape).astype(np.float32)
    return np.clip(img, 0, 1)


def save(arr, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    bt_align.to_image(arr).save(path, quality=95)


def make_data(tmp, n=5, shift=False):
    for i in range(n):
        base = scene(seed=i)
        cand = np.clip(base * 1.15, 0, 1)                    # brighter version
        if shift:
            cand = cand[40:-30, 25:-35]                      # and a slightly different frame
        d = tmp / 'photos' / f'p{i}'
        save(base, d / 'original.jpg')
        save(base * 0.9, d / 'v1.6.3.jpg')
        save(cand, d / 'cand.jpg')
    return tmp


# ---------- planning ----------

@pytest.mark.parametrize('n,sizes', [(14, [4, 4, 3, 3]), (12, [4, 4, 4]), (3, [3]), (1, [1])])
def test_plan_batches_sizes(n, sizes):
    import random
    b = make_set.plan_batches([f'x{i}' for i in range(n)], 10, random.Random(0))
    assert [len(x) for x in b] == sizes
    assert sorted(sum(b, [])) == sorted(f'x{i}' for i in range(n))


@pytest.mark.parametrize('photos,gap', [(['a', 'b', 'c', 'd'], 4), (['a', 'b', 'c'], 3), (['a', 'b'], 3), (['a'], 3)])
def test_order_batch_rules(photos, gap):
    import random
    items, g = make_set.order_batch(photos, random.Random(1))
    assert g == gap
    assert items[0][1] == 'pair'
    assert sum(1 for x in items if x[1] != 'pair') == 2
    for p in photos:
        pos = [i for i, x in enumerate(items) if x[0] == p and x[1] == 'pair']
        assert len(pos) == 2 and pos[1] - pos[0] >= gap
        swaps = [x[2] for x in items if x[0] == p and x[1] == 'pair']
        assert swaps[0] != swaps[1]                          # the two questions show opposite sides


# ---------- run output ----------

def test_make_set_writes_blind_pages(tmp_path):
    data = make_data(tmp_path, n=5)
    out = make_set.main(['--data', str(data), '--candidate', 'cand', '--baseline', 'v1.6.3', '--seed', '3',
                         '--out', str(tmp_path / 'run'), '--inline'])
    key = json.loads((out / 'key.json').read_text(encoding='utf-8'))
    assert [len(b['photos']) for b in key['batches']] == [3, 2]
    for b in key['batches']:
        page = (out / f"batch{b['batch']}" / 'page' / 'index.html').read_text(encoding='utf-8')
        assert 'cand' not in page and 'v1.6.3' not in page and 'p0' not in page   # nothing gives the answer away
        names = [p.name for p in (out / f"batch{b['batch']}" / 'page' / 'img').iterdir()]
        assert all(re.fullmatch(r'[0-9a-f]{8}\.jpg', n) for n in names)
        assert len(names) == 2 * len(b['photos'])            # each picture stored once
        inline = (out / f"batch{b['batch']}" / f"batch{b['batch']}_inline.html").read_text(encoding='utf-8')
        assert 'data:image/jpeg;base64,' in inline
        assert sum(q['kind'] == 'sentinel' for q in b['questions']) == 2


def test_inline_pictures_are_capped(tmp_path):
    d = tmp_path / 'photos' / 'big'
    save(scene(2400, 3200, 7), d / 'v1.6.3.jpg')
    save(scene(2400, 3200, 7), d / 'cand.jpg')
    out = make_set.main(['--data', str(tmp_path), '--candidate', 'cand', '--baseline', 'v1.6.3', '--seed', '1',
                         '--out', str(tmp_path / 'run'), '--inline', '--long-edge', '4000'])
    html = (out / 'batch1' / 'batch1_inline.html').read_text(encoding='utf-8')
    import base64, io
    uri = re.search(r'data:image/jpeg;base64,([A-Za-z0-9+/=]+)', html).group(1)
    assert max(Image.open(io.BytesIO(base64.b64decode(uri))).size) <= make_set.INLINE_LONG_EDGE


def test_missing_versions_are_skipped(tmp_path):
    data = make_data(tmp_path, n=2)
    save(scene(), tmp_path / 'photos' / 'only_original' / 'original.jpg')
    out = make_set.main(['--data', str(data), '--candidate', 'cand', '--baseline', 'v1.6.3', '--seed', '1',
                         '--out', str(tmp_path / 'run')])
    key = json.loads((out / 'key.json').read_text(encoding='utf-8'))
    assert 'only_original' in key['skipped'] and key['photos'] == ['p0', 'p1']


def test_full_mode_uses_the_originals_aspect(tmp_path):
    d = tmp_path / 'photos' / 'c'
    save(scene(900, 1200, 2), d / 'original.jpg')
    save(scene(900, 1200, 2)[100:1000], d / 'v1.6.3.jpg')     # a cropped baseline
    save(scene(900, 1200, 2), d / 'cand.jpg')
    out = make_set.main(['--data', str(tmp_path), '--candidate', 'cand', '--baseline', 'v1.6.3', '--seed', '1',
                         '--mode', 'full', '--out', str(tmp_path / 'run')])
    page = (out / 'batch1' / 'page' / 'index.html').read_text(encoding='utf-8')
    assert '"900 / 1200"' in page


# ---------- alignment ----------

def test_tone_mode_without_opencv_needs_the_same_frame(monkeypatch):
    monkeypatch.setattr(bt_align, 'cv2', None)
    a = scene(600, 800, 1)
    _, _, info = bt_align.same_frame(a, a.copy(), 'tone')
    assert 'no OpenCV' in info['method']
    with pytest.raises(bt_align.AlignError):
        bt_align.same_frame(a, a[50:-20, 10:-60], 'tone')


@pytest.mark.skipif(bt_align.cv2 is None, reason='needs OpenCV')
def test_tone_mode_aligns_a_different_frame():
    base = scene(900, 1200, 4)
    cand = np.clip(base[40:-30, 25:-35] * 1.1, 0, 1)
    a, b, info = bt_align.same_frame(base, cand, 'tone')
    assert a.shape == b.shape and info['share'] > 0.85
    diff = np.abs(a * 1.1 - b)[20:-20, 20:-20]
    assert np.median(diff) < 0.03                            # the warped picture lands on the reference


# ---------- scoring ----------

def key_for(photos):
    qs, n = [], 0
    for p in photos:
        for img1, img2 in (('cand', 'base'), ('base', 'cand')):
            n += 1
            qs.append({'q': f'1-{n:02d}', 'photo': p, 'kind': 'pair', 'img1': img1, 'img2': img2})
    for v in ('cand', 'base'):
        n += 1
        qs.append({'q': f'1-{n:02d}', 'photo': photos[0], 'kind': 'sentinel', 'img1': v, 'img2': v})
    return {'candidate': 'cand', 'baseline': 'base', 'mode': 'tone', 'batches': [{'batch': 1, 'photos': photos, 'questions': qs}]}


def answer(key, prefs, flags=None, sentinel='平'):
    lines = []
    for q in key['batches'][0]['questions']:
        if q['kind'] == 'sentinel':
            lines.append(f"{q['q']} {sentinel} 一致")
            continue
        want = prefs[q['photo']]
        if want == 'tie':
            lines.append(f"{q['q']} 平 -")
            continue
        pick = '1' if q['img1'] == want else '2'
        lines.append(f"{q['q']} {pick} {(flags or {}).get(q['photo'], '都能发')} 词")
    return score.parse('\n'.join(lines))


def test_gate_passes_on_a_clean_net_win():
    k = key_for(['a', 'b', 'c'])
    r = score.score(k, answer(k, {'a': 'cand', 'b': 'cand', 'c': 'base'}))
    assert r['totals'] == {'candidate_wins': 2, 'baseline_wins': 1, 'ties': 0}
    assert r['gate'] == 'pass' and not r['regressions']


def test_regression_blocks_the_gate():
    k = key_for(['a', 'b', 'c'])
    r = score.score(k, answer(k, {'a': 'cand', 'b': 'cand', 'c': 'base'}, flags={'c': '不想发'}))
    assert r['regressions'] == ['c'] and r['gate'] == 'fail'


def test_failed_sentinel_voids_the_batch():
    k = key_for(['a', 'b'])
    r = score.score(k, answer(k, {'a': 'cand', 'b': 'cand'}, sentinel='1'))
    assert r['batches'][0]['status'] == 'void' and r['gate'] == 'incomplete' and not r['photos']


def test_split_answers_are_a_tie():
    k = key_for(['a', 'b'])
    ans = answer(k, {'a': 'cand', 'b': 'cand'})
    first_b = next(q['q'] for q in k['batches'][0]['questions'] if q['photo'] == 'b')
    ans[first_b]['choice'] = '1' if ans[first_b]['choice'] == '2' else '2'
    r = score.score(k, ans)
    assert r['photos']['b']['verdict'] == 'tie (split)' and r['totals']['ties'] == 1


def test_parse_accepts_the_page_and_long_forms():
    a = score.parse('noise\n1-01 2 都能发 清透\n1-02 1 差的这张不想发 假\n1-03 平 一致\n1-04 2 两张都能发\n')
    assert a['1-01'] == {'choice': '2', 'usable': True, 'word': '清透'}
    assert a['1-02']['usable'] is False and a['1-03']['usable'] is None and a['1-04']['usable'] is True


def test_missing_answers_are_incomplete():
    k = key_for(['a', 'b'])
    ans = answer(k, {'a': 'cand', 'b': 'cand'})
    ans.pop('1-01')
    r = score.score(k, ans)
    assert r['batches'][0]['status'] == 'incomplete' and r['gate'] == 'incomplete'
