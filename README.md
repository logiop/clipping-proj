# clipping-proj: faceless GTA 6 clipping, mostly automated

Turn long GTA 6 streams into ready-to-post vertical clips (TikTok, Reels, Shorts) with
**Claude Code doing the heavy lifting** and no monthly clipping-SaaS fee. You only review and post.

> 🇮🇹 Progetto per creare clip verticali di GTA 6 dagli stream dei migliori streamer, quasi tutto automatico.
> Claude sceglie i momenti, tu controlli e pubblichi. Vedi sezione "Italiano" in fondo.

## How it works

```
stream URL ─► audio only ─► Whisper transcript + loudness + chat speed
          ─► Claude picks the best moments (score 1-100, hook title)
          ─► download only those minutes ─► 9:16 layout (facecam + gameplay)
          ─► hook bar + word-by-word captions ─► POST.md with caption + hashtags
```

The engine is the `gta6-clipping` Claude Code skill in `skills/gta6-clipping/` (stream finder, moment picker,
renderer, USB archive). Clips are archived on a USB stick; Claude never posts anything.

## What is in this repo

| Path | What |
|---|---|
| `skills/gta6-clipping/` | The skill: `SKILL.md`, `scripts/`, `prompts/`, `config/`, tests |
| `tools/peaks.py` | Ranks highlight windows from per-second loudness plus scene-cut density. Usage: `python3 -I tools/peaks.py rms.txt scenes.txt [top_n]` |
| `streamers.txt` | Watchlist (Kai Cenat, IShowSpeed, xQc, ...). Shipped with the skill as `skills/gta6-clipping/streamers.txt` |

Two other skills we evaluated and did not adopt: `melvynx/clips` (transcript-based, needs a separate editing skill) and `fabriqaai/ffmpeg-analyse-video` (frame extraction plus sub-agents, too heavy for hours of stream).

`gta6-clipper/` (the earlier third-party skill) is **not included** (no license file); it is git-ignored on purpose
and the new skill does not depend on it.

## Install (macOS)

```bash
brew install ffmpeg-full node      # ffmpeg needs libass for captions; ffmpeg-full is keg-only
cp -R skills/gta6-clipping ~/.claude/skills/
bash ~/.claude/skills/gta6-clipping/scripts/setup.sh   # private env in ~/.gta6-clipping, Whisper models
```

Then plug in the USB stick (default archive `/Volumes/KINGSTOM/Cartella di Claude`, override with `CLIP_ARCHIVE`).
Requirements: Claude Code (picking runs on your own subscription), Mac >= 5 GB free, stick >= 2 GB free.

## Run

```bash
export PATH="/opt/homebrew/opt/ffmpeg-full/bin:$PATH"
G=~/.claude/skills/gta6-clipping/scripts/gta6clip
bash $G "<STREAM_URL>" --clips 3 --fast
bash $G --find --list                      # biggest GTA streams right now
bash $G --find --streams 7                 # ~21 clips
bash $G <URL> --section "2:00:00-4:00:00"  # part of a stream
```

Output: `<archive>/gta6-clips/<YYYY-MM-DD>/<@streamer>__<title>/NN.mp4` plus `POST_<HHMMSS>.md`,
`clips_<HHMMSS>.json`, `report_<HHMMSS>.json`. Live state is in `<archive>/gta6-clips/state/`; the Mac work
cache `~/gta6-clips/work/` is removed after a successful archive (`--keep-work` keeps it). The skill writes only
inside the archive root and never deletes anything on the stick. Age-restricted YouTube and Kick need `--cookies chrome`.
See `skills/gta6-clipping/SKILL.md` for the launch-day playbook and review checklist.

### Gotchas we hit
- `No such filter: 'ass'`: Homebrew's plain ffmpeg has no libass. Use `ffmpeg-full` on PATH as above.
- Installing `ffmpeg-full` can upgrade x265 and break plain `ffmpeg`; fix with `brew reinstall ffmpeg`.
- Non-English streamers (e.g. Hindi) give garbled captions; Whisper `base` also mishears words.
- Layout `fit` leaves big blurred areas; dark gameplay clips look dull.

## Roadmap (approach B: use the clipper, add our layer step by step)

1. **Launch (19 Nov 2026):** run the skill, review every clip, post.
2. More accurate captions (bigger Whisper model plus a Claude correction pass).
3. Bilingual output: EN and IT versions (translated hook, captions, hashtags) for separate accounts.
4. Cold open on the strongest moment, tighter pacing, better layouts.
5. "Streamer A vs streamer B" comparison format.
6. Optional ElevenLabs voiceover, only over silent moments, always human-approved.

## Rules of the road (money and risk)

- Monetization is via clipping programs (e.g. Whop Content Rewards, per-view pay). Rates vary and are capped.
- **Only clip streamers who allow it**, credit them, and never post leaked or unlicensed footage.
- Rockstar's content policy is non-commercial; platforms flag reused content. Add real value (hooks, edits, commentary).
- You review and publish each clip. Nothing here posts for you.

## Italiano

Pipeline: scarichi solo l'audio dello stream, Whisper lo trascrive, Claude sceglie i momenti migliori,
vengono scaricati solo quei minuti e montati in 9:16 con facecam, titolo hook e sottotitoli parola per parola.
Installazione: copia `skills/gta6-clipping` in `~/.claude/skills/`, esegui `bash ~/.claude/skills/gta6-clipping/scripts/setup.sh`
e collega la chiavetta USB: le clip finiscono lì (`<archivio>/gta6-clips/<data>/`), mai altrove, e la skill non cancella nulla sulla chiavetta.
Il piano: lancio con la skill così com'è, poi sottotitoli più precisi, versioni EN/IT per account separati,
formato "streamer A vs B" e, per ultimo, voiceover ElevenLabs solo sui silenzi con approvazione umana.
Clippa solo streamer che lo permettono, citali, e controlla ogni clip prima di pubblicare. Claude non pubblica mai.
