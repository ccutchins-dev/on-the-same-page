# PROGRESS.md

Append-only log of completed work. Appends a new entry after each task 
that successfully merges to `main`, and also appends a handoff note 
when escalating to the human.

## Schema

Each entry is a heading-level entry in the Entries section below:

```
## YYYY-MM-DD — T-NNN — short summary

- **Commit**: <merge commit SHA on main>
- **Branch**: feature/T-NNN-short-desc
- **Tag** (if applicable): vX.Y-milestone-name
- **Notes**: brief context, results, anything notable
```

For escalation handoffs (not task completions), use this format instead:

```
## YYYY-MM-DD — ESCALATION

- **Last task attempted**: T-NNN
- **Last commit**: <SHA on main, or "none">
- **Branch state**: which branches exist, in what state
- **What was tried**: brief summary of recent activity
- **Why escalating**: which stop condition fired
- **Input needed from human**: the specific decision or info required
```

Append in chronological order. Never edit prior entries.

## Entries

## 2026-05-30 — Per-recommendation evidence panel (feature/result-detail-panel)

- **Commit**: 017fdd6 on feature/result-detail-panel (to be merged to main)
- **Usage**: click any result row to expand; click again to collapse. Slider drag or book
  edits collapse any open panel automatically.
- **Content**: distinctiveness badge, evidence headline (never narrates rank), bucket
  breakdown (matched voters by input-overlap tier with bar + count + names), "Most often
  listed alongside your X" co-occurrence note.
- **Verified**: badge/headline, accordion, collapse-on-re-rank, tier label wording, "listed
  alongside" wording — all confirmed via Playwright.

## 2026-05-29 — Blend slider added (feature/blend-slider)

- **Commit**: dd73c1b on feature/blend-slider (to be merged to main)
- **Usage**: `python3 -m http.server 8000` → `http://localhost:8000/site/`; `?debug=1` for diagnostics
- **Slider**: "Popular ↔ Distinctive", t=0–1, default 0.5. t=0=pure co-occ, t=1=pure PPMI.
  Drag re-fuses precomputed ranks (32ms/21 moves); book add/remove re-runs both scorers.
- **Verified**: t=0 top-15 identical to standalone co-occurrence; t=1 identical to standalone PPMI.
  Full candidate pools: 438 (PPMI) and 469 (co-occ) for 2-book input — no cap lingering.

## 2026-05-29 — PPMI-direct shipped to site (feature/phase3-ppmi-live)

- **Commit**: 7b8e7d8 on feature/phase3-ppmi-live (to be merged to main)
- **How to run**: `python3 -m http.server 8000` → `http://localhost:8000/site/`
- **Scorer swap**: `?scorer=cooc` activates co-occurrence for A/B; `?debug=1` shows co=/n= diagnostics
- **Changes**: PPMI computed client-side from voter_books (no JSON growth); rarity dropdown removed;
  parity verified (rank-parity ✓ score-parity ✓ for SET1/SET2/SET3 vs Python rank_ppmi_direct)
- **Modeling arc complete**: co-occ → BETA → lift → embeddings → PPMI-direct (all tested; none beat
  co-occ aggregate recall; PPMI-direct best on rare bins; shipped for live qualitative eval)

## 2026-05-29 — PPMI-direct scorer (feature/ppmi-direct-scorer)

- **Commit**: fe444f1 on feature/ppmi-direct-scorer (to be merged to main)
- **Usage**: `python3 evaluate.py --ppmi [--shift-k K] [--input-rarity α]`
- **Baseline k=0/α=0**: PPMI-direct RW-recall@10=4.3% vs co-occurrence (unoptimized)=12.6%.
  Zero-row rate=21.8% (matches embedding harness ✓). n=21+ recall collapses to 1.9% — PPMI
  over-suppresses popular-book associations at k=0. k>0 sweep is the next tuning step.
- **Key finding**: k=0 boosts singletons (Middlemarch top-5 are all n=1 books with PPMI≈2.25
  from single-count accidental co-occurrences). This is the floor, not the ceiling.

## 2026-05-29 — PPMI+SVD embedding recommender (feature/embedding-recommender)

- **Commit**: d1bbf1b on feature/embedding-recommender (to be merged to main)
- **Deps**: `pip3 install numpy scipy` (numpy 2.0.2, scipy 1.13.1)
- **Usage**: `python3 evaluate.py --embed --d 30` (add `--input-rarity` to tune query weighting)
- **Baseline d=30, input_rarity=0**: LOO recall@10=7.4%, RW-recall@10=5.2%, MRR=0.0398.
  Zero-vector=21.9% (vs co-occurrence unrecommendable 34.6% → structural improvement confirmed).
  Overfitting gap=+30pp (training 37.0% vs LOO 7.0% on recoverable subset) — motivates sweep.
- **Validation**: all 4 checks pass. Charlotte's Web (n=2, Adriana Trigiani) was unrecommendable
  under co-occurrence; now reachable at rank=46 in the embedding harness.

## 2026-05-29 — Evaluation harness (evaluate.py)

- **Commit**: ee35ceb on feature/evaluate-harness (to be merged to main)
- **Usage**: `python3 evaluate.py` (α=γ=1.0 by default); `--alpha / --gamma` to sweep;
  `--validate-only` for just the sanity checks
- **Baseline (α=1.0, γ=1.0)**: LOO recall@10=31.9% (38×random), RW-recall@10=23.2%,
  MRR=0.162; curve K=1→8 rises from 26.9%→32.1%. Unrecommendable=34.6% (1218/3525),
  includes all 770 singleton pairs + 448 non-singletons with no co-voter overlap.
- **Differentiation diagnostic**: 12.5% mean top-10 overlap between random voter pairs.

## 2026-05-29 — Phase 3 update: co-occurrence scorer live, rarity controls, live recompute

- **Commit**: f5b7136 (to be merged to main from feature/phase3-cooc-live)
- **Branch**: feature/phase3-cooc-live
- **How to run**: `python3 -m http.server 8000` from repo root → `http://localhost:8000/site/`
- **Notes**: main.js now implements the co-occurrence scorer (α=γ=1.0). Parity verified: 9
  input-set × parameter settings, 15 books each + 20 co= counts. Rarity tuning: collapsed
  `<details>` with two number inputs; expanding shows co= and n= diagnostic columns. Live
  recompute on book add/remove and on α/γ change; layout shift on first book selected.
  Run button and stale-graying removed. ⚠ JS parity open item CLOSED for co-occurrence scorer;
  BETA and lift remain Python-only by design — no remaining unported scorer open items.

## 2026-05-29 — Phase 2: co-occurrence scorer added (feature/phase2-cooc-scorer)

- **Commit**: bbf60b6 on feature/phase2-cooc-scorer (to be merged to main)
- **Notes**: Fourth Step-2 scorer option: `score(c) = (Σᵢ co(i,c) × raw_idf(i)^α) × raw_idf(c)^γ`.
  Two dials: COOC_INPUT_EXP (α, input-side) and COOC_OUTPUT_EXP (γ, output-side). Both at 0.0
  = plain co-occurrence integers; at None = scorer disabled (prior scorers unaffected).
  Framework checks pass: integer co-occurrence, input-boost direction, output-boost direction,
  singleton-resistance. Three unported Step-2 scorers now outstanding — see ⚠ open item.

## 2026-05-29 — Phase 2: lift-with-shrinkage scorer added (feature/phase2-lift-scorer)

- **Commit**: 8dcaa55 on feature/phase2-lift-scorer (to be merged to main)
- **Notes**: Third selectable Step-2 scorer: `score = 1 + (lift-1) × m_b/(m_b+K)` where
  lift = (matched rate)/(population rate). K sweep (0,5,10,20,50) run. Key findings:
  K=5-10 resolves Set 2/Set 1/Set 4 well (canon-appropriate, less singleton flood). Set 3
  (all-rare) remains m_b=1-dominated at all K — root cause is small matched pool size, not
  scorer design. Two unported Step-2 scorers now outstanding in JS. See ⚠ open item above.

## 2026-05-29 — Phase 2: BETA scorer added (feature/phase2-beta-scorer)

- **Commit**: acae4ff on feature/phase2-beta-scorer (to be merged to main)
- **Notes**: Added BETA constant and `_norm_score()` to phase2_model.py. BETA=0 is the
  exact raw-affinity baseline; BETA>0 divides affinity by n_voters^BETA to penalize popular
  books. BETA sweep (0, 0.3, 0.5, 0.7, 1.0) run; Set 2/Set 3 divergence drops from 8→0
  shared top-15 books at BETA=0.5. Anomaly: BETA≥0.5 on mixed inputs causes singleton
  flooding (over-correction). BETA choice is still pending human review of sweep output.
- **⚠ Open item — JS parity, THREE unported Step-2 scorers**: site/main.js still runs raw
  affinity (BETA=0, SHRINK_K=None, COOC params None). The BETA scorer, lift-with-shrinkage
  scorer, and co-occurrence scorer are all unported. Until main.js is updated to implement whichever scorer is ultimately chosen
  and parity is re-confirmed, the live site serves raw affinity regardless of what
  phase2_model.py uses. This is a known and deliberate lag — do not ship a new default
  BETA or SHRINK_K without first porting and verifying the JS implementation.

## 2026-05-29 — Phase 1 cleanup complete (duplicate canonical merge)

- **Commit**: fbf37cb on feature/phase1-cleanup (to be merged to main)
- **Branch**: feature/phase1-cleanup
- **Notes**: Added T7/T7b (blank↔authored same or near title) and T8 (title variant) proposal tiers to phase1_canonicalize.py. After sign-off: 24 merges applied, canonical count 1,229 → 1,209. Key fixes: Moby-Dick (41→42), Ulysses (57→58), Tristram Shandy 3-way (→28), Clarissa 3-way (→4), Huckleberry Finn (28+3→30), Don Quixote/Quijote (24→25), Bible/Homer source-error correction. All 10 phase1 --verify checks pass; all 5 phase2 --verify cases pass; Mr./Mrs. Bridge still distinct. model_data.json re-exported (205.5 KB, 1,209 books).

## 2026-05-29 — Phase 3 complete (website)

- **Commit**: (to be merged to main from feature/phase3-site)
- **Branch**: feature/phase3-site
- **How to run**: `python3 -m http.server 8000` from repo root, then open `http://localhost:8000/site/`
- **Notes**: Static site in `site/` (index.html, style.css, main.js). Loads `data/model_data.json` (~207 KB) and runs the same rarity+position-weighted soft-kNN algorithm client-side. 15-point browser verification passed (autocomplete, duplicate prevention, stale graying, mobile layout, algorithm parity). Parity check: JS and Python produce identical 50-book ranking for Middlemarch + The Confidence-Man input. Also applied 6-decimal rounding to `phase2_model.py` sort key for guaranteed JS/Python float determinism.

## 2026-05-29 — Phase 2b complete (position factor)

- **Commit**: 8ac2398 on feature/phase2-position (to be merged to main)
- **Branch**: feature/phase2-position
- **Notes**: Added POSITION_WEIGHT=0.1 to voter similarity scoring. Position factor is a linear decay from 1.0 (pos 1) to 0.9 (pos 10), applied as a kwarg on recommend() so it can be swept without reloading. Edge cases: compound '1;5' → min=1 (21 rows, cross-source merges); blank → 10 neutral-low (48 rows, series_explode); out-of-range → clamp to 10. Dominance invariant confirmed: max swing (0.514) < cheapest book weight (1.407). PW=0 reproduces old numbers exactly. --verify covers 5 cases including compound-voter and explicit invariant demo. model_data.json updated with position_weight key and [[cid, pos]] pairs. Ready for Phase 3.

## 2026-05-28 — Phase 2 complete (matching model)

- **Commit**: dcf8e67 on feature/phase2-model (to be merged to main)
- **Branch**: feature/phase2-model
- **Tag**: (none yet)
- **Notes**: `phase2_model.py` implements the stable `recommend()` interface from PROJECT.md §5. Algorithm: rarity-weighted soft-k-NN; IDF weight `log((N+1)/(n+1))^RARITY_ALPHA` (α=1.0 default); voter similarity = raw weighted sum; book affinity = sum of voter similarities, tiebroken by rarity. 4 sanity-check cases pass (--verify). `data/model_data.json` exported (193 KB) for Phase 3 static site use. Ready for Phase 3 (website).

## 2026-05-28 — Phase 1 complete (canonical book identity signed off)

- **Commit**: 7b5c59d (main)
- **Branch**: main
- **Tag**: (none yet)
- **Notes**: Phase 1 pipeline (`phase1_canonicalize.py`) complete and all 10 verification checks pass. 3,564 rows → 1,229 canonical books; 220 books span both sources; 108 review flags all resolved (102 accepted, 6 rejected); 0 pending proposals. Human-reviewed every FUZZY_TITLE, AUTHOR_VARIANT, SERIES_EXPLODE, MULTI_BOOK_SLOT, NON_BOOK_ENTRY, BLANK_AUTHOR_RECOVERED, and BLANK_AUTHOR_CANON proposal. Outputs in `data/processed/`. Ready for Phase 2 (matching model).

## 2026-05-28 — ESCALATION (human review of Phase 1 canonical mapping)

- **Last task attempted**: Phase 1 — canonical book identity
- **Last commit**: pending merge of feature/phase1-canonical-identity
- **Branch state**: feature/phase1-canonical-identity ready; main has no commits yet
- **What was tried**: Built and ran `phase1_canonicalize.py` (stdlib-only). Outputs in `data/processed/`. All automated checks pass (1,247 canonical books from 3,564 rows; 217 cross-source bridges; Middlemarch 7-OLID split healed; Mr/Mrs Bridge kept distinct). 179 flags in review_flags.csv await human decisions.
- **Why escalating**: PROJECT.md §4 requires human review of the flagged cases before Phase 1 is trusted. Cannot advance to Phase 2 without sign-off.
- **Input needed from human**: Review `data/processed/review_flags.csv`. For each pending flag, record decision (accept/reject/pending) in `overrides/merge_decisions.csv`, then re-run `python3 phase1_canonicalize.py --verify`.