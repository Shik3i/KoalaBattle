#!/usr/bin/env python3
"""Batch-playtest the Draft campaign against a running KoalaBattle stack.

Balance work on a thirteen-stage campaign cannot be done from single runs: one campaign
takes minutes, and one sample says nothing about a distribution. This drives real runs
through the real API and reports how far they actually get, per difficulty.

    docker compose up -d
    python3 scripts/playtest_draft.py --difficulty normal hard --runs 6 --retries 1

Every run is a real Draft run with real Showdown battles; nothing here is simulated. Runs
are deleted afterwards unless --keep is passed, so a sweep does not bury the run history.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

DIFFICULTIES = ("normal", "hard", "expert", "nightmare")


class ApiError(RuntimeError):
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
        raise ApiError(f"{path} -> {error.code} {error.read(600).decode(errors='replace')}") from error
    except OSError as error:
        raise ApiError(f"{path} -> {error}") from error


@dataclass
class StageOutcome:
    stage: str
    index: int
    opponent_level: int
    player_level: int
    status: str
    turns: int


@dataclass
class RunOutcome:
    difficulty: str
    seed: int
    run_id: str
    roster: list[str] = field(default_factory=list)
    stages: list[StageOutcome] = field(default_factory=list)
    error: str | None = None

    @property
    def cleared(self) -> int:
        return sum(1 for stage in self.stages if stage.status == "won")

    @property
    def furthest(self) -> int:
        """One-based number of the deepest battle actually reached."""
        return max((stage.index + 1 for stage in self.stages), default=0)

    @property
    def completed(self) -> bool:
        return bool(self.stages) and self.cleared == self.stages[-1].index + 1 and self.stages[-1].status == "won"


def wait_for(base: str, run_id: str, statuses: set[str], timeout: float) -> dict:
    deadline = time.time() + timeout
    view: dict = {}
    while time.time() < deadline:
        view = call(base, f"/api/challenges/{run_id}")  # type: ignore[assignment]
        if view["run"]["status"] in statuses:
            return view
        time.sleep(2)
    raise ApiError(f"timed out waiting for {sorted(statuses)}; last was {view.get('run', {}).get('status')}")


def resolve_reward(base: str, run_id: str, policy: str) -> None:
    """Answer a pending training reward so an unattended sweep keeps moving."""
    view = call(base, f"/api/challenges/{run_id}")
    assert isinstance(view, dict)
    offer = view["run"].get("pending_reward")
    if not offer:
        return
    revision = view["run"]["revision"]
    if policy == "skip":
        call(base, f"/api/challenges/{run_id}/reward/skip", {"expected_revision": revision})
        return
    call(base, f"/api/challenges/{run_id}/reward", {
        "option_id": offer["options"][0]["id"], "expected_revision": revision,
    })


def play_one(
    base: str, difficulty: str, seed: int, retries: int, stage_timeout: float, rewards: str
) -> RunOutcome:
    view = call(base, "/api/challenges", {
        "name": f"Playtest {difficulty} {seed}",
        "seed": seed,
        "difficulty": difficulty,
        # A deterministic random drafter is the worst-case roster and the only way to
        # compare difficulties on identical teams.
        "draft_controller": {"kind": "random"},
        "battle_controller": {"agent_type": "tactical-auto"},
        "opponent_controller": {"agent_type": "tactical-auto"},
        "battle_experience": "quick-sim",
        "draft_rules": {
            "roster_size": 6, "rerolls": 3, "type_rerolls": 1,
            "generation_rerolls": 1, "choice_count": 3, "species_clause": True,
        },
    })
    assert isinstance(view, dict)
    run_id = view["run"]["id"]
    outcome = RunOutcome(
        difficulty=difficulty,
        seed=seed,
        run_id=run_id,
        roster=[pick["candidate"]["species"] for pick in view["run"]["picks"]],
    )
    try:
        view = wait_for(base, run_id, {"ready", "team_review", "failed", "cancelled"}, stage_timeout)
    except ApiError as error:
        outcome.error = str(error)
        return outcome
    if view["run"]["status"] != "ready":
        outcome.error = view["run"].get("error") or f"stopped in {view['run']['status']}"
        return outcome

    losses: dict[int, int] = {}
    stage_count = len(view["stages"])
    for _ in range(stage_count * (retries + 1)):
        view = call(base, f"/api/challenges/{run_id}")  # type: ignore[assignment]
        run = view["run"]
        if run["status"] == "completed":
            break
        index = run["current_stage_index"]
        stage = view["stages"][index]
        try:
            call(base, f"/api/challenges/{run_id}/launch", {"expected_revision": run["revision"]})
            view = wait_for(base, run_id, {"stage_result", "completed", "failed"}, stage_timeout)
        except ApiError as error:
            outcome.error = str(error)
            break
        try:
            resolve_reward(base, run_id, rewards)
        except ApiError:
            pass
        view = call(base, f"/api/challenges/{run_id}")  # type: ignore[assignment]
        result = view["run"]["stage_results"][-1]
        outcome.stages.append(StageOutcome(
            stage=stage["name"], index=index,
            opponent_level=stage["level"], player_level=stage["player_level"],
            status=result["status"], turns=result["turns"],
        ))
        if result["status"] != "won":
            losses[index] = losses.get(index, 0) + 1
            if losses[index] > retries:
                break
    return outcome


def delete(base: str, run_id: str) -> None:
    for _ in range(4):
        try:
            view = call(base, f"/api/challenges/{run_id}")
            assert isinstance(view, dict)
            call(base, f"/api/challenges/{run_id}/delete", {"expected_revision": view["run"]["revision"]})
            return
        except ApiError:
            time.sleep(2)


def report(outcomes: list[RunOutcome], stage_names: list[str]) -> None:
    by_difficulty: dict[str, list[RunOutcome]] = {}
    for outcome in outcomes:
        by_difficulty.setdefault(outcome.difficulty, []).append(outcome)
    print()
    for difficulty in DIFFICULTIES:
        runs = by_difficulty.get(difficulty)
        if not runs:
            continue
        reached = [run.furthest for run in runs]
        cleared = [run.cleared for run in runs]
        completions = sum(1 for run in runs if run.completed)
        print(f"── {difficulty.upper()} ── {len(runs)} run(s)")
        print(f"   cleared:  min {min(cleared)}  median {statistics.median(cleared):.1f}  max {max(cleared)}")
        print(f"   reached:  min {min(reached)}  median {statistics.median(reached):.1f}  max {max(reached)}")
        print(f"   campaign completions: {completions}/{len(runs)}")
        walls: dict[str, int] = {}
        for run in runs:
            for stage in run.stages:
                if stage.status != "won":
                    walls[stage.stage] = walls.get(stage.stage, 0) + 1
        if walls:
            ranked = sorted(walls.items(), key=lambda item: -item[1])
            print("   losses by stage: " + ", ".join(f"{name} x{count}" for name, count in ranked))
        for run in runs:
            if run.error:
                print(f"   ! seed {run.seed}: {run.error}")
        print()
    # A per-stage win rate across every difficulty tells you which stage is the real wall.
    attempts: dict[str, list[int]] = {name: [] for name in stage_names}
    for outcome in outcomes:
        for stage in outcome.stages:
            attempts.setdefault(stage.stage, []).append(1 if stage.status == "won" else 0)
    print("── PER-STAGE WIN RATE ──")
    for name in stage_names:
        results = attempts.get(name) or []
        if not results:
            print(f"   {name:<16} never reached")
            continue
        rate = 100 * sum(results) / len(results)
        bar = "█" * round(rate / 10)
        print(f"   {name:<16} {rate:5.1f}%  ({sum(results)}/{len(results)})  {bar}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--difficulty", nargs="+", default=["normal"], choices=DIFFICULTIES)
    parser.add_argument("--runs", type=int, default=3, help="runs per difficulty")
    parser.add_argument("--seed", type=int, default=1000, help="first seed; every run uses seed+n")
    parser.add_argument("--retries", type=int, default=0, help="extra attempts allowed per stage")
    parser.add_argument("--stage-timeout", type=float, default=900.0)
    parser.add_argument(
        "--rewards", choices=("claim", "skip"), default="claim",
        help="how to answer the post-victory training reward (claim takes the first option)",
    )
    parser.add_argument("--keep", action="store_true", help="do not delete the runs afterwards")
    parser.add_argument("--json", action="store_true", help="emit machine-readable results too")
    args = parser.parse_args()

    try:
        catalog = call(args.base_url, "/api/challenges")
        assert isinstance(catalog, list)
    except ApiError as error:
        print(f"backend not reachable at {args.base_url}: {error}", file=sys.stderr)
        return 2

    outcomes: list[RunOutcome] = []
    stage_names: list[str] = []
    total = len(args.difficulty) * args.runs
    done = 0
    for difficulty in args.difficulty:
        for offset in range(args.runs):
            done += 1
            seed = args.seed + offset
            print(f"[{done}/{total}] {difficulty} seed {seed} …", flush=True)
            outcome = play_one(
                args.base_url, difficulty, seed, args.retries, args.stage_timeout, args.rewards
            )
            outcomes.append(outcome)
            if not stage_names and outcome.stages:
                view = call(args.base_url, f"/api/challenges/{outcome.run_id}")
                if isinstance(view, dict):
                    stage_names = [stage["name"] for stage in view["stages"]]
            trail = " → ".join(
                f"{stage.stage}{'' if stage.status == 'won' else '✗'}" for stage in outcome.stages
            )
            print(f"    {', '.join(outcome.roster) or 'no roster'}")
            print(f"    {trail or outcome.error or 'no battles'}", flush=True)
            if not args.keep:
                delete(args.base_url, outcome.run_id)

    report(outcomes, stage_names)
    if args.json:
        print(json.dumps([
            {
                "difficulty": o.difficulty, "seed": o.seed, "roster": o.roster,
                "cleared": o.cleared, "furthest": o.furthest, "completed": o.completed,
                "error": o.error,
                "stages": [vars(stage) for stage in o.stages],
            }
            for o in outcomes
        ], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
