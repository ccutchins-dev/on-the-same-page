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