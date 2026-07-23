#!/usr/bin/env python3
"""Fetch n8n templates and persist sanitized workflow-card artifacts."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from n8n_registry.cards import (  # noqa: E402
    append_workflow_card_jsonl,
    extract_workflow_card,
    legacy_template_response,
    load_json_file,
    load_workflow_cards_jsonl,
    workflow_card_to_dict,
    write_json_atomic,
)
from n8n_registry.fts import CardSearchIndex  # noqa: E402

_SEARCH_URL = "https://api.n8n.io/api/templates/search"
_DETAIL_URL = "https://api.n8n.io/api/templates/workflows/{id}"


def fetch_template_ids(
    client: httpx.Client,
    total_limit: int | None,
    *,
    query: str | None = None,
) -> list[dict[str, Any]]:
    templates_basic: list[dict[str, Any]] = []
    page = 1
    page_size = 20

    while total_limit is None or len(templates_basic) < total_limit:
        params: dict[str, Any] = {"rows": page_size, "page": page}
        if query:
            params["search"] = query
        response = client.get(_SEARCH_URL, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        items = data.get("workflows", [])
        if not items:
            break
        templates_basic.extend(items)
        available = data.get("totalWorkflows")
        print(
            f"  Listed page {page}: +{len(items)} "
            f"(loaded: {len(templates_basic)}, available: {available or '?'})"
        )
        if len(items) < page_size:
            break
        if isinstance(available, int) and len(templates_basic) >= available:
            break
        page += 1
        time.sleep(0.2)

    return templates_basic if total_limit is None else templates_basic[:total_limit]


def fetch_template_detail(client: httpx.Client, template_id: int | str) -> dict[str, Any] | None:
    try:
        response = client.get(_DETAIL_URL.format(id=template_id), timeout=20)
        response.raise_for_status()
    except Exception as exc:
        print(f"  Warning: failed to fetch detail for {template_id}: {exc}", file=sys.stderr)
        return None
    payload = response.json()
    detail = payload.get("workflow")
    if not isinstance(detail, dict):
        return None
    nested = detail.get("workflow")
    workflow = nested if isinstance(nested, dict) else detail
    nodes = workflow.get("nodes")
    if not isinstance(nodes, list) or not any(
        isinstance(node, dict) and str(node.get("type") or "").strip() for node in nodes
    ):
        print(
            f"  Warning: detail for {template_id} has no native workflow nodes",
            file=sys.stderr,
        )
        return None
    return workflow


def _manifest_template(
    *,
    limit: int,
    jsonl_path: Path,
    legacy_out_path: Path,
    db_path: Path,
) -> dict[str, Any]:
    return {
        "artifactVersion": 1,
        "searchUrl": _SEARCH_URL,
        "detailUrl": _DETAIL_URL,
        "limit": limit,
        "jsonlPath": str(jsonl_path),
        "legacyPath": str(legacy_out_path),
        "dbPath": str(db_path),
        "completedIds": [],
        "failedIds": [],
        "updatedAt": None,
    }


def _load_or_init_manifest(
    manifest_path: Path,
    *,
    limit: int,
    jsonl_path: Path,
    legacy_out_path: Path,
    db_path: Path,
) -> dict[str, Any]:
    existing = load_json_file(manifest_path)
    if existing:
        existing["limit"] = limit
        existing["jsonlPath"] = str(jsonl_path)
        existing["legacyPath"] = str(legacy_out_path)
        existing["dbPath"] = str(db_path)
        return existing
    return _manifest_template(
        limit=limit,
        jsonl_path=jsonl_path,
        legacy_out_path=legacy_out_path,
        db_path=db_path,
    )


def _rewrite_workflow_cards_jsonl(jsonl_path: Path, cards: list[Any]) -> None:
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = jsonl_path.with_suffix(f"{jsonl_path.suffix}.tmp")
    content = "".join(
        f"{json.dumps(workflow_card_to_dict(card), ensure_ascii=False, sort_keys=True)}\n"
        for card in cards
    )
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(jsonl_path)


def _load_completed_ids(
    manifest: dict[str, Any],
    jsonl_path: Path,
    *,
    require_detail: bool,
) -> tuple[set[str], set[str]]:
    completed = {str(item) for item in manifest.get("completedIds") or []}
    incomplete: set[str] = set()
    if jsonl_path.exists():
        cards = load_workflow_cards_jsonl(jsonl_path)
        if require_detail:
            incomplete = {
                str(card.id) for card in cards if card.node_count <= 0 or not card.node_types
            }
            if incomplete:
                cards = [card for card in cards if str(card.id) not in incomplete]
                _rewrite_workflow_cards_jsonl(jsonl_path, cards)
        completed.update(str(card.id) for card in cards)
    completed.difference_update(incomplete)
    return completed, incomplete


def _persist_manifest(manifest_path: Path, manifest: dict[str, Any]) -> None:
    manifest["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    write_json_atomic(manifest_path, manifest)


def fetch_workflow_cards(
    client: httpx.Client,
    basics: list[dict[str, Any]],
    *,
    jsonl_path: Path,
    manifest_path: Path,
    legacy_out_path: Path,
    db_path: Path,
    raw_snapshot_path: Path,
    resume: bool,
    no_detail: bool,
) -> list[dict[str, Any]]:
    manifest = _load_or_init_manifest(
        manifest_path,
        limit=len(basics),
        jsonl_path=jsonl_path,
        legacy_out_path=legacy_out_path,
        db_path=db_path,
    )
    completed_ids: set[str] = set()
    incomplete_ids: set[str] = set()
    if resume:
        completed_ids, incomplete_ids = _load_completed_ids(
            manifest,
            jsonl_path,
            require_detail=not no_detail,
        )
    failed_ids = {str(item) for item in manifest.get("failedIds") or []}
    failed_ids.update(incomplete_ids)

    for index, basic in enumerate(basics, start=1):
        template_id = str(basic.get("id") or "")
        if not template_id:
            continue
        if template_id in completed_ids:
            continue

        workflow = {} if no_detail else fetch_template_detail(client, template_id)
        if workflow is None:
            failed_ids.add(template_id)
            completed_ids.discard(template_id)
            manifest["completedIds"] = sorted(completed_ids)
            manifest["failedIds"] = sorted(failed_ids)
            manifest["completedCount"] = len(completed_ids)
            manifest["listedCount"] = len(basics)
            manifest["lastProgressIndex"] = index
            _persist_manifest(manifest_path, manifest)
            continue
        fetched_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        record = dict(basic)
        record["workflow"] = workflow
        record["fetchedAt"] = fetched_at
        raw_snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        with raw_snapshot_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        card = extract_workflow_card(record)
        append_workflow_card_jsonl(jsonl_path, card)

        completed_ids.add(template_id)
        failed_ids.discard(template_id)
        manifest["completedIds"] = sorted(completed_ids)
        manifest["failedIds"] = sorted(failed_ids)
        manifest["lastCompletedId"] = template_id
        manifest["completedCount"] = len(completed_ids)
        manifest["listedCount"] = len(basics)
        manifest["lastProgressIndex"] = index
        _persist_manifest(manifest_path, manifest)

        if index % 10 == 0:
            print(f"  Progress: {index}/{len(basics)}")
        time.sleep(0.1)

    cards = load_workflow_cards_jsonl(jsonl_path)
    legacy_payload = [legacy_template_response(card) for card in cards]
    write_json_atomic(legacy_out_path, legacy_payload)
    CardSearchIndex.build(workflow_cards=cards, path=db_path).close()

    manifest["completedIds"] = sorted(str(card.id) for card in cards)
    manifest["completedCount"] = len(cards)
    manifest["finished"] = True
    _persist_manifest(manifest_path, manifest)
    return legacy_payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch sanitized n8n workflow cards")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--limit", type=int, default=100, help="Max templates to fetch")
    scope.add_argument(
        "--all",
        dest="fetch_all",
        action="store_true",
        help="Fetch the complete community corpus reported by the API",
    )
    parser.add_argument(
        "--query",
        help="Optional n8n Community search query; useful for prioritizing scenario cards",
    )
    parser.add_argument(
        "--out",
        default=str(ROOT / "data" / "templates.json"),
        help="Legacy sanitized template output path",
    )
    parser.add_argument(
        "--jsonl-out",
        default=str(ROOT / "data" / "workflow_cards.jsonl"),
        help="Workflow card JSONL artifact path",
    )
    parser.add_argument(
        "--manifest-out",
        default=str(ROOT / "generated" / "fetch_manifest.json"),
        help="Fetch manifest path",
    )
    parser.add_argument(
        "--db-out",
        default=str(ROOT / "data" / "retrieval.sqlite"),
        help="SQLite FTS5 index output path",
    )
    parser.add_argument(
        "--raw-out",
        default=str(ROOT / "generated" / "raw" / "community_workflows.jsonl"),
        help="Untrusted raw snapshot path; this directory is not copied into the agent image",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from existing JSONL/manifest and skip completed template ids",
    )
    parser.add_argument(
        "--no-detail",
        action="store_true",
        help="Skip full workflow detail fetches and build cards from listing metadata only",
    )
    args = parser.parse_args()

    jsonl_path = Path(args.jsonl_out)
    manifest_path = Path(args.manifest_out)
    legacy_out_path = Path(args.out)
    db_path = Path(args.db_out)
    raw_snapshot_path = Path(args.raw_out)

    if not args.resume:
        for path in (jsonl_path, manifest_path, db_path, raw_snapshot_path):
            if path.exists():
                path.unlink()

    total_limit = None if args.fetch_all else max(1, args.limit)
    scope_label = "all available" if total_limit is None else f"up to {total_limit}"
    query_label = f" matching {args.query!r}" if args.query else ""
    print(f"Fetching {scope_label} templates{query_label} from n8n.io...")
    with httpx.Client(headers={"Accept": "application/json"}) as client:
        basics = fetch_template_ids(client, total_limit, query=args.query)
        print(f"\nFetched {len(basics)} template listings. Building cards...")
        payload = fetch_workflow_cards(
            client,
            basics,
            jsonl_path=jsonl_path,
            manifest_path=manifest_path,
            legacy_out_path=legacy_out_path,
            db_path=db_path,
            raw_snapshot_path=raw_snapshot_path,
            resume=args.resume,
            no_detail=args.no_detail,
        )
    print(f"\nSaved {len(payload)} sanitized templates to {legacy_out_path}")
    print(f"Saved workflow-card JSONL to {jsonl_path}")
    print(f"Saved fetch manifest to {manifest_path}")
    print(f"Saved SQLite FTS5 index to {db_path}")


if __name__ == "__main__":
    main()
