"""Model providers. Each one does at most two things:

    read(photo_path, prompt) -> dict      the vision model's JSON answer (brief)
    edit(photo_path, prompt) -> bytes     the image model's edit of the photo (G), as PNG/JPEG bytes

Swap providers with STUDIO_VISION / STUDIO_IMAGE; add a new one by writing a class with these methods.
"""
from .base import ProviderError  # noqa: F401


def vision_provider(cfg):
    name = cfg.vision
    if name == 'openai':
        from .openai_provider import OpenAIProvider; return OpenAIProvider(cfg)
    if name == 'gemini':
        from .gemini_provider import GeminiProvider; return GeminiProvider(cfg)
    if name == 'replay':
        from .replay import ReplayProvider; return ReplayProvider(cfg)
    raise ValueError(f'unknown STUDIO_VISION={name}')


def image_provider(cfg):
    name = cfg.image
    if name == 'none': return None
    if name == 'openai':
        from .openai_provider import OpenAIProvider; return OpenAIProvider(cfg)
    if name == 'gemini':
        from .gemini_provider import GeminiProvider; return GeminiProvider(cfg)
    if name == 'replay':
        from .replay import ReplayProvider; return ReplayProvider(cfg)
    raise ValueError(f'unknown STUDIO_IMAGE={name}')
