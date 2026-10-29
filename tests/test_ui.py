"""Optional Streamlit integration tests; core-only installations skip this file."""

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


@unittest.skipUnless(importlib.util.find_spec("streamlit"), "requires [ui] extra")
class UiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        data = root / "data"
        data.mkdir()
        (data / "rules.txt").write_text("村长发布任务，完成任务后领取奖励。", encoding="utf-8")
        self.env = patch.dict(
            os.environ,
            {
                "GAME_NPC_STATE_DIR": str(root / "state"),
                "GAME_NPC_DATA_DIR": str(data),
                "GAME_NPC_MODE": "demo",
                "GAME_NPC_RETRIEVAL": "local",
                "DASHSCOPE_API_KEY": "",
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        from streamlit.testing.v1 import AppTest

        from game_npc import ui

        self.app = AppTest.from_file(ui.__file__, default_timeout=15)

    def test_demo_chat_reward_report_and_player_switch(self):
        app = self.app.run()
        self.assertFalse(app.exception)
        app.chat_input[0].set_value("你好").run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.session_state["conversation"].history), 2)
        app.chat_input[0].set_value("领取 T002 奖励").run()
        self.assertEqual(app.session_state["conversation"].game.player_info()["gold"], 20)
        app.toggle[0].set_value(True).run()
        app.chat_input[0].set_value("领取 T002 奖励").run()
        self.assertIn("报告", app.session_state["conversation"].history[-1]["content"])
        app.selectbox[1].set_value("1002").run()
        self.assertEqual(app.session_state["conversation"].game.player_info()["gold"], 0)
        self.assertEqual(app.session_state["conversation"].history, [])
        self.assertFalse(app.exception)

    def test_build_index_and_missing_online_key(self):
        app = self.app.run()
        next(button for button in app.button if button.label == "构建 / 同步知识库").click().run()
        self.assertTrue(app.session_state["conversation"].knowledge.status()["ready"])
        app.selectbox[0].set_value("live").run()
        self.assertTrue(app.chat_input[0].disabled)
        self.assertTrue(any("DASHSCOPE_API_KEY" in item.value for item in app.warning))
        self.assertFalse(app.exception)


if __name__ == "__main__":
    unittest.main()
