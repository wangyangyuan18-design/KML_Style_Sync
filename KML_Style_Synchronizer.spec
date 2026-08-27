# PyInstaller specification for the standalone Windows desktop application.
# No QGIS, ArcGIS, AutoCAD, ZWCAD, or plugin runtime is required.

from PyInstaller.utils.hooks import collect_submodules

hiddenimports = collect_submodules("kml_style_sync")

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "qgis",
        "qgis.PyQt",
        "osgeo",
        "arcpy",
        "PyQt5",
        "PyQt6",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="KML_Style_Synchronizer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)
