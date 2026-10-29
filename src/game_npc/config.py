"""Explicit configuration and resource paths, independent of the working directory."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from game_npc.providers import PROVIDERS, apply_provider, resolve_api_key

ASSETS = Path(__file__).resolve().parent / "assets"


def _default_state_dir() -> Path:
    try:
        return Path.home() / ".game-npc"
    except RuntimeError as exc:
        raise ValueError(
            "无法确定用户目录，请通过 --state-dir 或 GAME_NPC_STATE_DIR 指定状态目录"
        ) from exc


def _resolve_user_path(value: Path | str, label: str) -> Path:
    """Resolve paths without turning missing HOME into an uncaught expanduser error."""
    try:
        return Path(value).expanduser().resolve()
    except RuntimeError as exc:
        raise ValueError(
            f"无法解析{label}，请使用绝对路径，或设置可用的用户目录 / GAME_NPC_STATE_DIR"
        ) from exc


@dataclass(frozen=True)
class Settings:
    mode: str = "demo"
    retrieval: str = "local"
    state_dir: Path = field(default_factory=_default_state_dir)
    data_dir: Path = ASSETS / "knowledge"
    npc_profile_path: Path | None = None
    world_pack_path: Path | None = None
    provider: str = "qwen"
    model: str | None = None
    base_url: str | None = None
    api_key: str = field(default="", repr=False)
    embedding_model: str | None = None
    max_tool_calls: int = 5
    history_turns: int = 12

    def __post_init__(self):
        object.__setattr__(self, "state_dir", _resolve_user_path(self.state_dir, "状态目录"))
        object.__setattr__(self, "data_dir", _resolve_user_path(self.data_dir, "知识目录"))
        if self.npc_profile_path is not None:
            object.__setattr__(
                self,
                "npc_profile_path",
                _resolve_user_path(self.npc_profile_path, "角色档案路径"),
            )
        if self.world_pack_path is not None:
            object.__setattr__(
                self,
                "world_pack_path",
                _resolve_user_path(self.world_pack_path, "世界包路径"),
            )
        provider, model, base_url, embedding_model = apply_provider(
            self.provider,
            model=self.model,
            base_url=self.base_url,
            embedding_model=self.embedding_model,
        )
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "base_url", base_url)
        object.__setattr__(self, "embedding_model", embedding_model)
        if self.mode not in {"demo", "live"}:
            raise ValueError("GAME_NPC_MODE 只能是 demo 或 live")
        if self.retrieval not in {"local", "vector"}:
            raise ValueError("GAME_NPC_RETRIEVAL 只能是 local 或 vector")
        if not 1 <= self.max_tool_calls <= 20:
            raise ValueError("工具调用预算必须在 1 到 20 之间")
        if not 1 <= self.history_turns <= 50:
            raise ValueError("历史轮数必须在 1 到 50 之间")
        if not self.model.strip() or not self.embedding_model.strip():
            raise ValueError("模型名称不能为空")
        url = urlparse(self.base_url)
        if url.scheme != "https" or not url.netloc or url.username or url.password:
            raise ValueError("模型接口必须是没有内嵌凭据的 HTTPS 地址")

    @classmethod
    def from_env(cls, *, state_dir: Path | str | None = None):
        provider = os.getenv("GAME_NPC_PROVIDER", "qwen").strip().lower() or "qwen"
        # Never pass Path.home() as os.getenv's default argument: Python evaluates
        # that expression eagerly even when GAME_NPC_STATE_DIR is already set, and
        # Windows runners / cleared test envs then raise before the override applies.
        selected_state = state_dir if state_dir is not None else os.getenv("GAME_NPC_STATE_DIR")
        state_override = {"state_dir": Path(selected_state)} if selected_state else {}
        return cls(
            mode=os.getenv("GAME_NPC_MODE", "demo"),
            retrieval=os.getenv("GAME_NPC_RETRIEVAL", "local"),
            data_dir=Path(os.getenv("GAME_NPC_DATA_DIR", str(ASSETS / "knowledge"))),
            npc_profile_path=Path(os.environ["GAME_NPC_PROFILE_PATH"])
            if os.getenv("GAME_NPC_PROFILE_PATH")
            else None,
            world_pack_path=Path(os.environ["GAME_NPC_WORLD_PATH"])
            if os.getenv("GAME_NPC_WORLD_PATH")
            else None,
            provider=provider,
            model=os.getenv("GAME_NPC_MODEL") or None,
            base_url=os.getenv("GAME_NPC_BASE_URL") or None,
            api_key=resolve_api_key(provider),
            embedding_model=os.getenv("GAME_NPC_EMBEDDING_MODEL") or None,
            **state_override,
        )

    def require_online(self):
        if not self.api_key.strip():
            raise ValueError(
                "在线能力需要设置 GAME_NPC_API_KEY（或当前提供商对应密钥）；"
                "也可使用 demo + local 离线运行"
            )

    def provider_label(self) -> str:
        preset = PROVIDERS.get(self.provider)
        return preset.label if preset else self.provider


def load_prompt(name: str) -> str:
    if name not in {"dialogue", "report"}:
        raise ValueError("未知提示词")
    return (ASSETS / "prompts" / f"{name}.txt").read_text(encoding="utf-8")
