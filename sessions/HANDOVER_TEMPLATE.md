# Session handover template

Fill this in at the end of every session that changes code or documentation in this
repository, and keep it (or a link to it) alongside `PROJECT_STATE.md` so the next
session can pick up without re-deriving context. See
[../docs/development/MILESTONE_GUIDELINES.md](../docs/development/MILESTONE_GUIDELINES.md#handover-process-before-starting-the-next-milestone)
for when this is required.

---

## Handover: `<short title, e.g. "Milestone 4 documentation pass">`

**Date**: `<date>`

### Current branch

```
<output of: git branch --show-current>
```

### Current commit

```
<output of: git log -1 --oneline>
```

(Note separately if there are uncommitted changes on top of this commit -- see
"Uncommitted changes" below; this field is the last *committed* state only.)

### Current milestone

`<milestone number and name, e.g. "Milestone 4: Scanner Runtime">` -- status:
`<not started / in progress / implemented and locally verified, not yet committed /
committed, not yet pushed / pushed, PR open / merged>`

### Completed work

`<bulleted summary of what was actually built/changed this session -- be specific
about which files/behaviors, not just "implemented the feature">`

### Modified files

```
<output of: git diff --stat (or git status, if everything is new/untracked)>
```

### Created files

`<list of new files, grouped by directory, e.g.:>`
- `docs/development/...`
- `sessions/...`

### Tests run

`<exact commands run, e.g.:>`
```
ruff check .
pyright
pytest -q
docker compose config
```

### Exact test count

`<the literal number reported by pytest, e.g. "118 passed">` -- do not round or
approximate; paste the actual summary line.

### Known issues

`<bugs, gaps, or quirks discovered but not fixed this session -- e.g. the Alembic
KeyError: 'formatters' issue documented in
docs/operations/TROUBLESHOOTING.md#alembic-migration-commands-fail-with-keyerror-formatters>`

### Remaining risks

`<anything that works today but is fragile, incomplete, or depends on an assumption --
mirror the "Remaining risks / known limitations" style used in
docs/architecture/milestone-N.md files>`

### Uncommitted changes

`<state plainly whether there are uncommitted changes in the working tree right now,
and whether they are from this session or were already present at the start of it.
Never imply "clean" if git status shows otherwise.>`

### Next recommended step

`<the single most useful thing the next session should do -- e.g. "review this diff
and, if satisfied, commit and push feature/milestone-N-... then open a PR to develop"
or "begin Milestone 5 scope definition">`

### Commands the next session should run first

```bash
git branch --show-current
git status
git diff --stat
cat PROJECT_STATE.md
```

Then follow [SESSION_PROMPT.md](SESSION_PROMPT.md) with the current branch/milestone
filled in from this handover and `PROJECT_STATE.md`.
