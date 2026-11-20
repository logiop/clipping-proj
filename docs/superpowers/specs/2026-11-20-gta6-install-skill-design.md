# gta6-clipping: install as a real skill (short design)

Status: approved by the user on 2026-11-20 ("si va bene"). Follows the token-budget work.

## Why
The engine works, but until now it has only been run by hand from the build session. The user wants to ask Claude for clips in any new session ("fammi 3 clip da questo link"). That fresh session is also the only clean way to measure what the skill costs against the 5-hour limit.

## Goals / non-goals / anti-goals
- Goal: Claude Code finds the skill in `~/.claude/skills/gta6-clipping` and runs it from a plain request.
- Goal: the calling session spends as little as possible. It runs the launcher in the background, waits for the completion notice without polling, and reports only the clip paths and the engine's token line.
- Goal: no permission prompt for the launcher, and only for the launcher.
- Non-goal: changes to the engine itself.
- Anti-goal: an installer that overwrites or deletes something already in `~/.claude/skills`.

## Approaches
1. **Symlink to the repo** (picked): follows how the user's other skills are installed. Code edits apply at once. If the repo moves, re-run the installer.
2. Copy into `~/.claude/skills`: survives repo moves, but every change needs a re-copy and two copies drift apart.

## Design
- `scripts/install.sh`: links `~/.claude/skills/gta6-clipping` to the skill folder. If our link is already there, it does nothing. If anything else is at that path, it refuses with a message. It never removes anything.
- `SKILL.md`: a "How Claude runs a request" section with the background/no-polling/short-report rules and the time to expect.
- User settings: one allow rule for `bash <home>/.claude/skills/gta6-clipping/scripts/gta6clip …` (user-approved).
- Check: the user opens a fresh session, reads `/usage`, asks for 3 clips from a link, reads `/usage` again.
