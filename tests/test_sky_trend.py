"""v1.2.8: on a plain bright sky only G's smooth gradient is carried over (no invented cloud blotches), the sky's
average deepening is held to 6.5 L*, and a grey sky is checked against -7 by intensity_check.py."""
import json
from pathlib import Path
import numpy as np
from PIL import Image
from conftest import run_tool, load, L

REAL = Path(__file__).resolve().parent / 'fixtures' / 'real'


def save(a, p):
    Image.fromarray(np.uint8(np.clip(np.rint(a * 255), 0, 255))).save(p)
    return p


def scene(h=600, w=800, seed=4):
    rng = np.random.default_rng(seed)
    Y, X = np.mgrid[0:h, 0:w] / np.array([h, w])[:, None, None]
    land = 0.35 + 0.2 * np.sin(X * 90) * np.sin(Y * 70) + 0.05 * rng.standard_normal((h, w))
    img = np.repeat(land[..., None], 3, -1) * np.array([0.85, 1.0, 0.8])
    sky = Y < 0.35 + 0.05 * np.sin(X * 15)
    img[sky] = 0.88
    return np.clip(img, 0, 1), sky, Y, X


def test_g_cloud_blotches_on_a_plain_sky_are_not_carried(tmp_path):
    src, sky, Y, X = scene()
    g = src.copy()
    blot = 0.10 * np.sin(X * 25) * np.sin(Y * 40)                       # cloud blotches G invents
    g[sky] = np.clip(g[sky] - 0.10 * (1 - Y[sky, None]) + blot[sky, None], 0, 1)   # plus a smooth deepening at the top
    g = np.clip(g * 1.03, 0, 1)
    sp, gp, out = save(src, tmp_path / 's.png'), save(g, tmp_path / 'g.png'), tmp_path / 'o.png'
    p = run_tool('look_transfer.py', sp, gp, out)
    assert p.returncode == 0, p.stderr
    rec = json.loads(p.stdout)
    st = rec['measurements']['sky_kept_to_smooth_gradient']
    assert st['blotch_area_of_sky'] > 0.3
    D = L(load(out)) - L(load(sp))
    core = sky & (Y < 0.25)
    rows = D[core].reshape(-1)
    assert float(np.std(D[core] - np.array([np.mean(D[r][core[r]]) if core[r].any() else 0 for r in range(D.shape[0])])[np.nonzero(core)[0]])) < 1.2
    assert float(rows.mean()) >= -7.0
    assert float(np.mean(D[Y < 0.08])) < float(np.mean(D[(Y > 0.2) & (Y < 0.28) & sky]))   # still deeper at the top


def test_grey_sky_is_checked_against_minus_seven(tmp_path):
    src, sky, Y, X = scene()
    dark = src.copy(); dark[sky] = np.clip(dark[sky] - 0.12, 0, 1)
    sp, dp = save(src, tmp_path / 's.png'), save(dark, tmp_path / 'd.png')
    p = run_tool('intensity_check.py', sp, dp)
    rec = json.loads(p.stdout)
    s = rec['checks']['sky_L_change']
    assert s['value'] is not None and s['range'][0] == -7.0 and s['ok'] is False
