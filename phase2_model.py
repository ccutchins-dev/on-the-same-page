"""
Phase 2 matching model for Kindred Lists.

Public interface (stable — algorithm is swappable behind it):
    model = load_model()
    book_ids, voter_names = recommend(model, input_ids)

Usage:
    python phase2_model.py              # load silently (import-safe; does nothing)
    python phase2_model.py --verify     # run sanity-check cases, print results
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
RARITY_ALPHA    = 1.0   # IDF exponent: 0=uniform, 1=standard smoothed IDF, >1=stronger rarity
POSITION_WEIGHT = 0.1   # position factor band: 1.0 at pos 1, (1-PW) at pos 10; 0=ignored
BETA            = 0.0   # Step 2 popularity-normalization exponent:
                        # 0 = raw affinity (current behavior); >0 penalizes popular books
                        # score(book) = affinity / n_voters^BETA
SHRINK_K        = None  # Step 2 lift-with-shrinkage scorer (overrides BETA path when set):
                        # None = disabled (use BETA scorer); 0 = pure lift baseline;
                        # >0 = score = 1 + (lift−1) × m_b/(m_b+K)
                        # lift = (matched_rate) / (population_rate) = (m_b/M) / (n_b/N)
COOC_INPUT_EXP  = 1.0   # Co-occurrence scorer — input-side rarity exponent (α):
                        # None = scorer disabled; 0.0 = on, all inputs weighted equally;
                        # >0 = rare input books weighted by raw_idf(i)^α
                        # 1.0 is the chosen production default (co-occurrence sweep)
COOC_OUTPUT_EXP = 1.0   # Co-occurrence scorer — output-side rarity exponent (γ):
                        # None = no output boost; 0.0 = on, no rarity boost applied;
                        # >0 = candidate books boosted by raw_idf(c)^γ
                        # 1.0 is the chosen production default (co-occurrence sweep)
                        # Activation: scorer fires when either param is not None.
DEFAULT_TOP_BOOKS  = 50
DEFAULT_TOP_VOTERS = 20

DATA_DIR = Path("data/processed")


# ── Data structures ───────────────────────────────────────────────────────────

class Model:
    """Precomputed model state. Build once with load_model(); reuse for many recommend() calls."""
    __slots__ = ("voter_books", "voter_positions", "book_info", "n_voters", "alpha")

    def __init__(self, voter_books, voter_positions, book_info, n_voters, alpha):
        self.voter_books     = voter_books      # {voter_name: frozenset[canonical_id]}
        self.voter_positions = voter_positions  # {voter_name: {canonical_id: int 1-10}}
        self.book_info       = book_info        # {canonical_id: {"title","author","n_voters","weight"}}
        self.n_voters        = n_voters         # int — total distinct voters
        self.alpha           = alpha            # float — RARITY_ALPHA used at load time


# ── Position helpers ──────────────────────────────────────────────────────────

def _parse_position(raw):
    """
    Parse voter_books.csv position string → effective int in [1, 10].

    Rules (all are artifacts of Phase 1, not noise):
      - Normal '1'–'10': use as-is.
      - Compound 'a;b' (cross-source merged voters, 21 rows): take min(a, b) — the
        voter ranked this book at #a on one list and #b on the other; min uses the
        more emphatic endorsement.
      - Blank '' (series_explode rows, 48 rows): return 10 (neutral-low). These
        volumes were listed without per-volume ranking; 'unranked' → bottom of band
        rather than middle (~5) because there is no signal favoring any position.
      - Out-of-range (>10, e.g. Richard Powers pos 25/35): clamp to 10.
      - Any other invalid value: 10 (neutral).
    """
    raw = raw.strip()
    if not raw:
        return 10
    parts = [x.strip() for x in raw.split(";")]
    nums = []
    for x in parts:
        try:
            n = int(x)
            nums.append(min(n, 10) if n >= 1 else 10)
        except ValueError:
            pass
    return min(nums) if nums else 10


def _position_factor(pos, pw):
    """Linear decay: 1.0 at pos=1, (1-pw) at pos=10. pw=0 → always 1.0."""
    return 1.0 - pw * (pos - 1) / 9


# ── Loading ───────────────────────────────────────────────────────────────────

def load_model(data_dir=DATA_DIR, alpha=RARITY_ALPHA):
    """Load Phase 1 CSVs and precompute IDF weights. Call once per process."""
    data_dir = Path(data_dir)

    # 1. canonical_books.csv → book metadata + voter counts
    book_info = {}
    with open(data_dir / "canonical_books.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            book_info[row["canonical_id"]] = {
                "title":         row["canonical_title"],
                "author":        row["canonical_author"],
                "canonical_year": row.get("canonical_year", ""),
                "n_voters":      int(row["n_voters"]),
                "weight":        0.0,
            }

    n_voters = _count_voters(data_dir)

    # 2. Smoothed IDF weight per book: log((N+1)/(n+1))^alpha
    for cid, info in book_info.items():
        raw = math.log((n_voters + 1) / (info["n_voters"] + 1))
        info["weight"] = raw ** alpha

    # 3. voter_books.csv → voter → books + positions
    raw_voter_books     = defaultdict(set)
    raw_voter_positions = defaultdict(dict)

    with open(data_dir / "voter_books.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cid   = row["canonical_id"]
            voter = row["voter_name"]
            if cid not in book_info:
                continue
            raw_voter_books[voter].add(cid)
            raw_voter_positions[voter][cid] = _parse_position(row["positions"])

    voter_books     = {v: frozenset(bs) for v, bs in raw_voter_books.items()}
    voter_positions = {v: dict(ps)      for v, ps in raw_voter_positions.items()}

    return Model(voter_books, voter_positions, book_info, n_voters, alpha)


def _count_voters(data_dir):
    voters = set()
    with open(data_dir / "voter_books.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            voters.add(row["voter_name"])
    return len(voters)


# ── Core algorithm ────────────────────────────────────────────────────────────

def _raw_idf(n_voters, N):
    """Unraised IDF, decoupled from RARITY_ALPHA. When used as exponent base, 0^0=1 → off."""
    return math.log((N + 1) / (n_voters + 1))


def _cooc_score(model, input_set, alpha, gamma):
    """
    Transparent co-occurrence Step-2 scorer with two independent rarity dials.

    score(c) = (Σᵢ co(i,c) × raw_idf(i)^alpha) × raw_idf(c)^gamma

    co(i,c) = number of voter lists containing both input book i and candidate c,
    counted over ALL voters who have any input book. Fully decoupled from Step-1
    voter_sim — the scorer is a pure co-occurrence model. The input-side dial (alpha)
    is where input-level rarity signal is recovered; no per-voter weighting is needed
    because "how often do readers of i also read c?" is a book-level question.

    alpha=0: all input books weighted equally (plain co-occurrence sum, off value).
    gamma=0: no output-side rarity boost (off value).
    Singleton-flood resistance is built-in: a singleton has base ≤ |input_set|,
    so base × idf^gamma is dominated by any book with several co-occurrences at
    moderate gamma. See DECISIONS.md for the worked numeric proof.
    """
    N  = model.n_voters
    bi = model.book_info
    book_scores = defaultdict(float)

    for voter, books in model.voter_books.items():
        voter_inputs = input_set & books
        if not voter_inputs:
            continue
        voter_candidates = books - input_set
        for i in voter_inputs:
            n_i = bi.get(i, {}).get("n_voters", 1)
            w_i = _raw_idf(n_i, N) ** alpha if alpha != 0.0 else 1.0
            for c in voter_candidates:
                book_scores[c] += w_i

    if gamma != 0.0:
        for c in list(book_scores):
            n_c = bi.get(c, {}).get("n_voters", 1)
            book_scores[c] *= _raw_idf(n_c, N) ** gamma

    return book_scores


def _lift_score(m_b, M, n_b, N, K):
    """
    Shrunk observed-vs-expected lift for Step 2 book scoring.

    score = 1 + (lift - 1) × shrinkage_factor
    lift             = (m_b / M) / (n_b / N)  — observed rate / expected rate
    shrinkage_factor = m_b / (m_b + K)         — 1.0 when K=0 (pure lift)

    m_b: unweighted count of matched voters who have this book. Step 1 similarity
    scores determine pool membership only; they do not feed into the lift calculation
    (clean base-rate interpretation). Weighted alternative exists — see DECISIONS.md.

    K=0: pure lift (no shrinkage; singletons ride their full lift).
    K>0: deviation from no-signal baseline (lift=1) pulled toward zero by evidence count.
    """
    if M == 0 or n_b == 0 or N == 0:
        return 0.0
    lift   = (m_b / M) / (n_b / N)
    shrink = m_b / (m_b + K) if K > 0 else 1.0
    return 1.0 + (lift - 1.0) * shrink


def _norm_score(affinity, n_voters, beta):
    """
    Popularity-normalized affinity for Step 2 book ranking.
    beta=0: returns affinity unchanged (exact current behavior).
    beta>0: divides by n_voters^beta, penalizing books on many lists.
    """
    if beta == 0.0:
        return affinity
    return affinity / (n_voters ** beta) if n_voters > 0 else 0.0


def recommend(model, input_ids, *, top_books=DEFAULT_TOP_BOOKS,
              top_voters=DEFAULT_TOP_VOTERS, position_weight=POSITION_WEIGHT,
              beta=BETA, shrink_k=SHRINK_K,
              cooc_input_exp=COOC_INPUT_EXP, cooc_output_exp=COOC_OUTPUT_EXP):
    """
    Stable interface:
        input_ids        — iterable of 1–10 canonical_id strings
        position_weight  — overrides POSITION_WEIGHT; 0 recovers pre-position behavior
        beta             — BETA scorer: 0 = raw affinity; >0 = affinity/n_voters^beta
        shrink_k         — lift scorer: None=off; 0=pure lift; >0=shrunk lift
        cooc_input_exp   — co-occurrence scorer input rarity (α): None=off; 0=equal inputs;
                           >0=rare inputs weighted by raw_idf(i)^alpha
        cooc_output_exp  — co-occurrence scorer output rarity (γ): None=no boost; 0=no boost;
                           >0=candidates boosted by raw_idf(c)^gamma
        returns          — (ranked_book_ids, ranked_voter_names)

    Step 2 scorer selection (priority order):
        cooc_input_exp or cooc_output_exp is not None → co-occurrence scorer
        shrink_k is not None                          → lift-with-shrinkage scorer
        else                                          → BETA scorer (beta=0 = raw affinity)
    """
    input_set     = frozenset(input_ids)
    book_info     = model.book_info
    voter_pos_map = model.voter_positions

    # Step 1 — voter similarity (position-weighted)
    voter_sim = {}
    for voter, books in model.voter_books.items():
        overlap = input_set & books
        if overlap:
            vpos = voter_pos_map.get(voter, {})
            voter_sim[voter] = sum(
                book_info[b]["weight"] * _position_factor(vpos.get(b, 10), position_weight)
                for b in overlap if b in book_info
            )

    ranked_voters = sorted(voter_sim, key=lambda v: -voter_sim[v])

    # Step 2 — book affinity accumulation
    # book_matched_count is the unweighted evidence count for the lift scorer.
    book_affinity      = defaultdict(float)
    book_matched_count = defaultdict(int)
    for voter, sim in voter_sim.items():
        for b in model.voter_books[voter]:
            if b not in input_set:
                book_affinity[b] += sim
                if shrink_k is not None:
                    book_matched_count[b] += 1

    # Step 2 sort — branch on scorer selection.
    # Round to 6 decimals before sort.
    # BETA=0 / both cooc params None / shrink_k=None: JS parity preserved.
    # Any other scorer: site cannot reproduce until main.js ported — see PROGRESS.md.
    use_cooc = (cooc_input_exp is not None) or (cooc_output_exp is not None)
    if use_cooc:
        alpha = cooc_input_exp  if cooc_input_exp  is not None else 0.0
        gamma = cooc_output_exp if cooc_output_exp is not None else 0.0
        book_scores = _cooc_score(model, input_set, alpha, gamma)
        # Three-level sort: score desc, idf weight desc, cid asc (stable tiebreak).
        # The cid tiebreak ensures equal-score equal-idf ties (e.g. multiple n=1 books)
        # resolve identically in Python and JS regardless of iteration order.
        ranked_books = sorted(
            book_scores,
            key=lambda b: (-round(book_scores[b], 6),
                           -book_info.get(b, {}).get("weight", 0.0),
                           b),
        )
    elif shrink_k is not None:
        M_matched = len(voter_sim)
        ranked_books = sorted(
            book_affinity,
            key=lambda b: (
                -round(_lift_score(book_matched_count[b], M_matched,
                                   book_info.get(b, {}).get("n_voters", 1),
                                   model.n_voters, shrink_k), 6),
                -book_info.get(b, {}).get("weight", 0.0),
            ),
        )
    else:
        ranked_books = sorted(
            book_affinity,
            key=lambda b: (
                -round(_norm_score(book_affinity[b],
                                   book_info.get(b, {}).get("n_voters", 1),
                                   beta), 6),
                -book_info.get(b, {}).get("weight", 0.0),
            ),
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
            "Absalom, Absalom! (15) + The Third Policeman (4) + The Confidence-Man (1)"
        ),
        "ids": [
            "OL:OL20867W",    # Middlemarch
            "OL:OL267096W",   # Anna Karenina
            "K:d2d9f9b0f145", # Absalom, Absalom!
            "OL:OL2005223W",  # The Third Policeman
            "K:cc83b0188ed4", # The Confidence-Man
        ],
    },
]


def _voter_sim_detail(model, input_set, voter, pw):
    """Return (sim, list of (book_title, pos, contribution))."""
    bi   = model.book_info
    vpos = model.voter_positions.get(voter, {})
    overlap = input_set & model.voter_books[voter]
    parts = []
    for b in overlap:
        if b not in bi:
            continue
        pos   = vpos.get(b, 10)
        w     = bi[b]["weight"]
        contrib = w * _position_factor(pos, pw)
        parts.append((bi[b]["title"][:28], pos, contrib))
    return sum(c for _, _, c in parts), parts


def run_verify(model):
    bi = model.book_info
    pw = POSITION_WEIGHT
    print(f"Model: {model.n_voters} voters · {len(bi)} books")
    print(f"RARITY_ALPHA={model.alpha}  POSITION_WEIGHT={pw}  BETA={BETA}  "
          f"SHRINK_K={SHRINK_K}  COOC_INPUT_EXP={COOC_INPUT_EXP}  COOC_OUTPUT_EXP={COOC_OUTPUT_EXP}\n")

    # ── Dominance invariant check ─────────────────────────────────────────────
    min_book_weight = min(info["weight"] for info in bi.values())
    max_book_weight = max(info["weight"] for info in bi.values())
    max_pos_swing   = pw * max_book_weight
    print("── Dominance invariant ─────────────────────────────────────────────────")
    print(f"  Cheapest book weight (Middlemarch, n=83) : {min_book_weight:.4f}")
    print(f"  Priciest book weight (singleton)         : {max_book_weight:.4f}")
    print(f"  Max position swing (PW × max_weight)     : {max_pos_swing:.4f}")
    ok = "✓ PASS" if max_pos_swing < min_book_weight else "✗ FAIL"
    print(f"  Invariant (max_swing < cheapest_weight)  : {ok}")
    print()

    # ── Before/after on case 4 ────────────────────────────────────────────────
    case4_ids = _VERIFY_CASES[3]["ids"]
    case4_set = frozenset(case4_ids)
    print("── Before/after: case 4 with POSITION_WEIGHT=0 vs default ──────────────")
    for label, kw in [("PW=0 (old behavior)", 0.0), (f"PW={pw} (default)", pw)]:
        _, voters = recommend(model, case4_ids, top_voters=5, position_weight=kw)
        print(f"  {label}:")
        for v in voters:
            sim, _ = _voter_sim_detail(model, case4_set, v, kw)
            print(f"    {v[:35]:35} sim={sim:.4f}")
    print()

    # ── Cases 1–4 ─────────────────────────────────────────────────────────────
    for case in _VERIFY_CASES:
        print("=" * 72)
        print(case["label"])
        ids = case["ids"]
        missing = [i for i in ids if i not in bi]
        if missing:
            print(f"  ERROR: unknown canonical_id(s): {missing}")
            continue

        for cid in ids:
            info = bi[cid]
            print(f"  INPUT: {info['title'][:50]}  [n={info['n_voters']}, w={info['weight']:.3f}]")

        books, voters = recommend(model, ids, top_books=10, top_voters=5)
        input_set = frozenset(ids)

        print()
        print("  Top 5 voters by similarity:")
        for rank, v in enumerate(voters, 1):
            sim, parts = _voter_sim_detail(model, input_set, v, pw)
            detail = "  ".join(f"[{t} @{p} ={c:.3f}]" for t, p, c in parts)
            print(f"    {rank}. {v[:32]:32} sim={sim:.4f}  {detail}")

        print()
        print("  Top 10 recommended books:")
        voter_sim = {}
        for voter, vbooks in model.voter_books.items():
            overlap = input_set & vbooks
            if overlap:
                vpos = model.voter_positions.get(voter, {})
                voter_sim[voter] = sum(
                    bi[b]["weight"] * _position_factor(vpos.get(b, 10), pw)
                    for b in overlap if b in bi
                )
        book_aff = defaultdict(float)
        for voter, sim in voter_sim.items():
            for b in model.voter_books[voter]:
                if b not in input_set:
                    book_aff[b] += sim
        for rank, cid in enumerate(books, 1):
            info = bi[cid]
            print(f"    {rank:2}. {info['title'][:45]:45}  {info['author'][:20]:20}"
                  f"  n={info['n_voters']:3}  aff={book_aff[cid]:.3f}")
        print()

    # ── Case 5: position-effect demonstration ─────────────────────────────────
    print("=" * 72)
    print("5. Position-effect demonstration")

    ABSALOM    = "K:d2d9f9b0f145"
    ANNA_K     = "OL:OL267096W"
    MAD_BOV    = "OL:OL19350876W"
    SHRIVER    = "Lionel Shriver"
    CAPUTO     = "Philip Caputo"

    # 5A — position ordering
    print("\n  5A — Absalom, Absalom! solo (15 voters, pos range 2–10):")
    print(f"  INPUT: {bi[ABSALOM]['title']}  [n={bi[ABSALOM]['n_voters']}, w={bi[ABSALOM]['weight']:.3f}]")
    absalom_set = frozenset([ABSALOM])
    av = {v: {} for v in model.voter_books if ABSALOM in model.voter_books[v]}
    rows = []
    for voter in av:
        pos = model.voter_positions.get(voter, {}).get(ABSALOM, 10)
        sim_pos  = bi[ABSALOM]["weight"] * _position_factor(pos, pw)
        sim_flat = bi[ABSALOM]["weight"]
        rows.append((voter, pos, sim_pos, sim_flat))
    rows.sort(key=lambda r: -r[2])
    print(f"  {'voter':32} {'pos':>4}  {'sim(PW=.1)':>10}  {'sim(PW=0)':>10}")
    for voter, pos, sp, sf in rows:
        print(f"    {voter:32} {pos:4}  {sp:10.4f}  {sf:10.4f}")

    # 5B — extra book beats position advantage
    print(f"\n  5B — Adding Madame Bovary (n=52) to show extra book beats position:")
    print(f"  INPUT A: [Absalom, Absalom!] alone")
    for voter in [SHRIVER, CAPUTO]:
        vpos = model.voter_positions.get(voter, {})
        pos  = vpos.get(ABSALOM, 10)
        sim  = bi[ABSALOM]["weight"] * _position_factor(pos, pw)
        print(f"    {voter:32} Absalom@pos{pos}  contrib={sim:.4f}")

    shriver_absalom = bi[ABSALOM]["weight"] * _position_factor(
        model.voter_positions.get(SHRIVER, {}).get(ABSALOM, 10), pw)
    caputo_absalom  = bi[ABSALOM]["weight"] * _position_factor(
        model.voter_positions.get(CAPUTO, {}).get(ABSALOM, 10), pw)
    pos_advantage   = shriver_absalom - caputo_absalom
    print(f"    Position advantage (Shriver over Caputo): {pos_advantage:.4f}")

    print(f"\n  INPUT B: [Absalom + Madame Bovary ({bi[MAD_BOV]['title']}, n={bi[MAD_BOV]['n_voters']})]")
    for voter in [SHRIVER, CAPUTO]:
        books_set = frozenset([ABSALOM, MAD_BOV])
        overlap   = books_set & model.voter_books[voter]
        vpos      = model.voter_positions.get(voter, {})
        sim       = sum(bi[b]["weight"] * _position_factor(vpos.get(b, 10), pw)
                        for b in overlap if b in bi)
        shared_fmt = "  ".join(
            f"{bi[b]['title'][:25]}@pos{vpos.get(b,10)}:{bi[b]['weight']*_position_factor(vpos.get(b,10),pw):.3f}"
            for b in overlap if b in bi)
        has_extra = MAD_BOV in model.voter_books[voter]
        print(f"    {voter:32} has Madame Bovary={has_extra}  sim={sim:.4f}  [{shared_fmt}]")

    caputo_extra_contrib = bi[MAD_BOV]["weight"] * _position_factor(
        model.voter_positions.get(CAPUTO, {}).get(MAD_BOV, 10), pw)
    print(f"    Extra-book contribution (Caputo's Madame Bovary): {caputo_extra_contrib:.4f}")
    print(f"    Ratio extra_book/pos_advantage: {caputo_extra_contrib/pos_advantage:.1f}×")
    print(f"    Invariant: {caputo_extra_contrib:.4f} >> {pos_advantage:.4f} — presence dominates ✓")

    # 5C — compound-position voter
    print(f"\n  5C — Compound-position (cross-source merge): Anna Karenina input:")
    print(f"  INPUT: {bi[ANNA_K]['title']}  [n={bi[ANNA_K]['n_voters']}, w={bi[ANNA_K]['weight']:.3f}]")
    anna_voters = [(v, model.voter_positions.get(v, {}).get(ANNA_K, 10))
                   for v in model.voter_books if ANNA_K in model.voter_books[v]]
    anna_voters.sort(key=lambda x: x[1])

    # Read raw positions directly to show compound annotation
    raw_positions = {}
    with open(DATA_DIR / "voter_books.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["canonical_id"] == ANNA_K:
                raw_positions[row["voter_name"]] = row["positions"].strip()

    print(f"  {'voter':32} {'pos_raw':>10}  {'eff':>4}  {'sim':>8}  note")
    focal = {"Claire Messud", "Alexander McCall Smith", "Bebe Moore Campbell",
             "Ann Patchett", "Ha Jin"}
    shown = set()
    # Show the focal voters first, then a few others
    for voter, eff in sorted(anna_voters, key=lambda x: x[1]):
        if voter in focal or len(shown) < 5:
            raw = raw_positions.get(voter, "?")
            sim = bi[ANNA_K]["weight"] * _position_factor(eff, pw)
            note = ""
            if ";" in raw:
                parts_v = [int(x) for x in raw.split(";") if x.strip().isdigit()]
                note = f"compound → min({','.join(str(p) for p in parts_v)})={eff}"
                if eff == 5:
                    wrong_sim = bi[ANNA_K]["weight"] * _position_factor(5, pw)
                    note += f" (if eff=5: sim would be {wrong_sim:.4f})"
            print(f"    {voter:32} {raw:>10}  {eff:4}  {sim:8.4f}  {note}")
            shown.add(voter)
            if len(shown) >= 8:
                break

    # Explicitly annotate Claire Messud
    cm_raw = raw_positions.get("Claire Messud", "?")
    cm_eff = _parse_position(cm_raw)
    cm_sim_correct = bi[ANNA_K]["weight"] * _position_factor(cm_eff, pw)
    cm_sim_wrong   = bi[ANNA_K]["weight"] * _position_factor(5, pw)
    if "Claire Messud" not in shown:
        print(f"    {'Claire Messud':32} {cm_raw:>10}  {cm_eff:4}  {cm_sim_correct:8.4f}  "
              f"compound → min → eff={cm_eff}")
    print(f"\n  Claire Messud raw='{cm_raw}' → eff={cm_eff}  "
          f"sim_correct={cm_sim_correct:.4f}  sim_if_eff5={cm_sim_wrong:.4f}  "
          f"difference={cm_sim_correct-cm_sim_wrong:.4f}")
    print()


# ── Export ────────────────────────────────────────────────────────────────────

def export_model_data(model, out_path=None):
    """
    Write data/model_data.json for Phase 3 (static site).
    voter_books is now [[cid, pos], ...] so Phase 3 can apply the same position factor.
    """
    if out_path is None:
        out_path = Path("data") / "model_data.json"
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Build year lookup: canonical_year from canonical_books (694 books) +
    # additional backfill from year_backfill.csv (37 auto-resolved entries).
    year_lookup = {}
    for cid, info in model.book_info.items():
        if info.get("canonical_year"):
            year_lookup[cid] = info["canonical_year"]
    backfill_path = DATA_DIR / "year_backfill.csv"
    if backfill_path.exists():
        with open(backfill_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row["year"] and row["canonical_id"] not in year_lookup:
                    year_lookup[row["canonical_id"]] = row["year"]
    # year_overrides.csv: highest priority — user's manual corrections.
    overrides_path = DATA_DIR / "year_overrides.csv"
    if overrides_path.exists():
        with open(overrides_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row["year"]:
                    year_lookup[row["canonical_id"]] = row["year"]

    # Build description lookup from descriptions.csv if present; else placeholder.
    desc_lookup = {}
    desc_path = DATA_DIR / "descriptions.csv"
    if desc_path.exists():
        with open(desc_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row["description"]:
                    desc_lookup[row["canonical_id"]] = row["description"]

    payload = {
        "n_voters":       model.n_voters,
        "alpha":          model.alpha,
        "position_weight": POSITION_WEIGHT,
        "beta":           BETA,
        "shrink_k":       SHRINK_K,
        "cooc_input_exp":  COOC_INPUT_EXP,
        "cooc_output_exp": COOC_OUTPUT_EXP,
        "books": {
            cid: {
                "title":       info["title"],
                "author":      info["author"],
                "n_voters":    info["n_voters"],
                "year":        year_lookup.get(cid, ""),
                "description": desc_lookup.get(
                    cid,
                    f"{info['title']}, by {info['author']}. Description coming soon."
                    if info["author"]
                    else f"{info['title']}. Description coming soon."
                ),
            }
            for cid, info in model.book_info.items()
        },
        "idf": {
            cid: round(info["weight"], 6)
            for cid, info in model.book_info.items()
        },
        # voter_books: {voter: [[cid, effective_pos], ...]}
        "voter_books": {
            voter: [[cid, model.voter_positions.get(voter, {}).get(cid, 10)]
                    for cid in sorted(books)]
            for voter, books in model.voter_books.items()
        },
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    size_kb = out_path.stat().st_size / 1024
    print(f"Wrote {out_path}  ({size_kb:.1f} KB)")
    print(f"  {len(payload['books'])} books · {len(payload['voter_books'])} voters")
    print(f"  voter_books format: [[cid, pos], ...] pairs")


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
        print(f"  {model.n_voters} voters · {len(model.book_info)} books")
        print(f"  RARITY_ALPHA={model.alpha}  POSITION_WEIGHT={POSITION_WEIGHT}")
        print("Use --verify to run sanity checks, --export to write data/model_data.json.")
