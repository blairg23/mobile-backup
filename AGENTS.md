# AGENTS.md -- mobile-backup

Agent workflow guide. Read this before touching anything.

---

## What this is

A single CLI that moves photos/videos from a desktop staging area into a
month-span Google Drive folder: renames by EXIF/filename datetime, verifies
files exist in Dropbox Camera Uploads, dedupes by content, and sweeps junk.
See `README.md` for the full pipeline and configuration.

## Commands

```bash
poetry run python mobile_backup.py run            # full pipeline
poetry run python mobile_backup.py rename          # standalone: rename images in rename_tool_input
poetry run python mobile_backup.py organize         # standalone: verify/sync desktop_mobile_camera <-> dropbox_camera_uploads
poetry run python mobile_backup.py playground       # generate a synthetic source tree + scratch config for a safe rehearsal
poetry run python cleanup_folder.py <span> [--apply]  # post-run audit/cleanup
```

`run`/`rename`/`organize` accept `--config PATH` to target a config file other than
`config.yaml` (default) -- used by `playground` to keep rehearsals fully separate
from real config.

## Development

```bash
poetry install --with dev
poetry run pytest             # tests only
poetry run tox                # full gate: format check, lint, type, coverage
poetry run tox -e format      # auto-format (black + ruff --fix)
```

---

## GitHub operations go through repo-scaffold

This repo is managed by [repo-scaffold](https://github.com/blairg23/repo-scaffold). Never call
`gh` CLI directly for issues, PRs, branches, or project boards -- use
`poetry run repo-scaffold <command>` from the repo-scaffold checkout.

## Branch naming

Format: `type/NNN-short-description`

- `type`: `feat`, `fix`, `docs`, `chore`, `refactor`, `test`
- `NNN`: the GitHub issue number -- create the issue first if one does not exist
- `short-description`: kebab-case, 3-4 words max

Examples: `feat/28-consolidate-cli`, `fix/31-crash-on-load`

`master` is the only long-lived branch. Never reuse a branch after its PR has merged.

---

## PR titles

Format: `type(scope): description (#NNN)`

Example: `feat(cli): fold image-renamer and files-in-folder logic into mobile-backup (#28)`

The issue number at the end is required so the PR is immediately traceable to its ticket.

---

## Workflow rules

- Create a GitHub issue before starting work so you have the `NNN` for the branch name.
- Always use the PR template (`.github/pull_request_template.md`) -- no freeform bodies.
- Always use the issue templates (`.github/ISSUE_TEMPLATE/ticket.md` or `epic.md`).
- After creating an issue, add it to the `mobile-backup Roadmap` project board.
- Never merge or close PRs -- push the branch, open the PR, stop there.
- Never push new commits to a branch whose PR is already merged -- cut a fresh branch from master.

---

## Git identity

Before your first commit, confirm `git config user.name` and `git config user.email` are
set to real values (not `Your Name` / `you@example.com`). If they are placeholders, stop
and ask the user to configure them before continuing.

---

## Commit messages

Format: subject line (imperative mood) + blank line + body.

- Subject: 50 chars max, no trailing period
- Body: explain WHY the change is needed, not what it does (the diff shows what)
- No one-liner commits for non-trivial changes
