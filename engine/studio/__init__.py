"""Photographic Studio engine: the skill's pipeline as code, without ChatGPT.

    from studio import run
    receipt = run('photo.jpg', 'out/')

Judgement (reading the photo, the director brief) and the generative draft (G) come from providers chosen in
studio.config (environment variables). Every pixel operation is done by the skill's deterministic tools in
photographic-studio/optional/, unchanged.
"""
from .pipeline import run  # noqa: F401

__version__ = '0.1.0'
