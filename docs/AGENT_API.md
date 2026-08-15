# Agent API

Agents implement:

```python
async def decide(request: AgentRequest) -> AgentDecision: ...
```

`AgentRequest.state` is created from that player's Showdown view. `knowledge` persists only
revealed opponent facts across turns. `context` contains the complete versioned authoritative
snapshot and optional replacement Strategy Memory. `legal_actions` contains deterministic IDs
such as `move:1`, `move:1:tera`, and `switch:2`.

An agent returns one supplied ID and optional public commentary. The adapter validates the
ID again against the exact request before translating it to a Showdown order. Raw commands
are not accepted.

Manual responses are strict JSON with no extra keys:

```json
{"action":"switch:2","commentary":"Preserving the active Pokemon is safer.","strategy_memory":"Keep the cleaner healthy."}
```

The archive stores normalized state/knowledge/context and every profile/version, legal actions,
generated prompt, memory before/after, raw and parsed response, chosen action, commentary,
latency, validation attempts/errors, and provider metadata. Commentary is explicitly public;
hidden chain-of-thought is neither requested nor stored.
