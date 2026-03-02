"""Local/Ollama model provider — auto-discovers and serves models from tensor-ide/models/."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Iterator

from . import Provider, sse_delta

# Models live next to the hogue-ide package: hogue-ide/models/
_MODELS_DIR = Path(__file__).parent.parent.parent / "models"

_lock = threading.Lock()
_loaded: dict[str, tuple] = {}  # model_name -> (model, tokenizer)


def _discover_models() -> dict[str, Path]:
    """Scan models/ for any directory containing config.json (HuggingFace format)."""
    models: dict[str, Path] = {}
    if not _MODELS_DIR.is_dir():
        return models
    for child in sorted(_MODELS_DIR.iterdir()):
        if child.is_dir() and (child / "config.json").exists():
            slug = f"local/{child.name}"
            models[slug] = child
    return models


def _load(model_name: str):
    if model_name in _loaded:
        return _loaded[model_name]
    with _lock:
        if model_name in _loaded:
            return _loaded[model_name]
        models = _discover_models()
        path = models.get(model_name)
        # Case-insensitive fallback
        if not path:
            lower_map = {k.lower(): v for k, v in models.items()}
            path = lower_map.get(model_name.lower())
        if not path:
            raise ValueError(f"Unknown local model: {model_name}")
        try:
            from mlx_lm import load as mlx_load
            print(f"Loading local MLX model from {path} …", flush=True)
            model, tokenizer = mlx_load(str(path))
            print(f"Local MLX model ready: {model_name}", flush=True)
            _loaded[model_name] = (model, tokenizer)
            return model, tokenizer
        except Exception as e:
            print(f"Error loading {model_name}: {e}", flush=True)
            raise


class OllamaProvider(Provider):
    name = "ollama"

    def is_available(self) -> bool:
        return bool(_discover_models())

    def get_models(self) -> list[str]:
        return list(_discover_models().keys())

    def generate(self, prompt: str, system: str, max_tokens: int, temperature: float, model_name: str) -> str:
        try:
            from mlx_lm import generate as mlx_generate
            from mlx_lm.sample_utils import make_sampler
            model, tokenizer = _load(model_name)
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            fmt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            with _lock:
                return mlx_generate(model, tokenizer, prompt=fmt, max_tokens=max_tokens,
                                    sampler=make_sampler(temp=max(temperature, 0.01)), verbose=False, kv_bits=4)
        except Exception as e:
            return f"Error executing local MLX model: {e}"

    def generate_stream(self, prompt: str, system: str, max_tokens: int, temperature: float, model_name: str) -> Iterator[str]:
        try:
            from mlx_lm import stream_generate, load as mlx_load
            from mlx_lm.sample_utils import make_sampler
            model, tokenizer = _load(model_name)
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            fmt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            sampler = make_sampler(temp=max(temperature, 0.01))
            with _lock:
                for response in stream_generate(model, tokenizer, prompt=fmt,
                                                max_tokens=max_tokens, sampler=sampler, kv_bits=4):
                    yield sse_delta(response.text)
        except Exception as e:
            yield sse_delta(f"Error: {e}")
