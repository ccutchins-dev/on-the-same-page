"""
One-time year backfill for canonical_books.csv.

Resolves publication years for the 515 books with blank canonical_year:
  - Short-span ranges (≤25 yr): auto-resolved to first year (publication windows)
  - Long-span ranges (>25 yr): flagged for human review (author lifespans)
  - Truly blank, K-prefixed: flagged for human review
  - Truly blank, OL-prefixed: queried from OpenLibrary API (if reachable)
  - Clearly ancient works (Homer, Virgil, etc.): labeled "pre-Renaissance"

Outputs:
  data/processed/year_backfill.csv   — canonical_id, year (for resolved books)
  data/processed/year_gaps.csv       — books needing human input (with blank year column)

Usage:
  python3 backfill_years.py           # full run (attempts OL fetch)
  python3 backfill_years.py --no-fetch  # skip OL fetch (use after filling year_gaps.csv)
"""

import argparse
import csv
import json
import re
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

DATA_DIR = Path("data/processed")
GAPS_CSV = DATA_DIR / "year_gaps.csv"
BACKFILL_CSV = DATA_DIR / "year_backfill.csv"

# Ancient works: truly no reliable specific year → "pre-Renaissance"
ANCIENT_AUTHORS = frozenset({
    'homer', 'virgil', 'ovid', 'sophocles', 'euripides', 'aeschylus',
    'aristophanes', 'thucydides', 'herodotus', 'plato', 'aristotle',
    'murasaki shikibu', 'murasaki',
})
ANCIENT_TITLE_KEYWORDS = frozenset({
    'iliad', 'odyssey', 'aeneid', 'metamorphoses', 'oedipus',
    'medea', 'bacchae', 'oresteia', 'agamemnon', 'electra',
    'gilgamesh', 'arabian nights', 'thousand and one nights',
    'one thousand and one', 'tale of genji', 'bible', 'beowulf',
})


def is_ancient(title, author):
    t = title.lower()
    a = author.lower()
    if any(k in a for k in ANCIENT_AUTHORS):
        return True
    if any(k in t for k in ANCIENT_TITLE_KEYWORDS):
        return True
    return False


def parse_range_year(raw):
    """
    Return (first_year, span) for range/slash strings, or (None, None).

    Recognized formats:
      YYYY-YYYY  e.g. 1954-1956 → (1954, 2)
      YYYY-YY    e.g. 1954-56   → (1954, 2)   assumes same or next century
      YYYY/YY    e.g. 1605/15   → (1605, 10)
    Only returns a result if first_year is in [800, 2025].
    """
    raw = raw.strip()

    # YYYY-YYYY
    m = re.fullmatch(r'(\d{4})-(\d{4})', raw)
    if m:
        y1, y2 = int(m.group(1)), int(m.group(2))
        if 800 <= y1 <= 2025:
            return y1, abs(y2 - y1)

    # YYYY-YY
    m = re.fullmatch(r'(\d{4})-(\d{2})', raw)
    if m:
        y1 = int(m.group(1))
        suffix = int(m.group(2))
        century = (y1 // 100) * 100
        y2 = century + suffix
        if y2 < y1:
            y2 += 100
        if 800 <= y1 <= 2025:
            return y1, abs(y2 - y1)

    # YYYY/YY
    m = re.fullmatch(r'(\d{4})/(\d{2,4})', raw)
    if m:
        y1 = int(m.group(1))
        if 800 <= y1 <= 2025:
            return y1, 0   # slash = effectively a short-span alias

    return None, None


def check_ol_connectivity(timeout=5):
    """Return True if openlibrary.org responds."""
    try:
        req = urllib.request.Request(
            'https://openlibrary.org/works/OL20867W.json',
            headers={'User-Agent': 'KindredLists-YearBackfill/1.0'},
            method='HEAD',
        )
        urllib.request.urlopen(req, timeout=timeout)
        return True
    except Exception:
        return False


def fetch_ol_year(ol_work_id, timeout=8):
    """
    Fetch first_publish_year from OpenLibrary Works API.
    ol_work_id: bare ID like 'OL1190289W' (no prefix).
    Returns int year or None.
    """
    url = f'https://openlibrary.org/works/{ol_work_id}.json'
    try:
        req = urllib.request.Request(
            url, headers={'User-Agent': 'KindredLists-YearBackfill/1.0'})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        year = data.get('first_publish_year')
        if year:
            return int(year)
        # Fall back to created.value date string "YYYY-..."
        created = data.get('created', {}).get('value', '')
        m = re.match(r'(\d{4})', created)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return None


def load_blank_books():
    """Return {canonical_id: dict} for books with blank canonical_year."""
    blank = {}
    with open(DATA_DIR / 'canonical_books.csv', newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            if not row.get('canonical_year', '').strip():
                blank[row['canonical_id']] = dict(row)
    return blank


def load_raw_years(blank_ids):
    """Return {canonical_id: set[raw_year_str]} for blank books."""
    raw = {}
    with open(DATA_DIR / 'row_to_canonical.csv', newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            cid = row.get('canonical_id', '')
            if cid in blank_ids:
                y = row.get('year', '').strip()
                raw.setdefault(cid, set()).add(y)
    return raw


def load_existing_gaps():
    """If year_gaps.csv exists and has user-filled years, return {canonical_id: year}."""
    if not GAPS_CSV.exists():
        return {}
    filled = {}
    with open(GAPS_CSV, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            y = row.get('year', '').strip()
            if y:
                filled[row['canonical_id']] = y
    return filled


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-fetch', action='store_true',
                        help='Skip OpenLibrary API fetch; use only local data + existing gaps CSV')
    args = parser.parse_args()

    blank_books = load_blank_books()
    raw_years   = load_raw_years(set(blank_books))
    filled_gaps = load_existing_gaps()

    resolved  = {}   # {cid: year_str}  — auto or gap-filled
    gaps      = []   # [{...}]          — need human input

    auto_range_count   = 0
    ancient_count      = 0
    gap_lifespan_count = 0
    gap_blank_count    = 0

    # ── Pass 1: range/slash and ancient keyword resolution ─────────────────────
    for cid, book in blank_books.items():
        title  = book['canonical_title']
        author = book['canonical_author']

        # Already filled by user in gaps CSV
        if cid in filled_gaps:
            resolved[cid] = filled_gaps[cid]
            continue

        non_empty_raw = [y for y in raw_years.get(cid, set()) if y]

        # Try to parse a range/slash year
        resolved_year = None
        gap_reason    = None
        raw_used      = None

        for y in non_empty_raw:
            first, span = parse_range_year(y)
            if first is not None:
                if span is not None and span > 25:
                    gap_reason = f'lifespan-range: {y} (span {span}yr)'
                else:
                    resolved_year = str(first)
                    raw_used = y
                break

        if resolved_year:
            resolved[cid] = resolved_year
            auto_range_count += 1
            continue

        # Check for ancient / pre-Renaissance
        if not non_empty_raw and is_ancient(title, author):
            resolved[cid] = 'pre-Renaissance'
            ancient_count += 1
            continue

        # Everything else → gap (OL fetch will fill OL-prefix below; others go straight to gaps)
        gap_entry = {
            'canonical_id': cid,
            'title': title,
            'author': author,
            'source_olids': book.get('source_olids', ''),
            'raw_year': ', '.join(sorted(y for y in non_empty_raw if y)),
            'gap_reason': gap_reason or ('truly-blank' if not non_empty_raw else 'unparseable'),
            'year': '',
        }
        gaps.append(gap_entry)
        if gap_reason and 'lifespan' in gap_reason:
            gap_lifespan_count += 1
        else:
            gap_blank_count += 1

    # ── Pass 2: OpenLibrary fetch for OL-prefixed gaps ─────────────────────────
    ol_gaps = [g for g in gaps if g['canonical_id'].startswith('OL:')]

    if ol_gaps and not args.no_fetch:
        print(f'Checking OpenLibrary connectivity…', end=' ', flush=True)
        ol_ok = check_ol_connectivity()
        print('OK' if ol_ok else 'UNREACHABLE')

        if ol_ok:
            print(f'Fetching years for {len(ol_gaps)} OL-prefixed books…')
            fetched = failed = 0
            for g in ol_gaps:
                # canonical_id = 'OL:OLxxxxxxW'
                work_id = g['canonical_id'].removeprefix('OL:')
                year = fetch_ol_year(work_id)
                if year:
                    resolved[g['canonical_id']] = str(year)
                    fetched += 1
                else:
                    failed += 1
                # Rate limit: 5 req/s
                time.sleep(0.2)
                if (fetched + failed) % 50 == 0:
                    print(f'  {fetched + failed}/{len(ol_gaps)}…')
            print(f'  Fetched {fetched}, failed/missing {failed}')
            # Remove OL gaps that were resolved
            gaps = [g for g in gaps if g['canonical_id'] not in resolved]
        else:
            print('  → OpenLibrary unreachable; all OL-prefixed books go into year_gaps.csv')
            print('    To fetch: allowlist openlibrary.org and re-run without --no-fetch')
    elif args.no_fetch:
        print('Skipping OpenLibrary fetch (--no-fetch).')

    # ── Write outputs ──────────────────────────────────────────────────────────
    BACKFILL_CSV.parent.mkdir(parents=True, exist_ok=True)

    with open(BACKFILL_CSV, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['canonical_id', 'year'])
        w.writeheader()
        for cid, year in sorted(resolved.items()):
            w.writerow({'canonical_id': cid, 'year': year})

    with open(GAPS_CSV, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=[
            'canonical_id', 'title', 'author', 'source_olids', 'raw_year', 'gap_reason', 'year'])
        w.writeheader()
        for g in sorted(gaps, key=lambda x: (x['gap_reason'], x['title'])):
            w.writerow(g)

    # ── Summary ────────────────────────────────────────────────────────────────
    total_blank = len(blank_books)
    total_resolved = len(resolved)
    total_gaps = len(gaps)

    print()
    print(f'=== Year backfill summary ===')
    print(f'  Blank-year books total:            {total_blank}')
    print(f'  Auto-resolved (range, ≤25yr span): {auto_range_count}')
    print(f'  Auto-resolved (pre-Renaissance):   {ancient_count}')
    print(f'  Resolved via gap CSV (user input): {len(filled_gaps)}')
    print(f'  Resolved via OpenLibrary fetch:    {total_resolved - auto_range_count - ancient_count - len(filled_gaps)}')
    print(f'  Total resolved:                    {total_resolved}')
    print(f'  Remaining gaps (need review):      {total_gaps}')
    print()
    print(f'Wrote: {BACKFILL_CSV}  ({total_resolved} entries)')
    if total_gaps > 0:
        print(f'Wrote: {GAPS_CSV}  ({total_gaps} entries)')
        print()
        print('ACTION NEEDED:')
        if any(g['canonical_id'].startswith('OL:') for g in gaps):
            print('  - OL-prefixed books remain: allowlist openlibrary.org and re-run, OR')
        print('  - Fill in the `year` column of year_gaps.csv, then re-run with --no-fetch')
        print('  - Use 4-digit publication year (e.g. 1971) or "pre-Renaissance"')
        print()
        by_reason = {}
        for g in gaps:
            r = g['gap_reason'].split(':')[0]
            by_reason[r] = by_reason.get(r, 0) + 1
        for reason, count in sorted(by_reason.items()):
            print(f'    {count:3d}  {reason}')
    else:
        print('All books resolved! Ready to re-export model_data.json.')


if __name__ == '__main__':
    main()
