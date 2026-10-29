"""Game rules exercised without an API key, network, or UI."""

import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

from game_npc.domain import DomainError, GameService, GameStateError


class GameServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.db_path = Path(self.temporary_directory.name) / "state" / "game.sqlite3"
        self.game = GameService(self.db_path)

    def task(self, task_id: str, service: GameService | None = None) -> dict:
        return next(
            task for task in (service or self.game).player_tasks() if task["task_id"] == task_id
        )

    def test_demo_identity_and_tasks_are_stable_and_explicit(self) -> None:
        self.assertEqual(self.game.player_info()["player_id"], "1001")
        self.assertEqual(self.game.player_info()["source"], "demo")
        self.assertEqual(self.game.player_info(), self.game.player_info())
        task = self.task("T001")
        self.assertEqual((task["progress"], task["target"], task["status"]), (0, 3, "进行中"))
        self.assertEqual(task["source"], "demo")
        with self.assertRaises(DomainError):
            GameService(self.db_path, "unknown")

    def test_completion_requires_trusted_progress(self) -> None:
        with self.assertRaises(DomainError):
            self.game.update_task("T001", "已完成")
        with self.assertRaises(DomainError):
            self.game.grant_reward("T001")
        self.game.record_progress("T001", 2)
        with self.assertRaises(DomainError):
            self.game.update_task("T001", "已完成")
        self.game.record_progress("T001", 3)
        completed = self.game.update_task("T001", "已完成")
        self.assertEqual(completed["status"], "已完成")
        result = self.game.grant_reward("T001")
        self.assertTrue(result["granted"])
        self.assertEqual(result["balances"], {"gold": 30, "experience": 60})

    def test_invalid_status_and_terminal_transitions_are_rejected(self) -> None:
        for invalid in ("完成", "unknown", "", None, [], 1):
            with self.subTest(status=invalid), self.assertRaises(DomainError):
                self.game.update_task("T001", invalid)
        self.assertEqual(self.game.update_task("T001", "进行中")["status"], "进行中")
        self.game.update_task("T001", "已失败")
        for status in ("进行中", "已完成", "已放弃"):
            with self.subTest(status=status), self.assertRaises(DomainError):
                self.game.update_task("T001", status)
        self.assertEqual(self.game.update_task("T001", "已失败")["status"], "已失败")
        with self.assertRaises(DomainError):
            self.game.record_progress("T001", 1)
        with self.assertRaises(DomainError):
            self.game.grant_reward("T001")

    def test_abandoned_task_cannot_resume_or_receive_rewards(self) -> None:
        self.game.update_task("T001", "已放弃")
        with self.assertRaises(DomainError):
            self.game.update_task("T001", "进行中")
        with self.assertRaises(DomainError):
            self.game.grant_reward("T001")

    def test_progress_is_bounded_and_monotonic(self) -> None:
        for invalid in (-1, 4, True, "3", 1.5):
            with self.subTest(progress=invalid), self.assertRaises(DomainError):
                self.game.record_progress("T001", invalid)
        self.game.record_progress("T001", 2)
        self.assertEqual(self.game.record_progress("T001", 2)["progress"], 2)
        with self.assertRaises(DomainError):
            self.game.record_progress("T001", 1)
        self.assertEqual(self.task("T001")["progress"], 2)

    def test_rewards_are_persistent_and_idempotent(self) -> None:
        first = self.game.grant_reward("T002")
        self.assertTrue(first["granted"])
        self.assertEqual(first["reward"], {"gold": 20, "experience": 40})
        reopened = GameService(str(self.db_path), "1001")
        second = reopened.grant_reward("T002")
        self.assertFalse(second["granted"])
        self.assertEqual(second["balances"], first["balances"])
        self.assertTrue(self.task("T002", reopened)["reward_claimed"])
        self.assertEqual(reopened.player_info()["gold"], 20)

    def test_task_progress_and_status_survive_reopening(self) -> None:
        self.game.record_progress("T001", 3)
        self.game.update_task("T001", "已完成")
        reopened = GameService(self.db_path)
        self.assertEqual(self.task("T001", reopened)["progress"], 3)
        self.assertEqual(self.task("T001", reopened)["status"], "已完成")

    def test_players_cannot_read_or_modify_each_others_state(self) -> None:
        other = GameService(self.db_path, "1002")
        self.game.record_progress("T001", 2)
        self.game.grant_reward("T002")
        self.assertEqual(self.task("T001", other)["progress"], 0)
        self.assertFalse(self.task("T002", other)["reward_claimed"])
        self.assertEqual(other.player_info()["gold"], 0)
        self.assertTrue(all(task["player_id"] == "1002" for task in other.player_tasks()))
        # A task belonging only to the other player remains inaccessible even
        # if its identifier is known to this player.
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            connection.execute(
                """INSERT INTO tasks
                   (player_id, task_id, name, description, status, progress,
                    target, reward_gold, reward_experience)
                   VALUES ('1002', 'PRIVATE', '私人任务', '仅属于 1002', '进行中', 0, 1, 1, 1)"""
            )
        self.assertNotIn("PRIVATE", [task["task_id"] for task in self.game.player_tasks()])
        for operation in (
            lambda: self.game.update_task("PRIVATE", "已放弃"),
            lambda: self.game.record_progress("PRIVATE", 1),
            lambda: self.game.grant_reward("PRIVATE"),
        ):
            with self.assertRaises(DomainError):
                operation()
        self.assertEqual(self.task("PRIVATE", other)["status"], "进行中")

    def test_missing_task_and_sql_injection_are_rejected(self) -> None:
        for task_id in ("missing", "T001' OR 1=1 --", "", None):
            with self.subTest(task_id=task_id), self.assertRaises(DomainError):
                self.game.update_task(task_id, "已放弃")
        self.assertEqual(self.task("T001")["status"], "进行中")

    def test_concurrent_reward_claims_issue_exactly_once(self) -> None:
        services = [GameService(self.db_path) for _ in range(8)]
        barrier = threading.Barrier(len(services))

        def claim(service: GameService) -> dict:
            barrier.wait(timeout=10)
            return service.grant_reward("T002")

        with ThreadPoolExecutor(max_workers=len(services)) as pool:
            results = list(pool.map(claim, services))
        self.assertEqual(sum(result["granted"] for result in results), 1)
        self.assertTrue(
            all(result["balances"] == {"gold": 20, "experience": 40} for result in results)
        )
        self.assertEqual(self.game.player_info()["gold"], 20)
        self.assertEqual(self.game.player_info()["experience"], 40)

    def test_corrupt_database_returns_actionable_error_without_replacing_file(self) -> None:
        corrupt_path = Path(self.temporary_directory.name) / "corrupt.sqlite3"
        original_content = b"this is not a SQLite database\x00keep existing data"
        corrupt_path.write_bytes(original_content)
        with self.assertRaisesRegex(GameStateError, "数据库是否损坏") as raised:
            GameService(corrupt_path)
        self.assertIsInstance(raised.exception.__cause__, sqlite3.DatabaseError)
        self.assertEqual(corrupt_path.read_bytes(), original_content)

    def test_database_path_cannot_be_a_directory(self) -> None:
        directory_path = Path(self.temporary_directory.name) / "database-directory"
        directory_path.mkdir()
        sentinel = directory_path / "keep.txt"
        sentinel.write_text("preserve", encoding="utf-8")
        with self.assertRaisesRegex(GameStateError, "状态目录权限"):
            GameService(directory_path)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")

    def test_parent_path_cannot_be_a_file(self) -> None:
        parent_file = Path(self.temporary_directory.name) / "not-a-directory"
        parent_file.write_text("preserve", encoding="utf-8")
        with self.assertRaisesRegex(GameStateError, "状态目录"):
            GameService(parent_file / "game.sqlite3")
        self.assertEqual(parent_file.read_text(encoding="utf-8"), "preserve")

    def test_runtime_database_failure_is_wrapped_without_resetting_state(self) -> None:
        self.game.grant_reward("T002")
        # Simulate a database that became unavailable after construction.
        self.db_path.rename(self.db_path.with_suffix(".saved"))
        self.db_path.mkdir()
        with self.assertRaises(GameStateError):
            self.game.player_info()
        self.db_path.rmdir()
        self.db_path.with_suffix(".saved").rename(self.db_path)
        self.assertEqual(self.game.player_info()["gold"], 20)


if __name__ == "__main__":
    unittest.main()
