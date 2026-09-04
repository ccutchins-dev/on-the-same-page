# On the Same Page

**[onthesamepage.pages.dev](https://onthesamepage.pages.dev)**

Most "greatest books of all time" lists average many opinions into one
ranking. The average erases individual taste. This project skips the
average and matches you against specific people instead.

The source material is personal top-ten lists: "my ten favorite novels of
all time", "my ten favorite films". Hundreds of writers, directors, and
critics have published lists like this. We are more interested in
recommending books and movies you will *love* than books and movies you
will *like* — so if three critics all put an obscure novel on their
personal top ten, and you love that novel too, those three critics are a
better guide to what you'll read next than any consensus list.

## What you do

Pick books or films you love from the search field. Results update as
you pick — there is no submit button. Expand any result to see the
individual lists that support it. Move the "Popular ↔ Distinctive" slider
to steer the results toward common picks or toward rarer ones.

One honest caveat: the source lists skew toward the classics, so the
recommendations do too.

## How the matching works

A book on someone's top-ten list means "I love this," not "I rated this
4 out of 5 stars." A list is a set, not a ranking. Where a book falls on
the list matters only a little.

Rare agreement counts more than common agreement. *Middlemarch* appears
on about 83 book lists; most books appear on one or two. Two people
agreeing on an obscure book is a much stronger signal than two people
agreeing on *Middlemarch*. Every book is weighted by how rare it is.

Two scoring methods run side by side. One favors books that appear
alongside your picks often. The other favors books that appear alongside
your picks *more often than chance predicts* — it rewards a tighter,
less obvious connection. The slider blends the two: one end is pure
"often," the other end is pure "more than chance."

## The data

| | Voters | Titles |
|---|---|---|
| Books | 342 | 1,209 |
| Films | 2,115 | 4,485 |

Book lists come from Top Ten Books and the Guardian's Top 100, 3,564 raw
list entries in total. Film lists come from the 2022 Sight & Sound poll,
21,067 raw entries.

The hard part was not the matching. It was identity: the same book
appears under different title strings across voters — a translated
title, a different subtitle, a series entry that really means four
separate novels. Title strings alone cannot be trusted. Collapsing every
entry to one canonical book took a rules-based pass plus a human review
step, and both the review flags and the review decisions are committed
to this repo, so every merge is auditable.

## How it's built

A Python pipeline turns the raw lists into one small JSON file. The
website is plain HTML, CSS, and JavaScript — no framework, no build
step, no backend. The browser loads that one JSON file and does all the
ranking itself, in place, as you type. The data is small enough that
this works well. Cloudflare Pages serves the `site/` folder as-is.

## Repo map

- `input_data/` — the raw voter lists
- `phase1_canonicalize*.py` — turns titles into canonical book/film IDs
- `overrides/` — the human decisions the pipeline replays on every run
- `phase2_model.py` — scoring, and the JSON export the site loads
- `site/` — the website
- `PROJECT.md`, `DECISIONS.md`, `PROGRESS.md` — goals, design decisions,
  and a running log, for anyone who wants the full history

## Sources

The list data belongs to its original publishers. This is a personal,
non-commercial project.
