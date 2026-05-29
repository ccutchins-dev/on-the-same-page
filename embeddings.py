"""
embeddings.py — PPMI+SVD book embedding builder for Kindred Lists.

Constructs dense book vectors from voter-list co-occurrence data via:
  1. Co-occurrence matrix: C[a,b] = number of voter lists containing both a and b
  2. PPMI: max(0, log2(P(a,b) / (P(a)·P(b))))  — popularity-corrected, noise-clamped
  3. Truncated SVD: book vectors = U[:,0:d] × diag(s[0:d])  (left singular vecs × sigmas)
  4. L2-normalise each vector so cosine similarity = dot product

Design decisions recorded in DECISIONS.md:
  - PPMI (not raw counts): bakes in popularity correction; positive clamp drops high-
    variance negative PMI at this extreme sparsity (88.6% of pairs appear exactly once).
  - No add-k smoothing: at this density smoothing uniformly lowers PMI without changing
    relative ordering.
  - Left singular vectors × singular values: standard "semantic space" representation;
    discarding the singular values (using U only) would lose magnitude information.
  - ARPACK truncated SVD (scipy.sparse.linalg.svds): O(nnz × d × iter), far cheaper
    than full O(n³) SVD. Works directly on the sparse PPMI matrix.
  - L2-normalization: makes cosine similarity = dot product; required for efficient
    inner-product retrieval.

Singletons in per-fold rebuilds: a book whose only voter is the excluded voter has a
zero co-occurrence row → assigned a zero vector. All other books are guaranteed a
non-zero vector (they co-occur with their listmates from the remaining voters).
"""

import math
from itertools import combinations

import numpy as np
from scipy.sparse import lil_matrix, csr_matrix
from scipy.sparse.linalg import svds


# ── Co-occurrence matrix ──────────────────────────────────────────────────────

def build_cooc(voter_books, book_list, exclude_voter=None):
    """
    Build symmetric co-occurrence matrix from voter lists.

    C[i, j] = number of voter lists containing both book_list[i] and book_list[j].
    exclude_voter: skip this voter's list (for leak-free per-fold evaluation).

    Returns: scipy.sparse.csr_matrix of shape (n, n) where n = len(book_list).
    """
    book_idx = {cid: i for i, cid in enumerate(book_list)}
    n = len(book_list)
    mat = lil_matrix((n, n), dtype=np.float32)

    for voter, books in voter_books.items():
        if voter == exclude_voter:
            continue
        # books is a frozenset; get indices for books that are in book_list
        idxs = sorted(book_idx[b] for b in books if b in book_idx)
        for i, j in combinations(idxs, 2):
            mat[i, j] += 1.0
            mat[j, i] += 1.0

    return mat.tocsr()


# ── PPMI ──────────────────────────────────────────────────────────────────────

def compute_ppmi(cooc_csr):
    """
    Compute Positive Pointwise Mutual Information from a co-occurrence matrix.

    PMI(a,b) = log2(C(a,b) · C_total / (C_row(a) · C_row(b)))
    PPMI(a,b) = max(0, PMI(a,b))

    Returns: scipy.sparse.csr_matrix (same shape, non-negative entries).
    """
    mat = cooc_csr.astype(np.float64)
    C_total = mat.sum()
    if C_total == 0:
        return mat  # no co-occurrences (empty fold)

    row_sums = np.asarray(mat.sum(axis=1)).ravel()  # C_row(a)

    # Work on the COO form to vectorise the PMI computation
    coo = mat.tocoo()
    rows, cols, data = coo.row, coo.col, coo.data.copy()

    # PMI(a,b) = log2(data * C_total / (row_sums[a] * row_sums[b]))
    denom = row_sums[rows] * row_sums[cols]
    valid = denom > 0
    pmi = np.zeros_like(data)
    pmi[valid] = np.log2(data[valid] * C_total / denom[valid])

    # Positive clamp
    ppmi_data = np.maximum(pmi, 0.0)
    keep = ppmi_data > 0

    from scipy.sparse import csr_matrix as _csr
    result = _csr(
        (ppmi_data[keep], (rows[keep], cols[keep])),
        shape=mat.shape,
        dtype=np.float64,
    )
    return result


# ── Truncated SVD + L2 normalisation ─────────────────────────────────────────

def _l2_norm_rows(X):
    """L2-normalise each row; zero rows stay zero."""
    norms = np.linalg.norm(X, axis=1, keepdims=True)
    norms[norms == 0] = 1.0   # avoid divide-by-zero for zero vectors
    return X / norms


def build_embeddings(voter_books, book_list, d, exclude_voter=None):
    """
    Build L2-normalised book embeddings of dimensionality d.

    Parameters
    ----------
    voter_books : dict[str, frozenset[str]]
    book_list   : list[str]  — all canonical_ids in a fixed sorted order
    d           : int        — embedding dimensionality
    exclude_voter : str | None  — voter to exclude (per-fold leak prevention)

    Returns
    -------
    vectors : np.ndarray of shape (len(book_list), d)
        Row i corresponds to book_list[i].
        Zero vector for books with no co-occurrences after exclusion.
    """
    cooc  = build_cooc(voter_books, book_list, exclude_voter)
    ppmi  = compute_ppmi(cooc)

    n = len(book_list)
    actual_d = min(d, n - 1)   # svds requires k < min(m, n)

    if ppmi.nnz == 0:
        # No co-occurrences at all (e.g. only 1 voter and they were excluded)
        return np.zeros((n, actual_d), dtype=np.float32)

    # Truncated SVD: U (n × d), s (d,), Vt (d × n)
    # svds returns smallest singular values by default; sort descending
    try:
        U, s, _ = svds(ppmi, k=actual_d)
    except Exception:
        # Fallback: if ARPACK fails (e.g. nearly-rank-1 matrix), use dense SVD
        dense = ppmi.toarray()
        U_full, s_full, _ = np.linalg.svd(dense, full_matrices=False)
        U, s = U_full[:, :actual_d], s_full[:actual_d]

    # Sort descending (svds returns in ascending order)
    order = np.argsort(-s)
    U, s = U[:, order], s[order]

    # Book vectors = U × diag(s)
    vectors = U * s[np.newaxis, :]   # broadcast: (n, d) * (1, d)

    # Preserve zero rows (books with no co-occurrences) as zero vectors
    zero_rows = np.asarray(ppmi.sum(axis=1)).ravel() == 0
    vectors[zero_rows] = 0.0

    # L2-normalise non-zero rows
    vectors = _l2_norm_rows(vectors).astype(np.float32)
    vectors[zero_rows] = 0.0  # ensure zero rows stay exactly zero after norm

    return vectors


# ── Query construction ────────────────────────────────────────────────────────

def embed_query(input_cids, vectors, book_idx, book_info,
                input_rarity_weight=0.0, N=342):
    """
    Build a query vector from a list of input canonical_ids.

    input_rarity_weight=0 → plain centroid (equal weights).
    input_rarity_weight>0 → rarity-weighted centroid: each input book's vector
        is weighted by raw_idf(n_i)^rarity_weight where raw_idf = log((N+1)/(n+1)).

    Returns: L2-normalised query vector (float32), or None if all inputs are zero-vector.
    """
    vecs, weights = [], []
    for cid in input_cids:
        i = book_idx.get(cid)
        if i is None:
            continue
        v = vectors[i]
        if np.allclose(v, 0):
            continue   # skip zero-vector input books
        nv = book_info.get(cid, {}).get("n_voters", 1)
        if input_rarity_weight != 0.0:
            w = math.log((N + 1) / (nv + 1)) ** input_rarity_weight
        else:
            w = 1.0
        vecs.append(v)
        weights.append(w)

    if not vecs:
        return None

    q = np.average(vecs, axis=0, weights=weights).astype(np.float32)
    norm = np.linalg.norm(q)
    if norm < 1e-9:
        return None
    return q / norm


# ── Ranking ───────────────────────────────────────────────────────────────────

def rank_by_embedding(query_vec, vectors, book_list, input_cids, top_n=50):
    """
    Rank all books by cosine similarity to query_vec (= dot product after L2-norm).
    Excludes input_cids and zero-vector books.

    Returns: list of cids, length ≤ top_n, sorted by similarity descending.
    """
    if query_vec is None:
        return []

    exclude = set(input_cids)
    sims = vectors.dot(query_vec)   # (n,) cosine similarities

    # Build (sim, cid) candidates excluding inputs and zero-vectors
    candidates = []
    for i, cid in enumerate(book_list):
        if cid in exclude:
            continue
        if np.allclose(vectors[i], 0):
            continue
        candidates.append((sims[i], cid))

    candidates.sort(reverse=True)
    return [cid for _, cid in candidates[:top_n]]
