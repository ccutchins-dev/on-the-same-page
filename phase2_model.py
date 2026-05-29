"""
Phase 2 matching model for Kindred Lists.

Public interface (stable — algorithm is swappable behind it):
    model = load_model()
    book_ids, voter_names = recommend(model, input_ids)

Usage:
    python phase2_model.py              # load silently (import-safe; does nothing)
    python phase2_model.py --verify     # run 4 sanity-check cases, print results
    python phase2_model.py --export     # write data/model_data.json for Phase 3

Inputs (read-only):
    data/processed/canonical_books.csv
    data/processed/voter_books.csv

Outputs:
    data/model_data.json  (--export only)
"""

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path

# ── Tuning parameters ────────────────────────────────────────────────────────
RARITY_ALPHA       = 1.0   # IDF exponent: 0=uniform, 1=standard smoothed IDF, >1=stronger rarity
DEFAULT_TOP_BOOKS  = 50    # max book recommendations returned
DEFAULT_TOP_VOTERS = 20    # max similar voters returned

DATA_DIR = Path("data/processed")


# ── Data structures ───────────────────────────────────────────────────────────

class Model:
    """Precomputed model state. Build once with load_model(); reuse for many recommend() calls."""
    __slots__ = ("voter_books", "book_info", "n_voters", "alpha")

    def __init__(self, voter_books, book_info, n_voters, alpha):
        self.voter_books = voter_books   # {voter_name: frozenset[canonical_id]}
        self.book_info   = book_info     # {canonical_id: {"title","author","n_voters","weight"}}
        self.n_voters    = n_voters      # int — total distinct voters
        self.alpha       = alpha         # float — RARITY_ALPHA used at load time


# ── Loading ───────────────────────────────────────────────────────────────────

def load_model(data_dir=DATA_DIR, alpha=RARITY_ALPHA):
    """Load Phase 1 CSVs and precompute IDF weights. Call once per process."""
    data_dir = Path(data_dir)

    # 1. canonical_books.csv → book metadata + voter counts
    book_info = {}
    with open(data_dir / "canonical_books.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            book_info[row["canonical_id"]] = {
                "title":    row["canonical_title"],
                "author":   row["canonical_author"],
                "n_voters": int(row["n_voters"]),
                "weight":   0.0,   # filled below
            }

    n_voters = _count_voters(data_dir)

    # 2. Smoothed IDF weight per book: log((N+1)/(n+1))^alpha
    for cid, info in book_info.items():
        raw = math.log((n_voters + 1) / (info["n_voters"] + 1))
        info["weight"] = raw ** alpha

    # 3. voter_books.csv → voter → frozenset of canonical_ids
    raw_voter_books = defaultdict(set)
    with open(data_dir / "voter_books.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cid = row["canonical_id"]
            if cid in book_info:   # skip any orphaned ids (shouldn't exist)
                raw_voter_books[row["voter_name"]].add(cid)

    voter_books = {v: frozenset(bs) for v, bs in raw_voter_books.items()}

    return Model(voter_books, book_info, n_voters, alpha)


def _count_voters(data_dir):
    voters = set()
    with open(data_dir / "voter_books.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            voters.add(row["voter_name"])
    return len(voters)


# ── Core algorithm ────────────────────────────────────────────────────────────

def recommend(model, input_ids, *, top_books=DEFAULT_TOP_BOOKS, top_voters=DEFAULT_TOP_VOTERS):
    """
    Stable interface:
        input_ids  — iterable of 1–10 canonical_id strings
        returns    — (ranked_book_ids, ranked_voter_names)

    Algorithm (rarity-weighted soft-kNN):
        Step 1: score each voter by sum of IDF weights of shared books.
        Step 2: aggregate affinity for each candidate book by summing
                similarity scores of all voters who have it; tiebreak by
                rarity. Excludes books already in input_ids.
    """
    input_set = frozenset(input_ids)
    book_info  = model.book_info

    # Step 1 — voter similarity
    voter_sim = {}
    for voter, books in model.voter_books.items():
        overlap = input_set & books
        if overlap:
            voter_sim[voter] = sum(book_info[b]["weight"] for b in overlap if b in book_info)

    ranked_voters = sorted(voter_sim, key=lambda v: -voter_sim[v])

    # Step 2 — book affinity (sum over all matched voters who love the book)
    book_affinity = defaultdict(float)
    for voter, sim in voter_sim.items():
        for b in model.voter_books[voter]:
            if b not in input_set:
                book_affinity[b] += sim

    # Primary: affinity descending. Secondary: rarity (IDF weight) descending.
    ranked_books = sorted(
        book_affinity,
        key=lambda b: (-book_affinity[b], -book_info.get(b, {}).get("weight", 0.0)),
    )

    return ranked_books[:top_books], ranked_voters[:top_voters]


# ── Verification ──────────────────────────────────────────────────────────────

_VERIFY_CASES = [
    {
        "label": "1. Single common book — Middlemarch (83 voters)",
        "ids":   ["OL:OL20867W"],
    },
    {
        "label": "2. Single singleton — The Confidence-Man: His Masquerade (Melville, 1 voter)",
        "ids":   ["K:cc83b0188ed4"],
    },
    {
        "label": "3. Single book with 2–4 voters — The Third Policeman (Flann O'Brien, 4 voters)",
        "ids":   ["OL:OL2005223W"],
    },
    {
        "label": (
            "4. Mixed 5-book list — Middlemarch (83) + Anna Karenina (60) + "
            "Absalom, Absalom! (15) + The Third Policeman (4) + "
            "The Confidence-Man (1)"
        ),
        "ids": [
            "OL:OL20867W",    # Middlemarch              83 voters
            "OL:OL267096W",   # Anna Karenina             60 voters
            "K:d2d9f9b0f145", # Absalom, Absalom!         15 voters
            "OL:OL2005223W",  # The Third Policeman        4 voters
            "K:cc83b0188ed4", # The Confidence-Man         1 voter
        ],
    },
]


def run_verify(model):
    bi = model.book_info
    print(f"Model: {model.n_voters} voters · {len(bi)} books · RARITY_ALPHA={model.alpha}\n")

    for case in _VERIFY_CASES:
        print("=" * 72)
        print(case["label"])
        ids = case["ids"]

        # Confirm input IDs are valid
        missing = [i for i in ids if i not in bi]
        if missing:
            print(f"  ERROR: unknown canonical_id(s): {missing}")
            continue

        for cid in ids:
            info = bi[cid]
            print(f"  INPUT: {info['title'][:50]}  [{info['n_voters']} voters, weight={info['weight']:.3f}]")

        books, voters = recommend(model, ids, top_books=10, top_voters=5)

        print()
        print("  Top 5 voters by similarity:")
        input_set = frozenset(ids)
        for rank, v in enumerate(voters, 1):
            shared = input_set & model.voter_books[v]
            sim = sum(bi[b]["weight"] for b in shared if b in bi)
            shared_titles = ", ".join(bi[b]["title"][:25] for b in shared)
            print(f"    {rank}. {v[:35]:35}  sim={sim:.3f}  shared=[{shared_titles}]")

        print()
        print("  Top 10 recommended books:")
        # recompute affinity for display
        voter_sim = {}
        for voter, vbooks in model.voter_books.items():
            overlap = input_set & vbooks
            if overlap:
                voter_sim[voter] = sum(bi[b]["weight"] for b in overlap if b in bi)
        book_aff = defaultdict(float)
        for voter, sim in voter_sim.items():
            for b in model.voter_books[voter]:
                if b not in input_set:
                    book_aff[b] += sim

        for rank, cid in enumerate(books, 1):
            info = bi[cid]
            aff  = book_aff[cid]
            print(f"    {rank:2}. {info['title'][:45]:45}  "
                  f"{info['author'][:22]:22}  n={info['n_voters']:3}  aff={aff:.3f}")
        print()


# ── Export ────────────────────────────────────────────────────────────────────

def export_model_data(model, out_path=None):
    """
    Write data/model_data.json for Phase 3 (static site).
    Contains precomputed IDF weights so the browser runs the same algorithm
    without re-implementing the formula.
    """
    if out_path is None:
        out_path = Path("data") / "model_data.json"
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "n_voters": model.n_voters,
        "alpha":    model.alpha,
        "books": {
            cid: {
                "title":    info["title"],
                "author":   info["author"],
                "n_voters": info["n_voters"],
            }
            for cid, info in model.book_info.items()
        },
        "idf": {
            cid: round(info["weight"], 6)
            for cid, info in model.book_info.items()
        },
        "voter_books": {
            voter: sorted(books)
            for voter, books in model.voter_books.items()
        },
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    size_kb = out_path.stat().st_size / 1024
    print(f"Wrote {out_path}  ({size_kb:.1f} KB)")
    print(f"  {len(payload['books'])} books · {len(payload['voter_books'])} voters")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--export", action="store_true")
    args = parser.parse_args()

    model = load_model()

    if args.verify:
        run_verify(model)
    if args.export:
        export_model_data(model)
    if not args.verify and not args.export:
        print("Phase 2 model loaded OK.")
        print(f"  {model.n_voters} voters · {len(model.book_info)} books · RARITY_ALPHA={model.alpha}")
        print("Use --verify to run sanity checks, --export to write data/model_data.json.")
