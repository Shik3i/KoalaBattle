#!/usr/bin/env python3
"""Prove each Kanto stage is actually hard by throwing a worst-case team at it.

A stage that a deliberately terrible team can still beat is not a difficulty curve, it is
decoration. For every trainer this builds the worst legal team it can — Pokemon whose own
attacks that trainer's specialty resists, and which the specialty hits hard — then runs a
real Showdown battle against the shipped stage team at the stage level.

    docker compose up -d
    python3 scripts/probe_stage_floor.py                 # every stage
    python3 scripts/probe_stage_floor.py --stage koga brock

A loss is the expected result. A win is a finding: that trainer can be beaten with no type
advantage at all and wants a stronger core.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

#: Attacking type -> (super effective against, resisted by, immune).
CHART: dict[str, tuple[set[str], set[str], set[str]]] = {
    "normal": (set(), {"rock", "steel"}, {"ghost"}),
    "fire": ({"grass", "ice", "bug", "steel"}, {"fire", "water", "rock", "dragon"}, set()),
    "water": ({"fire", "ground", "rock"}, {"water", "grass", "dragon"}, set()),
    "electric": ({"water", "flying"}, {"electric", "grass", "dragon"}, {"ground"}),
    "grass": (
        {"water", "ground", "rock"},
        {"fire", "grass", "poison", "flying", "bug", "dragon", "steel"},
        set(),
    ),
    "ice": ({"grass", "ground", "flying", "dragon"}, {"fire", "water", "ice", "steel"}, set()),
    "fighting": (
        {"normal", "ice", "rock", "dark", "steel"},
        {"poison", "flying", "psychic", "bug", "fairy"},
        {"ghost"},
    ),
    "poison": ({"grass", "fairy"}, {"poison", "ground", "rock", "ghost"}, {"steel"}),
    "ground": ({"fire", "electric", "poison", "rock", "steel"}, {"grass", "bug"}, {"flying"}),
    "flying": ({"grass", "fighting", "bug"}, {"electric", "rock", "steel"}, set()),
    "psychic": ({"fighting", "poison"}, {"psychic", "steel"}, {"dark"}),
    "bug": (
        {"grass", "psychic", "dark"},
        {"fire", "fighting", "poison", "flying", "ghost", "steel", "fairy"},
        set(),
    ),
    "rock": ({"fire", "ice", "flying", "bug"}, {"fighting", "ground", "steel"}, set()),
    "ghost": ({"psychic", "ghost"}, {"dark"}, {"normal"}),
    "dragon": ({"dragon"}, {"steel"}, {"fairy"}),
    "dark": ({"psychic", "ghost"}, {"fighting", "dark", "fairy"}, set()),
    "steel": ({"ice", "rock", "fairy"}, {"fire", "water", "electric", "steel"}, set()),
    "fairy": ({"fighting", "dragon", "dark"}, {"fire", "poison", "steel"}, set()),
}


class ProbeError(RuntimeError):
    pass


def call(base: str, path: str, body: object | None = None, timeout: float = 180.0) -> object:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        f"{base}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST" if data is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            raw = response.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        detail = error.read(600).decode(errors="replace")
        raise ProbeError(f"{path} -> {error.code} {detail}") from error
    except OSError as error:
        raise ProbeError(f"{path} -> {error}") from error


def effectiveness(attacking: str, defending: tuple[str, ...]) -> float:
    strong, resisted, immune = CHART.get(attacking.lower(), (set(), set(), set()))
    multiplier = 1.0
    for kind in (item.lower() for item in defending):
        if kind in immune:
            return 0.0
        if kind in strong:
            multiplier *= 2
        elif kind in resisted:
            multiplier *= 0.5
    return multiplier


def worst_case_score(entry: dict, specialty: str) -> float | None:
    """Lower is worse for the player. `None` disqualifies the species as a probe pick."""
    types = tuple(entry["types"])
    outgoing = max((effectiveness(kind, (specialty,)) for kind in types), default=1.0)
    if outgoing > 1:
        return None  # it has a super-effective STAB, so it is not a worst case
    incoming = effectiveness(specialty, types)
    stat_total = entry.get("base_stat_total") or 600
    return outgoing * 100 - incoming * 40 + stat_total / 20


def build_probe_team(
    species: list[dict], specialty: str, level: int, min_bst: int = 0
) -> str:
    ranked: list[tuple[float, str, dict]] = []
    for entry in species:
        if entry["is_mega"] or entry["is_gmax"] or entry["battle_only"] or entry["cosmetic"]:
            continue
        if entry["unavailable"] or not entry["recommended_moves"] or not entry["abilities"]:
            continue
        if (entry.get("base_stat_total") or 0) < min_bst:
            continue
        score = worst_case_score(entry, specialty)
        if score is not None:
            ranked.append((score, entry["name"], entry))
    ranked.sort(key=lambda item: (item[0], item[1]))
    chosen: list[dict] = []
    seen: set[str] = set()
    for _, _, entry in ranked:
        if entry["base_species_id"] in seen:
            continue
        seen.add(entry["base_species_id"])
        chosen.append(entry)
        if len(chosen) == 6:
            break
    if len(chosen) < 6:
        raise ProbeError(f"could not assemble a probe team against {specialty}")
    blocks = []
    for entry in chosen:
        lines = [
            f"{entry['name']} @ {entry['required_item'] or 'Leftovers'}",
            f"Ability: {entry['abilities'][0]['name']}",
            f"Level: {level}",
            "EVs: 85 HP / 85 Atk / 85 Def / 85 SpA / 85 SpD / 85 Spe",
        ]
        lines += [f"- {move}" for move in entry["recommended_moves"]]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def snapshot(base: str, name: str, team: str, fmt: str) -> str:
    result = call(base, "/api/teams/validate", {
        "name": name[:120], "format": fmt, "team_text": team, "source": "imported", "save": True,
    })
    assert isinstance(result, dict)
    if not result["validation"]["valid"]:
        raise ProbeError("; ".join(result["validation"]["errors"])[:400])
    return result["snapshot"]["id"]


def run_probe(
    base: str, stage: dict, fmt: str, species: list[dict], timeout: float, min_bst: int = 0
) -> dict:
    specialty = (stage.get("specialty") or "Normal").lower()
    probe = build_probe_team(species, specialty, stage["level"], min_bst)
    probe_id = snapshot(base, f"floor probe {stage['name']}", probe, fmt)
    stage_id = snapshot(base, f"stage {stage['name']}", stage["opponent_team_at_level"], fmt)
    match = call(base, "/api/matches", {
        "name": f"Floor probe {stage['name']}"[:120],
        "format": fmt,
        "player1": {"display_name": "Worst case", "agent_type": "tactical-auto",
                    "team_source": "imported", "team_snapshot_id": probe_id},
        "player2": {"display_name": stage["name"][:60], "agent_type": "tactical-auto",
                    "team_source": "imported", "team_snapshot_id": stage_id},
        "team_policy": "fixed",
    })
    assert isinstance(match, dict)
    deadline = time.time() + timeout
    while time.time() < deadline:
        current = call(base, f"/api/matches/{match['id']}")
        assert isinstance(current, dict)
        if current["status"] in {"completed", "failed", "cancelled", "interrupted"}:
            return {
                "stage": stage["name"], "specialty": stage.get("specialty"),
                "probe": [b.splitlines()[0].split(" @")[0] for b in probe.split("\n\n")],
                "status": current["status"], "winner": current.get("winner"),
                "turns": current.get("turns"),
            }
        time.sleep(3)
    raise ProbeError(f"probe against {stage['name']} did not finish")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--validator-url", default="http://127.0.0.1:8002")
    parser.add_argument("--stage", nargs="*", help="stage ids to probe (default: all)")
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument(
        "--min-bst", type=int, default=0,
        help="only use species at or above this base stat total. The default picks the very "
             "weakest legal answer, which proves little against a level 100 Champion; "
             "--min-bst 480 asks the sharper question: can a *good* team with no type "
             "advantage still win?",
    )
    args = parser.parse_args()

    sys.path.insert(0, "backend")
    from koalabattle.challenges.service import (  # noqa: PLC0415
        _definition,
        _with_level,
        _with_unique_duplicate_nicknames,
    )

    definition = _definition("kanto-gym-gauntlet")
    with urllib.request.urlopen(  # noqa: S310
        f"{args.validator_url}/dex-species?format={definition.format}", timeout=180
    ) as response:
        species = json.loads(response.read())["species"]

    wanted = set(args.stage or [])
    results: list[dict] = []
    for stage in definition.stages:
        if wanted and stage.id not in wanted:
            continue
        payload = {
            "name": stage.name,
            "level": stage.level,
            "specialty": stage.specialty,
            "opponent_team_at_level": _with_unique_duplicate_nicknames(
                _with_level(stage.opponent_team, stage.level)
            ),
        }
        print(f"probing {stage.name} (Lv {stage.level}, {stage.specialty}) ...", flush=True)
        try:
            outcome = run_probe(
                args.base_url, payload, definition.format, species, args.timeout, args.min_bst
            )
        except ProbeError as error:
            print(f"  ! {error}")
            continue
        beaten = outcome["winner"] == "p1"
        print(f"  probe team: {', '.join(outcome['probe'])}")
        verdict = "*** PROBE WON - stage is too weak ***" if beaten else "stage held"
        print(f"  {verdict}  ({outcome['status']}, winner={outcome['winner']}, "
              f"{outcome['turns']} turns)", flush=True)
        results.append(outcome)

    won = [item for item in results if item["winner"] == "p1"]
    print(f"\nstages probed: {len(results)}   beaten by a worst-case team: {len(won)}")
    for item in won:
        print(f"  - {item['stage']} ({item['specialty']})")
    return 1 if won else 0


if __name__ == "__main__":
    raise SystemExit(main())
