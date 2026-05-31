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

## 2026-05-31 — Books/Movies mode toggle (feature/mode-toggle)

- **Branch**: feature/mode-toggle → merging to main
- **UI**: Segmented control (Books | Movies) above h1 via `order: -1`; post-run toggle
  centered; slider→heading gap widened to 1rem; redundant "Switch to Movies" post-input
  button removed (segmented control covers all switching paths)
- **Data loading**: books JSON at startup; movie JSON lazy-loaded + cached on first switch
- **No-leak core**: `applyModel()` (single shared rebuild path) + `makeEmptyRunState()`
  (single source of truth for reset). `updateModeUI('books')` in `init()` single-sources
  initial labels from `MODE_LABELS` map
- **Director overflow fix**: `truncateCreator(s, maxLen=100)` applied in `renderResults`,
  `renderEntries`, `renderDropdown`; title attr for full string on hover
- **Language**: `MODE_LABELS` map drives subtitle + search placeholders per mode; About page
  updated to cover both books and movies (static, mode-agnostic)
- **Books invariant**: all books-mode strings/recs/scores functionally identical to pre-toggle
- **Deferred**: /10 score recalibration for films; per-mode slider defaults

## 2026-05-31 — Film model data export (feature/film-export)

- **Branch**: feature/film-export (not yet merged — awaiting review)
- **Inputs**: `data/processed/canonical_films.csv` (4,485 films) + `data/processed/voter_films.csv` (21,050 rows)
- **Changes to `phase2_model.py`**:
  - `derive_film_positions()` + `--derive-positions` flag: writes deterministic 1..N positions into `voter_films.csv` (rarity-first → year ascending → blank year last → title alpha). Positions are DERIVED, not observed.
  - `load_model_films()`: film equivalent of `load_model()` (maps `canonical_director→author`, `vote_count→n_voters`, `resolved_year→year`)
  - `export_model_data_films()`: film equivalent of `export_model_data()` (blank descriptions, year from canonical_films.csv directly)
  - `--mode [books|films]` CLI flag (books is default; `--export` alone is unchanged)
- **Byte-identical guardrail passed**: `python3 phase2_model.py --export --mode books` → diff against committed `model_data.json` → identical
- **Output**: `site/data/model_data_movies.json` (1102.5 KB, 4,485 films, 2,115 voters)
- **Top-5 sanity check**: Jeanne Dielman 261 · Vertigo 246 · Citizen Kane 215 · 2001 192 · Tokyo Story 191 ✓
- **Deferred**: `/10` score normalization (calibrated against books, may cap for popular films); default slider value (may want per-mode tuning)
- **How to eyeball film mode locally** (do NOT commit main.js with this change):
  1. `python3 -m http.server 8020 --directory site/`
  2. Edit `site/main.js` line 741: change `'data/model_data.json'` → `'data/model_data_movies.json'`
  3. Browse http://localhost:8020; search a film, run recommendations
  4. Revert: `git checkout site/main.js`
- **Next**: user review → merge → build mode toggle (UI + label changes for film vs book mode)

## 2026-05-31 — Film adjudication phase (feature/film-adjudicate)

- **Branch**: feature/film-adjudicate (not yet merged — awaiting review)
- **Inputs**: 146 review flags from Phase 1 film canonicalization; 79 human decisions encoded in `overrides/film_adjudications.csv`
- **Script changes**: `phase1_canonicalize_films.py` extended with adjudication processing block (injected before write outputs). Key additions: merge loop, year/director setters, unresolved-row assignment, trilogy explosion with separate voter_films emission.
- **Results**:
  - canonical_films: 4,516 → 4,485 (−31 net: 37 merges removed, 4 create_and_assign + 2 explosion-new created)
  - voter_films: 21,050 rows, 2,115 voters
  - Explosions: 3 omnibus clusters ("Apu Trilogy", "The Apu Trilogy", "The Bill Douglas Trilogy") → components
- **Verified decisions** (all pass):
  - Dekalog: 4 source clusters merged → F:99525f6dd03f (Dekalog (Decalogue), 1989, 16 votes)
  - Leviathan: F:214b96df970a (2012, doc) and F:0e802a09eb66 (2014, Zvyagintsev) remain distinct
  - Week End / Weekend: F:ee860a1dac92 (Godard 1967) and F:9fec4fea25ca (Haigh 2011) remain distinct
  - Twin Peaks: The Return 2018 NBSP variant merged into F:f00e3c45dd9d (2017); Fire Walk With Me and 1990 series stay distinct
  - Apu Trilogy: 5 voter rows (3 "The Apu Trilogy" + 1 "Apu Trilogy" + 1 "The Apu trilogy") exploded; de-dup prevents duplicate Pather Panchali for voters who listed it separately
  - Bill Douglas Trilogy: Adam Chodzko's row exploded → My Childhood (F:49a59167770c) + My Ain Folk (F:2d923d9ec318, new, 1973) + My Way Home (F:d73269047025, new, 1978)
  - 7 new canonicals created: Andhaa Kaanoon (1983), The Prison in 12 Landscapes (2016), Looking for Mushrooms (1965), Gedächtnis (1981), Ceux de chez nous (1915), My Ain Folk (1973), My Way Home (1978)
- **Bug fixed during implementation**: explosion added voters to `canonical[cid]["voters"]` but `voter_films.csv` is built from `processed` rows only — explosion-added pairs were never emitted. Fixed with `explosion_added_pairs` list fed into voter_films output loop.
- **Next**: review diff and merge to main; then begin Phase 2 film pipeline (model_data.json equivalent for film mode).

## 2026-05-31 — Mobile layout refinements (feature/mobile-layout-refinements)

Five additive changes inside `@media (max-width: 600px)`. Desktop unchanged.

1. **Result title stacking**: `result-title-row` changed to `display: block`; title
   wraps at full column width; byline appears on its own line beneath. Overrides
   `overflow: hidden` and `white-space: nowrap` that were clipping titles to ~2 words.

2. **Expanded card full-width**: `result-detail { grid-column: 1/-1; margin-right: 0 }`
   removes the desktop 41.6px left indent and 12px right buffer that squeezed the
   expanded card to ~256px; now ~310px. Voter-strip sidescroll preserved.

3. **Dropdown min-width**: `min-width: 100%` removes the fixed 320px floor that
   extended the dropdown past the viewport on 320px phones (measured: right=340 > iw=320).
   After: right=300 < 320 at 320px; count visible.

4. **Dropdown count inline**: `justify-content: flex-start; gap: 0` on `.dropdown-item`
   and `flex: 0 1 auto` on `.item-left` so "on N lists" flows inline after the author
   instead of right-aligning. `::before { content: '·'; margin: 0 0.25rem }` adds
   the separator with spacing matching the existing title/author dot.

## 2026-05-31 — Mobile horizontal overflow fix (feature/mobile-overflow)

- **Diagnosis**: post-run state at 390px viewport showed scrollWidth=686px (+296px).
  Two-layer cascade of CSS Grid `min-width: auto` defaults. Layer 1: `#input-panel`
  and `#results-panel` (grid items in `#main.post-run`) pushed the `1fr` track to 646px
  instead of ~310px. Layer 2: inside each result `<li>` (grid: `2rem 1fr auto`),
  `result-title-row` (flex container with `flex-shrink:0` byline) pushed its `1fr`
  column to ~302px instead of ~236px, adding 65px overflow per row.
- **Fix**: additive rules inside `@media (max-width: 600px)`:
  `min-width: 0` on `#input-panel`, `#results-panel`, `.result-title-row`,
  `.result-count`; `overflow: hidden` on `.result-title-row`.
- **Verified**: post-fix scrollWidth=390=innerWidth (0px overflow); voter strip
  still sidescrolls (scrollWidth=2704 > clientWidth=214); desktop unchanged.

## 2026-05-31 — Mobile responsiveness (feature/mobile-responsive)

- **Diagnosis**: viewport meta tag already correct (not a cause). Search input was
  14.4px (0.9rem) → iOS Safari auto-zoom on focus. `#input-panel { position: sticky }`
  in post-run state causes panel to overlay scrolling results on phones. The 768px
  breakpoint already collapses the two-column grid to single-column.
- **Fixes**: single additive `@media (max-width: 600px)` block; no base rules modified.
  (1) Header: `display: flex; justify-content: space-between` → tabs left, title right.
  (2) `#input-panel { position: static }` → panel scrolls away instead of pinning.
  (3) `#search-input { font-size: 1rem }` → stops iOS auto-zoom (≥16px threshold).
- **Desktop**: byte-for-byte unaffected — diff is 24 lines added inside the new block.

## 2026-05-31 — About page redesign (feature/about-redesign-v2)

- **New copy**: replaced the three-section (How to Use / Underlying Data / Methodology)
  About page with a single-voice editorial layout. No section headers. Opening sentence
  functions as a pull-quote lead-in; four numbered tips with lettered a/b asides for
  slider caveats.
- **Typography**: 820px column, 3rem/5rem vertical padding. Lead paragraph 1.35rem /
  1.6 line-height. Body at 1.85 line-height and 1.25rem paragraph spacing. Numbered
  and lettered markers in --text (no accent coloring). Lettered sub-items at 0.9rem,
  same --text color.
- **Removed**: "ABOUT" heading (redundant with active tab), all .about-steps /
  .about-signals / h2 CSS rules.
- **Deployed**: merged to main and pushed; Cloudflare auto-redeploy triggered.

## 2026-05-31 — Tab nav + concise summary (feature/tab-nav-summary)

- **Tab nav**: replaced hamburger dropdown with always-visible Main/About tabs in the
  header. Header is now a `1fr auto 1fr` grid — tabs left, title centered (balanced by
  the empty 3rd column), no extra markup needed. Active tab gets a 2px accent underline.
  Narrow-screen breakpoint (<480px) switches to `auto auto 1fr` so tabs and title don't
  collide on phone widths. `initNav()` rewritten; `showView()` and state-preservation
  logic unchanged.
- **Summary line**: "on X lists from voters who share at least one input — Y of them
  share multiple" → "X lists share at least one input; Y share multiple". Single-input
  case: "X lists share at least one input" (no dangling semicolon).
- **Verified**: localhost review passed before merge.
- **Deployed**: merged to main and pushed; Cloudflare auto-redeploy triggered.

## 2026-05-31 — Cloudflare Pages deployment prep (feature/deploy-prep)

- **Restructure**: `data/model_data.json` moved to `site/data/model_data.json`. The `site/`
  directory is now a self-contained web root: index.html, main.js, style.css, data/model_data.json.
- **Fetch path fix**: `main.js` fetch changed from `../data/model_data.json` → `data/model_data.json`
  (relative to the page root, resolves correctly whether served locally or on Cloudflare).
- **Export path fix**: `phase2_model.py` default out_path changed from `data/model_data.json`
  → `site/data/model_data.json` so `--export` drops the file in the right place.
- **Go-forward update workflow**: edit CSV → `python3 phase2_model.py --export` →
  commit `site/data/model_data.json` → push → Cloudflare auto-redeploys.
- **GitHub**: private repo `ccutchins-dev/on-the-same-page` created; full history pushed.
- **Cloudflare Pages settings**: Framework: None, Build command: (empty),
  Build output directory: `site`. No redirects needed (About is a JS view toggle).
- **Verified locally**: served `site/` as root via `python3 -m http.server 8020 --directory site/`;
  confirmed page renders, 50 recommendations loaded (JSON fetched), About toggle works,
  zero console errors or 404s.

## 2026-05-30 — Slider polish + strip buffer fix (feature/slider-strip-polish)

- **Strip buffer**: `.detail-strip::after { flex: 0 0 0.5rem }` trailing spacer — actual
  content counted in scrollWidth, guarantees right-side buffer at scroll-end. Chrome's
  overflow-padding asymmetry (left padding counted, right padding dropped) was the root
  cause of two previous failed attempts.
- **Slider default**: 0.25 → 0.20 (`BLEND_DEFAULT` constant).
- **Bordered slider card**: `#blend-control` now has `border: 1px solid var(--border)` +
  border-radius + padding.
- **Reset button** (↺): replaces persistent `#blend-value` span; returns slider to 0.20.
- **Delayed tooltip**: numeric value hidden by default; shown after 2s hover-pause (debounced)
  or during active drag; hides on mouse-leave or 600ms after drag ends.
- **Next**: continue with any remaining UX/data polish.

## 2026-05-30 — CSV source of truth + strip buffer (feature/csv-source-of-truth)

- **Year resolution**: `resolve_years.py` applied 29 single-titled-work resolutions in
  `manually_filled_descriptions_and_years.csv` (range → last year). 47 separately-titled
  collections/series kept as ranges. Script is a one-time artifact.
- **Export consolidation**: `phase2_model.py` now reads solely from the curated CSV for
  both year and description. Old pipes (year_backfill, year_overrides, descriptions.csv,
  canonical_year) retired. model_data.json re-exported at 597.4 KB.
- **Description**: empty description → element omitted entirely from expanded panel (no
  placeholder). `renderDetailPanel()` only creates `.detail-description` when non-empty.
- **Strip buffer**: moved horizontal padding from `.detail-strip` (child of overflow
  container — unreliable) to `.detail-strip-wrapper` (the container itself — always
  visible outside scroll viewport).
- **Next**: supply updated CSV edits; descriptions and year corrections go via CSV →
  re-export workflow.

## 2026-05-30 — Rename + About page (feature/about-page)

- **Rename**: "Kindred Lists" → "On the Same Page" in `<title>`, header `.site-name`,
  and `PROJECT.md` heading. Display text only — no file, class, or identifier renames.
- **About page**: new `#about` div with three sections (How to Use / Underlying Data /
  Methodology), narrow 640px reading column, full dark-mode palette.
- **Nav**: hamburger ☰ now opens a dropdown with Main + About items. Click-outside
  uses explicit containment check. Header site-name navigates to Main.
- **State preservation**: `#main` is hidden/shown only; all JS state and DOM content
  survive navigation to About and back unchanged.
- **Model-independent nav**: `initNav()` runs before `init()` so About is reachable
  even during a slow or failed model load.
- **Next**: supply `descriptions.csv` + `year_overrides.csv` data in a separate session.

## 2026-05-30 — Light UX + data batch (feature/light-ux-batch)

- **Data plumbing**: descriptions.csv-or-placeholder + year_overrides.csv (header-only)
  added to export; model_data.json re-exported at 313.7 KB with description field.
  30 lifespan-range blank-year books + 448 OL-blocked books listed in PROGRESS for
  the upcoming data session. year_overrides.csv mechanism tested and confirmed working.
- **Item 1**: byline now left-grouped (Title · Author · Year inline); removed flex:1
  from .result-title so byline follows immediately rather than floating right.
- **Item 2**: blend-rank tooltip (li.title) removed from result rows.
- **Item 3**: voter strip has 0.5rem breathing room on left/right inside scroll area.
- **Item 4a**: scores inline in expanded panel (label + value on one line per score).
- **Item 4b**: description renders in expanded panel between scores and voter strip.
- **Next**: data session to supply descriptions.csv + year values for the 478 remaining
  books (30 lifespan-range + 448 OL-blocked; use year_overrides.csv + re-export).

## 2026-05-30 — UX batch 2 (feature/ux-batch-2)

- **Data**: "Independant People" → "Independent People" in canonical_books.csv;
  phase2_model.py now exports year per book (canonical_year + year_backfill.csv);
  model_data.json re-exported at 220.4 KB, 731/1209 books with year.
- **Item 1**: .result-detail grid-column 1/-1 → 2/-1; expansion now aligns under title.
- **Item 2**: #main.post-run max-width 1200px → 1360px.
- **Item 4**: Three result rows collapsed to two. Title+author·year on one flex line
  (.result-byline), count on row 2. .result-chevron spans 2 rows (was 3).
- **Item 5**: /10 scores: sqrt-compressed co-occ (D=5.5, not n-scaled) + linear PPMI
  (D=3.8/input). Popular pair spreads 9.4/8.9/8.7/8.3; incoherent pair tops at
  3.1/9.3 (both below 10).
- **Item 6**: .result-chevron right padding 0.5rem → 0.75rem.
- **Next**: merge to main; continue year gap resolution (openlibrary.org allowlist
  or manual fill of year_gaps.csv).

## 2026-05-30 — UX + data batch (feature/ux-data-batch)

- **Commits**: 6dbe85b backfill script · e170159 CSS layout · (JS display pending merge)
- **Year data**: backfill_years.py auto-resolves 22 publication ranges (≤25yr span)
  + 15 ancient works → "pre-Renaissance". 478 remain in year_gaps.csv for human review
  (29 lifespan ranges, 448 truly blank). Re-export of model_data.json blocked on gap
  resolution; OL API fetch resolves 438 OL-prefixed books if openlibrary.org is allowlisted.
- **Item 1**: results column max-width → min(100vw-2.5rem, 1200px); CSS strip breakout retired.
- **Item 3**: summary line → "on X lists from voters who share at least one input —
  Y of them share multiple" (Y clause dropped for 1-input). computeMatchedVoterCounts
  now returns both counts; state.multiMatchCounts added.
- **Item 4**: dropdown rows now show Title · Author on left, count right.
- **Item 5**: scores shown as "N.N / 10" with input-aware denominators (n_voters sum
  for co-occ, max-PPMI sum for distinctiveness). Hint text removed.
- **Year display** (item 2): renderResults shows "Author · Year" when year field is
  present in model_data.json; shows just author when blank. Requires re-export after
  year gap resolution.
- **Next**: resolve year_gaps.csv (allowlist openlibrary.org or fill manually) → re-export
  model_data.json → merge to main.

## 2026-05-30 — UX follow-up batch (feature/ux-followup)

- **Commits**: d914b2f focus-state fix · (layout+visual pending merge)
- **Focus-state bugs fixed**: (1) dropdown no longer opens on page load — removed
  `elSearchInput.focus()` from `setupUI()`; (2) clicking the input after book selection
  always opens dropdown — added `click` listener calling `onSearchFocus`; guard prevents
  scroll reset mid-browse.
- **Slider above title post-run**: `#main.post-run #run-area { order: -1 }` — floats
  before h1 (order 0) in the sticky input panel.
- **Chevron vertically centered**: moved chevron out of `.result-title-row` into grid
  column 3, `grid-row: 1 / span 3`, `align-self: center`; right padding added.
- **Voter strip breakout**: pure CSS `width: min(calc(100vw - 360px), calc(8 * 170px + 1rem))`
  on `.detail-strip-wrapper` — no JS needed, responds to resize automatically.
- **Resting background**: `.result-detail { background: #252525 }` — subtle elevation
  over `--bg` (#1e1e1e), no hover rule added (existing li:hover keeps title-row blue).
- **Next**: merge feature/ux-followup to main.

## 2026-05-30 — UX cosmetic batch (feature/ux-batch)

- **Commits**: e01f510 dark mode · e57de9e chevron/card/slider/label · 76657d6 dropdown · (slider default + docs)
- **Dark mode**: CSS var palette only — all components use var(--*) already, no rewrites
- **Browsable dropdown**: focus opens full catalog (n_voters desc); windowed render (100+50/scroll); title + "on N lists"; keyboard nav preserved including arrow-past-boundary window growth
- **Other**: expansion chevron (› rotates), card-like expansion boundaries, slider above book list in post-run, label centered, t=0.25 default

## 2026-05-30 — Deterministic evidence view (feature/evidence-view)

- **Commit**: 288a0dd on feature/evidence-view (to be merged to main)
- **Replaces**: prose headline, badge, tier bars, connection note in expansion panel
- **Shows**: co-occurrence score (int), PPMI score (2dp), full voter strip (horizontal scroll)
- **Voter cards**: ordered by shared-count desc → idf-sum desc; books by pos→rarity→alpha
- **Highlights**: .is-rec (dark blue) and .is-input (light blue) in-place, not reordered
- **Height**: uniform via CSS flex stretch, no hardcoded pixel constant
- **Verified**: score parity, voter count, card order, highlights, accordion, mobile

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