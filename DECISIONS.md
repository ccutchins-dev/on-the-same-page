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

## 2026-05-28 — Series rule reversed: collapse → explode

- **Context**: PROJECT.md §4 recorded a "decided" series rule: collapse a multi-volume series to one canonical book. During Phase 1 planning, a concrete example (Updike Rabbit) prompted reconsideration.
- **Decision**: Reversed. Each listed volume is its own canonical book. An omnibus/series-level entry (e.g. "Rabbit Angstrom") explodes into its constituent volumes via a human-curated series_registry; the omnibus itself is not a canonical book. Lists that included a full series become 11–14 books long.
- **Alternatives considered**: (a) keep collapse — one "Rabbit" canonical book for all voters; (b) explode — each volume separate, longer lists.
- **Rationale**: Explode is finer-grained: a voter who picked "Rabbit, Run" and one who picked "Rabbit at Rest" partially agree (same series), but not fully. Collapsing loses that distinction. The kNN algorithm is indifferent to list length varying by a few entries.
- **Trigger**: Plan review session, user explicitly chose explode.

## 2026-05-28 — Cross-source voter identity: merge by name

- **Context**: 8 voter names appear in both Top Ten Books and Guardian with different lists per source. Decision needed: is (voter_name, source) or voter_name the taste unit?
- **Decision**: voter_name is the taste unit. The 8 cross-source voters are merged into one; their book sets are the union of both lists. 342 taste units total.
- **Alternatives considered**: Keep (voter_name, source) separate → 350 units, lists stay context-pure.
- **Rationale**: Same person = same taste unit. The ~350 figure in PROJECT.md §3 was counting per-source rows, not people.
- **Trigger**: Plan review session.

## 2026-05-28 — Phase 1 outputs committed to git

- **Context**: CLAUDE.md says "don't commit generated output unless PROJECT.md says so." Phase 1 deliverables (canonical_books.csv, voter_books.csv, review_flags.csv, row_to_canonical.csv) are explicitly the Phase 1 artifact per PROJECT.md §4, they are human-auditable, and Phase 2 consumes them directly.
- **Decision**: Commit the four output CSVs under data/processed/. Gitignore is not applied to that directory (the lines are commented out).
- **Alternatives considered**: Gitignore and regenerate on demand.
- **Rationale**: The artifacts are the deliverable, not a build byproduct. Reviewing them requires them to be in the repo.
- **Trigger**: Plan review session.

## 2026-05-28 — OLID is not a per-book key; same-work OLIDs merged via T1

- **Context**: Initial assumption was that OpenLibrary IDs (work-level) uniquely identify books. Exploration found Middlemarch has 7 distinct OLIDs, 43 works total are split across multiple OLIDs.
- **Decision**: OLID is a strong anchor only when two rows *share* an ID (T0, auto-merge). Same-work multi-OLID splits are healed by T1 (exact normalized title + author surname), which is also the bridge that backfills OLID-less Top Ten Books rows into Guardian-anchored clusters.
- **Alternatives considered**: Trust OLID alone — would produce 7 separate "Middlemarch" canonical books.
- **Rationale**: T0 + T1 together achieve "extremely confident" identity resolution without requiring OLID to be unique.
- **Trigger**: Data exploration during Phase 1.