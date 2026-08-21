from __future__ import annotations

import hashlib
import json
import random

from .models import ChallengeRun, DraftCandidate, DraftOffer


def candidate_identity(candidate: DraftCandidate, species_clause: bool) -> str:
    """Use Showdown's authoritative base-species identity for Species Clause."""
    return candidate.base_species_id if species_clause else candidate.entry_id


def _rng(run: ChallengeRun, *, nonce: int) -> random.Random:
    material = json.dumps(
        {
            "definition": [run.definition.id, run.definition.version],
            "draft_rules_version": run.draft_rules_version,
            "catalog_hash": run.draft_pool.catalog_hash,
            "showdown_version": run.draft_pool.showdown_version,
            "rules": run.definition.draft_rules.model_dump(mode="json"),
            "seed": run.seed,
            "round": len(run.picks) + 1,
            "nonce": nonce,
            "consumed_species_ids": sorted(run.consumed_species_ids),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return random.Random(int.from_bytes(hashlib.sha256(material).digest()))


def feasible_candidates(run: ChallengeRun) -> tuple[DraftCandidate, ...]:
    rules = run.definition.draft_rules
    consumed = set(run.consumed_species_ids)
    return tuple(
        candidate
        for candidate in run.draft_pool.candidates
        if candidate_identity(candidate, rules.species_clause) not in consumed
    )


def unseen_identity_count(run: ChallengeRun) -> int:
    rules = run.definition.draft_rules
    return len(
        {
            candidate_identity(candidate, rules.species_clause)
            for candidate in feasible_candidates(run)
        }
    )


def _buckets(run: ChallengeRun) -> dict[tuple[int, str], tuple[DraftCandidate, ...]]:
    rules = run.definition.draft_rules
    grouped: dict[tuple[int, str], dict[str, DraftCandidate]] = {}
    for candidate in feasible_candidates(run):
        identity = candidate_identity(candidate, rules.species_clause)
        for type_name in candidate.types:
            bucket = grouped.setdefault((candidate.introduction_generation, type_name), {})
            previous = bucket.get(identity)
            if previous is None or candidate.entry_id < previous.entry_id:
                bucket[identity] = candidate
    return {
        key: tuple(sorted(values.values(), key=lambda item: item.entry_id))
        for key, values in grouped.items()
    }


def generate_offer(
    run: ChallengeRun,
    *,
    nonce: int | None = None,
    fixed_generation: int | None = None,
    fixed_type: str | None = None,
    excluded_generation: int | None = None,
    excluded_type: str | None = None,
) -> DraftOffer:
    if run.current_offer is not None:
        raise ValueError("the current draft offer is already persisted")
    rules = run.definition.draft_rules
    if len(run.picks) >= rules.roster_size:
        raise ValueError("draft roster is already complete")

    remaining_slots = rules.roster_size - len(run.picks)
    unseen = unseen_identity_count(run)
    if unseen < remaining_slots:
        raise ValueError(
            f"draft pool has only {unseen} unseen Species-Clause identities for "
            f"{remaining_slots} remaining roster slots"
        )

    buckets = _buckets(run)
    largest_bucket = max((len(values) for values in buckets.values()), default=0)
    # Consuming this offer must still leave one unseen identity for every later roster slot.
    safe_consumption = unseen - (remaining_slots - 1)
    offered_count = min(rules.choice_count, largest_bucket, safe_consumption)
    valid = [
        (key, values)
        for key, values in buckets.items()
        if offered_count
        and len(values) >= offered_count
        and (fixed_generation is None or key[0] == fixed_generation)
        and (fixed_type is None or key[1] == fixed_type)
        and (excluded_generation is None or key[0] != excluded_generation)
        and (excluded_type is None or key[1] != excluded_type)
    ]
    if not valid:
        raise ValueError(
            "no unseen Generation + Type bucket can produce a safe offer for the remaining roster"
        )

    valid.sort(key=lambda item: item[0])
    offer_nonce = run.offer_nonce if nonce is None else nonce
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


def attach_offer(
    run: ChallengeRun,
    *,
    nonce: int | None = None,
    fixed_generation: int | None = None,
    fixed_type: str | None = None,
    excluded_generation: int | None = None,
    excluded_type: str | None = None,
) -> ChallengeRun:
    """Persist an offer and consume every displayed Showdown species identity atomically."""
    offer = generate_offer(
        run,
        nonce=nonce,
        fixed_generation=fixed_generation,
        fixed_type=fixed_type,
        excluded_generation=excluded_generation,
        excluded_type=excluded_type,
    )
    rules = run.definition.draft_rules
    consumed = set(run.consumed_species_ids)
    consumed.update(
        candidate_identity(candidate, rules.species_clause) for candidate in offer.options
    )
    return run.model_copy(
        update={"current_offer": offer, "consumed_species_ids": tuple(sorted(consumed))}
    )


def can_generate_offer(
    run: ChallengeRun,
    *,
    nonce: int | None = None,
    fixed_generation: int | None = None,
    fixed_type: str | None = None,
    excluded_generation: int | None = None,
    excluded_type: str | None = None,
) -> bool:
    try:
        generate_offer(
            run.model_copy(update={"current_offer": None}),
            nonce=nonce,
            fixed_generation=fixed_generation,
            fixed_type=fixed_type,
            excluded_generation=excluded_generation,
            excluded_type=excluded_type,
        )
    except ValueError:
        return False
    return True


def deterministic_random_choice(run: ChallengeRun) -> DraftCandidate:
    offer = run.current_offer
    if offer is None:
        raise ValueError("random draft choice requires a persisted current offer")
    rng = _rng(run, nonce=offer.nonce + 10_000)
    return offer.options[rng.randrange(len(offer.options))]
