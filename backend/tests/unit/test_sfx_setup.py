from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType


def _script_path() -> Path:
    return Path(__file__).resolve().parents[3] / "scripts" / "setup_sfx.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("setup_sfx", _script_path())
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_install_verify_and_remove_curated_variants(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "hits").mkdir(parents=True)
    (source / "hits" / "light.wav").write_bytes(b"light")
    (source / "hits" / "heavy.wav").write_bytes(b"heavy")
    mapping = tmp_path / "mapping.json"
    mapping.write_text(
        json.dumps({"impact": ["hits/light.wav", "hits/heavy.wav"]}),
        encoding="utf-8",
    )
    common = [
        sys.executable,
        str(_script_path()),
        "--asset-root",
        str(tmp_path / "assets"),
        "--vendor-root",
        str(tmp_path / "vendor"),
    ]
    installed = subprocess.run(
        [
            *common,
            "install",
            "--source",
            str(source),
            "--mapping",
            str(mapping),
            "--pack",
            "test-pack",
            "--source-url",
            "https://example.test/pack",
            "--license-url",
            "https://example.test/license",
            "--license",
            "CC0",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert installed.returncode == 0, installed.stderr
    assert (tmp_path / "assets/audio/impact-01.wav").read_bytes() == b"light"
    assert (tmp_path / "assets/audio/impact-02.wav").read_bytes() == b"heavy"
    assert subprocess.run([*common, "verify"], check=False).returncode == 0
    manifest = json.loads((tmp_path / "vendor/sfx-manifest.json").read_text())
    assert manifest["packs"]["test-pack"]["license"] == "CC0"
    assert subprocess.run([*common, "remove", "--pack", "test-pack"], check=False).returncode == 0
    assert not (tmp_path / "assets/audio/impact-01.wav").exists()


def test_mapping_rejects_path_escape(tmp_path: Path) -> None:
    script = _load_script()
    mapping = tmp_path / "mapping.json"
    mapping.write_text(json.dumps({"impact": ["../outside.wav"]}), encoding="utf-8")
    loaded = script.load_mapping(mapping)
    source = tmp_path / "source"
    source.mkdir()
    try:
        script.safe_source_path(source, loaded["impact"][0])
    except ValueError as error:
        assert "escapes" in str(error)
    else:
        raise AssertionError("path escape was accepted")
