# Decompose Claims Prompt

Break the following fault hypothesis into individually verifiable claims.
Each claim should be a specific, testable statement that can be checked against evidence.

## Hypothesis
{hypothesis_text}

## Instructions
- Each claim should be independently verifiable against manual/evidence text.
- Include claims about: fault location, cause, affected parts, recommended fix.
- Be specific — include part numbers, model codes, measurements where implied.

## Output Format
Return a JSON array of claim strings:
```json
["claim 1", "claim 2", "claim 3"]
```
