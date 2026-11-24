import json

import numpy as np

from conftest import run_tool
from ps_common import lab_to_lin, load_rgb, save_png, srgb_to_lab, to_srgb


def test_identical_g_is_zero_and_output_is_deterministic(scene, tmp_path):
    source = scene('day')
    aligned, mask = tmp_path / 'aligned.png', tmp_path / 'mask.png'
    args = (source, source, source, '--names=source', f'--save-aligned={aligned},{mask}')
    one = run_tool('g_drift.py', *args)
    two = run_tool('g_drift.py', *args)
    assert one.returncode == two.returncode == 0, one.stderr + two.stderr
    assert one.stdout == two.stdout
    metrics = json.loads(one.stdout)['source']
    assert metrics['lowfreq_dE_to_G'] < 0.001
    assert metrics['look_captured'] is None
    assert aligned.is_file() and mask.is_file()


def test_g_with_five_more_lightness(scene, tmp_path):
    source = scene('day')
    lab = srgb_to_lab(load_rgb(source))
    lab[..., 0] += 5
    g, aligned, mask = (tmp_path / name for name in ('g.png', 'aligned.png', 'mask.png'))
    save_png(np.clip(to_srgb(lab_to_lin(lab)), 0, 1), g)
    process = run_tool('g_drift.py', source, g, source, '--names=source', f'--save-aligned={aligned},{mask}')
    assert process.returncode == 0, process.stderr
    metrics = json.loads(process.stdout)['source']
    assert abs(metrics['L_p50_minus_G'] + 5) < 0.5

    framed = run_tool('g_drift.py', '--aligned', aligned, mask, source, '--names=source',
                      '--source', source, '--inliers', metrics['registration_inliers'])
    assert framed.returncode == 0, framed.stderr
    round_trip = json.loads(framed.stdout)['source']
    assert round_trip['registration_inliers'] == metrics['registration_inliers']
    assert abs(round_trip['L_p50_minus_G'] - metrics['L_p50_minus_G']) < 0.1
    assert abs(round_trip['look_captured']) < 1e-6
