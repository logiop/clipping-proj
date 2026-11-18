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

The engine is the community skill **gta6-clipper** (stream finder, moment picker, renderer).
This repo is the layer around it: tests, tools, the watchlist, and the roadmap.

## What is in this repo

| Path | What |
|---|---|
| `tools/peaks.py` | Ranks highlight windows from per-second loudness plus scene-cut density. Usage: `python3 -I tools/peaks.py rms.txt scenes.txt [top_n]` |
| `streamers.txt` | Watchlist (Kai Cenat, IShowSpeed, xQc, ...). Copy to `~/gta6-clips/streamers.txt` |

Two other skills we evaluated and did not adopt: `melvynx/clips` (transcript-based, needs a separate editing skill) and `fabriqaai/ffmpeg-analyse-video` (frame extraction plus sub-agents, too heavy for hours of stream).

`gta6-clipper/` is **not included** (third-party code with no license file). Get the skill from its
original source and place it next to this README as `gta6-clipper/`; it is git-ignored on purpose.

## Setup (macOS)

```bash
brew install ffmpeg-full node      # ffmpeg needs libass for captions; ffmpeg-full is keg-only
bash gta6-clipper/scripts/setup.sh # private env in ~/.gta6-clipper, Whisper models (~0.4 GB)
```

Requirements: Claude Code (the picking runs on your own subscription), ~7 GB free disk.

## Run

```bash
PATH="/opt/homebrew/opt/ffmpeg-full/bin:$PATH" \
bash gta6-clipper/scripts/gta6clip "<STREAM_URL>" --clips 3 --fast --model sonnet
bash gta6-clipper/scripts/gta6clip --find --list        # biggest GTA streams right now
bash gta6-clipper/scripts/gta6clip --find --streams 7   # ~21 clips
bash gta6-clipper/scripts/gta6clip <URL> --section "2:00:00-4:00:00"   # part of a stream
```

Output lands in `~/gta6-clips/<date>/<streamer>__<title>/` (clips, `POST.md`, `clips.json`).
Age-restricted YouTube and Kick need `--cookies chrome`.

### Gotchas we hit
- `No such filter: 'ass'`: Homebrew's plain ffmpeg has no libass. Use `ffmpeg-full` on PATH as above.
- Installing `ffmpeg-full` can upgrade x265 and break plain `ffmpeg`; fix with `brew reinstall ffmpeg`.
- Non-English streamers (e.g. Hindi) give garbled captions; Whisper `base` also mishears words.
- Layout `fit` leaves big blurred areas; dark gameplay clips look dull.

## Roadmap (approach B: use the clipper, add our layer step by step)

1. **Launch (19 Nov 2026):** run the clipper as is, review every clip, post.
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
Il piano: lancio con il clipper così com'è, poi sottotitoli più precisi, versioni EN/IT per account separati,
formato "streamer A vs B" e, per ultimo, voiceover ElevenLabs solo sui silenzi con approvazione umana.
Clippa solo streamer che lo permettono, citali, e controlla ogni clip prima di pubblicare.
