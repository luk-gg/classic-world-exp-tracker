# PyInstaller recipe for the overlay: `pyinstaller exp_tracker.spec` (or run build.ps1).
# One windowed .exe; settings and what you taught it are stored in an exp_tracker_data folder next to it.
# The Qt pieces the app never touches are left out to keep the file small.

EXCLUDES = [
    "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtQuickControls2",
    "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtWebEngineCore",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtXml", "PySide6.QtConcurrent", "PySide6.QtDBus", "PySide6.QtPrintSupport",
    "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "tkinter", "unittest", "test", "PIL", "matplotlib", "scipy", "pandas",
]

a = Analysis(
    ["exp_tracker.py"],
    pathex=["."],
    binaries=[],
    datas=[],
    hiddenimports=["PySide6.QtSvg"],      # the icons are SVGs
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="MapleEXPTracker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
)
