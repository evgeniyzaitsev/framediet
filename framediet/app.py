"""FrameDiet desktop app (customtkinter) — light UI, preview-first layout."""
import os
import queue
import shutil
import sys
import tempfile
import threading
import traceback
import tkinter as tk
from tkinter import filedialog

import customtkinter as ctk
from PIL import Image

from . import APP_NAME, VERSION, core, presets, support
from .i18n import get_lang, log_line, set_lang, t

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except Exception:  # drag and drop is optional
    HAS_DND = False

# ------------------------------------------------------------------ themes
THEMES = {
    # A — editorial: graphite actions on paper, lime only as a signal
    "paper": dict(bg="#F3F3F0", card="#FFFFFF", border="#E4E4DE", field="#F3F3F0", field_border="#E0E0DA",
                  track="#ECECE7", text="#18181B", muted="#77777F", faint="#A3A3AA",
                  accent="#18181B", accent_hover="#34343A", on_accent="#FFFFFF", sel="#FFFFFF", sel_text="#18181B",
                  signal="#B7E62E", signal_text="#3B4A0B", error="#D93A2B", switch_off="#E4E4DE",
                  switch_on="#B7E62E", knob="#18181B",
                  check_a="#FFFFFF", check_b="#ECECE8", drop="#C9C9C2", mode="light"),
    # A in the dark: graphite surfaces, paper-white actions, the same lime signal
    "graphite": dict(bg="#121214", card="#1B1B1E", border="#29292E", field="#232327", field_border="#303036",
                     track="#2A2A2F", text="#EDEDEA", muted="#9C9CA5", faint="#6B6B74",
                     accent="#EDEDEA", accent_hover="#FFFFFF", on_accent="#121214", sel="#3A3A41",
                     sel_text="#F4F4F1", signal="#B7E62E", signal_text="#C9F25A", error="#FF6B5C",
                     switch_off="#34343A", switch_on="#B7E62E", knob="#EDEDEA",
                     check_a="#2B2B30", check_b="#222226", drop="#4A4A52", mode="dark"),
}
THEME_ORDER = ("paper", "graphite")
DEFAULT_THEME = "paper"
C = dict(THEMES[DEFAULT_THEME])

FONT = "Inter"
VIDEO_EXT = (".mov", ".mp4", ".webm", ".mkv", ".avi", ".gif", ".apng", ".m4v")
SCALES = ["100%", "90%", "80%", "75%", "70%", "60%", "50%"]
FPS_CHOICES = ["25", "24", "15", "12", "10", "8", "6", "5"]


def Btn(*a, **kw):
    """CTkButton whose disabled text is readable-but-quiet in both themes."""
    kw.setdefault("text_color_disabled", C["faint"])
    return ctk.CTkButton(*a, **kw)


def F(size, weight="normal"):
    return (FONT, size, weight)


def resource(*parts):
    base = getattr(sys, "_MEIPASS", None)
    root = os.path.join(base, "assets") if base else os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
    return os.path.join(root, *parts)


def load_fonts():
    for name in ("Inter-Regular.otf", "Inter-Medium.otf", "Inter-SemiBold.otf", "Inter-Bold.otf"):
        p = resource("fonts", name)
        if os.path.isfile(p):
            try:
                ctk.FontManager.load_font(p)
            except Exception:
                pass


def checker(size, cell=10):
    w, h = size
    img = Image.new("RGB", size, C["check_a"])
    tile = Image.new("RGB", (cell, cell), C["check_b"])
    for y in range(0, h, cell):
        for x in range((y // cell) % 2 * cell, w, cell * 2):
            img.paste(tile, (x, y))
    return img


def fit(img, box):
    w, h = img.size
    k = min(box[0] / w, box[1] / h, 1.0 if max(w, h) > 120 else 4.0)
    return img.resize((max(1, int(w * k)), max(1, int(h * k))), Image.LANCZOS)


def on_bg(rgba, bg):
    rgba = rgba.convert("RGBA")
    if bg == "white":
        base = Image.new("RGBA", rgba.size, "#FFFFFF")
    elif bg == "black":
        base = Image.new("RGBA", rgba.size, "#000000")
    else:
        base = checker(rgba.size).convert("RGBA")
    base.alpha_composite(rgba)
    return base


def collect_videos(paths):
    out = []
    for p in paths:
        if os.path.isdir(p):
            for f in sorted(os.listdir(p)):
                if f.lower().endswith(VIDEO_EXT):
                    out.append(os.path.join(p, f))
        elif os.path.isfile(p):
            out.append(p)
    return out


Base = ctk.CTk
if HAS_DND:
    class Base(ctk.CTk, TkinterDnD.DnDWrapper):  # noqa: F811
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.TkdndVersion = TkinterDnD._require(self)


class DropArea(tk.Canvas):
    """Empty state of the preview: big dashed drop target."""

    def __init__(self, master, on_click, **kw):
        super().__init__(master, bg=C["card"], highlightthickness=0, cursor="hand2", **kw)
        self.hot = False
        self.bind("<Configure>", lambda e: self.redraw())
        self.bind("<Button-1>", lambda e: on_click())
        self.bind("<Enter>", lambda e: self.set_hot(True))
        self.bind("<Leave>", lambda e: self.set_hot(False))

    def set_hot(self, v):
        self.hot = v
        self.redraw()

    def redraw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 20:
            return
        col = C["accent"] if self.hot else C["drop"]
        self.create_rectangle(2, 2, w - 2, h - 2, outline=col, width=2, dash=(7, 6))
        cx, cy = w // 2, h // 2
        r = 34
        self.create_oval(cx - r, cy - 70 - r, cx + r, cy - 70 + r, fill=C["track"], outline="")
        self.create_line(cx, cy - 88, cx, cy - 58, fill=col if self.hot else C["muted"], width=3, arrow="last",
                         arrowshape=(11, 13, 6))
        self.create_text(cx, cy, text=t("drop_title") if HAS_DND else t("drop_title_click"),
                         fill=C["text"], font=F(17, "bold"))
        self.create_text(cx, cy + 28, text=t("drop_sub") + (t("drop_sub_click") if HAS_DND else ""),
                         fill=C["muted"], font=F(11))


class App(Base):
    def __init__(self, theme=None):
        saved = presets.load_settings()
        name = theme or saved.get("theme", DEFAULT_THEME)
        name = name if name in THEMES else DEFAULT_THEME
        C.clear()
        C.update(THEMES[name])
        self.theme_name = name
        ctk.set_appearance_mode(C["mode"])  # also gives the log window a dark title bar on Windows
        super().__init__(fg_color=C["bg"])
        load_fonts()
        self.title(f"{APP_NAME} {VERSION}")
        self.geometry("1120x780")
        self.minsize(1040, 720)
        ico = resource("framediet.ico")
        if os.name == "nt" and os.path.isfile(ico):
            try:
                self.iconbitmap(ico)
            except Exception:
                pass

        set_lang(saved.get("lang", "en"))
        self.q = queue.Queue()
        self.cancel_flag = False
        self.running = False
        self.videos = []
        self.src_info = None
        self.src_img = None
        self.seq_pil = []
        self.frames_img = []
        self.prev_mode = None
        self.play_job = None
        self.last_out = ""
        self.last_report = None
        self.queue_status = {}
        self.tmp = tempfile.mkdtemp(prefix="framediet_prev_")
        self._thr_job = None
        self._log_lines = []
        self._status = ("ready", {}, False)
        self.log_open = False

        g = saved.get
        self.v = {
            "limit": tk.StringVar(value=str(g("limit", "2"))),
            "unit": tk.StringVar(value=g("unit", "MB")),
            "mode": tk.StringVar(value=g("mode", "total")),
            "allow_colors": tk.BooleanVar(value=g("allow_colors", True)),
            "allow_scale": tk.BooleanVar(value=g("allow_scale", True)),
            "allow_frames": tk.BooleanVar(value=g("allow_frames", False)),
            "max_scale": tk.StringVar(value=g("max_scale", "100%")),
            "min_scale": tk.StringVar(value=str(g("min_scale", "25%"))),
            "min_colors": tk.StringVar(value=str(g("min_colors", "64"))),
            "fps": tk.StringVar(value=g("fps", "")),
            "key": tk.StringVar(value=g("key", "none")),
            "threshold": tk.DoubleVar(value=g("threshold", 0)),
            "autocrop": tk.BooleanVar(value=g("autocrop", False)),
            "backup_on": tk.BooleanVar(value=g("backup_on", False)),
            "backup_frame": tk.StringVar(value=g("backup_frame", "last")),
            "backup_fmt": tk.StringVar(value=g("backup_fmt", "png")),
            "backup_limit": tk.StringVar(value=str(g("backup_limit_kb", "150"))),
            "name_prefix": tk.StringVar(value=g("name_prefix", "")),
            "name_suffix": tk.StringVar(value=g("name_suffix", "")),
            "name_sep": tk.StringVar(value=g("name_sep", "_")),
            "name_start": tk.StringVar(value=str(g("name_start", 0))),
            "name_digits": tk.StringVar(value=str(g("name_digits", 4))),
            "bg": tk.StringVar(value="checker"),
            "out": tk.StringVar(value=""),
            "preset": tk.StringVar(value=g("preset", "")),
            "tab": tk.StringVar(value="size"),
        }

        self.build()
        if HAS_DND:
            self.drop_target_register(DND_FILES)
            self.dnd_bind("<<Drop>>", self.on_drop)
        self.after(80, self.poll)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        for k in ("name_prefix", "name_suffix"):  # example follows the value however it changes (typing, preset)
            self.v[k].trace_add("write", lambda *_: self.update_name_example())
        # hotkeys work in every window of the app (main + log) and with any keyboard layout
        self.bind_all("<Control-KeyPress>", self.on_ctrl_key, add="+")
        self.bind_all("<Escape>", self.on_escape, add="+")

    # ============================================================ building
    def build(self):
        for w in self.winfo_children():
            if not isinstance(w, ctk.CTkToplevel):
                w.destroy()
        self.build_header()
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=24, pady=(0, 24))
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=0)
        body.grid_rowconfigure(0, weight=1)
        left = self.card(body)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        right = self.card(body, width=410)
        right.grid(row=0, column=1, sticky="nsew")
        right.pack_propagate(False)
        self.build_preview(left)
        self.build_settings(right)
        self.refresh_input()
        self.rerender()
        self.restore_log_and_status()

    def card(self, master, **kw):
        return ctk.CTkFrame(master, fg_color=C["card"], corner_radius=16, border_width=1,
                            border_color=C["border"], **kw)

    def build_header(self):
        head = ctk.CTkFrame(self, fg_color="transparent", height=64)
        head.pack(fill="x", padx=28, pady=(14, 10))
        logo = ctk.CTkFrame(head, fg_color="transparent")
        logo.pack(side="left")
        mark = tk.Canvas(logo, width=30, height=30, bg=C["bg"], highlightthickness=0)
        mark.create_rectangle(2, 2, 28, 28, fill=C["text"], outline="")
        mark.create_text(13, 15, text="F", fill=C["bg"], font=F(15, "bold"))
        mark.create_oval(19, 19, 25, 25, fill=C["signal"], outline="")
        mark.pack(side="left", padx=(0, 10))
        ctk.CTkLabel(logo, text="FrameDiet", font=F(20, "bold"), text_color=C["text"]).pack(side="left")
        ctk.CTkLabel(logo, text=f"  {VERSION}", font=F(11), text_color=C["faint"]).pack(side="left", pady=(4, 0))
        ctk.CTkLabel(logo, text=f"   {t('app_tagline')}", font=F(12), text_color=C["muted"]).pack(side="left", pady=(3, 0))
        self.segmented(head, {"en": "EN", "ru": "RU"}, get_lang(), self.switch_lang, height=28, font=F(11, "bold"),
                       width=96).pack(side="right")
        self.segmented(head, {"paper": t("theme_light"), "graphite": t("theme_dark")}, self.theme_name,
                       self.switch_theme, height=28, font=F(11, "bold")).pack(side="right", padx=(0, 10))

    # ---------------------------------------------------------------- left: preview
    def build_preview(self, master):
        bar = ctk.CTkFrame(master, fg_color="transparent")
        bar.pack(fill="x", padx=20, pady=(16, 10))
        self.file_title = ctk.CTkLabel(bar, text=t("preview"), font=F(14, "bold"), text_color=C["text"], anchor="w")
        self.file_title.pack(side="left")
        self.file_sub = ctk.CTkLabel(bar, text="", font=F(12), text_color=C["muted"], anchor="w")
        self.file_sub.pack(side="left", padx=(10, 0))
        self.segmented(bar, {"checker": t("bg_checker"), "white": t("bg_white"), "black": t("bg_black")},
                       self.v["bg"].get(), lambda c: (self.v["bg"].set(c), self.rerender()),
                       height=28, font=F(11)).pack(side="right")

        foot = ctk.CTkFrame(master, fg_color="transparent")
        foot.pack(fill="x", padx=20, pady=(12, 16), side="bottom")
        self.stat_vals = {}
        for i, key in enumerate(["st_weight", "st_size", "st_colors", "st_frames"]):
            foot.grid_columnconfigure(i, weight=1, uniform="stat")
            cell = ctk.CTkFrame(foot, fg_color="transparent")
            cell.grid(row=0, column=i, sticky="w")
            ctk.CTkLabel(cell, text=t(key), font=F(10, "bold"), text_color=C["faint"], anchor="w").pack(anchor="w")
            v = ctk.CTkLabel(cell, text="—", font=F(20, "bold"), text_color=C["text"], anchor="w")
            v.pack(anchor="w")
            self.stat_vals[key] = v
        self.btn_open = Btn(foot, text=t("open_folder"), width=120, height=34, corner_radius=10,
                                      fg_color=C["field"], hover_color=C["track"], text_color=C["text"],
                                      border_width=1, border_color=C["field_border"], font=F(12, "bold"),
                                      command=self.open_out, state="normal" if self.last_out else "disabled")
        self.btn_open.grid(row=0, column=4, sticky="e")
        info = ctk.CTkFrame(master, fg_color="transparent")
        info.pack(fill="x", padx=20, side="bottom", pady=(6, 0))
        self.prev_tag = ctk.CTkLabel(info, text="", font=F(11), text_color=C["muted"], height=18, anchor="w")
        self.prev_tag.pack(side="left")
        self.crop_lbl = ctk.CTkLabel(info, text="", font=F(11), text_color=C["muted"], height=18, anchor="e")
        self.crop_lbl.pack(side="right")

        self.queue_box = ctk.CTkTextbox(master, fg_color=C["field"], height=72, corner_radius=10, font=F(11),
                                        text_color=C["muted"], border_width=0, wrap="none")
        self.queue_box.tag_config("done", foreground=C["signal_text"])
        self.queue_box.tag_config("error", foreground=C["error"])
        self.queue_box.tag_config("running", foreground=C["text"])

        self.stage = ctk.CTkFrame(master, fg_color=C["card"], corner_radius=12)
        self.stage.pack(fill="both", expand=True, padx=20)
        self.drop = DropArea(self.stage, self.pick_videos)
        self.preview = ctk.CTkLabel(self.stage, text="", fg_color=C["field"], corner_radius=12)
        self.preview.bind("<Button-1>", lambda e: self.pick_videos())
        if self.last_report:
            self.show_stats(self.last_report)

    # ---------------------------------------------------------------- right: settings
    def build_settings(self, master):
        pad = 20
        bottom = ctk.CTkFrame(master, fg_color="transparent")
        bottom.pack(fill="x", padx=pad, pady=(6, 18), side="bottom")
        orow = ctk.CTkFrame(bottom, fg_color="transparent")
        orow.pack(fill="x")
        ctk.CTkLabel(orow, text=t("output"), font=F(12, "bold"), text_color=C["muted"], width=60, anchor="w").pack(side="left")
        self.entry(orow, self.v["out"], placeholder=t("output_ph")).pack(side="left", fill="x", expand=True)
        self.ghost_button(orow, "…", self.pick_out, width=34).pack(side="left", padx=(6, 0))
        self.btn = Btn(bottom, text="", height=50, corner_radius=12, fg_color=C["accent"],
                                 hover_color=C["accent_hover"], text_color=C["on_accent"], font=F(15, "bold"),
                                 command=self.start)
        self.btn.pack(fill="x", pady=(12, 0))
        self.pb = ctk.CTkProgressBar(bottom, height=4, corner_radius=2, fg_color=C["track"], progress_color=C["signal"])
        self.pb.set(0)
        self.pb.pack(fill="x", pady=(12, 6))
        srow = ctk.CTkFrame(bottom, fg_color="transparent")
        srow.pack(fill="x")
        self.status = ctk.CTkLabel(srow, text="", font=F(11), text_color=C["muted"], anchor="w", wraplength=220,
                                   justify="left")
        self.status.pack(side="left", fill="x", expand=True)
        self.btn_cancel = Btn(srow, text=t("cancel"), width=64, height=24, fg_color="transparent",
                                        hover_color=C["track"], text_color=C["muted"], font=F(11),
                                        command=self.cancel, state="normal" if self.running else "disabled")
        self.btn_cancel.pack(side="right")
        self.btn_log = Btn(srow, text=t("hide_log") if self.log_open else t("show_log"), width=84, height=24,
                                     fg_color="transparent", hover_color=C["track"], text_color=C["muted"], font=F(11),
                                     command=self.toggle_log)
        self.btn_log.pack(side="right")
        self.log_win = None
        self.logbox = None
        if self.log_open:
            self.log_open = False
            self.after(50, self.toggle_log)

        top = ctk.CTkFrame(master, fg_color="transparent")
        top.pack(fill="x", padx=pad, pady=(18, 0))
        ctk.CTkLabel(top, text=t("preset"), font=F(12, "bold"), text_color=C["muted"]).pack(anchor="w")
        prow = ctk.CTkFrame(top, fg_color="transparent")
        prow.pack(fill="x", pady=(6, 0))
        names = [t("preset_custom")] + [p["name"] for p in presets.all_presets()]
        cur = self.v["preset"].get() or t("preset_custom")
        if cur not in names:
            cur = t("preset_custom")
        self.preset_menu = self.option_menu(prow, names, cur, self.apply_preset, width=170)
        self.preset_menu.pack(side="left", fill="x", expand=True)
        self.ghost_button(prow, t("preset_save"), self.save_preset, width=92).pack(side="left", padx=(8, 0))
        self.btn_del_preset = Btn(prow, text="✕", width=34, height=34, corner_radius=10,
                                            fg_color="transparent", hover_color=C["track"], text_color=C["muted"],
                                            font=F(12), command=self.delete_preset)
        self.btn_del_preset.pack(side="left", padx=(4, 0))
        self.preset_note = ctk.CTkLabel(top, text="", font=F(11), text_color=C["muted"], anchor="w", justify="left",
                                        wraplength=360)
        self.preset_note.pack(fill="x", pady=(4, 0))
        self.update_preset_note()

        tabs = {"size": t("tab_size"), "bg": t("tab_bg"), "names": t("tab_names"), "extras": t("tab_extras")}
        self.tab_names = tabs
        self.tab_seg = self.segmented(master, tabs, self.v["tab"].get(), self.show_tab, height=36, font=F(12, "bold"))
        self.tab_seg.pack(fill="x", padx=pad, pady=(14, 4))
        self.tab_holder = ctk.CTkFrame(master, fg_color="transparent")
        self.tab_holder.pack(fill="both", expand=True, padx=pad)
        self.tab_frames = {k: ctk.CTkFrame(self.tab_holder, fg_color="transparent") for k in tabs}
        self.build_tab_size(self.tab_frames["size"])
        self.build_tab_bg(self.tab_frames["bg"])
        self.build_tab_names(self.tab_frames["names"])
        self.build_tab_extras(self.tab_frames["extras"])
        self.show_tab(self.v["tab"].get())
        self.update_start_label()

    def show_tab(self, key):
        self.v["tab"].set(key)
        seg = getattr(self, "tab_seg", None)
        if seg is not None and seg.winfo_exists() and seg.get() != self.tab_names[key]:
            seg.set(self.tab_names[key])
            for name, btn in seg._buttons_dict.items():
                btn.configure(text_color=C["sel_text"] if name == self.tab_names[key] else C["muted"])
        for fr in self.tab_frames.values():
            fr.pack_forget()
        self.tab_frames[key].pack(fill="both", expand=True)

    def label(self, master, text, **kw):
        return ctk.CTkLabel(master, text=text, font=F(12, "bold"), text_color=C["muted"], anchor="w", **kw)

    def build_tab_size(self, f):
        self.label(f, t("limit")).pack(fill="x", pady=(10, 6))
        lim = ctk.CTkFrame(f, fg_color="transparent")
        lim.pack(fill="x")
        ctk.CTkEntry(lim, textvariable=self.v["limit"], width=84, height=40, justify="center", fg_color=C["field"],
                     border_color=C["field_border"], border_width=1, corner_radius=10, text_color=C["text"],
                     font=F(20, "bold")).pack(side="left")
        self.segmented(lim, {"MB": t("mb"), "KB": "KB" if get_lang() == "en" else "КБ"}, self.v["unit"].get(),
                       lambda c: self.v["unit"].set(c), height=40, width=110).pack(side="left", padx=8)
        self.segmented(f, {"total": t("mode_total"), "frame": t("mode_frame")}, self.v["mode"].get(),
                       lambda c: self.v["mode"].set(c), height=32).pack(fill="x", pady=(10, 0))

        self.label(f, t("allowed")).pack(fill="x", pady=(14, 2))
        self.switch_row(f, t("sw_colors"), self.v["allow_colors"], [str(c) for c in core.COLOR_STEPS[1:]],
                        self.v["min_colors"])
        self.switch_row(f, t("sw_scale"), self.v["allow_scale"], [f"{s}%" for s in core.SCALE_STEPS[1:]],
                        self.v["min_scale"])
        self.switch(f, t("sw_frames"), self.v["allow_frames"])

        g = ctk.CTkFrame(f, fg_color="transparent")
        g.pack(fill="x", pady=(10, 0))
        g.grid_columnconfigure((0, 1), weight=1, uniform="g")
        self.label(g, t("start_scale")).grid(row=0, column=0, sticky="w")
        fl = ctk.CTkFrame(g, fg_color="transparent")
        fl.grid(row=0, column=1, sticky="ew", padx=(10, 0))
        self.label(fl, t("fps")).pack(side="left")
        self.fps_hint = ctk.CTkLabel(fl, text="", font=F(11), text_color=C["faint"])
        self.fps_hint.pack(side="right")
        self.option_menu(g, SCALES, self.v["max_scale"].get(), lambda v: self.v["max_scale"].set(v)).grid(
            row=1, column=0, sticky="ew", pady=(6, 0))
        self.fps_box = ctk.CTkComboBox(g, values=[t("fps_source")] + FPS_CHOICES, height=34, corner_radius=10,
                                       fg_color=C["field"], border_color=C["field_border"], border_width=1,
                                       button_color=C["field"], button_hover_color=C["track"], text_color=C["text"],
                                       font=F(12), dropdown_fg_color=C["card"], dropdown_text_color=C["text"],
                                       dropdown_hover_color=C["track"], dropdown_font=F(12),
                                       command=lambda v: self.on_fps_text())
        self.fps_box.set(self.v["fps"].get() or t("fps_source"))
        self.fps_box.grid(row=1, column=1, sticky="ew", padx=(10, 0), pady=(6, 0))
        self.fps_box.bind("<KeyRelease>", lambda e: self.on_fps_text())
        self.update_fps_hint()

    def build_tab_bg(self, f):
        self.label(f, t("unmult_title")).pack(fill="x", pady=(10, 6))
        self.segmented(f, {"none": t("key_none"), "black": t("key_black"), "white": t("key_white")},
                       self.v["key"].get(), self.on_key, height=36).pack(fill="x")
        tf = ctk.CTkFrame(f, fg_color="transparent")
        tf.pack(fill="x", pady=(18, 0))
        self.label(tf, t("threshold")).pack(side="left")
        self.thr_lbl = ctk.CTkLabel(tf, text=f"{int(self.v['threshold'].get())}%", font=F(12, "bold"), text_color=C["text"])
        self.thr_lbl.pack(side="right")
        ctk.CTkSlider(f, from_=0, to=30, number_of_steps=30, height=18, fg_color=C["track"], progress_color=C["accent"],
                      button_color=C["accent"], button_hover_color=C["accent_hover"],
                      variable=self.v["threshold"], command=self.on_thr).pack(fill="x", pady=(8, 0))
        ctk.CTkLabel(f, text=t("unmult_hint"), font=F(11), text_color=C["muted"], anchor="w", justify="left",
                     wraplength=360).pack(fill="x", pady=(16, 0))

    def build_tab_extras(self, f):
        self.label(f, t("autocrop_title")).pack(fill="x", pady=(10, 2))
        self.switch(f, t("sw_autocrop"), self.v["autocrop"])
        ctk.CTkLabel(f, text=t("autocrop_hint"), font=F(11), text_color=C["muted"], anchor="w", justify="left",
                     wraplength=360).pack(fill="x")
        self.label(f, t("backup_title")).pack(fill="x", pady=(18, 2))
        self.switch(f, t("sw_backup"), self.v["backup_on"])
        g = ctk.CTkFrame(f, fg_color="transparent")
        g.pack(fill="x", pady=(8, 0))
        g.grid_columnconfigure(0, weight=3)
        g.grid_columnconfigure(1, weight=2)
        self.label(g, t("backup_frame")).grid(row=0, column=0, sticky="w")
        self.label(g, t("backup_limit")).grid(row=0, column=1, sticky="w", padx=(10, 0))
        frames = {k: t("bf_" + k) for k in core.BACKUP_FRAMES}
        inv = {v: k for k, v in frames.items()}
        self.option_menu(g, list(frames.values()), frames.get(self.v["backup_frame"].get(), frames["last"]),
                         lambda v: self.v["backup_frame"].set(inv[v])).grid(row=1, column=0, sticky="ew", pady=(6, 0))
        self.entry(g, self.v["backup_limit"], justify="center").grid(row=1, column=1, sticky="ew", padx=(10, 0), pady=(6, 0))
        self.segmented(f, {"png": t("fmt_png"), "jpg": t("fmt_jpg")}, self.v["backup_fmt"].get(),
                       lambda c: self.v["backup_fmt"].set(c), height=32, font=F(11)).pack(fill="x", pady=(10, 0))

    def build_tab_names(self, f):
        g = ctk.CTkFrame(f, fg_color="transparent")
        g.pack(fill="x", pady=(10, 0))
        g.grid_columnconfigure((0, 1), weight=1, uniform="n")
        self.label(g, t("name_prefix")).grid(row=0, column=0, sticky="w")
        self.label(g, t("name_suffix")).grid(row=0, column=1, sticky="w", padx=(10, 0))
        e1 = self.entry(g, self.v["name_prefix"], placeholder=t("name_prefix_ph"))
        e1.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        e2 = self.entry(g, self.v["name_suffix"], placeholder=t("name_suffix_ph"))
        e2.grid(row=1, column=1, sticky="ew", padx=(10, 0), pady=(6, 0))
        for e in (e1, e2):
            e.bind("<KeyRelease>", lambda ev: self.update_name_example())

        self.label(f, t("name_sep")).pack(fill="x", pady=(14, 6))
        seps = {"_": "_", "-": "-", ".": ".", "": t("sep_none")}
        self.segmented(f, seps, self.v["name_sep"].get(),
                       lambda c: (self.v["name_sep"].set(c), self.update_name_example()), height=32).pack(fill="x")

        g2 = ctk.CTkFrame(f, fg_color="transparent")
        g2.pack(fill="x", pady=(14, 0))
        g2.grid_columnconfigure(0, weight=2, uniform="m")
        g2.grid_columnconfigure(1, weight=3, uniform="m")
        self.label(g2, t("name_start")).grid(row=0, column=0, sticky="w")
        self.label(g2, t("name_digits")).grid(row=0, column=1, sticky="w", padx=(10, 0))
        self.segmented(g2, {"0": "0", "1": "1"}, self.v["name_start"].get(),
                       lambda c: (self.v["name_start"].set(c), self.update_name_example()),
                       height=32).grid(row=1, column=0, sticky="ew", pady=(6, 0))
        digs = {str(d): str(d) for d in core.NAME_DIGITS}
        self.segmented(g2, digs, self.v["name_digits"].get(),
                       lambda c: (self.v["name_digits"].set(c), self.update_name_example()),
                       height=32).grid(row=1, column=1, sticky="ew", padx=(10, 0), pady=(6, 0))

        self.label(f, t("name_example")).pack(fill="x", pady=(14, 4))
        box = ctk.CTkFrame(f, fg_color=C["track"], corner_radius=10)
        box.pack(fill="x")
        self.name_example = ctk.CTkLabel(box, text="", font=F(12), text_color=C["text"], anchor="w", justify="left",
                                         wraplength=340)
        self.name_example.pack(fill="x", padx=12, pady=8)
        ctk.CTkLabel(f, text=t("names_hint"), font=F(11), text_color=C["muted"], anchor="w", justify="left",
                     wraplength=360).pack(fill="x", pady=(10, 0))
        self.update_name_example()

    def naming(self):
        return {"prefix": self.v["name_prefix"].get(), "suffix": self.v["name_suffix"].get(),
                "sep": self.v["name_sep"].get(), "start": int(self.v["name_start"].get() or 0),
                "digits": int(self.v["name_digits"].get() or 4)}

    def update_name_example(self):
        lbl = getattr(self, "name_example", None)
        if lbl is None or not lbl.winfo_exists():
            return
        video = self.videos[0] if self.videos else "video.mov"
        info = self.src_info if isinstance(self.src_info, dict) else None
        count = (info or {}).get("frames") or 37
        try:
            _, ni = core.make_namer(self.naming(), video, count)
            lbl.configure(text=t("name_example_n", first=ni["first"], last=ni["last"]), text_color=C["text"])
        except core.BadName:
            lbl.configure(text=t("err_name"), text_color=C["error"])

    # ============================================================ widgets
    def segmented(self, master, options, current, on_change, height=34, font=None, width=None):
        """options = {code: label}; on_change(code). Light pill track, white selected pill."""
        inv = {v: k for k, v in options.items()}
        kw = {"width": width} if width else {}
        s = ctk.CTkSegmentedButton(master, values=list(options.values()), height=height, font=font or F(12),
                                   corner_radius=10, border_width=3, fg_color=C["track"], unselected_color=C["track"],
                                   unselected_hover_color=C["border"], selected_color=C["sel"],
                                   selected_hover_color=C["sel"], text_color=C["muted"], **kw)
        s.set(options.get(current, list(options.values())[0]))

        def recolor():
            try:
                if not s.winfo_exists():
                    return
                cur = s.get()
                for name, btn in s._buttons_dict.items():
                    btn.configure(text_color=C["sel_text"] if name == cur else C["muted"])
            except tk.TclError:  # widget rebuilt before the deferred call ran
                pass

        def cmd(label):
            recolor()
            on_change(inv[label])
        s.configure(command=cmd)
        self.after(10, recolor)
        return s

    def switch(self, master, text, var):
        ctk.CTkSwitch(master, text=text, variable=var, font=F(13), text_color=C["text"], progress_color=C["switch_on"],
                      button_color=C["knob"], button_hover_color=C["accent_hover"], fg_color=C["switch_off"],
                      switch_width=40, switch_height=20).pack(anchor="w", pady=5)

    def switch_row(self, master, text, var, values, value_var):
        """Switch with a floor value on the right; the menu is greyed out while the switch is off."""
        row = ctk.CTkFrame(master, fg_color="transparent")
        row.pack(fill="x", pady=1)
        ctk.CTkSwitch(row, text=text, variable=var, font=F(13), text_color=C["text"], progress_color=C["switch_on"],
                      button_color=C["knob"], button_hover_color=C["accent_hover"], fg_color=C["switch_off"],
                      switch_width=40, switch_height=20).pack(side="left")
        cur = value_var.get() if value_var.get() in values else values[-1]
        value_var.set(cur)
        m = self.option_menu(row, values, cur, lambda v: value_var.set(v), width=84, height=30)
        m.pack(side="right")

        def sync(*_):
            try:
                if m.winfo_exists():
                    m.configure(state="normal" if var.get() else "disabled")
            except tk.TclError:
                pass
        sync()
        tid = var.trace_add("write", sync)
        row.bind("<Destroy>", lambda e: self._untrace(var, tid) if e.widget is row else None)

    @staticmethod
    def _untrace(var, tid):
        try:
            var.trace_remove("write", tid)
        except (tk.TclError, ValueError):
            pass

    def option_menu(self, master, values, current, command, width=140, height=34):
        m = ctk.CTkOptionMenu(master, values=values, width=width, height=height, corner_radius=10, fg_color=C["field"],
                              button_color=C["field"], button_hover_color=C["track"], text_color=C["text"],
                              font=F(12), dropdown_fg_color=C["card"], dropdown_text_color=C["text"],
                              dropdown_hover_color=C["track"], dropdown_font=F(12), command=command,
                              dynamic_resizing=False, text_color_disabled=C["faint"])
        m.set(current)
        return m

    def entry(self, master, var, placeholder=None, justify="left"):
        e = ctk.CTkEntry(master, textvariable=var, height=34, corner_radius=10, fg_color=C["field"],
                         border_color=C["field_border"], border_width=1, text_color=C["text"], font=F(12),
                         justify=justify)
        if placeholder:
            self._placeholder(e, var, placeholder)
        return e

    def _placeholder(self, e, var, text):
        """CTkEntry ignores placeholder_text when a textvariable is set, so draw our own hint over it."""
        hint = ctk.CTkLabel(e, text=text, fg_color=C["field"], text_color=C["faint"], font=F(12), height=20,
                            cursor="xterm")

        def sync(*_):
            try:
                if not hint.winfo_exists():
                    return
                if var.get() or e.focus_get() is e._entry:
                    hint.place_forget()
                else:
                    hint.place(x=11, rely=0.5, anchor="w")
            except (tk.TclError, KeyError):
                pass
        hint.bind("<Button-1>", lambda ev: e._entry.focus_set())
        e._entry.bind("<FocusIn>", sync, add="+")
        e._entry.bind("<FocusOut>", sync, add="+")
        tid = var.trace_add("write", sync)
        e.bind("<Destroy>", lambda ev: self._untrace(var, tid) if ev.widget is e else None, add="+")
        self.after(30, sync)

    def ghost_button(self, master, text, command, width=80):
        return Btn(master, text=text, width=width, height=34, corner_radius=10, fg_color=C["card"],
                             hover_color=C["track"], text_color=C["text"], border_width=1,
                             border_color=C["field_border"], font=F(12, "bold"), command=command)

    # ============================================================ language / presets
    def switch_lang(self, code):
        if code == get_lang():
            return
        set_lang(code)
        self.stop_play()
        was_open = self.log_open
        self.close_log()
        self.log_open = was_open
        self.build()

    def switch_theme(self, name):
        if name == self.theme_name or name not in THEMES:
            return
        self.theme_name = name
        C.clear()
        C.update(THEMES[name])
        ctk.set_appearance_mode(C["mode"])
        self.configure(fg_color=C["bg"])
        self.stop_play()
        was_open = self.log_open
        self.close_log()
        self.log_open = was_open
        self.build()  # rebuild re-reads C everywhere, preview frames are re-composited on the new checker
        try:
            self.save_state()
        except Exception:
            pass

    def apply_preset(self, name):
        self.v["preset"].set("" if name == t("preset_custom") else name)
        p = next((p for p in presets.all_presets() if p["name"] == name), None)
        if p:
            s = p["settings"]
            for k in ("limit", "unit", "allow_colors", "allow_scale", "allow_frames", "max_scale", "min_scale",
                      "min_colors", "key", "threshold",
                      "autocrop", "backup_on", "backup_frame", "backup_fmt",
                      "name_prefix", "name_suffix", "name_sep", "name_start", "name_digits"):
                if k in s:
                    self.v[k].set(str(s[k]) if isinstance(self.v[k], tk.StringVar) else s[k])
            if "per_frame" in s:
                self.v["mode"].set("frame" if s["per_frame"] else "total")
            if "fps" in s:
                self.v["fps"].set(str(s["fps"] or ""))
            if "backup_limit_kb" in s:
                self.v["backup_limit"].set(str(s["backup_limit_kb"]))
            self.stop_play()
            self.build()
        else:
            self.update_preset_note()

    def update_preset_note(self):
        name = self.v["preset"].get()
        p = next((p for p in presets.all_presets() if p["name"] == name), None)
        note = t(p["note_key"]) if p and p.get("note_key") else ""
        self.preset_note.configure(text=note)
        if not note:
            self.preset_note.pack_forget()
        self.btn_del_preset.configure(state="normal" if p and not p.get("builtin") else "disabled")

    def current_settings(self):
        return {"limit": self.v["limit"].get(), "unit": self.v["unit"].get(),
                "per_frame": self.v["mode"].get() == "frame", "max_scale": self.v["max_scale"].get(),
                "min_scale": self.v["min_scale"].get(), "min_colors": self.v["min_colors"].get(),
                "fps": self.v["fps"].get(), "allow_colors": self.v["allow_colors"].get(),
                "allow_scale": self.v["allow_scale"].get(), "allow_frames": self.v["allow_frames"].get(),
                "key": self.v["key"].get(), "threshold": int(self.v["threshold"].get()),
                "autocrop": self.v["autocrop"].get(), "backup_on": self.v["backup_on"].get(),
                "backup_frame": self.v["backup_frame"].get(), "backup_fmt": self.v["backup_fmt"].get(),
                "backup_limit_kb": self.v["backup_limit"].get(),
                "name_prefix": self.v["name_prefix"].get(), "name_suffix": self.v["name_suffix"].get(),
                "name_sep": self.v["name_sep"].get(), "name_start": int(self.v["name_start"].get() or 0),
                "name_digits": int(self.v["name_digits"].get() or 4)}

    def save_preset(self):
        d = ctk.CTkInputDialog(text=t("preset_name_prompt"), title=t("preset_name_title"), fg_color=C["card"],
                               button_fg_color=C["accent"], button_hover_color=C["accent_hover"],
                               button_text_color=C["on_accent"], entry_fg_color=C["field"],
                               entry_border_color=C["field_border"], entry_text_color=C["text"], text_color=C["text"])
        name = (d.get_input() or "").strip()
        if not name:
            return
        if presets.save_user_preset(name, self.current_settings()):
            self.v["preset"].set(name)
            self.set_status("preset_saved", name=name)
            self.stop_play()
            self.build()

    def delete_preset(self):
        name = self.v["preset"].get()
        if name:
            presets.delete_user_preset(name)
            self.v["preset"].set("")
            self.stop_play()
            self.build()

    # ============================================================ hotkeys
    HOTKEY_OPEN = {"o", "O", "Cyrillic_shcha", "Cyrillic_SHCHA"}   # Ctrl+O on EN and RU layouts
    HOTKEY_START = {"Return", "KP_Enter"}

    def on_ctrl_key(self, e):
        """Ctrl+O — choose videos, Ctrl+Enter — start. Windows VK code 79 = O on any layout."""
        if e.keysym in self.HOTKEY_START:
            if not self.running:
                self.start()
            return "break"
        if e.keysym in self.HOTKEY_OPEN or (os.name == "nt" and e.keycode == 79):
            self.after(1, self.pick_videos)  # let the key event finish before the modal dialog opens
            return "break"
        return None

    def on_escape(self, e=None):
        """Esc — cancel the running job; otherwise close the log window."""
        if self.running:
            if not self.cancel_flag:
                self.cancel()
            return "break"
        if self.log_open:
            self.close_log()
            return "break"
        return None

    # ============================================================ input
    def pick_videos(self):
        if self.running:
            return
        ps = filedialog.askopenfilenames(filetypes=[("Video", " ".join("*" + e for e in VIDEO_EXT)), ("*", "*.*")])
        if ps:
            self.set_videos(list(ps))

    def pick_out(self):
        p = filedialog.askdirectory()
        if p:
            self.v["out"].set(os.path.normpath(p))  # the dialog returns E:/a/b — show it the Windows way

    def on_drop(self, e):
        self.set_videos(collect_videos(self.tk.splitlist(e.data)))

    def set_videos(self, paths):
        if self.running or not paths:
            return
        paths = [os.path.normpath(p) for p in paths]
        self.videos = paths
        self.queue_status = {}
        self.src_info = None
        self.src_img = None
        self.stop_play()
        self.seq_pil, self.prev_mode = [], None
        self.last_report = None
        if len(paths) == 1:
            base = os.path.splitext(os.path.basename(paths[0]))[0]
            self.v["out"].set(os.path.join(os.path.dirname(paths[0]), base + "_png"))
        else:
            self.v["out"].set(os.path.dirname(paths[0]))
        self.refresh_input()
        self.reset_stats()
        self.update_start_label()
        self.update_name_example()
        first = paths[0]

        def work():
            try:
                info = core.probe(first)
                prev = os.path.join(self.tmp, "src.png")
                ok = core.first_frame(first, prev)
                self.q.put(("probed", (first, info, prev if ok else None)))
            except Exception as ex:
                self.q.put(("probed", (first, None, str(ex))))
        threading.Thread(target=work, daemon=True).start()

    def show_stage(self, has_image):
        if has_image:
            self.drop.pack_forget()
            if not self.preview.winfo_ismapped():
                self.preview.pack(fill="both", expand=True)
        else:
            self.preview.pack_forget()
            if not self.drop.winfo_ismapped():
                self.drop.pack(fill="both", expand=True)

    def refresh_input(self):
        self.show_stage(bool(self.seq_pil))
        if not self.videos:
            self.file_title.configure(text=t("preview"))
            self.file_sub.configure(text="")
            self.queue_box.pack_forget()
            return
        if len(self.videos) == 1:
            self.queue_box.pack_forget()
            info = self.src_info
            if info is None:
                sub = t("reading")
            elif info == "error":
                sub = t("cant_read")
            else:
                fr = f"  ·  {t('frames_n', n=info['frames'])}" if info["frames"] else ""
                sub = f"{info['w']}×{info['h']}  ·  {info['fps']:g} fps{fr}  ·  " + (t("alpha_yes") if info["alpha"] else t("alpha_no"))
            name = os.path.basename(self.videos[0])
            self.file_title.configure(text=name if len(name) < 34 else name[:15] + "…" + name[-15:])
            warn = isinstance(info, dict) and not info["alpha"] and self.v["key"].get() == "none"
            self.file_sub.configure(text=sub, text_color=C["error"] if warn else C["muted"])
        else:
            self.file_title.configure(text=t("queued", n=len(self.videos)))
            self.file_sub.configure(text="")
            self.render_queue()
            self.queue_box.pack(fill="x", padx=20, pady=(10, 0), before=self.stage)

    def render_queue(self):
        box = self.queue_box
        box.configure(state="normal")
        box.delete("1.0", "end")
        for i, v in enumerate(self.videos):
            st, extra = self.queue_status.get(i, ("", ""))
            mark = {"running": "…", "done": "✓", "error": "✕"}.get(st, "·")
            box.insert("end", f"{mark}  {os.path.basename(v)}   {extra}\n", st or ())
        box.configure(state="disabled")

    def set_queue_line(self, i):
        self.render_queue()

    def on_probed(self, data):
        path, info, prev = data
        if not self.videos or path != self.videos[0]:
            return
        if info is None:
            self.src_info = "error"
            self.refresh_input()
            self.set_status("error", error=True, msg=str(prev)[:120])
            return
        self.src_info = info
        if prev:
            with Image.open(prev) as im:
                self.src_img = im.convert("RGBA")
            self.show_source()
        self.refresh_input()
        self.update_fps_hint()
        self.update_name_example()
        if not info["alpha"] and self.v["key"].get() == "none":
            self.log("log_no_alpha")

    # ============================================================ preview
    def preview_box(self):
        self.update_idletasks()
        try:
            k = self.preview._get_widget_scaling()
        except Exception:
            k = 1.0
        w = int(self.stage.winfo_width() / k) - 24
        h = int(self.stage.winfo_height() / k) - 24
        return (w, h) if w > 50 and h > 50 else (520, 420)

    def show_source(self):
        if self.src_img is None:
            return
        self.stop_play()
        key, thr = self.v["key"].get(), int(round(self.v["threshold"].get())) / 100.0
        im = core.apply_key(fit(self.src_img, self.preview_box()), key, thr)
        tag = t("tag_source") + ("" if key == "none" else t("tag_unmult", thr=int(thr * 100)))
        self.seq_pil, self.prev_mode = [im], ("still", tag)
        self.rerender()

    def rerender(self):
        if not self.seq_pil or not self.prev_mode:
            return
        self.show_stage(True)
        bg = self.v["bg"].get()
        self.frames_img = [ctk.CTkImage(on_bg(im, bg), size=im.size) for im in self.seq_pil]
        kind, val = self.prev_mode
        if kind == "still":
            self.stop_play()
            self.preview.configure(image=self.frames_img[0], text="")
            self.prev_tag.configure(text=val)
        else:
            self.start_loop(val)

    def play_sequence(self, files, fps):
        self.stop_play()
        box = self.preview_box()
        seq = []
        for f in files[:400]:
            with Image.open(f) as im:
                seq.append(fit(im.convert("RGBA"), box))
        if seq:
            self.seq_pil, self.prev_mode = seq, ("seq", fps)
            self.rerender()

    def start_loop(self, fps):
        self.stop_play()
        self.prev_tag.configure(text=t("tag_result", fps=f"{fps:g}"))
        delay = max(16, int(1000 / max(fps, 1)))

        def step(i=0):
            self.preview.configure(image=self.frames_img[i % len(self.frames_img)], text="")
            self.play_job = self.after(delay, step, i + 1)
        step()

    def stop_play(self):
        if self.play_job:
            try:
                self.after_cancel(self.play_job)
            except Exception:
                pass
            self.play_job = None

    def on_key(self, code):
        self.v["key"].set(code)
        self.show_source()
        self.refresh_input()

    def on_thr(self, v):
        self.thr_lbl.configure(text=f"{int(round(v))}%")
        if self.v["key"].get() != "none":
            if self._thr_job:
                self.after_cancel(self._thr_job)
            self._thr_job = self.after(120, self.show_source)

    # ============================================================ fps
    def on_fps_text(self):
        txt = self.fps_box.get().strip()
        self.v["fps"].set("" if txt.lower() in ("", t("fps_source").lower(), "source", "исходный") else txt)
        self.update_fps_hint()

    def out_fps(self):
        v = self.v["fps"].get().strip().replace(",", ".")
        if not v:
            return None
        f = float(v)
        if not 0.5 <= f <= 120:
            raise ValueError
        return f

    def update_fps_hint(self):
        if not hasattr(self, "fps_hint") or not self.fps_hint.winfo_exists():
            return
        info = self.src_info if isinstance(self.src_info, dict) else None
        try:
            f = self.out_fps()
        except ValueError:
            self.fps_hint.configure(text=t("fps_hint_bad"), text_color=C["error"])
            return
        if not info or not info.get("duration"):
            self.fps_hint.configure(text="", text_color=C["faint"])
            return
        if f and f > info["fps"] + 1e-3:
            self.fps_hint.configure(text=t("fps_hint_above", src=f"{info['fps']:g}"), text_color=C["error"])
            return
        self.fps_hint.configure(text=t("fps_hint_frames", n=round(info["duration"] * (f or info["fps"]))), text_color=C["faint"])

    # ============================================================ status / log
    def toggle_log(self):
        if self.log_open and self.log_win is not None:
            self.close_log()
            return
        win = ctk.CTkToplevel(self, fg_color=C["card"])
        win.title(f"{APP_NAME} · {t('show_log')}")
        win.geometry(f"560x320+{self.winfo_rootx() + 120}+{self.winfo_rooty() + 160}")
        win.transient(self)
        bar = ctk.CTkFrame(win, fg_color="transparent")
        bar.pack(fill="x", side="bottom", padx=14, pady=(0, 12))
        self.ghost_button(bar, t("support_btn"), self.save_support_report, width=256).pack(side="right")
        box = ctk.CTkTextbox(win, fg_color=C["field"], text_color=C["text"], font=F(11), corner_radius=10,
                             border_width=0, wrap="word")
        box.pack(fill="both", expand=True, padx=14, pady=(14, 8))
        self.log_win, self.logbox, self.log_open = win, box, True
        for k, p in self._log_lines:
            box.insert("end", log_line(k, **dict(p)) + "\n")
        box.see("end")
        box.configure(state="disabled")
        win.protocol("WM_DELETE_WINDOW", self.close_log)
        self.btn_log.configure(text=t("hide_log"))

    def save_support_report(self):
        """Write a plain-text report the user can send to support. Nothing is sent by the program."""
        parent = self.log_win if self.log_win is not None else self
        desk = os.path.join(os.path.expanduser("~"), "Desktop")
        path = filedialog.asksaveasfilename(parent=parent, defaultextension=".txt", initialfile=support.default_name(),
                                            initialdir=desk if os.path.isdir(desk) else os.path.expanduser("~"),
                                            filetypes=[("Text", "*.txt")])
        if not path:
            return
        try:
            scaling = self._get_widget_scaling()
        except Exception:
            scaling = None
        key, kw, _ = self._status
        status_text = t(key, **{k: (v() if callable(v) else v) for k, v in kw.items()})
        settings = self.current_settings()
        settings["mode"] = self.v["mode"].get()
        text = support.make_report(settings, self.videos,
                                   self.src_info if isinstance(self.src_info, dict) else None,
                                   self.last_report, [log_line(k, **dict(p)) for k, p in self._log_lines],
                                   status_text, get_lang(), scaling)
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        except OSError as ex:
            self.set_status("err_report", error=True, msg=str(ex))
            return
        self.set_status("report_saved", name=os.path.basename(path))

    def close_log(self):
        if self.log_win is not None:
            try:
                self.log_win.destroy()
            except tk.TclError:
                pass
        self.log_win, self.logbox, self.log_open = None, None, False
        if self.btn_log.winfo_exists():
            self.btn_log.configure(text=t("show_log"))

    def set_status(self, key, error=False, **kw):
        self._status = (key, kw, error)
        if self.status.winfo_exists():
            kw = {k: (v() if callable(v) else v) for k, v in kw.items()}  # callables re-translate on language switch
            self.status.configure(text=t(key, **kw)[:200], text_color=C["error"] if error else C["muted"])

    def log(self, key, **p):
        self.q.put(("log", (key, p)))

    def write_log(self, key, p):
        self._log_lines.append((key, p))
        line = log_line(key, **dict(p))
        if self.logbox is not None:
            try:
                self.logbox.configure(state="normal")
                self.logbox.insert("end", line + "\n")
                self.logbox.see("end")
                self.logbox.configure(state="disabled")
            except tk.TclError:
                self.logbox = None
        if self.running:
            self.status.configure(text=line.strip()[:160], text_color=C["muted"])

    def restore_log_and_status(self):
        key, kw, err = self._status
        self.set_status(key, error=err, **kw)

    def update_start_label(self):
        if self.running:
            self.btn.configure(text=t("working"), state="disabled")
        elif len(self.videos) > 1:
            self.btn.configure(text=t("start_batch", n=len(self.videos)), state="normal")
        else:
            self.btn.configure(text=t("start"), state="normal")

    def poll(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "log":
                    self.write_log(*val)
                elif kind == "progress":
                    self.pb.set(val)
                elif kind == "probed":
                    self.on_probed(val)
                elif kind == "item":
                    i, st, rep = val
                    extra = f"{rep['total_mb']:.2f} {t('mb')}" if st == "done" else ""
                    self.queue_status[i] = (st, extra)
                    self.set_queue_line(i)
                elif kind == "done":
                    self.finish(val)
        except queue.Empty:
            pass
        self.after(80, self.poll)

    # ============================================================ run
    def gather(self):
        try:
            limit = float(self.v["limit"].get().replace(",", "."))
            assert limit > 0
        except Exception:
            self.set_status("err_limit", error=True)
            return None
        try:
            fps = self.out_fps()
        except ValueError:
            self.set_status("err_fps", error=True)
            return None
        backup = None
        if self.v["backup_on"].get():
            try:
                kb = float(self.v["backup_limit"].get().replace(",", "."))
                assert kb > 0
            except Exception:
                self.set_status("err_backup_kb", error=True)
                return None
            backup = {"frame": self.v["backup_frame"].get(), "fmt": self.v["backup_fmt"].get(), "limit_kb": kb}
        naming = self.naming()
        try:
            core.make_namer(naming, self.videos[0] if self.videos else "video.mov", 1)
        except core.BadName:
            self.set_status("err_name", error=True)
            self.show_tab("names")
            return None
        if self.v["unit"].get() == "KB":
            limit /= 1024
        return {"limit_mb": limit, "per_frame": self.v["mode"].get() == "frame",
                "max_scale": int(self.v["max_scale"].get().rstrip("%")),
                "min_scale": int(self.v["min_scale"].get().rstrip("%") or 25),
                "min_colors": int(self.v["min_colors"].get() or 64),
                "allow_colors": self.v["allow_colors"].get(), "allow_scale": self.v["allow_scale"].get(),
                "allow_frames": self.v["allow_frames"].get(), "key": self.v["key"].get(),
                "threshold": int(round(self.v["threshold"].get())) / 100.0, "out_fps": fps,
                "autocrop": self.v["autocrop"].get(), "backup": backup, "naming": naming}

    def start(self):
        if not self.videos:
            self.set_status("err_pick_video", error=True)
            return
        settings = self.gather()
        if settings is None:
            return
        self.save_state()
        self.running, self.cancel_flag = True, False
        self.update_start_label()
        self.btn_cancel.configure(state="normal")
        self.btn_open.configure(state="disabled")
        self.pb.set(0)
        self._log_lines = []
        if self.logbox is not None:
            self.logbox.configure(state="normal")
            self.logbox.delete("1.0", "end")
            self.logbox.configure(state="disabled")
        videos = list(self.videos)
        out = self.v["out"].get().strip()
        cb = dict(log=self.log, progress=lambda v: self.q.put(("progress", v)), cancel=lambda: self.cancel_flag)

        def work():
            try:
                if len(videos) == 1:
                    o = out or os.path.splitext(videos[0])[0] + "_png"
                    rep = core.run(videos[0], o, **settings, **cb)
                    self.q.put(("done", ("single", rep, o)))
                else:
                    res = core.run_batch(videos, out or None, settings,
                                         on_item=lambda i, s, r: self.q.put(("item", (i, s, r))), **cb)
                    self.q.put(("done", ("batch", res, out or os.path.dirname(videos[0]))))
            except core.Cancelled:
                self.q.put(("done", ("cancelled", None, None)))
            except core.FitError as ex:
                self.q.put(("done", ("error", ("fit", {"floor": ex.floor, "best": ex.best, "off": ex.off,
                                                         "limit": ex.limit, "per_frame": ex.per_frame}), None)))
            except Exception as ex:
                self.log("log_traceback", tb=traceback.format_exc().strip())  # goes into the support report
                self.q.put(("done", ("error", str(ex), None)))
        threading.Thread(target=work, daemon=True).start()

    def cancel(self):
        self.cancel_flag = True
        self.set_status("cancelling")

    def finish(self, res):
        kind, data, out = res
        self.running = False
        self.update_start_label()
        self.btn_cancel.configure(state="disabled")
        if kind == "cancelled":
            self.write_log("err_cancelled", {})
            self.set_status("err_cancelled", error=True)
            return
        if kind == "error":
            if isinstance(data, tuple) and data[0] == "fit":
                msg = (lambda d=data[1]: self.fit_message(d))
            else:
                msg = (lambda: t("err_fit")) if data == "err_fit" else data
            self.write_log("error", {"msg": msg() if callable(msg) else msg})  # keep it in the support report
            self.set_status("error", error=True, msg=msg)
            return
        self.pb.set(1)
        self.last_out = out
        self.btn_open.configure(state="normal")
        if kind == "single":
            rep = data
            self.last_report = rep
            self.show_stats(rep)
            self.set_status("done", mb=f"{rep['total_mb']:.2f}", lim=f"{rep['limit_mb']:g}",
                            path=os.path.basename(out.rstrip("/\\")) or out)
            files = [os.path.join(out, f) for f in rep.get("files", [])]
            self.play_sequence(files, rep["fps"])
        else:
            ok = sum(1 for _, good, _ in data if good)
            self.set_status("batch_done", ok=ok, total=len(data))
            last_ok = [r for _, good, r in data if good]
            if last_ok:
                self.last_report = last_ok[-1]
                self.show_stats(last_ok[-1])

    @staticmethod
    def size_text(nbytes):
        return f"{nbytes / 1024:.0f} {t('kb')}" if nbytes < 1048576 else f"{nbytes / 1048576:.2f} {t('mb')}"

    def fit_message(self, d):
        """Why it didn't fit and only the advice that can still help (re-translated on language switch)."""
        limit = d["limit"] * 1048576
        lead = (t("err_fit_best", best=self.size_text(d["best"]), limit=self.size_text(limit))
                if d.get("best") else t("err_fit"))
        if not d.get("best"):
            return lead
        adv = [t("adv_" + o) for o in d.get("off", [])]
        if d.get("floor"):
            adv.append(t("adv_floor", floor=self.floor_text(d["floor"])))
        adv.append(t("adv_limit"))
        tail = adv[0] if len(adv) == 1 else ", ".join(adv[:-1]) + f" {t('or')} " + adv[-1]
        return f"{lead} {t('adv_lead')} {tail}."

    @staticmethod
    def floor_text(floor):
        parts = []
        if floor.get("min_scale"):
            parts.append(t("floor_scale", n=floor["min_scale"]))
        if floor.get("min_colors"):
            parts.append(t("floor_colors", n=floor["min_colors"]))
        return ", ".join(parts)

    def show_stats(self, rep):
        self.stat_vals["st_weight"].configure(text=f"{rep['total_mb']:.2f} {t('mb')}", text_color=C["signal_text"])
        self.stat_vals["st_size"].configure(text=rep["size"].replace("x", "×"))
        self.stat_vals["st_colors"].configure(text=str(rep["colors"]))
        self.stat_vals["st_frames"].configure(text=f"{rep['frames']} @ {rep['fps']:g}")
        c = rep.get("crop")
        self.crop_lbl.configure(text=t("crop_info", w=c["w"], h=c["h"], x=c["x"], y=c["y"],
                                       cw=c["canvas_w"], ch=c["canvas_h"]) if c else "")

    def reset_stats(self):
        for v in self.stat_vals.values():
            v.configure(text="—", text_color=C["text"])
        self.crop_lbl.configure(text="")
        self.btn_open.configure(state="disabled")

    def open_out(self):
        if self.last_out and os.path.isdir(self.last_out) and os.name == "nt":
            os.startfile(self.last_out)

    # ============================================================ lifecycle
    def save_state(self):
        s = self.current_settings()
        s["mode"] = self.v["mode"].get()
        s["lang"] = get_lang()
        s["theme"] = self.theme_name
        s["preset"] = self.v["preset"].get()
        presets.save_settings(s)

    def on_close(self):
        self.cancel_flag = True
        self.stop_play()
        try:
            self.save_state()
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)
        self.destroy()


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
