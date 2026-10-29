"""Transactional demo game state, independent of the model and user interface.

Progress events are trusted inputs from the demo controls (or a future game
server).  ``record_progress`` must never be exposed as a model tool.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class DomainError(ValueError):
    """A player action rejected by the game rules."""


class GameStateError(RuntimeError):
    """Local state cannot be opened or updated; existing data is preserved."""


TASK_STATUSES = frozenset({"进行中", "已完成", "已失败", "已放弃"})
DEMO_PLAYER_IDS = ("1001", "1002")


class GameService:
    """A player-bound repository and rule boundary for local demo state.

    Every operation opens its own connection, so a service can safely be used
    from separate UI requests or threads.  Task writes and reward issuance use
    SQLite write transactions, including the completion and duplicate checks.
    """

    def __init__(self, db_path: Path | str, player_id: str = "1001") -> None:
        if player_id not in DEMO_PLAYER_IDS:
            raise DomainError("演示玩家不存在，请选择 1001 或 1002。")
        self._player_id = player_id
        try:
            self.db_path = Path(db_path).expanduser().resolve()
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise GameStateError(
                "无法访问演示状态目录，请检查路径与目录权限；程序不会自动重置现有数据。"
            ) from exc
        self._initialize()

    @property
    def player_id(self) -> str:
        return self._player_id

    @contextmanager
    def _connection(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        connection = None
        try:
            connection = sqlite3.connect(self.db_path, timeout=15)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            if write:
                connection.execute("BEGIN IMMEDIATE")
            yield connection
            if write:
                connection.commit()
        except sqlite3.Error as exc:
            self._rollback(connection)
            raise GameStateError(
                "无法读取或写入演示状态数据库，请检查状态目录权限、磁盘空间或数据库是否损坏；"
                "程序不会自动重置现有数据。"
            ) from exc
        except BaseException:
            self._rollback(connection)
            raise
        finally:
            if connection is not None:
                try:
                    connection.close()
                except sqlite3.Error:
                    # Commit/rollback above already decided the transaction;
                    # cleanup must not hide the original actionable error.
                    pass

    @staticmethod
    def _rollback(connection: sqlite3.Connection | None) -> None:
        if connection is not None:
            try:
                connection.rollback()
            except sqlite3.Error:
                pass

    def _initialize(self) -> None:
        with self._connection(write=True) as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS players (
                    player_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    level INTEGER NOT NULL,
                    profession TEXT NOT NULL,
                    region TEXT NOT NULL,
                    story_progress TEXT NOT NULL,
                    gold INTEGER NOT NULL DEFAULT 0 CHECK (gold >= 0),
                    experience INTEGER NOT NULL DEFAULT 0 CHECK (experience >= 0)
                )"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS tasks (
                    player_id TEXT NOT NULL REFERENCES players(player_id),
                    task_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (
                        status IN ('进行中', '已完成', '已失败', '已放弃')
                    ),
                    progress INTEGER NOT NULL CHECK (progress >= 0),
                    target INTEGER NOT NULL CHECK (target > 0 AND progress <= target),
                    reward_gold INTEGER NOT NULL CHECK (reward_gold >= 0),
                    reward_experience INTEGER NOT NULL CHECK (reward_experience >= 0),
                    reward_claimed INTEGER NOT NULL DEFAULT 0
                        CHECK (reward_claimed IN (0, 1)),
                    PRIMARY KEY (player_id, task_id)
                )"""
            )
            connection.executemany(
                """INSERT OR IGNORE INTO players
                   (player_id, name, level, profession, region, story_progress)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    ("1001", "旅行者一号", 8, "游侠", "新手村", "第一章：初抵村庄"),
                    ("1002", "旅行者二号", 6, "学者", "新手村", "第一章：初抵村庄"),
                ],
            )
            for player_id in DEMO_PLAYER_IDS:
                connection.executemany(
                    """INSERT OR IGNORE INTO tasks
                       (player_id, task_id, name, description, status, progress,
                        target, reward_gold, reward_experience)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [
                        (
                            player_id,
                            "T001",
                            "采集药草",
                            "为村中的药师采集三株药草。",
                            "进行中",
                            0,
                            3,
                            30,
                            60,
                        ),
                        (
                            player_id,
                            "T002",
                            "传递问候",
                            "已将村长的问候带给守卫，可领取奖励。",
                            "已完成",
                            1,
                            1,
                            20,
                            40,
                        ),
                    ],
                )

    def player_info(self) -> dict:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM players WHERE player_id = ?", (self.player_id,)
            ).fetchone()
        if row is None:
            raise DomainError("当前玩家不存在。")
        return {**dict(row), "source": "demo"}

    @staticmethod
    def _task_result(row: sqlite3.Row) -> dict:
        return {
            "player_id": row["player_id"],
            "task_id": row["task_id"],
            "name": row["name"],
            "description": row["description"],
            "status": row["status"],
            "progress": row["progress"],
            "target": row["target"],
            "reward": {
                "gold": row["reward_gold"],
                "experience": row["reward_experience"],
            },
            "reward_claimed": bool(row["reward_claimed"]),
            "source": "demo",
        }

    def _find_task(self, connection: sqlite3.Connection, task_id: str) -> sqlite3.Row:
        if not isinstance(task_id, str) or not task_id.strip():
            raise DomainError("任务 ID 不能为空。")
        row = connection.execute(
            "SELECT * FROM tasks WHERE player_id = ? AND task_id = ?",
            (self.player_id, task_id),
        ).fetchone()
        if row is None:
            raise DomainError("当前玩家没有该任务。")
        return row

    def player_tasks(self) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM tasks WHERE player_id = ? ORDER BY task_id",
                (self.player_id,),
            ).fetchall()
        return [self._task_result(row) for row in rows]

    def update_task(self, task_id: str, task_status: str) -> dict:
        """Change status after validating persisted, trusted progress."""
        if not isinstance(task_status, str) or task_status not in TASK_STATUSES:
            raise DomainError("任务状态仅支持：进行中、已完成、已失败、已放弃。")
        with self._connection(write=True) as connection:
            task = self._find_task(connection, task_id)
            if task["status"] == task_status:
                return self._task_result(task)
            if task["status"] != "进行中":
                raise DomainError("任务已结束，不能再次改变状态。")
            if task_status == "已完成" and task["progress"] < task["target"]:
                raise DomainError("可信游戏事件记录的目标进度尚未完成，不能交付任务。")
            connection.execute(
                "UPDATE tasks SET status = ? WHERE player_id = ? AND task_id = ?",
                (task_status, self.player_id, task_id),
            )
            return self._task_result(self._find_task(connection, task_id))

    def record_progress(self, task_id: str, progress: int) -> dict:
        """Record an absolute progress value from a trusted game event only.

        This method is intentionally separate from model-callable task tools.
        A player's claim in a chat message is not a trusted progress event.
        """
        if type(progress) is not int:
            raise DomainError("进度必须为整数。")
        with self._connection(write=True) as connection:
            task = self._find_task(connection, task_id)
            if task["status"] != "进行中":
                raise DomainError("任务已结束，不能再记录进度。")
            if progress < task["progress"] or progress > task["target"]:
                raise DomainError("进度只能增加，且不能超过任务目标。")
            connection.execute(
                "UPDATE tasks SET progress = ? WHERE player_id = ? AND task_id = ?",
                (progress, self.player_id, task_id),
            )
            return self._task_result(self._find_task(connection, task_id))

    def grant_reward(self, task_id: str) -> dict:
        """Issue a completed task's fixed reward once, atomically."""
        with self._connection(write=True) as connection:
            task = self._find_task(connection, task_id)
            if task["status"] != "已完成" or task["progress"] < task["target"]:
                raise DomainError("任务尚未完成，不能领取奖励。")
            granted = not bool(task["reward_claimed"])
            if granted:
                connection.execute(
                    """UPDATE tasks SET reward_claimed = 1
                       WHERE player_id = ? AND task_id = ?""",
                    (self.player_id, task_id),
                )
                connection.execute(
                    """UPDATE players SET gold = gold + ?, experience = experience + ?
                       WHERE player_id = ?""",
                    (task["reward_gold"], task["reward_experience"], self.player_id),
                )
            player = connection.execute(
                "SELECT gold, experience FROM players WHERE player_id = ?",
                (self.player_id,),
            ).fetchone()
            return {
                "player_id": self.player_id,
                "task_id": task_id,
                "granted": granted,
                "reward": {
                    "gold": task["reward_gold"],
                    "experience": task["reward_experience"],
                },
                "balances": dict(player),
                "source": "demo",
            }
