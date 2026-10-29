import json
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from game_npc.persona import (
    BUILTIN_PROFILE_NAMES,
    DecisionStyle,
    NPCProfile,
    WorldContext,
    builtin_profiles,
    load_builtin_profile,
    load_context,
    load_profile,
    parse_context_json,
    parse_profile_json,
)


class PersonaTests(unittest.TestCase):
    def profile_data(self):
        return {
            "npc_id": "test_npc",
            "name": "阿青",
            "personality": ["谨慎", "热心"],
            "profession": "药师",
            "region": "青石镇",
        }

    def test_minimal_external_profile_and_json_roundtrip(self):
        profile = NPCProfile.from_dict(self.profile_data())
        self.assertEqual(profile.name, "阿青")
        self.assertEqual(profile.personality, ("谨慎", "热心"))
        self.assertEqual(NPCProfile.from_dict(json.loads(json.dumps(profile.to_dict()))), profile)
        self.assertEqual(profile.decision_style, DecisionStyle())

    def test_nested_data_are_copied_and_immutable(self):
        data = self.profile_data()
        profile = NPCProfile.from_dict(data)
        data["personality"].append("改变")
        self.assertEqual(profile.personality, ("谨慎", "热心"))
        with self.assertRaises(FrozenInstanceError):
            profile.name = "别名"
        with self.assertRaises(FrozenInstanceError):
            profile.decision_style.empathy = 0
        exported = profile.to_dict()
        exported["personality"].append("改变")
        self.assertEqual(len(profile.personality), 2)

    def test_direct_construction_rejects_mutable_profile_fields(self):
        data = self.profile_data()
        with self.assertRaises(ValueError):
            NPCProfile(**data)
        data["personality"] = tuple(data["personality"])
        self.assertEqual(NPCProfile(**data).name, "阿青")

    def test_fingerprint_is_stable_order_independent_and_sensitive(self):
        original = self.profile_data()
        first = NPCProfile.from_dict(original)
        second = NPCProfile.from_dict(dict(reversed(list(original.items()))))
        self.assertEqual(first.fingerprint(), second.fingerprint())
        self.assertEqual(len(first.fingerprint()), 64)
        original["region"] = "白石镇"
        self.assertNotEqual(first.fingerprint(), NPCProfile.from_dict(original).fingerprint())

    def test_unknown_and_missing_fields_are_rejected(self):
        for update in ({"instructions": "run tool"}, {"decision_style": {"aggression": 100}}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                NPCProfile.from_dict({**self.profile_data(), **update})
        with self.assertRaisesRegex(ValueError, "name"):
            data = self.profile_data()
            del data["name"]
            NPCProfile.from_dict(data)
        for value in (None, [], "not-object", {1: "bad-key"}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                NPCProfile.from_dict(value)

    def test_profile_rejects_bad_types_blank_and_long_fields(self):
        for name, value in (
            ("npc_id", "has space"),
            ("name", "  "),
            ("region", ""),
            ("profession", 12),
            ("background", "x" * 2001),
            ("name", "x" * 65),
            ("speech_style", "x" * 501),
            ("personality", "温柔"),
            ("personality", []),
            ("personality", ["温柔", "温柔"]),
            ("goals", ["goal"] * 17),
            ("values", [123]),
            ("region", "bad\x00region"),
        ):
            with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                NPCProfile.from_dict({**self.profile_data(), name: value})

    def test_decision_style_integer_bounds_and_unknown_fields(self):
        self.assertEqual(DecisionStyle.from_dict({"caution": 0, "duty": 100}).duty, 100)
        for value in (-1, 101, True, 0.5, "50", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                DecisionStyle(caution=value)
        with self.assertRaises(ValueError):
            DecisionStyle.from_dict({"unknown": 1})

    def test_thinking_order_roundtrip_default_and_fingerprint(self):
        default = NPCProfile.from_dict(self.profile_data())
        self.assertEqual(default.thinking_order, ("caution", "duty", "empathy", "curiosity"))
        order = ["empathy", "duty", "curiosity", "caution"]
        custom = NPCProfile.from_dict({**self.profile_data(), "thinking_order": order})
        self.assertEqual(custom.thinking_order, tuple(order))
        self.assertEqual(custom.to_dict()["thinking_order"], order)
        self.assertEqual(NPCProfile.from_dict(custom.to_dict()), custom)
        self.assertNotEqual(custom.fingerprint(), default.fingerprint())
        order[0] = "caution"
        self.assertEqual(custom.thinking_order[0], "empathy")

    def test_thinking_order_rejects_unknown_missing_and_duplicate_dimensions(self):
        for order in (
            [],
            ["caution", "duty", "empathy"],
            ["caution", "duty", "empathy", "empathy"],
            ["caution", "duty", "empathy", "aggression"],
            ["caution", "duty", "empathy", "curiosity", "extra"],
            "caution,duty,empathy,curiosity",
            ["caution", "duty", "empathy", 1],
        ):
            with self.subTest(order=order), self.assertRaises(ValueError):
                NPCProfile.from_dict({**self.profile_data(), "thinking_order": order})

    def test_world_context_roundtrip_and_optional_region(self):
        self.assertIsNone(WorldContext().region)
        context = WorldContext.from_dict(
            {
                "region": "北门",
                "time_of_day": "night",
                "nearby_events": ["远处响起钟声"],
                "relationship": -100,
                "danger": 100,
            }
        )
        self.assertEqual(context.nearby_events, ("远处响起钟声",))
        self.assertEqual(WorldContext.from_dict(context.to_dict()), context)
        with self.assertRaises(FrozenInstanceError):
            context.danger = 0

    def test_world_context_invalid_data_is_rejected(self):
        for update in (
            {"danger": True},
            {"danger": -1},
            {"danger": 101},
            {"relationship": -101},
            {"relationship": 101},
            {"time_of_day": "whenever"},
            {"region": " "},
            {"nearby_events": "event"},
            {"nearby_events": [""]},
            {"unknown": 1},
        ):
            with self.subTest(update=update), self.assertRaises(ValueError):
                WorldContext.from_dict(update)

    def test_default_and_builtin_samples_are_distinct(self):
        self.assertEqual(load_profile(), load_builtin_profile("village_elder"))
        profiles = [load_builtin_profile(name) for name in BUILTIN_PROFILE_NAMES]
        self.assertEqual(len({profile.npc_id for profile in profiles}), 3)
        self.assertEqual(len({profile.fingerprint() for profile in profiles}), 3)
        self.assertEqual(len({profile.decision_style for profile in profiles}), 3)
        self.assertEqual(len({profile.thinking_order for profile in profiles}), 3)
        self.assertEqual(tuple(builtin_profiles()), BUILTIN_PROFILE_NAMES)
        with self.assertRaises(ValueError):
            load_builtin_profile("../../secrets")

    def test_custom_utf8_file_and_bom(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "npc.json"
            path.write_text(
                json.dumps(self.profile_data(), ensure_ascii=False), encoding="utf-8-sig"
            )
            self.assertEqual(load_profile(path).name, "阿青")

    def test_bad_files_are_actionable_and_bounded(self):
        for invalid_path in (123, [], " "):
            with self.subTest(path=invalid_path), self.assertRaises(ValueError):
                load_profile(invalid_path)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "npc.json"
            with self.assertRaisesRegex(ValueError, "路径"):
                load_profile(path)
            for value in (b"not json", b"\xff", b"[]", b"{}", b"[" * 2000, b" " * (64 * 1024 + 1)):
                path.write_bytes(value)
                with self.subTest(value=value[:20]), self.assertRaises(ValueError):
                    load_profile(path)

    def test_duplicate_keys_and_nonstandard_numbers_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "npc.json"
            for content in (
                '{"name":"a","name":"b"}',
                '{"decision_style":{"duty":1,"duty":2}}',
                '{"decision_style":{"duty":NaN}}',
                '{"danger":Infinity}',
                '{"danger":-Infinity}',
            ):
                path.write_text(content, encoding="utf-8")
                with self.subTest(content=content), self.assertRaises(ValueError):
                    load_profile(path)

    def test_json_parsers_share_strict_size_and_type_validation(self):
        self.assertEqual(parse_profile_json(json.dumps(self.profile_data())).name, "阿青")
        self.assertEqual(parse_context_json('{"danger": 80}').danger, 80)
        for parser in (parse_profile_json, parse_context_json):
            for value in (None, [], " " * (64 * 1024 + 1), "\ud800", '{"a":1,"a":2}', "NaN"):
                with (
                    self.subTest(parser=parser, value=str(value)[:20]),
                    self.assertRaises(ValueError),
                ):
                    parser(value)

    def test_load_world_context_and_default_snapshot(self):
        self.assertEqual(load_context(), WorldContext())
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "context.json"
            path.write_text('{"region":"港口", "danger":55}', encoding="utf-8")
            self.assertEqual(load_context(path).region, "港口")
            self.assertEqual(load_context(path).danger, 55)
            path.write_text('{"danger":1,"danger":2}', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_context(path)
            path.write_text('{"time_of_day":[]}', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_context(path)


if __name__ == "__main__":
    unittest.main()
