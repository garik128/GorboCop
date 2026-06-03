# PyInstaller spec для GorboCop (один EXE).
# Сборка:  .venv\Scripts\python.exe -m PyInstaller GorboCop.spec
from PyInstaller.utils.hooks import collect_all, collect_data_files

datas = []
binaries = []
hiddenimports = []

# MediaPipe тащит модели (.tflite/.binarypb) и нативные библиотеки —
# их нужно собрать целиком, иначе детекция лица не запустится.
for pkg in ("mediapipe",):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# Данные customtkinter (темы, шрифты).
datas += collect_data_files("customtkinter")

# Ресурсы приложения (распакуются в _MEIPASS, читаются через RESOURCE_DIR).
datas += [
    ("alert.mp3", "."),
    ("icon.ico", "."),
    ("icon.png", "."),
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # Не нужны для Face Detection в рантайме (проверено: не импортируются).
    # matplotlib НЕ исключаем — его тянет mediapipe.solutions.
    excludes=["jax", "jaxlib", "scipy", "tensorflow"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="GorboCop",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    runtime_tmpdir=None,
    console=False,
    icon="icon.ico",
)
