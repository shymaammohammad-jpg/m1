"""Small transactional SQLite store; source documents never enter executable code."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Callable


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.uploads = self.root / "uploads"
        self.uploads.mkdir(exist_ok=True)
        self.db = self.root / "audit.sqlite3"
        with self.connection() as conn:
            conn.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS cases (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY, case_id TEXT, payload TEXT NOT NULL,
                    path TEXT NOT NULL, text TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(case_id) REFERENCES cases(id)
                );
                CREATE INDEX IF NOT EXISTS documents_case ON documents(case_id);
                CREATE TABLE IF NOT EXISTS imported_references (
                    source TEXT PRIMARY KEY, document_id TEXT NOT NULL
                );
            """)

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.db, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def list_cases(self) -> list[dict]:
        with self.connection() as conn:
            return [json.loads(row[0]) for row in conn.execute(
                "SELECT payload FROM cases ORDER BY updated_at DESC")]

    def get_case(self, case_id: str) -> dict | None:
        with self.connection() as conn:
            row = conn.execute("SELECT payload FROM cases WHERE id=?", (case_id,)).fetchone()
            return json.loads(row[0]) if row else None

    def insert_case(self, case: dict):
        with self.connection() as conn:
            conn.execute("INSERT INTO cases(id,payload,updated_at) VALUES(?,?,?)",
                         (case["id"], json.dumps(case, ensure_ascii=False), case["updated_at"]))

    def mutate_case(self, case_id: str, mutate: Callable[[dict], None]) -> dict:
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT payload FROM cases WHERE id=?", (case_id,)).fetchone()
            if not row:
                raise KeyError(case_id)
            case = json.loads(row[0])
            mutate(case)
            case["updated_at"] = now()
            conn.execute("UPDATE cases SET payload=?,updated_at=? WHERE id=?",
                         (json.dumps(case, ensure_ascii=False), case["updated_at"], case_id))
            return case

    def documents(self, case_id: str | None = None) -> list[dict]:
        with self.connection() as conn:
            query = "SELECT payload FROM documents WHERE case_id IS NULL ORDER BY rowid"
            args: tuple = ()
            if case_id is not None:
                query = "SELECT payload FROM documents WHERE case_id=? ORDER BY rowid"
                args = (case_id,)
            return [json.loads(row[0]) for row in conn.execute(query, args)]

    def document(self, document_id: str) -> dict | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
            if not row:
                return None
            return {**json.loads(row["payload"]), "_path": row["path"],
                    "_text": row["text"], "_case_id": row["case_id"]}

    def add_documents(self, documents: list[dict], case_id: str | None):
        with self.connection() as conn:
            for item in documents:
                public = {k: v for k, v in item.items() if not k.startswith("_")}
                conn.execute("INSERT INTO documents(id,case_id,payload,path,text) VALUES(?,?,?,?,?)",
                             (item["id"], case_id, json.dumps(public, ensure_ascii=False),
                              item["_path"], item.get("_text", "")))

    def delete_document(self, document_id: str):
        with self.connection() as conn:
            conn.execute("DELETE FROM documents WHERE id=?", (document_id,))

    def update_document(self, document_id: str, values: dict, text: str | None = None):
        """Update descriptive metadata, never the immutable original or its identity."""
        allowed = {"category", "page_count", "pagination", "extraction_status", "extracted_characters", "warnings"}
        if set(values) - allowed:
            raise ValueError("Unsupported document metadata change")
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT payload FROM documents WHERE id=?", (document_id,)).fetchone()
            if not row:
                raise KeyError(document_id)
            payload = json.loads(row[0])
            payload.update(values)
            conn.execute("UPDATE documents SET payload=? WHERE id=?",
                         (json.dumps(payload, ensure_ascii=False), document_id))
            if text is not None:
                conn.execute("UPDATE documents SET text=? WHERE id=?", (text[:4_000_000], document_id))

    def delete_empty_case(self, case_id: str):
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM documents WHERE case_id=?", (case_id,)).fetchone():
                raise ValueError("Case contains documents")
            conn.execute("DELETE FROM cases WHERE id=?", (case_id,))

    def reference_imported(self, source: str) -> bool:
        with self.connection() as conn:
            return conn.execute("SELECT 1 FROM imported_references WHERE source=?", (source,)).fetchone() is not None

    def mark_imported(self, source: str, document_id: str):
        with self.connection() as conn:
            conn.execute("INSERT OR REPLACE INTO imported_references(source,document_id) VALUES(?,?)",
                         (source, document_id))
