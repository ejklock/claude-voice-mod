#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
    echo "usage: check-version.sh vX.Y.Z" >&2
    exit 2
fi

case "$1" in
    v?*) tag_version="${1#v}" ;;
    *)
        echo "usage: check-version.sh vX.Y.Z (the tag must start with v)" >&2
        exit 2
        ;;
esac

root="$(cd "$(dirname "$0")/.." && pwd)"

python3 -I - "$root" "$tag_version" <<'PY'
import json
import sys
import tomllib
from pathlib import Path

root, tag_version = Path(sys.argv[1]), sys.argv[2]
plugin = json.loads((root / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
sidecar = tomllib.loads((root / "sidecar/pyproject.toml").read_text(encoding="utf-8"))
found = {
    ".claude-plugin/plugin.json": plugin["version"],
    "sidecar/pyproject.toml": sidecar["project"]["version"],
}
bad = {name: v for name, v in found.items() if v != tag_version}
for name, v in bad.items():
    print(f"{name} has version {v}, the tag has {tag_version}", file=sys.stderr)
sys.exit(1 if bad else 0)
PY
