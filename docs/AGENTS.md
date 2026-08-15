# Agent implementation contract

An agent receives one immutable `AgentRequest` and returns one `AgentDecision`. The
battle engine does not import provider SDKs or inspect provider configuration.

Required invariants:

- choose one exact ID from `legal_actions`;
- treat `prompt`, versioned context/knowledge, and normalized state as the complete information
  boundary; never depend on provider conversation memory;
- never return a raw Showdown command;
- record public commentary separately from raw provider text;
- classify timeouts, authentication, rate limiting, network, unavailable, invalid
  request, and invalid response failures;
- use only bounded retries and a configured random, manual, or forfeit fallback;
- emit lifecycle states without credentials or raw provider objects.
- replace Strategy Memory under the selected policy; never accumulate or expose hidden reasoning.

Provider adapters implement `LLMProvider` in
`backend/koalabattle/agents/providers/base.py`. Use `FakeProvider` for unit/integration
tests. Paid-provider calls are never required by the test suite.
