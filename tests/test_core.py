import json
import os
import subprocess
import sys

import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from framediet import core, presets  # noqa: E402
from framediet.i18n import log_line, set_lang  # noqa: E402


def make_video(path, kind="alpha_small", size="640x480", dur=2, fps=10):
    """Synthetic test clips. alpha_small: moving circle on transparent canvas (lots of empty margin)."""
    w, h = (int(v) for v in size.split("x"))
    if kind == "alpha_small":
        flt = (f"testsrc2=s={size}:r={fps}:d={dur},format=rgba,"
               f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
               f"a='if(lt(hypot(X-{w//2}-30*sin(N/3),Y-{h//2}),{min(w,h)//6}),255,0)'")
        args = ["-c:v", "qtrle", "-pix_fmt", "argb"]
    else:  # glow on black, no alpha
        flt = (f"color=black:s={size}:r={fps}:d={dur},format=rgb24,"
               f"geq=r='255*exp(-((X-{w//2})^2+(Y-{h//2})^2)/3000)':g='120*exp(-((X-{w//2})^2+(Y-{h//2})^2)/2000)':b='20*exp(-((X-{w//2})^2+(Y-{h//2})^2)/2000)'")
        args = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "14"]
    subprocess.run([core.FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", flt, *args, path],
                   check=True)
    return path


@pytest.fixture(scope="module")
def clips(tmp_path_factory):
    d = tmp_path_factory.mktemp("clips")
    return {"alpha": make_video(str(d / "alpha.mov")),
            "alpha2": make_video(str(d / "alpha2.mov"), dur=1),
            "glow": make_video(str(d / "glow.mp4"), kind="glow")}


def frames_in(out):
    return sorted(f for f in os.listdir(out) if f.endswith(".png") and "_backup" not in f)


def test_fits_limit_and_report(clips, tmp_path):
    out = str(tmp_path / "o")
    rep = core.run(clips["alpha"], out, 0.4)
    total = sum(os.path.getsize(os.path.join(out, f)) for f in frames_in(out))
    assert total <= 0.4 * 1024 * 1024
    assert rep["frames"] == len(frames_in(out)) == 20
    assert json.load(open(os.path.join(out, "_report.json")))["app"] == "FrameDiet"


def test_autocrop_shrinks_frames_and_records_offset(clips, tmp_path):
    out = str(tmp_path / "o")
    rep = core.run(clips["alpha"], out, 2, autocrop=True)
    crop = rep["crop"]
    assert crop["canvas_w"] == 640 and crop["canvas_h"] == 480
    assert crop["w"] < 300 and crop["h"] < 200
    with Image.open(os.path.join(out, frames_in(out)[0])) as im:
        assert im.size == (crop["w"], crop["h"])
    # crop box must contain the circle: x offset around centre minus radius minus motion
    assert 120 < crop["x"] < 260 and 140 < crop["y"] < 180


def test_autocrop_reduces_weight(clips, tmp_path):
    a = core.run(clips["alpha"], str(tmp_path / "a"), 5)
    b = core.run(clips["alpha"], str(tmp_path / "b"), 5, autocrop=True)
    assert b["total_mb"] <= a["total_mb"]


@pytest.mark.parametrize("fmt", ["png", "jpg"])
def test_backup_under_limit(clips, tmp_path, fmt):
    out = str(tmp_path / "o")
    rep = core.run(clips["alpha"], out, 2, backup={"frame": "fullest", "fmt": fmt, "limit_kb": 20})
    b = rep["backup"]
    assert "file" in b and b["file"].endswith("." + fmt)
    assert os.path.getsize(os.path.join(out, b["file"])) <= 20 * 1024


def test_backup_impossible_limit_is_reported_not_fatal(clips, tmp_path):
    rep = core.run(clips["alpha"], str(tmp_path / "o"), 2, backup={"fmt": "png", "limit_kb": 0.05})
    assert rep["backup"] == {"error": "over_limit"}


def test_unmult_black_creates_alpha(clips, tmp_path):
    out = str(tmp_path / "o")
    core.run(clips["glow"], out, 2, key="black", threshold=0.05)
    with Image.open(os.path.join(out, frames_in(out)[0])) as im:
        a = im.convert("RGBA").getchannel("A")
        assert a.getpixel((0, 0)) == 0          # corner = black background → transparent
        assert a.getpixel((320, 240)) > 200     # glow centre stays opaque


def test_fps_resample(clips, tmp_path):
    rep = core.run(clips["alpha"], str(tmp_path / "o"), 5, out_fps=5)
    assert rep["fps"] == 5 and rep["frames"] == 10


def test_impossible_limit_raises(clips, tmp_path):
    with pytest.raises(core.FitError):
        core.run(clips["alpha"], str(tmp_path / "o"), 0.001, allow_scale=False)


def test_batch(clips, tmp_path):
    root = str(tmp_path / "batch")
    statuses = []
    res = core.run_batch([clips["alpha"], clips["alpha2"]], root, {"limit_mb": 1, "autocrop": True},
                         on_item=lambda i, s, r: statuses.append((i, s)))
    assert all(ok for _, ok, _ in res)
    assert os.path.isdir(os.path.join(root, "alpha_png")) and os.path.isdir(os.path.join(root, "alpha2_png"))
    assert (1, "done") in statuses
    csv = open(os.path.join(root, "_framediet_batch.csv")).read().splitlines()
    assert len(csv) == 3 and csv[1].startswith("alpha.mov,ok")


def test_batch_continues_after_error(clips, tmp_path):
    bad = str(tmp_path / "broken.mov")
    open(bad, "wb").write(b"not a video")
    res = core.run_batch([bad, clips["alpha2"]], str(tmp_path / "b"), {"limit_mb": 1})
    assert [ok for _, ok, _ in res] == [False, True]


def test_cancel(clips, tmp_path):
    with pytest.raises(core.Cancelled):
        core.run(clips["alpha"], str(tmp_path / "o"), 1, cancel=lambda: True)


def test_presets_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    assert presets.save_user_preset("Agency 300x250", {"limit": 120, "unit": "KB", "bogus": 1})
    names = [p["name"] for p in presets.all_presets()]
    assert "Agency 300x250" in names and names[0].startswith("Google Ads")
    p = [p for p in presets.user_presets() if p["name"] == "Agency 300x250"][0]
    assert p["settings"] == {"limit": 120, "unit": "KB"}
    presets.delete_user_preset("Agency 300x250")
    assert all(p["name"] != "Agency 300x250" for p in presets.user_presets())


def test_log_translation():
    set_lang("ru")
    assert "чёрный" in log_line("log_unmult", mode="black", thr=5)
    assert "каждый 2-й" in log_line("log_try_skip", scale=50, colors=128, keep=2, mb=1.0)
    set_lang("en")
    assert log_line("log_source", w=10, h=10, fps=9, out_fps=0) == "Source: 10×10, 9 fps"


def test_cli_single_and_errors(clips, tmp_path, capsys):
    from framediet import cli
    out = str(tmp_path / "cli")
    assert cli.main([clips["alpha"], "--limit", "300KB", "--autocrop", "--out", out]) == 0
    assert json.load(open(os.path.join(out, "_report.json")))["crop"]["canvas_w"] == 640
    assert cli.main([str(tmp_path / "nothing_here"), "--limit", "1MB"]) == 2
    assert cli.main([clips["alpha"], "--limit", "1KB", "--no-scale", "--out", str(tmp_path / "x")]) == 1


def test_cli_parse_size():
    from framediet.cli import parse_size
    assert parse_size("2MB") == 2 and parse_size("512kb") == 0.5 and parse_size("1,5") == 1.5


def test_naming_default_unchanged(clips, tmp_path):
    out = str(tmp_path / "d")
    rep = core.run(clips["alpha"], out, 1)
    base = os.path.splitext(os.path.basename(clips["alpha"]))[0]
    assert rep["files"][0] == f"{base}_0000.png"
    assert sorted(f for f in os.listdir(out) if f.endswith(".png")) == rep["files"]


def test_naming_custom(clips, tmp_path):
    out = str(tmp_path / "n")
    nm = {"prefix": "banner_{name}", "suffix": "_v2", "sep": ".", "start": 1, "digits": 3}
    rep = core.run(clips["alpha"], out, 1, naming=nm)
    base = os.path.splitext(os.path.basename(clips["alpha"]))[0]
    n = rep["frames"]
    assert rep["files"][0] == f"banner_{base}.001_v2.png"
    assert rep["files"][-1] == f"banner_{base}.{n:03d}_v2.png"
    assert rep["naming"]["start"] == 1 and rep["naming"]["digits"] == 3
    on_disk = sorted(f for f in os.listdir(out) if f.endswith(".png"))
    assert on_disk == sorted(rep["files"])


def test_naming_rerun_cleans_old_names_only(clips, tmp_path):
    out = tmp_path / "r"
    out.mkdir()
    (out / "keep_me.png").write_bytes(b"x")
    core.run(clips["alpha"], str(out), 1, naming={"prefix": "a"})
    rep = core.run(clips["alpha"], str(out), 1, naming={"prefix": "b", "start": 1}, backup={"limit_kb": 200})
    pngs = sorted(f for f in os.listdir(out) if f.endswith(".png"))
    assert "keep_me.png" in pngs
    assert not any(f.startswith("a_") for f in pngs)
    assert rep["backup"]["file"] == "b_backup.png"
    assert len([f for f in pngs if f.startswith("b_") and f != "b_backup.png"]) == rep["frames"]


def test_naming_widen_and_validation():
    name, info = core.make_namer({"digits": 2, "start": 1}, "x.mov", 150)
    assert info["widened"] and info["digits"] == 3 and name(149) == "x_150.png"
    name, info = core.make_namer({"sep": ""}, "clip.mp4", 5)
    assert name(0) == "clip0000.png"
    with pytest.raises(core.BadName):
        core.make_namer({"prefix": "a/b"}, "x.mov", 3)


def test_cli_naming(clips, tmp_path):
    from framediet import cli
    out = str(tmp_path / "cn")
    assert cli.main([clips["alpha"], "--limit", "1MB", "--out", out, "--prefix", "seq", "--start", "1",
                     "--digits", "3", "--sep", "none"]) == 0
    assert "seq001.png" in os.listdir(out)
    assert cli.main([clips["alpha"], "--limit", "1MB", "--out", out, "--prefix", "a:b"]) == 2


def test_quality_floor_stops_search(clips, tmp_path):
    # a limit just under the full-quality size fits only by shrinking; a high floor must refuse instead
    full = core.run(clips["alpha"], str(tmp_path / "full"), 50)
    assert full["scale_pct"] == 100 and full["colors"] == 256
    tight = full["total_mb"] * 0.9
    free = core.run(clips["alpha"], str(tmp_path / "free"), tight)
    assert free["scale_pct"] < 100 or free["colors"] < 256
    with pytest.raises(core.FitError) as ei:
        core.run(clips["alpha"], str(tmp_path / "floor"), tight, min_scale=90, min_colors=128)
    assert ei.value.floor == {"min_scale": 90, "min_colors": 128}


def test_quality_floor_respected(clips, tmp_path):
    rep = core.run(clips["alpha"], str(tmp_path / "f"), 1, min_scale=50, min_colors=96)
    assert rep["scale_pct"] >= 50 and rep["colors"] >= 96
    assert rep["min_scale"] == 50 and rep["min_colors"] == 96


def test_default_fit_error_has_no_floor(clips, tmp_path):
    with pytest.raises(core.FitError) as ei:
        core.run(clips["alpha"], str(tmp_path / "x"), 0.0001, allow_scale=False)
    assert ei.value.floor == {}


def test_cli_floor(clips, tmp_path, capsys):
    from framediet import cli
    assert cli.main([clips["alpha"], "--limit", "5KB", "--min-scale", "90", "--min-colors", "128",
                     "--out", str(tmp_path / "c")]) == 1
    assert "quality floor" in capsys.readouterr().err


def test_support_report_is_private_and_complete(clips, tmp_path, monkeypatch):
    from framediet import support, VERSION
    home = str(tmp_path / "home" / "evgeniy")
    os.makedirs(home)
    monkeypatch.setenv("HOME", home)
    monkeypatch.setenv("USERPROFILE", home)
    video = os.path.join(home, "Projects", "secret_client", "intro.mov")
    rep = core.run(clips["alpha"], str(tmp_path / "o"), 1)
    rep["source"] = video  # pretend the report holds a full path
    text = support.make_report({"limit": "2", "unit": "MB"}, [video], {"w": 640, "h": 480, "fps": 10.0},
                               rep, ["line one", f"saved to {home}/out"], "Done", "ru", 1.25)
    assert f"FrameDiet {VERSION}" in text and "has NOT been sent" in text
    assert "intro.mov" in text and "secret_client" not in text
    assert home not in text and "~/out" in text
    assert '"limit": "2"' in text and "line one" in text and "UI scaling: 1.25" in text
    assert "files\": \"20 files" in text
    assert support.default_name().startswith("FrameDiet_support_") and support.default_name().endswith(".txt")


def test_fit_error_explains_what_can_still_help(clips, tmp_path):
    with pytest.raises(core.FitError) as ei:
        core.run(clips["alpha"], str(tmp_path / "x"), 0.0001)
    ex = ei.value
    assert ex.off == ["frames"] and ex.best and ex.best > 0.0001 * 1048576
    from framediet.app import App
    set_lang("ru")
    msg = App.fit_message(App, {"floor": {}, "best": ex.best, "off": ex.off, "limit": ex.limit, "per_frame": False})
    assert "прореживание" in msg and "поднять лимит" in msg and "масштаб" not in msg
    msg = App.fit_message(App, {"floor": {"min_scale": 70}, "best": 300000, "off": [], "limit": 0.1,
                                "per_frame": False})
    assert "порог качества (масштаб 70%)" in msg and "293 КБ" in msg
    set_lang("en")
