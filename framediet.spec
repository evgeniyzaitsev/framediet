# PyInstaller spec: one-folder build (starts faster and trips antivirus less than --onefile)
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []
for pkg in ("customtkinter", "imagequant", "imageio_ffmpeg", "tkinterdnd2"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h
datas += [("framediet/assets", "assets"), ("LICENSE", "."), ("THIRD_PARTY_LICENSES.txt", ".")]

a = Analysis(["FrameDiet.pyw"], pathex=["."], binaries=binaries, datas=datas,
             hiddenimports=hiddenimports, excludes=["pytest", "matplotlib", "scipy"], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="FrameDiet", console=False,
          icon="framediet/assets/framediet.ico", version="installer/version_info.txt")
coll = COLLECT(exe, a.binaries, a.datas, name="FrameDiet")
