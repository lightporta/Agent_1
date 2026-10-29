import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from game_npc.knowledge import EmptyIndexError, KnowledgeBase, KnowledgeBaseError


class FakeCollection:
    def __init__(self):
        self.documents = []
        self.metadatas = []

    def add(self, *, ids, documents, metadatas, embeddings):
        self.documents.extend(documents)
        self.metadatas.extend(metadatas)

    def query(self, *, query_embeddings, n_results, include):
        return {
            "documents": [self.documents[:n_results]],
            "metadatas": [self.metadatas[:n_results]],
            "distances": [[0.1] * min(n_results, len(self.documents))],
        }


class FakeVectorClient:
    def __init__(self):
        self.collections = {}

    def create_collection(self, *, name, metadata, embedding_function=None):
        collection = FakeCollection()
        self.collections[name] = collection
        return collection

    def get_collection(self, name, embedding_function=None):
        return self.collections[name]

    def delete_collection(self, name):
        del self.collections[name]


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.data = self.root / "data"
        self.state = self.root / "state"
        self.data.mkdir()
        self.knowledge = KnowledgeBase(self.data, self.state)

    def write(self, source, text):
        path = self.data / source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_new_instance_has_no_side_effect_and_requires_ingest(self):
        self.assertFalse(self.state.exists())
        self.assertFalse(self.knowledge.status()["ready"])
        self.assertFalse(self.state.exists())
        with self.assertRaisesRegex(EmptyIndexError, "ingest"):
            self.knowledge.search("任务")

    def test_chinese_retrieval_and_relative_source(self):
        self.write("规范/任务.MD", "玩家完成任务后，可以领取金币奖励。")
        self.write("dialogue.txt", "村长会热情问候来到村庄的客人。")
        result = self.knowledge.ingest()
        self.assertEqual(result, {"added": 2, "updated": 0, "deleted": 0, "chunks": 2, "files": 2})
        matches = self.knowledge.search("任务奖励")
        self.assertEqual(matches[0]["source"], "规范/任务.MD")
        self.assertIn("金币奖励", matches[0]["text"])
        self.assertGreater(matches[0]["score"], 0)
        self.assertEqual(self.knowledge.search("unrelatedkeyword"), [])
        self.assertTrue(self.knowledge.status()["ready"])

    def test_latin_retrieval_is_case_insensitive(self):
        self.write("guide.txt", "Blacksmith repairs armor and weapons.")
        self.knowledge.ingest()
        self.assertEqual(len(self.knowledge.search("BLACKSMITH")), 1)

    def test_second_ingest_is_idempotent_and_persists(self):
        self.write("任务.txt", "收集野狼皮后交付给村长。")
        self.knowledge.ingest()
        before = self.knowledge.search("野狼皮")
        result = self.knowledge.ingest()
        self.assertEqual(result["added"], 0)
        self.assertEqual(result["updated"], 0)
        self.assertEqual(result["deleted"], 0)
        self.assertEqual(result["chunks"], 1)
        reopened = KnowledgeBase(self.data, self.state)
        self.assertEqual(reopened.search("野狼皮"), before)

    def test_changed_file_replaces_old_content(self):
        self.write("任务.txt", "玩家收集野狼皮。")
        self.knowledge.ingest()
        self.write("任务.txt", "旅人寻找神秘水晶。")
        result = self.knowledge.ingest()
        self.assertEqual(result["updated"], 1)
        self.assertEqual(result["chunks"], 1)
        self.assertEqual(self.knowledge.search("野狼皮"), [])
        self.assertIn("水晶", self.knowledge.search("水晶")[0]["text"])

    def test_deleted_files_and_added_files_are_synchronized(self):
        old = self.write("old.txt", "野狼皮")
        self.knowledge.ingest()
        old.unlink()
        self.write("new.txt", "水晶矿石")
        result = self.knowledge.ingest()
        self.assertEqual(result["added"], 1)
        self.assertEqual(result["deleted"], 1)
        self.assertEqual(result["files"], 1)
        self.assertEqual(self.knowledge.search("野狼皮"), [])
        self.assertEqual(self.knowledge.search("水晶")[0]["source"], "new.txt")

    def test_all_files_deleted_returns_explicit_empty_index_error(self):
        path = self.write("task.txt", "任务")
        self.knowledge.ingest()
        path.unlink()
        self.assertEqual(self.knowledge.ingest()["chunks"], 0)
        self.assertFalse(self.knowledge.status()["ready"])
        with self.assertRaisesRegex(EmptyIndexError, "为空"):
            self.knowledge.search("任务")

    def test_empty_directory_and_whitespace_files_do_not_fake_ready(self):
        self.assertEqual(self.knowledge.ingest()["files"], 0)
        self.write("empty.txt", " \n\t")
        result = self.knowledge.ingest()
        self.assertEqual(result["files"], 1)
        self.assertEqual(result["chunks"], 0)
        self.assertFalse(self.knowledge.status()["ready"])

    def test_index_location_does_not_depend_on_cwd(self):
        self.write("task.txt", "任务奖励为金币。")
        self.knowledge.ingest()
        previous = Path.cwd()
        try:
            os.chdir(self.root)
            reopened = KnowledgeBase(self.data, self.state)
            self.assertIn("金币", reopened.search("奖励")[0]["text"])
        finally:
            os.chdir(previous)
        self.assertFalse((self.root / "knowledge.sqlite3").exists())

    def test_configuration_change_requires_rebuild(self):
        self.write("task.txt", "任务" * 100)
        self.knowledge.ingest()
        smaller = KnowledgeBase(self.data, self.state, chunk_size=80, chunk_overlap=10)
        self.assertTrue(smaller.status()["needs_ingest"])
        with self.assertRaisesRegex(KnowledgeBaseError, "配置"):
            smaller.search("任务")
        result = smaller.ingest()
        self.assertEqual(result["updated"], 1)
        self.assertGreater(result["chunks"], 1)
        self.assertTrue(smaller.status()["ready"])

    def test_status_detects_source_changes_without_writing_or_loading_dependencies(self):
        original = self.write("task.txt", "任务金币")
        self.knowledge.ingest()
        unchanged_db = self.knowledge.db_path.read_bytes()
        with patch(
            "game_npc.knowledge.importlib.import_module",
            side_effect=AssertionError("unexpected import"),
        ):
            self.assertFalse(self.knowledge.status()["needs_ingest"])
            self.write("task.txt", "任务水晶")
            self.assertTrue(self.knowledge.status()["needs_ingest"])
            self.write("task.txt", "任务金币")
            self.assertFalse(self.knowledge.status()["needs_ingest"])
            added = self.write("new.md", "新增任务")
            self.assertTrue(self.knowledge.status()["needs_ingest"])
            added.unlink()
            self.assertFalse(self.knowledge.status()["needs_ingest"])
            original.unlink()
            self.assertTrue(self.knowledge.status()["needs_ingest"])
        self.assertEqual(unchanged_db, self.knowledge.db_path.read_bytes())

    def test_corrupt_database_is_actionable_for_all_public_operations(self):
        self.state.mkdir()
        self.knowledge.db_path.write_bytes(b"this is not a sqlite database")
        for operation in (
            self.knowledge.status,
            self.knowledge.ingest,
            lambda: self.knowledge.search("任务"),
        ):
            with self.subTest(operation=operation.__name__):
                with self.assertRaisesRegex(KnowledgeBaseError, "备份.*ingest"):
                    operation()

    def test_missing_database_tables_are_actionable_for_all_public_operations(self):
        self.write("task.txt", "任务金币")
        self.knowledge.ingest()
        with closing(sqlite3.connect(self.knowledge.db_path)) as connection, connection:
            connection.execute("DROP TABLE metadata")
        for operation in (
            self.knowledge.status,
            self.knowledge.ingest,
            lambda: self.knowledge.search("任务"),
        ):
            with self.subTest(operation=operation.__name__):
                with self.assertRaisesRegex(KnowledgeBaseError, "备份.*ingest"):
                    operation()

    def test_failed_read_preserves_previous_complete_index(self):
        self.write("task.txt", "任务金币")
        self.knowledge.ingest()
        self.write("task.txt", "新的任务水晶")
        (self.data / "bad.txt").write_bytes(b"\xff\xfe\xff")
        with self.assertRaisesRegex(KnowledgeBaseError, "UTF-8"):
            self.knowledge.ingest()
        self.assertIn("金币", self.knowledge.search("金币")[0]["text"])
        self.assertEqual(self.knowledge.search("水晶"), [])

    def test_missing_data_directory_fails_clearly(self):
        missing = KnowledgeBase(self.root / "missing", self.state)
        with self.assertRaisesRegex(KnowledgeBaseError, "目录不存在"):
            missing.ingest()

    def test_pdf_dependency_is_lazy_and_actionable(self):
        self.write("rules.PDF", "placeholder")
        with patch("game_npc.knowledge.importlib.import_module", side_effect=ImportError):
            with self.assertRaisesRegex(KnowledgeBaseError, r"\[pdf\]"):
                self.knowledge.ingest()

    def test_optional_dependencies_are_unused_in_local_mode(self):
        self.write("task.txt", "任务奖励")
        with patch(
            "game_npc.knowledge.importlib.import_module",
            side_effect=AssertionError("unexpected import"),
        ):
            self.knowledge.ingest()
            self.assertTrue(self.knowledge.search("奖励"))

    def test_top_k_limit_and_unrecognized_files(self):
        for number in range(5):
            self.write(f"{number}.txt", f"任务奖励{number}")
        self.write("ignored.csv", "任务奖励")
        self.knowledge.ingest()
        self.assertEqual(len(self.knowledge.search("任务")), 3)
        self.assertEqual(self.knowledge.status()["files"], 5)

    def test_invalid_parameters_and_empty_query(self):
        for kwargs in (
            {"mode": "unknown"},
            {"chunk_size": 0},
            {"chunk_overlap": 600},
            {"top_k": 0},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                KnowledgeBase(self.data, self.state, **kwargs)
        with self.assertRaises(ValueError):
            self.knowledge.search("  ")

    def test_vector_rebuild_is_atomic_and_success_removes_old_collection(self):
        self.write("task.txt", "旧任务金币")
        client = FakeVectorClient()
        knowledge = KnowledgeBase(self.data, self.state, mode="vector", api_key="test-only")

        def embeddings(texts):
            return [[0.1, 0.2] for _ in texts]

        with (
            patch.object(knowledge, "_vector_client", return_value=client),
            patch.object(knowledge, "_embed", side_effect=embeddings),
        ):
            knowledge.ingest()
            self.assertEqual(len(client.collections), 1)
            self.assertIn("金币", knowledge.search("任务")[0]["text"])
            self.write("task.txt", "新任务水晶")
            with patch.object(
                knowledge, "_embed", side_effect=KnowledgeBaseError("test failed embedding")
            ):
                with self.assertRaises(KnowledgeBaseError):
                    knowledge.ingest()
            self.assertIn("金币", knowledge.search("任务")[0]["text"])
            self.assertEqual(len(client.collections), 1)
            knowledge.ingest()
            self.assertIn("水晶", knowledge.search("任务")[0]["text"])
            self.assertEqual(len(client.collections), 1)

    def test_vector_mode_requires_explicit_credentials(self):
        knowledge = KnowledgeBase(self.data, self.state, mode="vector")
        with self.assertRaisesRegex(KnowledgeBaseError, "API 密钥"):
            knowledge._embed(["任务"])


if __name__ == "__main__":
    unittest.main()
