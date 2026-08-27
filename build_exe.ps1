$ErrorActionPreference = "Stop"

Write-Host "=== KML Style Synchronizer - Windows EXE Build ===" -ForegroundColor Cyan
Write-Host "Standalone application: QGIS/AutoCAD/ZWCAD are NOT required." -ForegroundColor Yellow

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install pyinstaller

if (Test-Path "build") { Remove-Item "build" -Recurse -Force }
if (Test-Path "dist") { Remove-Item "dist" -Recurse -Force }

python -m PyInstaller --clean --noconfirm KML_Style_Synchronizer.spec

if (!(Test-Path "dist\KML_Style_Synchronizer.exe")) {
    throw "EXE build failed: dist\KML_Style_Synchronizer.exe was not created."
}

Write-Host "Build successful:" -ForegroundColor Green
Write-Host "dist\KML_Style_Synchronizer.exe" -ForegroundColor Green
