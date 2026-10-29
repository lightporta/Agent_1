"""Real local Chroma driver with synthetic embeddings; no cloud verification."""

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from game_npc.knowledge import KnowledgeBase


@unittest.skipUnless(importlib.util.find_spec("chromadb"), "requires [vector] extra")
class VectorDriverTests(unittest.TestCase):
    def test_persistent_chroma_with_synthetic_embeddings(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            data.mkdir()
            (data / "herbs.txt").write_text("药草用于任务。", encoding="utf-8")
            (data / "smith.txt").write_text("铁匠修理装备。", encoding="utf-8")
            knowledge = KnowledgeBase(data, root / "state", mode="vector", api_key="unused")

            def synthetic(texts):
                return [[1.0, 0.0, 0.0] if "药草" in text else [0.0, 1.0, 0.0] for text in texts]

            with patch.object(knowledge, "_embed", side_effect=synthetic):
                self.assertEqual(knowledge.ingest()["chunks"], 2)
                self.assertEqual(knowledge.search("药草")[0]["source"], "herbs.txt")
                self.assertEqual(knowledge.ingest()["added"], 0)
                (data / "smith.txt").unlink()
                self.assertEqual(knowledge.ingest()["deleted"], 1)
                self.assertEqual(len(knowledge._vector_client().list_collections()), 1)
                self.assertEqual(len(knowledge.search("药草")), 1)


if __name__ == "__main__":
    unittest.main()
