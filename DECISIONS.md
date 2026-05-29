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

## 2026-05-28 — Phase 2: soft k-NN (all matched voters) vs hard k cutoff

- **Context**: PROJECT.md §5 says "k-nearest-neighbors approach" and lists k as an open question (§8). A hard cutoff at k would exclude voter k+1 entirely even if near-identical to voter k.
- **Decision**: Use soft k-NN — all voters with positive overlap contribute to book affinity, weighted by their similarity score. There is no hard k cutoff; the `top_voters` parameter controls only how many voters appear in output (b), not which voters feed into book affinity.
- **Alternatives considered**: Hard cutoff at k — simpler, matches the PROJECT.md label literally.
- **Rationale**: Cleaner mathematically; avoids the cliff where voter k+1 has no contribution despite being highly similar. Equivalent to k=∞ with affinity decay to zero for non-overlapping voters. K can always be added later as a filter if needed.
- **Trigger**: Phase 2 plan review.

## 2026-05-28 — Phase 2: voter similarity = raw weighted sum (not cosine-normalized)

- **Context**: Standard k-NN often normalizes by vector magnitude (cosine similarity) to remove length bias.
- **Decision**: Use raw weighted sum. Normalization is unnecessary because (a) we rank voters against each other for a fixed input (relative order is what matters), and (b) the user's input set is bounded at 1–10 books.
- **Known accepted bias**: The 32 voters with 11–18 books (cross-source merges and series-explode voters) have marginally more overlap surface than pure 10-book voters, so may score slightly higher when input books are on their extended lists. This is judged acceptable: a voter who genuinely read and loved 18 books has a broader overlapping surface, and a slight boost is arguably correct rather than a flaw.
- **Alternatives considered**: Cosine normalization (divide by |voter_list| or by |input_set| × |voter_list|).
- **Rationale**: Simplicity wins here; the bias is small and directionally reasonable.
- **Trigger**: Phase 2 plan review.

## 2026-05-28 — Phase 2: book aggregation = affinity-first, rarity tiebreaker only

- **Context**: Two options for ranking recommended books: (a) sum voter similarity scores (affinity-first), or (b) rarity-weighted sum (rarity-first). The user explicitly stated the concern: "a book loved by one weakly-matched voter shouldn't outrank a book loved by several strongly-matched voters just because it's rarer."
- **Decision**: Primary sort by affinity (sum of matched-voter similarity scores); secondary sort by IDF weight (rarity) as a tiebreaker only.
- **Alternatives considered**: Rarity-first (multiply affinity by IDF weight) — amplifies rare books regardless of how many matched voters love them.
- **Rationale**: Affinity directly captures "how much do the people who match you love this book?" Rarity is a secondary tie-breaker that surfaces more distinctive books when affinity is equal.
- **Trigger**: Phase 2 plan review; user's explicit instruction.

## 2026-05-28 — Phase 2: RARITY_ALPHA as the sole tuning parameter

- **Context**: The IDF formula `log((N+1)/(n_voters+1))^alpha` has one free parameter (alpha). Multiple other tuning parameters were considered: a minimum overlap floor, a hard k cutoff, a separate rarity multiplier for book ranking.
- **Decision**: Expose only `RARITY_ALPHA` as a top-level constant. At alpha=1.0: singleton weight ≈ 5.14, Middlemarch weight ≈ 1.41 (ratio ~3.6×). Alpha=0 gives uniform weighting; alpha>1 amplifies rarity further.
- **Alternatives considered**: Separate alpha for voter scoring vs book ranking; minimum overlap floor (rejected — would break the singleton case the user explicitly wanted to support).
- **Rationale**: One knob is easy to sweep; the formula is already smoothed so no floor is needed; separating voter/book alphas would add complexity without clear benefit at this stage.
- **Trigger**: Phase 2 plan review.