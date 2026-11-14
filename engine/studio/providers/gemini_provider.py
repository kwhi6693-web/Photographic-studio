"""Google Gemini: generateContent for reading and for G (image in, image out). Plain HTTP (requests).
NOT YET VERIFIED AGAINST THE LIVE API (no key during development)."""
import base64
from .base import ProviderError, image_b64, parse_json, need_key
from .openai_provider import _post

API = 'https://generativelanguage.googleapis.com/v1beta/models'


class GeminiProvider:
    def __init__(self, cfg):
        self.cfg = cfg

    def _call(self, model, prompt, photo, json_out):
        import requests
        need_key(self.cfg.gemini_key, 'GEMINI_API_KEY')
        b64, _ = image_b64(photo)
        body = {'contents': [{'parts': [{'text': prompt}, {'inline_data': {'mime_type': 'image/jpeg', 'data': b64}}]}]}
        if json_out: body['generationConfig'] = {'responseMimeType': 'application/json'}
        r = _post(requests, f'{API}/{model}:generateContent', headers={'x-goog-api-key': self.cfg.gemini_key},
                  json=body, timeout=300)
        return r.json()['candidates'][0]['content']['parts']

    def read(self, photo, prompt):
        parts = self._call(self.cfg.gemini_vision_model, prompt, photo, True)
        return parse_json(''.join(p.get('text', '') for p in parts))

    def edit(self, photo, prompt):
        for p in self._call(self.cfg.gemini_image_model, prompt, photo, False):
            d = p.get('inline_data') or p.get('inlineData')
            if d and d.get('data'): return base64.b64decode(d['data'])
        raise ProviderError('Gemini returned no image')
