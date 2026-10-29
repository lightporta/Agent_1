"""Validated, immutable NPC identity and trusted world-context input.

These objects describe game data. Loading a profile does not execute its text,
access environment variables, create runtime state, or initialize a model.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MAX_PROFILE_BYTES = 64 * 1024
BUILTIN_PROFILE_NAMES = ("village_elder", "guard", "merchant")
THINKING_DIMENSIONS = ("caution", "duty", "empathy", "curiosity")


def _mapping(value: Any, fields: set[str], label: str) -> dict:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} 必须是对象")
    if any(not isinstance(key, str) or key not in fields for key in value):
        raise ValueError(f"{label} 含有未知字段")
    return dict(value)


def _text(value: Any, name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{name} 必须是 1 到 {maximum} 字的非空字符串")
    if any(ord(character) < 32 and character not in "\n\t" for character in value):
        raise ValueError(f"{name} 含有不支持的控制字符")
    return value


def _integer(value: Any, name: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} 必须是 {minimum} 到 {maximum} 的整数")
    return value


def _items(value: Any, name: str, *, minimum: int = 1) -> tuple[str, ...]:
    if not isinstance(value, tuple) or not minimum <= len(value) <= 16:
        raise ValueError(f"{name} 必须是包含 {minimum} 到 16 项的 tuple")
    for item in value:
        _text(item, name, 200)
    if len(set(value)) != len(value):
        raise ValueError(f"{name} 不能包含重复项")
    return value


def _array(value: Any, name: str) -> tuple:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{name} 必须是数组")
    return tuple(value)


@dataclass(frozen=True)
class DecisionStyle:
    """Character-specific inputs to strategy scoring, rather than hidden reasoning."""

    caution: int = 50
    empathy: int = 50
    duty: int = 50
    curiosity: int = 50

    def __post_init__(self):
        for name in ("caution", "empathy", "duty", "curiosity"):
            _integer(getattr(self, name), name, 0, 100)

    @classmethod
    def from_dict(cls, value: Mapping) -> DecisionStyle:
        return cls(**_mapping(value, {"caution", "empathy", "duty", "curiosity"}, "decision_style"))

    def to_dict(self) -> dict:
        return {name: getattr(self, name) for name in ("caution", "empathy", "duty", "curiosity")}


@dataclass(frozen=True)
class NPCProfile:
    npc_id: str
    name: str
    personality: tuple[str, ...]
    profession: str
    region: str
    background: str = "本地演示角色。"
    speech_style: str = "自然、简洁的中文。"
    goals: tuple[str, ...] = ("履行当前职责",)
    values: tuple[str, ...] = ("诚实",)
    decision_style: DecisionStyle = field(default_factory=DecisionStyle)
    thinking_order: tuple[str, ...] = THINKING_DIMENSIONS

    def __post_init__(self):
        if not isinstance(self.npc_id, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}", self.npc_id
        ):
            raise ValueError("npc_id 必须是 1 到 64 位字母、数字、下划线、点、冒号或短横线标识")
        for name, maximum in (
            ("name", 64),
            ("profession", 128),
            ("region", 128),
            ("background", 2000),
            ("speech_style", 500),
        ):
            _text(getattr(self, name), name, maximum)
        for name in ("personality", "goals", "values"):
            _items(getattr(self, name), name)
        if not isinstance(self.decision_style, DecisionStyle):
            raise ValueError("decision_style 必须是 DecisionStyle")
        _items(self.thinking_order, "thinking_order", minimum=4)
        if len(self.thinking_order) != 4 or set(self.thinking_order) != set(THINKING_DIMENSIONS):
            raise ValueError(
                "thinking_order 必须是 caution、empathy、duty、curiosity 的完整唯一排列"
            )

    @classmethod
    def from_dict(cls, value: Mapping) -> NPCProfile:
        fields = {
            "npc_id",
            "name",
            "personality",
            "profession",
            "region",
            "background",
            "speech_style",
            "goals",
            "values",
            "decision_style",
            "thinking_order",
        }
        data = _mapping(value, fields, "NPCProfile")
        missing = {"npc_id", "name", "personality", "profession", "region"} - set(data)
        if missing:
            raise ValueError("NPCProfile 缺少必需字段：" + ", ".join(sorted(missing)))
        for name in ("personality", "goals", "values", "thinking_order"):
            if name in data:
                data[name] = _array(data[name], name)
        if "decision_style" in data:
            data["decision_style"] = DecisionStyle.from_dict(data["decision_style"])
        return cls(**data)

    def to_dict(self) -> dict:
        return {
            "npc_id": self.npc_id,
            "name": self.name,
            "personality": list(self.personality),
            "profession": self.profession,
            "region": self.region,
            "background": self.background,
            "speech_style": self.speech_style,
            "goals": list(self.goals),
            "values": list(self.values),
            "decision_style": self.decision_style.to_dict(),
            "thinking_order": list(self.thinking_order),
        }

    def fingerprint(self) -> str:
        canonical = json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class WorldContext:
    """A trusted snapshot supplied by the game host, separate from player dialogue."""

    region: str | None = None
    time_of_day: str = "day"
    nearby_events: tuple[str, ...] = ()
    relationship: int = 0
    danger: int = 0

    def __post_init__(self):
        if self.region is not None:
            _text(self.region, "region", 128)
        if not isinstance(self.time_of_day, str) or self.time_of_day not in {
            "dawn",
            "day",
            "dusk",
            "night",
        }:
            raise ValueError("time_of_day 只能是 dawn、day、dusk 或 night")
        _items(self.nearby_events, "nearby_events", minimum=0)
        _integer(self.relationship, "relationship", -100, 100)
        _integer(self.danger, "danger", 0, 100)

    @classmethod
    def from_dict(cls, value: Mapping) -> WorldContext:
        data = _mapping(
            value,
            {"region", "time_of_day", "nearby_events", "relationship", "danger"},
            "WorldContext",
        )
        if "nearby_events" in data:
            data["nearby_events"] = _array(data["nearby_events"], "nearby_events")
        return cls(**data)

    def to_dict(self) -> dict:
        return {
            "region": self.region,
            "time_of_day": self.time_of_day,
            "nearby_events": list(self.nearby_events),
            "relationship": self.relationship,
            "danger": self.danger,
        }


def _unique_object(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"NPC JSON 含有重复字段：{key}")
        result[key] = value
    return result


def _reject_constant(value: str):
    raise ValueError(f"NPC JSON 不允许数值 {value}")


def _read_json_text(path: str | Path) -> str:
    if not isinstance(path, (str, Path)) or (isinstance(path, str) and not path.strip()):
        raise ValueError("JSON 文件路径必须是非空字符串或 Path")
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(MAX_PROFILE_BYTES + 1)
    except OSError as exc:
        raise ValueError("无法读取角色或世界情境 JSON，请检查文件路径与权限") from exc
    if len(raw) > MAX_PROFILE_BYTES:
        raise ValueError("JSON 文件不能超过 64 KB")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeError as exc:
        raise ValueError("角色或世界情境文件必须是有效 UTF-8 JSON") from exc


def _parse_json(text: str) -> Any:
    if not isinstance(text, str):
        raise ValueError("JSON 输入必须是字符串")
    try:
        if len(text.encode("utf-8")) > MAX_PROFILE_BYTES:
            raise ValueError("JSON 文本不能超过 64 KB")
        return json.loads(
            text.removeprefix("\ufeff"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("角色或世界情境必须是有效 UTF-8 JSON 对象") from exc


def parse_profile_json(text: str) -> NPCProfile:
    return NPCProfile.from_dict(_parse_json(text))


def parse_context_json(text: str) -> WorldContext:
    return WorldContext.from_dict(_parse_json(text))


def load_profile(path: str | Path | None = None) -> NPCProfile:
    """Read at most 64 KiB of explicit JSON; the default is a bundled demo profile."""
    source = (
        path
        if path is not None
        else (Path(__file__).resolve().parent / "assets" / "npcs" / "village_elder.json")
    )
    return parse_profile_json(_read_json_text(source))


def load_context(path: str | Path | None = None) -> WorldContext:
    return WorldContext() if path is None else parse_context_json(_read_json_text(path))


def load_builtin_profile(name: str = "village_elder") -> NPCProfile:
    if name not in BUILTIN_PROFILE_NAMES:
        raise ValueError("未知内置 NPC，请选择 village_elder、guard 或 merchant")
    return load_profile(Path(__file__).resolve().parent / "assets" / "npcs" / f"{name}.json")


def builtin_profiles() -> dict[str, NPCProfile]:
    return {name: load_builtin_profile(name) for name in BUILTIN_PROFILE_NAMES}
