from __future__ import annotations

import hashlib
import json
import random

from .models import ChallengeRun, DraftCandidate, DraftOffer


def _rng(run: ChallengeRun, *, nonce: int) -> random.Random:
    material = json.dumps(
        {
            "definition": [run.definition.id, run.definition.version],
            "catalog_hash": run.pricing.catalog_hash,
            "rules": run.definition.draft_rules.model_dump(mode="json"),
            "seed": run.seed,
            "round": len(run.picks) + 1,
            "nonce": nonce,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return random.Random(int.from_bytes(hashlib.sha256(material).digest()))


def _identity(candidate: DraftCandidate, species_clause: bool) -> str:
    return candidate.base_species_id if species_clause else candidate.entry_id


def feasible_candidates(run: ChallengeRun) -> tuple[DraftCandidate, ...]:
    rules = run.definition.draft_rules
    picked = {_identity(pick.candidate, rules.species_clause) for pick in run.picks}
    slots_after_pick = rules.roster_size - len(run.picks) - 1
    result: list[DraftCandidate] = []
    for candidate in run.pricing.candidates:
        identity = _identity(candidate, rules.species_clause)
        if identity in picked or candidate.points > run.credits_remaining:
            continue
        if slots_after_pick <= 0:
            result.append(candidate)
            continue
        remaining_budget = run.credits_remaining - candidate.points
        excluded = picked | {identity}
        cheapest: dict[str, int] = {}
        for other in run.pricing.candidates:
            other_identity = _identity(other, rules.species_clause)
            if other_identity in excluded:
                continue
            cheapest[other_identity] = min(cheapest.get(other_identity, other.points), other.points)
        if len(cheapest) < slots_after_pick:
            continue
        if sum(sorted(cheapest.values())[:slots_after_pick]) <= remaining_budget:
            result.append(candidate)
    return tuple(result)


def minimum_completion_cost(run: ChallengeRun) -> int:
    """Cheapest Species-Clause-safe way to fill every remaining roster slot."""
    rules = run.definition.draft_rules
    picked = {_identity(pick.candidate, rules.species_clause) for pick in run.picks}
    cheapest: dict[str, int] = {}
    for candidate in run.pricing.candidates:
        identity = _identity(candidate, rules.species_clause)
        if identity in picked:
            continue
        cheapest[identity] = min(cheapest.get(identity, candidate.points), candidate.points)
    slots = rules.roster_size - len(run.picks)
    if slots <= 0:
        return 0
    if len(cheapest) < slots:
        raise ValueError("draft pool cannot fill the remaining roster slots")
    return sum(sorted(cheapest.values())[:slots])


def generate_offer(run: ChallengeRun, *, nonce: int | None = None) -> DraftOffer:
    if len(run.picks) >= run.definition.draft_rules.roster_size:
        raise ValueError("draft roster is already complete")
    offer_nonce = run.offer_nonce if nonce is None else nonce
    choice_count = run.definition.draft_rules.choice_count
    feasible = feasible_candidates(run)
    buckets: dict[tuple[int, str], list[DraftCandidate]] = {}
    for candidate in feasible:
        for type_name in candidate.types:
            buckets.setdefault((candidate.introduction_generation, type_name), []).append(candidate)
    largest_bucket = max((len(values) for values in buckets.values()), default=0)
    offered_count = min(choice_count, largest_bucket)
    valid = [
        (key, sorted(values, key=lambda item: (item.points, item.entry_id)))
        for key, values in buckets.items()
        if offered_count and len(values) >= offered_count
    ]
    if not valid:
        raise ValueError(
            "the remaining roster cannot be completed with this pricing pool and budget; "
            "cancel this run or start again with broader coverage"
        )
    valid.sort(key=lambda item: item[0])
    rng = _rng(run, nonce=offer_nonce)
    (generation, type_name), candidates = valid[rng.randrange(len(valid))]
    options = tuple(sorted(rng.sample(candidates, offered_count), key=lambda item: item.entry_id))
    fingerprint_material = json.dumps(
        {
            "round": len(run.picks) + 1,
            "nonce": offer_nonce,
            "generation": generation,
            "type": type_name,
            "options": [item.model_dump(mode="json") for item in options],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return DraftOffer(
        round=len(run.picks) + 1,
        nonce=offer_nonce,
        generation=generation,
        type=type_name,
        options=options,
        fingerprint=hashlib.sha256(fingerprint_material).hexdigest(),
    )


def deterministic_random_choice(run: ChallengeRun) -> DraftCandidate:
    offer = run.current_offer or generate_offer(run)
    rng = _rng(run, nonce=offer.nonce + 10_000)
    return offer.options[rng.randrange(len(offer.options))]
