"""Command line: FrameDiet.exe --cli INPUT [INPUT ...] --limit 2MB [options]

Examples:
  FrameDiet --cli intro.mov --limit 500KB --autocrop
  FrameDiet --cli renders/ --limit 2MB --out out/ --fps 12 --backup 150
  FrameDiet --cli intro.mov --limit 2MB --prefix banner --start 1 --digits 3
"""
import argparse
import json
import os
import re
import sys

from . import VERSION, core
from .app import collect_videos
from .i18n import log_line


def parse_size(s):
    m = re.fullmatch(r"\s*([\d.,]+)\s*(kb|mb|k|m)?\s*", s.lower())
    if not m:
        raise argparse.ArgumentTypeError(f"bad size: {s}")
    v = float(m.group(1).replace(",", "."))
    return v / 1024 if (m.group(2) or "mb").startswith("k") else v


def main(argv):
    p = argparse.ArgumentParser(prog="FrameDiet --cli", description=f"FrameDiet {VERSION} command line")
    p.add_argument("inputs", nargs="+", help="video files or folders")
    p.add_argument("--limit", type=parse_size, required=True, help="e.g. 2MB or 500KB")
    p.add_argument("--per-frame", action="store_true", help="limit applies to each frame")
    p.add_argument("--out", default="", help="output folder (single file) or root folder (several)")
    p.add_argument("--fps", type=float, default=None)
    p.add_argument("--max-scale", type=int, default=100)
    p.add_argument("--no-scale", action="store_true")
    p.add_argument("--min-scale", type=int, default=core.MIN_SCALE_DEFAULT, metavar="PCT",
                   help="never scale below this percent (quality floor)")
    p.add_argument("--min-colors", type=int, choices=core.COLOR_STEPS, default=core.MIN_COLORS_DEFAULT,
                   help="never use fewer colours than this (quality floor)")
    p.add_argument("--no-colors", action="store_true")
    p.add_argument("--drop-frames", action="store_true")
    p.add_argument("--unmult", choices=core.KEY_MODES, default="none")
    p.add_argument("--threshold", type=float, default=0, help="unmult threshold, percent")
    p.add_argument("--autocrop", action="store_true")
    p.add_argument("--backup", type=float, default=None, metavar="KB", help="save backup image under KB")
    p.add_argument("--backup-format", choices=("png", "jpg"), default="png")
    p.add_argument("--backup-frame", choices=core.BACKUP_FRAMES, default="last")
    p.add_argument("--prefix", default="", help="file name prefix (default: video name; {name} = video name)")
    p.add_argument("--suffix", default="", help="text after the frame number")
    p.add_argument("--sep", choices=("_", "-", ".", "none"), default="_", help="separator before the number")
    p.add_argument("--start", type=int, choices=(0, 1), default=0, help="first frame number")
    p.add_argument("--digits", type=int, choices=core.NAME_DIGITS, default=4, help="digits in the frame number")
    a = p.parse_args(argv)

    videos = collect_videos(a.inputs)
    if not videos:
        print("no input videos found", file=sys.stderr)
        return 2
    settings = {"limit_mb": a.limit, "per_frame": a.per_frame, "max_scale": a.max_scale,
                "allow_colors": not a.no_colors, "allow_scale": not a.no_scale, "allow_frames": a.drop_frames,
                "min_scale": a.min_scale, "min_colors": a.min_colors,
                "key": a.unmult, "threshold": a.threshold / 100, "out_fps": a.fps, "autocrop": a.autocrop,
                "backup": {"limit_kb": a.backup, "fmt": a.backup_format, "frame": a.backup_frame} if a.backup else None,
                "naming": {"prefix": a.prefix, "suffix": a.suffix, "sep": "" if a.sep == "none" else a.sep,
                           "start": a.start, "digits": a.digits}}
    log = lambda k, **kw: print(log_line(k, **kw), flush=True)  # noqa: E731
    try:
        if len(videos) == 1:
            out = a.out or os.path.splitext(videos[0])[0] + "_png"
            rep = core.run(videos[0], out, log=log, **settings)
            print(json.dumps(rep, ensure_ascii=False, indent=2))
            return 0
        res = core.run_batch(videos, a.out or None, settings, log=log)
        bad = [v for v, ok, _ in res if not ok]
        print(f"{len(res) - len(bad)} of {len(res)} OK")
        return 1 if bad else 0
    except core.FitError as ex:
        floor = ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in ex.floor.items())
        hints = {"frames": "--drop-frames", "scale": "remove --no-scale", "colors": "remove --no-colors"}
        tips = [hints[o] for o in ex.off] + ([f"lower the quality floor ({floor})"] if floor else []) + ["raise --limit"]
        print(f"could not fit the limit: {ex}. Try: " + ", ".join(tips), file=sys.stderr)
        return 1
    except core.BadName as ex:
        print(f"bad file name part: {ex}", file=sys.stderr)
        return 2
