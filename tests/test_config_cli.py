import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from game_npc.cli import main
from game_npc.config import Settings, load_prompt


class ConfigCliTests(unittest.TestCase):
    def test_invalid_settings_are_rejected_without_io(self):
        for overrides in (
            {"mode": "bad"},
            {"retrieval": "bad"},
            {"max_tool_calls": 0},
            {"base_url": "http://example.org"},
            {"history_turns": 0},
            {"model": ""},
            {"base_url": "https://key@example.org/v1"},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                Settings(**overrides)

    def test_env_paths_and_key_redaction(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.dict(
                os.environ,
                {
                    "GAME_NPC_STATE_DIR": temporary,
                    "GAME_NPC_MODE": "live",
                    "GAME_NPC_API_KEY": "secret-test-value",
                },
                clear=True,
            ),
        ):
            settings = Settings.from_env()
            self.assertEqual(settings.state_dir, Path(temporary).resolve())
            self.assertNotIn("secret-test-value", repr(settings))
            settings.require_online()

    def test_provider_presets_fill_model_and_base_url(self):
        settings = Settings(provider="deepseek", api_key="x")
        self.assertEqual(settings.provider, "deepseek")
        self.assertEqual(settings.model, "deepseek-chat")
        self.assertIn("deepseek.com", settings.base_url)
        openai = Settings(provider="openai", model="gpt-4o", api_key="x")
        self.assertEqual(openai.model, "gpt-4o")
        with self.assertRaises(ValueError):
            Settings(provider="custom", api_key="x")

    def test_prompts_are_packaged(self):
        self.assertIn("报告", load_prompt("report"))
        self.assertIn("最终答复", load_prompt("dialogue"))
        with self.assertRaises(ValueError):
            load_prompt("../config")

    def test_cli_ingest_doctor_and_chat_from_any_cwd(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {}, clear=True):
            root = Path(temporary)
            data = root / "data"
            data.mkdir()
            (data / "rules.txt").write_text("村长负责发布任务，药师需要药草。", encoding="utf-8")
            with patch.dict(os.environ, {"GAME_NPC_DATA_DIR": str(data)}):
                output, error = io.StringIO(), io.StringIO()
                with redirect_stdout(output), redirect_stderr(error):
                    self.assertEqual(main(["--state-dir", str(root / "state"), "doctor"]), 0)
                    # Doctor must not create a database as a side effect.
                    self.assertFalse((root / "state").exists())
                    self.assertEqual(main(["--state-dir", str(root / "state"), "ingest"]), 0)
                    self.assertEqual(main(["--state-dir", str(root / "state"), "chat", "药草"]), 0)
                    self.assertEqual(main(["--state-dir", str(root / "state"), "chat", "你好"]), 0)
                self.assertIn("rules.txt", output.getvalue())
                self.assertEqual(error.getvalue(), "")

    def test_live_doctor_returns_failure_without_exposing_secrets(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {}, clear=True):
            output = io.StringIO()
            with redirect_stdout(output):
                result = main(["--state-dir", temporary, "--mode", "live", "doctor"])
            self.assertEqual(result, 1)
            self.assertIn("GAME_NPC_API_KEY", json.loads(output.getvalue())["problems"][0])

    def test_bad_configuration_is_concise_nonzero_error(self):
        with (
            patch.dict(os.environ, {"GAME_NPC_MODE": "invalid"}),
            redirect_stderr(io.StringIO()) as out,
        ):
            self.assertEqual(main(["doctor"]), 1)
            self.assertNotIn("Traceback", out.getvalue())


if __name__ == "__main__":
    unittest.main()
