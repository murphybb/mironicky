from __future__ import annotations

import asyncio
import os
from pathlib import Path
from threading import Lock

from core.component.config_provider import ConfigProvider
from core.component.openai_compatible_client import OpenAICompatibleClient
from core.di.utils import get_bean
from research_layer.config.feature_flags import LOCAL_FIRST_FLAG, is_feature_enabled
from research_layer.services.llm_gateway import LLMGateway
from research_layer.services.llm_result_parser import LLMResultParser

_gateway_lock = Lock()
_gateway_singleton: LLMGateway | None = None


def get_openai_compatible_client() -> OpenAICompatibleClient:
    try:
        bean = get_bean("openai_compatible_client")
    except Exception:
        bean = OpenAICompatibleClient(ConfigProvider())
    if not isinstance(bean, OpenAICompatibleClient):
        raise TypeError(
            "openai_compatible_client bean must be OpenAICompatibleClient"
        )
    _apply_live_provider_overrides(bean)
    return bean


def build_research_llm_gateway(*, force_rebuild: bool = False) -> LLMGateway:
    global _gateway_singleton
    with _gateway_lock:
        if _gateway_singleton is None or force_rebuild:
            _gateway_singleton = LLMGateway(
                client=get_openai_compatible_client(),
                parser=LLMResultParser(),
            )
        return _gateway_singleton


def reset_research_llm_gateway() -> None:
    global _gateway_singleton
    with _gateway_lock:
        if _gateway_singleton is not None:
            client = getattr(_gateway_singleton, "_client", None)
            close = getattr(client, "close", None)
            if callable(close):
                try:
                    running_loop = asyncio.get_running_loop()
                except RuntimeError:
                    running_loop = None
                if running_loop and running_loop.is_running():
                    running_loop.create_task(close())
                else:
                    asyncio.run(close())
        _gateway_singleton = None


def resolve_research_backend_and_model() -> tuple[str | None, str | None]:
    config = ConfigProvider().get_config("llm_backends")
    dotenv = _read_dotenv(Path(__file__).resolve().parents[3] / ".env")
    backend_map = config.get("llm_backends", {})
    if is_feature_enabled(LOCAL_FIRST_FLAG):
        local_backend = (
            os.getenv("RESEARCH_LOCAL_LLM_BACKEND")
            or os.getenv("LOCAL_LLM_BACKEND")
            or dotenv.get("RESEARCH_LOCAL_LLM_BACKEND")
            or dotenv.get("LOCAL_LLM_BACKEND")
        )
        if local_backend and local_backend in backend_map:
            local_model = (
                os.getenv("RESEARCH_LOCAL_LLM_MODEL")
                or os.getenv("LOCAL_LLM_MODEL")
                or dotenv.get("RESEARCH_LOCAL_LLM_MODEL")
                or dotenv.get("LOCAL_LLM_MODEL")
                or backend_map.get(local_backend, {}).get("model")
            )
            return local_backend, (str(local_model) if local_model else None)
    env_backend = (
        os.getenv("RESEARCH_LLM_BACKEND")
        or os.getenv("MIRONICKY_LIVE_BACKEND")
        or os.getenv("LLM_PROVIDER")
        or dotenv.get("LLM_PROVIDER")
    )
    backend = None
    if env_backend and env_backend in backend_map:
        backend = env_backend
    elif "openai" in backend_map:
        backend = "openai"
    else:
        fallback = str(config.get("default_backend", "")).strip()
        backend = fallback or None
    model = (
        os.getenv("RESEARCH_LLM_MODEL")
        or os.getenv("MIRONICKY_LIVE_MODEL")
        or os.getenv("LLM_MODEL")
        or dotenv.get("LLM_MODEL")
    )
    if not model and backend and backend in backend_map:
        model = backend_map.get(backend, {}).get("model")
    return backend, (str(model) if model is not None else None)


def _read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _apply_live_provider_overrides(client: OpenAICompatibleClient) -> None:
    config = getattr(client, "_config", None)
    if not isinstance(config, dict):
        return
    backend_map = config.get("llm_backends")
    if not isinstance(backend_map, dict):
        return
    dotenv = _read_dotenv(Path(__file__).resolve().parents[3] / ".env")
    backend, model = resolve_research_backend_and_model()
    if not backend:
        return
    backend_cfg = backend_map.get(backend)
    if not isinstance(backend_cfg, dict):
        return
    api_key = (
        os.getenv("OPENAI_API_KEY")
        or os.getenv("LLM_API_KEY")
        or dotenv.get("LLM_API_KEY")
        or dotenv.get("OPENAI_API_KEY")
    )
    base_url = (
        os.getenv("OPENAI_BASE_URL")
        or os.getenv("LLM_BASE_URL")
        or dotenv.get("LLM_BASE_URL")
        or dotenv.get("OPENAI_BASE_URL")
    )
    if api_key:
        backend_cfg["api_key"] = api_key
    if base_url:
        backend_cfg["base_url"] = base_url
    if model:
        backend_cfg["model"] = model
    if not backend_cfg.get("provider"):
        backend_cfg["provider"] = "openai"
    config["default_backend"] = backend

