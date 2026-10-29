"""Cross-platform regressions for Windows home lookup and redirected text output.

These tests reproduce the failed assumptions without pretending that the host is
Windows. The subprocess tests deliberately start with a legacy output encoding.
"""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from game_npc.cli import main
from game_npc.config import Settings


class MissingHomeTests(unittest.TestCase):
    def test_explicit_environment_state_directory_never_queries_home(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary) / "explicit-env-state"
            with (
                patch.dict(os.environ, {"GAME_NPC_STATE_DIR": str(state)}, clear=True),
                patch.object(Path, "home", side_effect=RuntimeError("home unavailable")) as home,
            ):
                settings = Settings.from_env()
            self.assertEqual(settings.state_dir, state.resolve())
            home.assert_not_called()
            self.assertFalse(state.exists())

    def test_argument_state_directory_takes_precedence_without_home_lookup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            argument_state = root / "argument-state"
            environment_state = root / "environment-state"
            with (
                patch.dict(os.environ, {"GAME_NPC_STATE_DIR": str(environment_state)}, clear=True),
                patch.object(Path, "home", side_effect=RuntimeError("home unavailable")) as home,
            ):
                settings = Settings.from_env(state_dir=argument_state)
            self.assertEqual(settings.state_dir, argument_state.resolve())
            home.assert_not_called()
            self.assertFalse(argument_state.exists())
            self.assertFalse(environment_state.exists())

    def test_doctor_honors_cli_directory_in_an_environment_without_home(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary) / "doctor-state"
            output, error = io.StringIO(), io.StringIO()
            with (
                patch.dict(os.environ, {}, clear=True),
                patch.object(Path, "home", side_effect=RuntimeError("home unavailable")) as home,
                redirect_stdout(output),
                redirect_stderr(error),
            ):
                result = main(["--state-dir", str(state), "doctor"])
            self.assertEqual(result, 0, error.getvalue())
            self.assertEqual(json.loads(output.getvalue())["state_dir"], str(state.resolve()))
            self.assertEqual(error.getvalue(), "")
            home.assert_not_called()
            self.assertFalse(state.exists())

    def test_metadata_commands_need_neither_home_nor_runtime_state(self):
        commands = (
            ["providers", "--json"],
            ["npc", "--sample", "guard"],
            ["world", "--list"],
            ["world", "--sample", "minecraft"],
        )
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary) / "unused-state"
            for command in commands:
                with self.subTest(command=command):
                    output, error = io.StringIO(), io.StringIO()
                    with (
                        patch.dict(os.environ, {"GAME_NPC_STATE_DIR": str(state)}, clear=True),
                        patch.object(
                            Path, "home", side_effect=RuntimeError("home unavailable")
                        ) as home,
                        patch.object(
                            Settings,
                            "from_env",
                            side_effect=AssertionError("metadata must not initialize settings"),
                        ),
                        redirect_stdout(output),
                        redirect_stderr(error),
                    ):
                        result = main(command)
                    self.assertEqual(result, 0, error.getvalue())
                    self.assertIsInstance(json.loads(output.getvalue()), (list, dict))
                    self.assertEqual(error.getvalue(), "")
                    home.assert_not_called()
                    self.assertFalse(state.exists())

    def test_unavailable_home_without_override_fails_without_cwd_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            previous = Path.cwd()
            output, error = io.StringIO(), io.StringIO()
            try:
                os.chdir(root)
                with (
                    patch.dict(os.environ, {}, clear=True),
                    patch.object(Path, "home", side_effect=RuntimeError("home unavailable")),
                    redirect_stdout(output),
                    redirect_stderr(error),
                ):
                    result = main(["doctor"])
                self.assertEqual(result, 1)
                self.assertTrue(error.getvalue().strip())
                self.assertNotIn("Traceback", error.getvalue())
                self.assertEqual(output.getvalue(), "")
                self.assertEqual(list(root.iterdir()), [])
            finally:
                os.chdir(previous)


class RedirectedEncodingTests(unittest.TestCase):
    def run_cli(self, arguments, state):
        # Keep OS runtime variables such as SystemRoot, but remove application
        # configuration so a developer's provider or API key cannot affect a test.
        environment = {
            name: value
            for name, value in os.environ.items()
            if not name.startswith("GAME_NPC_") and not name.endswith("API_KEY")
        }
        environment.update(
            {
                "PYTHONIOENCODING": "cp1252",
                "PYTHONUTF8": "0",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
                "GAME_NPC_MODE": "demo",
                "GAME_NPC_RETRIEVAL": "local",
                "GAME_NPC_STATE_DIR": str(state),
            }
        )
        return subprocess.run(
            [sys.executable, "-m", "game_npc", *arguments],
            cwd=state.parent,
            env=environment,
            capture_output=True,
            timeout=20,
            check=False,
        )

    def test_doctor_emits_utf8_json_despite_legacy_redirected_stdout(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary) / "doctor-state"
            result = self.run_cli(["doctor"], state)
            self.assertEqual(
                result.returncode, 0, result.stderr.decode("utf-8", "backslashreplace")
            )
            document = json.loads(result.stdout.decode("utf-8"))
            self.assertEqual(document["npc"]["name"], "林守溪")
            self.assertEqual(document["state_dir"], str(state.resolve()))
            self.assertEqual(result.stderr, b"")
            self.assertFalse(state.exists())

    def test_npc_template_preserves_chinese_through_legacy_redirected_stdout(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary) / "unused-state"
            result = self.run_cli(["npc", "--sample", "guard"], state)
            self.assertEqual(
                result.returncode, 0, result.stderr.decode("utf-8", "backslashreplace")
            )
            document = json.loads(result.stdout.decode("utf-8"))
            self.assertEqual(document["name"], "沈砺")
            self.assertIn("守卫", document["profession"])
            self.assertEqual(result.stderr, b"")
            self.assertFalse(state.exists())

    def test_missing_index_retains_nonzero_exit_and_readable_utf8_stderr(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary) / "empty-index-state"
            result = self.run_cli(["chat", "NPC 对话规范"], state)
            self.assertEqual(result.returncode, 1)
            error = result.stderr.decode("utf-8")
            self.assertIn("知识", error)
            self.assertIn("ingest", error)
            self.assertNotIn("charmap", error)
            self.assertNotIn("UnicodeEncodeError", error)
            self.assertNotIn("Traceback", error)
            self.assertEqual(result.stdout, b"")


if __name__ == "__main__":
    unittest.main()
