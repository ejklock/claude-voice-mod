import json
from pathlib import Path

import pytest

MANIFEST = Path(".claude-plugin") / "plugin.json"


def find_plugin_json() -> Path:
    for directory in Path(__file__).resolve().parents:
        candidate = directory / MANIFEST
        if candidate.is_file():
            return candidate
    raise AssertionError(f"no {MANIFEST} above {Path(__file__).resolve()}")


@pytest.fixture(scope="session")
def plugin_version() -> str:
    return str(json.loads(find_plugin_json().read_text(encoding="utf-8"))["version"])
