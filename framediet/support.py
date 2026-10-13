"""Support report: one plain-text file with everything needed to understand a problem.

Created only when the user presses the button; nothing is ever sent anywhere.
The user's home folder is masked as "~" and only file names (not full paths) of videos are included.
"""
import datetime
import json
import os
import platform
import sys

from . import APP_NAME, VERSION


def _versions():
    from importlib import metadata
    out = {}
    for dist, mod in (("customtkinter", "customtkinter"), ("Pillow", "PIL"), ("numpy", "numpy"),
                      ("imagequant", "imagequant"), ("imageio-ffmpeg", "imageio_ffmpeg"), ("tkinterdnd2", "tkinterdnd2")):
        try:
            out[dist] = metadata.version(dist)
        except Exception:  # frozen builds may lack metadata: fall back to the module attribute
            try:
                out[dist] = getattr(__import__(mod), "__version__", "?")
            except Exception:
                out[dist] = "not available"
    try:
        import imageio_ffmpeg
        out["ffmpeg"] = imageio_ffmpeg.get_ffmpeg_version()
    except Exception:
        out["ffmpeg"] = "?"
    return out


def mask_home(text):
    """Replace the user's home folder (it contains the user name) with ~."""
    home = os.path.expanduser("~")
    if home and len(home) > 3:
        text = text.replace(home, "~").replace(home.replace("\\", "/"), "~")
    return text


def _strip_paths(obj):
    """Keep only base names for anything that looks like a path inside the last run report."""
    if isinstance(obj, dict):
        return {k: _strip_paths(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_strip_paths(v) for v in obj]
    if isinstance(obj, str) and (os.sep in obj or "/" in obj) and len(obj) > 2:
        return os.path.basename(obj.rstrip("/\\"))
    return obj


def make_report(settings, videos, video_info=None, last_report=None, log_lines=(), status="", lang="en",
                ui_scaling=None, now=None):
    """Return the report text. log_lines are already formatted strings."""
    now = now or datetime.datetime.now()
    lines = [
        f"{APP_NAME} support report",
        f"Created: {now:%Y-%m-%d %H:%M:%S}",
        "This file was created on your request and has NOT been sent anywhere.",
        "Read it before sharing: it contains settings, video file names and the log of the last run.",
        "",
        "== Program ==",
        f"{APP_NAME} {VERSION}",
        f"OS: {platform.platform()}",
        f"Python: {sys.version.split()[0]} ({platform.architecture()[0]})",
        f"Language: {lang}",
    ]
    if ui_scaling:
        lines.append(f"UI scaling: {ui_scaling:g}")
    lines += [f"{k}: {v}" for k, v in _versions().items()]

    lines += ["", "== Status ==", status or "-"]

    lines += ["", "== Input =="]
    if videos:
        lines += [f"{i + 1}. {os.path.basename(v)}" for i, v in enumerate(videos)]
    else:
        lines.append("-")
    if isinstance(video_info, dict):
        lines.append("First video: " + json.dumps(video_info, ensure_ascii=False))

    lines += ["", "== Settings ==", json.dumps(settings or {}, ensure_ascii=False, indent=2)]

    lines += ["", "== Last result (_report.json) =="]
    if last_report:
        rep = dict(last_report)
        files = rep.pop("files", None)
        if files:
            rep["files"] = f"{len(files)} files, {files[0]} … {files[-1]}"
        lines.append(json.dumps(_strip_paths(rep), ensure_ascii=False, indent=2))
    else:
        lines.append("-")

    lines += ["", "== Log of the last run =="]
    lines += list(log_lines) or ["-"]
    return mask_home("\n".join(lines)) + "\n"


def default_name(now=None):
    now = now or datetime.datetime.now()
    return f"FrameDiet_support_{now:%Y%m%d_%H%M%S}.txt"
