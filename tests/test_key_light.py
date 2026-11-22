"""v1.3.0 key light (grade.py key_light): the subject takes the light and the surroundings fall off; the size comes from
the original's light (directional about 7 L*, a flat grey-sky day about 4), a plain sky is never changed, and
physics_check.py's sky_glow catches light spilled onto a plain sky around a subject."""
import json
from pathlib import Path
import numpy as np
from PIL import Image
from conftest import run_tool, load, L

ROOT = Path(__file__).resolve().parents[1]
OPT = ROOT / 'photographic-studio' / 'optional'


def save(a, p):
    Image.fromarray(np.uint8(np.clip(np.rint(a * 255), 0, 255))).save(p)
    return p


def textured(h, w, seed, base, amp):
    rng = np.random.default_rng(seed)
    Y, X = np.mgrid[0:h, 0:w] / np.array([h, w])[:, None, None]
    t = base + amp * np.sin(X * 90) * np.sin(Y * 70) + 0.04 * rng.standard_normal((h, w))
    return t, Y, X


def grey_sky_scene(h=600, w=800):
    land, Y, X = textured(h, w, 3, 0.32, 0.12)
    img = np.repeat(land[..., None], 3, -1) * np.array([0.85, 1.0, 0.8])
    sky = Y < 0.45
    img[sky] = 0.86 - 0.04 * Y[sky, None]                             # flat grey overcast sky, a little lighter low down
    tower = (np.abs(X - 0.5) < 0.06) & (Y > 0.25) & (Y < 0.6)
    img[tower] = 0.30 + 0.1 * np.sin(Y[tower, None] * 200)
    return np.clip(img, 0, 1), sky & ~tower, Y, X


def side_lit_room(h=600, w=800):
    land, Y, X = textured(h, w, 5, 0.18, 0.08)
    light = 0.10 + 0.45 * np.exp(-(((X - 0.6) / 0.25) ** 2 + ((Y - 0.55) / 0.3) ** 2))   # a window light from the right
    img = np.repeat((land + light)[..., None], 3, -1) * np.array([1.0, 0.9, 0.75])
    return np.clip(img, 0, 1), Y, X


def grade(tmp_path, img, params, name='x'):
    sp = save(img, tmp_path / f'{name}.png'); out = tmp_path / f'{name}_o.png'; pj = tmp_path / f'{name}.json'
    pj.write_text(json.dumps(params))
    p = run_tool('grade.py', sp, out, pj)
    assert p.returncode == 0, p.stderr
    return sp, out, json.loads(p.stdout)['params_used']['key_light']


def test_directional_light_gets_the_full_separation(tmp_path):
    img, Y, X = side_lit_room()
    sp, out, kl = grade(tmp_path, img, {'key_light': {'box': [0.45, 0.35, 0.75, 0.75], 'from': 'right'}})
    assert kl['mode'] == 'directional'
    gained = kl['subject_minus_surroundings_L']['after'] - kl['subject_minus_surroundings_L']['before']
    assert 5.5 <= gained <= 10.5, kl          # v1.4.0: directional target 9 (was 7)
    D = L(load(out)) - L(load(sp))
    assert D[(np.abs(X - 0.6) < 0.08) & (np.abs(Y - 0.55) < 0.08)].mean() > 1.5      # the subject comes up
    assert D[(X < 0.12) & (Y < 0.2)].mean() < -2.0                                   # a far corner falls off


def test_grey_sky_day_is_quieter_and_the_sky_is_untouched(tmp_path):
    img, sky, Y, X = grey_sky_scene()
    sp, out, kl = grade(tmp_path, img, {'key_light': {'box': [0.38, 0.2, 0.62, 0.7], 'from': 'front'}})
    assert kl['mode'] == 'diffuse' and kl['light_in_original']['grey_sky']
    gained = kl['subject_minus_surroundings_L']['after'] - kl['subject_minus_surroundings_L']['before']
    assert 2.0 <= gained <= 5.5, kl
    assert kl['lift_L'] < kl['falloff_L']                    # mostly the surroundings recede, no spotlight
    D = L(load(out)) - L(load(sp))
    core = sky & (Y < 0.4)
    assert np.abs(D[core]).max() < 0.6                       # not one sky pixel lifted or darkened
    ph = json.loads(run_tool('physics_check.py', sp, out).stdout)
    assert ph['checks']['sky_glow']['ok'] is True


def test_the_brief_can_only_make_it_quieter(tmp_path):
    img, Y, X = side_lit_room()
    _, _, full = grade(tmp_path, img, {'key_light': {'box': [0.45, 0.35, 0.75, 0.75]}}, 'a')
    _, _, quiet = grade(tmp_path, img, {'key_light': {'box': [0.45, 0.35, 0.75, 0.75], 'light': 'diffuse'}}, 'b')
    _, _, half = grade(tmp_path, img, {'key_light': {'box': [0.45, 0.35, 0.75, 0.75], 'strength': 0.5}}, 'c')
    g = lambda k: k['subject_minus_surroundings_L']['after'] - k['subject_minus_surroundings_L']['before']
    assert quiet['mode'] == 'diffuse' and g(quiet) < g(full) and g(half) < g(full)
    img2, sky, _, _ = grey_sky_scene()
    _, _, forced = grade(tmp_path, img2, {'key_light': {'box': [0.38, 0.2, 0.62, 0.7], 'light': 'directional'}}, 'd')
    assert forced['mode'] == 'diffuse'                       # a flat overcast light is not turned into a spotlight


def test_sky_glow_catches_light_spilled_onto_a_plain_sky(tmp_path):
    img, sky, Y, X = grey_sky_scene()
    glow = img.copy()
    e = np.exp(-(((X - 0.5) / 0.14) ** 2 + ((Y - 0.42) / 0.2) ** 2))  # the old ellipse lift that covered the sky
    glow = np.clip(glow + 0.07 * e[..., None], 0, 1)
    sp, gp = save(img, tmp_path / 's.png'), save(glow, tmp_path / 'g.png')
    ph = json.loads(run_tool('physics_check.py', sp, gp).stdout)
    assert ph['checks']['sky_glow']['ok'] is False, ph['checks']['sky_glow']
    smooth = np.clip(img - 0.04 * (1 - Y[..., None]) * sky[..., None], 0, 1)     # a sky deepened smoothly towards the top
    ph2 = json.loads(run_tool('physics_check.py', sp, save(smooth, tmp_path / 'm.png')).stdout)
    assert ph2['checks']['sky_glow']['ok'] is not False, ph2['checks']['sky_glow']


def test_safer_attempt_halves_but_keeps_the_key_light():
    import sys
    sys.path.insert(0, str(OPT))
    import finish
    q = finish.safer({'key_light': {'box': [0.3, 0.3, 0.6, 0.6]}, 'moves': [{'lift': 4}]})
    assert q['key_light']['strength'] == 0.5 and q['moves'][0]['lift'] == 2.0
