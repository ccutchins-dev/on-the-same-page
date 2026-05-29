# PROJECT.md — Kindred Lists

## 1. Premise

There are countless "greatest novels of all time" lists. Almost all of them collapse many people's opinions into a single aggregate ranking. This project rejects the aggregate.

The thesis: **a reader's taste is best matched not against a crowd average, but against specific individuals whose taste resembles theirs.** If three critics independently put obscure book X on their personal top-ten lists, and you also love X, those three people are a far better signal for what you'll read next than any "Top 100 Of All Time."

So we take a corpus of individual top-ten lists from authors and critics, let a user enter a handful of books they love, find the *people* whose lists overlap most with theirs, and surface the *books* those people loved that the user hasn't named yet.

## 2. What the user does

1. The user visits a single web page.
2. They select between 1 and 10 books they love from a **validated drop-down / search field**. Only books that exist in our canonical dataset can be chosen — there is no free-text entry, so there is never an unrecognized input.
3. They submit.
4. They receive:
   - **Primary output:** a scrollable, ranked list of recommended books — the books "closest" to their input — excluding any book they themselves entered.
   - **Secondary output:** a small side table of the authors/critics whose taste most resembles theirs ("Your taste aligns with: …").

That is the entire product. No accounts, no persistence, no social features.

## 3. The data

Source file: `combined_voters.csv` (~3,564 rows).

Each row is one book on one person's personal list. Key columns:

- `source` — which list collection the row came from (`Top Ten Books` or `Guardian Top 100`).
- `voter_name` — the individual author/critic. **This is the unit of taste we match against.** ~350 unique voters.
- `position` — the book's rank within that person's own list. **Not used as a similarity weight** (see §5); available only as an optional tiebreaker.
- `book_title`, `book_author`, `year` — the book. ~1,264 raw unique titles before normalization.
- `voter_type` — Author / Journalist / Academic (often blank). Display metadata only; not used in matching for v1.
- `openLibraryId` — present for the Guardian rows only (~1,720 rows); absent for Top Ten Books.

### Known data hazards (these drive Phase 1)

- The **same book appears under different title strings** across voters (translated titles, subtitle variants, punctuation). Title strings cannot be trusted as identity.
- **~140 rows have a blank author.**
- **Series collapsed into one position** — e.g. one voter's slot is split across the four "Rabbit" novels by Updike *plus* a series-level "Rabbit Angstrom" entry, all under a single position. **Resolved rule (§4):** a recognized series collapses to a single canonical book.
- **Only one of the two sources carries OpenLibrary IDs**, so IDs cannot be assumed present.

## 4. Phase 1 — Canonical book identity (the foundational task)

**This is the most important and most time-intensive phase. The quality of every recommendation depends on it. We are aiming for an "extremely confident" standard, not a quick fuzzy pass.**

Goal: collapse every row to a single **canonical book ID**, so that two people who love the same book are recognized as agreeing even when their title strings differ.

Approach (to be refined with Claude Code during the work):

- Build a canonicalization pipeline that normalizes titles/authors and resolves variants to one ID per book. Where OpenLibrary IDs exist, prefer them as the anchor; backfill the source that lacks them.
- Define explicit rules for the hazard cases: blank authors, series-under-one-position, translated/subtitled variants.
  - **Series rule (decided):** a recognized series collapses to a **single canonical book**. When both a series-level entry and its individual volumes appear (e.g. "Rabbit Angstrom" alongside the four Rabbit novels), prefer the series/omnibus identity as the canonical book. Every series collapse is written to the flagged-for-review file for confirmation.
- **Treat the canonical mapping as a reviewable, human-auditable artifact**, not a hidden intermediate step. The pipeline must output:
  - a clean canonical mapping file (raw row → canonical book ID, with title/author/year),
  - a separate **flagged-for-review list** of low-confidence merges and ambiguous cases (series, blank-author, near-duplicate titles), so a human can eyeball and correct them.
- Do not advance to Phase 2 until the canonical set is trusted.

Deliverable: a canonical book table + a voter→{canonical book IDs} mapping, plus the review/flag file.

## 5. Phase 2 — The matching model (modular, swappable)

The model is defined by a **stable interface**, with the algorithm behind it free to change:

```
input:  a list of 1–10 canonical book IDs (the user's loved books)
output: (a) a ranked list of canonical book IDs (recommendations), excluding the inputs
        (b) a ranked list of voter_names most similar to the user
```

Anything implementing that interface can be swapped in without touching the website. This modularity is a hard requirement.

### v1 algorithm (the starting point, not a permanent choice)

A k-nearest-neighbors approach over voters:

- Represent each voter as the **set of canonical book IDs** on their list. Membership is binary: a book being on someone's list means "I love this very much" — its position is not weighted.
- Compute similarity between the user's input set and each voter's set.
- **Weight matches by book rarity (inverse popularity).** Agreeing on an obscure book (one that appears on very few lists) is a much stronger taste signal than agreeing on a near-universal pick. (Empirically the data is top-heavy: *Middlemarch* appears on ~86 lists, while most books appear on one or two — so down-weighting the popular books matters a lot.)
- Rank voters by weighted similarity → that produces the **secondary "similar people" output** directly.
- Aggregate the books loved by the most-similar voters (again rarity-weighted, and excluding the user's own inputs) → that produces the **primary book recommendations**.
- `position` may be used only as a minor tiebreaker, never as a primary weight.

### Where the model lives

Given the scale — ~350 voters × ~1,264 books is a tiny, sparse matrix (a precomputed data file of a few hundred KB) — the model can almost certainly run **entirely in the browser**, with no backend. Phase 1 produces a precomputed data artifact; the site loads it and does the math client-side. *Claude Code to confirm this is the simplest viable approach during build; if a thin backend turns out simpler, that's an acceptable change.*

## 6. Phase 3 — The website

Priorities, in order: **simplicity, simplicity, simplicity.** Low traffic, no concurrency concerns, no accounts.

- Default to a **static site** (just files served as-is; the browser does the work; trivial and effectively free to host — e.g. GitHub Pages or Netlify). Stack (plain JS vs. a framework like React) is left to Claude Code's recommendation under the simplicity bias.
- UI surface:
  - a validated book picker (drop-down / searchable, choices limited to the canonical set, 1–10 selections),
  - a submit action,
  - the primary scrollable ranked book list,
  - the secondary "similar critics/authors" side table.
- The website must treat the model as a black box behind the §5 interface, so swapping the algorithm never requires website changes.

## 7. Explicit non-goals (v1)

- No comparison against any aggregate / consensus list — that's the whole point.
- No free-text book entry; no handling of books outside the dataset.
- No accounts, saved history, sharing, or persistence.
- No use of `voter_type` or list `position` as similarity weights.
- No multi-user scaling work.

## 8. Open questions to resolve during the build

- Exact rarity-weighting function and the k in k-NN — to be tuned once the canonical set exists and we can sanity-check recommendations against intuition.
- Whether any thin backend is warranted, or fully client-side (default assumption: fully client-side).

## 9. Suggested phase order

1. Canonical identity pipeline + human review of flagged cases (§4) — **do this thoroughly before anything else.**
2. Model behind the fixed interface, v1 = rarity-weighted k-NN (§5), validated by eyeballing outputs.
3. Static website wrapping the model (§6).