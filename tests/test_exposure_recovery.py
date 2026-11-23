import json

import numpy as np
from PIL import Image, PngImagePlugin

from conftest import run_tool
from exposure_recovery import recover
from ps_common import load_rgb, srgb_to_lab


def grayscale(rows, path):
    rgb = np.repeat(np.broadcast_to(np.uint8(rows), (64, len(rows)))[..., None], 3, axis=-1)
    Image.fromarray(rgb).save(path)
    return rgb


def test_g_reference_limit_and_exact_protection(tmp_path):
    src, current, g, out = (tmp_path / name for name in ('src.png', 'current.png', 'g.png', 'out.png'))
    rgb = grayscale(range(12, 241), current)
    grayscale(np.linspace(15, 245, 229), src)
    grayscale(np.linspace(135, 250, 229), g)
    light = srgb_to_lab(load_rgb(current))[..., 0]
    sky = light >= 80
    r = recover(src, current, out, ~sky, sky, g)
    assert r['reference'] == 'G' and r['triggered'] and r['applied'] and r['capped']
    assert 7.75 <= r['lift_L'] <= 8.0
    protected = (light <= r['protected_dark_L']) | sky
    pixels = np.array(Image.open(out))
    assert np.array_equal(pixels[protected], rgb[protected])
    assert np.all(np.diff(pixels[0, :, 0].astype(int)) >= 0)
    assert r['sky_median_change_L'] == 0


def test_untriggered_preserves_the_file(tmp_path):
    src, out = tmp_path / 'source.png', tmp_path / 'out.png'
    info = PngImagePlugin.PngInfo()
    info.add_text('test', 'this chunk must survive')
    Image.new('RGB', (64, 64), (90, 80, 70)).save(src, pnginfo=info)
    land = np.ones((64, 64), bool)
    r = recover(src, src, out, land, ~land)
    assert not r['triggered'] and r['reference'] == 'original'
    assert src.read_bytes() == out.read_bytes()


def test_pipeline_no_g_uses_original_and_reports_delivery_checks(tmp_path):
    # Resume the already-settled work to isolate the harmonize/recovery boundary.
    src, candidate, out, params, receipt = (
        tmp_path / name for name in ('src.png', 'dark.png', 'out.png', 'params.json', 'receipt.json'))
    grayscale(np.linspace(24, 201, 112), src)
    grayscale(np.linspace(10, 172, 112), candidate)
    params.write_text('{}')
    p = run_tool('pipeline.py', src, src, params, out, receipt, '--no-g', f'--settled={candidate}')
    assert p.returncode == 0, p.stderr
    data = json.loads(receipt.read_text())
    exp = data['steps']['exposure_recovery']
    assert exp['reference'] == 'original' and exp['applied']
    assert 0 < exp['lift_L'] <= 8
    assert exp['gates_before'] and data['gates'] == exp['gates_after']
    assert exp['physics_before']['failed_physics'] is not None
    assert exp['physics_after']['failed_physics'] is not None
