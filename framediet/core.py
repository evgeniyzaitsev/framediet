"""FrameDiet engine: video (with alpha) -> PNG sequence that fits a size limit.

Pipeline per attempt:
  1. ffmpeg extracts RGBA frames (fps resample, thinning, scale)
  2. optional Unmult (black/white background -> alpha)
  3. optional auto-crop of transparent margins (one box for the whole sequence)
  4. libimagequant palette quantization with full alpha (the pngquant / TinyPNG engine)
If the result is over the limit: fewer colours, then smaller scale, then (optionally) fewer frames.

All user-visible messages go through the `log` callback as (key, params) so the GUI can translate them.
"""
import io
import json
import os
import re
import shutil
import subprocess
import tempfile

import imageio_ffmpeg
import imagequant
import numpy as np
from PIL import Image

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
NO_WINDOW = 0x08000000 if os.name == "nt" else 0  # no console flash on Windows

SCALE_STEPS = [100, 90, 80, 70, 60, 50, 45, 40, 35, 30, 25]
COLOR_STEPS = [256, 128, 96, 64]
KEY_MODES = ("none", "black", "white")
BACKUP_FRAMES = ("last", "first", "middle", "fullest")
ALPHA_CUTOFF = 3  # alpha <= this counts as empty when auto-cropping


class Cancelled(Exception):
    pass


class FitError(Exception):
    """Nothing fits the limit.

    floor     — dict(min_scale, min_colors): user floors raised above the defaults that stopped the search early
    best      — smallest size reached in bytes (estimate or real), None if unknown
    off       — search options that were switched off and could still help: "frames", "scale", "colors"
    per_frame — the limit applies to each frame"""

    def __init__(self, limit, floor=None, best=None, off=(), per_frame=False):
        super().__init__(limit)
        self.limit = limit
        self.floor = floor or {}
        self.best = best
        self.off = list(off)
        self.per_frame = per_frame

    def __str__(self):
        best = f"; smallest result ~{self.best / 1048576:.2f} MB" if self.best else ""
        return f"doesn't fit {self.limit:g} MB{best}"


MIN_SCALE_DEFAULT = SCALE_STEPS[-1]
MIN_COLORS_DEFAULT = COLOR_STEPS[-1]


# --------------------------------------------------------------------- probing
def probe(video):
    """Size, fps, duration and alpha presence via `ffmpeg -i`."""
    r = subprocess.run([FFMPEG, "-hide_banner", "-i", video], capture_output=True,
                       text=True, errors="replace", creationflags=NO_WINDOW)
    info = r.stderr
    m = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", info)
    if not m:
        raise RuntimeError("cannot read video:\n" + info[-800:])
    w, h = int(m.group(1)), int(m.group(2))
    fps_m = re.search(r"([\d.]+) fps", info) or re.search(r"([\d.]+) tbr", info)
    fps = float(fps_m.group(1)) if fps_m else 25.0
    d = re.search(r"Duration: (\d+):(\d+):([\d.]+)", info)
    dur = int(d.group(1)) * 3600 + int(d.group(2)) * 60 + float(d.group(3)) if d else 0
    alpha = any(k in info for k in ("rgba", "argb", "bgra", "yuva", "gbrap", "ya8", "rgb48a", "rgba64"))
    return {"w": w, "h": h, "fps": fps, "alpha": alpha, "duration": dur,
            "frames": round(dur * fps) if dur else 0}


def first_frame(video, out_png):
    """One frame for the preview."""
    r = subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", video,
                        "-frames:v", "1", "-pix_fmt", "rgba", out_png],
                       capture_output=True, creationflags=NO_WINDOW)
    return r.returncode == 0 and os.path.isfile(out_png)


# --------------------------------------------------------------------- image ops
def apply_key(img, key="none", threshold=0.0):
    """Unmult: turn a black or white background into alpha.

    black: alpha = max(R,G,B), colour divided by alpha (like Red Giant Unmult).
    white: mirrored — alpha = 1 - min(R,G,B), for dark artwork on white.
    threshold (0..0.5): anything darker/lighter than this counts as clean background.
    Existing source alpha is kept and multiplied in.
    """
    if key not in ("black", "white"):
        return img
    a = np.asarray(img.convert("RGBA"), dtype=np.float32) / 255.0
    rgb, a_src = a[..., :3], a[..., 3]
    t = float(min(max(threshold, 0.0), 0.5))
    if key == "white":
        rgb = 1.0 - rgb
    if t > 0:
        rgb = np.clip((rgb - t) / (1.0 - t), 0.0, 1.0)
    k = rgb.max(axis=2)
    safe = np.where(k > 1e-6, k, 1.0)[..., None]
    rgb = np.clip(rgb / safe, 0.0, 1.0)
    if key == "white":
        rgb = 1.0 - rgb
    out = np.dstack([rgb, a_src * k])
    return Image.fromarray((out * 255.0 + 0.5).astype(np.uint8), "RGBA")


def alpha_bbox(paths, pad=2):
    """Union bounding box (x0, y0, x1, y1) of visible pixels over all frames, or None if all empty."""
    box = None
    size = None
    for p in paths:
        with Image.open(p) as im:
            size = im.size
            a = np.asarray(im.convert("RGBA"))[..., 3]
        ys, xs = np.nonzero(a > ALPHA_CUTOFF)
        if xs.size == 0:
            continue
        b = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
        box = b if box is None else (min(box[0], b[0]), min(box[1], b[1]), max(box[2], b[2]), max(box[3], b[3]))
    if box is None:
        return None
    w, h = size
    return (max(0, box[0] - pad), max(0, box[1] - pad), min(w, box[2] + pad), min(h, box[3] + pad))


def quantize_image(img, colors):
    """Palette-quantize with full alpha, return PNG bytes."""
    rgba = img.convert("RGBA")
    # pass raw bytes directly: the library's own PIL helper converts pixel by pixel in Python (very slow)
    data, palette = imagequant.quantize_raw_rgba_bytes(rgba.tobytes(), rgba.width, rgba.height,
                                                       dithering_level=1.0, max_colors=colors,
                                                       min_quality=0, max_quality=100)
    q = Image.frombytes("P", rgba.size, data, decoder_name="raw")
    q.putpalette(palette, rawmode="RGBA")
    buf = io.BytesIO()
    q.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def quantize_bytes(png_path, colors):
    with Image.open(png_path) as im:
        return quantize_image(im, colors)


def fits(sizes, limit_bytes, per_frame):
    return (max(sizes) if per_frame else sum(sizes)) <= limit_bytes


# --------------------------------------------------------------------- extraction
def extract_frames(video, out_dir, scale_pct, src_w, src_h, keep_every=1, out_fps=None):
    """RGBA PNG frames, lanczos scaling."""
    os.makedirs(out_dir, exist_ok=True)
    w = max(1, round(src_w * scale_pct / 100))
    h = max(1, round(src_h * scale_pct / 100))
    vf = []
    if out_fps:
        vf.append(f"fps={out_fps:g}")
    if keep_every > 1:
        vf.append(f"select='not(mod(n\\,{keep_every}))'")
    if scale_pct != 100:
        vf.append(f"scale={w}:{h}:flags=lanczos")
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", video]
    if vf:
        cmd += ["-vf", ",".join(vf)]
    cmd += ["-fps_mode", "passthrough", "-pix_fmt", "rgba", os.path.join(out_dir, "f_%06d.png")]
    r = subprocess.run(cmd, capture_output=True, text=True, errors="replace", creationflags=NO_WINDOW)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg: " + r.stderr[-800:])
    files = sorted(f for f in os.listdir(out_dir) if f.endswith(".png"))
    if not files:
        raise RuntimeError("ffmpeg produced no frames")
    return [os.path.join(out_dir, f) for f in files], (w, h)


def prepare_frames(video, fdir, scale, info, keep, out_fps, key, threshold, autocrop, cancel):
    """Extract + key + crop one variant. Returns (frames, size, crop_box_or_None, canvas_size)."""
    frames, canvas = extract_frames(video, fdir, scale, info["w"], info["h"], keep, out_fps)
    if key != "none":
        for p in frames:
            if cancel():
                raise Cancelled()
            with Image.open(p) as im:
                keyed = apply_key(im, key, threshold)
            keyed.save(p, compress_level=1)
    box = None
    size = canvas
    if autocrop:
        b = alpha_bbox(frames)
        if b and (b[2] - b[0], b[3] - b[1]) != canvas:
            for p in frames:
                with Image.open(p) as im:
                    cropped = im.crop(b)
                cropped.save(p, compress_level=1)
            box = b
            size = (b[2] - b[0], b[3] - b[1])
    return frames, size, box, canvas


# --------------------------------------------------------------------- backup image
def pick_backup_frame(frames, which):
    if which == "first":
        return frames[0]
    if which == "middle":
        return frames[len(frames) // 2]
    if which == "fullest":
        best, best_n = frames[-1], -1
        for p in frames:
            with Image.open(p) as im:
                n = int((np.asarray(im.convert("RGBA"))[..., 3] > ALPHA_CUTOFF).sum())
            if n > best_n:
                best, best_n = p, n
        return best
    return frames[-1]


def make_backup(src_png, out_base, limit_kb, fmt="png", bg="#FFFFFF"):
    """Save a static backup image under limit_kb. fmt 'png' keeps alpha, 'jpg' flattens on bg.
    Returns (path, bytes, detail) or raises FitError."""
    limit = int(limit_kb * 1024)
    with Image.open(src_png) as im:
        img = im.convert("RGBA")
    if fmt == "jpg":
        flat = Image.new("RGB", img.size, bg)
        flat.paste(img, mask=img.getchannel("A"))
        for scale in (1.0, 0.85, 0.7, 0.5):
            cur = flat if scale == 1.0 else flat.resize((max(1, int(flat.width * scale)), max(1, int(flat.height * scale))), Image.LANCZOS)
            for q in (90, 82, 74, 66, 58, 50, 42):
                buf = io.BytesIO()
                cur.save(buf, "JPEG", quality=q, optimize=True, progressive=True)
                if buf.tell() <= limit:
                    path = out_base + ".jpg"
                    with open(path, "wb") as fh:
                        fh.write(buf.getvalue())
                    return path, buf.tell(), f"jpg q{q} {cur.width}x{cur.height}"
    else:
        for scale in (1.0, 0.85, 0.7, 0.5):
            cur = img if scale == 1.0 else img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))), Image.LANCZOS)
            for colors in COLOR_STEPS + [32]:
                data = quantize_image(cur, colors)
                if len(data) <= limit:
                    path = out_base + ".png"
                    with open(path, "wb") as fh:
                        fh.write(data)
                    return path, len(data), f"png {colors}c {cur.width}x{cur.height}"
    raise FitError(limit_kb)



# --------------------------------------------------------------------- file names
NAME_SEPS = ("_", "-", ".", "")
NAME_DIGITS = (2, 3, 4, 5, 6)
_BAD_NAME_CHARS = set('\\/:*?"<>|')


class BadName(ValueError):
    """Invalid prefix/suffix (characters Windows does not allow in file names)."""


def naming_defaults():
    return {"prefix": "", "suffix": "", "sep": "_", "start": 0, "digits": 4}


def make_namer(naming, video, count):
    """Return (name(i) -> file name, info dict) for a sequence of `count` frames.

    naming: prefix ("" = video name; "{name}" is replaced by the video name), suffix, sep, start (0/1), digits.
    Digits widen automatically if the last frame number needs more."""
    n = dict(naming_defaults(), **(naming or {}))
    base = os.path.splitext(os.path.basename(video))[0]
    prefix = (n["prefix"] or "").strip().replace("{name}", base) or base
    suffix = (n["suffix"] or "").strip().replace("{name}", base)
    for part in (prefix, suffix):
        if any(ch in _BAD_NAME_CHARS for ch in part):
            raise BadName(part)
    sep = n["sep"] if n["sep"] in NAME_SEPS else "_"
    start = 1 if int(n["start"]) == 1 else 0
    want = int(n["digits"]) if int(n["digits"]) in NAME_DIGITS else 4
    last = start + max(count, 1) - 1
    digits = max(want, len(str(last)))

    def name(i):
        return f"{prefix}{sep}{start + i:0{digits}d}{suffix}.png"
    info = {"prefix": prefix, "suffix": suffix, "sep": sep, "start": start, "digits": digits,
            "widened": digits > want, "first": name(0), "last": name(max(count, 1) - 1),
            "backup_base": f"{prefix}{sep}backup{suffix}"}
    return name, info


def _sequence_regex(info):
    return re.compile("^" + re.escape(info["prefix"] + info["sep"]) + r"\d+" + re.escape(info["suffix"]) + r"\.png$",
                      re.IGNORECASE)


def clean_previous(out_dir, info):
    """Remove files of an earlier run in out_dir: those listed in its _report.json and
    those matching the current naming pattern. Other files are never touched."""
    if not os.path.isdir(out_dir):
        return
    old = set()
    try:
        with open(os.path.join(out_dir, "_report.json"), encoding="utf-8") as fh:
            rep = json.load(fh)
        old.update(rep.get("files", []))
        if isinstance(rep.get("backup"), dict) and rep["backup"].get("file"):
            old.add(rep["backup"]["file"])
    except (OSError, ValueError):
        pass
    rx = _sequence_regex(info)
    for f in os.listdir(out_dir):
        if os.path.basename(f) != f:
            continue
        stem = os.path.splitext(f)[0].lower()
        if f in old or rx.match(f) or stem == info["backup_base"].lower():
            try:
                os.remove(os.path.join(out_dir, f))
            except OSError:
                pass

# --------------------------------------------------------------------- main
def run(video, out_dir, limit_mb, per_frame=False, max_scale=100,
        allow_colors=True, allow_scale=True, allow_frames=False,
        prefix=None, log=None, progress=None, cancel=lambda: False,
        key="none", threshold=0.0, out_fps=None,
        autocrop=False, backup=None, naming=None,
        min_scale=MIN_SCALE_DEFAULT, min_colors=MIN_COLORS_DEFAULT):
    """Find settings that fit and write the sequence to out_dir. Returns a report dict.

    log(key, **params) receives translatable events. backup = dict(frame, fmt, limit_kb, bg) or None.
    naming = dict(prefix, suffix, sep, start, digits) — see make_namer(). `prefix` (old argument) still works.
    min_scale / min_colors are quality floors: the search never goes below them (FitError.floor tells why).
    """
    log = log or (lambda k, **p: None)
    progress = progress or (lambda v: None)
    limit = int(limit_mb * 1024 * 1024)
    info = probe(video)
    if out_fps and out_fps >= info["fps"] - 1e-3:
        if out_fps > info["fps"] + 1e-3:
            log("log_fps_above_source", fps=out_fps, src=info["fps"])
        out_fps = None
    base_fps = out_fps or info["fps"]
    log("log_source", w=info["w"], h=info["h"], fps=info["fps"], out_fps=out_fps or 0)
    if not info["alpha"] and key == "none":
        log("log_no_alpha")
    if key != "none":
        log("log_unmult", mode=key, thr=round(threshold * 100))

    scales = [s for s in SCALE_STEPS if s <= max_scale] or [max_scale]
    if max_scale not in scales:
        scales.insert(0, max_scale)
    if not allow_scale:
        scales = scales[:1]
    min_scale = int(min_scale or MIN_SCALE_DEFAULT)
    min_colors = int(min_colors or MIN_COLORS_DEFAULT)
    scales = [s for s in scales if s >= min_scale] or scales[:1]
    colors_list = COLOR_STEPS if allow_colors else [256]
    colors_list = [c for c in colors_list if c >= min_colors] or colors_list[:1]
    floor = {}
    if allow_scale and min_scale > MIN_SCALE_DEFAULT:
        floor["min_scale"] = min_scale
    if allow_colors and min_colors > MIN_COLORS_DEFAULT:
        floor["min_colors"] = min_colors
    frame_steps = [1, 2, 3] if allow_frames else [1]

    naming = dict(naming or {})
    if prefix and not naming.get("prefix"):
        naming["prefix"] = prefix
    make_namer(naming, video, 1)  # validate names before any heavy work
    tmp = tempfile.mkdtemp(prefix="framediet_")
    best = None
    try:
        attempts = [(k, s, c) for k in frame_steps for s in scales for c in colors_list]
        prepared = {}
        for i, (keep, scale, colors) in enumerate(attempts):
            if cancel():
                raise Cancelled()
            pk = (keep, scale)
            if pk not in prepared:
                fdir = os.path.join(tmp, f"k{keep}_s{scale}")
                prepared[pk] = prepare_frames(video, fdir, scale, info, keep, out_fps,
                                              key, threshold, autocrop, cancel)
                box = prepared[pk][2]
                if box and scale == scales[0] and keep == 1:
                    log("log_autocrop", w=box[2] - box[0], h=box[3] - box[1],
                        cw=prepared[pk][3][0], ch=prepared[pk][3][1])
            frames, size, box, canvas = prepared[pk]

            sample = frames[:: max(1, len(frames) // 8)][:8]
            est = [len(quantize_bytes(p, colors)) for p in sample]
            est_total = max(est) if per_frame else sum(est) / len(est) * len(frames)
            best = est_total if best is None else min(best, est_total)
            if est_total > limit * 1.08:
                log("log_try_skip", scale=scale, colors=colors, keep=keep, mb=est_total / 1048576)
                progress((i + 1) / len(attempts))
                continue

            log("log_try_full", scale=scale, colors=colors, keep=keep, mb=est_total / 1048576)
            data = []
            for j, p in enumerate(frames):
                if cancel():
                    raise Cancelled()
                data.append(quantize_bytes(p, colors))
                progress(j / len(frames))
            sizes = [len(d) for d in data]
            if not fits(sizes, limit, per_frame):
                got = max(sizes) if per_frame else sum(sizes)
                best = min(best, got)
                log("log_try_fail", mb=got / 1048576)
                continue

            name, ninfo = make_namer(naming, video, len(data))
            if ninfo["widened"]:
                log("log_digits_widened", digits=ninfo["digits"])
            os.makedirs(out_dir, exist_ok=True)
            clean_previous(out_dir, ninfo)
            files = [name(j) for j in range(len(data))]
            for fn, d in zip(files, data):
                with open(os.path.join(out_dir, fn), "wb") as fh:
                    fh.write(d)

            report = {
                "app": "FrameDiet",
                "source": os.path.basename(video),
                "size": f"{size[0]}x{size[1]}", "scale_pct": scale, "colors": colors,
                "frames": len(data), "fps": round(base_fps / keep, 3), "source_fps": info["fps"],
                "keep_every": keep,
                "total_mb": round(sum(sizes) / 1048576, 3),
                "max_frame_kb": round(max(sizes) / 1024, 1),
                "limit_mb": limit_mb, "limit_mode": "per_frame" if per_frame else "total",
                "key": key, "threshold": threshold,
                "min_scale": min_scale, "min_colors": min_colors,
                "naming": {k: ninfo[k] for k in ("prefix", "suffix", "sep", "start", "digits", "first", "last")},
                "files": files,
            }
            if box:
                report["crop"] = {"x": box[0], "y": box[1], "w": size[0], "h": size[1],
                                  "canvas_w": canvas[0], "canvas_h": canvas[1]}
            if backup:
                src = pick_backup_frame(frames, backup.get("frame", "last"))
                try:
                    path, nbytes, detail = make_backup(src, os.path.join(out_dir, ninfo["backup_base"]),
                                                       backup.get("limit_kb", 150), backup.get("fmt", "png"),
                                                       backup.get("bg", "#FFFFFF"))
                    report["backup"] = {"file": os.path.basename(path), "kb": round(nbytes / 1024, 1),
                                        "detail": detail}
                    log("log_backup_ok", file=os.path.basename(path), kb=nbytes / 1024)
                except FitError:
                    report["backup"] = {"error": "over_limit"}
                    log("log_backup_fail", kb=backup.get("limit_kb", 150))
            with open(os.path.join(out_dir, "_report.json"), "w", encoding="utf-8") as fh:
                json.dump(report, fh, ensure_ascii=False, indent=2)
            progress(1.0)
            return report
        off = [name for name, on in (("frames", allow_frames), ("scale", allow_scale), ("colors", allow_colors))
               if not on]
        raise FitError(limit_mb, floor, best, off, per_frame)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run_batch(videos, out_root, settings, log=None, progress=None, cancel=lambda: False, on_item=None):
    """Process several videos with the same settings. Each goes to <out_root>/<name>_png.
    on_item(index, status, report_or_error). Returns list of (video, ok, report_or_error)."""
    log = log or (lambda k, **p: None)
    results = []
    for i, v in enumerate(videos):
        if cancel():
            raise Cancelled()
        name = os.path.splitext(os.path.basename(v))[0]
        out = os.path.join(out_root or os.path.dirname(v), name + "_png")
        if on_item:
            on_item(i, "running", None)
        log("log_batch_item", n=i + 1, total=len(videos), name=os.path.basename(v))
        try:
            rep = run(v, out, log=log, cancel=cancel,
                      progress=(lambda val, i=i: progress((i + val) / len(videos))) if progress else None,
                      **settings)
            results.append((v, True, rep))
            if on_item:
                on_item(i, "done", rep)
        except Cancelled:
            raise
        except Exception as ex:  # keep going with the rest of the batch
            results.append((v, False, ex))
            if on_item:
                on_item(i, "error", ex)
    if out_root:
        os.makedirs(out_root, exist_ok=True)
    summary_dir = out_root or (os.path.dirname(videos[0]) if videos else ".")
    with open(os.path.join(summary_dir, "_framediet_batch.csv"), "w", encoding="utf-8") as fh:
        fh.write("source,status,size,colors,frames,fps,total_mb\n")
        for v, ok, r in results:
            if ok:
                fh.write(f"{os.path.basename(v)},ok,{r['size']},{r['colors']},{r['frames']},{r['fps']},{r['total_mb']}\n")
            else:
                fh.write(f"{os.path.basename(v)},error,,,,,\n")
    return results
