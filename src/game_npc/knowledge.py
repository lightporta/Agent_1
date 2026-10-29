"""Explicit, reproducible knowledge indexing with an offline default backend."""

from __future__ import annotations

import hashlib
import importlib
import json
import math
import re
import sqlite3
import uuid
from collections import Counter
from contextlib import closing
from functools import wraps
from pathlib import Path
from typing import Any, Callable


class KnowledgeBaseError(RuntimeError):
    """A knowledge source or index could not be used."""


class EmptyIndexError(KnowledgeBaseError):
    """The user must explicitly build the knowledge index."""


def _database_errors(method: Callable[..., Any]) -> Callable[..., Any]:
    """Expose database failures through the same actionable public error type."""

    @wraps(method)
    def guarded(self: KnowledgeBase, *args: Any, **kwargs: Any) -> Any:
        try:
            return method(self, *args, **kwargs)
        except sqlite3.Error as exc:
            raise KnowledgeBaseError(
                "知识索引数据库不可用，请确认状态目录可写且没有其他构建占用。"
                f"若数据库损坏或表缺失，请备份并移走 {self.db_path} 后重新运行 ingest。"
            ) from exc

    return guarded


def _tokens(text: str) -> Counter[str]:
    """Index Latin words plus Chinese characters and adjacent character pairs."""
    text = text.lower()
    terms = re.findall(r"[a-z0-9_]+|[\u3400-\u9fff]", text)
    for match in re.finditer(r"[\u3400-\u9fff]{2,}", text):
        sequence = match.group()
        terms.extend(sequence[i : i + 2] for i in range(len(sequence) - 1))
    return Counter(terms)


class KnowledgeBase:
    """Own one index rooted in ``state_dir``; importing never initializes clients.

    ``local`` uses SQLite and BM25 without credentials. ``vector`` additionally
    uses Chroma and an OpenAI-compatible embeddings endpoint. Source files are
    authoritative; generated indexes from earlier versions are never imported.
    """

    def __init__(
        self,
        data_dir: Path,
        state_dir: Path,
        mode: str = "local",
        chunk_size: int = 600,
        chunk_overlap: int = 80,
        top_k: int = 3,
        embedding_model: str = "text-embedding-v4",
        api_key: str | None = None,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
    ) -> None:
        if mode not in {"local", "vector"}:
            raise ValueError("知识检索模式必须为 local 或 vector")
        if chunk_size <= 0 or not 0 <= chunk_overlap < chunk_size:
            raise ValueError("chunk_size 必须为正数，chunk_overlap 必须在 0 到 chunk_size-1 之间")
        if top_k <= 0:
            raise ValueError("top_k 必须为正数")
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.state_dir = Path(state_dir).expanduser().resolve()
        self.mode = mode
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.top_k = top_k
        self.embedding_model = embedding_model
        self.api_key = api_key
        self.base_url = base_url
        self.db_path = self.state_dir / "knowledge.sqlite3"

    @property
    def _signature(self) -> str:
        settings = {
            "schema": 1,
            "data_dir": str(self.data_dir),
            "mode": self.mode,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
        }
        if self.mode == "vector":
            settings.update(embedding_model=self.embedding_model, base_url=self.base_url)
        return json.dumps(settings, sort_keys=True)

    def _connect(self) -> sqlite3.Connection:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        existing = self.db_path.exists()
        connection = sqlite3.connect(self.db_path, timeout=30)
        try:
            if existing:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                if not {"files", "chunks", "metadata"}.issubset(tables):
                    raise sqlite3.DatabaseError("知识索引缺少必要的数据表")
            connection.execute("PRAGMA foreign_keys = ON")
            connection.executescript(
                """
            CREATE TABLE IF NOT EXISTS files (
                source TEXT PRIMARY KEY, digest TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS chunks (
                source TEXT NOT NULL REFERENCES files(source) ON DELETE CASCADE,
                ordinal INTEGER NOT NULL, text TEXT NOT NULL, terms TEXT NOT NULL,
                PRIMARY KEY (source, ordinal)
            );
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY, value TEXT NOT NULL
            );
                """
            )
        except BaseException:
            connection.close()
            raise
        return connection

    def _read(self) -> sqlite3.Connection:
        if not self.db_path.is_file():
            raise EmptyIndexError("知识库尚未构建，请先运行 ingest 构建知识索引。")
        return sqlite3.connect(self.db_path.as_uri() + "?mode=ro", uri=True, timeout=30)

    @staticmethod
    def _metadata(connection: sqlite3.Connection) -> dict[str, str]:
        return dict(connection.execute("SELECT key, value FROM metadata"))

    @_database_errors
    def status(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ready": False,
            "files": 0,
            "chunks": 0,
            "mode": self.mode,
            "indexed_mode": None,
            "needs_ingest": True,
        }
        if not self.db_path.is_file():
            return result
        with closing(self._read()) as connection:
            metadata = self._metadata(connection)
            manifest = dict(connection.execute("SELECT source, digest FROM files"))
            result["files"] = connection.execute("SELECT COUNT(*) FROM files").fetchone()[0]
            result["chunks"] = connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        result["indexed_mode"] = metadata.get("mode")
        result["needs_ingest"] = (
            metadata.get("signature") != self._signature
            or not self.data_dir.is_dir()
            or manifest
            != {source: self._digest(path) for source, path in self._source_paths().items()}
        )
        result["ready"] = result["chunks"] > 0 and not result["needs_ingest"]
        return result

    def _source_paths(self) -> dict[str, Path]:
        return {
            path.relative_to(self.data_dir).as_posix(): path
            for path in sorted(self.data_dir.rglob("*"))
            if path.is_file() and path.suffix.lower() in {".txt", ".md", ".pdf"}
        }

    @staticmethod
    def _digest(path: Path) -> str:
        try:
            with path.open("rb") as source:
                return hashlib.file_digest(source, "sha256").hexdigest()
        except OSError as exc:
            raise KnowledgeBaseError(f"无法读取知识文件：{path.name}") from exc

    def _load(self, path: Path) -> str:
        try:
            if path.suffix.lower() == ".pdf":
                try:
                    reader = importlib.import_module("pypdf").PdfReader
                except ImportError as exc:
                    raise KnowledgeBaseError(
                        'PDF 读取需要可选依赖，请安装：python -m pip install -e ".[pdf]"'
                    ) from exc
                return "\n".join(page.extract_text() or "" for page in reader(path).pages)
            return path.read_text(encoding="utf-8-sig")
        except KnowledgeBaseError:
            raise
        except Exception as exc:
            raise KnowledgeBaseError(
                f"无法读取知识文件 {path.name}，请检查格式及 UTF-8 编码。"
            ) from exc

    def _split(self, text: str) -> list[str]:
        text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
        chunks = []
        start = 0
        while start < len(text):
            end = min(start + self.chunk_size, len(text))
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end == len(text):
                break
            start = end - self.chunk_overlap
        return chunks

    @_database_errors
    def ingest(self) -> dict[str, int]:
        """Synchronize new, changed and deleted files atomically in SQLite.

        Vector builds use a new collection and switch the manifest only after
        all embedding requests and Chroma writes succeed. A failed rebuild
        leaves the previous index available.
        """
        if not self.data_dir.is_dir():
            raise KnowledgeBaseError(f"知识目录不存在：{self.data_dir}")
        paths = self._source_paths()
        with closing(self._connect()) as connection, connection:
            # Serialize writers, including remote embedding work, so two builds
            # cannot publish manifests derived from different file snapshots.
            connection.execute("BEGIN IMMEDIATE")
            metadata = self._metadata(connection)
            old = dict(connection.execute("SELECT source, digest FROM files"))
            settings_changed = metadata.get("signature") != self._signature
            digests = {}
            changed: dict[str, list[str]] = {}
            for source, path in paths.items():
                digest = self._digest(path)
                digests[source] = digest
                if settings_changed or old.get(source) != digest:
                    changed[source] = self._split(self._load(path))
            deleted = set(old) - set(paths)
            added = set(paths) - set(old)
            updated = set(changed) & set(old)
            if not changed and not deleted and not settings_changed:
                return {
                    "added": 0,
                    "updated": 0,
                    "deleted": 0,
                    "chunks": connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
                    "files": len(old),
                }

            for source in deleted | set(changed):
                connection.execute("DELETE FROM files WHERE source = ?", (source,))
            for source, texts in changed.items():
                connection.execute("INSERT INTO files VALUES (?, ?)", (source, digests[source]))
                connection.executemany(
                    "INSERT INTO chunks VALUES (?, ?, ?, ?)",
                    (
                        (source, number, text, json.dumps(_tokens(text), ensure_ascii=False))
                        for number, text in enumerate(texts)
                    ),
                )
            rows = connection.execute(
                "SELECT source, ordinal, text FROM chunks ORDER BY source, ordinal"
            ).fetchall()
            new_collection = None
            if self.mode == "vector" and rows:
                new_collection = self._build_vectors(rows)
            new_metadata = {
                "signature": self._signature,
                "mode": self.mode,
                "collection": new_collection or "",
            }
            connection.executemany(
                "INSERT OR REPLACE INTO metadata VALUES (?, ?)", new_metadata.items()
            )
            connection.commit()
        # Cleanup cannot invalidate a successfully committed new index.
        old_collection = metadata.get("collection")
        if old_collection and old_collection != new_collection:
            try:
                self._vector_client().delete_collection(old_collection)
            except Exception:
                pass
        return {
            "added": len(added),
            "updated": len(updated),
            "deleted": len(deleted),
            "chunks": len(rows),
            "files": len(paths),
        }

    @_database_errors
    def search(self, query: str) -> list[dict[str, Any]]:
        query = query.strip()
        if not query:
            raise ValueError("检索词不能为空")
        with closing(self._read()) as connection:
            metadata = self._metadata(connection)
            if metadata.get("signature") != self._signature:
                raise KnowledgeBaseError("知识索引与当前配置不一致，请重新运行 ingest。")
            rows = connection.execute(
                "SELECT source, ordinal, text, terms FROM chunks ORDER BY source, ordinal"
            ).fetchall()
        if not rows:
            raise EmptyIndexError("知识索引为空，请添加知识文件后重新运行 ingest。")
        if self.mode == "vector":
            return self._search_vectors(query, metadata.get("collection", ""), len(rows))
        query_terms = set(_tokens(query))
        if not query_terms:
            return []
        counters = [json.loads(row[3]) for row in rows]
        lengths = [sum(terms.values()) for terms in counters]
        average_length = sum(lengths) / len(lengths) or 1
        frequencies = Counter(term for terms in counters for term in query_terms if term in terms)
        ranked = []
        for row, terms, length in zip(rows, counters, lengths):
            score = 0.0
            for term in query_terms:
                frequency = terms.get(term, 0)
                if not frequency:
                    continue
                inverse_frequency = math.log(
                    1 + (len(rows) - frequencies[term] + 0.5) / (frequencies[term] + 0.5)
                )
                score += (
                    inverse_frequency
                    * frequency
                    * 2.5
                    / (frequency + 1.5 * (0.25 + 0.75 * length / average_length))
                )
            if score > 0:
                ranked.append((score, row[0], row[1], row[2]))
        ranked.sort(key=lambda item: (-item[0], item[1], item[2]))
        return [
            {"source": source, "text": text, "score": score}
            for score, source, _, text in ranked[: self.top_k]
        ]

    def _vector_client(self) -> Any:
        try:
            chromadb = importlib.import_module("chromadb")
        except ImportError as exc:
            raise KnowledgeBaseError(
                '向量检索需要可选依赖，请安装：python -m pip install -e ".[vector]"'
            ) from exc
        return chromadb.PersistentClient(
            path=str(self.state_dir / "chroma"),
            settings=chromadb.Settings(anonymized_telemetry=False),
        )

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if not self.api_key:
            raise KnowledgeBaseError("向量检索需要 API 密钥，请配置 DASHSCOPE_API_KEY。")
        try:
            openai = importlib.import_module("openai")
        except ImportError as exc:
            raise KnowledgeBaseError(
                '向量检索需要可选依赖，请安装：python -m pip install -e ".[vector]"'
            ) from exc
        vectors = []
        try:
            with openai.OpenAI(
                api_key=self.api_key, base_url=self.base_url, timeout=60, max_retries=2
            ) as client:
                for offset in range(0, len(texts), 10):
                    batch = texts[offset : offset + 10]
                    response = client.embeddings.create(model=self.embedding_model, input=batch)
                    ordered = sorted(response.data, key=lambda item: item.index)
                    if len(ordered) != len(batch):
                        raise ValueError("嵌入服务返回数量与请求不一致")
                    vectors.extend(item.embedding for item in ordered)
        except Exception as exc:
            raise KnowledgeBaseError(
                "嵌入请求失败，请检查 API 密钥、模型、服务地址及网络连接。"
            ) from exc
        return vectors

    def _build_vectors(self, rows: list[tuple[str, int, str]]) -> str:
        client = self._vector_client()
        vectors = self._embed([row[2] for row in rows])
        name = "npc-" + uuid.uuid4().hex
        collection = client.create_collection(
            name=name, metadata={"hnsw:space": "cosine"}, embedding_function=None
        )
        try:
            for offset in range(0, len(rows), 100):
                batch = rows[offset : offset + 100]
                collection.add(
                    ids=[
                        hashlib.sha256(f"{source}\0{ordinal}".encode()).hexdigest()
                        for source, ordinal, _ in batch
                    ],
                    documents=[text for _, _, text in batch],
                    metadatas=[{"source": source} for source, _, _ in batch],
                    embeddings=vectors[offset : offset + len(batch)],
                )
        except Exception:
            client.delete_collection(name)
            raise
        return name

    def _search_vectors(self, query: str, name: str, count: int) -> list[dict[str, Any]]:
        if not name:
            raise EmptyIndexError("向量索引为空，请重新运行 ingest。")
        try:
            collection = self._vector_client().get_collection(name, embedding_function=None)
            result = collection.query(
                query_embeddings=self._embed([query]),
                n_results=min(self.top_k, count),
                include=["documents", "metadatas", "distances"],
            )
        except KnowledgeBaseError:
            raise
        except Exception as exc:
            raise KnowledgeBaseError("向量索引不可用，请重新运行 ingest 构建。") from exc
        return [
            {"source": metadata["source"], "text": text, "score": 1 - distance}
            for text, metadata, distance in zip(
                result["documents"][0], result["metadatas"][0], result["distances"][0]
            )
        ]
