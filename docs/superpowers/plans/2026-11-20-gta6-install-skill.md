# gta6-clipping Install Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Install the skill in `~/.claude/skills` and teach the calling session to run it cheaply.
**Architecture:** A bash installer that only creates a symlink; a SKILL.md section; one allow rule in user settings.
**Tech Stack:** bash, pytest (subprocess with a fake HOME).
**Spec:** `docs/superpowers/specs/2026-11-20-gta6-install-skill-design.md`

## Global Constraints
- The installer never deletes or overwrites anything; it exits non-zero with a one-line message if `~/.claude/skills/gta6-clipping` exists and is not a link to this skill folder.
- Paths contain spaces (`progetti in deploy`): every path is quoted.

## Review Focus
1. Existing real directory at the target → refuse, untouched. → `test_install_refuses_existing_dir`
2. Stale link to an old repo location → refuse (the user decides), untouched. → `test_install_refuses_foreign_link`
3. Re-run → no-op, exit 0. → `test_install_is_idempotent`
4. Repo path with spaces → link resolves. → `test_install_links_skill` uses a tmp path with a space.
5. `~/.claude/skills` missing → created. → `test_install_links_skill`

### Task 1: Installer
- Create `skills/gta6-clipping/scripts/install.sh`; test `skills/gta6-clipping/tests/test_install.py` (runs the script with `HOME=<tmp>`, on a copy of the skill folder under a tmp dir whose name has a space).
- [ ] Failing tests (the four above), run → FAIL; implement; run focused + full suite → PASS.
- [ ] Commit `feat: installer that links the skill into ~/.claude/skills`

### Task 2: SKILL.md run rules + install
- [ ] Add "How Claude runs a request" to SKILL.md: run `bash <launcher> <URL> --clips N --fast` with run_in_background; never poll or tail the log while it runs; on the completion notice read only the last ~15 lines; reply with the clip paths, the `tokens:` line and the time; do not open or extract frames from the clips; ~40 min for a full 12 h VOD and ~11 min for a 10-min section. Add `install.sh` to the setup line.
- [ ] Commit `docs: SKILL.md rules for running cheaply from a session`
- [ ] REAL: run `install.sh`; check the link resolves to the SKILL.md; add the user-approved allow rule to `~/.claude/settings.json`.
