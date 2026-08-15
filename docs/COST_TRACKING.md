# Usage and cost tracking

Provider usage is normalized to input, cached input, output, and total tokens when the
provider reports them. Each decision stores normalized usage, latency, retry attempts,
fallback, error category, and an estimated cost.

Pricing is operator-controlled and versioned:

```dotenv
KOALABATTLE_PRICING_VERSION=2026-08-local
KOALABATTLE_PRICING_TABLE_JSON={"openai:gpt-5-mini":{"input_per_million":0.25,"output_per_million":2,"cached_input_per_million":0.025}}
```

Rates are USD per one million tokens. No prices ship as authoritative defaults because
prices change. Unknown model pricing, missing usage, and incomplete provider accounting
produce `available=false`; KoalaBattle never invents a value.

Player and match cost limits prevent later provider calls once recorded estimated spend
reaches the configured threshold. A response that crosses a threshold is retained and
executed, then the configured fallback applies on that player's next decision.
