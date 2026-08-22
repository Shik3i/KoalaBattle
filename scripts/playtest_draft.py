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
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

DIFFICULTIES = ("normal", "hard", "expert", "nightmare")
#: A stage battle takes roughly twelve seconds of real Showdown time, so polling any
#: slower than this just adds dead time to every single stage.
POLL_SECONDS = 0.4


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
        time.sleep(POLL_SECONDS)
    raise ApiError(f"timed out waiting for {sorted(statuses)}; last was {view.get('run', {}).get('status')}")


def wait_for_new_result(base: str, run_id: str, seen: int, timeout: float) -> dict:
    """Wait until the run records a stage result beyond the ones already collected.

    Waiting on a *status* is not enough any more: a won stage advances instantly, so the
    run is already back in `stage_result` (from the previous battle) while the next match
    is only queued, and a status wait returns immediately with stale data.
    """
    deadline = time.time() + timeout
    view: dict = {}
    while time.time() < deadline:
        view = call(base, f"/api/challenges/{run_id}")  # type: ignore[assignment]
        run = view["run"]
        if len(run["stage_results"]) > seen:
            return view
        if run["status"] in {"failed", "cancelled", "completed"}:
            return view
        time.sleep(POLL_SECONDS)
    raise ApiError("timed out waiting for the next stage result")


def play_one(
    base: str, difficulty: str, seed: int, retries: int, stage_timeout: float
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
        seen = len(run["stage_results"])
        try:
            if not run["active_match_id"]:
                # Re-read the revision immediately before launching: an instant auto-advance
                # can bump it between the poll above and this call.
                current = call(base, f"/api/challenges/{run_id}")
                assert isinstance(current, dict)
                if not current["run"]["active_match_id"]:
                    call(
                        base,
                        f"/api/challenges/{run_id}/launch",
                        {"expected_revision": current["run"]["revision"]},
                    )
            view = wait_for_new_result(base, run_id, seen, stage_timeout)
        except ApiError as error:
            outcome.error = str(error)
            break
        results = view["run"]["stage_results"]
        if len(results) <= seen:
            break
        result = results[-1]
        played = view["stages"][result["stage_index"]]
        outcome.stages.append(StageOutcome(
            stage=played["name"], index=result["stage_index"],
            opponent_level=played["level"], player_level=played["player_level"],
            status=result["status"], turns=result["turns"],
        ))
        if result["status"] != "won":
            losses[result["stage_index"]] = losses.get(result["stage_index"], 0) + 1
            if losses[result["stage_index"]] > retries:
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
            time.sleep(POLL_SECONDS)


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
        "--parallel", type=int, default=1,
        help="campaigns to drive at once. Stages inside one campaign are inherently "
             "sequential, so this is the only real speed-up; keep it at or below the "
             "backend's KOALABATTLE_MAX_CONCURRENT_MATCHES.",
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

    jobs = [
        (difficulty, args.seed + offset)
        for difficulty in args.difficulty
        for offset in range(args.runs)
    ]

    def drive(job: tuple[str, int]) -> RunOutcome:
        difficulty, seed = job
        outcome = play_one(args.base_url, difficulty, seed, args.retries, args.stage_timeout)
        if not args.keep:
            delete(args.base_url, outcome.run_id)
        return outcome

    started = time.time()
    outcomes: list[RunOutcome] = []
    stage_names: list[str] = []
    workers = max(1, args.parallel)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for done, outcome in enumerate(pool.map(drive, jobs), start=1):
            outcomes.append(outcome)
            trail = " → ".join(
                f"{stage.stage}{'' if stage.status == 'won' else '✗'}" for stage in outcome.stages
            )
            print(f"[{done}/{len(jobs)}] {outcome.difficulty} seed {outcome.seed}")
            print(f"    {', '.join(outcome.roster) or 'no roster'}")
            print(f"    {trail or outcome.error or 'no battles'}", flush=True)
    # Report stages in campaign order, taken from the indexes the runs actually reached.
    by_index = {stage.index: stage.stage for outcome in outcomes for stage in outcome.stages}
    stage_names = [by_index[index] for index in sorted(by_index)]
    print(f"\nwall clock: {time.time() - started:.0f}s for {len(jobs)} campaign(s)")

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
