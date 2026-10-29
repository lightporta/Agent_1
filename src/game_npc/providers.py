"""OpenAI-compatible chat provider presets.

Every live provider uses the same Chat Completions + tool-calling transport.
Claude and other non-native SDKs are reached through OpenRouter or any custom
OpenAI-compatible gateway; this module does not scrape provider docs at runtime.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderPreset:
    """Default endpoint and models for one named provider family."""

    name: str
    base_url: str
    model: str
    embedding_model: str
    api_key_envs: tuple[str, ...]
    label: str
    notes: str = ""


PROVIDERS: dict[str, ProviderPreset] = {
    "qwen": ProviderPreset(
        name="qwen",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen3-max",
        embedding_model="text-embedding-v4",
        api_key_envs=("DASHSCOPE_API_KEY", "GAME_NPC_API_KEY"),
        label="通义千问 / Qwen",
    ),
    "deepseek": ProviderPreset(
        name="deepseek",
        base_url="https://api.deepseek.com/v1",
        model="deepseek-chat",
        embedding_model="text-embedding-v4",
        api_key_envs=("DEEPSEEK_API_KEY", "GAME_NPC_API_KEY"),
        label="DeepSeek",
        notes="Embeddings usually need a separate embedding-capable endpoint.",
    ),
    "kimi": ProviderPreset(
        name="kimi",
        base_url="https://api.moonshot.cn/v1",
        model="moonshot-v1-auto",
        embedding_model="text-embedding-v4",
        api_key_envs=("MOONSHOT_API_KEY", "KIMI_API_KEY", "GAME_NPC_API_KEY"),
        label="Kimi / Moonshot",
    ),
    "openai": ProviderPreset(
        name="openai",
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
        embedding_model="text-embedding-3-small",
        api_key_envs=("OPENAI_API_KEY", "GAME_NPC_API_KEY"),
        label="OpenAI / ChatGPT",
    ),
    "grok": ProviderPreset(
        name="grok",
        base_url="https://api.x.ai/v1",
        model="grok-3-mini",
        embedding_model="text-embedding-3-small",
        api_key_envs=("XAI_API_KEY", "GROK_API_KEY", "GAME_NPC_API_KEY"),
        label="Grok / xAI",
        notes="Use an OpenAI-compatible embedding provider when vector mode is enabled.",
    ),
    "glm": ProviderPreset(
        name="glm",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        model="glm-4-plus",
        embedding_model="embedding-3",
        api_key_envs=("ZHIPUAI_API_KEY", "GLM_API_KEY", "GAME_NPC_API_KEY"),
        label="智谱 GLM",
    ),
    "openrouter": ProviderPreset(
        name="openrouter",
        base_url="https://openrouter.ai/api/v1",
        model="anthropic/claude-sonnet-4",
        embedding_model="openai/text-embedding-3-small",
        api_key_envs=("OPENROUTER_API_KEY", "GAME_NPC_API_KEY"),
        label="OpenRouter (Claude / multi-model)",
        notes="Route Claude, Grok, Gemini and others through one OpenAI-compatible key.",
    ),
    "claude": ProviderPreset(
        name="claude",
        base_url="https://openrouter.ai/api/v1",
        model="anthropic/claude-sonnet-4",
        embedding_model="openai/text-embedding-3-small",
        api_key_envs=("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "GAME_NPC_API_KEY"),
        label="Claude via OpenAI-compatible gateway",
        notes=(
            "Native Anthropic Messages API is not used. Point GAME_NPC_BASE_URL at "
            "OpenRouter or another OpenAI-compatible Claude gateway."
        ),
    ),
    "custom": ProviderPreset(
        name="custom",
        base_url="https://example.invalid/v1",
        model="custom-model",
        embedding_model="text-embedding-3-small",
        api_key_envs=("GAME_NPC_API_KEY", "OPENAI_API_KEY"),
        label="Custom OpenAI-compatible endpoint",
        notes="Require explicit GAME_NPC_BASE_URL and GAME_NPC_MODEL.",
    ),
}


def resolve_api_key(provider: str, explicit: str = "") -> str:
    """Prefer an explicit key, then GAME_NPC_API_KEY, then provider-specific envs."""
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    shared = os.getenv("GAME_NPC_API_KEY", "").strip()
    if shared:
        return shared
    preset = PROVIDERS.get(provider, PROVIDERS["custom"])
    for name in preset.api_key_envs:
        value = os.getenv(name, "").strip()
        if value:
            return value
    # Legacy fallback kept for older demo/live setups.
    return os.getenv("DASHSCOPE_API_KEY", "").strip() or os.getenv("OPENAI_API_KEY", "").strip()


def apply_provider(
    provider: str,
    *,
    model: str | None = None,
    base_url: str | None = None,
    embedding_model: str | None = None,
) -> tuple[str, str, str, str]:
    """Return (provider, model, base_url, embedding_model) after applying presets."""
    name = (provider or "qwen").strip().lower()
    if name not in PROVIDERS:
        allowed = ", ".join(sorted(PROVIDERS))
        raise ValueError(f"GAME_NPC_PROVIDER 必须是其一：{allowed}")
    preset = PROVIDERS[name]

    def _resolve(value: str | None, field_name: str, fallback: str) -> str:
        if value is None:
            return fallback
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name}不能为空")
        return value.strip()

    resolved_model = _resolve(model, "模型名称", preset.model)
    resolved_base = _resolve(base_url, "模型接口", preset.base_url)
    resolved_embedding = _resolve(embedding_model, "嵌入模型名称", preset.embedding_model)
    if name == "custom" and (
        resolved_base == preset.base_url or "example.invalid" in resolved_base
    ):
        raise ValueError("custom 提供商必须设置有效的 GAME_NPC_BASE_URL")
    return name, resolved_model, resolved_base, resolved_embedding


def provider_catalog() -> list[dict[str, str]]:
    return [
        {
            "name": item.name,
            "label": item.label,
            "model": item.model,
            "base_url": item.base_url,
            "notes": item.notes,
        }
        for item in PROVIDERS.values()
    ]
