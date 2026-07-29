# Known Issues

This file is the working memory for open issues, environmental constraints, and follow-up items that should stay visible while the project evolves.

## Environment Constraints

- Shell commands in this workspace should be run through `rtk`.
- The sandbox can fail with `bwrap: loopback: Failed RTM_NEWADDR`.
- When that happens, the failure is usually caused by the local sandbox/runtime, not by repository code.
- If a command is blocked by sandbox policy, rerun it with `require_escalated` instead of changing project files to work around the environment.

## Project Scope Boundaries

- Phase 2 stays limited to ingestion reliability.
- Reconciliation logic is out of scope for the current phase.
- Frontend work is out of scope for the current phase.
- AI-related work is out of scope for the current phase.

## Open Follow-ups

- Keep the phase split documented in `docs/INDEX.md`.
- Keep milestone tracking updated in `docs/MILESTONES.md`.
- Treat `TODO.md` as the source of truth for unresolved product work.
