---
description: Workflow for Git and Github
---

We use a variant of the [Github Flow](https://docs.github.com/en/get-started/using-github/github-flow) workflow to manage Git for the project.

### Expectations
- The `main` branch is always deployable.
- All threads of work on the project are documented in Github issues.  Issues are created in advance to capture defects or enhancments; or created to document work done.
- Branches are named `<type>/<issue>-<short-description>`: the prefix is `feature/`, `fix/` or `chore/` (for non-code changes), followed by the primary issue number and a short description, for example `feature/41-openrouter-evaluation`.  (In the case that a PR resolves multiple issues, the number of the most relevant issue is adequate in the branch name.)
- All incremental work is done on branches named this way, never directly on `main`.
- Only main is deployed. Production deploys run from the primary checkout on a clean, up-to-date main via scripts/deploy.sh; feature branches are synthesized only in unreleased mode for review and never deployed.
- When work is ready for review, a pull request should be created and reference the issue or issues related to the work using the appropriate keyword.  (See [how to reference issues from a PR](https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/linking-a-pull-request-to-an-issue).).

### Worktrees
- **The primary checkout stays on `main`.** Update it only with `git fetch` followed by `git merge --ff-only origin/main`. Never commit, switch branches or edit files there.
- **Do all branch work in a worktree under `.worktrees/`.** Create one per branch from an up-to-date `origin/main`, named after the branch with `/` replaced by `-`: `git worktree add .worktrees/<type>-<issue>-<short-description> -b <type>/<issue>-<short-description> origin/main`. Run builds, tests and commits from inside the worktree.
- **Clean up after a merge.** Fast-forward the primary checkout, then remove the merged worktree (`git worktree remove .worktrees/<name>`) and delete its local branch.
- **Leave stray changes alone.** If uncommitted or staged changes appear in the primary checkout, do not commit or discard them; move them into a worktree or ask before removing them.
- **Check out other people's branches separately.** Review checkouts and branches owned by someone else go in their own worktree, added detached (`git worktree add --detach .worktrees/review-<pr> <sha>`), and are removed when done.

### PR Reviews and Approvals
- PR reviews will be performed either by another agent (e.g., a different AI coding agent or Github copilot) or by a human.
- Updates to address feedback on the PR may be requested by a human.
- All PR approvals will be provided by a human.