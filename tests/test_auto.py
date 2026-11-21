"""v1.2.7 automatic base adjustment (grade.py "auto"), its three boundaries (user 2026-11-20), and pipeline.py.

1. White balance only from the original's near-neutral areas; nothing when there are too few (foliage, night).
2. Tones open up (and the limits relax) only for a narrow land range or lifted blacks; a bright sky is kept.
3. No stacking on the G route; a normal photo's whites rise at most 2.5 L*.
"""
import json
import numpy as np
from PIL import Image
from pathlib import Path
from conftest import run_tool, load, L

REAL = Path(__file__).resolve().parent / "fixtures" / "real"

REALDIR = REAL


def save(a, p):
    Image.fromarray(np.uint8(np.clip(np.rint(a * 255), 0, 255))).save(p)
    return p


def grade(tmp_path, src, params, name='out'):
    pj = tmp_path / f'{name}.json'; pj.write_text(json.dumps(params)); out = tmp_path / f'{name}.png'
    p = run_tool('grade.py', src, out, pj)
    assert p.returncode == 0, p.stderr
    return out, json.loads(p.stdout)


def flat_city(seed=1):
    """A grey, veiled street: blacks lifted to ~L*40, whites at ~L*70, a slight cyan cast."""
    rng = np.random.default_rng(seed); h, w = 600, 900
    Y, X = np.mgrid[0:h, 0:w] / np.array([h, w])[:, None, None]
    img = (0.62 + 0.12 * (1 - Y))[..., None] * np.array([0.93, 1.0, 1.02])
    for i, (x0, x1, top) in enumerate([(0.05, 0.3, 0.35), (0.3, 0.55, 0.25), (0.55, 0.8, 0.4)]):
        m = (X >= x0) & (X < x1) & (Y > top)
        col = np.array([0.6, 0.6, 0.6]) * (0.35 + 0.1 * i + 0.05 * np.sin(X * 300) * np.sin(Y * 200))[..., None]
        img[m] = col[m]
    img = 0.3 + img * 0.5
    return np.clip(img + 0.01 * rng.standard_normal(img.shape), 0, 1)


def range_L(a):
    l = L(a); return float(np.percentile(l, 99) - np.percentile(l, 1))


def test_auto_opens_a_flat_photo(tmp_path):
    src = save(flat_city(), tmp_path / 'flat.png')
    out, rec = grade(tmp_path, src, {'auto': True})
    assert range_L(load(src)) < 35
    assert range_L(load(out)) > 60, rec['params_used']['auto']
    assert rec['measurements']['structure_corr'] > 0.98


def test_auto_leaves_night_and_museum_darkness_alone(tmp_path):
    for name in ('02_night_tower.png',):
        out, rec = grade(tmp_path, REALDIR / name, {'auto': True}, name[:-4])
        a = rec['params_used']['auto']
        assert 'night' in a.get('skipped', '') and 'removed_ab' not in a['wb']
        assert abs(rec['measurements']['L_mean_change']) < 0.5


def test_auto_white_balance_does_not_touch_foliage_or_warm_light(tmp_path):
    for name in ('04_willow_lake.jpg', '03_canal.jpg', '05_bronze_ox.png'):
        _, rec = grade(tmp_path, REALDIR / name, {'auto': True}, name.split('.')[0])
        wb = rec['params_used']['auto']['wb']
        if 'removed_ab' in wb:   # only a cool or green/magenta cast shared by dark and light greys may be removed
            assert abs(wb['removed_ab'][1]) <= 3 and wb['removed_ab'][1] <= 0.5, (name, wb)


def test_auto_corrects_a_cool_cast_found_in_the_greys(tmp_path):
    base = flat_city(); base = 0.05 + base * 0.95
    grey = np.repeat(base.mean(-1, keepdims=True), 3, -1)
    lo = 0.15 + (grey - grey.min()) / (grey.max() - grey.min()) * 0.8      # a full-range grey scene
    cast = np.clip(lo * np.array([0.95, 1.0, 1.06]), 0, 1)   # a mild cool cast: the greys stay near-neutral
    src = save(cast, tmp_path / 'cool.png')
    out, rec = grade(tmp_path, src, {'auto': True})
    wb = rec['params_used']['auto']['wb']
    assert 'removed_ab' in wb, wb
    b_in, b_out = float(np.median(load(src) @ [0, 0, 1] - load(src) @ [1, 0, 0])), float(np.median(load(out) @ [0, 0, 1] - load(out) @ [1, 0, 0]))
    assert abs(b_out) < abs(b_in)


def test_normal_photo_whites_rise_at_most_a_little(tmp_path):
    src = REALDIR / '03_canal.jpg'
    out, rec = grade(tmp_path, src, {'auto': True})
    p99 = lambda a: float(np.percentile(L(a), 99))
    assert p99(load(out)) - p99(load(src)) <= 3.0, rec['params_used']['auto']


def test_bright_sky_is_kept_while_grey_land_opens_up(tmp_path):
    """A bright overcast sky above veiled land: the land opens up, the sky is not pushed to white."""
    h, w = 600, 800
    Y, X = np.mgrid[0:h, 0:w] / np.array([h, w])[:, None, None]
    rng = np.random.default_rng(3)
    land = 0.42 + 0.18 * np.sin(X * 90) * np.sin(Y * 70) + 0.05 * rng.standard_normal((h, w))
    img = np.repeat(land[..., None], 3, -1) * np.array([0.9, 1.0, 0.85])
    sky = Y < 0.3 + 0.05 * np.sin(X * 20)
    img[sky] = 0.88 + 0.02 * Y[sky, None]
    src = save(np.clip(img, 0, 1), tmp_path / 'sky_land.png')
    out, rec = grade(tmp_path, src, {'auto': True})
    lv = rec['params_used']['auto']['levels']
    assert 'land_from' in lv, rec['params_used']['auto']
    Lo, Lf = L(load(src)), L(load(out))
    assert float(Lf[sky].mean()) <= float(Lo[sky].mean()) + 0.5
    assert np.mean(np.uint8(np.rint(load(out)[sky] * 255)) == 255) < 0.001
    land_m = ~sky & (Y > 0.45)
    assert float(np.percentile(Lf[land_m], 99) - np.percentile(Lf[land_m], 1)) > float(np.percentile(Lo[land_m], 99) - np.percentile(Lo[land_m], 1)) + 10


def test_auto_off_is_v126(tmp_path):
    src = REALDIR / '03_canal.jpg'
    a, _ = grade(tmp_path, src, {'contrast': 0.1}, 'a')
    b, _ = grade(tmp_path, src, {'contrast': 0.1, 'auto': False}, 'b')
    assert np.array_equal(load(a), load(b))


def test_pipeline_reframes_the_original_with_the_same_crop(tmp_path):
    src = REALDIR / '03_canal.jpg'
    pj = tmp_path / 'p.json'
    pj.write_text(json.dumps({'moves': [{'what': 'water', 'look': 'contrast+', 'shape': 'rect', 'box': [0, 0.6, 1, 1], 'clarity': 0.2}],
                              'reframe': {'box': [0.05, 0.05, 0.95, 0.95]}}))
    out = tmp_path / 'final.png'
    p = run_tool('pipeline.py', src, src, pj, out, '--no-g')
    assert p.returncode == 0, p.stderr
    rec = json.loads(p.stdout)
    assert rec['steps']['reframe']['original_reframed_same_way'] is True
    w0, h0 = Image.open(src).size; w1, h1 = Image.open(out).size
    assert abs(w1 - 0.9 * w0) <= 2 and abs(h1 - 0.9 * h0) <= 2
    assert rec['steps']['harmonize']['verdict'].startswith('DELIVER')
