"""Settings, all from environment variables (or a .env file next to the engine). Nothing secret lives in code.

STUDIO_VISION     which provider reads the photo and writes the brief: openai | gemini | replay   (default openai)
STUDIO_IMAGE      which provider draws G:                               openai | gemini | replay | none (default openai)
OPENAI_API_KEY    key for openai          OPENAI_VISION_MODEL / OPENAI_IMAGE_MODEL  model ids (see defaults below)
GEMINI_API_KEY    key for gemini          GEMINI_VISION_MODEL / GEMINI_IMAGE_MODEL
STUDIO_REPLAY_DIR folder with original.*, g.png, params.json (replay provider: offline tests, no key)
STUDIO_TOOLS      path of photographic-studio/optional (default: the copy in this repository)
STUDIO_G_MAX      most G calls per photo (default 2)
STUDIO_PRICE_*    optional cost estimates in USD per call, e.g. STUDIO_PRICE_IMAGE=0.08 STUDIO_PRICE_VISION=0.01
"""
import os
from dataclasses import dataclass, field
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent
REPO = ENGINE.parent


def _load_dotenv():
    p = ENGINE / '.env'
    if not p.exists(): return
    for line in p.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line: continue
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


@dataclass
class Config:
    vision: str = 'openai'
    image: str = 'openai'
    openai_key: str = ''
    openai_vision_model: str = 'gpt-5.1'           # any OpenAI model that reads images and returns JSON
    openai_image_model: str = 'gpt-image-2.5-sunburst'
    gemini_key: str = ''
    gemini_vision_model: str = 'gemini-3-flash'
    gemini_image_model: str = 'gemini-nano-banana-2.1'
    replay_dir: str = ''
    tools: Path = field(default_factory=lambda: REPO / 'photographic-studio' / 'optional')
    g_max: int = 2
    price_image: float = 0.0
    price_vision: float = 0.0

    @classmethod
    def from_env(cls, **override):
        _load_dotenv()
        e = os.environ.get
        c = cls(vision=e('STUDIO_VISION', 'openai'), image=e('STUDIO_IMAGE', 'openai'),
                openai_key=e('OPENAI_API_KEY', ''), gemini_key=e('GEMINI_API_KEY', ''),
                replay_dir=e('STUDIO_REPLAY_DIR', ''), g_max=int(e('STUDIO_G_MAX', '2')),
                price_image=float(e('STUDIO_PRICE_IMAGE', '0') or 0), price_vision=float(e('STUDIO_PRICE_VISION', '0') or 0))
        for k, env in (('openai_vision_model', 'OPENAI_VISION_MODEL'), ('openai_image_model', 'OPENAI_IMAGE_MODEL'),
                       ('gemini_vision_model', 'GEMINI_VISION_MODEL'), ('gemini_image_model', 'GEMINI_IMAGE_MODEL')):
            if e(env): setattr(c, k, e(env))
        if e('STUDIO_TOOLS'): c.tools = Path(e('STUDIO_TOOLS'))
        for k, v in override.items(): setattr(c, k, v)
        return c
