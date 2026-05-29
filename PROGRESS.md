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

## 2026-05-29 — Phase 2: BETA scorer added (feature/phase2-beta-scorer)

- **Commit**: acae4ff on feature/phase2-beta-scorer (to be merged to main)
- **Notes**: Added BETA constant and `_norm_score()` to phase2_model.py. BETA=0 is the
  exact raw-affinity baseline; BETA>0 divides affinity by n_voters^BETA to penalize popular
  books. BETA sweep (0, 0.3, 0.5, 0.7, 1.0) run; Set 2/Set 3 divergence drops from 8→0
  shared top-15 books at BETA=0.5. Anomaly: BETA≥0.5 on mixed inputs causes singleton
  flooding (over-correction). BETA choice is still pending human review of sweep output.
- **⚠ Open item — JS parity for BETA>0**: site/main.js still runs raw affinity (BETA=0).
  If a non-zero BETA is chosen, main.js must be updated to apply the same normalization
  and site/script parity must be re-confirmed before the site reflects the new default.
  Until that lands, the live site serves BETA=0 regardless of what phase2_model.py uses.

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