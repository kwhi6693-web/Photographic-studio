"""Photographic Studio engine: the retouching pipeline as code (no ChatGPT agent needed).

    from studio_engine import load_config, Studio
    result = Studio(load_config()).run('photo.jpg', 'out/')
"""
from .config import load as load_config
from .pipeline import VERSION, Result, Studio

__all__ = ['Studio', 'Result', 'load_config', 'VERSION']
