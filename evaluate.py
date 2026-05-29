#!/usr/bin/env python3
"""
evaluate.py — leave-out recovery evaluation harness for Kindred Lists.

Protocols:
  A. Leave-one-out: for each voter, hold out each book in turn, ask the model
     (without that voter) to recover it from the rest.
  B. Retained-input curve (K=1..8): hold out all-but-K books, measure recovery
     averaged over multiple random K-subsets.

Usage:
    python3 evaluate.py                    # α=1.0, γ=1.0 (production defaults)
    python3 evaluate.py --alpha 1.5        # custom input rarity
    python3 evaluate.py --gamma 0.5        # custom output rarity
    python3 evaluate.py --validate-only    # validation checks only, no full run
    python3 evaluate.py --seed 42          # reproducible random draws
"""

import argparse
import math
import random
import sys
from collections import defaultdict
from pathlib import Path

# Import the model (read-only — evaluate.py never modifies phase2_model.py)
from phase2_model import load_model, recommend, COOC_INPUT_EXP, COOC_OUTPUT_EXP

NUM_DRAWS = 10   # random retained-input subsets per (voter, K); 10 for smooth curve
TOP_BOOKS = 50   # top recommendations to retrieve per call (covers recall@25, MRR)
K_RANGE   = range(1, 9)   # K = 1..8

DATA_DIR = Path("data/processed")


# ── Voter-exclusion wrapper ────────────────────────────────────────────────────

class _EvalModel:
    """
    Thin wrapper with the same interface as Model, but voter_books excludes
    one voter. Everything else — book_info, n_voters, alpha — is FROZEN at
    full-dataset values so rarity weights are not biased by exclusion.
    """
    __slots__ = ("voter_books", "voter_positions", "book_info", "n_voters", "alpha")

    def __init__(self, base, exclude_voter):
        self.voter_books     = {v: b for v, b in base.voter_books.items()
                                if v != exclude_voter}
        self.voter_positions = base.voter_positions   # not used by co-occurrence scorer
        self.book_info       = base.book_info         # FROZEN
        self.n_voters        = base.n_voters          # FROZEN
        self.alpha           = base.alpha             # FROZEN


# ── Recommendability ──────────────────────────────────────────────────────────

def build_book_to_voters(voter_books):
    """Build reverse index: cid → set of voter names."""
    btv = defaultdict(set)
    for voter, books in voter_books.items():
        for b in books:
            btv[b].add(voter)
    return btv


def is_recommendable(book_to_voters, voter_books, exclude_voter, input_set, h):
    """
    True iff some voter w ≠ exclude_voter has h AND shares at least one book
    with input_set.  If this returns False, h cannot appear in recommendations
    from the LOO model (structural impossibility, not model failure).
    """
    for w in book_to_voters.get(h, ()):
        if w == exclude_voter:
            continue
        if input_set & voter_books[w]:
            return True
    return False


# ── Trial helpers ─────────────────────────────────────────────────────────────

def rank_of(ranked_books, h):
    """1-indexed rank of h in ranked_books list, or None if not present."""
    try:
        return ranked_books.index(h) + 1
    except ValueError:
        return None


def rarity_weight(n_voters, N):
    """raw_idf(n) = log((N+1)/(n+1)); higher weight for rarer books."""
    return math.log((N + 1) / (n_voters + 1))


def popularity_bin(n_voters):
    if n_voters == 1:   return "n=1"
    if n_voters <= 5:   return "n=2-5"
    if n_voters <= 20:  return "n=6-20"
    return "n=21+"


# ── Metrics ───────────────────────────────────────────────────────────────────

def compute_metrics(trials, N):
    """
    Compute recall@10, recall@25, rarity-weighted recall@10/@25, MRR,
    and popularity-stratified recall@10 from a list of trial dicts.

    Each trial dict: {rank: int|None, n_voters: int, recommendable: bool}
    Only recommendable=True trials are included.
    """
    rec_trials = [t for t in trials if t["recommendable"]]
    if not rec_trials:
        return {
            "n_rec": 0, "recall_10": None, "recall_25": None,
            "rw_recall_10": None, "rw_recall_25": None, "mrr": None,
            "strat": {},
        }

    r10 = r25 = rw10_num = rw10_den = rw25_num = rw25_den = mrr = 0.0
    strat = defaultdict(lambda: [0, 0])   # bin → [hits@10, total]

    for t in rec_trials:
        rank = t["rank"]   # 1-indexed or None (beyond TOP_BOOKS)
        nv   = t["n_voters"]
        w    = rarity_weight(nv, N)
        b    = popularity_bin(nv)

        hit10 = 1 if rank is not None and rank <= 10 else 0
        hit25 = 1 if rank is not None and rank <= 25 else 0

        r10   += hit10
        r25   += hit25
        rw10_num += w * hit10;  rw10_den += w
        rw25_num += w * hit25;  rw25_den += w
        mrr   += (1.0 / rank) if rank is not None else 0.0
        strat[b][0] += hit10
        strat[b][1] += 1

    n = len(rec_trials)
    return {
        "n_rec":       n,
        "recall_10":   r10 / n,
        "recall_25":   r25 / n,
        "rw_recall_10": rw10_num / rw10_den if rw10_den else 0.0,
        "rw_recall_25": rw25_num / rw25_den if rw25_den else 0.0,
        "mrr":         mrr / n,
        "strat":       {b: (v[0] / v[1] if v[1] else 0.0, v[1])
                        for b, v in strat.items()},
    }


# ── Protocol A: Leave-one-out ─────────────────────────────────────────────────

def run_protocol_a(base_model, alpha, gamma):
    """
    For each voter v, for each book h on v's list:
    - Create LOO model (v excluded, all weights frozen)
    - Run co-occurrence scorer on v.books - {h}
    - Record rank of h (or unrecommendable flag)
    """
    voter_books   = base_model.voter_books
    book_info     = base_model.book_info
    N             = base_model.n_voters
    book_to_voters = build_book_to_voters(voter_books)

    # Pre-create all LOO models
    loo_models = {v: _EvalModel(base_model, v) for v in voter_books}

    trials        = []
    n_unrecommend = 0

    for voter, books in voter_books.items():
        loo = loo_models[voter]
        books_list = list(books)
        for h in books_list:
            input_ids = frozenset(b for b in books_list if b != h)
            n_h = book_info.get(h, {}).get("n_voters", 1)

            if not is_recommendable(book_to_voters, voter_books, voter, input_ids, h):
                n_unrecommend += 1
                trials.append({"recommendable": False, "n_voters": n_h})
                continue

            ranked, _ = recommend(loo, list(input_ids),
                                   cooc_input_exp=alpha, cooc_output_exp=gamma,
                                   top_books=TOP_BOOKS)
            r = rank_of(ranked, h)
            trials.append({"recommendable": True, "rank": r, "n_voters": n_h})

    return trials, n_unrecommend


# ── Protocol B: Retained-input curve ─────────────────────────────────────────

def run_protocol_b(base_model, alpha, gamma, k_range=K_RANGE, num_draws=NUM_DRAWS):
    """
    For each K, for each voter, for each random K-subset as input:
    hold out the rest, record rank of each held-out book.
    """
    voter_books    = base_model.voter_books
    book_info      = base_model.book_info
    N              = base_model.n_voters
    book_to_voters = build_book_to_voters(voter_books)

    loo_models = {v: _EvalModel(base_model, v) for v in voter_books}
    curve = {}

    for K in k_range:
        trials        = []
        n_unrecommend = 0

        for voter, books in voter_books.items():
            books_list = list(books)
            if len(books_list) <= K:
                continue   # need at least K+1 books

            loo = loo_models[voter]

            for _ in range(num_draws):
                input_ids  = frozenset(random.sample(books_list, K))
                held_out   = [b for b in books_list if b not in input_ids]

                ranked, _ = recommend(loo, list(input_ids),
                                       cooc_input_exp=alpha, cooc_output_exp=gamma,
                                       top_books=TOP_BOOKS)

                for h in held_out:
                    n_h = book_info.get(h, {}).get("n_voters", 1)
                    if not is_recommendable(book_to_voters, voter_books, voter, input_ids, h):
                        n_unrecommend += 1
                        trials.append({"recommendable": False, "n_voters": n_h})
                        continue
                    r = rank_of(ranked, h)
                    trials.append({"recommendable": True, "rank": r, "n_voters": n_h})

        curve[K] = (trials, n_unrecommend)

    return curve


# ── Differentiation diagnostic ────────────────────────────────────────────────

def run_differentiation_diagnostic(base_model, alpha, gamma, n_pairs=20):
    """
    Sample n_pairs random voter pairs; measure overlap in their top-10 recommendations
    given 5 random books each.  Uses the FULL model (no voter excluded) because this
    measures production differentiation, not recovery accuracy.  The only place in the
    harness using the full model — all recall metrics use LOO models.
    """
    voters     = list(base_model.voter_books.keys())
    overlaps   = []
    INPUT_SIZE = 5

    for _ in range(n_pairs):
        va, vb = random.sample(voters, 2)
        books_a = list(base_model.voter_books[va])
        books_b = list(base_model.voter_books[vb])

        input_a = random.sample(books_a, min(INPUT_SIZE, len(books_a)))
        input_b = random.sample(books_b, min(INPUT_SIZE, len(books_b)))

        recs_a, _ = recommend(base_model, input_a,
                               cooc_input_exp=alpha, cooc_output_exp=gamma,
                               top_books=10)
        recs_b, _ = recommend(base_model, input_b,
                               cooc_input_exp=alpha, cooc_output_exp=gamma,
                               top_books=10)
        overlap = len(set(recs_a) & set(recs_b)) / 10.0
        overlaps.append(overlap)

    return sum(overlaps) / len(overlaps) if overlaps else 0.0


# ── Random-baseline validation ────────────────────────────────────────────────

def run_random_baseline(base_model):
    """
    Theoretical recall@10 for a random recommender: 10 / avg_n_candidates.
    avg_n_candidates ≈ n_books − avg_input_size.
    This avoids sampling variance — the expected value is deterministic and
    correct, and is what the model must beat to show it has learned anything.
    """
    n_books  = len(base_model.book_info)
    voter_books = base_model.voter_books
    avg_list = sum(len(b) for b in voter_books.values()) / max(len(voter_books), 1)
    # In LOO, input size = list_len - 1; avg candidates = n_books - (avg_list - 1)
    avg_candidates = n_books - (avg_list - 1)
    return 10.0 / avg_candidates if avg_candidates > 0 else 0.0


# ── Validation checks ─────────────────────────────────────────────────────────

def run_validation_checks(base_model, alpha, gamma, book_info_frozen):
    """Print all four harness validation checks."""
    voter_books    = base_model.voter_books
    book_to_voters = build_book_to_voters(voter_books)
    N              = base_model.n_voters

    print("\n──── Harness Validation ─────────────────────────────────────────────────")

    # 1. Random baseline
    print("\n1. Random baseline:")
    rand_r10 = run_random_baseline(base_model)
    print(f"   Expected ~0.83%  |  Measured: {rand_r10*100:.2f}%")

    # 2. Recall curve in K (just K=1,4,8 for validation speed)
    print("\n2. Recall curve (K=1,4,8 spot-check) + held-out composition:")
    for K in [1, 4, 8]:
        bins = defaultdict(int)
        n_rec = n_unrec = 0
        for voter, books in voter_books.items():
            books_list = list(books)
            if len(books_list) <= K:
                continue
            input_ids = frozenset(random.sample(books_list, K))
            for h in books_list:
                if h in input_ids:
                    continue
                nv = book_info_frozen.get(h, {}).get("n_voters", 1)
                if is_recommendable(book_to_voters, voter_books, voter, input_ids, h):
                    bins[popularity_bin(nv)] += 1
                    n_rec += 1
                else:
                    n_unrec += 1
        total = n_rec + n_unrec
        comp = {b: f"{100*v/total:.0f}%" for b, v in bins.items()} if total else {}
        print(f"   K={K}: recommendable={n_rec} unrec={n_unrec}  composition={comp}")
    print("   (No auto-flag on recall dips — composition changes are real.)")

    # 3. Unrecommendable ≥ singletons
    print("\n3. Unrecommendable ≥ singletons check:")
    singleton_count = sum(1 for v, books in voter_books.items()
                          for b in books if book_info_frozen.get(b,{}).get("n_voters",0) == 1)
    unrec_count = sum(
        1 for voter, books in voter_books.items()
        for h in books
        if not is_recommendable(book_to_voters, voter_books, voter,
                                frozenset(b for b in books if b != h), h)
    )
    ok = "✓" if unrec_count >= singleton_count else "✗"
    print(f"   Unrecommendable in LOO: {unrec_count}  |  Singleton voter-book pairs: {singleton_count}  {ok}")

    # 4. Spot-check A.L. Kennedy
    print("\n4. Spot-check — A.L. Kennedy:")
    kennedy = "A.L. Kennedy"
    if kennedy not in voter_books:
        print("   A.L. Kennedy not in voter_books — skip.")
        return

    ken_books     = list(voter_books[kennedy])
    confidenceman = "K:cc83b0188ed4"   # The Confidence-Man (singleton for A.L. Kennedy)
    third_police  = "OL:OL2005223W"    # The Third Policeman (n=4)

    # Check singleton → unrecommendable
    if confidenceman in ken_books:
        inp_no_cm = frozenset(b for b in ken_books if b != confidenceman)
        unrec_cm = not is_recommendable(book_to_voters, voter_books, kennedy, inp_no_cm, confidenceman)
        cm_title = book_info_frozen.get(confidenceman, {}).get("title", confidenceman)
        print(f"   '{cm_title}' (n=1, hold-out): unrecommendable={unrec_cm}  {'✓' if unrec_cm else '✗'}")
    else:
        print("   The Confidence-Man not in A.L. Kennedy's list — skip.")

    # Check Third Policeman → has a finite rank
    if third_police in ken_books:
        inp_no_tp = frozenset(b for b in ken_books if b != third_police)
        rec_tp = is_recommendable(book_to_voters, voter_books, kennedy, inp_no_tp, third_police)
        tp_title = book_info_frozen.get(third_police, {}).get("title", third_police)
        if rec_tp:
            loo_k = _EvalModel(base_model, kennedy)
            # Use 200 for spot-check to show the true rank (harness uses TOP_BOOKS=50 for metrics)
            ranked, _ = recommend(loo_k, list(inp_no_tp),
                                   cooc_input_exp=alpha, cooc_output_exp=gamma,
                                   top_books=200)
            r = rank_of(ranked, third_police)
            in_top50 = "  (outside top-50 metrics window)" if r is None or r > TOP_BOOKS else ""
            r_str = str(r) if r else f">200"
            print(f"   '{tp_title}' (n=4, hold-out): recommendable=True ✓  rank={r_str}{in_top50}")
        else:
            print(f"   '{tp_title}' (n=4, hold-out): unexpectedly unrecommendable ✗")
    else:
        print("   The Third Policeman not in A.L. Kennedy's list — skip.")


# ── Print panel ───────────────────────────────────────────────────────────────

def print_panel(alpha, gamma, n_voters_total, n_books, n_pairs,
                n_singletons, singleton_pct, pair_singleton_pct,
                loo_trials, loo_unrec,
                curve,
                diff_diag,
                random_r10,
                book_info_frozen):

    N = n_voters_total

    print(f"\n{'='*72}")
    print(f"  Kindred Lists Evaluation  |  α={alpha}  γ={gamma}")
    print(f"  co-occurrence scorer  |  {n_voters_total} voters  |  {n_books} books  |  {n_pairs} voter-book pairs")
    print(f"  Singletons: {n_singletons} books ({singleton_pct:.1f}%)  |  "
          f"{pair_singleton_pct:.1f}% of voter-book pairs are singletons")
    print(f"{'='*72}")

    # ── Protocol A ──
    n_total_loo = len(loo_trials)
    n_rec_loo   = n_total_loo - loo_unrec
    m_loo = compute_metrics(loo_trials, N)
    strat = m_loo["strat"]

    print(f"\n──── Protocol A: Leave-One-Out ({n_total_loo} trials) ────────────────────────────")
    print(f"  Unrecommendable: {loo_unrec}/{n_total_loo} ({100*loo_unrec/n_total_loo:.1f}%)  "
          f"← singletons + non-singletons with no co-voter overlap")
    print(f"  Recommendable trials: {n_rec_loo}")
    if n_rec_loo == 0:
        print("  (no recommendable trials)")
    else:
        bins_ordered = ["n=1", "n=2-5", "n=6-20", "n=21+"]
        hdr  = f"  {'':27}  {'Overall':>8}"
        for b in bins_ordered:
            hdr += f"  {b:>7}"
        print(hdr)

        def strat_cell(b):
            if b not in strat: return "     --"
            r, cnt = strat[b]
            return f" {100*r:5.1f}%"

        def fmt_metric(label, val_overall, key):
            row = f"  {label:<27}  {100*val_overall:>7.1f}%"
            for b in bins_ordered:
                row += strat_cell(b) if key == "r10" else "       "
            return row

        # Recall@10 (with stratification)
        strat_row = f"  {'Recall@10 [LEADING]:':27}  {100*m_loo['recall_10']:>7.1f}%"
        for b in bins_ordered:
            strat_row += strat_cell(b)
        print(strat_row)

        # Recall@25
        strat25 = compute_metrics(loo_trials, N)   # recomputed for @25 stratification
        strat25_d = m_loo["strat"]
        row25 = f"  {'Recall@25:':27}  {100*m_loo['recall_25']:>7.1f}%"
        for b in bins_ordered:
            if b in strat25_d:
                # recompute @25 per bin
                bin_trials = [t for t in loo_trials
                              if t["recommendable"] and popularity_bin(t["n_voters"]) == b]
                if bin_trials:
                    h25 = sum(1 for t in bin_trials
                              if t["rank"] is not None and t["rank"] <= 25) / len(bin_trials)
                    row25 += f" {100*h25:5.1f}%"
                else:
                    row25 += "      --"
            else:
                row25 += "      --"
        print(row25)

        print(f"  {'RW-Recall@10:':27}  {100*m_loo['rw_recall_10']:>7.1f}%"
              f"  ← rarity-weighted; higher = model surfaces distinctive books")
        print(f"  {'RW-Recall@25:':27}  {100*m_loo['rw_recall_25']:>7.1f}%")
        print(f"  {'MRR:':27}  {m_loo['mrr']:>8.4f}")
        print()
        print("  Popularity-stratified Recall@10 (n=1 excluded = always unrecommendable):")
        for b in bins_ordered:
            if b in strat:
                r, cnt = strat[b]
                note = "  (unrecommendable, excluded)" if b == "n=1" else ""
                print(f"    {b:>8}: {100*r:5.1f}%  ({cnt} trials){note}")
            else:
                print(f"    {b:>8}: --  (no trials)")

    # ── Protocol B ──
    print(f"\n──── Protocol B: Retained-Input Curve ({NUM_DRAWS} draws/voter, K=1..8) ────────")
    print(f"  {'K':>2}  {'Trials':>7}  {'Unrec%':>7}  "
          f"{'R@10':>7}  {'R@25':>7}  {'RW-R@10':>8}  {'MRR':>6}  "
          f"  held-out composition")

    for K in K_RANGE:
        if K not in curve:
            continue
        trials_k, unrec_k = curve[K]
        n_total_k = len(trials_k)
        n_rec_k   = n_total_k - unrec_k
        m_k = compute_metrics(trials_k, N)

        if n_total_k == 0:
            continue
        unrec_pct = 100 * unrec_k / n_total_k

        # Composition of held-out books (all trials, not just recommendable)
        comp_bins = defaultdict(int)
        for t in trials_k:
            comp_bins[popularity_bin(t["n_voters"])] += 1
        comp_str = "  ".join(f"{b}:{100*comp_bins.get(b,0)/n_total_k:.0f}%" for b in ["n=1","n=2-5","n=6-20","n=21+"])

        if m_k["recall_10"] is not None:
            print(f"  {K:>2}  {n_total_k:>7}  {unrec_pct:>6.1f}%  "
                  f"{100*m_k['recall_10']:>6.1f}%  {100*m_k['recall_25']:>6.1f}%  "
                  f"{100*m_k['rw_recall_10']:>7.1f}%  {m_k['mrr']:>6.4f}  "
                  f"  {comp_str}")
        else:
            print(f"  {K:>2}  {n_total_k:>7}  {unrec_pct:>6.1f}%  (no recommendable trials)")

    # ── Differentiation diagnostic ──
    print(f"\n──── Differentiation Diagnostic (informational, NOT a tuning target) ──────")
    print(f"  Mean top-10 overlap between 20 random voter pairs: {100*diff_diag:.1f}%")
    print(f"  Uses full model (production context). Anti-popularity signal is")
    print(f"  already captured by rarity-weighted recall above.")

    # ── Harness validation summary ──
    print(f"\n──── Harness Validation Summary ─────────────────────────────────────────")
    loo_r10 = m_loo["recall_10"] if m_loo["recall_10"] is not None else 0.0
    ratio = loo_r10 / random_r10 if random_r10 > 0 else float("inf")
    ok = "✓" if loo_r10 > random_r10 * 2 else "⚠"
    print(f"  Random baseline R@10: {100*random_r10:.2f}%  "
          f"|  Model R@10: {100*loo_r10:.1f}%  ({ratio:.1f}× above random)  {ok}")
    print(f"  (See full validation output above for spot-checks and unrecommendable check.)")


# ── Embedding harness ─────────────────────────────────────────────────────────

def _is_zero_vec(vec):
    import numpy as np
    return np.allclose(vec, 0)


def run_embedding_validation(voter_books, book_info, book_list, book_idx, fold_vecs, d):
    """Four embedding-specific validation checks."""
    import numpy as np
    from embeddings import embed_query, rank_by_embedding, build_embeddings

    N = len(voter_books)
    print("\n──── Embedding Harness Validation ──────────────────────────────────────")

    # 1. Random-vector baseline
    print("\n1. Random-vector baseline:")
    rng = np.random.default_rng(42)
    rnd_hits = rnd_total = 0
    voters_list = list(voter_books.keys())
    sample_v = voters_list[:min(200, len(voters_list))]
    for voter in sample_v:
        books_list = list(voter_books[voter])
        if len(books_list) < 2:
            continue
        h = books_list[0]
        inp = frozenset(b for b in books_list if b != h)
        n_h = book_info.get(h, {}).get("n_voters", 1)
        # Random unit vectors for this fold
        rnd_vecs = rng.standard_normal((len(book_list), d)).astype(np.float32)
        norms = np.linalg.norm(rnd_vecs, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        rnd_vecs /= norms
        q = embed_query(list(inp), rnd_vecs, book_idx, book_info, N=N)
        if q is None:
            continue
        ranked = rank_by_embedding(q, rnd_vecs, book_list, inp, top_n=50)
        rank = rank_of(ranked, h)
        rnd_hits += 1 if (rank is not None and rank <= 10) else 0
        rnd_total += 1
    rnd_r10 = rnd_hits / rnd_total if rnd_total else 0.0
    ok = "✓" if rnd_r10 < 0.05 else "⚠"
    print(f"   Random-vector R@10: {100*rnd_r10:.2f}%  (expected ~0.83%)  {ok}")

    # 2. Singletons remain zero-vector
    print("\n2. Singleton zero-vector check:")
    confidence_man = "K:cc83b0188ed4"
    kennedy = "A.L. Kennedy"
    if kennedy in fold_vecs and confidence_man in book_idx:
        cm_vec = fold_vecs[kennedy][book_idx[confidence_man]]
        is_zero = _is_zero_vec(cm_vec)
        print(f"   '{book_info.get(confidence_man,{}).get('title','The Confidence-Man')}' "
              f"(n=1) in {kennedy} fold: zero_vector={is_zero}  {'✓' if is_zero else '✗'}")
    else:
        print("   A.L. Kennedy or The Confidence-Man not found — skip.")

    # 3. Newly-reachable books (structural win proof)
    print("\n3. Newly-reachable books (structural win):")
    btv = build_book_to_voters(voter_books)
    found = False
    for voter in list(voter_books.keys())[:len(voter_books)]:
        if found:
            break
        vb = list(voter_books[voter])
        fold_v = fold_vecs[voter]
        for h in vb:
            inp = frozenset(b for b in vb if b != h)
            n_h = book_info.get(h, {}).get("n_voters", 1)
            if n_h < 2:
                continue  # skip singletons
            # Check if unrecommendable under old co-occurrence harness
            if is_recommendable(btv, voter_books, voter, inp, h):
                continue  # was recommendable; not a structural win case
            # Check if now reachable with embedding
            h_idx = book_idx.get(h)
            if h_idx is None or _is_zero_vec(fold_v[h_idx]):
                continue  # still zero-vector
            q = embed_query(list(inp), fold_v, book_idx, book_info, N=N)
            if q is None:
                continue
            ranked = rank_by_embedding(q, fold_v, book_list, inp, top_n=200)
            rank = rank_of(ranked, h)
            if rank is not None:
                title = book_info.get(h, {}).get("title", h)
                print(f"   Voter: {voter}")
                print(f"   Book:  '{title}' (n_voters={n_h})")
                print(f"   Previously unrecommendable (no co-voter of '{title}' shares "
                      f"any input book with {voter})")
                print(f"   Embedding rank: {rank}  ✓  (now reachable via latent proximity)")
                found = True
                break
    if not found:
        # Count total newly-reachable
        newly_reachable = 0
        total_non_singletons = 0
        for voter in voter_books:
            vb = list(voter_books[voter])
            fold_v = fold_vecs[voter]
            for h in vb:
                n_h = book_info.get(h, {}).get("n_voters", 1)
                if n_h < 2:
                    continue
                total_non_singletons += 1
                inp = frozenset(b for b in vb if b != h)
                if is_recommendable(btv, voter_books, voter, inp, h):
                    continue
                h_idx = book_idx.get(h)
                if h_idx is not None and not _is_zero_vec(fold_v[h_idx]):
                    newly_reachable += 1
        print(f"   No single example shown (scan complete).")
        print(f"   Newly-reachable trials (non-singleton, co-occ-disconnected, "
              f"non-zero-vector): {newly_reachable}/{total_non_singletons}")

    # 4. Per-fold rebuild excludes the right voter
    print("\n4. Per-fold rebuild excludes test voter:")
    # Find a book with n_voters=2
    target_book = target_voter = co_voter = None
    for cid, info in book_info.items():
        if info["n_voters"] == 2:
            owners = list(btv.get(cid, []))
            if len(owners) == 2:
                target_book, target_voter, co_voter = cid, owners[0], owners[1]
                break
    if target_book:
        title = book_info[target_book].get("title", target_book)
        # Fold excluding target_voter: co_voter still contributes → non-zero
        vec_excl_tv = fold_vecs[target_voter][book_idx[target_book]]
        # Fold excluding co_voter: target_voter still contributes → non-zero
        vec_excl_cv = fold_vecs[co_voter][book_idx[target_book]]
        # Rebuild excluding BOTH owners: no one contributes → zero vector
        # Build a modified voter_books that excludes both owners
        vbooks_neither = {v: b for v, b in voter_books.items()
                          if v != target_voter and v != co_voter}
        vecs_excl_both = build_embeddings(vbooks_neither, book_list, d)
        vec_excl_both = vecs_excl_both[book_idx[target_book]]
        non_zero_tv   = not _is_zero_vec(vec_excl_tv)
        non_zero_cv   = not _is_zero_vec(vec_excl_cv)
        zero_both     = _is_zero_vec(vec_excl_both)
        ok_tv   = "✓" if non_zero_tv else "✗"
        ok_cv   = "✓" if non_zero_cv else "✗"
        ok_both = "✓" if zero_both   else "✗"
        print(f"   '{title}' (n=2, owners: {target_voter[:20]} / {co_voter[:20]})")
        print(f"   Fold excl. {target_voter[:20]}: non-zero? {non_zero_tv}  {ok_tv}")
        print(f"   Fold excl. {co_voter[:20]}: non-zero? {non_zero_cv}  {ok_cv}")
        print(f"   Rebuild excl. BOTH owners: zero vector? {zero_both}  {ok_both}")
    else:
        print("   No n=2 book found — skip.")


def run_embedding_loo(voter_books, book_info, book_list, book_idx, fold_vecs,
                      input_rarity, N):
    """Protocol A for embedding model: leave-one-out with per-fold SVD rebuild."""
    from embeddings import embed_query, rank_by_embedding

    trials     = []
    n_zero_vec = 0

    for voter, books in voter_books.items():
        fold_v = fold_vecs[voter]
        books_list = list(books)
        for h in books_list:
            input_ids = [b for b in books_list if b != h]
            n_h = book_info.get(h, {}).get("n_voters", 1)

            h_idx = book_idx.get(h)
            if h_idx is None or _is_zero_vec(fold_v[h_idx]):
                n_zero_vec += 1
                # Still counted in denominator (conservative, honest)
                trials.append({"recommendable": True, "rank": None, "n_voters": n_h})
                continue

            q = embed_query(input_ids, fold_v, book_idx, book_info,
                            input_rarity_weight=input_rarity, N=N)
            if q is None:
                n_zero_vec += 1
                trials.append({"recommendable": True, "rank": None, "n_voters": n_h})
                continue

            ranked = rank_by_embedding(q, fold_v, book_list,
                                        frozenset(input_ids), top_n=TOP_BOOKS)
            r = rank_of(ranked, h)
            trials.append({"recommendable": True, "rank": r, "n_voters": n_h})

    return trials, n_zero_vec


def run_embedding_curve(voter_books, book_info, book_list, book_idx, fold_vecs,
                        input_rarity, N, k_range=K_RANGE, num_draws=NUM_DRAWS):
    """Protocol B for embedding model: retained-input curve K=1..8."""
    from embeddings import embed_query, rank_by_embedding

    curve = {}
    for K in k_range:
        trials     = []
        n_zero_vec = 0

        for voter, books in voter_books.items():
            fold_v    = fold_vecs[voter]
            books_list = list(books)
            if len(books_list) <= K:
                continue

            for _ in range(num_draws):
                input_ids  = random.sample(books_list, K)
                held_out   = [b for b in books_list if b not in set(input_ids)]
                inp_set    = frozenset(input_ids)

                q = embed_query(input_ids, fold_v, book_idx, book_info,
                                input_rarity_weight=input_rarity, N=N)
                ranked = [] if q is None else rank_by_embedding(
                    q, fold_v, book_list, inp_set, top_n=TOP_BOOKS)

                for h in held_out:
                    n_h = book_info.get(h, {}).get("n_voters", 1)
                    h_idx = book_idx.get(h)
                    if h_idx is None or _is_zero_vec(fold_v[h_idx]) or q is None:
                        n_zero_vec += 1
                        trials.append({"recommendable": True, "rank": None,
                                       "n_voters": n_h})
                        continue
                    r = rank_of(ranked, h)
                    trials.append({"recommendable": True, "rank": r,
                                   "n_voters": n_h})

        curve[K] = (trials, n_zero_vec)

    return curve


def compute_reconstruction_recall(voter_books, book_info, book_list, book_idx,
                                   fold_vecs, full_vecs, input_rarity, N,
                                   n_sample=200, seed=0):
    """
    Overfitting guard: compare training (full-model) vs LOO recall@10 on the
    SAME recoverable subset — (voter, held_out) pairs where h has n_voters≥2
    (non-zero-vector after fold exclusion). Comparing on this subset ensures
    the gap measures overfitting, not the structural singleton penalty.
    """
    from embeddings import embed_query, rank_by_embedding

    rng = random.Random(seed)
    voters_list = list(voter_books.keys())

    # Build the recoverable-subset sample
    sample_pairs = []
    for voter in voters_list:
        vb = list(voter_books[voter])
        for h in vb:
            if book_info.get(h, {}).get("n_voters", 1) >= 2:
                sample_pairs.append((voter, h))

    rng.shuffle(sample_pairs)
    sample_pairs = sample_pairs[:n_sample]

    train_hits = loo_hits = total = 0

    for voter, h in sample_pairs:
        vb = list(voter_books[voter])
        inp = [b for b in vb if b != h]
        inp_set = frozenset(inp)
        n_h = book_info.get(h, {}).get("n_voters", 1)

        # Training (full) recall
        q_full = embed_query(inp, full_vecs, book_idx, book_info,
                              input_rarity_weight=input_rarity, N=N)
        if q_full is not None:
            ranked_full = rank_by_embedding(q_full, full_vecs, book_list,
                                             inp_set, top_n=TOP_BOOKS)
            r_full = rank_of(ranked_full, h)
            train_hits += 1 if (r_full is not None and r_full <= 10) else 0

        # LOO recall
        fold_v = fold_vecs[voter]
        h_idx = book_idx.get(h)
        if h_idx is not None and not _is_zero_vec(fold_v[h_idx]):
            q_loo = embed_query(inp, fold_v, book_idx, book_info,
                                input_rarity_weight=input_rarity, N=N)
            if q_loo is not None:
                ranked_loo = rank_by_embedding(q_loo, fold_v, book_list,
                                                inp_set, top_n=TOP_BOOKS)
                r_loo = rank_of(ranked_loo, h)
                loo_hits += 1 if (r_loo is not None and r_loo <= 10) else 0

        total += 1

    if total == 0:
        return 0.0, 0.0
    return train_hits / total, loo_hits / total


def print_embedding_panel(d, input_rarity, loo_trials, n_zero_vec,
                          curve, train_r10, loo_r10_recov, N, book_info):
    """Print the embedding evaluation panel."""
    n_total = len(loo_trials)
    m_loo   = compute_metrics(loo_trials, N)

    print(f"\n{'='*72}")
    print(f"  Embedding Evaluation  |  d={d}  input_rarity={input_rarity}")
    print(f"  PPMI+SVD  |  342 voters  |  1209 books  |  3525 voter-book pairs")
    print(f"  Zero-vector in LOO: {n_zero_vec}/{n_total} ({100*n_zero_vec/n_total:.1f}%)"
          f"  ← singletons of test voter; all others get vectors")
    print(f"{'='*72}")

    gap = train_r10 - loo_r10_recov
    print(f"\n  Overfitting check (recoverable subset, n_voters≥2):")
    print(f"    Training R@10 (full model): {100*train_r10:.1f}%")
    print(f"    LOO R@10     (per-fold):    {100*loo_r10_recov:.1f}%")
    print(f"    Gap:                        {gap*100:+.1f}pp  "
          f"{'[small = good generalization]' if gap < 0.10 else '[widening = check for overfitting]'}")

    # Protocol A
    print(f"\n──── Protocol A: Leave-One-Out ({n_total} trials, all in denominator) ───────")
    if m_loo["recall_10"] is None:
        print("  (no trials)")
    else:
        bins_ordered = ["n=1", "n=2-5", "n=6-20", "n=21+"]
        strat = m_loo["strat"]

        hdr = f"  {'':33}  {'Overall':>8}"
        for b in bins_ordered:
            hdr += f"  {b:>7}"
        print(hdr)

        # Recall@10 with stratification
        row = f"  {'Recall@10 [LEADING]:':33}  {100*m_loo['recall_10']:>7.1f}%"
        for b in bins_ordered:
            row += f" {100*strat[b][0]:5.1f}%" if b in strat else "      --"
        print(row)

        # Recall@25 with stratification
        row25 = f"  {'Recall@25:':33}  {100*m_loo['recall_25']:>7.1f}%"
        for b in bins_ordered:
            bt = [t for t in loo_trials if t["recommendable"]
                  and popularity_bin(t["n_voters"]) == b]
            if bt:
                h25 = sum(1 for t in bt
                          if t["rank"] is not None and t["rank"] <= 25) / len(bt)
                row25 += f" {100*h25:5.1f}%"
            else:
                row25 += "      --"
        print(row25)

        print(f"  {'RW-Recall@10 [PRIMARY TUNING TARGET]:':33}  "
              f"{100*m_loo['rw_recall_10']:>7.1f}%")
        print(f"  {'RW-Recall@25:':33}  {100*m_loo['rw_recall_25']:>7.1f}%")
        print(f"  {'MRR:':33}  {m_loo['mrr']:>8.4f}")

        print()
        print("  Popularity-stratified Recall@10:")
        for b in bins_ordered:
            if b in strat:
                r, cnt = strat[b]
                print(f"    {b:>8}: {100*r:5.1f}%  ({cnt} trials)")
            else:
                print(f"    {b:>8}: --  (no trials)")

    # Protocol B
    print(f"\n──── Protocol B: Retained-Input Curve ({NUM_DRAWS} draws, K=1..8) ────────")
    print(f"  {'K':>2}  {'Trials':>7}  {'ZeroVec%':>9}  "
          f"{'R@10':>7}  {'R@25':>7}  {'RW-R@10':>8}  {'MRR':>6}  "
          f"  held-out composition")

    for K in K_RANGE:
        if K not in curve:
            continue
        trials_k, zero_k = curve[K]
        n_total_k = len(trials_k)
        if n_total_k == 0:
            continue
        m_k = compute_metrics(trials_k, N)
        zero_pct = 100 * zero_k / n_total_k

        comp_bins = defaultdict(int)
        for t in trials_k:
            comp_bins[popularity_bin(t["n_voters"])] += 1
        comp_str = "  ".join(
            f"{b}:{100*comp_bins.get(b,0)/n_total_k:.0f}%"
            for b in ["n=1","n=2-5","n=6-20","n=21+"])

        if m_k["recall_10"] is not None:
            print(f"  {K:>2}  {n_total_k:>7}  {zero_pct:>8.1f}%  "
                  f"{100*m_k['recall_10']:>6.1f}%  {100*m_k['recall_25']:>6.1f}%  "
                  f"{100*m_k['rw_recall_10']:>7.1f}%  {m_k['mrr']:>6.4f}  "
                  f"  {comp_str}")
        else:
            print(f"  {K:>2}  {n_total_k:>7}  {zero_pct:>8.1f}%  (no trials)")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Evaluation harness for Kindred Lists.")
    parser.add_argument("--alpha",         type=float, default=COOC_INPUT_EXP,
                        help=f"Input rarity exponent α (default: {COOC_INPUT_EXP})")
    parser.add_argument("--gamma",         type=float, default=COOC_OUTPUT_EXP,
                        help=f"Output rarity exponent γ (default: {COOC_OUTPUT_EXP})")
    parser.add_argument("--validate-only", action="store_true",
                        help="Run validation checks only, skip full protocols")
    parser.add_argument("--seed",          type=int,   default=0,
                        help="Random seed for reproducible draws (default: 0)")
    # Embedding flags
    parser.add_argument("--embed",         action="store_true",
                        help="Run embedding (PPMI+SVD) evaluation instead of co-occurrence")
    parser.add_argument("--d",             type=int,   default=30,
                        help="SVD dimensionality (default: 30)")
    parser.add_argument("--input-rarity",  type=float, default=0.0,
                        help="Input rarity weighting for query centroid (default: 0.0 = plain centroid)")
    args = parser.parse_args()

    random.seed(args.seed)
    alpha, gamma = args.alpha, args.gamma

    print(f"Loading model…", flush=True)
    model       = load_model()
    voter_books = model.voter_books
    book_info   = model.book_info
    N           = model.n_voters

    # Dataset statistics
    n_books       = len(book_info)
    n_pairs       = sum(len(b) for b in voter_books.values())
    n_singletons  = sum(1 for info in book_info.values() if info["n_voters"] == 1)
    singleton_pct = 100 * n_singletons / n_books
    sing_in_pairs = sum(1 for books in voter_books.values()
                        for b in books if book_info.get(b,{}).get("n_voters",0) == 1)
    pair_sing_pct = 100 * sing_in_pairs / n_pairs

    if args.embed:
        # ── Embedding path ─────────────────────────────────────────────────────
        from embeddings import build_embeddings

        d            = args.d
        input_rarity = args.input_rarity

        # Fixed sorted book list (index ↔ cid)
        book_list = sorted(book_info.keys())
        book_idx  = {cid: i for i, cid in enumerate(book_list)}

        print(f"Building per-fold embeddings (d={d}, 342 folds)…", flush=True)
        fold_vecs = {}
        for i, voter in enumerate(voter_books.keys()):
            if (i+1) % 50 == 0:
                print(f"  fold {i+1}/342…", flush=True)
            fold_vecs[voter] = build_embeddings(voter_books, book_list, d,
                                                exclude_voter=voter)

        # Validation always runs first
        run_embedding_validation(voter_books, book_info, book_list, book_idx,
                                  fold_vecs, d)

        if args.validate_only:
            return

        # Full embeddings (for reconstruction recall / overfitting guard)
        print("\nBuilding full embeddings (no exclusion)…", flush=True)
        full_vecs = build_embeddings(voter_books, book_list, d)

        print("\nRunning embedding Protocol A (leave-one-out)…", flush=True)
        loo_trials, n_zero_vec = run_embedding_loo(
            voter_books, book_info, book_list, book_idx, fold_vecs, input_rarity, N)

        print(f"Running embedding Protocol B (K=1..8, {NUM_DRAWS} draws)…", flush=True)
        curve = run_embedding_curve(
            voter_books, book_info, book_list, book_idx, fold_vecs,
            input_rarity, N)

        print("Computing overfitting guard (reconstruction recall)…", flush=True)
        train_r10, loo_r10_recov = compute_reconstruction_recall(
            voter_books, book_info, book_list, book_idx,
            fold_vecs, full_vecs, input_rarity, N)

        print_embedding_panel(d, input_rarity, loo_trials, n_zero_vec,
                               curve, train_r10, loo_r10_recov, N, book_info)

    else:
        # ── Co-occurrence path (original harness) ───────────────────────────
        run_validation_checks(model, alpha, gamma, book_info)

        if args.validate_only:
            return

        print(f"\nRunning Protocol A (α={alpha}, γ={gamma})…", flush=True)
        loo_trials, loo_unrec = run_protocol_a(model, alpha, gamma)

        print(f"Running Protocol B (K=1..8, {NUM_DRAWS} draws)…", flush=True)
        curve = run_protocol_b(model, alpha, gamma)

        print("Running differentiation diagnostic…", flush=True)
        diff = run_differentiation_diagnostic(model, alpha, gamma)

        print("Running random baseline…", flush=True)
        rand_r10 = run_random_baseline(model)

        print_panel(
            alpha=alpha, gamma=gamma,
            n_voters_total=N, n_books=n_books, n_pairs=n_pairs,
            n_singletons=n_singletons, singleton_pct=singleton_pct,
            pair_singleton_pct=pair_sing_pct,
            loo_trials=loo_trials, loo_unrec=loo_unrec,
            curve=curve, diff_diag=diff, random_r10=rand_r10,
            book_info_frozen=book_info,
        )


if __name__ == "__main__":
    main()
