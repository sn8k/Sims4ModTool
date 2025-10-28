@echo off
setlocal ENABLEEXTENSIONS ENABLEDELAYEDEXPANSION

rem Build script for Sims4ModTool using PyInstaller
rem Usage: build.bat

rem Resolve Python launcher
set "PYTHON="
where python >nul 2>&1 && set "PYTHON=python"
if not defined PYTHON (
  where py >nul 2>&1 && set "PYTHON=py -3"
)
if not defined PYTHON (
  echo [ERROR] Python not found in PATH
  exit /b 1
)

rem Ensure PyInstaller is installed
%PYTHON% -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
  echo Installing PyInstaller...
  %PYTHON% -m pip install --user pyinstaller
  if errorlevel 1 (
    echo [ERROR] Failed to install PyInstaller
    exit /b 1
  )
)

set "NAME=Sims4ModTool"
set "ICON="
set "ADD_DATA="

if exist version_release.json (
  set "ADD_DATA=--add-data \"version_release.json;.\""
)

if not exist main.py (
  echo [ERROR] main.py not found
  exit /b 1
)

echo Running PyInstaller...
%PYTHON% -m PyInstaller --clean --exclude-module PySide6 --exclude-module PySide2 --exclude-module PyQt6 --onefile --noconsole --name "%NAME%" %ICON% %ADD_DATA% main.py
if errorlevel 1 (
  echo [ERROR] PyInstaller failed
  exit /b 1
)

echo Build complete. See the "dist" folder for output.
exit /b 0
