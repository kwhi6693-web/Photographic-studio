"""Engine tests: offline (replay and fake providers), no key, no network."""
import io, json, sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

ENGINE = Path(__file__).resolve().parents[1]
REPO = ENGINE.parent
sys.path.insert(0, str(ENGINE))

from studio import prompts                      # noqa: E402
from studio.config import Config                # noqa: E402
from studio.pipeline import run                 # noqa: E402
from studio.providers import ProviderError      # noqa: E402

FIX = REPO / 'tests' / 'fixtures'


def cfg(**kw):
    c = Config(); c.vision = kw.pop('vision', 'replay'); c.image = kw.pop('image', 'replay')
    for k, v in kw.items(): setattr(c, k, v)
    return c


def test_replay_reproduces_the_recorded_chatgpt_route(tmp_path):
    rec = run(FIX / 'real_g' / 'b1_03' / 'original.jpeg', tmp_path / 'o', cfg())
    assert rec['result'] == 'DELIVERED'
    assert rec['route'] == 'default'                       # the route ChatGPT took on 2026-11-11 (tests/test_real_g.py)
    assert rec['final']['physics'] == 'PHYSICALLY_PLAUSIBLE'
    assert str(rec['final']['intensity']).startswith('IN_RANGE')
    for f in ('final.png', 'brief.json', 'params.json', 'settle.json', 'receipt.json', 'g1.png'):
        assert (tmp_path / 'o' / f).exists(), f


class Fake:
    """Vision says what we tell it; G returns the photo with the given darkening, call by call."""
    def __init__(self, brief, darken=()):
        self.brief, self.darken, self.prompts = brief, list(darken), []

    def read(self, photo, prompt): return dict(self.brief)

    def edit(self, photo, prompt):
        self.prompts.append(prompt)
        a = np.asarray(Image.open(photo).convert('RGB'), float) * (self.darken.pop(0) if self.darken else 1.0)
        buf = io.BytesIO(); Image.fromarray(np.uint8(np.clip(a, 0, 255))).save(buf, 'PNG'); return buf.getvalue()


def _patch(monkeypatch, fake):
    import studio.pipeline as P
    monkeypatch.setattr(P, 'vision_provider', lambda c: fake)
    monkeypatch.setattr(P, 'image_provider', lambda c: fake)


def test_portrait_is_refused_before_any_g(tmp_path, monkeypatch):
    fake = Fake({'is_portrait': True, 'genre': 'day', 'params': {}})
    _patch(monkeypatch, fake)
    rec = run(FIX / 'real' / '03_canal.jpg', tmp_path / 'o', cfg(vision='openai', image='openai'))
    assert rec['result'].startswith('REFUSED') and fake.prompts == []


def test_rejected_g_gets_one_corrected_retry(tmp_path, monkeypatch):
    """SKILL step 5 (v1.0.7): G darkens the scene -> finish delivers N direct -> one more G with a correction from the problems found."""
    fake = Fake({'is_portrait': False, 'genre': 'day', 'g_intent': 'x', 'params': {'clarity': 0.1}}, darken=(0.55, 1.0))
    _patch(monkeypatch, fake)
    rec = run(FIX / 'real' / '03_canal.jpg', tmp_path / 'o', cfg(vision='openai', image='openai'))
    assert rec['result'] == 'DELIVERED'
    assert rec['calls']['image'] == 2
    assert fake.prompts[1].startswith(fake.prompts[0]) and len(fake.prompts[1]) > len(fake.prompts[0])   # same intent + a correction
    assert 'Concentrate the light and colour on the main subject' in fake.prompts[1]


def test_brief_parameters_are_clamped_to_grade_ranges():
    p = prompts.clean_params({'clarity': 3, 'exposure_ev': -9, 'regions': [1], 'white_balance': {'temp': 5}, 'junk': 1})
    assert p == {'exposure_ev': -1.0, 'clarity': 0.6, 'white_balance': {'temp': 1.0}}


def test_missing_key_is_a_clear_error(tmp_path):
    from studio.providers.openai_provider import OpenAIProvider
    with pytest.raises(ProviderError, match='OPENAI_API_KEY'):
        OpenAIProvider(cfg(openai_key='')).read(FIX / 'real' / '03_canal.jpg', 'x')


def test_eval_writes_summary_and_sheets(tmp_path, monkeypatch):
    import studio.evaluate as E
    def fake_run(photo, out, c=None):
        out = Path(out); out.mkdir(parents=True, exist_ok=True)
        Image.open(photo).convert('RGB').save(out / 'final.png')
        return {'result': 'DELIVERED', 'route': 'default', 'seconds': 1.0, 'calls': {'image': 1, 'vision': 1}, 'final': {}}
    monkeypatch.setattr(E, 'run', fake_run)
    d = tmp_path / 'set'; d.mkdir()
    for n in ('a.jpg', 'b.jpg'): Image.new('RGB', (60, 40), (90, 120, 150)).save(d / n)
    s = E.evaluate(d, tmp_path / 'out', runs=2)
    assert s['photos'] == 2 and s['delivered'] == 4 and s['run_to_run_diff_max'] == 0
    assert (tmp_path / 'out' / 'sheets' / 'a.jpg').exists() and (tmp_path / 'out' / 'summary.md').exists()


def test_http_api_job_lifecycle(tmp_path, monkeypatch):
    pytest.importorskip('fastapi'); pytest.importorskip('httpx')
    monkeypatch.setenv('STUDIO_DATA', str(tmp_path / 'jobs'))
    import importlib, time
    import studio.server as S
    S = importlib.reload(S)
    def fake_run(photo, out, c=None):
        out = Path(out); out.mkdir(parents=True, exist_ok=True)
        Image.open(photo).convert('RGB').save(out / 'final.png')
        return {'result': 'DELIVERED', 'route': 'default', 'seconds': 0.1, 'calls': {'image': 1, 'vision': 1}, 'final': {}}
    monkeypatch.setattr(S, 'run', fake_run)
    from fastapi.testclient import TestClient
    c = TestClient(S.app)
    buf = io.BytesIO(); Image.new('RGB', (40, 30), (200, 100, 50)).save(buf, 'JPEG')
    jid = c.post('/jobs', files={'file': ('p.jpg', buf.getvalue(), 'image/jpeg')}).json()['id']
    for _ in range(50):
        st = c.get(f'/jobs/{jid}').json()['status']
        if st in ('done', 'failed'): break
        time.sleep(0.1)
    assert st == 'done'
    r = c.get(f'/jobs/{jid}/result'); assert r.status_code == 200 and r.content[:4] == b'\x89PNG'
    assert c.delete(f'/jobs/{jid}').json()['deleted'] and c.get(f'/jobs/{jid}').status_code == 404
