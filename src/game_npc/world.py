"""Validated game-world packs that frame lore without replacing NPC cognition.

A world pack supplies setting name, regions, tone and optional knowledge paths.
NPC thinking_order / decision scoring stay inside CognitiveEngine. Hosts may
point knowledge at licensed or original materials they control; this loader
never scrapes websites.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from game_npc.persona import (
    MAX_PROFILE_BYTES,
    _array,
    _items,
    _mapping,
    _parse_json,
    _read_json_text,
    _text,
)

BUILTIN_WORLD_NAMES = (
    "demo_valley",
    "honor_of_kings",
    "genshin",
    "minecraft",
    "open_world",
)
WORLDS_ROOT = Path(__file__).resolve().parent / "assets" / "worlds"


@dataclass(frozen=True)
class WorldPack:
    """Static setting frame for one game or original world."""

    world_id: str
    title: str
    setting_name: str
    summary: str
    regions: tuple[str, ...]
    tone: str = "保持角色口吻，只使用已提供的设定资料。"
    genre: str = "fantasy"
    lore_guidelines: tuple[str, ...] = (
        "只依据宿主提供的知识库与情境作答，不编造官方未给出的剧情。",
    )
    knowledge_dir: str | None = None
    default_npc: str | None = None
    source_policy: str = (
        "知识与角色资料由宿主显式提供；程序不会自动抓取网页或下载受版权保护的内容。"
    )

    def __post_init__(self):
        if not isinstance(self.world_id, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}", self.world_id
        ):
            raise ValueError("world_id 必须是 1 到 64 位字母、数字、下划线、点、冒号或短横线标识")
        for name, maximum in (
            ("title", 128),
            ("setting_name", 128),
            ("summary", 4000),
            ("tone", 500),
            ("genre", 64),
            ("source_policy", 500),
        ):
            _text(getattr(self, name), name, maximum)
        _items(self.regions, "regions")
        _items(self.lore_guidelines, "lore_guidelines")
        if self.knowledge_dir is not None:
            _text(self.knowledge_dir, "knowledge_dir", 512)
        if self.default_npc is not None:
            _text(self.default_npc, "default_npc", 128)

    @classmethod
    def from_dict(cls, value: Mapping) -> WorldPack:
        fields = {
            "world_id",
            "title",
            "setting_name",
            "summary",
            "regions",
            "tone",
            "genre",
            "lore_guidelines",
            "knowledge_dir",
            "default_npc",
            "source_policy",
        }
        data = _mapping(value, fields, "WorldPack")
        missing = {"world_id", "title", "setting_name", "summary", "regions"} - set(data)
        if missing:
            raise ValueError("WorldPack 缺少必需字段：" + ", ".join(sorted(missing)))
        for name in ("regions", "lore_guidelines"):
            if name in data:
                data[name] = _array(data[name], name)
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "world_id": self.world_id,
            "title": self.title,
            "setting_name": self.setting_name,
            "summary": self.summary,
            "regions": list(self.regions),
            "tone": self.tone,
            "genre": self.genre,
            "lore_guidelines": list(self.lore_guidelines),
            "knowledge_dir": self.knowledge_dir,
            "default_npc": self.default_npc,
            "source_policy": self.source_policy,
        }

    def prompt_block(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    def resolve_knowledge_dir(self, pack_dir: Path | None = None) -> Path | None:
        if self.knowledge_dir is None:
            return None
        path = Path(self.knowledge_dir).expanduser()
        if path.is_absolute():
            return path.resolve()
        if pack_dir is not None:
            return (pack_dir / path).resolve()
        # WorldPack objects from builtin_worlds() still resolve packaged lore.
        candidate = (WORLDS_ROOT / self.world_id / path).resolve()
        return candidate if candidate.is_dir() else None


def parse_world_json(text: str) -> WorldPack:
    return WorldPack.from_dict(_parse_json(text))


def load_world(path: str | Path) -> tuple[WorldPack, Path]:
    """Load a world.json file and return (pack, pack_directory)."""
    source = Path(path).expanduser().resolve()
    if source.is_dir():
        source = source / "world.json"
    text = _read_json_text(source)
    if len(text.encode("utf-8")) > MAX_PROFILE_BYTES:
        raise ValueError("世界包 JSON 不能超过 64 KB")
    pack = parse_world_json(text)
    return pack, source.parent


def load_builtin_world(name: str = "demo_valley") -> tuple[WorldPack, Path]:
    if name not in BUILTIN_WORLD_NAMES:
        raise ValueError("未知内置世界，请选择：" + ", ".join(BUILTIN_WORLD_NAMES))
    return load_world(WORLDS_ROOT / name)


def builtin_worlds() -> dict[str, WorldPack]:
    return {name: load_builtin_world(name)[0] for name in BUILTIN_WORLD_NAMES}


def load_world_npc(pack_dir: Path, npc_name: str):
    from game_npc.persona import load_profile

    path = Path(pack_dir) / "npcs" / f"{npc_name}.json"
    if not path.is_file():
        path = Path(pack_dir) / "npcs" / npc_name
    return load_profile(path)
