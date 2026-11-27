"""v1.2.9: cvlite.py, the numpy + Pillow stand-in for OpenCV, and the no-OpenCV route.
With OpenCV installed, cvlite is compared with it; in any environment the alignment is checked on real G drafts and
a whole pipeline run is made with OpenCV blocked (as on a ChatGPT sandbox)."""
import json, os, subprocess, sys
from pathlib import Path
import numpy as np
import pytest
from conftest import LEGACY, TOOLS, load

sys.path.insert(0, str(TOOLS))
import cvlite as L
try:
    import cv2
except ImportError:
    cv2 = None
REALG = Path(__file__).resolve().parent / 'fixtures' / 'real_g'
need_cv2 = pytest.mark.skipif(cv2 is None or getattr(cv2, 'LITE', False), reason='needs real OpenCV to compare with')


@need_cv2
def test_cvlite_matches_opencv_on_the_calls_the_tools_make():
    rng = np.random.default_rng(0); x = rng.random((120, 160, 3)).astype(np.float32)
    d = lambda a, b: float(np.abs(a.astype(np.float64) - b.astype(np.float64)).mean())
    assert d(cv2.resize(x, (80, 60), interpolation=cv2.INTER_AREA), L.resize(x, (80, 60), L.INTER_AREA)) < 1e-4
    assert d(cv2.GaussianBlur(x, (0, 0), 3), L.GaussianBlur(x, (0, 0), 3)) < 1e-3
    assert d(cv2.blur(x[..., 0], (7, 7)), L.blur(x[..., 0], (7, 7))) < 1e-5
    m = (x[..., 0] > 0.8).astype(np.uint8); k = np.ones((5, 5), np.uint8)
    assert d(cv2.dilate(m, k), L.dilate(m, k)) == 0 and d(cv2.erode(x[..., 0], k), L.erode(x[..., 0], k)) == 0
    n1, _, s1, _ = cv2.connectedComponentsWithStats(m, 8); n2, _, s2, _ = L.connectedComponentsWithStats(m, 8)
    assert n1 == n2 and sorted(s1[1:, 4].tolist()) == sorted(s2[1:, 4].tolist())
    H = np.array([[1.02, 0.01, 3], [0.005, 0.99, -2], [1e-5, 2e-5, 1]])
    for fl in (cv2.INTER_LINEAR, cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP):
        a = cv2.warpPerspective(x, H, (160, 120), flags=fl, borderMode=cv2.BORDER_REPLICATE)
        b = L.warpPerspective(x, H, (160, 120), fl, L.BORDER_REPLICATE)
        assert d(a[6:-6, 6:-6], b[6:-6, 6:-6]) < 0.01
    s4 = np.float32([[3, 4], [150, 2], [158, 117], [1, 119]]); t4 = np.float32([[0, 0], [160, 0], [160, 120], [0, 120]])
    assert np.abs(cv2.getPerspectiveTransform(s4, t4) - L.getPerspectiveTransform(s4, t4)).max() < 1e-6
    assert np.abs(cv2.getRotationMatrix2D((80, 60), 3, 1.0) - L.getRotationMatrix2D((80, 60), 3, 1.0)).max() < 1e-9


@pytest.mark.parametrize('case', sorted(p.name for p in REALG.iterdir() if (p / 'g.png').exists())[:6])
def test_alignment_without_feature_matching_finds_the_real_g(case):
    src, g = load(REALG / case / 'original.jpeg'), load(REALG / case / 'g.png')
    H, ncc = L.register(src, g)
    assert ncc >= 0.40, ncc                                    # on the ORB scale: passes look_transfer's 60 inliers
    assert L.lite_inliers(ncc, 60) >= 60
    hs, ws = src.shape[:2]; hg, wg = g.shape[:2]
    c = H @ np.array([ws / 2, hs / 2, 1.0]); c = c[:2] / c[2]
    assert abs(c[0] - wg / 2) < 0.06 * wg and abs(c[1] - hg / 2) < 0.06 * hg   # same framing, centre to centre


def test_alignment_refuses_another_scene():
    cases = sorted(p for p in REALG.iterdir() if (p / 'g.png').exists())
    src, g = load(cases[0] / 'original.jpeg'), load(cases[-1] / 'g.png')
    _, ncc = L.register(src, g)
    assert L.lite_inliers(ncc, 60) < 60, ncc


def test_pipeline_runs_with_opencv_blocked(tmp_path):
    # v1.6.2: the v1.4 default route (pipeline.py without flags, texture_blend.py) lives in legacy/v1.4
    block = tmp_path / 'block'; block.mkdir()
    (block / 'cv2.py').write_text('raise ImportError("OpenCV blocked for this test")\n')
    env = {**os.environ, 'PYTHONPATH': str(block)}
    case = sorted(p for p in REALG.iterdir() if (p / 'g.png').exists())[0]
    sc = json.loads(subprocess.run([sys.executable, '-B', str(LEGACY / 'selfcheck.py')], capture_output=True, text=True, env=env).stdout)
    assert sc['modules']['cv2'] is None and sc['tools']['pipeline.py'] and not sc['tools']['texture_blend.py']
    out = tmp_path / 'final.png'
    p = subprocess.run([sys.executable, '-B', str(LEGACY / 'pipeline.py'), case / 'original.jpeg', case / 'g.png', case / 'params.json', out],
                       capture_output=True, text=True, env=env)
    assert p.returncode == 0, p.stderr
    rec = json.loads(p.stdout)
    assert out.exists() and rec['verdict'].startswith('DELIVER')
    assert not str(rec['steps']['finish']['delivered']).startswith('n_direct'), rec['steps']['finish']   # G was used
    t = subprocess.run([sys.executable, '-B', str(LEGACY / 'texture_blend.py'), case / 'original.jpeg', out, tmp_path / 't.png'],
                       capture_output=True, text=True, env=env)
    assert json.loads(t.stdout)['verdict'].startswith('SKIPPED_NO_OPENCV')
    assert np.array_equal(load(out), load(tmp_path / 't.png'))


def test_ghost_outline_from_a_redrawn_g_is_caught():
    """v1.2.9: b2_01's G redrew the folding screen off its place; the outline came through the light transfer as a
    ghost frame. physics_check.py's ghost_edges catches it (with or without OpenCV); good G drafts pass."""
    import tempfile
    from conftest import run_tool
    with tempfile.TemporaryDirectory() as td:
        res = {}
        for case in ('b2_01', 'b1_03', 'b2_07', 'b2_02'):
            d = REALG / case; lt = Path(td) / f'{case}.png'
            run_tool('look_transfer.py', next(d.glob('original.*')), d / 'g.png', lt)
            r = json.loads(run_tool('physics_check.py', next(d.glob('original.*')), lt).stdout)
            res[case] = r['checks']['ghost_edges']
        assert res['b2_01']['ok'] is False, res
        assert all(res[c]['ok'] for c in ('b1_03', 'b2_07', 'b2_02')), res
