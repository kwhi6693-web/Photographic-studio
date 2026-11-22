"""Regression coverage for source-based sky and invented-light handling."""
import json

import numpy as np
import pytest

import finish
from grade import key_light
from look_transfer import glow_region, sky_delta, source_light_support
from ps_common import sky_surfaces


@pytest.mark.parametrize('problem, culprit', [
    ('sky_glow', 'moves[0]'),
    ('darkening_patch', 'key_light.falloff'),
])
def test_clean_transfer_survives_an_added_grade_problem(tmp_path, monkeypatch, problem, culprit):
    src, transferred = tmp_path / 'source', tmp_path / 'transferred'
    params = {'key_light': {'box': [.2, .5, .75, .9]}, 'anchor': True,
              'moves': [{'shape': 'gradient', 'lift': -4}, {'sat': 1.1}]}

    def render(lt, trial, pj, out, original, kj):
        assert lt == transferred and original == src
        out.write_text(json.dumps(trial))

    def physics(original, path):
        assert original == src
        if path == transferred:
            return [], 'pass'
        p = json.loads(path.read_text())
        safe = len(p['moves']) == 1 if culprit == 'moves[0]' else p['key_light'].get('falloff_scale') == 0
        return ([] if safe else [problem]), 'checked'

    monkeypatch.setattr(finish, 'render', render)
    monkeypatch.setattr(finish, 'physical_problems', physics)
    result, receipt = finish.rescue_grade(src, transferred, params, None, [problem], tmp_path, 0)
    assert result is not None
    assert receipt['transfer'] == []
    assert receipt['trials'][-1] == {'removed': [culprit], 'left': []}
    assert result[0]['anchor'] is True
    assert {'sat': 1.1} in result[0]['moves']


def test_unsafe_transfer_cannot_be_cleared_by_grade_attribution(tmp_path, monkeypatch):
    monkeypatch.setattr(finish, 'physical_problems', lambda *_: (['sky_glow'], 'fail'))
    result, receipt = finish.rescue_grade(None, None, {}, None, ['sky_glow'], tmp_path, 0)
    assert result is None
    assert receipt['transfer'] == ['sky_glow'] and receipt['trials'] == []


@pytest.mark.parametrize('b', [-24, 0])
def test_key_light_does_not_grade_sky_between_silhouettes(b):
    y, x = np.mgrid[:330, :440]
    sky = (y < 150) & ~((x % 41 < 8) & (y > 40))
    lab = np.zeros((330, 440, 3), dtype=np.float32)
    lab[..., 0] = 34 + 8 * np.sin(x / 11) * np.sin(y / 13)
    lab[sky, 0] = (62 if b else 84) + y[sky] / 120
    lab[sky, 2] = b
    original = lab[..., 0]
    mask = sky_surfaces(lab, gaps=True)
    assert mask[sky].all()
    result, _ = key_light({'box': [.3, .6, .7, .9], 'from': 'top'},
                          original, original, lab, None, *original.shape)
    assert np.array_equal(result[sky], original[sky])
    assert np.max(np.abs(result[~sky] - original[~sky])) > 1


@pytest.mark.parametrize('source_b, expected', [(-16, 'blue'), (-2, 'pale')])
def test_sky_trend_controls_clouds_and_overexposure_separately_from_blue(source_b, expected):
    y, x = np.mgrid[:180, :230]
    lab = np.zeros((180, 230, 3), dtype=np.float32)
    lab[..., 0] = 83
    lab[..., 2] = source_b
    sky = y < 120
    delta = np.zeros_like(lab)
    cloud = ((x - 135) ** 2 + (y - 50) ** 2) < 22 ** 2
    delta[..., 0] = -4 + y / 65 + 18 * cloud
    delta[..., 2] = -13 + y / 55 - 3 * cloud
    info = sky_delta(lab, delta, sky)
    assert info['source_sky'] == expected
    assert info['blotch_area_of_sky'] > .03
    assert delta[cloud, 0].max() < 3
    assert delta[sky, 0].max() < 4
    sky_colour = float(delta[sky, 2].mean())
    assert sky_colour < -9 if expected == 'blue' else -4.6 < sky_colour < -3.4


def test_bright_sky_trend_excludes_water_below_the_horizon():
    y, x = np.mgrid[:300, :400]
    lab = np.empty((300, 400, 3), dtype=np.float32)
    lab[..., 0] = 70 + 0.09 * y
    lab[..., 1] = -y / 25
    lab[..., 2] = -39 + y / 7
    water = y >= 148
    lab[water] = [54, -11, -16]
    mask = sky_surfaces(lab)
    assert mask[~water].mean() > 0.99
    assert not mask[water].any()


def test_dark_blue_sky_is_not_split_at_an_absolute_brightness():
    y, x = np.mgrid[:300, :400]
    lab = np.empty((300, 400, 3), dtype=np.float32)
    lab[..., 0] = 35 + x / 23 + y / 45
    lab[..., 1:] = [-1, -19]
    skyline = y >= 115 + 15 * np.sin(x / 24)
    lab[skyline] = [18, 0, -2]
    mask = sky_surfaces(lab)
    assert mask[~skyline].mean() > 0.99
    assert not mask[skyline].any()


def test_light_support_comes_from_original_pixels_without_genre():
    L = np.full((240, 320), 14, dtype=np.float32)
    tex = np.zeros_like(L)
    L[146:152, 65:72] = 88
    tex[128:170, 54:85] = 4
    support = source_light_support(L, tex)
    assert support[149, 68] == 1
    assert support[154, 72] > 0
    assert not support[:100].any()
    residual = np.zeros_like(L)
    residual[50:55, 140:147] = 3
    residual[52, 144] = 4
    assert glow_region(residual, support < .1) == {
        'box_xyxy': [140, 50, 147, 55], 'peak_xy': [144, 52], 'peak_L': 4.0}


def test_residual_glow_is_a_warning_unless_g_also_deleted_light():
    glow = 'G_GLOW_LEFT 3.03: visual review'
    assert finish.transfer_light_problems({'flags': [glow]}) == []
    assert finish.transfer_light_problems({'flags': [
        glow, 'G_LIGHT_REMOVAL_NOT_CARRIED 0.02: restored original light',
    ]}) == ['conflicting_light_artifacts']
