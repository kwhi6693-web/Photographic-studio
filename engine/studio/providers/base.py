import base64, io, json, re
from pathlib import Path


class ProviderError(RuntimeError):
    pass


def image_b64(path, max_side=1536, fmt='JPEG'):
    """The photo as base64, long side at most max_side (models do not need more to read or to relight)."""
    from PIL import Image, ImageOps
    im = ImageOps.exif_transpose(Image.open(path)).convert('RGB')
    s = max_side / max(im.size)
    if s < 1: im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    buf = io.BytesIO(); im.save(buf, fmt, quality=92)
    return base64.b64encode(buf.getvalue()).decode(), im.size


def parse_json(text: str) -> dict:
    """First JSON object in a model's answer (tolerates ```json fences and // comments)."""
    m = re.search(r'\{.*\}', text, re.S)
    if not m: raise ProviderError('no JSON in the model answer: ' + text[:200])
    body = re.sub(r'//[^\n"]*\n', '\n', m.group(0))
    return json.loads(body)


def need_key(key, name):
    if not key: raise ProviderError(f'{name} is not set: put it in engine/.env (see .env.example) or the environment')
