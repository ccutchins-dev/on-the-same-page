# PROGRESS.md

Append-only log of completed work. Appends a new entry after each task 
that successfully merges to `main`, and also appends a handoff note 
when escalating to the human.

## Schema

Each entry is a heading-level entry in the Entries section below:

```
## YYYY-MM-DD — T-NNN — short summary

- **Commit**: <merge commit SHA on main>
- **Branch**: feature/T-NNN-short-desc
- **Tag** (if applicable): vX.Y-milestone-name
- **Notes**: brief context, results, anything notable
```

For escalation handoffs (not task completions), use this format instead:

```
## YYYY-MM-DD — ESCALATION

- **Last task attempted**: T-NNN
- **Last commit**: <SHA on main, or "none">
- **Branch state**: which branches exist, in what state
- **What was tried**: brief summary of recent activity
- **Why escalating**: which stop condition fired
- **Input needed from human**: the specific decision or info required
```

Append in chronological order. Never edit prior entries.

## Entries

*No work completed yet.*