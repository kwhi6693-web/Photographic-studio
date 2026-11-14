"""Engine configuration: which models to call and with which keys.

Keys are never stored in the repository. They come from (first match wins):
  1. environment variables  OPENAI_API_KEY, GEMINI_API_KEY
  2. the file named by STUDIO_CONFIG, or engine/config.toml (git-ignored; copy config.example.toml)
An empty key means "not configured": the engine says so instead of calling the network.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = ENGINE_DIR.parent
DEFAULT_TOOLS = REPO_DIR / 'photographic-studio' / 'optional'


@dataclass
class ProviderConfig:
    name: str = ''            # 'openai' | 'gemini' | 'replay'
    model: str = ''
    api_key: str = ''
    base_url: str = ''
    price_per_call_usd: float = 0.0   # rough estimate for the cost report; the provider's bill is what counts
    extra: dict = field(default_factory=dict)


@dataclass
class EngineConfig:
    vision: ProviderConfig = field(default_factory=lambda: ProviderConfig(name='openai'))
    editor: ProviderConfig = field(default_factory=lambda: ProviderConfig(name='openai'))
    tools_dir: Path = DEFAULT_TOOLS
    work_size: int = 1536          # long edge the pipeline works at
    g_max_calls: int = 2
    timeout_s: int = 180
    replay_dir: str = ''           # for name == 'replay': a fixture folder with params.json, g.png, receipt.json


ENV_KEYS = {'openai': 'OPENAI_API_KEY', 'gemini': 'GEMINI_API_KEY'}


def _provider(d: dict, default_name: str) -> ProviderConfig:
    p = ProviderConfig(name=d.get('provider', default_name), model=d.get('model', ''),
                       api_key=d.get('api_key', ''), base_url=d.get('base_url', ''),
                       price_per_call_usd=float(d.get('price_per_call_usd', 0.0)),
                       extra={k: v for k, v in d.items() if k not in
                              ('provider', 'model', 'api_key', 'base_url', 'price_per_call_usd')})
    env = os.environ.get(ENV_KEYS.get(p.name, ''), '')
    if env:
        p.api_key = env
    return p


def load(path: str | os.PathLike | None = None) -> EngineConfig:
    path = Path(path or os.environ.get('STUDIO_CONFIG') or ENGINE_DIR / 'config.toml')
    data = tomllib.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    cfg = EngineConfig()
    cfg.vision = _provider(data.get('vision', {}), 'openai')
    cfg.editor = _provider(data.get('editor', {}), 'openai')
    eng = data.get('engine', {})
    if eng.get('tools_dir'):
        cfg.tools_dir = Path(eng['tools_dir'])
    cfg.work_size = int(eng.get('work_size', cfg.work_size))
    cfg.g_max_calls = int(eng.get('g_max_calls', cfg.g_max_calls))
    cfg.timeout_s = int(eng.get('timeout_s', cfg.timeout_s))
    cfg.replay_dir = eng.get('replay_dir', '')
    return cfg
