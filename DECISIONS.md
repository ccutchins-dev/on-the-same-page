# DECISIONS.md

Append-only record of non-obvious decisions made during the project:
architectural choices, methodological choices, scope adjustments, and
meaningful interpretations of `PROJECT.md` made under ambiguity.

The bar for inclusion: would a future reader reasonably ask "wait, why did 
they do it that way?" If yes, it belongs here.

## Schema

Each entry is a heading-level entry in the Entries section below:

```
## YYYY-MM-DD — Decision title

- **Context**: the situation that required a decision
- **Decision**: what was decided
- **Alternatives considered**: other options and why they weren't chosen
- **Rationale**: why this decision
- **Trigger**: task id or event that surfaced the decision (e.g., T-007, plan review, ml-scientist Mode 2 verdict)
```

For interpretation-of-PROJECT.md entries specifically, structure as:

```
## YYYY-MM-DD — Interpretation: <what was ambiguous>

- **Ambiguity**: the unclear point in PROJECT.md (quote or paraphrase the relevant text)
- **Interpretation**: how the orchestrator interpreted it
- **Reversibility**: if this turns out wrong, how costly is it to revisit?
- **Trigger**: task id where the interpretation was applied
```

Append in chronological order. Never edit prior entries — if a decision is
later revised, append a new entry that explicitly references and supersedes
the prior one.

## Entries

*No decisions logged yet.*