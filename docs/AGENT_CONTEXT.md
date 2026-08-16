# Agent context and knowledge

Each decision is stateless at the provider boundary. `PokemonShowdownContextProvider` derives
a fresh `AgentContextSnapshot` from the requesting player's current poke-env view, the
persistent player-specific knowledge reducer, legal actions, bounded relevant history, and
optional Strategy Memory. No provider conversation ID or prior provider message is required.

## Versioned contracts

- `PlayerKnowledgeState` (`1.0`): own visible side plus only revealed opponent data.
- `AgentContextSnapshot` (`1.0`): knowledge, format/turn/side, history, legal actions, profiles,
  memory policy, and output schema version.
- prompt schema `5.0`; decision output schema `battle-decision-v2`.
- history policy `relevant-v1`; memory policy version `1.0`.

New decisions persist normalized knowledge/context, metrics, every profile/version, rendered
prompt, memory before/after, raw and parsed response, validation, and selected action. Old
Legacy decisions remain readable; the inspector reports unavailable context instead of
fabricating it.

## Knowledge and hidden information

The reducer remembers revealed moves, items, abilities, Tera type, HP/status/faint state, and
previously seen opponent Pokémon. Unknown item, ability, moves, bench members, and other
player-hidden fields remain absent. Each match and side owns a separate reducer instance.
Spectator and OBS DTOs omit the complete decision request/context and fixed team exports.

## Profiles and budgets

Prompt profiles `standard-competitive` and `benchmark-fair` are provider-independent semantic
policies. Context profiles `pokemon-standard` (estimated 4,000 tokens; ten relevant history
events) and `pokemon-compact` (2,400; five) use deterministic JSON. If a prompt exceeds its
budget, oldest history is removed first. Current knowledge and Showdown-authoritative legal
actions are never dropped. If history removal is insufficient, the prompt representation
removes duplicated active-team entries and deterministically summarizes bench Pokémon; the
minimal tier retains species/IDs, public HP/status, revealed item/ability/Tera data and revealed
move IDs. The immutable audit snapshot remains complete.

Fair mode applies the same prompt, context, memory, information, and output policies to both
players; only their legitimate player-scoped state differs. The estimate is deterministic
`ceil(characters / 4)`, not provider billing.

## Strategy Memory

`disabled` always supplies/stores no note. `strategy-note` accepts a maximum 400-character
replacement note in the validated JSON response. It replaces the prior note; KoalaBattle does
not concatenate notes or ask for private chain of thought. The same contract applies to API and
Manual Web Chat agents.

Local control provides Game State, Player Knowledge, Agent Context, Rendered Prompt, Raw
Response, Parsed Decision, and Validation views plus a small consecutive-turn diff. The local
`/admin/prompts` playground re-renders a stored context under another profile without calling
a provider.
