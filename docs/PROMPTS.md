# Prompt contract

Current prompt schema: `6.0`. Current template: `battle-text-v1`. Decision output schema:
`battle-decision-v2`. Information profile: `standard`.

## Structured context and rendered prompt are different things

`AgentContextSnapshot`, `PlayerKnowledgeState` and `PromptProfile` remain the versioned
internal models, and they are what gets persisted and audited. The prompt an agent actually
receives is a *rendering* of that snapshot, produced by
`koalabattle/agents/prompt_renderer.py`:

```
AgentContextSnapshot  ->  PromptRenderer  ->  compact model-friendly prompt
```

The rendered prompt is readable text, not `json.dumps(snapshot)`. The Prompt Inspector on the
control page shows both, plus player knowledge, raw provider response and parsed decision, so
it stays obvious that the compact prompt is a view of richer state.

## Shape

Rules come first, state second. Providers with a real system channel receive the two parts
separately (`system_prompt` / `user_prompt`); Manual Web Chat receives them concatenated as
one self-contained block that a fresh chat with no history can act on.

System part:

- who the agent is, which player it is, and the objective
- the action contract and the output JSON schema
- the hidden-information policy

User part, in order: `FORMAT`, `TURN`, `YOUR ACTIVE POKEMON`, `YOUR BENCH`, `OPPONENT ACTIVE`,
`KNOWN OPPONENT TEAM`, `FIELD`, `RECENT EVENTS`, `YOUR STRATEGY NOTE`, `LEGAL ACTIONS`.

Your own team is complete: every bench Pokémon carries its typing, HP, status, level and full
move list with metadata, because an agent that cannot see what its bench does cannot switch
well. Legal actions are self-describing — each move action states type, damage class, base
power, accuracy, PP and priority; each switch action states the display name and HP — so the
model never has to cross-reference another section.

Recent events are rendered as sentences from the reading player's own perspective, not as raw
`|move|p1a: …` protocol lines.

## Generation awareness

The renderer omits every mechanic the selected format does not have, using the mechanics the
pinned Showdown build reports for that format:

| Generation | Items | Abilities | Physical/special split | Terastallization |
| --- | --- | --- | --- | --- |
| 1 | no | no | no | no |
| 2 | yes | no | no | no |
| 3 | yes | yes | no | no |
| 4-8 | yes | yes | yes | no |
| 9 | yes | yes | yes | yes |

A Gen 1 prompt therefore contains no `Ability:`, `Item:` or `Tera type:` lines, states that
damage class follows the move's type, and never lists a `move:N:tera` action. Legal actions
always come from Showdown, so an impossible mechanic cannot appear.

## Hidden information

The old `Do not infer hidden state.` and `Use only information in this prompt.` rules were
replaced, because they discouraged ordinary competitive reasoning:

- The supplied snapshot is the only source of current match facts.
- General Pokémon battle knowledge and the supplied format rules may be used freely.
- Probabilistic strategic predictions from public information are allowed; unrevealed
  opponent information must never be stated as fact.

Unknown values are rendered as `unknown`, never as a fake-looking token such as
`unknown_item`.

## Names

Human-facing labels use Showdown's canonical display names — `Oricorio-Pom-Pom`, not
`oricoriopompom`. Machine IDs remain stable internally and in the action IDs.

## Profiles

- `standard-competitive` version `2.0`
- `benchmark-fair` version `2.0`

Both state semantically identical rules, the same context policy, the same move metadata and
the same memory policy; only player-specific state differs. Provider adapters may use
different technical structured-output mechanisms but receive the same semantic contract.

## Output

```json
{
  "action": "move:1",
  "commentary": "One short viewer-facing sentence",
  "strategy_memory": "Replacement note for the next turn or null"
}
```

`action` must exactly match a supplied legal ID. `commentary` is public: it is shown on the
overlay and spoken by TTS, so it is limited to 240 characters and trimmed rather than
rejected if a model writes more. `strategy_memory` is private, limited to 400 characters,
never broadcast or spoken, and discarded under the `disabled` policy.

Generated prompt, normalized context, metrics, profile/version fields, memory before/after,
and validation audit persist with each new decision. Archives written before this schema keep
loading; their prompts are replayed as recorded.
