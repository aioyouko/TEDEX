# Uploading to GitHub & Releasing Tagged Versions

A practical guide for publishing `tedex` to GitHub and cutting versioned releases. Version numbers live in **four** manifest files that must stay in sync — `VERSION`, `pyproject.toml`, `te_analysis/__init__.py`, and `plugin/tedex/plugin.json` — alongside the release notes in `CHANGELOG.md`.

> Replace `<your-username>` with your GitHub username throughout.
> The current version is **1.5.1**; examples below use **1.6.0** as a future minor release.

---

## 0. Pre-Release Checklist

Before staging or pushing a public commit:

1. **Run the test suite**:
   ```bash
   python tests/run_tests.py
   ```
2. **Verify version consistency**:
   Ensure `VERSION`, `pyproject.toml` (`version = "..."`), `te_analysis/__init__.py` (`__version__ = "..."`), and `plugin/tedex/plugin.json` (`"version": "..."`) all match.
3. **Verify `.gitignore` protection**:
    Run `git status --short` and confirm that no private experimental folders (`data/raw/`, `data/lab/`, `data/metadata/`, `data/processed/`, `data/performance_comparison/`, `configs/workspace.json`, `configs/lab_batches.json`, or `.env`) appear as staged or untracked files.

---

## 1. First-Time Upload (Do This Once)

From the project root:

```bash
git branch -M main
git add -A
git commit -m "Release TEDEX v1.5.0"
```

Create the repository and push with the GitHub CLI:

```bash
gh repo create tedex --private --source=. --remote=origin --push
```

Or create an empty repository at <https://github.com/new> and run:

```bash
git remote add origin https://github.com/<your-username>/tedex.git
git push -u origin main
```

---

## 2. Cutting a New Version (`X.Y.Z`)

1. **`CHANGELOG.md`** — move items under `## Unreleased` into `## X.Y.Z - YYYY-MM-DD` and keep an empty `## Unreleased` heading at the top.
2. **Update version strings** in:
   - `VERSION`
   - `pyproject.toml`
   - `te_analysis/__init__.py`
   - `plugin/tedex/plugin.json`
3. **Commit, tag, and push**:
   ```bash
   git add CHANGELOG.md VERSION pyproject.toml te_analysis/__init__.py plugin/tedex/plugin.json
   git commit -m "Release vX.Y.Z"
   git tag -a vX.Y.Z -m "Release vX.Y.Z"
   git push --follow-tags
   gh release create vX.Y.Z --generate-notes
   ```
