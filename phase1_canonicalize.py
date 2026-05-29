"""
Phase 1 canonicalization pipeline for Kindred Lists.

Usage:
    python phase1_canonicalize.py            # run pipeline
    python phase1_canonicalize.py --verify   # run + automated checks

Inputs (read-only):
    input_data/combined_voters.csv
    overrides/registries.json     (author_aliases, series_registry, drop_titles, manual_canonical)
    overrides/merge_decisions.csv (proposal_id, decision, note)

Outputs (data/processed/):
    canonical_books.csv     canonical_id -> title/author/year/n_voters
    voter_books.csv         voter_name x canonical_id (long form; deduped)
    review_flags.csv        proposals for human review
    row_to_canonical.csv    every raw row -> its canonical_id
"""

import argparse
import csv
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

INPUT_CSV  = Path("input_data/combined_voters.csv")
REGISTRIES = Path("overrides/registries.json")
DECISIONS  = Path("overrides/merge_decisions.csv")
OUT_DIR    = Path("data/processed")

FUNCTION_WORDS = frozenset(
    "of and the a an in to for on his her its at by with from as is was are were".split()
)

# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def _remove_diacritics(s):
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")

_CURLY_MAP   = str.maketrans("‘’“”′″", "''\"\"''")
_ABBREV_DOT  = re.compile(r'\b(mr|mrs|ms|dr|st|jr|sr)\.', re.I)
_LEADING_ART = re.compile(r'^(the|a|an)\s+', re.I)
_AMPERSAND   = re.compile(r'\s*&\s*')
_NON_ALNUM   = re.compile(r'[^a-z0-9]+')


def norm_title(raw):
    """Return (title_key, dropped_subtitle_or_None)."""
    s = unicodedata.normalize("NFKC", raw or "")
    s = s.translate(_CURLY_MAP)
    s = s.casefold()
    s = _remove_diacritics(s)
    s = _AMPERSAND.sub(" and ", s)
    subtitle = None
    if ":" in s:
        before, after = s.split(":", 1)
        subtitle = after.strip() or None
        s = before
    s = _LEADING_ART.sub("", s)
    s = _ABBREV_DOT.sub(lambda m: m.group(1).lower(), s)
    s = _NON_ALNUM.sub(" ", s)
    s = re.sub(r'\bgrey\b', 'gray', s)
    s = s.strip()
    return s, subtitle


def norm_author(raw):
    """Return (surname_key, full_key)."""
    s = unicodedata.normalize("NFKC", raw or "")
    s = s.translate(_CURLY_MAP)
    s = s.casefold()
    s = _remove_diacritics(s)
    s = re.sub(r'\(ed\.?\)|,\s*editors?|et al\.?', '', s, flags=re.I)
    s = _NON_ALNUM.sub(" ", s).strip()
    tokens = s.split()
    return (tokens[-1] if tokens else ""), s


def token_sort_ratio(a, b):
    return SequenceMatcher(None,
                           " ".join(sorted(a.split())),
                           " ".join(sorted(b.split()))).ratio()


_SHORT_NON_FUNC = re.compile(r'^[a-z0-9]{1,4}$')

def short_token_discriminator(key_a, key_b):
    diff = set(key_a.split()).symmetric_difference(set(key_b.split()))
    for t in diff:
        if _SHORT_NON_FUNC.match(t) and t not in FUNCTION_WORDS:
            return True
    return False


_COLLECTED_PAT = re.compile(
    r'^(?:the\s+)?(?:stories|story|poems|collected\s+stories|collected\s+poems|'
    r'selected\s+poems|plays|complete\s+stories|selected\s+stories|works)\s+of\s+(.+)$',
    re.I
)

def extract_collected_author(title):
    m = _COLLECTED_PAT.match(title.strip())
    return m.group(1).strip().rstrip(".") if m else None


# ---------------------------------------------------------------------------
# Stable IDs
# ---------------------------------------------------------------------------

def make_row_id(row):
    key = "|".join([row["source"], row["voter_name"], row["position"],
                    row["book_title"], row["book_author"]])
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def make_proposal_id(*parts):
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Union-Find
# ---------------------------------------------------------------------------

class UnionFind:
    def __init__(self):
        self._p = {}

    def find(self, x):
        if x not in self._p:
            self._p[x] = x
        while self._p[x] != x:
            self._p[x] = self._p[self._p[x]]
            x = self._p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._p[rb] = ra

    def groups(self):
        out = defaultdict(list)
        for x in self._p:
            out[self.find(x)].append(x)
        return dict(out)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def load_overrides():
    regs = {"author_aliases": {}, "series_registry": {},
            "manual_canonical": {}, "drop_titles": []}
    if REGISTRIES.exists():
        with open(REGISTRIES) as f:
            regs.update(json.load(f))
    decisions = {}
    if DECISIONS.exists():
        with open(DECISIONS, newline="") as f:
            for row in csv.DictReader(f):
                pid = row.get("proposal_id", "").strip()
                if pid:
                    decisions[pid] = row.get("decision", "").strip()
    return regs, decisions


def find_volume_cid(vtk, vsk, canonical_meta, norm_title_fn, norm_author_fn):
    """Find the canonical_id best matching (volume_title_key, author_surname_key)."""
    best_cid, best_n = None, -1
    for cid, cm in canonical_meta.items():
        if norm_title_fn(cm["canonical_title"])[0] == vtk:
            cm_sk = norm_author_fn(cm["canonical_author"])[0]
            n = cm.get("_n_rows", 0)
            if cm_sk == vsk and n > best_n:
                best_n, best_cid = n, cid
    if best_cid:
        return best_cid
    # Fallback: title only
    for cid, cm in canonical_meta.items():
        if norm_title_fn(cm["canonical_title"])[0] == vtk:
            n = cm.get("_n_rows", 0)
            if n > best_n:
                best_n, best_cid = n, cid
    return best_cid


def run(verify=False):
    regs, accepted_decisions = load_overrides()
    aliases     = regs["author_aliases"]
    series_reg  = {norm_title(k)[0]: v for k, v in regs["series_registry"].items()}
    drop_title_keys = {norm_title(t)[0] for t in regs.get("drop_titles", [])}

    # -----------------------------------------------------------------------
    # 1. Load rows
    # -----------------------------------------------------------------------
    rows = []
    with open(INPUT_CSV, newline="", encoding="utf-8") as f:
        for raw in csv.DictReader(f):
            rid = make_row_id(raw)
            tk, subtitle = norm_title(raw["book_title"])
            surname, full_auth = norm_author(raw["book_author"])
            surname = aliases.get(surname, surname)
            rows.append({**raw, "row_id": rid, "title_key": tk,
                         "subtitle": subtitle, "surname_key": surname,
                         "full_auth_key": full_auth})
    row_by_id = {r["row_id"]: r for r in rows}

    # -----------------------------------------------------------------------
    # 2. Union-Find: T0 OLID → T1/T2 exact (title+author) → T1b blank-author
    # -----------------------------------------------------------------------
    uf = UnionFind()
    for r in rows:
        uf.find(r["row_id"])

    # T0: shared OLID
    olid_groups = defaultdict(list)
    for r in rows:
        if r["openLibraryId"].strip():
            olid_groups[r["openLibraryId"].strip()].append(r["row_id"])
    for ids in olid_groups.values():
        for rid in ids[1:]:
            uf.union(ids[0], rid)

    # T1/T2: exact (title_key, surname_key) — both non-blank
    exact_groups = defaultdict(list)
    for r in rows:
        if r["title_key"] and r["surname_key"]:
            exact_groups[(r["title_key"], r["surname_key"])].append(r["row_id"])
    for ids in exact_groups.values():
        for rid in ids[1:]:
            uf.union(ids[0], rid)

    # T1b: blank-author rows share title_key → merge together
    blank_title_groups = defaultdict(list)
    for r in rows:
        if not r["surname_key"] and r["title_key"]:
            blank_title_groups[r["title_key"]].append(r["row_id"])
    for ids in blank_title_groups.values():
        for rid in ids[1:]:
            uf.union(ids[0], rid)

    # -----------------------------------------------------------------------
    # 3. Detect multi-book slots
    # -----------------------------------------------------------------------
    slot_books = defaultdict(list)
    for r in rows:
        slot_books[(r["source"], r["voter_name"], r["position"])].append(r)
    multi_slots = {k: v for k, v in slot_books.items() if len(v) > 1}

    # -----------------------------------------------------------------------
    # 4. Generate proposals (T3–T6)  [canonical_map not yet built]
    # -----------------------------------------------------------------------
    proposals = []

    # T3: fuzzy title (same surname block)
    surname_blocks = defaultdict(list)
    for r in rows:
        if r["surname_key"]:
            surname_blocks[r["surname_key"]].append(r)

    seen_fuzzy = set()
    for surname, block in surname_blocks.items():
        seen_tk = {}
        for r in block:
            if r["title_key"] not in seen_tk:
                seen_tk[r["title_key"]] = r
        tks = list(seen_tk.keys())
        for i in range(len(tks)):
            for j in range(i + 1, len(tks)):
                a_tk, b_tk = tks[i], tks[j]
                ra = seen_tk[a_tk]["row_id"]
                rb = seen_tk[b_tk]["row_id"]
                if uf.find(ra) == uf.find(rb):
                    continue
                pair = tuple(sorted([a_tk, b_tk]))
                if pair in seen_fuzzy:
                    continue
                seen_fuzzy.add(pair)
                ratio = token_sort_ratio(a_tk, b_tk)
                if ratio < 0.90:
                    continue
                trap = short_token_discriminator(a_tk, b_tk)
                pid = make_proposal_id("T3", a_tk, b_tk, surname)
                proposals.append({
                    "proposal_id": pid,
                    "reason": "SHORT_TOKEN_DISCRIMINATOR" if trap else "FUZZY_TITLE",
                    "tier": "REJECT" if trap else "T3",
                    "left_row_id": ra, "left_title": seen_tk[a_tk]["book_title"],
                    "left_author": seen_tk[a_tk]["book_author"],
                    "left_olid": seen_tk[a_tk]["openLibraryId"],
                    "right_row_id": rb, "right_title": seen_tk[b_tk]["book_title"],
                    "right_author": seen_tk[b_tk]["book_author"],
                    "right_olid": seen_tk[b_tk]["openLibraryId"],
                    "similarity": f"{ratio:.3f}", "group_members": "",
                    "suggested_action": "reject" if trap else "review",
                    "decision": accepted_decisions.get(pid, "pending"),
                })

    # T4: author variant (same title_key, different non-blank surnames)
    title_blocks = defaultdict(list)
    for r in rows:
        if r["title_key"]:
            title_blocks[r["title_key"]].append(r)

    seen_auth = set()
    for tk, block in title_blocks.items():
        reps = {}
        for r in block:
            if r["surname_key"] and r["surname_key"] not in reps:
                reps[r["surname_key"]] = r
        surnames = sorted(reps.keys())
        for i in range(len(surnames)):
            for j in range(i + 1, len(surnames)):
                sa, sb = surnames[i], surnames[j]
                ra, rb = reps[sa]["row_id"], reps[sb]["row_id"]
                if uf.find(ra) == uf.find(rb):
                    continue
                pair = tuple(sorted([sa + "|" + tk, sb + "|" + tk]))
                if pair in seen_auth:
                    continue
                seen_auth.add(pair)
                edit = SequenceMatcher(None, sa, sb).ratio()
                pid = make_proposal_id("T4", tk, sa, sb)
                proposals.append({
                    "proposal_id": pid, "reason": "AUTHOR_VARIANT", "tier": "T4",
                    "left_row_id": ra, "left_title": reps[sa]["book_title"],
                    "left_author": reps[sa]["book_author"], "left_olid": reps[sa]["openLibraryId"],
                    "right_row_id": rb, "right_title": reps[sb]["book_title"],
                    "right_author": reps[sb]["book_author"], "right_olid": reps[sb]["openLibraryId"],
                    "similarity": f"{edit:.3f}", "group_members": "",
                    "suggested_action": "review",
                    "decision": accepted_decisions.get(pid, "pending"),
                })

    # T5: blank-author recovery
    seen_blank = set()
    for r in rows:
        if r["surname_key"] or r["title_key"] in seen_blank:
            continue
        seen_blank.add(r["title_key"])
        recovered = extract_collected_author(r["book_title"])
        reason = "BLANK_AUTHOR_RECOVERED" if recovered else "BLANK_AUTHOR_CANON"
        pid = make_proposal_id("T5", r["title_key"], reason)
        action = (f"set author to: {recovered}" if recovered
                  else "confirm as author-less canonical entry")
        proposals.append({
            "proposal_id": pid, "reason": reason, "tier": "T5",
            "left_row_id": r["row_id"], "left_title": r["book_title"],
            "left_author": "", "left_olid": r["openLibraryId"],
            "right_row_id": "", "right_title": "",
            "right_author": recovered or "", "right_olid": "",
            "similarity": "", "group_members": "",
            "suggested_action": action,
            "decision": accepted_decisions.get(pid, "pending"),
        })

    # T6a: multi-book slots
    seen_slots = set()
    for slot_key, slot_rows in multi_slots.items():
        source, voter, pos = slot_key
        titles = [r["book_title"] for r in slot_rows]
        containers = [r for r in slot_rows if r["title_key"] in series_reg]
        if containers:
            reason = "SERIES_EXPLODE"
            c = containers[0]
            entry = series_reg[c["title_key"]]
            action = (f"explode '{c['book_title']}' into volumes: "
                      + ", ".join(f"'{v}'" for v in entry["canonical_volumes"])
                      + "; other listed volumes remain as-is")
            rep_row = c
        else:
            reason = "MULTI_BOOK_SLOT"
            action = "each title is its own canonical book; confirm or classify"
            rep_row = slot_rows[0]
        pid = make_proposal_id("T6", source, voter, pos, "|".join(sorted(titles)))
        if pid in seen_slots:
            continue
        seen_slots.add(pid)
        proposals.append({
            "proposal_id": pid, "reason": reason, "tier": "T6",
            "left_row_id": rep_row["row_id"], "left_title": rep_row["book_title"],
            "left_author": rep_row["book_author"], "left_olid": rep_row["openLibraryId"],
            "right_row_id": "", "right_title": "", "right_author": "", "right_olid": "",
            "similarity": "", "group_members": " | ".join(titles),
            "suggested_action": action,
            "decision": accepted_decisions.get(pid, "pending"),
        })

    # T6b: standalone omnibus rows (single-book slots matching series_registry)
    for r in rows:
        if r["title_key"] not in series_reg:
            continue
        slot_key = (r["source"], r["voter_name"], r["position"])
        if slot_key in multi_slots:
            continue  # already covered by T6a
        pid = make_proposal_id("T6_standalone", r["row_id"], r["title_key"])
        if any(p["proposal_id"] == pid for p in proposals):
            continue
        entry = series_reg[r["title_key"]]
        action = ("standalone omnibus: explode into volumes: "
                  + ", ".join(f"'{v}'" for v in entry["canonical_volumes"]))
        proposals.append({
            "proposal_id": pid, "reason": "SERIES_EXPLODE", "tier": "T6",
            "left_row_id": r["row_id"], "left_title": r["book_title"],
            "left_author": r["book_author"], "left_olid": r["openLibraryId"],
            "right_row_id": "", "right_title": "", "right_author": "", "right_olid": "",
            "similarity": "", "group_members": r["book_title"],
            "suggested_action": action,
            "decision": accepted_decisions.get(pid, "pending"),
        })

    # -----------------------------------------------------------------------
    # 5. Apply accepted T3/T4 merges to union-find (pair-based accepts)
    # -----------------------------------------------------------------------
    for prop in proposals:
        if prop["decision"] == "accept" and prop["right_row_id"]:
            uf.union(prop["left_row_id"], prop["right_row_id"])

    # -----------------------------------------------------------------------
    # 6. Build canonical_map and raw canonical_meta
    # -----------------------------------------------------------------------
    groups = uf.groups()
    canonical_map   = {}
    canonical_meta  = {}

    for root, members in groups.items():
        member_rows = [row_by_id[rid] for rid in members]
        olids = sorted(set(r["openLibraryId"].strip() for r in member_rows
                           if r["openLibraryId"].strip()))
        if olids:
            cid = "OL:" + olids[0]
        else:
            tk_c = Counter(r["title_key"] for r in member_rows if r["title_key"])
            sk_c = Counter(r["surname_key"] for r in member_rows if r["surname_key"])
            rep_tk = tk_c.most_common(1)[0][0] if tk_c else "unknown"
            rep_sk = sk_c.most_common(1)[0][0] if sk_c else ""
            cid = "K:" + hashlib.sha1(f"{rep_tk}|{rep_sk}".encode()).hexdigest()[:12]

        # manual override
        for rid in members:
            if rid in regs["manual_canonical"]:
                cid = regs["manual_canonical"][rid]
                break

        olid_rows = [r for r in member_rows if r["openLibraryId"].strip()]
        title_pool = olid_rows if olid_rows else member_rows
        title_c  = Counter(r["book_title"] for r in title_pool)
        auth_c   = Counter(r["book_author"] for r in member_rows if r["book_author"].strip())
        year_c   = Counter(r["year"].strip() for r in member_rows
                           if re.match(r'^\d{4}$', r["year"].strip()))

        rep_title  = title_c.most_common(1)[0][0] if title_c else ""
        rep_author = auth_c.most_common(1)[0][0] if auth_c else ""
        rep_year   = year_c.most_common(1)[0][0] if year_c else ""

        for rid in members:
            canonical_map[rid] = cid
        canonical_meta[cid] = {
            "canonical_id": cid,
            "canonical_title": rep_title,
            "canonical_author": rep_author,
            "canonical_year": rep_year,
            "source_olids": ";".join(olids),
            "derived_from": "olid_anchor" if olids else "title_author_exact",
            "row_ids": members,
            "_n_rows": len(members),
        }

    # -----------------------------------------------------------------------
    # 7. NON_BOOK_ENTRY proposals (per canonical_id, keyed by title_key)
    # -----------------------------------------------------------------------
    seen_nonbook = set()
    for cid, cm in canonical_meta.items():
        tk = norm_title(cm["canonical_title"])[0]
        if tk not in drop_title_keys or tk in seen_nonbook:
            continue
        seen_nonbook.add(tk)
        rep_rid = cm["row_ids"][0]
        rep_row = row_by_id[rep_rid]
        pid = make_proposal_id("NON_BOOK", tk)
        proposals.append({
            "proposal_id": pid, "reason": "NON_BOOK_ENTRY", "tier": "T6",
            "left_row_id": rep_rid, "left_title": cm["canonical_title"],
            "left_author": cm["canonical_author"], "left_olid": rep_row["openLibraryId"],
            "right_row_id": "", "right_title": "", "right_author": "", "right_olid": "",
            "similarity": "", "group_members": cm["canonical_title"],
            "suggested_action": f"remove from dataset (non-book / un-enumerable container)",
            "decision": accepted_decisions.get(pid, "pending"),
        })

    # -----------------------------------------------------------------------
    # 8. Post-processing: build explode_ops, drop_cids, recovered_authors
    # -----------------------------------------------------------------------

    # Accepted SERIES_EXPLODE → (voter -> remove_cids, add_volume_cids)
    # We also need to know which slot rows belong to each proposal.
    voter_explode = defaultdict(lambda: [set(), set()])  # voter -> [remove, add]

    for prop in proposals:
        if prop["decision"] != "accept" or prop["reason"] != "SERIES_EXPLODE":
            continue
        left_rid = prop["left_row_id"]
        if left_rid not in row_by_id:
            continue
        left_row = row_by_id[left_rid]
        omnibus_tk = left_row["title_key"]
        if omnibus_tk not in series_reg:
            continue
        entry = series_reg[omnibus_tk]
        vsk = norm_author(entry.get("canonical_author", ""))[0]
        slot_key = (left_row["source"], left_row["voter_name"], left_row["position"])

        # All rows in this slot (or just the one row if standalone)
        slot_rows = multi_slots.get(slot_key, [left_row])

        # canonical_ids currently associated with these rows
        slot_cids = {canonical_map[r["row_id"]] for r in slot_rows}

        # Volume canonical_ids to add
        volume_cids = set()
        for vol_title in entry["canonical_volumes"]:
            vtk = norm_title(vol_title)[0]
            vcid = find_volume_cid(vtk, vsk, canonical_meta, norm_title, norm_author)
            if vcid:
                volume_cids.add(vcid)

        voter = left_row["voter_name"]
        voter_explode[voter][0].update(slot_cids)
        voter_explode[voter][1].update(volume_cids)

    # Accepted NON_BOOK_ENTRY + drop_titles → canonical_ids to drop
    drop_cids = set()
    for cid, cm in canonical_meta.items():
        if norm_title(cm["canonical_title"])[0] in drop_title_keys:
            drop_cids.add(cid)
    for prop in proposals:
        if prop["decision"] == "accept" and prop["reason"] == "NON_BOOK_ENTRY":
            rid = prop["left_row_id"]
            if rid in canonical_map:
                drop_cids.add(canonical_map[rid])

    # Accepted BLANK_AUTHOR_RECOVERED → canonical_id -> recovered_author
    recovered_authors = {}
    for prop in proposals:
        if prop["decision"] == "accept" and prop["reason"] == "BLANK_AUTHOR_RECOVERED":
            rid = prop["left_row_id"]
            if rid in canonical_map:
                cid = canonical_map[rid]
                recovered_authors[cid] = prop["right_author"]

    # Apply recovered_authors to canonical_meta
    for cid, auth in recovered_authors.items():
        if cid in canonical_meta:
            canonical_meta[cid]["canonical_author"] = auth

    # -----------------------------------------------------------------------
    # 9. Build voter_books with explodes and drops applied
    # -----------------------------------------------------------------------
    voter_books_raw = defaultdict(lambda: defaultdict(lambda: {
        "sources": set(), "positions": set(), "voter_types": set()
    }))
    for r in rows:
        cid = canonical_map[r["row_id"]]
        vb = voter_books_raw[r["voter_name"]][cid]
        vb["sources"].add(r["source"])
        vb["positions"].add(r["position"])
        vb["voter_types"].add(r["voter_type"])

    for voter, (remove_cids, add_cids) in voter_explode.items():
        for rcid in remove_cids:
            voter_books_raw[voter].pop(rcid, None)
        for acid in add_cids:
            if acid not in drop_cids:
                vb = voter_books_raw[voter][acid]
                vb["sources"].add("series_explode")

    for voter in list(voter_books_raw.keys()):
        for dcid in list(drop_cids):
            voter_books_raw[voter].pop(dcid, None)

    # -----------------------------------------------------------------------
    # 10. Recompute n_voters; filter orphaned (0-voter) canonical books
    # -----------------------------------------------------------------------
    cid_voters = defaultdict(set)
    for voter, books in voter_books_raw.items():
        for cid in books:
            cid_voters[cid].add(voter)

    # Remove canonical_ids that are now orphaned (exploded/dropped away entirely)
    canonical_meta = {cid: cm for cid, cm in canonical_meta.items()
                      if cid_voters.get(cid) and cid not in drop_cids}

    # -----------------------------------------------------------------------
    # 11. Write outputs
    # -----------------------------------------------------------------------
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    canon_sorted = sorted(canonical_meta.values(),
                          key=lambda x: -len(cid_voters[x["canonical_id"]]))
    with open(OUT_DIR / "canonical_books.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "canonical_id", "canonical_title", "canonical_author", "canonical_year",
            "n_rows", "n_voters", "source_olids", "derived_from"
        ])
        w.writeheader()
        for cm in canon_sorted:
            cid = cm["canonical_id"]
            w.writerow({
                "canonical_id": cid,
                "canonical_title": cm["canonical_title"],
                "canonical_author": cm["canonical_author"],
                "canonical_year": cm["canonical_year"],
                "n_rows": cm["_n_rows"],
                "n_voters": len(cid_voters[cid]),
                "source_olids": cm["source_olids"],
                "derived_from": cm["derived_from"],
            })

    with open(OUT_DIR / "voter_books.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "voter_name", "canonical_id", "sources", "positions", "voter_types"
        ])
        w.writeheader()
        for voter in sorted(voter_books_raw):
            for cid in sorted(voter_books_raw[voter]):
                if cid not in canonical_meta:
                    continue
                vb = voter_books_raw[voter][cid]
                w.writerow({
                    "voter_name": voter,
                    "canonical_id": cid,
                    "sources": ";".join(sorted(vb["sources"])),
                    "positions": ";".join(sorted(str(p) for p in vb["positions"])),
                    "voter_types": ";".join(sorted(t for t in vb["voter_types"] if t)),
                })

    with open(OUT_DIR / "review_flags.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "proposal_id", "reason", "tier", "status",
            "left_row_id", "left_title", "left_author", "left_olid",
            "right_row_id", "right_title", "right_author", "right_olid",
            "similarity", "group_members", "suggested_action", "decision"
        ])
        w.writeheader()
        for p in sorted(proposals, key=lambda x: (x["tier"], x["reason"], x["left_title"])):
            p["status"] = "applied" if p["decision"] == "accept" else p["decision"]
            w.writerow(p)

    with open(OUT_DIR / "row_to_canonical.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "row_id", "source", "voter_name", "position",
            "book_title", "book_author", "year", "openLibraryId",
            "canonical_id", "canonical_title"
        ])
        w.writeheader()
        for r in rows:
            cid = canonical_map[r["row_id"]]
            ct = canonical_meta.get(cid, {}).get("canonical_title", cid)
            w.writerow({
                "row_id": r["row_id"], "source": r["source"],
                "voter_name": r["voter_name"], "position": r["position"],
                "book_title": r["book_title"], "book_author": r["book_author"],
                "year": r["year"], "openLibraryId": r["openLibraryId"],
                "canonical_id": cid, "canonical_title": ct,
            })

    # -----------------------------------------------------------------------
    # 12. Count report
    # -----------------------------------------------------------------------
    n_pending  = sum(1 for p in proposals if p["decision"] == "pending")
    n_accepted = sum(1 for p in proposals if p["decision"] == "accept")
    n_rejected = sum(1 for p in proposals if p["decision"] == "reject")
    bridge_count = sum(
        1 for cid, cm in canonical_meta.items()
        if any(row_by_id[rid]["source"] == "Top Ten Books"
               for rid in cm["row_ids"] if rid in row_by_id)
        and any(row_by_id[rid]["source"] == "Guardian Top 100"
                for rid in cm["row_ids"] if rid in row_by_id)
    )
    print(f"Input rows   : {len(rows)}")
    print(f"Canonical bks: {len(canonical_meta)}")
    print(f"Cross-source : {bridge_count} canonical books span both sources")
    print(f"Review flags : {len(proposals)} total  "
          f"({n_pending} pending / {n_accepted} accepted / {n_rejected} rejected)")
    by_reason = Counter(p["reason"] for p in proposals)
    for r, c in sorted(by_reason.items()):
        d = Counter(p["decision"] for p in proposals if p["reason"] == r)
        print(f"  {r}: {c}  ({dict(d)})")

    # -----------------------------------------------------------------------
    # 13. Automated verification
    # -----------------------------------------------------------------------
    if not verify:
        return

    print("\n--- VERIFICATION ---")
    errors = []

    # Conservation: every raw row maps to exactly one canonical_id
    if len(canonical_map) != len(rows):
        errors.append(f"FAIL conservation: {len(canonical_map)} mapped vs {len(rows)} rows")
    else:
        print("PASS conservation (all rows mapped)")

    # No silent fuzzy: no cluster has multiple title_keys without an OLID or accepted override.
    # Build set of title_key pairs covered by accepted pair-based proposals (T3/T4).
    accepted_tk_pairs = set()
    for prop in proposals:
        if prop["decision"] == "accept" and prop.get("right_row_id"):
            lrid, rrid = prop["left_row_id"], prop["right_row_id"]
            ltk = row_by_id[lrid]["title_key"] if lrid in row_by_id else ""
            rtk = row_by_id[rrid]["title_key"] if rrid in row_by_id else ""
            if ltk != rtk:
                accepted_tk_pairs.add((min(ltk, rtk), max(ltk, rtk)))

    bad = 0
    for cid, cm in canonical_meta.items():
        mrows = [row_by_id[rid] for rid in cm["row_ids"] if rid in row_by_id]
        tkeys = sorted(set(r["title_key"] for r in mrows))
        olids = set(r["openLibraryId"].strip() for r in mrows if r["openLibraryId"].strip())
        if len(tkeys) > 1 and not olids:
            # Check whether every cross-title-key pair has an accepted proposal
            all_covered = all(
                (min(a, b), max(a, b)) in accepted_tk_pairs
                for i, a in enumerate(tkeys)
                for b in tkeys[i+1:]
            )
            if not all_covered:
                bad += 1
                if bad <= 3:
                    errors.append(f"SUSPECT cluster {cid}: title_keys={tkeys}")
    if bad:
        errors.append(f"FAIL no-silent-fuzzy: {bad} suspect clusters")
    else:
        print("PASS no-silent-fuzzy")

    # Trap regression: Mr. Bridge and Mrs. Bridge must differ
    mr  = [canonical_map[r["row_id"]] for r in rows if r["book_title"] == "Mr. Bridge"]
    mrs = [canonical_map[r["row_id"]] for r in rows if r["book_title"] == "Mrs. Bridge"]
    if mr and mrs and set(mr) & set(mrs):
        errors.append("FAIL trap: Mr. Bridge and Mrs. Bridge share a canonical_id")
    elif mr and mrs:
        print(f"PASS trap: Mr. Bridge ({mr[0]}) != Mrs. Bridge ({mrs[0]})")

    # No phantom omnibus: Rabbit Angstrom and A Rabbit Omnibus must not appear in canonical_books
    phantoms = [cid for cid, cm in canonical_meta.items()
                if norm_title(cm["canonical_title"])[0] in ("rabbit angstrom", "rabbit omnibus")]
    if phantoms:
        errors.append(f"FAIL phantom omnibus: {phantoms} still in canonical_books")
    else:
        print("PASS no phantom omnibus (Rabbit Angstrom / A Rabbit Omnibus gone)")

    # Cross-source bridge
    if bridge_count == 0:
        errors.append("FAIL bridge: no canonical books span both sources")
    else:
        print(f"PASS bridge: {bridge_count} books span both sources")

    # Translation OLIDs stay single
    for olid, label in [("OL1230613W", "Camus"), ("OL24156W", "Jekyll"),
                        ("OL151411W", "Alice"), ("OL15202030W", "Hunchback")]:
        hits = [cid for cid, cm in canonical_meta.items()
                if olid in cm["source_olids"].split(";")]
        if len(hits) != 1:
            errors.append(f"FAIL translation OLID {olid} ({label}): {len(hits)} clusters")
        else:
            print(f"PASS translation OLID {olid} ({label})")

    # Dorian Gray/Grey: should be ONE cluster
    dorian = [cid for cid, cm in canonical_meta.items()
              if "dorian" in norm_title(cm["canonical_title"])[0]]
    if len(dorian) > 1:
        errors.append(f"FAIL Dorian Gray/Grey still split: {dorian}")
    elif dorian:
        print(f"PASS Dorian Gray/Grey merged: {dorian[0]}")

    if errors:
        print("\nERRORS:")
        for e in errors:
            print(" ", e)
        sys.exit(1)
    else:
        print("\nAll checks passed.")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--verify", action="store_true")
    args = p.parse_args()
    run(verify=args.verify)


if __name__ == "__main__":
    main()
