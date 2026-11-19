---
name: gta6-clipping
description: Use when the user wants to turn GTA 6 streams, VODs or live URLs (YouTube, Twitch, Kick) into ready-to-review vertical 9:16 clips with a facecam layout, word-by-word captions, a hook title and streamer credit, or wants to find the biggest GTA 6 streams right now. Clips and a POST.md with caption and hashtags are archived on the USB stick. Claude never posts them.
---

# GTA 6 clipping

Pipeline: audio only -> Whisper transcript + loudness -> Claude picks moments -> download only those minutes -> 9:16 layout (facecam + gameplay) -> hook bar + captions + credit -> archive on the stick.

## Rules

- **Claude never posts.** It produces clips and `POST_<HHMMSS>.md`; the human reviews and publishes.
- Only clip streamers who allow it, always credit them, never use leaked or unlicensed footage.
- The skill writes only inside the archive root and never deletes anything on the stick.

## Commands

`gta6clip` below means the launcher `~/.claude/skills/gta6-clipping/scripts/gta6clip`, run as `bash <launcher> [URL ...] [flags]`.

| Goal | Command |
|---|---|
| One stream, 3 clips | `gta6clip <URL> --clips 3 --fast` |
| Several streams | `gta6clip <URL1> <URL2> --clips 3 --fast` |
| Part of a stream | `gta6clip <URL> --section 2:00:00-4:00:00` (A-B in seconds, m:ss or h:mm:ss) |
| List streams found now | `gta6clip --find --list` |
| Find and clip N streams | `gta6clip --find --streams 7 --clips 3 --fast` |
| Age-restricted / Kick | add `--cookies <browser>`, e.g. `--cookies chrome` |
| Force a layout | `--layout {auto,stream,face,fit}` |
| Redo from scratch | `--redo` (ignores saved stage files) |
| Keep Mac work folder | `--keep-work` |
| Tune parallelism | `--parallel N` (streams), `--pick-parallel N` (Claude pick calls) |
| Pick the model | `--model sonnet` |

`--fast` uses the hardware encoder. With no URL the tool finds streams itself.

## Storage

- Archive root: `CLIP_ARCHIVE` (default `/Volumes/KINGSTOM/Cartella di Claude`).
- Output: `<archive>/gta6-clips/<YYYY-MM-DD>/<@streamer>__<title>/NN.mp4`, plus per run `POST_<HHMMSS>.md`, `clips_<HHMMSS>.json`, `report_<HHMMSS>.json`.
- Live state: `<archive>/gta6-clips/state/`. Whisper cache: `<archive>/models`.
- Work cache on the Mac: `~/gta6-clips/work/`, removed after a successful archive unless `--keep-work`.
- Pre-flight needs the stick mounted, Mac >= 5 GB free, stick >= 2 GB free. It warns when the stick is >80% full.

## Launch-day playbook

1. Plug in the stick (before setup.sh on a fresh install), run `gta6clip --find --list` and pick the biggest streams.
2. First pass on live streams: `gta6clip <URL> --clips 3 --fast`.
3. Re-run live streams every 2-3 h. Saved state resumes where the last run stopped and re-reads a 90 s overlap, so no moment is cut at the boundary. Use `--redo` only if state is corrupt.
4. After each run read `report_<HHMMSS>.json` and the `POST_<HHMMSS>.md`, then review (below).
5. Check the stick usage warning; free space yourself, the skill will not.

## Review checklist before posting

- [ ] Face is inside the cam crop (not cut, not an empty room).
- [ ] Captions are readable and match what is said.
- [ ] The right streamer is credited in the video and in POST.md.
- [ ] No unresolved `⚠` flags in `POST_<HHMMSS>.md` or the report.
- [ ] Clips flagged `non_english` (language unknown or not English) or `low_confidence` (unreliable transcription) show "⚠ needs review" in POST_<HHMMSS>.md: a human must check the captions or skip the clip.
- [ ] Hook title is accurate, not misleading; caption and hashtags are sensible.

Then the human posts. Claude does not.

## Timing (real runs)

- A 12 h YouTube VOD's audio download is throttled to ~240 KiB/s, about 20 min.
- A 10-minute section end to end takes ~11 min for one clip.

## Troubleshooting

- ffmpeg: `brew install ffmpeg-full`; the skill uses it automatically; the doctor run by setup.sh fails if the build lacks the `ass` filter.
- Stick not mounted or too full: pre-flight stops before any work; fix and re-run.
