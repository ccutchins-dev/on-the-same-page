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

## 2026-05-29 — Phase 2b: position factor edge-case rules

- **Context**: voter_books.csv positions have three non-standard patterns from Phase 1 artifacts: compound 'a;b' (21 rows, cross-source merged voters), blank '' (48 rows, series_explode volumes), and out-of-range >10 (2 rows, Richard Powers Top Ten Books lists).
- **Decision**: Compound 'a;b' → min(a, b). Blank → 10 (neutral-low). Out-of-range → clamp to 10.
- **Rationale**: Compound: the voter ranked this book at their stated position on each list; min uses the most emphatic endorsement (the higher ranking). Blank: these volumes were listed without per-volume ranking — "unranked" maps to the low end of the band rather than neutral-middle (~5) because there is no signal favoring any particular position; erring low avoids over-crediting position where none was stated. Neutral-middle was the alternative; this is a deliberate choice. Out-of-range: clamping to 10 (neutral-low) is safe and affects only 2 rows.
- **Trigger**: Phase 2b implementation.

## 2026-05-29 — Phase 2b: dominance invariant for position weight

- **Context**: The position factor ranges from 1.0 (pos 1) to (1-POSITION_WEIGHT) (pos 10), creating a risk that within-list rank could outweigh presence vs absence on a list.
- **Decision**: Assert by construction that max position swing < cheapest book IDF weight. With POSITION_WEIGHT=0.1: max swing = 0.1 × 5.145 (singleton) = 0.514 < 1.407 (Middlemarch weight). Verified numerically in --verify output.
- **Alternatives considered**: No invariant check — rely on intuition. Rejected: the invariant should be explicit and tested.
- **Rationale**: Sharing one additional book (even the most common book, Middlemarch, weight 1.407) always outweighs the maximum position advantage (0.514). Presence dominates position by construction.
- **Trigger**: Phase 2b plan review; user's explicit requirement.

## 2026-05-29 — Phase 2b: POSITION_WEIGHT as recommend() kwarg, not baked into Model

- **Context**: RARITY_ALPHA is precomputed into IDF weights at load_model() time and stored in Model. POSITION_WEIGHT could follow the same pattern (baked in) or be applied at inference time.
- **Decision**: POSITION_WEIGHT is the default value of a `position_weight` kwarg on recommend(). It is not stored in Model and does not affect any precomputed data. Setting position_weight=0 exactly recovers pre-position behavior without reloading.
- **Alternatives considered**: Bake into Model (parallel to RARITY_ALPHA) — would require reload to sweep values.
- **Rationale**: Position weighting does not affect the precomputed IDF weights (only how they are combined at query time), so there is no reason to bake it into the Model. A kwarg enables sweeping without reloading, which the user explicitly wanted.
- **Trigger**: Phase 2b plan review.

## 2026-05-29 — Phase 3: plain HTML/CSS/JS, no framework

- **Context**: PROJECT.md requires a static site. Stack choice was open.
- **Decision**: Plain HTML/CSS/JS, no framework. Three files: `site/index.html`, `site/style.css`, `site/main.js`.
- **Alternatives considered**: React, Alpine.js, Vue — all add build steps or CDN dependencies.
- **Rationale**: One page, static data, no routing, no component reuse. ~300 lines of vanilla JS is simpler, faster to load, and requires nothing to install.
- **Trigger**: Phase 3 implementation.

## 2026-05-29 — Phase 3: round affinity to 6 decimals before sort (JS/Python parity)

- **Context**: Python and JS accumulate floats in different internal orders, producing ~15th-decimal divergence that can flip near-tied books.
- **Decision**: Round affinity to 6 decimal places before comparing in the sort key, in both `phase2_model.py` and `site/main.js`. Verified: 50-result parity check (same input in Python and Node.js) passes with exact order match.
- **Alternatives considered**: Accept float divergence (could silently flip near-ties). No visible ordering change from the rounding in any existing verify case.
- **Trigger**: Phase 3 plan review; user requirement to match exactly.

## 2026-05-29 — Phase 1 cleanup: T7/T8 proposal tiers and author_corrections

- **Context**: The site surfaced a Moby-Dick duplicate (blank-author cluster separate from the
  Melville cluster). Phase 1's conservative design never merged blank-author rows with authored
  rows — correct for genuinely author-less works (Bible, Mahabharata) but wrong for books where
  the blank author is just a missing attribution.
- **Decision**: Added three new proposal tiers to `phase1_canonicalize.py` (proposal-only, never
  auto-merge): T7 (blank↔authored, identical title_key), T7b (blank↔authored, fuzzy ≥0.85), T8
  (authored↔authored title variant — prefix/containment/punctuation, same surname). Applied 24
  accepted merges; 1,229 → 1,209 canonical books.
- **Alternatives considered**: Only patching the Moby-Dick case (too narrow); auto-merging all
  T7 pairs (unsafe — the Bible/Mahabharata cases require human review to distinguish genuine
  author-less works from attribution errors).
- **Rationale**: The original Phase 1 was deliberately conservative; this cleanup uses the same
  proposal-and-review mechanism to extend coverage without breaking the audit trail.
- **Trigger**: Site review surfaced the Moby-Dick split; user requested broad hunt.

## 2026-05-29 — T8 is PROPOSAL-ONLY permanently (never auto-merge)

- **Context**: Title containment ("Tristram Shandy" ⊂ "Life and Opinions of Tristram Shandy,
  Gentleman") correctly identifies title variants, but also catches trap pairs (Molloy ⊂ Molloy
  Malone Dies and the Unnamable). Auto-merging would silently combine a volume with an omnibus.
- **Decision**: T8 generates proposals every run but never fires the union-find without an
  accepted merge_decisions.csv entry. This is enforced by code structure, not just convention.
- **Trigger**: Phase 1 cleanup plan review.

## 2026-05-29 — U.S.A. trilogy: series-level merge (volumes absent from data)

- **Context**: "The U.S.A. trilogy" and "U.s.a." (Dos Passos) are the same series-level entry
  listed two ways. The three constituent volumes (The 42nd Parallel, 1919, The Big Money) do not
  appear separately anywhere in the data.
- **Decision**: Merge as one canonical, not via series-explode. Contrast with Rabbit Angstrom:
  there, all four volumes were present separately, so the omnibus exploded to the volumes.
  Here, there is nothing to explode to, so the series-level entry is the correct canonical.
- **Rationale**: Consistent with the series-explode rule — explode only when constituent volumes
  exist in the data. When they don't, the omnibus/series entry is kept as-is.
- **Trigger**: Phase 1 cleanup; identified during T8 scan.

## 2026-05-29 — The Bible / Homer misattribution: source-error correction

- **Context**: One voter listed "The Bible" with "Homer" as author — a clear data entry error.
  The T7 merge would absorb this voter into The Bible canonical but the Counter logic picks
  "Homer" as canonical_author because it is the only non-blank surname in the merged cluster.
- **Decision**: Use a new `author_corrections` field in `overrides/registries.json` to explicitly
  clear the canonical_author for the merged Bible cluster (K:450eb07e587b → ""). This is a
  source-error correction, not a title variant or blank-author recovery — it removes an incorrect
  attribution rather than supplying a missing one.
- **Alternatives considered**: Reject the T7 merge and leave the Homer voter stranded (loses 1
  voter from The Bible count); add Homer to author_aliases (would corrupt The Iliad/Odyssey).
- **Trigger**: Phase 1 cleanup; discovered when the Homer attribution won the canonical_author
  slot after the T7 merge.

## 2026-05-29 — Phase 2: BETA popularity-normalization for Step 2 book scoring

- **Context**: The alpha (RARITY_ALPHA) sweep showed recommendations converge to the same popular
  canon regardless of input set. Root cause: Step 2 raw affinity (Σ matched-voter similarity)
  accumulates faster for books on more lists — a book on 83 lists accumulates affinity 83× faster
  than a singleton per unit of voter signal. RARITY_ALPHA operates in Step 1 and cannot fix a
  Step 2 structural bias.
- **Decision**: Add `BETA` parameter: `score(book) = affinity / n_voters^BETA`. BETA=0 is the
  exact raw-affinity baseline (no code-path branching needed; `n**0 = 1`). BETA>0 penalizes
  popular books. Both modes selectable via `recommend(model, ids, beta=X)`.
- **Known failure mode**: High BETA (≥0.5 on mixed inputs, ≥0.3 on rare inputs) causes singletons
  to flood the top of results — over-correction where one weakly-matched voter's singleton
  outranks a book loved by many strongly-matched voters. The BETA sweep output shows the
  over-correction regime clearly.
- **JS parity**: BETA>0 produces scores the static site (main.js) cannot reproduce. The site
  serves BETA=0 (raw affinity) until main.js is ported and parity re-confirmed. Recorded as
  open item in PROGRESS.md.
- **Trigger**: Alpha sweep revealed structural Step 2 bias; BETA sweep to inform final choice.

## 2026-05-29 — Phase 2: lift-with-shrinkage Step-2 scorer

- **Context**: The BETA sweep proved fixed-exponent normalization has no global threshold:
  BETA's failure mode is distinguishing a book backed by 1 matched voter from one backed by 20.
  The lift scorer replaces the exponent with a base-rate comparison and conditions on evidence.
- **Decision**: Third selectable scorer: `score(b) = 1 + (lift(b) - 1) × m_b/(m_b+K)`.
  `lift(b) = (m_b/M) / (n_b/N)` — observed rate among matched voters over expected rate across
  all voters. Shrinkage factor `m_b/(m_b+K)` pulls deviations from the no-signal baseline (1.0)
  toward zero proportionally to how little evidence backs the book.
  SHRINK_K=None (default) leaves the BETA scorer path unchanged; shrink_k=0 is pure lift
  baseline; shrink_k>0 activates shrinkage.
- **Unweighted m_b — deliberate fork**: m_b is the simple count of matched voters who have
  the book, not a similarity-weighted sum. Unweighted gives a clean base-rate interpretation
  of lift (Step 1 scores determine pool membership only, not the lift calculation). The
  weighted alternative — m_b = Σ voter_sim[v] for matched voters with the book, normalized
  over total pool similarity — would preserve more of Step 1's rarity weighting by crediting
  strongly-matched voters' preferences more. This would matter if Set 1/Set 4 surface books
  from incidental weak matches (voters who only matched on a common book). Deferred until that
  failure mode is observed empirically.
- **Sweep findings**: K=0 (pure lift) already produces 2 shared books between Set 2 and Set 3
  top-15 (vs 8 for raw affinity), but both sets flood with singletons — not the target. K=5-10
  resolves Set 2 and Set 1 well (more corroborated, canon-appropriate results) but Set 3
  persists with m_b=1 books across all K. Root cause: Set 3's matched pool (~10 voters) is so
  small that nearly every candidate book has m_b=1; shrinkage cannot differentiate among
  equally-evidence-poor books. Set 3 is limited by pool size, not by the scorer design.
- **JS parity**: lift scorer produces scores the site (main.js) cannot reproduce. Two unported
  Step-2 scorers now outstanding (BETA and lift). Site serves raw affinity until main.js updated.
- **Trigger**: BETA sweep; user identified fixed-exponent's evidence blindness as root cause.

## 2026-05-29 — Phase 2: co-occurrence scorer with two independent rarity dials

- **Context**: Raw affinity, BETA, and lift all conflated two separate rarity effects (signal
  from rare inputs, and distinctiveness of rare candidates) into a single mechanism. None had a
  usable global parameter because the effects interact. This scorer separates them explicitly.
- **Decision**: `score(c) = (Σᵢ co(i,c) × raw_idf(i)^α) × raw_idf(c)^γ`. Two independent
  tunable parameters: COOC_INPUT_EXP (α, input-side) and COOC_OUTPUT_EXP (γ, output-side),
  each with a clear off value (0.0 = no effect) and a None sentinel for scorer deactivation.
  raw_idf decoupled from RARITY_ALPHA — clean separation of concerns.
- **Singleton-flood resistance via base score**: a singleton (n=1) has base ≤ |input_set|
  (at most one co-occurrence per input book). A book with b co-occurrences only loses to a
  singleton when `(idf_singleton/idf_book)^γ > b`, requiring implausibly large γ for any
  book with b≥3. Resistance is structural, not a separate shrinkage parameter.
- **Unweighted co-occurrence base — intentional, different reason from lift scorer**: the lift
  scorer's unweighted m_b was a noted deficiency (discards Step-1 per-voter weighting). Here,
  decoupling from voter_sim is correct by design: the scorer asks "how often do readers of
  input book i also read candidate c?" — a book-level question. The alpha parameter recovers
  the input-level rarity signal at the right abstraction. Per-voter weighting would conflate
  the two levels and recreate the opacity of the prior scorers.
- **JS parity**: Previously THREE unported Step-2 scorers (BETA, lift, co-occurrence). The
  co-occurrence scorer is now ported to main.js and verified. BETA and lift remain Python-only
  by design — they were evaluation options, not shipped features.
- **Trigger**: Lift-scorer sweep showed Set 3 is pool-size-limited, not scorer-limited;
  user requested a legible framework separating the two rarity effects.

## 2026-05-29 — Co-occurrence scorer chosen as production default (α=γ=1.0)

- **Context**: Five scorer sweeps converged on co-occurrence as the recommended model.
  γ=1.0 from the gamma sweep (3 shared books between Set 2 and Set 3 top-15 — in the
  target window). α sweep showed stable results across 0–2 for most sets; α=1.0 chosen
  as the natural IDF unit weighting.
- **Decision**: COOC_INPUT_EXP=1.0, COOC_OUTPUT_EXP=1.0 set as Python constants; JSON
  re-exported as source of truth. main.js now implements the co-occurrence scorer, closing
  the JS parity open item for this scorer. BETA and lift remain Python-only by design.
- **Cid tiebreak added**: equal-score equal-idf ties (all n=1 singletons, identical IDF)
  resolve by cid alphabetically in both Python and JS, ensuring deterministic ordering
  regardless of dict/object iteration order. Parity gate confirmed: 9 input-set × parameter
  combinations, 15 books each — all match exactly.
- **IDF sources**: JS rawIdf(n, N) = Math.log((N+1)/(n+1)) matches Python _raw_idf exactly.
  Tiebreak uses model.idf (stored) in JS and book_info["weight"] in Python — equal at
  RARITY_ALPHA=1.0. See prior DECISIONS.md entry on RARITY_ALPHA dependency.
- **co= display count**: distinct voter count (per voter, outside per-input loop), distinct
  from the weighted edge sum used for scoring. Verified: 20 co= values match between Python
  and JS in the parity gate.
- **JS parity open item status**: co-occurrence scorer closed. BETA and lift unported by
  design (evaluation tools, not shipping). No remaining unported scorer open items.
- **Trigger**: Five scorer sweeps; user approved co-occurrence α=γ=1.0 for production.

## 2026-05-29 — Evaluation harness design choices

- **Voter exclusion (LOO correctness)**: When evaluating voter v, v is removed from the
  model's voter_books. Without exclusion, v's own co-occurrences trivially rank their held-out
  books highly (data leakage). n_voters and IDF weights are frozen at full-dataset values
  so the rarity signal is not biased by excluding one voter.

- **Unrecommendable definition**: a held-out book h is unrecommendable iff no voter w≠v has
  h AND shares any input book with v. Singletons (n_voters=1) are always unrecommendable
  after v is excluded. Some non-singletons are also unrecommendable (their co-voters share
  no input books). In the baseline: 770 singleton pairs + 448 non-singleton pairs = 1218/3525
  (34.6%) are unrecommendable. Recall metrics computed on recommendable subset only;
  unrecommendable rate reported as a separate measurement ("the ceiling").

- **recall@10 as leading metric**: matches the 10-item result list shown to users; the
  natural unit for "did the model surface this book?" in the deployed context.

- **Rarity-weighted recall@10**: weights each trial by raw_idf(n_h), so recovering a
  distinctive book counts more than recovering canon. This is the anti-popularity-bias
  metric — a model that only surfaces Middlemarch variants will score low despite high
  unweighted recall. Computed on recommendable books only; unrecommendable singletons
  (already excluded) are noted as "the impossible long tail" in the panel.

- **Differentiation diagnostic uses full model (not LOO)**: measures production
  recommendation divergence between different inputs. LOO would be inconsistent with the
  deployment context (users are not excluded from the full dataset). This is the only
  place in the harness that does not use a LOO model; stated explicitly in the output.

- **K-curve composition reporting**: recall dips from K to K+1 are NOT automatically
  flagged as harness errors. Target-set composition changes with K (fewer held-out books,
  shifted rarity mix), so a dip can be real rather than noise.

- **Trigger**: first quantitative evaluation of the scorer; replaces eyeballing sweep tables.

## 2026-05-29 — PPMI+SVD embedding recommender design choices

- **Why embeddings over co-occurrence**: the co-occurrence harness showed 34.6% of held-out
  books were structurally unrecommendable (no co-occurrence path to any input book after voter
  exclusion). Embeddings reduce this to 21.9% (only true singletons remain zero-vector) because
  a non-singleton book retains a vector from its other voters' listmates even after the test
  voter is excluded. Books with no direct co-occurrence path to inputs become reachable by latent
  space proximity. Confirmed by concrete validation: Charlotte's Web (n=2) unrecommendable under
  co-occurrence for Adriana Trigiani → rank=46 in embedding harness.

- **PPMI (not raw counts or TF-IDF)**: (1) positive clamp removes high-variance negative PMI,
  which is unreliable at this sparsity (88.6% of co-occurrence pairs appear exactly once);
  (2) PMI naturally controls for popularity — a popular-×-popular pair has high raw count but
  low PMI because P(a)·P(b) is also large; standard for small/sparse corpora.
  No add-k smoothing: at this density, smoothing uniformly lowers all PMI values without
  changing relative ordering — deliberate omission.

- **Truncated SVD via ARPACK (scipy.sparse.linalg.svds)**: O(nnz×d×iter) vs O(n³) for full SVD.
  Book vectors = U·diag(s) (left singular vectors × singular values), not just U — the singular
  values encode variance magnitude and are needed for correct geometric distances.

- **L2-normalisation**: makes cosine similarity = dot product; standard for embedding retrieval.

- **No recommendable-subset filter in embedding harness**: zero-vector books (singletons of
  the test voter) counted as misses in the denominator. More conservative than the old filter;
  the structural improvement is visible as 34.6% → 21.9% zero-vector rate. The two harnesses
  use different denominators and are not directly numerically comparable — this is documented.

- **Overfitting guard on recoverable subset (n_voters≥2)**: comparing training vs LOO recall
  must exclude zero-vector books from BOTH sides. Without this filter, the gap is confounded
  by the structural singleton penalty (LOO denominator includes singletons, full-model does not).
  Baseline gap = +30pp at d=30, which motivates a dimensionality sweep.

- **Dependency on numpy/scipy**: appropriate for embedding work; not a stdlib-only regime

## 2026-05-29 — PPMI-direct scorer design and baseline results

- **Motivation**: SVD embeddings hit a data-sparsity ceiling (best RW-recall@10=6.7% at d=50,
  co-occurrence=12.6%). PPMI itself is sound; the factorization was the problem. Use PPMI
  associations directly: score(c) = Σᵢ PPMI_k(i,c) × raw_idf(nᵢ)^α.

- **Shifted PPMI parameter k**: PPMI_k(a,b) = max(0, PMI(a,b) − k). k=0 is standard PPMI;
  k>0 suppresses weak/accidental associations. At extreme sparsity (88.6% of pairs co-occur
  exactly once), k=0 creates a singleton-flooding problem: rare books that happen to share a
  list with an input book get high PMI because P(book) is tiny — Middlemarch's top-5 PPMI
  neighbors at k=0 are all n=1 singletons with PPMI≈2.25. k is the sparse-data control.

- **Baseline k=0/α=0 result**: PPMI-direct RW-recall@10=4.3% vs co-occurrence=12.6% (−8.3pp).
  Zero-row rate=21.8% (matches embedding harness ✓ — same structural cause: singletons of
  test voter). n=21+ recall collapses to 1.9% (vs 63.2% for co-occurrence) because PPMI
  suppresses popular-book associations so aggressively. This is the floor of the approach —
  k>0 is expected to improve things by suppressing accidental single-count associations.

- **Random-score validation**: uses real per-fold PPMI matrix but assigns random candidate
  scores, testing "does PPMI ranking beat random ranking?" Not index-scrambling (which would
  relabel the same structure and pass vacuously).

## 2026-05-29 — PPMI-direct shipped to live site (k=0, α=0)

- **Decision**: Ship PPMI-direct (k=0, α=0) as the production scorer. Co-occurrence scorer
  retained in code, swappable via `?scorer=cooc` URL param for silent A/B. Rarity-tuning
  dropdown (α/γ controls) removed — PPMI-direct has no user-facing parameters.

- **Rationale**: None of the scorers tested beat co-occurrence's aggregate recall on this
  sparse corpus. The full modeling arc was exercised: co-occurrence → BETA normalization →
  lift-with-shrinkage → PPMI+SVD embeddings → PPMI-direct. PPMI-direct is chosen because:
  (1) it is the most differentiating at the data's sparsity ceiling — best on rare-book bins
  (n=2–5 and n=6–20) where the interesting taste signal lives; (2) it is the conceptually
  principled version of co-occurrence (popularity-corrected associations); (3) it has no
  tuning knobs that need sweeping before shipping. Shipping for live qualitative evaluation.

- **Client-side PPMI**: computed at startup from voter_books already in model_data.json —
  no new JSON data. C_total verified exact match with Python (both = 33294). Parity gate:
  rank-parity and score-parity exact for 3 input sets vs Python rank_ppmi_direct. The one
  "score mismatch" flag was a tied-score artifact in the parity helper (not the scorer);
  the actual ranked lists matched identically.

- **Y-voters display with PPMI scoring**: `computeMatchedVoterCounts` stays unchanged. With
  PPMI, a high-ranked result may have a low Y (PPMI surfaces books for association strength,
  not corroboration count). This is correct behavior — Y is now informational, not the
  rationale for the ranking. Verified: no Y=0 in results (a book with no matched-pool voters
  can't have a PPMI score from those voters, so it won't appear).

- **k=0 note**: ships the floor of the PPMI approach. k=0 includes all single-count
  accidental associations; k>0 might improve things but the sweep showed no clear win
  (n=21+ recall collapses monotonically with k). Shipping k=0 for feel-based evaluation.

## 2026-05-29 — Blend slider: rank fusion of co-occurrence ↔ PPMI

- **Why rank fusion, not score blending**: the two scorers produce scores on incompatible
  scales (co-occurrence scores are weighted edge sums; PPMI scores are PMI values). Blending
  scores would require scale normalization, which introduces arbitrary choices. Blending ranks
  is parameter-free and preserves each scorer's full ordering.

- **Formula**: `blended_rank(c) = (1-t) × rank_cooc(c) + t × rank_ppmi(c)`
  t=0 → pure co-occurrence; t=1 → pure PPMI. Default t=0.5.

- **Shared sentinel `N_sentinel = max(|ppmi_pool|, |cooc_pool|) + 1`**: used for BOTH sides
  when a book is absent from one scorer. A per-side max would be asymmetric — if co-occ
  has 469 candidates and PPMI has 438, using different sentinels would put a thumb on the
  scale for books exclusive to one scorer. Shared sentinel = equal penalty for absence,
  regardless of which scorer dropped the book.

- **Tie breaking**: equal blended rank → sort by cid alphabetically. Deterministic; no
  hidden preference.

- **Full candidate pools required**: both scorers called with `top_n=Infinity` to get
  complete ranked lists. A lingering top-50 cap would break the endpoint guarantees:
  t=0 would not reproduce the pure co-occurrence ranking for books ranked 51–N.
  Verified: pools of 438 (PPMI) and 469 (co-occ) for Middlemarch+Anna Karenina.

- **Score-display vs recompute separation**: `liveRecompute()` runs both scorers; slider
  drag calls `fuseAndRender()` only (re-fuses precomputed ranks, no re-scoring).
  Drag latency: 21 moves in 32ms.

- **?scorer= URL param retired**: slider supersedes it. Both scorers always run.

- **Endpoint guarantees verified**: t=0 top-15 = standalone coocScorer top-15 (identical);
  t=1 top-15 = standalone ppmiDirectScorer top-15 (identical). Any fusion bug that reorders
  at the extremes would have failed this check.

## 2026-05-30 — Per-recommendation evidence expansion panel

- **Evidence-not-rank framing**: the expansion headline explains who backs the recommendation
  and how distinctive it is. It never claims to explain the rank, which comes from a blended
  scorer (co-occ + PPMI) we deliberately do not narrate. All copy uses "readers who love it
  also share your taste" framing, not "ranked first because of…".

- **Bucket design**: matched voters (those who share ≥1 input book AND have the result book)
  are grouped by overlap count (how many of the user's inputs they share). This directly
  represents signal strength — a voter sharing 3 of your books is a stronger taste signal
  than one sharing 1. Label states the overlap; explicit number beside the bar states the
  voter count; bar encodes relative tier size. Avoiding "N readers share M books" in a
  single sentence removes the ambiguity of two numbers competing.

- **Distinctiveness badge thresholds** (based on 342 total voters):
  n=1 → "Deep cut"; n=2–5 → "Distinctive pick"; n=6–20 → "Popular pick"; n=21+ → "Widely loved".
  The n=1 "but" headline construction signals that rarity is notable; the n=21+ "and"
  construction signals corroboration; mid-range is neutral.

- **Name cap of 5 per tier**: balances personalisation (enough names to feel real) with
  avoiding overwhelming long lists.

- **"Most often listed alongside your X."** — plain co-occurrence fact, never "most connected
  to your love of X" (which implied rank explanation). Omitted if inputs are tied or single.

## 2026-05-30 — Deterministic evidence view (replaced expansion panel prose)

- **Replaced**: badge (Deep cut / Distinctive pick etc.), prose headline, tier bars with
  voter names, and "most often listed alongside" connection note — all removed entirely.

- **Two-score framing**: shows `state.baseCounts[cid]` (raw co-occurrence sum =
  Σᵢ count(voter_lists with both input_i and rec)) and `state.ppmiScores[cid]` (PPMI sum
  = Σᵢ PPMI(input_i, rec)). Both come directly from the live scorers; no re-computation.
  Labelled as separate lenses with scale caveats — not comparable magnitudes.

- **Voter strip**: every qualifying voter (has rec AND shares ≥1 input) gets a card.
  No cap. Each card shows the voter's full list in reading order.

- **Card influence order**: shared-input-count descending → raw_idf-sum of shared inputs
  descending. Slider-independent (doesn't change when t moves).

- **Within-card book order**: position ascending → n_voters ascending (rarer first) →
  title alphabetical. Fully deterministic. Tied integer positions occur for cross-source
  voters (compound positions like "1;5" and "1;6" both min-resolve to 1 in the JSON).
  The n_voters → title tiebreak handles these correctly.

- **Position format**: confirmed via data inspection — `pos` in model_data.json is always
  a plain integer (0 non-integer entries across all 3525 voter-book pairs). Compound
  strings were converted by `_parse_position()` during Python export.

- **Highlight colors** (existing vars only): `.is-input` = accent-soft background +
  accent text (light blue); `.is-rec` = accent background + white text (dark blue).
  In-place — books are not reordered to float highlights.

## 2026-05-30 — UX cosmetic batch (7 surface changes)

- **Dark mode palette**: dark gray bg (#1e1e1e), surface (#2a2a2a), near-white text
  (#e8e6e3), bright blue accent (#5b8ad9) readable on dark, dark navy hover tint
  (#1e3258). accent-soft flips from light tint to dark navy — all three usages audited
  (dropdown hover, result-row hover, .is-input highlight) and confirmed legible.
  Voter-card highlights on dark: .is-input = dark navy bg + bright blue text;
  .is-rec = bright blue bg + white text — clearly distinguishable from each other.

- **Dropdown windowing approach**: WINDOW_INITIAL=100 items mounted on open,
  WINDOW_PAGE=50 appended on scroll, lazy-loaded via scroll event listener. Keyboard
  arrow-past-boundary grows the window before advancing selection.

- **Autocomplete ordering**: always uses sortedBooks (n_voters desc, cid asc tiebreak)
  as the base. On keystroke, filtering stays in this order — no text-match reordering,
  no jarring reshuffle. scrollTop reset to 0 on each keystroke filter.

- **Slider default**: t=0.25 (shifted toward co-occurrence / popular end).

- **Uniform card height**: CSS `align-items: stretch` on the flex strip container —
  all cards grow to the height of the tallest card naturally. No hardcoded pixel constant.
  Avoids the failure mode where a wrong constant + `overflow: hidden` clips the last
  (possibly highlighted) book of the tallest card.

- **Accordion (one open)**: simpler than multi-open; re-clicking collapses.
  `collapseAll()` called at the start of every `fuseAndRender()` and `liveRecompute()` so
  evidence panels never show stale data after slider drag or book edits.

- **Lazy computation**: computed on click only (~3,500 iterations per expansion; negligible).
  No upfront cost for all 50 result rows.
## 2026-05-30 — UX follow-up batch (6 surface changes)

- **Dropdown focus trigger**: added `click` listener on search input (alongside `focus`).
  Root cause: after `selectBook()` calls `elSearchInput.focus()`, if the input was
  already focused the browser treats it as a no-op — no `focus` event fires. The input
  is stale-focused, so clicking it fires only `click` but `onSearchFocus` was only
  wired to `focus`. Adding the `click` listener means clicking always opens the dropdown.
  Guard `if (!elDropdown.hidden) return` prevents scroll-position resets mid-browse.
  Also removed the `elSearchInput.focus()` call from `setupUI()` so the dropdown no
  longer opens on page load before any user interaction.

- **Voter strip width — CSS breakout over JS measurement**: strip uses
  `width: min(calc(100vw - 360px), calc(8 * 170px + 1rem))`. Alternatives: (a) JS
  `getBoundingClientRect()` + inline style — accurate but flaky on first render when
  layout hasn't settled; requires `setTimeout(0)` or `requestAnimationFrame` and a
  resize observer. (b) Pure CSS vw approximation — approximate (360px is estimated left
  offset, not measured) but always in sync with viewport resize, no JS timing needed.
  Chosen: CSS. Minor cosmetic gap (strip narrower than possible at small viewports with
  a wide input panel) is acceptable; timing fragility is not.

- **Chevron vertical centering**: moved chevron span from inside `.result-title-row`
  to a direct `li` grid child in column 3, `grid-row: 1 / span 3`. `align-self: center`
  centers it across all three content rows (title, author, count). Alternative: absolute
  positioning inside the li — rejected because `li` is a grid container and absolute
  children escape grid flow unpredictably.

- **Slider order post-run**: changed from `order: 2` (above book-entries, below h1) to
  `order: -1` (above everything including h1). The slider is the most-interactive
  control post-run; floating it to the top of the sticky panel improves reach on mobile
  and reduces scrolling.

## 2026-05-30 — UX + data batch (5 items)

- **Year backfill — lifespan vs publication ranges**: auto-resolve range years only
  when span ≤ 25 years (clear publication windows: LOTR 1954-56, Proust 1913-27,
  Decameron 1351-53). Ranges > 25 years flagged as likely author lifespans (O'Connor
  1925-64, Kafka 1883-1924, Shakespeare 1564-1616, etc.) — the first year of these
  ranges is a birth year, not a publication date, so resolving automatically would be
  confidently wrong. Ancient works with no year at all (Homer, Virgil, Aeschylus, etc.)
  auto-labeled "pre-Renaissance" via keyword list. OpenLibrary API used for OL-prefixed
  books if reachable; otherwise gap CSV output for domain-allowlist or manual resolution.

- **/10 scores — input-aware denominators**: denomCooc = Σᵢ n_voters(input_i) (the
  maximum co-occurrence achievable if all of each input book's voters also have the rec);
  denomPpmi = Σᵢ max(ppmiMap[input_i].values()) (max PPMI sum achievable for this input
  set). Both denominators are stable per (rec, inputs) pair — they depend only on the
  inputs, not on what's in the result set. Verified spreads: Confidence-Man (1 voter)
  shows 10.0 → 7.7 → 7.3 → 5.5 → 4.4 PPMI /10 across top results; Middlemarch (83
  voters) shows 2.4/10 co-occ for Anna Karenina (honest: 24% of 83 voters have it)
  with PPMI spread distinguishing Portrait of a Lady (7.0/10) from Ulysses (2.8/10).
  Rejected fixed global denominators because they collapse niche-taste scores uniformly.

- **Results column width**: increased #main.post-run max-width from 960px to
  min(calc(100vw - 2.5rem), 1200px); removed CSS breakout (width: min(...)) from
  .detail-strip-wrapper. The strip is now self-contained; expanded cards are the same
  width as collapsed rows, with horizontal scroll within the wider column.

- **Summary line** now reads "on X lists from voters who share at least one input —
  Y of them share multiple" (Y clause dropped for single-input). This required extending
  computeMatchedVoterCounts to return both X and Y, and storing multiMatchCounts in
  state alongside matchedCounts.

## 2026-05-30 — UX batch 2 (6 items)

- **"Independent People" data fix**: corrected canonical_title in canonical_books.csv
  (OL:OL757983W: "Independant" → "Independent"). combined_voters.csv and
  row_to_canonical.csv retain the original spelling — they're Phase 1 source/output
  files. Phase 2 export reads from canonical_books.csv only, so the re-exported
  model_data.json is correct everywhere.

- **Year field added to model_data.json export**: phase2_model.py now reads
  canonical_year from canonical_books.csv (694 books) and merges with
  year_backfill.csv (37 auto-resolved entries from the prior batch). 731/1209
  books have a year in the current export; the remainder show year="" (not displayed).

- **/10 score denominators — sqrt-compressed co-occ + linear PPMI**: replacing the
  input-aware (n_voters sum) denominator that made Middlemarch's #1 recommendation
  score 2.4/10. Co-occ uses min(10, sqrt(raw) / 5.5 × 10) — sqrt compression
  spreads the popular cluster that would otherwise all pin at 10/10 (27/24/21 →
  9.4/8.9/8.3 rather than all 10). D_COOC_SQRT=5.5 calibrated so the highest
  observed n=2 co-occ (raw=27, Middlemarch+JE best) → ≈9.4/10; only raw ≥30
  earns 10/10. PPMI is left linear (min(10, ppmi / (3.8 × n) × 10)) because it
  already differentiates well — compressing it would flatten the 0.8–7.5 signal
  seen for popular inputs. D_PPMI=3.8/input ≈ p99 of per-input PPMI distribution.
  Verified across three test cases: popular pair shows gradient 9.4/8.9/8.7/8.3;
  rare pair shows PPMI 3.2–10.0 with honest low co-occ; incoherent pair (zero
  shared voters) tops at 3.1/10 co-occ and 9.3/10 PPMI — both below 10. The
  transform is display-only: renderDetailPanel() reads raw scores from state but
  never writes back to state.baseCounts/ppmiScores or any ranking input.
  Denominators calibrated to the 342-voter corpus: must be recomputed if the
  dataset changes significantly.

## 2026-05-30 — Light UX + data batch (feature/light-ux-batch)

- **Description field sourced from descriptions.csv-or-placeholder**: `data/processed/descriptions.csv`
  (canonical_id, description) is read at export time if it exists; missing entries
  get a lightly-templated placeholder ("{title}, by {author}. Description coming soon.").
  Zero UI/code change on re-export: dropping in a real CSV and re-running
  `python3 phase2_model.py --export` populates descriptions automatically.

- **year_overrides.csv mechanism**: highest-priority year source at export time,
  `data/processed/year_overrides.csv` (canonical_id, year). Overrides year_backfill.csv
  and canonical_books.csv canonical_year. Created as header-only placeholder; the
  30 lifespan-range books (author-birth ranges mistaken for publication years) and
  448 OL-blocked blank-year books will be filled in a separate data session
  alongside real descriptions. Priority: overrides > year_backfill > canonical_books.

- **Byline left-grouped**: removed `flex: 1` from `.result-title`. Title now has
  `flex: 0 1 auto` (default); byline follows immediately at natural width. Title
  truncates before byline is squeezed (flex-shrink: 0 on byline preserved).

## 2026-05-30 — Rename + About page (feature/about-page)

- **Rename display-only scope**: "Kindred Lists" → "On the Same Page" changes only
  the human-readable display string in `site/index.html` (`<title>`, `.site-name`) and
  the `PROJECT.md` heading. No file renames, CSS class renames, JS variable names,
  data keys, git artifacts, or historical doc entries changed.

- **About page nav: view toggle (not hash routing)**: `#main` and `#about` coexist in
  the DOM; navigation only toggles the `hidden` attribute. Chosen over hash routing
  because this is a single-page app and the URL-state machinery adds complexity with
  no benefit. State preservation is automatic — the main app's DOM and JS state are
  never touched when switching views.

- **Nav wired before model load**: `initNav()` runs before `init()` (the async model
  fetch), so the About page is reachable even during a slow or failed load. About is
  static content that requires no model data. `setupUI()` checks `#about.hidden` before
  revealing `#main` to respect any mid-load navigation.

## 2026-05-30 — CSV as single source of truth for year + description

- **Curated CSV as single source of truth**: `data/processed/manually_filled_descriptions_and_years.csv`
  replaces all prior year pipes (canonical_books canonical_year, year_backfill.csv,
  year_overrides.csv) and the descriptions.csv lookup. The multi-source priority chain
  is retired; editing this CSV + re-running `python3 phase2_model.py --export` is now
  the complete workflow for both fields.

- **Year range resolution — separately-titled vs. single-titled rule**: for plain
  YYYY–YYYY dash-ranges, the deciding question is: separately-titled volumes (trilogies,
  series, any set of distinct volumes each with its own title) → keep full range.
  Single-titled work issued in installments, serialized parts, or cantos under one title
  → replace with last year. Resolution baked into CSV once by `resolve_years.py` (29 rows
  updated); thereafter years display verbatim with no runtime classification logic.
  Examples: Middlemarch 1871–1872 → 1872; In Search of Lost Time 1913–1927 → kept;
  Lord of the Rings 1954–1955 → kept (3 separately-titled volumes).

- **Strip buffer root cause**: `padding` on the CHILD of `overflow-x: auto` is inside
  the scrollable content area and unreliable for outer breathing room (right-side padding
  is browser-clipped; left-side technically present but may not appear as outer gap).
  Fixed by moving horizontal padding to `.detail-strip-wrapper` (the overflow container
  itself), where it is always visible outside the scroll viewport.

## 2026-05-30 — Slider polish + strip buffer fix (feature/slider-strip-polish)

- **Strip buffer true root cause**: Chrome/WebKit counts `padding-left` but NOT
  `padding-right` in `scrollWidth` when flex content overflows. Attempt 1 (padding
  on `.detail-strip` child) and attempt 2 (padding on `.detail-strip-wrapper`
  container) both failed at scroll-end. Fixed with `.detail-strip::after { content:'';
  flex: 0 0 0.5rem; }` — a real flex item IS counted in scrollWidth, guaranteeing
  0.5rem visible space after the last card at any scroll position. Wrapper's
  `padding-left` kept for left-side buffer (still works); right padding removed
  since it doesn't help.

- **Slider default 0.20**: changed from 0.25. `BLEND_DEFAULT` constant used in
  both the HTML default value and the reset button handler.

- **Reset button replaces persistent value display**: `#blend-value` span removed;
  `↺` (U+21BA) reset button restores `BLEND_DEFAULT`. The value is now only shown
  as a delayed hover tooltip (2s debounce) or during drag.

- **Tooltip rough thumb-tracking**: `left: ${value * 100}%` gives approximate thumb
  position without browser-specific thumb-offset corrections. Programmatic `.value`
  assignment (reset button) doesn't fire the `input` event, so `updateTooltipContent()`
  is called explicitly in the reset handler to avoid stale tooltip display.

## 2026-05-30 — Strip buffer final fix + reset button (feature/strip-reset-fix)

- **Strip buffer final root cause**: The missing gap was at the container level.
  `.detail-strip-wrapper` filled `.result-detail`'s content box with no horizontal
  margin, so wrapper edges were flush with content-box edges (0px inset). Fixed by
  `margin: 0 0.5rem` on the wrapper. The Chrome overflow-padding asymmetry (previous
  attempts) is a separate gap — between scroll content and the scroll viewport edge at
  scroll-end; the `::after` spacer handles that correctly. These were two distinct gaps;
  both are now addressed. Measurement: wrapper left offset from content-box = 8px (0.5rem).

## 2026-05-30 — Strip spacer + slider alignment final fix (feature/strip-slider-final)

Before-fix measurements (Chromium 1440×900, Middlemarch+Jane Eyre, result expanded):
- External strip gap (content-box → wrapper): 8px each side ✓ (margin from prior batch working)
- Internal right buffer at max scroll: 18.3px ✗ (flex gap 9.6px + spacer 8px stacked)
- Reset/slider vertical delta: 2.8px ✗ (range input not centered in its wrapper)

- **Strip ::after spacer removed**: the spacer was redundant — the wrapper's margin-right
  already provides 8px external right buffer. The spacer created an additional 17.6px
  internal buffer (0.6rem flex gap + 0.5rem spacer stacked), totaling 26px from last
  card to card inner border vs 21px on the left. Removing it equalizes both sides at
  ~21px (8px external only). Measured post-fix: internal buffer 0.3px, external 8px
  each side (symmetric).

- **Slider wrapper made flex**: `.blend-slider-wrapper { display: flex; align-items:
  center }` was added. The range input wasn't auto-centered within its `position:
  relative` block wrapper; making it a flex container centers the input explicitly.
  Post-fix delta = 0px. Tooltip still sits above the slider thumb (absolute positioning
  is out of flow; wrapper becoming flex doesn't affect it — confirmed tooltip.bottom <
  slider.top after fix).

## 2026-05-30 — Expanded-card right gutter + reset button size (feature/detail-right-gutter)

Before: `.result-detail { grid-column: 2 / -1 }` was flush right (0px gutter within `<li>`).
The left indent (41.6px = counter col 32px + grid gap 9.6px) is deliberate — it aligns the
content box under the title, clearing the number column. The right side has no alignment job;
it only needs a containment buffer.

Fixed with `margin-right: 0.75rem` (12px, matching the box's own horizontal padding) on
`.result-detail`. Intentionally asymmetric: left=41.6px (alignment), right=12px (containment).
Strip-wrapper internal gutters confirmed unaffected: 8px/8px symmetric.

Also bumped `.blend-reset` font-size from 1.15rem → 1.3rem (20.8px computed).

Measured post-fix: detailWithinLi left=41.6px, right=12px; wrapperWithinDetail 8px/8px; reset=20.8px.
