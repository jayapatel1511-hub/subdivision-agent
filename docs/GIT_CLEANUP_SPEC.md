# Git Cleanup + README Update Spec

**Project:** subdivision-agent
**Repo:** https://github.com/jayapatl1511-hub/subdivision-agent
**Branch:** Create `git-cleanup` from `main`

## Current Problems

1. **macOS `._` files committed** — AppleDouble resource fork files (`.._README.md`, `.._main.py`, etc.) are tracked in git. These are junk from macOS and should NOT be in the repo.
2. **No `.gitignore`** — repo has no gitignore at all.
3. **Stale branches** — `irregular-v1` and `qgis-export` are merged into main but still exist locally and remotely.
4. **`CONSTRAINT_TAXONOMY.md`** exists at repo root but is not mentioned in README.
5. **`intake.py`** exists but isn't documented in README architecture table.

## Tasks

### 1. Remove all `._` files from git tracking

```bash
# Remove all AppleDouble files from git index (keep on disk if macOS needs them)
git rm --cached '._*' -r
git rm --cached '._*.*'
```

Remove every file matching `._*` from git tracking. Do NOT delete the actual files from disk — just untrack them.

### 2. Add proper `.gitignore`

Create `.gitignore` with:

```
# macOS
._*
.DS_Store
.AppleDouble
.LSOverride

# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg

# Virtual environments
venv/
.venv/
env/
ENV/

# Testing
.pytest_cache/
.coverage
htmlcov/
.tox/

# IDE
.idea/
.vscode/
*.swp
*.swo
*~

# OS
Thumbs.db
ehthumbs.db
Desktop.ini
```

### 3. Delete stale branches

```bash
# Local
git branch -d irregular-v1
git branch -d qgis-export

# Remote
git push origin --delete irregular-v1
git push origin --delete qgis-export
```

### 4. Update README.md

Add these missing items to the architecture table:

| File | Lines | Purpose |
|---|---|---|
| `intake.py` | 126 | Interactive CLI input (rectangle path) |
| `CONSTRAINT_TAXONOMY.md` | — | Constraint classification reference doc |

Also:
- Add `CONSTRAINT_TAXONOMY.md` to the project structure tree
- Add a **## Branches** section explaining the branch strategy (main = stable, feature branches = dev)
- Verify all file line counts in the architecture table are accurate — recount them

### 5. Commit and push

```bash
git add -A
git commit -m "cleanup: remove macOS ._ files, add .gitignore, delete stale branches, update README"
git push origin git-cleanup
```

### 6. Verify

```bash
# No ._ files tracked
git ls-files | grep '^\._' | wc -l   # should be 0

# .gitignore exists
test -f .gitignore && echo "OK"

# All tests still pass
python -m pytest tests/ -q
```

## Do NOT

- Do NOT delete actual `._*` files from disk — just untrack from git
- Do NOT squash or rewrite existing commit history
- Do NOT change any Python source code
- Do NOT touch any test files