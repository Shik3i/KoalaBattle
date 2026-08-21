from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType


def _script_path() -> Path:
    return Path(__file__).resolve().parents[3] / "scripts" / "setup_assets.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("setup_assets", _script_path())
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_index_parser_and_plan_normalize_showdown_form_names() -> None:
    script = _load_script()
    html = """
    <a href="../">parent</a><a href="./Mr.-Mime.png">bad case</a>
    <a href="./charizard-megax.png">form</a><a href="notes.txt">notes</a>
    <a href="https://untrusted.example/evil.png">external</a>
    """
    assert script.parse_index(html, ".png") == ["Mr.-Mime.png", "charizard-megax.png"]
    categories = {"front": script.CATEGORIES["front"]}
    plan = script.build_plan({"front": script.parse_index(html, ".png")}, categories)
    assert [item[2].as_posix() for item in plan] == [
        "pokemon/front/mrmime.png",
        "pokemon/front/charizardmegax.png",
    ]


def test_plan_prefers_canonical_source_when_upstream_names_collide() -> None:
    script = _load_script()
    categories = {"front": script.CATEGORIES["front"]}
    plan = script.build_plan(
        {"front": ["pokestargiant-2.png", "pokestargiant2.png"]},
        categories,
    )
    assert plan == [
        (
            "front",
            "pokestargiant2.png",
            Path("pokemon/front/pokestargiant2.png"),
        )
    ]


def test_trainer_category_normalizes_exact_red_blue_portrait_names() -> None:
    script = _load_script()
    category = script.CATEGORIES["trainers"]
    plan = script.build_plan(
        {"trainers": [*script.KANTO_RB_TRAINERS, "acerola.png"]},
        {"trainers": category},
    )

    assert len(plan) == 14
    assert ("trainers", "brock-gen1rb.png", Path("trainers/brockgen1rb.png")) in plan


def test_status_and_verify_empty_installation(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(_script_path()),
            "--asset-root",
            str(tmp_path / "assets"),
            "--vendor-root",
            str(tmp_path / "vendor"),
            "status",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "Manifest: missing (0 managed files)" in result.stdout
    verify = subprocess.run(
        [
            sys.executable,
            str(_script_path()),
            "--asset-root",
            str(tmp_path / "assets"),
            "--vendor-root",
            str(tmp_path / "vendor"),
            "verify",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert verify.returncode == 1
    assert "manifest missing" in verify.stderr


def test_verify_and_remove_only_manifest_owned_synthetic_assets(tmp_path: Path) -> None:
    script = _load_script()
    asset_root = tmp_path / "assets"
    vendor_root = tmp_path / "vendor"
    managed = asset_root / "pokemon/front/pikachu.png"
    unrelated = asset_root / "backgrounds/custom.png"
    managed.parent.mkdir(parents=True)
    unrelated.parent.mkdir(parents=True)
    managed.write_bytes(b"synthetic png")
    unrelated.write_bytes(b"user content")
    vendor_root.mkdir()
    (vendor_root / script.MANIFEST_NAME).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "files": [
                    {
                        "path": "pokemon/front/pikachu.png",
                        "sha256": script.sha256(managed),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    common = [
        sys.executable,
        str(_script_path()),
        "--asset-root",
        str(asset_root),
        "--vendor-root",
        str(vendor_root),
    ]
    assert subprocess.run([*common, "verify"], check=False).returncode == 0
    assert subprocess.run([*common, "remove"], check=False).returncode == 0
    assert not managed.exists()
    assert unrelated.exists()
