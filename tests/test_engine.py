"""The engine runs the whole pipeline without ChatGPT. Offline here: the replay provider answers from recorded real runs
(tests/fixtures/real_g), so the engine must reproduce the routes those runs took. Network providers are only checked
for 'not configured' behaviour: no key, no call."""
import json
import sys

import numpy as np
import pytest
from PIL import Image

from conftest import ROOT

sys.path.insert(0, str(ROOT / 'engine'))
from studio_engine import Studio, load_config  # noqa: E402
from studio_engine import prompts  # noqa: E402
from studio_engine.cli import selftest  # noqa: E402
from studio_engine.config import EngineConfig, ProviderConfig  # noqa: E402

REAL_G = ROOT / 'tests' / 'fixtures' / 'real_g'


def replay_cfg(name):
    cfg = EngineConfig()
    cfg.vision = ProviderConfig(name='replay'); cfg.editor = ProviderConfig(name='replay')
    cfg.replay_dir = str(REAL_G / name)
    return cfg


def original(name):
    return next((REAL_G / name).glob('original.*'))


@pytest.mark.parametrize('name,route', [('b1_01', 'default'), ('b2_06', 'museum_strength')])
def test_replay_reproduces_the_recorded_route(tmp_path, name, route):
    r = Studio(replay_cfg(name)).run(original(name), tmp_path / 'out')
    assert r.status == 'done', r.reason
    assert r.route == route
    assert (tmp_path / 'out' / 'final.png').exists()
    rec = json.loads((tmp_path / 'out' / 'receipt.json').read_text())
    assert rec['g_calls'] == 1 and [s['step'] for s in rec['steps']][:3] == ['measure', 'brief', 'g1']
    assert rec['final_physics'] and rec['final_intensity']


def test_missing_key_is_reported_not_called(tmp_path, monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    cfg = EngineConfig()
    cfg.vision = ProviderConfig(name='openai', model='any'); cfg.editor = ProviderConfig(name='openai', model='any')
    r = Studio(cfg).run(original('b1_01'), tmp_path / 'out')
    assert r.status == 'failed' and 'not configured' in r.reason and 'OPENAI_API_KEY' in r.reason
    rep = selftest(tmp_path / 'none.toml')
    assert 'NOT CONFIGURED' in rep['vision']['status'] and rep['tools_found']


def test_brief_is_clamped_and_portraits_stop():
    b = prompts.clamp_brief({'genre': 'portrait', 'params': {'exposure_ev': 3, 'clarity': -1}, 'g_intent': 'x'})
    assert b['portrait'] and b['params']['exposure_ev'] == 0.4 and b['params']['clarity'] == 0.0
    p = prompts.g_prompt({'g_intent': 'warm light on the facade'}, ['darkening_patch', 'sky'])
    assert 'Follow real light physics' in p and 'Do not darken the sky' in p


def test_eval_harness_writes_sheets_and_summary(tmp_path):
    from studio_engine.eval import evaluate
    sdir = tmp_path / 'set'; sdir.mkdir()
    Image.open(original('b1_01')).save(sdir / 'b1_01.jpg', quality=95)
    rows = evaluate(sdir, tmp_path / 'res', runs=2, studio_factory=lambda p: Studio(replay_cfg('b1_01')))
    assert rows[0]['run1_status'] == 'done' and rows[0]['run_diff_max'] == 0.0   # same G -> identical output (deterministic)
    assert (tmp_path / 'res' / 'sheets' / 'b1_01.jpg').exists() and (tmp_path / 'res' / 'summary.md').exists()


def test_service_upload_poll_download_delete(tmp_path, monkeypatch):
    pytest.importorskip('fastapi'); pytest.importorskip('httpx')
    import time
    monkeypatch.setenv('STUDIO_DATA', str(tmp_path / 'jobs'))
    sys.path.insert(0, str(ROOT / 'engine'))
    import importlib
    import service.app as svc
    importlib.reload(svc)
    svc.studio_factory = lambda: Studio(replay_cfg('b1_01'))
    from fastapi.testclient import TestClient
    c = TestClient(svc.app)
    r = c.post('/jobs', files={'photo': ('p.jpg', original('b1_01').read_bytes(), 'image/jpeg')})
    jid = r.json()['id']
    for _ in range(600):
        s = c.get(f'/jobs/{jid}').json()
        if s['status'] in ('done', 'failed', 'unsupported'): break
        time.sleep(1)
    assert s['status'] == 'done', s
    assert c.get(f'/jobs/{jid}/result').status_code == 200
    assert c.delete(f'/jobs/{jid}').status_code == 200 and c.get(f'/jobs/{jid}').status_code == 404
    assert c.post('/jobs', files={'photo': ('p.gif', b'x', 'image/gif')}).status_code == 415
