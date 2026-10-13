@echo off
setlocal
cd /d "%~dp0"
echo === FrameDiet build ===

set "PY=py -3.12"
where py >nul 2>nul || set "PY=python"
%PY% --version >nul 2>nul || (
  echo Python 3.12 not found - installing via winget...
  winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
  set "PY=%LocalAppData%\Programs\Python\Python312\python.exe"
)
if not exist .venv (
  %PY% -m venv .venv || goto :fail
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements-build.txt || goto :fail

echo --- tests ---
python -m pytest -q tests || goto :fail

echo --- PyInstaller ---
python -m PyInstaller --noconfirm --clean framediet.spec || goto :fail

echo --- installer ---
set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC (
  echo Inno Setup not found - trying winget...
  winget install -e --id JRSoftware.InnoSetup --scope user --silent --accept-package-agreements --accept-source-agreements
  if exist "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
)
if defined ISCC (
  "%ISCC%" installer\FrameDiet.iss || goto :fail
  echo.
  echo Done: dist\FrameDiet-Setup-1.2.0-beta.3.exe
) else (
  echo.
  echo Inno Setup not available. Portable build is in dist\FrameDiet\FrameDiet.exe
)
pause
exit /b 0

:fail
echo.
echo BUILD FAILED - send a screenshot of this window to Claude.
pause
exit /b 1
