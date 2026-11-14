"""OpenAI: chat completions for reading, the Images edit endpoint for G. Plain HTTP (requests), no SDK needed.
NOT YET VERIFIED AGAINST THE LIVE API (no key during development): check the first real call's response."""
import base64, time
from .base import ProviderError, image_b64, parse_json, need_key

API = 'https://api.openai.com/v1'


class OpenAIProvider:
    def __init__(self, cfg):
        self.cfg = cfg

    def _h(self):
        need_key(self.cfg.openai_key, 'OPENAI_API_KEY')
        return {'Authorization': f'Bearer {self.cfg.openai_key}'}

    def read(self, photo, prompt):
        import requests
        b64, _ = image_b64(photo)
        body = {'model': self.cfg.openai_vision_model, 'response_format': {'type': 'json_object'},
                'messages': [{'role': 'user', 'content': [
                    {'type': 'text', 'text': prompt},
                    {'type': 'image_url', 'image_url': {'url': f'data:image/jpeg;base64,{b64}'}}]}]}
        r = _post(requests, f'{API}/chat/completions', headers=self._h(), json=body, timeout=120)
        return parse_json(r.json()['choices'][0]['message']['content'])

    def edit(self, photo, prompt):
        import requests
        b64, size = image_b64(photo)
        w, h = size
        out_size = '1024x1536' if h > w * 1.15 else '1536x1024' if w > h * 1.15 else '1024x1024'
        files = {'image': ('source.jpg', base64.b64decode(b64), 'image/jpeg')}
        data = {'model': self.cfg.openai_image_model, 'prompt': prompt, 'size': out_size, 'quality': 'high', 'n': '1'}
        r = _post(requests, f'{API}/images/edits', headers=self._h(), files=files, data=data, timeout=300)
        item = r.json()['data'][0]
        if item.get('b64_json'): return base64.b64decode(item['b64_json'])
        if item.get('url'): return requests.get(item['url'], timeout=120).content
        raise ProviderError('image edit returned no image')


def _post(requests, url, retries=2, **kw):
    for i in range(retries + 1):
        r = requests.post(url, **kw)
        if r.status_code < 400: return r
        if r.status_code in (429, 500, 502, 503) and i < retries:
            time.sleep(5 * (i + 1)); continue
        raise ProviderError(f'{url} -> {r.status_code}: {r.text[:300]}')
