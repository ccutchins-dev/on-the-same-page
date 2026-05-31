"""
One-time year resolution pass on manually_filled_descriptions_and_years.csv.

Rule: plain YYYY-YYYY ranges on single-titled works (serialized/installment novels)
→ replace with the last year. Separately-titled volumes (series, trilogies,
collections) → untouched. Estimate values (c., BCE, century, etc.) → untouched.

Run once, then this script is no longer needed.
"""

import csv
import re
from pathlib import Path

CSV_PATH = Path("data/processed/manually_filled_descriptions_and_years.csv")
YEAR_COL = "publication_year"

# 29 canonical IDs whose plain YYYY-YYYY ranges resolve to the last year.
# These are single-titled works issued in installments/parts under one title.
NOVEL_CANONICAL_IDS = {
    "OL:OL20867W",       # Middlemarch
    "OL:OL267096W",      # Anna Karenina
    "OL:OL19350876W",    # Madame Bovary
    "OL:OL32013322W",    # Tristram Shandy
    "OL:OL14868508W",    # Bleak House
    "OL:OL276365W",      # The Portrait of a Lady
    "OL:OL44222301W",    # Don Quixote
    "OL:OL8721462W",     # Great Expectations
    "OL:OL10432709W",    # The Brothers Karamazov
    "OL:OL8662242W",     # David Copperfield
    "OL:OL676009W",      # The Master and Margarita
    "OL:OL41368739W",    # Our Mutual Friend
    "OL:OL668682W",      # The Makioka Sisters
    "OL:OL757983W",      # Independent People
    "OL:OL1330246W",     # The Man Without Qualities
    "K:338581d02713",    # The Wind-Up Bird Chronicle
    "K:bd646529eae4",    # The Possessed (Dostoevsky)
    "K:1d1ae492ede5",    # Don Juan (Byron)
    "OL:OL27871634W",    # Septology
    "OL:OL25451958W",    # Eugene Onegin
    "K:d2e22cdb10e6",    # Anton Reiser
    "K:276c1877072e",    # Splendeurs et misères (A Harlot High and Low)
    "K:fc55a5b4798e",    # The Good Soldier Svejk
    "K:abe0b2fd942d",    # Antony and Cleopatra
    "K:11db7aaa5eac",    # Little Women
    "K:275b5f71a8ce",    # Faust
    "OL:OL16273321W",    # Invitation to a Beheading
    "OL:OL166971W",      # Demons (Dostoevsky)
    "OL:OL41016555W",    # Pickwick Papers
}


def resolve_last_year(raw):
    """Parse YYYY-YYYY or YYYY-YY range and return the last year as a string."""
    parts = re.split(r"[–\-]", raw.strip())
    if len(parts) != 2:
        return None
    first, last = parts[0].strip(), parts[1].strip()
    if not (re.match(r"^\d{4}$", first) and re.match(r"^\d{2,4}$", last)):
        return None
    if len(last) == 2:
        last = first[:2] + last  # e.g. 1871-72 → 1872
    return last


def main():
    rows = list(csv.DictReader(open(CSV_PATH, newline="", encoding="utf-8")))
    fieldnames = list(rows[0].keys())

    changes = []
    for row in rows:
        cid = row["canonical_id"]
        old_year = row[YEAR_COL].strip()
        if cid not in NOVEL_CANONICAL_IDS:
            continue
        # Safety: only act on rows that ARE plain ranges
        if not re.match(r"^\d{4}[–\-]\d{2,4}$", old_year):
            print(f"  SKIP {cid} ({row['title']!r}): not a plain range: {old_year!r}")
            continue
        new_year = resolve_last_year(old_year)
        if new_year is None:
            print(f"  SKIP {cid}: could not parse {old_year!r}")
            continue
        if old_year == new_year:
            continue
        row[YEAR_COL] = new_year
        changes.append((cid, row["title"], old_year, new_year))

    if not changes:
        print("No changes to apply.")
        return

    print(f"\nApplying {len(changes)} year resolutions:\n")
    for cid, title, old, new in sorted(changes, key=lambda x: x[2]):
        print(f"  {old} → {new:4s}  {title}")

    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nWrote {CSV_PATH}")


if __name__ == "__main__":
    main()
