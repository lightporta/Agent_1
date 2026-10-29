"""Small, lazy OpenAI-compatible adapter for the online NPC provider."""

from dataclasses import dataclass, field
from typing import Any

from game_npc.config import Settings


class ModelError(RuntimeError):
    """A safe, user-facing model configuration, transport, or protocol error."""


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class ModelReply:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)


def _get(value: Any, name: str, default: Any = None) -> Any:
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def _text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        raise ModelError("模型返回了无法识别的文本格式，请检查兼容接口配置")
    parts = []
    for block in content:
        kind = _get(block, "type")
        if kind == "refusal":
            raise ModelError("模型未能回应本次请求，请调整问题后重试")
        if kind in {"text", "output_text"}:
            text = _get(block, "text")
            if not isinstance(text, str):
                raise ModelError("模型返回了无法识别的文本格式，请检查兼容接口配置")
            parts.append(text)
    return "".join(parts).strip()


class OpenAIModel:
    """Use Chat Completions tool calls without exposing intermediate model text.

    The agent decides which final answer to display. Network requests deliberately
    use complete messages so that tool-planning text is never rendered as a delta.
    A fake SDK client may be injected for offline protocol tests.
    """

    def __init__(self, settings: Settings, client: Any = None):
        settings.require_online()
        self.settings = settings
        if client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise ModelError(
                    '在线模式缺少依赖，请运行 python -m pip install ".[live]"'
                ) from exc
            try:
                client = OpenAI(
                    api_key=settings.api_key,
                    base_url=settings.base_url,
                    timeout=45,
                    max_retries=0,
                )
            except Exception as exc:
                raise ModelError("无法初始化模型客户端，请检查在线配置") from exc
        self._client = client

    def complete(self, messages: list[dict], tools: list[dict]) -> ModelReply:
        kwargs = {
            "model": self.settings.model,
            "messages": messages,
            "stream": False,
        }
        if tools:
            kwargs["tools"] = tools
        try:
            response = self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            # Provider errors can include URLs, headers, user content, or keys.
            # Keep the cause for diagnostics, but expose only this fixed message.
            raise ModelError("模型请求失败，请检查网络、密钥、模型权限或稍后重试") from exc

        choices = _get(response, "choices")
        if not isinstance(choices, list) or not choices:
            raise ModelError("模型返回了空响应，请稍后重试")
        choice = choices[0]
        reason = _get(choice, "finish_reason")
        if reason == "length":
            raise ModelError("模型输出超出长度限制，请缩短问题后重试")
        if reason == "content_filter":
            raise ModelError("模型未能回应本次请求，请调整问题后重试")
        message = _get(choice, "message")
        if message is None:
            raise ModelError("模型返回了不完整的响应，请稍后重试")
        if _get(message, "refusal"):
            raise ModelError("模型未能回应本次请求，请调整问题后重试")
        text = _text(_get(message, "content"))
        calls = []
        raw_calls = _get(message, "tool_calls") or []
        if not isinstance(raw_calls, list):
            raise ModelError("模型返回了无效的工具调用格式")
        for call in raw_calls:
            function = _get(call, "function")
            call_id, name, arguments = (
                _get(call, "id"),
                _get(function, "name"),
                _get(function, "arguments"),
            )
            if (
                _get(call, "type", "function") != "function"
                or not isinstance(call_id, str)
                or not call_id.strip()
                or not isinstance(name, str)
                or not name.strip()
                or not isinstance(arguments, str)
            ):
                raise ModelError("模型返回了无效的工具调用格式")
            calls.append(ToolCall(call_id, name, arguments))
        if not text and not calls:
            raise ModelError("模型没有生成可显示的回答，请稍后重试")
        return ModelReply(text, calls)
