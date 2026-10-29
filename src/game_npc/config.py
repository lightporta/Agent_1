"""Explicit configuration and resource paths, independent of the working directory."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

ASSETS = Path(__file__).resolve().parent / "assets"


@dataclass(frozen=True)
class Settings:
    mode: str = "demo"
    retrieval: str = "local"
    state_dir: Path = field(default_factory=lambda: Path.home() / ".game-npc")
    data_dir: Path = ASSETS / "knowledge"
    npc_profile_path: Path | None = None
    model: str = "qwen3-max"
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    api_key: str = field(default="", repr=False)
    embedding_model: str = "text-embedding-v4"
    max_tool_calls: int = 5
    history_turns: int = 12

    def __post_init__(self):
        object.__setattr__(self, "state_dir", Path(self.state_dir).expanduser().resolve())
        object.__setattr__(self, "data_dir", Path(self.data_dir).expanduser().resolve())
        if self.npc_profile_path is not None:
            object.__setattr__(
                self, "npc_profile_path", Path(self.npc_profile_path).expanduser().resolve()
            )
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
    def from_env(cls):
        return cls(
            mode=os.getenv("GAME_NPC_MODE", "demo"),
            retrieval=os.getenv("GAME_NPC_RETRIEVAL", "local"),
            state_dir=Path(os.getenv("GAME_NPC_STATE_DIR", str(Path.home() / ".game-npc"))),
            data_dir=Path(os.getenv("GAME_NPC_DATA_DIR", str(ASSETS / "knowledge"))),
            npc_profile_path=Path(os.environ["GAME_NPC_PROFILE_PATH"])
            if os.getenv("GAME_NPC_PROFILE_PATH")
            else None,
            model=os.getenv("GAME_NPC_MODEL", "qwen3-max"),
            base_url=os.getenv("GAME_NPC_BASE_URL", cls.base_url),
            api_key=os.getenv("DASHSCOPE_API_KEY", ""),
            embedding_model=os.getenv("GAME_NPC_EMBEDDING_MODEL", "text-embedding-v4"),
        )

    def require_online(self):
        if not self.api_key.strip():
            raise ValueError("在线能力需要设置 DASHSCOPE_API_KEY；也可使用 demo + local 离线运行")


def load_prompt(name: str) -> str:
    if name not in {"dialogue", "report"}:
        raise ValueError("未知提示词")
    return (ASSETS / "prompts" / f"{name}.txt").read_text(encoding="utf-8")
