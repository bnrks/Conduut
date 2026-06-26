#!/usr/bin/env python3
"""Copy credentials.json from the n8n container cache to data/credentials.json.

Mirror of fetch_nodes.py — n8n's HTTP types endpoint needs browser auth, so we
copy the cache file directly.

    python scripts/fetch_credentials.py [--container conduut-n8n] [--out data/credentials.json]
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

_N8N_CREDENTIALS_PATH = "/home/node/.cache/n8n/public/types/credentials.json"


def fetch_via_docker_cp(container: str, out_path: Path) -> bool:
    print(f"Copying {_N8N_CREDENTIALS_PATH} from container '{container}'...")
    result = subprocess.run(
        ["docker", "cp", f"{container}:{_N8N_CREDENTIALS_PATH}", str(out_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"ERROR: docker cp failed: {result.stderr}", file=sys.stderr)
        return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch n8n credential schemas from container")
    parser.add_argument("--container", default="conduut-n8n", help="Docker container name")
    parser.add_argument(
        "--out",
        default=str(Path(__file__).parent.parent / "data" / "credentials.json"),
        help="Output file path",
    )
    args = parser.parse_args()
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not fetch_via_docker_cp(args.container, out_path):
        sys.exit(1)
    try:
        data = json.loads(out_path.read_text(encoding="utf-8"))
        count = len(data) if isinstance(data, list) else len(data.get("data") or [])
        size_kb = out_path.stat().st_size / 1024
        print(f"Saved {count} credential types ({size_kb:.0f} KB) to {out_path}")
    except Exception as exc:
        print(f"Warning: could not parse output: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
