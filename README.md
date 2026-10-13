# FrameDiet

**Video in, PNG sequence out — under your size limit, at the best quality that fits.**

FrameDiet turns a video with transparency (or a clip on black/white) into a PNG sequence and automatically
finds the settings that fit a size budget — for HTML5 banners, web animations and game sprites.

## Features

- **Fit to limit** — whole sequence or per frame, in MB or KB. Tries palette 256 → 64 colours, then scale, then (optionally) fewer frames, and keeps the first result that fits.
- **Quality floors** — never go below a chosen scale or number of colours; FrameDiet says so instead of producing mush.
- **Alpha-preserving compression** — libimagequant (the pngquant engine): semi-transparent edges stay smooth.
- **Unmult** — remove a black or white background from footage without alpha (fire, glows, ink, lines).
- **FPS control** — resample to a target frame rate.
- **Auto-crop** — trims empty transparent margins; the offset is written to `_report.json`.
- **Backup image** — a static PNG/JPG under its own KB limit (last, first, middle or fullest frame).
- **Batch** — drop several files or a folder; a summary goes to `_framediet_batch.csv`.
- **File names** — prefix, suffix, separator, first number 0 or 1, number of digits; `{name}` = video name.
- **Presets** — built-in platform presets plus your own saved settings.
- **Preview** — the result loops on checker, white or black.
- **Command line** — `FrameDiet.exe --cli input.mov --limit 500KB --autocrop`.
- **Hotkeys** — Ctrl+O choose videos, Ctrl+Enter start, Esc cancel.
- **Support report** — one click in the log window saves a .txt for support (masked paths, nothing is sent).
- **Light and dark theme**, English and Russian interface.

## Privacy

FrameDiet works offline. It does not send anything anywhere and collects no data.
The support report is only written to a file you choose; you decide whether to share it.
Settings and presets are stored in `%APPDATA%\FrameDiet`.

## Build (Windows)

Run `build.bat`. It creates a virtual environment, installs pinned dependencies, runs the tests, builds
`dist\FrameDiet\FrameDiet.exe` with PyInstaller and, if Inno Setup is available (installed via winget if not),
the installer `dist\FrameDiet-Setup-<version>.exe`.

Run from source: `run_from_source.bat`.

## Command line

```
FrameDiet.exe --cli INPUT [INPUT ...] --limit 2MB [--out DIR] [--fps 12] [--autocrop]
              [--backup 150 --backup-format png|jpg --backup-frame last|first|middle|fullest]
              [--unmult black|white --threshold 5] [--per-frame] [--no-scale] [--drop-frames]
              [--prefix NAME --suffix TEXT --sep _|-|.|none --start 0|1 --digits 2-6]
              [--min-scale 50 --min-colors 128]
```

## License

GPL-3.0-or-later. See `LICENSE` and `THIRD_PARTY_LICENSES.txt`.
