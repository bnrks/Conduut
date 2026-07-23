"""SQLite FTS5 search index for sanitized registry cards."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from .models import NodeCard, WorkflowCard

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def _fts_query(query: str) -> str:
    tokens = [token.lower() for token in _TOKEN_RE.findall(query)]
    return " AND ".join(f'"{token}"*' for token in tokens)


class CardSearchIndex:
    """Small FTS5 index over workflow and node cards."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._connection.row_factory = sqlite3.Row

    @classmethod
    def build(
        cls,
        *,
        workflow_cards: Iterable[WorkflowCard] = (),
        node_cards: Iterable[NodeCard] = (),
        path: str | Path = ":memory:",
    ) -> "CardSearchIndex":
        destination = str(path)
        if destination != ":memory:":
            target = Path(destination)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                target.unlink()
        connection = sqlite3.connect(destination)
        index = cls(connection)
        index._create_schema()
        index._populate_workflow_cards(workflow_cards)
        index._populate_node_cards(node_cards)
        return index

    @classmethod
    def load(cls, path: str | Path) -> "CardSearchIndex" | None:
        target = Path(path)
        if not target.exists():
            return None
        connection = sqlite3.connect(str(target))
        index = cls(connection)
        index._validate_schema()
        return index

    def close(self) -> None:
        self._connection.close()

    def search_workflow_cards(self, query: str, *, limit: int = 5) -> list[str]:
        statement = _fts_query(query)
        if not statement:
            return []
        rows = self._connection.execute(
            """
            SELECT id
            FROM workflow_cards_fts
            WHERE workflow_cards_fts MATCH ?
            ORDER BY bm25(workflow_cards_fts, 1.0)
            LIMIT ?
            """,
            (statement, limit),
        ).fetchall()
        return [str(row["id"]) for row in rows]

    def search_node_cards(self, query: str, *, limit: int = 20) -> list[str]:
        statement = _fts_query(query)
        if not statement:
            return []
        rows = self._connection.execute(
            """
            SELECT type_name
            FROM node_cards_fts
            WHERE node_cards_fts MATCH ?
            ORDER BY bm25(node_cards_fts, 1.0)
            LIMIT ?
            """,
            (statement, limit),
        ).fetchall()
        return [str(row["type_name"]) for row in rows]

    def _create_schema(self) -> None:
        self._connection.executescript(
            """
            DROP TABLE IF EXISTS workflow_cards;
            DROP TABLE IF EXISTS workflow_cards_fts;
            DROP TABLE IF EXISTS node_cards;
            DROP TABLE IF EXISTS node_cards_fts;

            CREATE TABLE workflow_cards (
                id TEXT PRIMARY KEY,
                payload TEXT NOT NULL
            );

            CREATE VIRTUAL TABLE workflow_cards_fts USING fts5(
                id UNINDEXED,
                search_text
            );

            CREATE TABLE node_cards (
                type_name TEXT PRIMARY KEY,
                payload TEXT NOT NULL
            );

            CREATE VIRTUAL TABLE node_cards_fts USING fts5(
                type_name UNINDEXED,
                search_text
            );
            """
        )

    def _validate_schema(self) -> None:
        required_tables = {
            "workflow_cards",
            "workflow_cards_fts",
            "node_cards",
            "node_cards_fts",
        }
        rows = self._connection.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'virtual table')"
        ).fetchall()
        found = {str(row["name"]) for row in rows}
        missing = required_tables - found
        if missing:
            raise RuntimeError(f"Registry search index is missing tables: {sorted(missing)}")

    def _populate_workflow_cards(self, cards: Iterable[WorkflowCard]) -> None:
        rows = []
        for card in cards:
            rows.append(
                (
                    str(card.id),
                    json.dumps(asdict(card), ensure_ascii=False, sort_keys=True),
                    card.search_text,
                )
            )
        if not rows:
            return
        with self._connection:
            self._connection.executemany(
                "INSERT INTO workflow_cards (id, payload) VALUES (?, ?)",
                [(card_id, payload) for card_id, payload, _ in rows],
            )
            self._connection.executemany(
                "INSERT INTO workflow_cards_fts (id, search_text) VALUES (?, ?)",
                [(card_id, search_text) for card_id, _, search_text in rows],
            )

    def _populate_node_cards(self, cards: Iterable[NodeCard]) -> None:
        rows = []
        for card in cards:
            rows.append(
                (
                    card.type_name,
                    json.dumps(asdict(card), ensure_ascii=False, sort_keys=True),
                    card.search_text,
                )
            )
        if not rows:
            return
        with self._connection:
            self._connection.executemany(
                "INSERT INTO node_cards (type_name, payload) VALUES (?, ?)",
                [(type_name, payload) for type_name, payload, _ in rows],
            )
            self._connection.executemany(
                "INSERT INTO node_cards_fts (type_name, search_text) VALUES (?, ?)",
                [(type_name, search_text) for type_name, _, search_text in rows],
            )
