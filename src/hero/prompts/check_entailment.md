# Check Entailment Prompt

Determine whether the given evidence text supports (entails) the claim.

## Claim
{claim}

## Evidence
{evidence_text}

## Instructions
- Answer ONLY "true" or "false".
- "true" means the evidence directly supports or implies the claim.
- "false" means the evidence does not support the claim, contradicts it, or is irrelevant.
- Do not guess or infer beyond what the evidence states.

## Output
Return a single JSON boolean: `true` or `false`
