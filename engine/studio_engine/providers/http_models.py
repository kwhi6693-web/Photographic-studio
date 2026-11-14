"""Network providers: OpenAI and Google Gemini, over plain HTTPS (requests). Untested against the live APIs until a key is
configured: run `python -m studio_engine.cli selftest` first. Request shapes follow the providers' public REST docs; if a
provider changes them, this is the only file to touch."""
from __future__ import annotations

import base64
import io
import json
import time
from pathlib import Path

from PIL import Image

from ..config import ProviderConfig
from ..prompts import BRIEF_SCHEMA, BRIEF_SYSTEM
from .base import ImageEditor, NotConfigured, ProviderError, Usage, VisionModel


def _need(cfg: ProviderConfig, what: str):
    if not cfg.api_key:
        raise NotConfigured(f'{cfg.name} {what}: no API key. Set {"OPENAI_API_KEY" if cfg.name == "openai" else "GEMINI_API_KEY"} '
                            f'or fill engine/config.toml.')
    if not cfg.model:
        raise NotConfigured(f'{cfg.name} {what}: no model name in engine/config.toml.')


def jpeg_bytes(path: str, long_edge: int = 1536, quality: int = 92) -> bytes:
    im = Image.open(path).convert('RGB')
    s = long_edge / max(im.size)
    if s < 1:
        im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    b = io.BytesIO(); im.save(b, 'JPEG', quality=quality)
    return b.getvalue()


def _post(url, timeout, **kw):
    import requests
    t = time.time()
    for attempt in range(2):   # one retry on transient errors
        try:
            r = requests.post(url, timeout=timeout, **kw)
        except requests.RequestException as e:
            if attempt: raise ProviderError(f'network error: {e}')
            time.sleep(2); continue
        if r.status_code in (429, 500, 502, 503, 504) and not attempt:
            time.sleep(3); continue
        if r.status_code >= 400:
            raise ProviderError(f'HTTP {r.status_code}: {r.text[:600]}')
        return r.json(), time.time() - t
    raise ProviderError('unreachable')


class OpenAIVision(VisionModel):
    def __init__(self, cfg: ProviderConfig, timeout: int):
        self.cfg, self.timeout, self.usage = cfg, timeout, Usage()

    def brief(self, image_path, user_text):
        _need(self.cfg, 'vision')
        b64 = base64.b64encode(jpeg_bytes(image_path)).decode()
        body = {'model': self.cfg.model,
                'input': [{'role': 'system', 'content': [{'type': 'input_text', 'text': BRIEF_SYSTEM}]},
                          {'role': 'user', 'content': [{'type': 'input_text', 'text': user_text},
                                                       {'type': 'input_image', 'image_url': f'data:image/jpeg;base64,{b64}'}]}],
                'text': {'format': {'type': 'json_schema', 'name': 'brief', 'schema': BRIEF_SCHEMA, 'strict': True}}}
        url = (self.cfg.base_url or 'https://api.openai.com') + '/v1/responses'
        data, dt = _post(url, self.timeout, headers={'Authorization': f'Bearer {self.cfg.api_key}'}, json=body)
        text = ''.join(c.get('text', '') for o in data.get('output', []) if o.get('type') == 'message'
                       for c in o.get('content', []) if c.get('type') in ('output_text', 'text'))
        self.usage.calls += 1; self.usage.seconds += dt; self.usage.cost_usd += self.cfg.price_per_call_usd
        self.usage.detail.append({'usage': data.get('usage')})
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            raise ProviderError(f'brief is not JSON: {text[:300]}')


class OpenAIEditor(ImageEditor):
    def __init__(self, cfg: ProviderConfig, timeout: int):
        self.cfg, self.timeout, self.usage = cfg, timeout, Usage()

    def edit(self, image_path, prompt, out_path):
        _need(self.cfg, 'editor')
        files = {'image': ('source.jpg', jpeg_bytes(image_path), 'image/jpeg')}
        form = {'model': self.cfg.model, 'prompt': prompt, 'n': '1'}
        for k in ('size', 'quality', 'input_fidelity'):
            if self.cfg.extra.get(k): form[k] = str(self.cfg.extra[k])
        url = (self.cfg.base_url or 'https://api.openai.com') + '/v1/images/edits'
        data, dt = _post(url, self.timeout, headers={'Authorization': f'Bearer {self.cfg.api_key}'}, data=form, files=files)
        try:
            raw = base64.b64decode(data['data'][0]['b64_json'])
        except (KeyError, IndexError, TypeError):
            raise ProviderError(f'no image in response: {str(data)[:300]}')
        Image.open(io.BytesIO(raw)).convert('RGB').save(out_path)
        self.usage.calls += 1; self.usage.seconds += dt; self.usage.cost_usd += self.cfg.price_per_call_usd
        self.usage.detail.append({'usage': data.get('usage')})
        return out_path


def _gemini_schema(s):
    if isinstance(s, dict):
        return {k: _gemini_schema(v) for k, v in s.items() if k not in ('additionalProperties', 'description')}
    return s


class _Gemini:
    def _call(self, parts, gen_cfg):
        _need(self.cfg, 'gemini')
        url = (self.cfg.base_url or 'https://generativelanguage.googleapis.com') + f'/v1beta/models/{self.cfg.model}:generateContent'
        body = {'contents': [{'role': 'user', 'parts': parts}], 'generationConfig': gen_cfg}
        data, dt = _post(url, self.timeout, headers={'x-goog-api-key': self.cfg.api_key}, json=body)
        self.usage.calls += 1; self.usage.seconds += dt; self.usage.cost_usd += self.cfg.price_per_call_usd
        self.usage.detail.append({'usage': data.get('usageMetadata')})
        try:
            return data['candidates'][0]['content']['parts']
        except (KeyError, IndexError):
            raise ProviderError(f'empty Gemini response: {str(data)[:300]}')


class GeminiVision(_Gemini, VisionModel):
    def __init__(self, cfg, timeout):
        self.cfg, self.timeout, self.usage = cfg, timeout, Usage()

    def brief(self, image_path, user_text):
        b64 = base64.b64encode(jpeg_bytes(image_path)).decode()
        parts = self._call([{'text': BRIEF_SYSTEM + '\n\n' + user_text}, {'inline_data': {'mime_type': 'image/jpeg', 'data': b64}}],
                           {'responseMimeType': 'application/json', 'responseSchema': _gemini_schema(BRIEF_SCHEMA)})
        text = ''.join(p.get('text', '') for p in parts)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            raise ProviderError(f'brief is not JSON: {text[:300]}')


class GeminiEditor(_Gemini, ImageEditor):
    def __init__(self, cfg, timeout):
        self.cfg, self.timeout, self.usage = cfg, timeout, Usage()

    def edit(self, image_path, prompt, out_path):
        b64 = base64.b64encode(jpeg_bytes(image_path)).decode()
        parts = self._call([{'text': prompt}, {'inline_data': {'mime_type': 'image/jpeg', 'data': b64}}],
                           {'responseModalities': ['IMAGE']})
        for p in parts:
            d = p.get('inlineData') or p.get('inline_data')
            if d and d.get('data'):
                Image.open(io.BytesIO(base64.b64decode(d['data']))).convert('RGB').save(out_path)
                return out_path
        raise ProviderError('Gemini returned no image')
