# Claude Code instructions

Project instructions for every agent live in AGENTS.md, which Codex reads too:

@AGENTS.md

## Role subagents

`.claude/agents/` defines three roles. Delegate to them by name, or let their
descriptions decide:

- `te-plotter`: figures (`plot-te`, `plot-xrd`, `flexible`).
- `te-analyst`: raw-data processing, SPB fits, and lab metadata. The only role
  that writes `data/lab/` and processed data.
- `te-assessor`: assessment, Bayesian ranking, and the LLM analysis (`agent`).

Plotting and assessment jobs can run in parallel. `analyze` jobs cannot, so
give the analyst all batches in one request.
