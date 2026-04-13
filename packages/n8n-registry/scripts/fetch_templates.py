#!/usr/bin/env python3
"""
n8n.io resmi template API'sinden workflow şablonlarını çekip
data/templates.json olarak kaydeder.

API flow:
  1. GET /api/templates/search?rows=N  → liste (node type isimleri var, workflow JSON yok)
  2. GET /api/templates/workflows/{id} → tek template detayı (tam workflow JSON var)

Kullanım:
    python scripts/fetch_templates.py             # varsayılan 100 template
    python scripts/fetch_templates.py --limit 50
    python scripts/fetch_templates.py --out data/templates.json
"""

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

_SEARCH_URL = "https://api.n8n.io/api/templates/search"
_DETAIL_URL = "https://api.n8n.io/api/templates/workflows/{id}"


def fetch_template_ids(client: httpx.Client, total_limit: int) -> list[dict]:
    """Arama sayfalarını dolaşarak template listesini döner (id + name + nodes)."""
    templates_basic: list[dict] = []
    page = 1
    page_size = 20

    while len(templates_basic) < total_limit:
        params = {
            "rows": page_size,
            "page": page,   # skip değil page kullanılıyor
        }
        try:
            resp = client.get(_SEARCH_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            print(f"Error fetching page {page}: {exc}", file=sys.stderr)
            break

        items = data.get("workflows", [])
        if not items:
            break

        templates_basic.extend(items)
        print(f"  Listed page {page}: +{len(items)} (total: {len(templates_basic)})")

        if len(items) < page_size:
            break

        if len(templates_basic) >= total_limit:
            break

        page += 1
        time.sleep(0.2)

    return templates_basic[:total_limit]


def fetch_template_detail(client: httpx.Client, template_id: int) -> dict | None:
    """Tek template'in tam workflow JSON'unu döner."""
    try:
        resp = client.get(_DETAIL_URL.format(id=template_id), timeout=15)
        resp.raise_for_status()
        return resp.json().get("workflow", {})
    except Exception as exc:
        print(f"  Warning: failed to fetch detail for {template_id}: {exc}", file=sys.stderr)
        return None


def build_template_record(basic: dict, detail: dict | None) -> dict:
    """search + detail verilerini birleştirir, loader'ın anlayacağı formata getirir."""
    workflow_json: dict = {}
    if detail:
        workflow_json = detail.get("workflow", {})

    node_types: list[str] = []
    # Detail'den node type'larını al (varsa)
    for node in workflow_json.get("nodes", []):
        t = node.get("type", "")
        if t and t not in node_types:
            node_types.append(t)
    # Yoksa basic'teki metadata node'larından al
    if not node_types:
        for node in basic.get("nodes", []):
            t = node.get("name", "")
            if t and t not in node_types:
                node_types.append(t)

    categories = [
        c.get("name", "") if isinstance(c, dict) else str(c)
        for c in (detail or basic).get("categories", [])
    ]

    return {
        "id": basic.get("id"),
        "name": basic.get("name", "Untitled"),
        "description": basic.get("description", ""),
        "categories": categories,
        "nodeTypes": node_types,
        "totalViews": basic.get("totalViews", 0),
        "workflow": workflow_json,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch n8n workflow templates")
    parser.add_argument("--limit", type=int, default=100, help="Max templates to fetch")
    parser.add_argument(
        "--out",
        default=str(Path(__file__).parent.parent / "data" / "templates.json"),
        help="Output file path",
    )
    parser.add_argument(
        "--no-detail",
        action="store_true",
        help="Skip fetching full workflow JSON (faster, but templates won't have workflow data)",
    )
    args = parser.parse_args()

    print(f"Fetching up to {args.limit} templates from n8n.io...")
    records: list[dict] = []

    with httpx.Client(timeout=30, headers={"Accept": "application/json"}) as client:
        basics = fetch_template_ids(client, args.limit)
        print(f"\nFetched {len(basics)} template listings. Fetching details...")

        for i, basic in enumerate(basics, 1):
            tmpl_id = basic.get("id")
            detail = None if args.no_detail else fetch_template_detail(client, tmpl_id)
            record = build_template_record(basic, detail)
            records.append(record)

            if i % 10 == 0:
                print(f"  Progress: {i}/{len(basics)}")
            time.sleep(0.1)  # polite rate limiting

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved {len(records)} templates to {out_path}")


if __name__ == "__main__":
    main()
