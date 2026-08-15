from __future__ import annotations

from pathlib import Path

import pytest

from koalabattle.core.assets import LocalAssetProvider, normalize_species_id


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Mr. Mime", "mrmime"),
        ("Farfetch'd", "farfetchd"),
        ("Nidoran♀", "nidoranf"),
        ("Nidoran♂", "nidoranm"),
        ("Rotom-Wash", "rotomwash"),
        ("Landorus-Therian", "landorustherian"),
        ("Charizard-Mega-X", "charizardmegax"),
        ("Meowth-Alola", "meowthalola"),
    ],
)
def test_normalize_species_id_handles_forms_and_special_names(name: str, expected: str) -> None:
    assert normalize_species_id(name) == expected


def test_resolves_layout_variants_and_phase_one_files(tmp_path: Path) -> None:
    back = tmp_path / "pokemon" / "back"
    animated = tmp_path / "pokemon" / "animated" / "front"
    back.mkdir(parents=True)
    animated.mkdir(parents=True)
    (back / "mrmime.png").write_bytes(b"png")
    (animated / "rotomwash.gif").write_bytes(b"gif")
    (tmp_path / "pokemon" / "farfetchd.webp").write_bytes(b"webp")
    provider = LocalAssetProvider(tmp_path)

    assert provider.pokemon("Mr. Mime", perspective="back") == back / "mrmime.png"
    assert provider.pokemon("Rotom-Wash", animated=True) == animated / "rotomwash.gif"
    assert provider.pokemon("Farfetch'd") == tmp_path / "pokemon" / "farfetchd.webp"


def test_missing_and_malformed_names_never_escape_asset_root(tmp_path: Path) -> None:
    provider = LocalAssetProvider(tmp_path)
    resolution = provider.resolve_pokemon("../../etc/passwd")
    assert not resolution.found
    assert resolution.resolved_path is None
    assert provider.pokemon("missingno") is None
    assert provider.scan().unresolved_species == ("etcpasswd", "missingno")


def test_scan_reports_installed_and_invalid_assets(tmp_path: Path) -> None:
    front = tmp_path / "pokemon" / "front"
    backgrounds = tmp_path / "backgrounds"
    front.mkdir(parents=True)
    backgrounds.mkdir()
    (front / "pikachu.webp").write_bytes(b"webp")
    (backgrounds / "arena.exe").write_bytes(b"nope")

    report = LocalAssetProvider(tmp_path).scan()
    assert report.pokemon_species == 1
    assert report.categories["pokemon_front"].installed
    assert report.invalid_files == ("backgrounds/arena.exe",)
    assert not report.valid
