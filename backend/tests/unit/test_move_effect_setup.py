from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


def load_setup_module():
    path = Path(__file__).resolve().parents[3] / "scripts" / "setup_move_effects.py"
    spec = importlib.util.spec_from_file_location("setup_move_effects", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_showdown_allowlist_excludes_unclear_and_restrictive_assets() -> None:
    setup = load_setup_module()
    assert not set(setup.SHOWDOWN_FILES) & setup.BLOCKED
    assert "lightning.png" not in setup.SHOWDOWN_FILES
    assert "bone.png" not in setup.SHOWDOWN_FILES
    assert setup.SHOWDOWN_COMMIT == "daa28cfeb19775dea9f19f90a8c8f1418bac316a"


def test_local_mapping_rejects_escape(tmp_path: Path) -> None:
    setup = load_setup_module()
    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"png")
    mapping = tmp_path / "mapping.json"
    mapping.write_text(json.dumps({"impact": "../outside.png"}), encoding="utf-8")
    args = type("Args", (), {
        "source": source, "mapping": mapping, "pack": "custom", "asset_root": tmp_path / "assets",
        "vendor_root": tmp_path / "vendor", "source_url": "https://example.invalid",
        "license": "CC0-1.0", "license_url": "https://example.invalid/license",
    })()
    with pytest.raises(ValueError, match="unsafe"):
        setup.command_local(args)
