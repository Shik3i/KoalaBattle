# Prompt contract

Current prompt schema: `3.0`. Current template: `battle-standard-v1`. Information
profile: `standard`.

The prompt contains only the requesting player's normalized perspective, current legal
action IDs, and at most the latest 12 public history entries. It does not include an API
key, provider object, hidden opponent information, raw Showdown command, or private
chain of thought. Both players receive the same template when fair prompt mode is on.

The response contract is deliberately small:

```json
{
  "action": "move:1",
  "commentary": "Brief public reason"
}
```

`action` must exactly match a supplied legal ID. `commentary` is public presentation
text, limited to 1,000 characters. Generated prompts and their schema/template versions
are stored in the audit archive so an old decision remains explainable after templates
change.
