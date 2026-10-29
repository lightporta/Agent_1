"""Game world packs frame lore; they do not replace NPC cognition."""

import tempfile
import unittest
from pathlib import Path

from game_npc.bootstrap import build_conversation
from game_npc.config import Settings
from game_npc.world import (
    BUILTIN_WORLD_NAMES,
    WorldPack,
    builtin_worlds,
    load_builtin_world,
    load_world_npc,
    parse_world_json,
)


class WorldPackTests(unittest.TestCase):
    def test_builtin_worlds_cover_requested_game_frames(self):
        worlds = builtin_worlds()
        self.assertEqual(set(worlds), set(BUILTIN_WORLD_NAMES))
        self.assertIn("王者峡谷", worlds["honor_of_kings"].setting_name)
        self.assertIn("提瓦特", worlds["genshin"].setting_name)
        self.assertIn("方块", worlds["minecraft"].setting_name)
        self.assertIn("大世界", worlds["open_world"].setting_name)

    def test_world_pack_rejects_unknown_fields_and_bad_ids(self):
        base = {
            "world_id": "demo",
            "title": "演示",
            "setting_name": "测试大陆",
            "summary": "摘要",
            "regions": ["城镇"],
        }
        WorldPack.from_dict(base)
        with self.assertRaises(ValueError):
            WorldPack.from_dict({**base, "extra": 1})
        with self.assertRaises(ValueError):
            WorldPack.from_dict({**base, "world_id": "坏 id"})

    def test_default_npc_keeps_unique_thinking_order(self):
        pack, pack_dir = load_builtin_world("honor_of_kings")
        profile = load_world_npc(pack_dir, pack.default_npc)
        self.assertEqual(profile.thinking_order[0], "duty")
        genshin, genshin_dir = load_builtin_world("genshin")
        vendor = load_world_npc(genshin_dir, genshin.default_npc)
        self.assertEqual(vendor.thinking_order[0], "curiosity")
        self.assertNotEqual(profile.thinking_order, vendor.thinking_order)

    def test_conversation_attaches_world_without_changing_engine_identity_rules(self):
        with tempfile.TemporaryDirectory() as temporary:
            pack, pack_dir = load_builtin_world("genshin")
            profile = load_world_npc(pack_dir, pack.default_npc)
            conversation = build_conversation(
                Settings(state_dir=Path(temporary)),
                profile=profile,
                world=pack,
                use_world_npc=False,
            )
            answer = conversation.reply("你是谁")
            self.assertIn(profile.name, answer)
            self.assertIn(pack.setting_name, answer)
            self.assertEqual(conversation.last_decision["world_id"], "genshin")
            self.assertEqual(
                conversation.last_decision["thinking_order"], list(profile.thinking_order)
            )
            self.assertEqual(conversation.knowledge.data_dir, pack_dir / "knowledge")

    def test_explicit_data_dir_overrides_world_knowledge(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            custom = root / "custom_lore"
            custom.mkdir()
            (custom / "note.txt").write_text("自定义资料", encoding="utf-8")
            pack, _ = load_builtin_world("minecraft")
            conversation = build_conversation(
                Settings(state_dir=root / "state", data_dir=custom),
                world=pack,
            )
            self.assertEqual(conversation.knowledge.data_dir, custom.resolve())

    def test_parse_world_json_roundtrip(self):
        pack, _ = load_builtin_world("open_world")
        again = parse_world_json(__import__("json").dumps(pack.to_dict(), ensure_ascii=False))
        self.assertEqual(again, pack)


if __name__ == "__main__":
    unittest.main()
