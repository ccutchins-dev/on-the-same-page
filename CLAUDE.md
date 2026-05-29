# CLAUDE.md

Guidance for Claude Code working in this repository.

## Source of truth

- `PROJECT.md` — the project's goals, scope, and phases. Read it before starting work. Do not contradict it; if a change seems to require contradicting it, stop and ask.
- `PROGRESS.md` — running log of what's done and what's next.
- `DECISIONS.md` — record of meaningful decisions and their rationale.

## Workflow

1. Before a task, read `PROJECT.md` and the latest entries in `PROGRESS.md`.
2. Work in small, verifiable steps. Prefer the simplest approach that satisfies `PROJECT.md`; don't add scope, abstraction, or dependencies that weren't asked for.
3. Verify your work before considering a task done — run it, test it, or otherwise confirm it behaves as intended. Don't claim something works without checking.
4. At the end of each task, update `PROGRESS.md` (see below) and append to `DECISIONS.md` if any meaningful decision was made.
5. Handle all git operations yourself (see below).

## PROGRESS.md

Update at the end of every task. Keep it short. Each entry: date, what was done, current state, and the next logical step. Newest entries at the top. This file is how a fresh session gets oriented — write it for that reader.

## DECISIONS.md

Append an entry whenever you make a decision that someone might later wonder about: a choice between viable alternatives, a tradeoff, a non-obvious approach, or anything that locks in future work. Each entry: date, the decision, the alternatives considered, and a one-line rationale. Don't log trivial or purely mechanical choices.

When `PROJECT.md` leaves something open and you resolve it, record it here.

## Git

You own git. The user does not want to manage it.

- Commit in logical units — one coherent change per commit, not one giant commit at the end.
- Write clear, imperative commit messages explaining *why*, not just *what*.
- Commit working states; don't commit broken code as a checkpoint.
- Never force-push, rewrite shared history, or delete branches without being asked.
- Don't commit secrets, credentials, large data artifacts, or generated output unless `PROJECT.md` says to. Use `.gitignore`.

## When unsure

If a requirement is ambiguous, the simplest reading conflicts with `PROJECT.md`, or a decision feels above your pay grade — ask rather than guess. A short question now beats unwinding the wrong direction later.

## Style

- Match the conventions already present in the codebase.
- Keep changes focused; avoid unrelated refactors in the same task.
- Leave the code at least as clear as you found it.