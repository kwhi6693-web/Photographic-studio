"""Model interfaces. A provider is anything that can (a) read a photo into a brief and/or (b) edit a photo into a G draft."""
from __future__ import annotations

from dataclasses import dataclass, field


class NotConfigured(RuntimeError):
    """The provider has no API key or model name: fill engine/config.toml or set the environment variable."""


class ProviderError(RuntimeError):
    pass


@dataclass
class Usage:
    calls: int = 0
    seconds: float = 0.0
    cost_usd: float = 0.0
    detail: list = field(default_factory=list)


class VisionModel:
    usage: Usage

    def brief(self, image_path: str, user_text: str) -> dict:   # returns the raw brief dict (clamped by the pipeline)
        raise NotImplementedError


class ImageEditor:
    usage: Usage

    def edit(self, image_path: str, prompt: str, out_path: str) -> str:   # writes a PNG, returns its path
        raise NotImplementedError
