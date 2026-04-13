#!/usr/bin/env python3
"""
n8n container'ından node type şemalarını çekip data/nodes.json olarak kaydeder.

n8n'in /types/nodes.json HTTP endpoint'i modern versiyonlarda browser session auth
gerektirdiğinden, bu script doğrudan container içindeki cache dosyasını kopyalar.

Kullanım:
    # n8n container adını belirt (varsayılan: conduut-n8n):
    python scripts/fetch_nodes.py

    # Farklı container adı:
    python scripts/fetch_nodes.py --container my-n8n

    # Çıktı dosyasını belirtmek için:
    python scripts/fetch_nodes.py --out data/nodes.json
"""

import argparse
import subprocess
import sys
from pathlib import Path


# n8n container'ında nodes.json'un bulunduğu yol
_N8N_NODES_PATH = "/home/node/.cache/n8n/public/types/nodes.json"


def fetch_via_docker_cp(container: str, out_path: Path) -> bool:
    """docker cp ile container'dan nodes.json'u yerel diske kopyalar."""
    print(f"Copying {_N8N_NODES_PATH} from container '{container}'...")
    result = subprocess.run(
        ["docker", "cp", f"{container}:{_N8N_NODES_PATH}", str(out_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"ERROR: docker cp failed: {result.stderr}", file=sys.stderr)
        return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch n8n node schemas from container")
    parser.add_argument(
        "--container",
        default="conduut-n8n",
        help="Docker container name (default: conduut-n8n)",
    )
    parser.add_argument(
        "--out",
        default=str(Path(__file__).parent.parent / "data" / "nodes.json"),
        help="Output file path",
    )
    args = parser.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not fetch_via_docker_cp(args.container, out_path):
        sys.exit(1)

    # Kaç node var?
    import json
    try:
        data = json.loads(out_path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            count = len(data)
        elif isinstance(data, dict):
            count = len(data.get("data") or data.get("nodes") or [])
        else:
            count = "?"
        size_mb = out_path.stat().st_size / 1024 / 1024
        print(f"Saved {count} nodes ({size_mb:.1f} MB) to {out_path}")
    except Exception as exc:
        print(f"Warning: could not parse output: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
