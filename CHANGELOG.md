# Changelog

## 1.2.0-beta.3 — 2026-10-12
- File names: new "Names" tab — prefix (default: video name, `{name}` token), suffix, separator (`_` `-` `.` none),
  first number 0 or 1, 2–6 digits (widened automatically if frames need more), live example.
- Re-running into the same folder removes only the files of the previous run (listed in `_report.json`).
- `_report.json` now lists the written files and the naming used.
- Command line: `--prefix`, `--suffix`, `--sep`, `--start`, `--digits`.
- Quality floors: "Fewer colours, down to 128/96/64" and "Smaller scale, down to 90–25%" in the Size tab.
  If nothing fits above the floor, FrameDiet stops and says which floor blocked it instead of producing mush.
  `_report.json` records the floors; CLI `--min-scale`, `--min-colors`.
- Hotkeys: Ctrl+O choose videos, Ctrl+Enter start, Esc cancel (or close the log). Work with the Russian layout too;
  hints shown in the drop area, status line and on the button while working.
- "Save report for support…" in the log window: one .txt with version, OS, library versions, settings, video
  file names, last result and the log (errors and tracebacks included). Home folder masked as ~, full video paths
  removed. Nothing is sent anywhere.
- Dark theme (design A in graphite): Light / Dark switch next to EN / RU, remembered between runs.
- Fixed: hints in empty fields (prefix, suffix, output) were never shown; disabled buttons now look disabled.
- "Doesn't fit" now tells the smallest size reached vs the limit and suggests only what can still help
  (drop frames, scale, colours, lower floor, raise the limit). CLI prints the same hints.
- Paths picked in dialogs are shown Windows-style (E:\folder instead of E:/folder).

## 1.2.0-beta.2 — 2026-10-10
- New light interface (design A "Paper & Graphite"): large preview on the left that doubles as the drop target,
  settings column on the right, result figures under the preview, log in a separate window.
- Bundled Inter typeface (SIL OFL 1.1) for a consistent look on every machine.
- Dark-knob switches readable on light backgrounds; preset row with a compact delete button.

## 1.2.0-beta.1 — 2026-10-10
- Renamed to FrameDiet (formerly WUS PNG Sequencer).
- Auto-crop of transparent margins with offset in `_report.json`.
- Backup image (PNG/JPG) under its own KB limit; first/last/middle/fullest frame.
- Batch processing of several files or a folder, `_framediet_batch.csv` summary.
- Presets: built-in Google Ads HTML5, user presets (save/delete).
- English (default) and Russian UI; settings remembered.
- Command line: `FrameDiet.exe --cli …`.
- ~2× faster frame quantization.
- Windows installer (Inno Setup, no admin rights), PyInstaller one-folder build, GitHub Actions workflow.

## 1.1 (WUS PNG Sequencer) — 2026-10-10
- Output FPS control.

## 1.0 (WUS PNG Sequencer) — 2026-10-10
- Fit a PNG sequence under a size limit (palette, scale, frame thinning), Unmult black/white, preview.
