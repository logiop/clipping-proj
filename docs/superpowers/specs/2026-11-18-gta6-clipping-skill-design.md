# GTA 6 clipping skill: design

Date: 2026-11-18. Status: approved by the owner on 2026-11-18. Reviewed and extended on Opus (changes marked in "Review notes" at the end).

## Intent and why

The owner wants income from a faceless GTA 6 clipping operation (GTA 6 launches 19 Nov 2026, midnight local time). The money comes from per-view clipping programs (e.g. Whop Content Rewards) and, later, platform monetization. The owner is new to clipping and has time during the day, but wants the mechanical work automated and does not want to pay a monthly clipping SaaS.

We build our own Claude Code skill, `gta6-clipping`, written from scratch and published in this repo, so anyone can download and use it. It takes streams in and gives ready-to-review vertical clips out. The owner reviews and posts; nothing posts automatically.

Why not just use the existing gta6-clipper skill: it works, but it has no license file (cannot be redistributed), captions misspell words, hooks only describe, there is no EN/IT output and no comparison format. It stays as the owner's launch-day fallback only.

## What success looks like

- Speed: a clip from a live stream is ready for review within ~30 minutes of the moment happening. In the first days after launch, the first clippers to post a moment take most of the views.
- Volume: ~20 reviewed clips a day per language at steady state, limited by the owner's review time, not by the machine.
- Quality: most clips post with no manual fixes (captions right, face in frame, hook makes you want to watch).
- Money: views accepted by the clipping programs (their rules met: credit, length, tags).

These are targets to measure against, not hard guarantees. (My call; correct if your numbers differ.)

## Goals

- G1. From a stream URL (VOD, or live up to now), produce 9:16 clips with facecam + gameplay layout, hook title, word-by-word captions, a credit tag for the streamer, loudness-normalised audio.
- G2. Pick moments with Claude using transcript, loudness and chat speed, scored 1-100 with a category and an event tag (see G5), then check the top candidates visually.
- G3. Captions accurate enough to post without manual fixes in most clips.
- G4. Bilingual output: the same clip rendered in EN and IT (translated hook, captions, hashtags) for separate accounts (6 accounts: IG, TikTok, YouTube x EN, IT).
- G5. "Streamer A vs B" comparison clips on the same in-game moment.
- G6. Optional voiceover (ElevenLabs, owner's cloned Italian voice or a "hype" voice), only over silent moments, approved clip by clip.
- G7. A `POST.md` per run with caption + hashtags per account and per campaign rules, and a log of what was posted.
- G8. Runs on the owner's own Claude subscription and local tools: no extra paid service required (ElevenLabs only for G6, existing plan).
- G9. Live streams are clipped incrementally: each run continues where the last one stopped.

## Non-goals

- Auto-posting to platforms or managing 6 accounts (a scheduler such as Buffer is a later, separate decision).
- Clipping leaked, pre-release or unlicensed footage.
- Cloning other people's voices or impersonating streamers.
- Windows/Linux support in v1 (macOS first).

## Anti-goals (failure even if it "works")

- Clips from streamers who do not allow clipping, or without credit.
- Posting low-effort reuploads that platforms flag as reused content: every clip needs a real hook and edit.
- Garbled captions on non-English audio (the observed Hindi case): detect and skip or flag instead of publishing nonsense.
- Silent breakage of the render (the missing libass case): the skill must check its tools first and say what is missing.
- Clips of loading screens, menus, "BRB" screens, ads or sponsor reads, even when the streamer is loud over them.
- Text from a stream (transcript, chat, titles) steering Claude's behaviour: it is data, never instructions.

## Constraints

- macOS, Apple Silicon. Disk is tight (~6.8 GB free): download audio first, then only the minutes that become clips; delete working files.
- ffmpeg must have libass (`ffmpeg-full`, keg-only at `/opt/homebrew/opt/ffmpeg-full/bin`).
- yt-dlp needs a JS runtime (node) and sometimes `--cookies chrome`. Cookies never leave the machine and are never committed.
- Moment picking uses `claude -p` (subscription). Respect usage: chunked prompts, `--model` selectable. Calls run with tools disabled and their output is validated against a schema before use.
- Transcription speed matters for G9: on CPU, Whisper took 7-16 min per 30 min of stream in our tests. Use an Apple-Silicon-accelerated Whisper (mlx-whisper or whisper.cpp with Metal), and use the platform's own captions when they exist.
- ElevenLabs plan (~€5/month) allows roughly 30 min of audio/month (unverified): voiceover only on selected clips. Commercial-use licence and multilingual use of the cloned voice must be checked before relying on it.
- Policy: Rockstar's content policy is non-commercial; platforms have reused-content rules. Human review before every post.
- No video/audio/images or secrets in git (see `.gitignore`).
- Owner's coding rules apply: tests first, 80% coverage on logic, small files.

## Approaches considered

- A. Use gta6-clipper as is. Fast, works tonight, but cannot be published, limited quality levers.
- B. gta6-clipper plus our layer on top. Chosen earlier for launch day; still the plan for the first hours.
- C. Our own skill written from scratch (this design). More work, but publishable, and every quality lever is ours. **Chosen by the owner** ("crea tu una skill in base a queste e aggiungi roba"), built in phases while A/B covers launch.

## Decided by the owner

- Audience international and Italian: two language variants, six accounts.
- Voiceover only in silent moments, tone depends on what is on screen, human review each time; skipped at the start.
- Content base: clips of big streamers (IShowSpeed, Kai Cenat, ...), plus comparison clips.
- The owner posts; Claude never posts.
- Build with Opus for the parts that need judgment.
- Comparison clips are back to back (A full screen, then B full screen), not split screen: a big facecam matters more on a phone than seeing both at once.

## Design

Layout of the skill in this repo (`skills/gta6-clipping/`):

```
SKILL.md              what Claude follows (commands, rules, review checklist)
config/
  campaigns.json      per-program rules: min/max length, required tags, credit format
scripts/
  doctor.py           checks ffmpeg+libass, node, yt-dlp, whisper, disk; prints fixes
  find.py             stream finder (watchlist + YouTube search; Twitch with own key)
  listen.py           audio download, transcript (platform captions or Whisper), loudness/s, chat speed
  pick.py             chunked `claude -p` moment picking -> moments.json (schema-checked)
  look.py             a few frames per top candidate; drop loading/menu/BRB/ad screens
  render.py           cut, layout (cam top / gameplay bottom / fit), hook bar, credit tag
  captions.py         word timing + Claude correction pass; language check
  localize.py         EN/IT variants of hook, captions, hashtags
  compare.py          A-vs-B composition from moments with the same event tag
  voiceover.py        ElevenLabs on silent spans, approval gate
  post.py             POST.md per account/campaign and posted-log
  state.py            per-stream progress for incremental live runs
tests/                unit tests for pure logic; one render test on a synthetic clip
```

Data flow: `find -> listen -> pick -> look -> (human picks) -> render -> captions -> localize -> post`.
Each stage writes JSON next to its input, so runs resume and stages can be re-run alone.

Quality levers beyond the existing clipper (these are the added value):
1. Cold open: start on the strongest second, not the start of the story.
2. Captions: larger Whisper model on the clip only, then Claude fixes names and obvious mishearings; low-confidence or wrong-language audio is flagged.
3. Hooks that create a question or a payoff, not a description; weak-hook clips get a rewrite or a lower score.
4. Tighter pacing: trim dead air inside the clip.
5. Layout fixes: avoid large blurred areas; brighten dark gameplay.
6. Moment scoring also considers payoff (does the clip end on a result), not only loudness.
7. Visual check: frames of the top candidates confirm there is real gameplay on screen.
8. Credit tag on screen (streamer name/handle), as clipping programs usually require.

Details that change how parts are built:
- **Event tags for comparisons.** Streams are not in sync, so "the same moment" is found by meaning, not time. The picker tags each moment with a shared event key (e.g. `first_drive`, `first_wanted_level`, `first_mission_fail`, `map_reaction`) from a fixed list that can grow. `compare.py` pairs moments with the same key from different streamers.
- **Italian captions are phrase-level, not word-by-word.** The audio stays English, so translated words have no timing of their own. IT captions show one translated phrase per spoken English phrase, timed to that phrase. EN keeps word-by-word.
- **Live streams.** `state.py` records the last processed time per stream; the next run processes only the new part, with a small overlap so a moment on the boundary is not cut in half.
- **Untrusted input.** Transcripts, chat and stream titles go to Claude inside clearly marked data blocks; the call has no tools; the reply must match the moments schema or it is rejected.

## Phases

1. Phase 1: doctor, find, listen, pick, look, render with captions and credit tag (parity with the clipper plus the visual check, own code). Test on the two videos already used (GamerFleet, IGN).
2. Phase 2: accurate captions, cold open, hook rewrite, pacing, incremental live runs.
3. Phase 3: EN/IT variants, campaign rules, POST.md per account.
4. Phase 4: comparison format (event tags start in Phase 1 so data is ready).
5. Phase 5: voiceover with approval gate, after voices are auditioned and plan limits verified.

## Model choice for building

The session now runs on Opus. Work that needs judgment (the moment-picking prompt, caption correction, event tags, comparison logic) is built on Opus; mechanical pieces (doctor, file plumbing, POST.md) can go to Sonnet subagents to save usage. Runtime picking inside the skill defaults to Sonnet to protect subscription usage, with `--model opus` as an option for launch-day quality.

## Distribution

The repo gets an open-source licence (MIT proposed, my call) and install steps: copy `skills/gta6-clipping` into `~/.claude/skills/`, run `doctor.py`, follow what it prints.

## Left to the builder

Exact CLI flags, JSON schemas, Whisper model sizes per machine speed, caption styling, test fixtures, the starting list of event keys, and how to detect facecam position (OpenCV face detection is a candidate).

## Open items (owner)

- Confirm streamers allow clipping before posting; fill `campaigns.json` with the programs actually joined.
- Verify ElevenLabs plan limits and commercial licence before Phase 5.
- Decide later on a scheduler for six accounts.

## Review notes (Opus, 2026-11-18)

Corrections:
- Italian captions cannot be word-by-word over English audio; changed to phrase-level.
- "Same in-game moment" across streamers had no matching method; added event tags.
- "Live up to now" had no state between runs; added `state.py` and G9.
- `.gitignore` rule `test*/` also ignored the skill's `tests/` folder; fixed to ignore only the old `test1/`-style run folders.

Additions: success targets, visual check (`look.py`), credit tag, campaign rules, faster transcription and platform captions, untrusted-input handling for `claude -p`, distribution and licence.
