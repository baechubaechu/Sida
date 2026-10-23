"""Which provider, model and context size each role (Conductor, worker) runs with."""

from __future__ import annotations

from sida.config import load_config
from sida.errors import fail
from sida.i18n import t
from sida.providers import DEFAULT_OLLAMA_URL, make_provider

DEFAULT_CHATGPT_MODEL = "gpt-6.1-sol"


def load_env(*, config: dict | None = None) -> str:
    """The OpenRouter API key. Fails (SidaError) when a role needs OpenRouter and none is set."""
    from sida import settings

    cfg = config if config is not None else load_config()
    key = settings.read_key("OPENROUTER_API_KEY")
    if not key and needs_openrouter(cfg):
        fail(t("api_required"))
    return key


def needs_openrouter(config: dict) -> bool:
    """True if Conductor, Worker, or state_update will call OpenRouter."""
    top = str(config.get("provider") or "openrouter").lower()
    conductor = str((config.get("conductor") or {}).get("provider") or top).lower()
    worker = str((config.get("worker") or {}).get("provider") or top).lower()
    providers = {conductor, worker}
    su = config.get("state_update") or {}
    if str(su.get("mode", "ask")).lower() != "off":
        which = str(su.get("provider", "worker")).lower()
        providers.add(conductor if which == "conductor" else worker)
    return any(p in {"openrouter", "cloud"} for p in providers)


def resolve_local_profile(config: dict, *, for_worker: bool = False) -> dict | None:
    """Return local_profiles entry when Conductor (or Worker) provider is ollama."""
    conductor = config.get("conductor") or {}
    worker = config.get("worker") or {}
    if for_worker:
        provider = str(worker.get("provider") or config.get("provider") or "openrouter")
        name = str(worker.get("local_profile") or conductor.get("local_profile") or "local")
    else:
        provider = str(conductor.get("provider") or config.get("provider") or "openrouter")
        name = str(conductor.get("local_profile") or "local")
    if provider.lower() not in {"ollama", "local"}:
        return None
    profiles = config.get("local_profiles") or {}
    profile = profiles.get(name)
    if not isinstance(profile, dict):
        fail(
            f"Unknown local_profile '{name}'. "
            f"Define it under local_profiles in config.yaml "
            f"(available: {', '.join(profiles) or 'none'})."
        )
    return profile


def resolve_conductor_runtime(config: dict) -> dict:
    """Effective Conductor settings after applying local_profile overlays."""
    conductor = dict(config.get("conductor") or {})
    provider = str(conductor.get("provider") or config.get("provider") or "openrouter")
    runtime = {
        "provider": provider.lower(),
        "model": conductor.get("model", "anthropic/claude-haiku-4.5"),
        "temperature": float(conductor.get("temperature", 0.4)),
        "max_tokens": int(conductor.get("max_tokens", 700)),
        "cache_ttl": str(conductor.get("cache_ttl", "1h")),
        "prompt": conductor.get("prompt", "agents/00_conductor.md"),
        "base_url": conductor.get("base_url"),
        "local_profile": conductor.get("local_profile"),
        "num_ctx": None,
        "history_window": int((conductor.get("context") or {}).get("history_window", 12)),
        "action_recovery": str(conductor.get("action_recovery", "auto")).lower(),
        "tool_calls": str(conductor.get("tool_calls", "auto")).lower(),
        "max_expert_runs": max(1, int(conductor.get("max_expert_runs", 3))),
        "keep_alive": str(conductor.get("ollama_keep_alive", "30m")),
        # Default false: thinking models (qwen3.5) otherwise burn num_predict on CoT.
        "think": bool(conductor.get("ollama_think", False)),
    }

    if runtime["provider"] == "chatgpt":  # the signed-in ChatGPT plan has its own model ids
        runtime["model"] = str(conductor.get("chatgpt_model") or DEFAULT_CHATGPT_MODEL)

    profile = resolve_local_profile(config)
    if profile:
        if profile.get("model"):
            runtime["model"] = profile["model"]
        if "temperature" in profile:
            runtime["temperature"] = float(profile["temperature"])
        if "max_tokens" in profile:
            runtime["max_tokens"] = int(profile["max_tokens"])
        if "history_window" in profile:
            runtime["history_window"] = int(profile["history_window"])
        if "num_ctx" in profile:
            runtime["num_ctx"] = int(profile["num_ctx"])
        if profile.get("base_url"):
            runtime["base_url"] = profile["base_url"]
        elif not runtime["base_url"]:
            runtime["base_url"] = DEFAULT_OLLAMA_URL

    return runtime


def resolve_worker_runtime(config: dict) -> dict:
    """Effective worker settings. ollama → local_profile model / num_ctx / base_url."""
    worker = dict(config.get("worker") or {})
    conductor = config.get("conductor") or {}
    runtime = {
        "provider": str(worker.get("provider") or config.get("provider") or "openrouter").lower(),
        "model": worker.get("model") or config.get("model", "openai/gpt-4o-mini"),
        "temperature": float(worker.get("temperature", config.get("temperature", 0.3))),
        "max_tokens": int(worker.get("max_tokens", config.get("max_tokens", 2000))),
        "base_url": worker.get("base_url") or conductor.get("base_url"),
        "num_ctx": worker.get("num_ctx"),
        "keep_alive": str(
            worker.get("keep_alive") or conductor.get("ollama_keep_alive") or "30m"
        ),
        "local_profile": worker.get("local_profile") or conductor.get("local_profile"),
        "think": bool(
            worker["think"]
            if "think" in worker
            else conductor.get("ollama_think", False)
        ),
    }
    profile = resolve_local_profile(config, for_worker=True)
    if profile and runtime["provider"] in {"ollama", "local"}:
        # Cloud-style ids (openai/...) are not valid Ollama tags — replace from profile.
        model = str(runtime["model"] or "")
        if profile.get("model") and ("/" in model or not model):
            runtime["model"] = profile["model"]
        if runtime["num_ctx"] is None and profile.get("num_ctx"):
            runtime["num_ctx"] = int(profile["num_ctx"])
        if not runtime["base_url"]:
            runtime["base_url"] = profile.get("base_url") or DEFAULT_OLLAMA_URL
    if runtime["provider"] in {"ollama", "local"} and not runtime["base_url"]:
        runtime["base_url"] = DEFAULT_OLLAMA_URL
    return runtime


def conductor_provider(config: dict, api_key: str):
    rt = resolve_conductor_runtime(config)
    return make_provider(
        rt["provider"],
        api_key=api_key,
        base_url=rt.get("base_url"),
        num_ctx=rt.get("num_ctx"),
        keep_alive=rt.get("keep_alive"),
        think=rt.get("think", False),
    )


def worker_provider(config: dict, api_key: str):
    rt = resolve_worker_runtime(config)
    return make_provider(
        rt["provider"],
        api_key=api_key,
        base_url=rt.get("base_url"),
        num_ctx=rt.get("num_ctx"),
        keep_alive=rt.get("keep_alive"),
        think=rt.get("think", False),
    )
