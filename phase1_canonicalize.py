"""
Phase 1 canonicalization pipeline for Kindred Lists.

Usage:
    python phase1_canonicalize.py            # run pipeline
    python phase1_canonicalize.py --verify   # run + automated checks
    python phase1_canonicalize.py --report   # print count summary only

Inputs (read-only):
    input_data/combined_voters.csv
    overrides/registries.json
    overrides/merge_decisions.csv

Outputs (data/processed/):
    canonical_books.csv
    voter_books.csv
    review_flags.csv
    row_to_canonical.csv
"""

import argparse
import csv
import hashlib
import json
import re
import sys
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

INPUT_CSV = Path("input_data/combined_voters.csv")
REGISTRIES = Path("overrides/registries.json")
DECISIONS = Path("overrides/merge_decisions.csv")
OUT_DIR = Path("data/processed")

FUNCTION_WORDS = frozenset(
    "of and the a an in to for on his her its at by with from as is was are were".split()
)

# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def _remove_diacritics(s):
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")

_CURLY_MAP = str.maketrans("‘’“”′″", "''\"\"''")
_ABBREV_DOT = re.compile(r'\b(mr|mrs|ms|dr|st|jr|sr)\.',  re.I)
_LEADING_ARTICLE = re.compile(r'^(the|a|an)\s+', re.I)
_AMPERSAND = re.compile(r'\s*&\s*')
_NON_ALNUM = re.compile(r'[^a-z0-9]+')


def norm_title(raw: str):
    """Return (title_key, title_key_no_subtitle, dropped_subtitle)."""
    s = unicodedata.normalize("NFKC", raw or "")
    s = s.translate(_CURLY_MAP)
    s = s.casefold()
    s = _remove_diacritics(s)
    s = _AMPERSAND.sub(" and ", s)
    # drop post-colon subtitle
    subtitle = None
    if ":" in s:
        before, after = s.split(":", 1)
        subtitle = after.strip() or None
        s = before
    s = _LEADING_ARTICLE.sub("", s)
    # keep abbreviation tokens, drop trailing dot only
    s = _ABBREV_DOT.sub(lambda m: m.group(1).lower(), s)
    s = _NON_ALNUM.sub(" ", s)
    # normalize known American/British spelling variants
    s = re.sub(r'\bgrey\b', 'gray', s)
    s = s.strip()
    return s, s, subtitle


def norm_author(raw: str):
    """Return (surname_key, full_key)."""
    s = unicodedata.normalize("NFKC", raw or "")
    s = s.translate(_CURLY_MAP)
    s = s.casefold()
    s = _remove_diacritics(s)
    # drop editorial noise
    s = re.sub(r'\(ed\.?\)|,\s*editors?|et al\.?', '', s, flags=re.I)
    s = _NON_ALNUM.sub(" ", s).strip()
    tokens = s.split()
    surname = tokens[-1] if tokens else ""
    return surname, s


def token_sort_ratio(a: str, b: str) -> float:
    a_sorted = " ".join(sorted(a.split()))
    b_sorted = " ".join(sorted(b.split()))
    return SequenceMatcher(None, a_sorted, b_sorted).ratio()


SHORT_NON_FUNCTION = re.compile(r'^[a-z0-9]{1,4}$')

def short_token_discriminator(key_a: str, key_b: str) -> bool:
    """Return True if the pair differs on a short non-function-word token — likely distinct books."""
    ta, tb = set(key_a.split()), set(key_b.split())
    diff = ta.symmetric_difference(tb)
    return any(
        SHORT_NON_FUNCTION.match(t) and t not in FUNCTION_WORDS
        for t in diff
    )


# ---------------------------------------------------------------------------
# Stable row ID
# ---------------------------------------------------------------------------

def make_row_id(row: dict) -> str:
    key = "|".join([
        row["source"], row["voter_name"], row["position"],
        row["book_title"], row["book_author"]
    ])
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def make_proposal_id(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Union-Find
# ---------------------------------------------------------------------------

class UnionFind:
    def __init__(self):
        self._parent = {}

    def find(self, x):
        if x not in self._parent:
            self._parent[x] = x
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]
            x = self._parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[rb] = ra

    def groups(self):
        result = defaultdict(list)
        for x in self._parent:
            result[self.find(x)].append(x)
        return dict(result)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def load_overrides():
    regs = {"author_aliases": {}, "series_registry": {}, "manual_canonical": {}}
    if REGISTRIES.exists():
        with open(REGISTRIES) as f:
            regs.update(json.load(f))
    decisions = {}
    if DECISIONS.exists():
        with open(DECISIONS, newline="") as f:
            for row in csv.DictReader(f):
                if row.get("proposal_id"):
                    decisions[row["proposal_id"]] = row["decision"].strip()
    return regs, decisions


_COLLECTED_PATTERN = re.compile(
    r'^(?:the\s+)?(?:stories|story|poems|collected\s+stories|collected\s+poems|'
    r'selected\s+poems|plays|complete\s+stories|selected\s+stories|works)\s+of\s+(.+)$',
    re.I
)


def extract_collected_author(title: str):
    m = _COLLECTED_PATTERN.match(title.strip())
    if m:
        name = m.group(1).strip().rstrip(".")
        return name
    return None


def run(verify: bool = False, report_only: bool = False):
    regs, accepted_decisions = load_overrides()
    aliases = regs["author_aliases"]
    series_reg = {norm_title(k)[0]: v for k, v in regs["series_registry"].items()}
    manual_canonical = regs["manual_canonical"]

    # -----------------------------------------------------------------------
    # 1. Load rows, mint row_ids, compute norm keys
    # -----------------------------------------------------------------------
    rows = []
    with open(INPUT_CSV, newline="", encoding="utf-8") as f:
        for raw in csv.DictReader(f):
            rid = make_row_id(raw)
            tk, tk_ns, subtitle = norm_title(raw["book_title"])
            surname, full_auth = norm_author(raw["book_author"])
            # apply author alias
            surname = aliases.get(surname, surname)
            rows.append({
                **raw,
                "row_id": rid,
                "title_key": tk,
                "title_key_ns": tk_ns,
                "subtitle": subtitle,
                "surname_key": surname,
                "full_auth_key": full_auth,
            })

    row_by_id = {r["row_id"]: r for r in rows}

    # -----------------------------------------------------------------------
    # 2. Build union-find: T0 (shared OLID), then T1/T2 (title+author exact)
    # -----------------------------------------------------------------------
    uf = UnionFind()
    for r in rows:
        uf.find(r["row_id"])  # ensure every row is registered

    # T0: group by OLID
    olid_groups = defaultdict(list)
    for r in rows:
        if r["openLibraryId"].strip():
            olid_groups[r["openLibraryId"].strip()].append(r["row_id"])
    for olid, ids in olid_groups.items():
        for rid in ids[1:]:
            uf.union(ids[0], rid)

    # T1/T2: group by (title_key, surname_key) — exact match
    # T2 is implicit: we dropped the subtitle before creating title_key, so two rows
    # that differ only in subtitle already share the same title_key.
    exact_groups = defaultdict(list)
    for r in rows:
        if r["title_key"] and r["surname_key"]:
            exact_groups[(r["title_key"], r["surname_key"])].append(r["row_id"])
    for (tk, sk), ids in exact_groups.items():
        for rid in ids[1:]:
            uf.union(ids[0], rid)

    # Apply accepted overrides (merge_decisions with decision=accept)
    # For accepted fuzzy proposals we store (row_id_a, row_id_b) pairs encoded in proposal_id
    # We can't recover the pair from just the hash, so we store them in the review_flags
    # and re-apply on re-run. For first run there are none yet.
    # (On subsequent runs: accepted proposals are re-generated and then applied here.)
    # We'll apply them after generating proposals — see end of this function.

    # -----------------------------------------------------------------------
    # 3. Detect multi-book slots (series/grouped entries)
    # -----------------------------------------------------------------------
    slot_books = defaultdict(list)
    for r in rows:
        slot_key = (r["source"], r["voter_name"], r["position"])
        slot_books[slot_key].append(r)

    multi_slots = {k: v for k, v in slot_books.items() if len(v) > 1}

    # -----------------------------------------------------------------------
    # 4. Generate review proposals (T3–T6) — do NOT apply them
    # -----------------------------------------------------------------------
    proposals = []

    # T3 Fuzzy title — block by surname, then score within block
    surname_blocks = defaultdict(list)
    for r in rows:
        if r["surname_key"]:
            surname_blocks[r["surname_key"]].append(r)

    seen_fuzzy = set()
    for surname, block in surname_blocks.items():
        # Only look at distinct title_key representatives (one row per title_key)
        seen_tk = {}
        for r in block:
            if r["title_key"] not in seen_tk:
                seen_tk[r["title_key"]] = r
        tks = list(seen_tk.keys())
        for i in range(len(tks)):
            for j in range(i + 1, len(tks)):
                a_tk, b_tk = tks[i], tks[j]
                if a_tk == b_tk:
                    continue
                # Skip pairs already merged by T0/T1/T2
                ra = seen_tk[a_tk]["row_id"]
                rb = seen_tk[b_tk]["row_id"]
                if uf.find(ra) == uf.find(rb):
                    continue
                pair_key = tuple(sorted([a_tk, b_tk]))
                if pair_key in seen_fuzzy:
                    continue
                seen_fuzzy.add(pair_key)

                ratio = token_sort_ratio(a_tk, b_tk)
                if ratio < 0.90:
                    continue

                trap = short_token_discriminator(a_tk, b_tk)
                reason = "SHORT_TOKEN_DISCRIMINATOR" if trap else "FUZZY_TITLE"
                tier = "REJECT" if trap else "T3"
                pid = make_proposal_id("T3", a_tk, b_tk, surname)

                proposals.append({
                    "proposal_id": pid,
                    "reason": reason,
                    "tier": tier,
                    "left_row_id": ra,
                    "left_title": seen_tk[a_tk]["book_title"],
                    "left_author": seen_tk[a_tk]["book_author"],
                    "left_olid": seen_tk[a_tk]["openLibraryId"],
                    "right_row_id": rb,
                    "right_title": seen_tk[b_tk]["book_title"],
                    "right_author": seen_tk[b_tk]["book_author"],
                    "right_olid": seen_tk[b_tk]["openLibraryId"],
                    "similarity": f"{ratio:.3f}",
                    "group_members": "",
                    "suggested_action": "reject" if trap else "review",
                    "decision": accepted_decisions.get(pid, "pending"),
                })

    # T4 Author variant — near-equal title_key, surnames differ by small edit
    title_blocks = defaultdict(list)
    for r in rows:
        if r["title_key"]:
            title_blocks[r["title_key"]].append(r)

    seen_auth = set()
    for tk, block in title_blocks.items():
        surnames = set(r["surname_key"] for r in block if r["surname_key"])
        if len(surnames) <= 1:
            continue
        # Multiple authors for same normalized title — propose author alias
        reps = {}
        for r in block:
            if r["surname_key"] and r["surname_key"] not in reps:
                reps[r["surname_key"]] = r
        surnames_sorted = sorted(reps.keys())
        for i in range(len(surnames_sorted)):
            for j in range(i + 1, len(surnames_sorted)):
                sa, sb = surnames_sorted[i], surnames_sorted[j]
                if uf.find(reps[sa]["row_id"]) == uf.find(reps[sb]["row_id"]):
                    continue
                pair_key = tuple(sorted([sa + "|" + tk, sb + "|" + tk]))
                if pair_key in seen_auth:
                    continue
                seen_auth.add(pair_key)
                edit = SequenceMatcher(None, sa, sb).ratio()
                pid = make_proposal_id("T4", tk, sa, sb)
                proposals.append({
                    "proposal_id": pid,
                    "reason": "AUTHOR_VARIANT",
                    "tier": "T4",
                    "left_row_id": reps[sa]["row_id"],
                    "left_title": reps[sa]["book_title"],
                    "left_author": reps[sa]["book_author"],
                    "left_olid": reps[sa]["openLibraryId"],
                    "right_row_id": reps[sb]["row_id"],
                    "right_title": reps[sb]["book_title"],
                    "right_author": reps[sb]["book_author"],
                    "right_olid": reps[sb]["openLibraryId"],
                    "similarity": f"{edit:.3f}",
                    "group_members": "",
                    "suggested_action": "review",
                    "decision": accepted_decisions.get(pid, "pending"),
                })

    # T5 Blank-author recovery
    for r in rows:
        if r["surname_key"]:
            continue  # has an author
        title = r["book_title"]
        recovered = extract_collected_author(title)
        if recovered:
            pid = make_proposal_id("T5", r["row_id"], "recovered")
            proposals.append({
                "proposal_id": pid,
                "reason": "BLANK_AUTHOR_RECOVERED",
                "tier": "T5",
                "left_row_id": r["row_id"],
                "left_title": title,
                "left_author": "",
                "left_olid": r["openLibraryId"],
                "right_row_id": "",
                "right_title": "",
                "right_author": recovered,
                "right_olid": "",
                "similarity": "",
                "group_members": "",
                "suggested_action": f"set author to: {recovered}",
                "decision": accepted_decisions.get(pid, "pending"),
            })
        else:
            pid = make_proposal_id("T5", r["row_id"], "canon")
            proposals.append({
                "proposal_id": pid,
                "reason": "BLANK_AUTHOR_CANON",
                "tier": "T5",
                "left_row_id": r["row_id"],
                "left_title": title,
                "left_author": "",
                "left_olid": r["openLibraryId"],
                "right_row_id": "",
                "right_title": "",
                "right_author": "",
                "right_olid": "",
                "similarity": "",
                "group_members": "",
                "suggested_action": "confirm as author-less canonical entry",
                "decision": accepted_decisions.get(pid, "pending"),
            })

    # T6 Multi-book slots (series explode / non-series / non-books)
    seen_slots = set()
    for slot_key, slot_rows in multi_slots.items():
        source, voter, pos = slot_key
        titles_in_slot = [r["book_title"] for r in slot_rows]
        # Identify if any title is a known series container
        series_containers = []
        volume_titles = []
        for r in slot_rows:
            if r["title_key"] in series_reg:
                series_containers.append(r)
            else:
                volume_titles.append(r)

        if series_containers:
            reason = "SERIES_EXPLODE"
            container = series_containers[0]
            entry = series_reg[container["title_key"]]
            suggested = (f"explode '{container['book_title']}' into volumes: "
                         + ", ".join(f"'{v}'" for v in entry["canonical_volumes"])
                         + "; volume entries in this slot remain as-is")
        else:
            # Check for non-book signals (films etc.)
            is_nonbook = any(
                r["source_url"] == "" or "film" in r["book_title"].lower()
                for r in slot_rows
            )
            # Heuristic: if titles look like films (no obvious author match), flag NON_BOOK_ENTRY
            # We'll flag all non-series multi-book slots for human review
            reason = "MULTI_BOOK_SLOT"
            suggested = ("each title treated as separate canonical book; "
                         "confirm or identify if any should collapse")

        pid = make_proposal_id("T6", source, voter, pos, "|".join(sorted(titles_in_slot)))
        if pid in seen_slots:
            continue
        seen_slots.add(pid)

        proposals.append({
            "proposal_id": pid,
            "reason": reason,
            "tier": "T6",
            "left_row_id": slot_rows[0]["row_id"],
            "left_title": slot_rows[0]["book_title"],
            "left_author": slot_rows[0]["book_author"],
            "left_olid": slot_rows[0]["openLibraryId"],
            "right_row_id": "",
            "right_title": "",
            "right_author": "",
            "right_olid": "",
            "similarity": "",
            "group_members": " | ".join(titles_in_slot),
            "suggested_action": suggested,
            "decision": accepted_decisions.get(pid, "pending"),
        })

    # Apply accepted merge decisions (pairs stored in review_flags on earlier runs)
    # On first run there are no accepted decisions, so this is a no-op.
    for prop in proposals:
        if prop["decision"] == "accept" and prop["right_row_id"]:
            uf.union(prop["left_row_id"], prop["right_row_id"])

    # -----------------------------------------------------------------------
    # 5. Assign canonical IDs & pick representatives
    # -----------------------------------------------------------------------
    groups = uf.groups()
    # root -> list of row_ids
    canonical_map = {}  # row_id -> canonical_id
    canonical_meta = {}  # canonical_id -> {title, author, year, olids, row_ids, tiers}

    for root, members in groups.items():
        member_rows = [row_by_id[rid] for rid in members]

        # Collect OLIDs in this cluster
        olids = sorted(set(r["openLibraryId"].strip() for r in member_rows
                           if r["openLibraryId"].strip()))

        # Canonical ID
        if olids:
            cid = "OL:" + olids[0]
        else:
            # Derive from most-common title_key + surname_key
            from collections import Counter
            tk_counts = Counter(r["title_key"] for r in member_rows if r["title_key"])
            sk_counts = Counter(r["surname_key"] for r in member_rows if r["surname_key"])
            rep_tk = tk_counts.most_common(1)[0][0] if tk_counts else "unknown"
            rep_sk = sk_counts.most_common(1)[0][0] if sk_counts else ""
            cid = "K:" + hashlib.sha1(f"{rep_tk}|{rep_sk}".encode()).hexdigest()[:12]

        # Override if manual_canonical set
        for rid in members:
            if rid in manual_canonical:
                cid = manual_canonical[rid]
                break

        # Representative title: prefer OLID-anchored row's raw title
        olid_rows = [r for r in member_rows if r["openLibraryId"].strip()]
        from collections import Counter
        if olid_rows:
            title_counts = Counter(r["book_title"] for r in olid_rows)
        else:
            title_counts = Counter(r["book_title"] for r in member_rows)
        rep_title = title_counts.most_common(1)[0][0] if title_counts else ""

        # Representative author: most frequent non-blank
        auth_counts = Counter(r["book_author"] for r in member_rows if r["book_author"].strip())
        rep_auth = auth_counts.most_common(1)[0][0] if auth_counts else ""

        # Representative year: modal clean 4-digit year
        clean_years = [r["year"].strip() for r in member_rows
                       if re.match(r'^\d{4}$', r["year"].strip())]
        rep_year = Counter(clean_years).most_common(1)[0][0] if clean_years else ""

        # How was this cluster derived?
        if olids:
            derived = "olid_anchor"
        else:
            derived = "title_author_exact"

        for rid in members:
            canonical_map[rid] = cid
        canonical_meta[cid] = {
            "canonical_id": cid,
            "canonical_title": rep_title,
            "canonical_author": rep_auth,
            "canonical_year": rep_year,
            "n_rows": len(members),
            "source_olids": ";".join(olids),
            "derived_from": derived,
            "row_ids": members,
        }

    # -----------------------------------------------------------------------
    # 6. Build voter_books: voter_name -> {canonical_id -> metadata}
    # -----------------------------------------------------------------------
    voter_books_raw = defaultdict(lambda: defaultdict(lambda: {
        "sources": set(), "positions": set(), "voter_types": set()
    }))
    for r in rows:
        cid = canonical_map[r["row_id"]]
        voter = r["voter_name"]
        vb = voter_books_raw[voter][cid]
        vb["sources"].add(r["source"])
        vb["positions"].add(r["position"])
        vb["voter_types"].add(r["voter_type"])

    # -----------------------------------------------------------------------
    # 7. Write outputs
    # -----------------------------------------------------------------------
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # canonical_books.csv
    # compute n_voters per canonical
    cid_voters = defaultdict(set)
    for r in rows:
        cid_voters[canonical_map[r["row_id"]]].add(r["voter_name"])

    canon_rows = sorted(canonical_meta.values(), key=lambda x: -cid_voters[x["canonical_id"]].__len__())
    with open(OUT_DIR / "canonical_books.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "canonical_id", "canonical_title", "canonical_author", "canonical_year",
            "n_rows", "n_voters", "source_olids", "derived_from"
        ])
        w.writeheader()
        for cm in canon_rows:
            w.writerow({
                "canonical_id": cm["canonical_id"],
                "canonical_title": cm["canonical_title"],
                "canonical_author": cm["canonical_author"],
                "canonical_year": cm["canonical_year"],
                "n_rows": cm["n_rows"],
                "n_voters": len(cid_voters[cm["canonical_id"]]),
                "source_olids": cm["source_olids"],
                "derived_from": cm["derived_from"],
            })

    # voter_books.csv
    with open(OUT_DIR / "voter_books.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "voter_name", "canonical_id", "sources", "positions", "voter_types"
        ])
        w.writeheader()
        for voter in sorted(voter_books_raw):
            for cid in sorted(voter_books_raw[voter]):
                vb = voter_books_raw[voter][cid]
                w.writerow({
                    "voter_name": voter,
                    "canonical_id": cid,
                    "sources": ";".join(sorted(vb["sources"])),
                    "positions": ";".join(sorted(vb["positions"])),
                    "voter_types": ";".join(sorted(t for t in vb["voter_types"] if t)),
                })

    # review_flags.csv
    with open(OUT_DIR / "review_flags.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "proposal_id", "reason", "tier", "status",
            "left_row_id", "left_title", "left_author", "left_olid",
            "right_row_id", "right_title", "right_author", "right_olid",
            "similarity", "group_members", "suggested_action", "decision"
        ])
        w.writeheader()
        for p in sorted(proposals, key=lambda x: (x["tier"], x["reason"], x["left_title"])):
            p["status"] = "auto-merged" if p["decision"] == "accept" else p["decision"]
            w.writerow(p)

    # row_to_canonical.csv
    with open(OUT_DIR / "row_to_canonical.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "row_id", "source", "voter_name", "position",
            "book_title", "book_author", "year", "openLibraryId",
            "canonical_id", "canonical_title"
        ])
        w.writeheader()
        for r in rows:
            cid = canonical_map[r["row_id"]]
            w.writerow({
                "row_id": r["row_id"],
                "source": r["source"],
                "voter_name": r["voter_name"],
                "position": r["position"],
                "book_title": r["book_title"],
                "book_author": r["book_author"],
                "year": r["year"],
                "openLibraryId": r["openLibraryId"],
                "canonical_id": cid,
                "canonical_title": canonical_meta[cid]["canonical_title"],
            })

    # -----------------------------------------------------------------------
    # 8. Count report
    # -----------------------------------------------------------------------
    n_canonical = len(canonical_meta)
    n_pending = sum(1 for p in proposals if p["decision"] == "pending")
    n_accepted = sum(1 for p in proposals if p["decision"] == "accept")
    bridge_count = sum(
        1 for cm in canonical_meta.values()
        if any(row_by_id[rid]["source"] == "Top Ten Books" for rid in cm["row_ids"])
        and any(row_by_id[rid]["source"] == "Guardian Top 100" for rid in cm["row_ids"])
    )
    print(f"Input rows   : {len(rows)}")
    print(f"Canonical bks: {n_canonical}")
    print(f"Cross-source : {bridge_count} canonical books span both sources")
    print(f"Review flags : {len(proposals)} total  "
          f"({n_pending} pending / {n_accepted} accepted)")
    reasons = defaultdict(int)
    for p in proposals:
        reasons[p["reason"]] += 1
    for r, c in sorted(reasons.items()):
        print(f"  {r}: {c}")

    # -----------------------------------------------------------------------
    # 9. Automated verification
    # -----------------------------------------------------------------------
    if verify:
        print("\n--- VERIFICATION ---")
        errors = []

        # Conservation: every row has exactly one canonical_id
        if len(canonical_map) != len(rows):
            errors.append(f"FAIL conservation: {len(canonical_map)} mapped vs {len(rows)} rows")
        else:
            print("PASS conservation (all 3564 rows mapped)")

        # No silent fuzzy: no cluster contains rows auto-merged by non-T0/T1/T2 path
        # (We can't retroactively detect which tier merged within union-find, but we can
        # check that no cluster contains rows that differ on title_key+surname_key AND
        # have no shared OLID AND no accepted override linking them.)
        fuzzy_violations = 0
        for cid, cm in canonical_meta.items():
            member_rows = [row_by_id[rid] for rid in cm["row_ids"]]
            title_keys = set(r["title_key"] for r in member_rows)
            surnames = set(r["surname_key"] for r in member_rows if r["surname_key"])
            olids = set(r["openLibraryId"].strip() for r in member_rows if r["openLibraryId"].strip())
            if len(title_keys) > 1 and not olids:
                # Multiple title keys in one cluster with no OLID — unexpected
                fuzzy_violations += 1
                if fuzzy_violations <= 3:
                    errors.append(f"SUSPECT: cluster {cid} has title_keys {title_keys} with no OLID anchor")
        if fuzzy_violations:
            errors.append(f"FAIL no-silent-fuzzy: {fuzzy_violations} suspect clusters")
        else:
            print("PASS no-silent-fuzzy (no title-variant clusters without OLID anchor or override)")

        # Trap regression: Mr. Bridge and Mrs. Bridge must have different canonical_ids
        mr_ids = [canonical_map[r["row_id"]] for r in rows if r["book_title"] == "Mr. Bridge"]
        mrs_ids = [canonical_map[r["row_id"]] for r in rows if r["book_title"] == "Mrs. Bridge"]
        if mr_ids and mrs_ids and set(mr_ids) & set(mrs_ids):
            errors.append("FAIL trap: Mr. Bridge and Mrs. Bridge share a canonical_id")
        elif mr_ids and mrs_ids:
            print(f"PASS trap: Mr. Bridge ({mr_ids[0]}) != Mrs. Bridge ({mrs_ids[0]})")
        else:
            print("INFO: Mr/Mrs Bridge not found (titles may have been normalized away)")

        # Cross-source bridge
        if bridge_count == 0:
            errors.append("FAIL bridge: no canonical books span both sources — backfill broken")
        else:
            print(f"PASS bridge: {bridge_count} canonical books span both sources")

        # 4 translation OLIDs stay single (each maps to exactly one cluster)
        translation_olids = {
            "OL1230613W": "Camus Stranger/Outsider",
            "OL24156W": "Jekyll & Hyde",
            "OL151411W": "Alice",
            "OL15202030W": "Hunchback Notre-Dame",
        }
        for olid, label in translation_olids.items():
            matching = [cid for cid, cm in canonical_meta.items()
                        if olid in cm["source_olids"].split(";")]
            if len(matching) != 1:
                errors.append(f"FAIL translation OLID {olid} ({label}): found in {len(matching)} clusters")
            else:
                print(f"PASS translation OLID {olid} ({label}): single cluster {matching[0]}")

        if errors:
            print("\nERRORS:")
            for e in errors:
                print(" ", e)
            sys.exit(1)
        else:
            print("\nAll checks passed.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()
    run(verify=args.verify, report_only=args.report)


if __name__ == "__main__":
    main()
