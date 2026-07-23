#!/usr/bin/env python3
"""Build sanitized workflow/node cards, FTS index, and compatibility manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from n8n_registry.cards import (  # noqa: E402
    extract_workflow_card,
    legacy_template_response,
    write_json_atomic,
)
from n8n_registry.fts import CardSearchIndex  # noqa: E402
from n8n_registry.loader import load_nodes_from_file, load_templates_from_file  # noqa: E402
from n8n_registry.search import build_node_contract_response  # noqa: E402


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    content = "".join(f"{json.dumps(row, ensure_ascii=False, sort_keys=True)}\n" for row in rows)
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _load_workflow_cards(
    *,
    templates_path: Path,
    raw_templates_path: Path | None,
    seed_templates_path: Path | None = None,
) -> list[Any]:
    seed_path = seed_templates_path or templates_path
    templates = load_templates_from_file(seed_path)
    cards_by_id = {
        str(template.card.id): template.card for template in templates if template.card is not None
    }
    if raw_templates_path is None or not raw_templates_path.exists():
        return list(cards_by_id.values())

    latest_by_id: dict[str, dict[str, Any]] = {}
    with raw_templates_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid community raw snapshot JSON at line {line_number}"
                ) from exc
            if not isinstance(record, dict):
                continue
            template_id = str(record.get("id") or "").strip()
            if template_id:
                latest_by_id[template_id] = record

    for template_id, record in latest_by_id.items():
        card = extract_workflow_card(record)
        if card.node_count > 0 and card.node_types:
            cards_by_id[template_id] = card
    cards = list(cards_by_id.values())
    write_json_atomic(
        templates_path,
        [legacy_template_response(card) for card in cards],
    )
    return cards


def build(
    *,
    nodes_path: Path,
    templates_path: Path,
    workflow_cards_path: Path,
    node_cards_path: Path,
    index_path: Path,
    manifest_path: Path,
    n8n_version: str,
    raw_templates_path: Path | None = None,
    seed_templates_path: Path | None = None,
) -> dict[str, Any]:
    nodes = load_nodes_from_file(nodes_path)
    workflow_cards = _load_workflow_cards(
        templates_path=templates_path,
        raw_templates_path=raw_templates_path,
        seed_templates_path=seed_templates_path,
    )
    node_cards = [node.card for node in nodes if node.card is not None]
    operation_cards = [
        build_node_contract_response(node, contract)
        for node in nodes
        for contract in node.contracts
    ]

    _write_jsonl(workflow_cards_path, [asdict(card) for card in workflow_cards])
    _write_jsonl(node_cards_path, operation_cards)
    CardSearchIndex.build(
        workflow_cards=workflow_cards,
        node_cards=node_cards,
        path=index_path,
    ).close()

    manifest = {
        "artifactVersion": 2,
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "finished": True,
        "n8nVersion": n8n_version or None,
        "nodeSchemaSha256": _sha256(nodes_path),
        "workflowCardsSha256": _sha256(workflow_cards_path),
        "nodeCardsSha256": _sha256(node_cards_path),
        "retrievalIndexSha256": _sha256(index_path),
        "workflowCardCount": len(workflow_cards),
        "nodeCardCount": len(operation_cards),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = manifest_path.with_suffix(f"{manifest_path.suffix}.tmp")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(manifest_path)
    return manifest


def main() -> None:
    data_dir = ROOT / "data"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nodes", default=str(data_dir / "nodes.json"))
    parser.add_argument("--templates", default=str(data_dir / "templates.json"))
    parser.add_argument(
        "--raw-templates",
        default=str(ROOT / "generated" / "raw" / "community_workflows.jsonl"),
        help="Untrusted raw Community snapshot used to deterministically rebuild cards",
    )
    parser.add_argument(
        "--seed-templates",
        help="Optional sanitized seed corpus to merge before raw snapshot overrides",
    )
    parser.add_argument("--workflow-cards", default=str(data_dir / "workflow_cards.jsonl"))
    parser.add_argument("--node-cards", default=str(data_dir / "node_cards.jsonl"))
    parser.add_argument("--index", default=str(data_dir / "retrieval.sqlite"))
    parser.add_argument("--manifest", default=str(data_dir / "registry_manifest.json"))
    parser.add_argument(
        "--n8n-version",
        default=os.getenv("N8N_VERSION", ""),
        help="Version of the n8n instance that produced nodes.json",
    )
    args = parser.parse_args()

    manifest = build(
        nodes_path=Path(args.nodes),
        templates_path=Path(args.templates),
        workflow_cards_path=Path(args.workflow_cards),
        node_cards_path=Path(args.node_cards),
        index_path=Path(args.index),
        manifest_path=Path(args.manifest),
        n8n_version=args.n8n_version,
        raw_templates_path=Path(args.raw_templates) if args.raw_templates else None,
        seed_templates_path=Path(args.seed_templates) if args.seed_templates else None,
    )
    print(
        "Built registry cards: "
        f"{manifest['workflowCardCount']} workflows, {manifest['nodeCardCount']} nodes"
    )


if __name__ == "__main__":
    main()
