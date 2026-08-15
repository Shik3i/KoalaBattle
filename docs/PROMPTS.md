# Prompt contract

Current prompt schema: `5.0`. Current template: `pokemon-battle-v2`. Decision output schema:
`battle-decision-v2`. Information profile: `standard`.

Every turn is a complete provider-independent JSON prompt containing the selected versioned
PromptProfile, policy, player-scoped normalized context, bounded relevant event history,
optional bounded Strategy Memory, exact Showdown-authoritative legal actions, and response
schema. It contains no API key, provider conversation state, hidden opponent data, raw
Showdown command, or request for private chain of thought.

Prompt profiles:

- `standard-competitive` version `1.0`: normal competitive play.
- `benchmark-fair` version `1.0`: identical semantic rules for fair model comparison.

Context profiles and trimming are documented in [Agent context](AGENT_CONTEXT.md). Provider
adapters may use different technical structured-output mechanisms, but receive the same
semantic prompt and output contract.

```json
{
  "action": "move:1",
  "commentary": "Brief public reason",
  "strategy_memory": "Replacement note for the next turn or null"
}
```

`action` must exactly match a supplied legal ID. `commentary` is public and limited to 1,000
characters. `strategy_memory` is optional, limited to 400 characters, and discarded under the
`disabled` policy. Generated prompt, normalized context, metrics, profile/version fields,
memory before/after, and validation audit persist with each new decision.
