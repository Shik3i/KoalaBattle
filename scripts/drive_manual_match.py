#!/usr/bin/env python3
"""Play a Manual Web Chat match to completion with realistic public commentary.

Dogfooding and review media need a battle whose commentary reads like something a person
would actually paste back from a web chat, rather than a placeholder from a test agent. This
drives the real Manual transport: it copies nothing, it just answers each pending request
through the same `/api/decisions/{id}` endpoint the workspace uses.

    python scripts/drive_manual_match.py --format gen9randombattle --name "Review battle"
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
import urllib.error
import urllib.request

#: Commentary in the length band the overlay is designed for: one concise sentence.
COMMENTARY = (
    "Staying in to keep momentum while the matchup is still in my favour.",
    "Going for the strongest neutral hit before it can set up on me.",
    "Pivoting out now so I keep a healthy answer in reserve for later.",
    "This should force the switch and let me take the free turn.",
    "Chipping it down first; the knockout range opens up next turn.",
    "Playing around the obvious status move rather than risking the miss.",
    "Taking the safe line here instead of gambling on the high roll.",
    "Setting up while it is locked into a move that cannot hurt me.",
    "Trading this one off so my sweeper gets a clean entry afterwards.",
    "Pressing the advantage before the speed tier turns against me.",
)


def request(url: str, payload: dict[str, object] | None = None) -> dict[str, object]:
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    method = "POST" if data else "GET"
    call = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(call, timeout=30) as response:  # noqa: S310
        return json.loads(response.read())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://localhost:8001")
    parser.add_argument("--format", default="gen9randombattle")
    parser.add_argument("--name", default="Review battle")
    parser.add_argument("--p1", default="Gemini")
    parser.add_argument("--p2", default="ChatGPT")
    parser.add_argument("--maximum-turns", type=int, default=40)
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--timeout", type=float, default=900.0)
    args = parser.parse_args()

    match = request(
        f"{args.api}/api/matches",
        {
            "name": args.name,
            "format": args.format,
            "player1": {"display_name": args.p1, "agent_type": "manual"},
            "player2": {"display_name": args.p2, "agent_type": "manual"},
            "prompt_profile": "benchmark-fair",
            "context_profile": "pokemon-standard",
            "memory_policy": "strategy-note",
            "team_policy": "showdown-random",
            "limits": {"maximum_turns": args.maximum_turns},
        },
    )
    match_id = match["id"]
    print(f"match {match_id} ({args.format})", flush=True)

    chooser = random.Random(args.seed)
    deadline = time.monotonic() + args.timeout
    answered = 0
    idle = 0
    while time.monotonic() < deadline:
        archive = request(f"{args.api}/api/matches/{match_id}")
        status = archive["status"]
        if status in {"completed", "failed", "cancelled"}:
            print(f"status={status} turns={archive['turns']} answers={answered}")
            print(match_id)
            return 0 if status == "completed" else 1
        pending = request(f"{args.api}/api/matches/{match_id}/pending")["requests"]
        if not pending:
            idle += 1
            time.sleep(0.5)
            continue
        idle = 0
        for item in pending:
            actions = item["legal_actions"]
            # Prefer a damaging move so the review battle actually shows combat, but keep
            # switches in the mix so switch-in and faint choreography appear too.
            moves = [
                a for a in actions if a["type"] == "move" and (a.get("power") or 0) > 0
            ]
            switches = [a for a in actions if a["type"] == "switch"]
            pool = moves or actions
            if switches and chooser.random() < 0.18:
                pool = switches
            action = chooser.choice(pool)
            try:
                request(
                    f"{args.api}/api/decisions/{item['request_id']}",
                    {
                        "raw_response": json.dumps(
                            {
                                "action": action["id"],
                                "commentary": chooser.choice(COMMENTARY),
                                "strategy_memory": "Keep a healthy pivot in reserve.",
                            }
                        )
                    },
                )
                answered += 1
            except urllib.error.HTTPError as error:
                # The request can be answered by a concurrent poll or expire on a faint.
                if error.code not in {404, 422}:
                    raise
        time.sleep(0.35)

    print("timed out waiting for the match to finish", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
