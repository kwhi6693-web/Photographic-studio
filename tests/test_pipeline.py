"""The promises SKILL.md makes about the default route, tested end to end through finish.py."""
import hashlib
import numpy as np
import pytest
import synth
from conftest import L, detail, load, run_tool

G = synth.good_edit


def sha(p):
    return hashlib.sha256(open(p, 'rb').read()).hexdigest()


def test_same_input_same_output(tmp_path, scene, finish):
    src = scene('day'); g = synth.save(G(synth.day()), tmp_path / 'g.png')
    a, _ = finish(src, g, {'contrast': 0.15, 'vibrance': 0.2}, tag='a')
    b, _ = finish(src, g, {'contrast': 0.15, 'vibrance': 0.2}, tag='b')
    assert sha(a) == sha(b)


def test_final_has_the_size_of_the_original(tmp_path, scene, finish):
    src = scene('day'); g = synth.save(G(synth.day()), tmp_path / 'g.png')
    out, _ = finish(src, g)
    assert load(out).shape == load(src).shape


def test_final_pixels_come_from_the_original_not_from_g(tmp_path, scene, finish):
    """G arrives with its texture wiped (the AI look). The final must still carry the original's fine detail."""
    src = scene('day'); g = synth.save(synth.smoothed_texture(G(synth.day())), tmp_path / 'g.png')
    out, _ = finish(src, g)
    s, o, gg = detail(load(src)), detail(load(out)), detail(load(g))
    m = np.abs(s) > 0.01
    assert np.corrcoef(s[m], o[m])[0, 1] > 0.98
    assert o.std() > 0.85 * s.std() > gg.std()


def test_an_edit_the_eye_cannot_see_is_never_a_clean_pass(scene, finish):
    for name in synth.SCENES:
        src = scene(name)
        _, rec = finish(src, src, {}, genre='museum' if name == 'museum' else None, tag=name)
        assert rec['verdict'] != 'DELIVER', name


def _dark_lift(src, other):
    dark = L(load(src)) < 8
    return float(np.percentile((L(load(other)) - L(load(src)))[dark], 99))


@pytest.mark.parametrize('name', ['night', 'museum'])
def test_light_g_invented_on_a_dark_background_is_mostly_blocked(tmp_path, scene, finish, name):
    src = scene(name); g = synth.save(synth.invented_spotlight(G(synth.SCENES[name]())), tmp_path / 'g.png')
    out, _ = finish(src, g, genre='museum' if name == 'museum' else None)
    assert _dark_lift(src, g) > 15                       # the defect is really there in G
    assert _dark_lift(src, out) < 0.4 * _dark_lift(src, g)


@pytest.mark.parametrize('name', ['night', 'museum'])
def test_invented_light_leaves_no_visible_trace(tmp_path, scene, finish, name):
    """Before v1.0.2 about 5.5 L* of the invented glow was delivered on black. 3 L* is a provisional line for
    'the eye cannot see it'; the user's eye decides, not this number."""
    src = scene(name); g = synth.save(synth.invented_spotlight(G(synth.SCENES[name]())), tmp_path / 'g.png')
    out, _ = finish(src, g, genre='museum' if name == 'museum' else None)
    assert _dark_lift(src, out) < 3


def test_light_g_removed_is_put_back(tmp_path, scene, finish):
    src = scene('night'); g = synth.save(synth.removed_light(synth.night()), tmp_path / 'g.png')
    out, _ = finish(src, g)
    top = lambda p: float(np.percentile(L(load(p)), 99.5))
    assert top(g) < top(src) - 30
    assert top(out) > top(src) - 2


def test_g_of_another_scene_is_refused(tmp_path, scene):
    src = scene('day'); g = scene('night')
    p = run_tool('look_transfer.py', src, g, tmp_path / 'o.png', tmp_path / 'o.json')
    assert p.returncode == 2 and not (tmp_path / 'o.png').exists()
