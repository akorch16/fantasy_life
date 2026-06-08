# FL Merge to Production

Merge the current working branch into `main` via a squash PR. Handles conflict resolution automatically.

## When to use

Run `/fl-merge` whenever changes on the current branch are ready for production. Do not push directly to `main`.

---

## Step 1 — Confirm branch

```bash
git status
git branch --show-current
```

If already on `main`, stop and tell the user — there is nothing to merge.

---

## Step 2 — Rebase onto origin/main

```bash
git fetch origin main
git merge origin/main --no-edit
```

If merge succeeds cleanly, proceed to Step 4.

---

## Step 3 — Resolve conflicts (if any)

Check for conflict markers:
```bash
grep -rn "<<<<<<" --include="*.py" --include="*.json" --include="*.html" --include="*.md" .
```

### Conflict resolution rules

| File | Rule |
|---|---|
| `docs/scores.json` | Always take **`origin/main`** — it has the most recent scoring run. Run: `git checkout origin/main -- docs/scores.json` |
| `scoring.py`, `scrapers.py`, `db.py` | Take the **feature branch** version (HEAD) — the branch contains the intentional change |
| `docs/index.html` | Take the **feature branch** version (HEAD) |
| `data/*.json` | Take the **feature branch** version unless it is `scores.json` |
| `data/bonuses.json` | **Manually merge** — both sides may have legitimate additions. Combine all entries. |

After resolving, verify no conflict markers remain:
```bash
python3 -c "import ast; ast.parse(open('scoring.py').read()); print('ok')" 2>/dev/null || true
grep -c "<<<<<<" docs/scores.json || echo "clean"
```

Commit the merge resolution:
```bash
git add -A
git commit -m "merge: resolve conflicts with main"
```

---

## Step 4 — Push the branch

```bash
BRANCH=$(git branch --show-current)
git push -u origin "${BRANCH}"
```

If push fails due to network error, retry up to 4 times with exponential backoff (2s, 4s, 8s, 16s).

---

## Step 5 — Create PR

Use `mcp__github__create_pull_request`:
- `owner`: `akorch16`
- `repo`: `fantasy_life`
- `head`: current branch name
- `base`: `main`
- `title`: infer from the branch name or most recent commit message
- `body`: one-sentence summary of what changed

---

## Step 6 — Squash merge immediately

Use `mcp__github__merge_pull_request` with `merge_method: squash`.

If merge fails with "merge conflicts", go back to Step 2 — the branch diverged further since the push.

Report the merged SHA to the user and confirm production is updated.
