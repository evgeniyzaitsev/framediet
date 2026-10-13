"""Platform presets and user settings storage.

Built-in presets only carry limits that come from a platform's published spec (source in `source`).
Everything else is a user preset: the user saves the current settings under a name.
Stored in %APPDATA%\\FrameDiet (Windows) or ~/.config/framediet.
"""
import json
import os

BUILTIN = [
    {
        "id": "google_ads_html5",
        "name": "Google Ads · HTML5 (ZIP ≤ 600 KB)",
        "builtin": True,
        "settings": {"limit": 500, "unit": "KB", "per_frame": False, "backup_on": True,
                     "backup_limit_kb": 150, "backup_fmt": "png"},
        "note_key": "preset_note_google_html5",
        "source": "https://support.google.com/google-ads/answer/1722096",
    },
]

# keys a preset may carry (anything else is ignored when applying)
PRESET_KEYS = ("limit", "unit", "per_frame", "max_scale", "fps", "allow_colors", "allow_scale",
               "allow_frames", "key", "threshold", "autocrop", "backup_on", "backup_frame",
               "backup_fmt", "backup_limit_kb", "backup_bg",
               "name_prefix", "name_suffix", "name_sep", "name_start", "name_digits",
               "min_scale", "min_colors")


def config_dir():
    base = os.environ.get("APPDATA") if os.name == "nt" else os.path.join(os.path.expanduser("~"), ".config")
    path = os.path.join(base or os.path.expanduser("~"), "FrameDiet" if os.name == "nt" else "framediet")
    os.makedirs(path, exist_ok=True)
    return path


def _load(name, default):
    try:
        with open(os.path.join(config_dir(), name), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def _save(name, data):
    try:
        path = os.path.join(config_dir(), name)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except Exception:
        return False


def load_settings():
    return _load("settings.json", {})


def save_settings(data):
    return _save("settings.json", data)


def user_presets():
    data = _load("presets.json", [])
    return [p for p in data if isinstance(p, dict) and p.get("name") and isinstance(p.get("settings"), dict)]


def all_presets():
    return BUILTIN + user_presets()


def save_user_preset(name, settings):
    name = name.strip()[:60]
    if not name:
        return False
    clean = {k: v for k, v in settings.items() if k in PRESET_KEYS}
    presets = [p for p in user_presets() if p["name"] != name]
    presets.append({"id": "user_" + str(abs(hash(name)) % 10**8), "name": name, "settings": clean})
    return _save("presets.json", presets)


def delete_user_preset(name):
    presets = [p for p in user_presets() if p["name"] != name]
    return _save("presets.json", presets)
