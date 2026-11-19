# GTA 6 clipping: storage on the USB stick (short design)

Status: draft, awaiting approval. Amends `2026-11-18-gta6-clipping-skill-design.md` and the Phase 1 plan.

## Why

The Mac's internal disk has 17 GB free out of 228 GB (91% full). The user plugged in a 256 GB stick
(`/Volumes/KINGSTOM`, always attached) and created `Cartella di Claude` for the skill's files.

## Facts measured on 2026-11-19

- File system FAT32: max 4 GB per file; no symlinks; `: ? " / \ * < > |` not allowed in names.
- Write ~7 MB/s, read ~39 MB/s. 153 GB free.
- Holds the user's personal folder `foto video NON TOCCARE`.

## Goals / anti-goals

- Goal: the Mac's disk does not fill up; working is as fast as possible.
- Anti-goal (hard): the skill never reads, writes, moves or deletes anything outside
  `/Volumes/KINGSTOM/Cartella di Claude`. Losing the photo folder is the worst possible failure.

## Approaches

1. **Mac is the workbench, stick is the archive** — picked by the user. Fast (heavy writes on the SSD),
   Mac stays clean because the work folder is emptied after every run.
2. Everything on the stick — rejected: every write at 7 MB/s, rendering several times slower.
3. Reformat the stick to APFS/exFAT — rejected: means moving 94 GB of personal photos, does not fix speed.

## Design

| What | Where |
|---|---|
| venv, YuNet model, code | Mac `~/.gta6-clipping/` (venv cannot live on FAT32) |
| Work cache (audio, previews, 1080p sections, frames, temp renders, stage JSON) | Mac `~/gta6-clips/work/<stream-id>/` |
| Finished clips, POST.md, clips.json, report.json | Stick `Cartella di Claude/gta6-clips/<YYYY-MM-DD>/<streamer>__<slug>/` |
| Live resume state (`state.json`) | Stick `Cartella di Claude/gta6-clips/state/<stream-id>.json` |
| Whisper model cache (`HF_HOME`) | Stick `Cartella di Claude/models/` |
| User's own source video | Read in place, never copied |

- One config root: `CLIP_ARCHIVE` (default `/Volumes/KINGSTOM/Cartella di Claude`). All archive paths derive from it.
- **Path guard:** a single `safe_archive_path()` resolves every path written or deleted under the archive and refuses
  anything not inside `CLIP_ARCHIVE` (after resolving `..`). Tested.
- **Pre-flight (doctor + start of each run):** stop with a clear message if the stick is not mounted,
  if Mac free < 5 GB, or stick free < 2 GB. Never fall back to writing archive files on the Mac.
- **4 GB guard:** before copying to the stick, refuse any file > 4 GB with a clear message.
- **Name sanitizing:** folder/file names stripped of FAT32-illegal characters.
- **Copy then clean:** finished files are copied to the stick, size-verified, then the Mac work folder for that
  stream is deleted. Work folder is kept if the run failed, so a re-run resumes.
- **Cleanup:** never automatic. When the stick passes 80% full, the run prints a warning. Cleanup of
  `Cartella di Claude` happens only when the user asks.

## Left to the builder

Exact constant names, how `HF_HOME` is passed to faster-whisper/mlx-whisper, copy implementation.
