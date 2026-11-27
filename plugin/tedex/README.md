# TEDEX Plugin (Software-Layer Bundle — Mode B)

This folder packages **TEDEX** as a standalone software-layer plugin for **Antigravity** and **Claude Code / Cowork**, cleanly separating engine code & skills from the user's experimental data folder.

## Installation

1. **Install the Python CLI engine once** (editable or standard install):
   ```bash
   pip install -e .
   ```
   This registers the `te` and `te-init` commands globally in your Python environment.
2. **Install / Link the Plugin**:
   Copy or symlink `plugin/tedex` into `~/.gemini/config/plugins/tedex` (or publish to a plugin catalog).
3. **Open any clean data folder**:
   Your research project folder needs **zero** `.py` files, **zero** `skills/` folders, and **zero** `AGENTS.md` clutter. On first use, ask the agent to initialize the workspace (or run `te init`), confirm your preferred folder locations and instrument types, and TEDEX locks them into `configs/workspace.json`.
