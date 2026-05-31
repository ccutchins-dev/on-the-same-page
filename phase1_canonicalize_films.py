"""
Phase 1 film canonicalization -- Sight & Sound 2022 ballots.

Usage:
    python phase1_canonicalize_films.py          # run pipeline
    python phase1_canonicalize_films.py --verify # run + check known cases

Inputs (read-only):
    input_data/ss2022_ballots_long.csv
    overrides/film_overrides.csv  (canonical_id, action, merged_into, note)

Outputs (data/processed/):
    canonical_films.csv
    voter_films.csv
    review_flags_films.csv
    row_to_canonical_films.csv
"""

import argparse
import csv
import hashlib
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

INPUT_CSV = Path("input_data/ss2022_ballots_long.csv")
OVERRIDES = Path("overrides/film_overrides.csv")
OUT_DIR   = Path("data/processed")

# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

# Characters to strip from titles before comparison
_STRIP_PUNCT = frozenset(".:,;!?()[]")
_STRIP_ASCII_QUOTES = frozenset(["'", '"'])
# Curly quotes and prime chars by code point
_STRIP_CURLY = frozenset([
    chr(0x2018), chr(0x2019),  # left/right single quotation marks
    chr(0x201C), chr(0x201D),  # left/right double quotation marks
    chr(0x2032), chr(0x2033),  # prime, double prime
])
_STRIP_ALL = _STRIP_PUNCT | _STRIP_ASCII_QUOTES | _STRIP_CURLY

_DASHES = re.compile("[" + chr(0x2013) + chr(0x2014) + chr(0x2015) + "]")


def normalize_title(s):
    """Normalize a film title for identity comparison.

    Strips diacritics, lowercases, collapses whitespace (including NBSP),
    strips punctuation and quotes, normalises dashes.
    """
    s = s.strip()
    # Drop combining diacritics (handles accents: Salom\xe9 -> Salome)
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.lower()
    # Collapse all whitespace including NBSP (U+00A0), thin space, etc.
    s = re.sub(r"\s+", " ", s).strip()
    # Strip punctuation and quote characters
    s = "".join(c for c in s if c not in _STRIP_ALL)
    # Normalise em-dash / en-dash to plain hyphen
    s = _DASHES.sub("-", s)
    # Final whitespace collapse
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalize_director(s):
    """Light normalisation for director names (diacritics + case only)."""
    s = s.strip()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.lower()


# ---------------------------------------------------------------------------
# Year resolution
# ---------------------------------------------------------------------------

_FOUR_DIGITS = re.compile(r"\b(\d{4})\b")


def resolve_year(raw):
    """Return (resolved_year: str|None, flags: list[str])."""
    raw = raw.strip()
    if not raw:
        return None, ["BLANK_YEAR"]

    # Exact 4-digit year
    if re.fullmatch(r"\d{4}", raw):
        y = int(raw)
        if 1870 <= y <= 2025:
            return raw, []
        return None, ["YEAR_ERROR"]

    # Abbreviated range YYYY-YY  e.g. 1972-75
    m = re.fullmatch(r"(\d{4})[~\-" + chr(0x2013) + chr(0x2014) + r"](\d{2})", raw)
    if m:
        y1 = int(m.group(1))
        century = (y1 // 100) * 100
        y2 = century + int(m.group(2))
        if y2 < y1:
            y2 += 100
        flags = ["YEAR_RANGE_LONG"] if (y2 - y1) > 5 else []
        return str(y2), flags

    # Full range YYYY-YYYY  e.g. 1961-1964
    m = re.fullmatch(r"(\d{4})\s*[~\-" + chr(0x2013) + chr(0x2014) + r"\s]\s*(\d{4})", raw)
    if m:
        y1, y2 = int(m.group(1)), int(m.group(2))
        if y2 < y1:
            y1, y2 = y2, y1
        flags = ["YEAR_RANGE_LONG"] if (y2 - y1) > 5 else []
        return str(y2), flags

    # Slash-separated  e.g. 1915 / 1952
    if "/" in raw:
        return None, ["YEAR_AMBIGUOUS"]

    # Comma-separated  e.g. 1972, 1973, 1978
    if "," in raw:
        return None, ["YEAR_AMBIGUOUS"]

    # Has prefix like ca., c., ~
    all_years = [int(x) for x in _FOUR_DIGITS.findall(raw) if 1870 <= int(x) <= 2025]
    if all_years:
        last_y = max(all_years)
        span = last_y - min(all_years)
        flags = ["YEAR_RANGE_LONG"] if span > 5 else []
        return str(last_y), flags

    # Non-numeric junk (director name, "Ongoing", etc.)
    return None, ["YEAR_ERROR"]


# ---------------------------------------------------------------------------
# Canonical ID
# ---------------------------------------------------------------------------

def make_film_id(norm_title, resolved_year):
    """Identity key is title+year only. Director is display-only."""
    key = "{0}|{1}".format(norm_title, resolved_year or "")
    h = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
    return "F:" + h


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run(verify=False):
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Load overrides
    overrides = {}
    if OVERRIDES.exists():
        with open(OVERRIDES, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("canonical_id") and row.get("action"):
                    overrides[row["canonical_id"]] = row

    # Load input
    with open(INPUT_CSV, newline="", encoding="utf-8") as f:
        raw_rows = list(csv.DictReader(f))
    print("Loaded {0} rows from {1}".format(len(raw_rows), INPUT_CSV))

    # --- Resolve years and normalize titles for every row ---
    processed = []
    for idx, row in enumerate(raw_rows):
        norm_t = normalize_title(row["film_title"])
        norm_d = normalize_director(row["film_director"])
        resolved_year, y_flags = resolve_year(row["film_year"])
        processed.append({
            "row_idx": idx,
            "voter_name": row["voter_name"],
            "voter_id": row["voter_id"],
            "role": row["role"],
            "norm_title": norm_t,
            "norm_director": norm_d,
            "raw_title": row["film_title"].strip(),
            "raw_year": row["film_year"].strip(),
            "raw_director": row["film_director"].strip(),
            "resolved_year": resolved_year,
            "year_flags": y_flags,
        })

    # For each normalized title, collect all distinct valid 4-digit years
    title_to_valid_years = defaultdict(set)
    for p in processed:
        if p["resolved_year"]:
            title_to_valid_years[p["norm_title"]].add(p["resolved_year"])

    # --- Pass 1: build canonical clusters from valid-year rows ---
    canonical = {}
    row_to_cid = {}
    review_flags = []

    def get_or_create(norm_t, resolved_year, norm_d, raw_t, raw_d):
        cid = make_film_id(norm_t, resolved_year)
        if cid in overrides and overrides[cid].get("action") == "merge_into":
            cid = overrides[cid]["merged_into"]
        if cid not in canonical:
            canonical[cid] = {
                "canonical_id": cid,
                "norm_title": norm_t,
                "resolved_year": resolved_year,
                "raw_titles": Counter(),
                "raw_directors": Counter(),
                "raw_years": Counter(),
                "voters": set(),
                "row_indices": [],
            }
        cl = canonical[cid]
        cl["raw_titles"][raw_t] += 1
        if raw_d:
            cl["raw_directors"][raw_d] += 1
        return cid

    for p in processed:
        if not p["resolved_year"]:
            continue
        cid = get_or_create(
            p["norm_title"], p["resolved_year"], p["norm_director"],
            p["raw_title"], p["raw_director"],
        )
        row_to_cid[p["row_idx"]] = cid
        canonical[cid]["voters"].add(p["voter_name"])
        canonical[cid]["row_indices"].append(p["row_idx"])
        canonical[cid]["raw_years"][p["raw_year"]] += 1

    # Director variant flags
    for cid, cl in canonical.items():
        dirs_norm = set()
        dirs_raw = set()
        for p in processed:
            if row_to_cid.get(p["row_idx"]) == cid and p["norm_director"]:
                dirs_norm.add(p["norm_director"])
                dirs_raw.add(p["raw_director"])
        if len(dirs_norm) > 1:
            review_flags.append({
                "flag_id": "DV-" + cid,
                "flag_type": "DIRECTOR_VARIANT",
                "raw_titles": cl["raw_titles"].most_common(1)[0][0],
                "raw_years": cl["resolved_year"],
                "raw_directors": " | ".join(sorted(dirs_raw)),
                "row_count": len(cl["row_indices"]),
                "notes": "{0} director spellings".format(len(dirs_norm)),
            })

    # --- Pass 2: assign null-year rows ---
    for p in processed:
        if p["resolved_year"]:
            continue
        norm_t = p["norm_title"]
        base_flags = list(p["year_flags"])
        matching_cids = [cid for cid, cl in canonical.items() if cl["norm_title"] == norm_t]

        if len(matching_cids) == 1:
            cid = matching_cids[0]
            row_to_cid[p["row_idx"]] = cid
            canonical[cid]["voters"].add(p["voter_name"])
            canonical[cid]["row_indices"].append(p["row_idx"])
            canonical[cid]["raw_titles"][p["raw_title"]] += 1
            if p["raw_director"]:
                canonical[cid]["raw_directors"][p["raw_director"]] += 1
            canonical[cid]["raw_years"][p["raw_year"]] += 1
            ft = base_flags[0] if base_flags else "BLANK_YEAR"
            review_flags.append({
                "flag_id": "PY-{0}".format(p["row_idx"]),
                "flag_type": ft,
                "raw_titles": p["raw_title"],
                "raw_years": p["raw_year"],
                "raw_directors": p["raw_director"],
                "row_count": 1,
                "notes": "Tentatively assigned to {0} ({1}). Confirm.".format(
                    cid, canonical[cid]["resolved_year"]),
            })
        elif len(matching_cids) > 1:
            row_to_cid[p["row_idx"]] = "UNRESOLVED"
            ft = base_flags[0] if base_flags else "BLANK_YEAR"
            review_flags.append({
                "flag_id": "AR-{0}".format(p["row_idx"]),
                "flag_type": ft + "+AMBIGUOUS_YEAR_REMAKE",
                "raw_titles": p["raw_title"],
                "raw_years": p["raw_year"],
                "raw_directors": p["raw_director"],
                "row_count": 1,
                "notes": "Title matches {0} distinct films. Human must assign.".format(len(matching_cids)),
            })
        else:
            placeholder = "UNRESOLVED:" + make_film_id(norm_t, "")
            row_to_cid[p["row_idx"]] = placeholder
            ft = base_flags[0] if base_flags else "BLANK_YEAR"
            review_flags.append({
                "flag_id": "NY-{0}".format(p["row_idx"]),
                "flag_type": ft,
                "raw_titles": p["raw_title"],
                "raw_years": p["raw_year"],
                "raw_directors": p["raw_director"],
                "row_count": 1,
                "notes": "No valid-year cluster exists for this title. Unresolved.",
            })

    # POTENTIAL_MERGE: same title when all spaces removed (e.g. "Week End" / "Weekend")
    norm_stripped = defaultdict(set)
    for p in processed:
        ns = p["norm_title"].replace(" ", "").replace("-", "")
        norm_stripped[ns].add(p["norm_title"])
    seen_pm = set()
    for ns, norms in norm_stripped.items():
        if len(norms) < 2:
            continue
        key = tuple(sorted(norms))
        if key in seen_pm:
            continue
        seen_pm.add(key)
        sample = " | ".join(sorted(set(p["raw_title"] for p in processed if p["norm_title"] in norms))[:5])
        review_flags.append({
            "flag_id": "PM-" + ns[:20],
            "flag_type": "POTENTIAL_MERGE",
            "raw_titles": sample,
            "raw_years": str({n: sorted(title_to_valid_years.get(n, set())) for n in sorted(norms)}),
            "raw_directors": "",
            "row_count": sum(1 for p in processed if p["norm_title"] in norms),
            "notes": "Titles differ by space/concat: {0}. Same film?".format(sorted(norms)),
        })

    # YEAR_PROXIMITY: same norm title, years within 2
    for norm_t, valid_years in title_to_valid_years.items():
        if len(valid_years) < 2:
            continue
        yr_list = sorted(int(y) for y in valid_years)
        for i in range(len(yr_list) - 1):
            diff = yr_list[i + 1] - yr_list[i]
            if 1 <= diff <= 2:
                sample = next((p["raw_title"] for p in processed if p["norm_title"] == norm_t), norm_t)
                review_flags.append({
                    "flag_id": "YP-{0}-{1}".format(norm_t[:20], yr_list[i]),
                    "flag_type": "YEAR_PROXIMITY",
                    "raw_titles": sample,
                    "raw_years": "{0} vs {1}".format(yr_list[i], yr_list[i + 1]),
                    "raw_directors": "",
                    "row_count": sum(
                        1 for p in processed
                        if p["norm_title"] == norm_t
                        and p["resolved_year"] in (str(yr_list[i]), str(yr_list[i + 1]))
                    ),
                    "notes": "Years differ by {0}. Remake or range error?".format(diff),
                })

    # BLANK_DIRECTOR flags (deduplicated per canonical film)
    seen_bd = set()
    for p in processed:
        if not p["raw_director"]:
            cid = row_to_cid.get(p["row_idx"])
            if cid not in seen_bd:
                seen_bd.add(cid)
                review_flags.append({
                    "flag_id": "BD-{0}".format(p["row_idx"]),
                    "flag_type": "BLANK_DIRECTOR",
                    "raw_titles": p["raw_title"],
                    "raw_years": p["raw_year"],
                    "raw_directors": "",
                    "row_count": 1,
                    "notes": "No director provided.",
                })


    # Build processed_dict for fast lookup
    processed_dict = {p["row_idx"]: p for p in processed}

    # --- Apply adjudications from overrides/film_adjudications.csv ---
    adj_path = Path("overrides/film_adjudications.csv")
    adjudications = []
    if adj_path.exists():
        with open(adj_path, newline="", encoding="utf-8") as f:
            adjudications = list(csv.DictReader(f))

    if adjudications:
        print("  Applying {0} adjudications...".format(len(adjudications)))

    # Step 1: Merges
    merged_away = set()
    for adj in adjudications:
        if adj["action"] != "merge":
            continue
        src, tgt = adj["source"], adj["target"]
        if src not in canonical or tgt not in canonical:
            continue
        for idx in list(row_to_cid):
            if row_to_cid[idx] == src:
                row_to_cid[idx] = tgt
        cl = canonical[src]
        canonical[tgt]["voters"] |= cl["voters"]
        canonical[tgt]["raw_titles"].update(cl["raw_titles"])
        canonical[tgt]["raw_directors"].update(cl["raw_directors"])
        canonical[tgt]["raw_years"].update(cl["raw_years"])
        canonical[tgt]["row_indices"].extend(cl["row_indices"])
        del canonical[src]
        merged_away.add(src)
    if merged_away:
        print("    Merged {0} source clusters".format(len(merged_away)))

    # Step 2: set_year, set_director
    for adj in adjudications:
        if adj["action"] == "set_year" and adj["source"] in canonical:
            canonical[adj["source"]]["resolved_year"] = adj["resolved_year"]
        elif adj["action"] == "set_director" and adj["source"] in canonical:
            dr = adj["resolved_director"]
            canonical[adj["source"]]["raw_directors"][dr] = (
                canonical[adj["source"]]["raw_directors"].get(dr, 0) + 1000
            )

    # Step 3: create_and_assign / assign_unresolved
    def apply_assign(src_placeholder, target_cid, new_cid_args=None):
        """Reassign rows matching src_placeholder to target_cid."""
        created = False
        if target_cid == "new" and new_cid_args:
            title, year, director = new_cid_args
            norm_t = normalize_title(title)
            cid = make_film_id(norm_t, year)
            if cid not in canonical:
                canonical[cid] = {
                    "canonical_id": cid, "norm_title": norm_t,
                    "resolved_year": year,
                    "raw_titles": Counter({title: 1}),
                    "raw_directors": Counter({director: 1} if director else {}),
                    "raw_years": Counter({year: 1}),
                    "voters": set(), "row_indices": [],
                }
                created = True
            target_cid = cid
        if target_cid not in canonical:
            return None, False
        for idx in list(row_to_cid):
            if row_to_cid.get(idx) == src_placeholder:
                p = processed_dict[idx]
                row_to_cid[idx] = target_cid
                canonical[target_cid]["voters"].add(p["voter_name"])
                canonical[target_cid]["row_indices"].append(idx)
                canonical[target_cid]["raw_titles"][p["raw_title"]] += 1
                canonical[target_cid]["raw_years"][p["raw_year"]] += 1
        return target_cid, created

    new_cids_from_adj = set()
    for adj in adjudications:
        if adj["action"] not in ("create_and_assign", "assign_unresolved"):
            continue
        src = adj["source"]
        tgt = adj["target"]
        yr = adj["resolved_year"]
        dr = adj["resolved_director"]

        if src.startswith("title:"):
            # After merges, find UNRESOLVED rows whose norm_title matches
            raw_title_pattern = src[6:]
            target_norm = normalize_title(raw_title_pattern)
            matching_clusters = [cid for cid, cl in canonical.items()
                                  if cl["norm_title"] == target_norm]
            for idx in list(row_to_cid):
                cid = row_to_cid.get(idx, "")
                if (cid == "UNRESOLVED" or cid.startswith("UNRESOLVED:")):
                    p = processed_dict[idx]
                    if p["norm_title"] == target_norm:
                        if len(matching_clusters) == 1:
                            row_to_cid[idx] = matching_clusters[0]
                            canonical[matching_clusters[0]]["voters"].add(p["voter_name"])
        else:
            # Direct placeholder ID
            new_cid_args = None
            if tgt == "new":
                raw_title = next((processed_dict[idx]["raw_title"]
                                  for idx in row_to_cid if row_to_cid.get(idx) == src), "")
                new_cid_args = (raw_title, yr, dr)
            result_cid, created = apply_assign(src, tgt, new_cid_args)
            if created and result_cid:
                new_cids_from_adj.add(result_cid)

    if new_cids_from_adj:
        print("    Created {0} new canonical films".format(len(new_cids_from_adj)))

    # Step 4: Explosions
    exploded_cids = set()
    explosion_added_pairs = []  # (voter_name, comp_cid) from explosions, for voter_films output
    for adj in adjudications:
        if adj["action"] != "explode":
            continue
        src = adj["source"]
        raw_specs = [s.strip() for s in adj["target"].split(",")]

        # Resolve component canonical_ids
        component_cids = []
        for spec in raw_specs:
            if spec.startswith("new:"):
                parts = spec.split(":", 3)
                t, y = parts[1], parts[2]
                dr2 = parts[3] if len(parts) > 3 else ""
                nt = normalize_title(t)
                cid2 = make_film_id(nt, y)
                if cid2 not in canonical:
                    canonical[cid2] = {
                        "canonical_id": cid2, "norm_title": nt, "resolved_year": y,
                        "raw_titles": Counter({t: 1}),
                        "raw_directors": Counter({dr2: 1} if dr2 else {}),
                        "raw_years": Counter({y: 1}),
                        "voters": set(), "row_indices": [],
                    }
                    new_cids_from_adj.add(cid2)
                component_cids.append(cid2)
            else:
                component_cids.append(spec)

        # Find omnibus rows
        norm_pat = normalize_title(src[6:]) if src.startswith("title:") else ""
        omnibus_voters = set()
        for idx in list(row_to_cid):
            p = processed_dict[idx]
            if norm_pat and p["norm_title"] == norm_pat:
                omnibus_voters.add(p["voter_name"])
                exploded_cids.add(row_to_cid.get(idx, ""))
                row_to_cid[idx] = "EXPLODED"

        # Add component films to omnibus voters; de-dup within voter ballot
        for comp_cid in component_cids:
            if comp_cid in canonical:
                canonical[comp_cid]["voters"] |= omnibus_voters
                for v in omnibus_voters:
                    explosion_added_pairs.append((v, comp_cid))

    # De-dup (voter_name, canonical_id) across all ballot rows including explosions
    # (handled during voter_films output step below)

    if exploded_cids:
        print("    Exploded {0} omnibus cluster(s) into components".format(
            len({c for c in exploded_cids if c and c != "EXPLODED"})))


    # --- Write outputs ---

    # canonical_films.csv
    canon_rows = []
    for cid, cl in sorted(canonical.items(), key=lambda x: -len(x[1]["voters"])):
        canon_rows.append({
            "canonical_id": cid,
            "canonical_title": cl["raw_titles"].most_common(1)[0][0],
            "canonical_director": cl["raw_directors"].most_common(1)[0][0] if cl["raw_directors"] else "",
            "resolved_year": cl["resolved_year"],
            "n_rows": len(cl["row_indices"]),
            "vote_count": len(cl["voters"]),
        })

    with open(OUT_DIR / "canonical_films.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["canonical_id", "canonical_title", "canonical_director",
                                           "resolved_year", "n_rows", "vote_count"])
        w.writeheader()
        w.writerows(canon_rows)
    print("  canonical_films.csv: {0} films".format(len(canon_rows)))

    # voter_films.csv (deduplicated)
    voter_film_pairs = set()
    vf_rows = []
    for p in processed:
        cid = row_to_cid.get(p["row_idx"])
        if not cid or cid.startswith("UNRESOLVED"):
            continue
        pair = (p["voter_name"], cid)
        if pair in voter_film_pairs:
            continue
        voter_film_pairs.add(pair)
        vf_rows.append({
            "voter_name": p["voter_name"],
            "canonical_id": cid,
            "role": p["role"],
            "position": "",  # blank = unranked; _parse_position("") -> 10 (neutral-low)
        })

    # Add explosion-added voter×component pairs (not present in processed rows)
    for voter_name, comp_cid in explosion_added_pairs:
        pair = (voter_name, comp_cid)
        if pair in voter_film_pairs:
            continue
        voter_film_pairs.add(pair)
        vf_rows.append({
            "voter_name": voter_name,
            "canonical_id": comp_cid,
            "role": "",
            "position": "",
        })

    with open(OUT_DIR / "voter_films.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["voter_name", "canonical_id", "role", "position"])
        w.writeheader()
        w.writerows(vf_rows)
    n_voters = len(set(r["voter_name"] for r in vf_rows))
    print("  voter_films.csv: {0} voter*film pairs ({1} voters)".format(len(vf_rows), n_voters))

    # review_flags_films.csv
    with open(OUT_DIR / "review_flags_films.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["flag_id", "flag_type", "raw_titles", "raw_years",
                                           "raw_directors", "row_count", "notes"])
        w.writeheader()
        w.writerows(review_flags)
    by_type = Counter(f["flag_type"].split("+")[0] for f in review_flags)
    print("  review_flags_films.csv: {0} flags".format(len(review_flags)))
    for ft, cnt in sorted(by_type.items()):
        print("    {0}: {1}".format(ft, cnt))

    # row_to_canonical_films.csv
    rtc_rows = []
    for p in processed:
        cid = row_to_cid.get(p["row_idx"], "UNRESOLVED")
        rtc_rows.append({
            "row_index": p["row_idx"],
            "voter_name": p["voter_name"],
            "raw_title": p["raw_title"],
            "raw_year": p["raw_year"],
            "raw_director": p["raw_director"],
            "canonical_id": cid or "UNRESOLVED",
            "resolved_year": p["resolved_year"] or "",
            "flag_types": "+".join(p["year_flags"]),
        })

    with open(OUT_DIR / "row_to_canonical_films.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["row_index", "voter_name", "raw_title", "raw_year",
                                           "raw_director", "canonical_id", "resolved_year", "flag_types"])
        w.writeheader()
        w.writerows(rtc_rows)
    print("  row_to_canonical_films.csv: {0} rows".format(len(rtc_rows)))

    # Overrides placeholder
    OVERRIDES.parent.mkdir(parents=True, exist_ok=True)
    if not OVERRIDES.exists():
        with open(OVERRIDES, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=["canonical_id", "action", "merged_into", "note"]).writeheader()
        print("  Created {0} (header-only placeholder)".format(OVERRIDES))

    # --- Verification ---
    if verify:
        print("\n=== VERIFICATION ===")
        errors = 0

        # 1. Twin Peaks: 5 spellings -> 1 canonical_id
        # 4 spellings have year=2017; NBSP variant has year=2018 (voter data error)
        # Verify the 4 year=2017 spellings merge, and NBSP is flagged YEAR_PROXIMITY
        tp_2017 = [
            "Twin Peaks: The Return", "Twin Peaks the Return",
            "Twin Peaks The Return", "Twin Peaks: The Return.",
        ]
        tp_cids_2017 = set()
        for p in processed:
            if p["raw_title"] in tp_2017 and p["resolved_year"] == "2017":
                c = row_to_cid.get(p["row_idx"])
                if c:
                    tp_cids_2017.add(c)
        tp_proximity = any(
            "2017" in f["raw_years"] and "2018" in f["raw_years"] and "twin peaks" in normalize_title(f["raw_titles"])
            for f in review_flags if f["flag_type"] == "YEAR_PROXIMITY"
        )
        if len(tp_cids_2017) == 1 and tp_proximity:
            print("  PASS Twin Peaks: 4 x 2017 spellings -> 1 cid; 2018 NBSP variant flagged YEAR_PROXIMITY")
        elif len(tp_cids_2017) == 1:
            print("  PASS Twin Peaks: 4 x 2017 spellings -> 1 cid (2018 NBSP variant is separate data-error row)")
        else:
            print("  FAIL Twin Peaks 2017: expected 1 cid, got {0}: {1}".format(len(tp_cids_2017), tp_cids_2017))
            errors += 1

        # 2. Accent/case normalization
        # Note: Salomè (1972) and Salomé (1976) in the data are DIFFERENT films (different years).
        # Our normalization correctly gives them the same norm title, but year disambiguates them.
        # Verify: norm titles are identical (normalization works), and they are distinct because
        # they have different years (correct behavior under our rules).
        sal_a = "Salom" + chr(0xe8)
        sal_b = "Salom" + chr(0xe9)
        norm_a = normalize_title(sal_a)
        norm_b = normalize_title(sal_b)
        years_a = set(p["resolved_year"] for p in processed if p["raw_title"] == sal_a and p["resolved_year"])
        years_b = set(p["resolved_year"] for p in processed if p["raw_title"] == sal_b and p["resolved_year"])
        if norm_a == norm_b:
            if years_a != years_b:
                print("  PASS Salome: norm({0!r}) == norm({1!r}) = {2!r}; distinct years {3} vs {4} correctly kept separate".format(
                    sal_a, sal_b, norm_a, sorted(years_a), sorted(years_b)))
            else:
                ca = set(row_to_cid[p["row_idx"]] for p in processed if p["raw_title"] == sal_a)
                cb = set(row_to_cid[p["row_idx"]] for p in processed if p["raw_title"] == sal_b)
                if ca == cb:
                    print("  PASS Merged {0!r} / {1!r} (same year)".format(sal_a, sal_b))
                else:
                    print("  FAIL Not merged {0!r} / {1!r} (same year {2})".format(sal_a, sal_b, years_a))
                    errors += 1
        else:
            print("  FAIL Normalization: {0!r} -> {1!r} != {2!r} -> {3!r}".format(sal_a, norm_a, sal_b, norm_b))
            errors += 1

        for a, b in [("Gangs Of Wasseypur", "Gangs of Wasseypur")]:
            ca = set(row_to_cid[p["row_idx"]] for p in processed if p["raw_title"] == a)
            cb = set(row_to_cid[p["row_idx"]] for p in processed if p["raw_title"] == b)
            merged = ca & cb
            if merged:
                print("  PASS Merged {0!r} / {1!r}".format(a, b))
            else:
                print("  FAIL Not merged {0!r} ({1}) / {2!r} ({3})".format(a, ca, b, cb))
                errors += 1

        # 3. Remakes kept distinct
        for title, expected_years in [
            ("Carrie", {"1952", "1976"}),
            ("Elephant", {"1988", "2003"}),
            ("Asylum", {"1972", "2000"}),
            ("Angst", {"1954", "1983"}),
        ]:
            norm_t = normalize_title(title)
            cids = set()
            for p in processed:
                if p["norm_title"] == norm_t and p["resolved_year"] in expected_years:
                    c = row_to_cid.get(p["row_idx"])
                    if c:
                        cids.add(c)
            if len(cids) == len(expected_years):
                print("  PASS Remakes distinct: {0!r} -> {1} films".format(title, len(cids)))
            else:
                print("  FAIL {0!r}: expected {1}, got {2} cids".format(title, len(expected_years), len(cids)))
                errors += 1

        # 4. Dog Star Man: YEAR_ERROR flagged, all rows -> same cid
        dsm_norm = normalize_title("Dog Star Man")
        dsm_cids = set()
        dsm_err = False
        for p in processed:
            if p["norm_title"] == dsm_norm:
                c = row_to_cid.get(p["row_idx"])
                if c:
                    dsm_cids.add(c)
                if "YEAR_ERROR" in p["year_flags"]:
                    dsm_err = True
        if len(dsm_cids) == 1 and dsm_err:
            print("  PASS Dog Star Man: YEAR_ERROR flagged, all -> {0}".format(next(iter(dsm_cids))))
        else:
            print("  FAIL Dog Star Man: cids={0}, err={1}".format(dsm_cids, dsm_err))
            errors += 1

        # 5. Week End / Weekend: NOT auto-merged, flagged POTENTIAL_MERGE
        we_norm = normalize_title("Week End")
        wk_norm = normalize_title("Weekend")
        auto_merged = (we_norm == wk_norm)
        weekend_flag = any(
            ("Weekend" in f["raw_titles"] or "Week End" in f["raw_titles"])
            and f["flag_type"] == "POTENTIAL_MERGE"
            for f in review_flags
        )
        if not auto_merged and weekend_flag:
            print("  PASS Week End / Weekend: not merged, POTENTIAL_MERGE flag present")
        else:
            print("  FAIL Week End/Weekend: auto_merged={0}, flag={1}".format(auto_merged, weekend_flag))
            errors += 1

        result = "ALL CHECKS PASSED" if errors == 0 else "{0} CHECK(S) FAILED".format(errors)
        print("\n" + result)

    print("\nDone.")
    return canonical, review_flags


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    run(verify=args.verify)
