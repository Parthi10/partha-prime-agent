# Session prompt template

Copy this prompt to open a new coding session on this repository. Fill in the
placeholders (`<...>`) before sending it. This prompt exists to make every session
start from the same disciplined baseline regardless of who or what is running it.

See also: [../docs/development/CLAUDE_CODE_RULES.md](../docs/development/CLAUDE_CODE_RULES.md),
[HANDOVER_TEMPLATE.md](HANDOVER_TEMPLATE.md), [DEVELOPMENT_CHECKLIST.md](DEVELOPMENT_CHECKLIST.md).

---

## Prompt

```
Continue working in the current repository and current branch.

Before doing anything else:
1. Read PROJECT_STATE.md in the repository root. It is the source of truth for what
   has been done, what is in progress, and what is next.
2. Run `git branch --show-current` and `git status` and `git diff --stat`. Confirm the
   branch matches PROJECT_STATE.md's stated current branch: <current branch>. If it
   does not match, or if there is uncommitted work you did not expect, stop and report
   what you found before proceeding.
3. Read docs/development/CLAUDE_CODE_RULES.md and follow it for the rest of this
   session.

Preserve all existing work:
- Do not discard, reset, restore, overwrite, or delete any existing uncommitted work.
- Do not commit, push, open a pull request, or merge unless explicitly asked to in
  this prompt.
- The user performs the final merge -- never merge a branch yourself.

Current milestone: <current milestone number and name>

Requirements for this session:
<paste the specific requirements/scope for this session here -- be as concrete as the
milestone's own architecture-doc scope statement. Name explicitly what is in scope and
what is not.>

Constraints:
- Work only on the current milestone above. Do not implement functionality that
  belongs to a later milestone, even if it would be a natural extension of this work.
- Review docs/development/PROJECT_ARCHITECTURE.md and the current milestone's
  docs/architecture/milestone-N.md before making changes, so new work is consistent
  with what already exists.
- Never expose, persist, or log credentials or access tokens.
- Never execute untrusted repository code (no running a scanned/cloned repository's
  own tests, setup scripts, Makefiles, migrations, or startup commands).
- Never install dependencies from a repository being scanned or cloned.

Before reporting this session's work as complete, run and report the results of:
  ruff check .
  pyright
  pytest -q
  docker compose config
  git status

Required report at the end of this session:
<list exactly what you want reported -- typically: files created, files modified,
exact test count, verification command results, assumptions made, risks/gaps
remaining, and confirmation that nothing was committed/pushed/merged unless
explicitly authorized above>

Do not commit, push, create a pull request, or merge without explicit permission in
this prompt. Stop and wait for approval once the above report is delivered.
```

---

## Notes for whoever fills in the placeholders

- **Current branch**: copy from `PROJECT_STATE.md`'s "Current branch" field, or run
  `git branch --show-current` yourself first.
- **Current milestone**: copy from `PROJECT_STATE.md`'s "Current milestone" field.
- **Requirements**: be as explicit as the requirements given for Milestones 1-4 were --
  a scoped list of what to build, what security properties must hold, and what must
  explicitly NOT be built yet (see
  [../docs/development/MILESTONE_GUIDELINES.md](../docs/development/MILESTONE_GUIDELINES.md)).
- **Required report**: if unsure what to ask for, default to the list in
  [HANDOVER_TEMPLATE.md](HANDOVER_TEMPLATE.md) -- it's the same information a human
  reviewer would want.
- If this is the very first session on a new milestone (no branch exists yet), add an
  explicit instruction for whether the agent should create
  `feature/milestone-N-description` from `develop` itself, or whether you'll do that
  first (see
  [../docs/development/DEVELOPMENT_WORKFLOW.md](../docs/development/DEVELOPMENT_WORKFLOW.md#when-to-create-a-branch)).
