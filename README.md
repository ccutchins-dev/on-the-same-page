# Generic Agentic Project Scaffolding

This folder is a reusable template for autonomous agentic ML and software
projects driven by Claude Code. It defines an orchestrator (the main
Claude Code session, driven by `CLAUDE.md`) that dispatches three
specialized subagents — `architect`, `engineer`, and `ml-scientist` —
through a structured workflow: plan → review → execute → verify → merge.
Git discipline, state files, and stop conditions are designed so the team
can iterate unattended for hours and return control to the human cleanly
when a working version is reached or a guardrail fires.

To start a new project from this template, see **`START_HERE.md`**.