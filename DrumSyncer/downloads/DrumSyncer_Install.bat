@echo off
setlocal enabledelayedexpansion
title DrumSyncer v2.0 — One-Click Installer
color 0f

:: ================================================================
::  DRUMSYNCER v2.0 — SINGLE-FILE INSTALLER
::  Kauzak Foundation | kauzak.foundation
::
::  This ONE file does everything:
::    1. Creates the install folder
::    2. Downloads all DrumSyncer files from GitHub
::    3. Installs Python (if not installed)
::    4. Downloads FFmpeg and yt-dlp
::    5. Installs all Python dependencies
::    6. Creates Desktop shortcut
::    7. Launches DrumSyncer
::
::  User just double-clicks this file. That's it.
:: ================================================================

echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║                                                      ║
echo  ║   DrumSyncer v2.0 — Kauzak Foundation                ║
echo  ║   드럼싱커 v2.0 — 카우작 재단                          ║
echo  ║                                                      ║
echo  ║   AI-Powered Drum Cover Video Production             ║
echo  ║   AI 기반 드럼 커버 영상 제작                          ║
echo  ║                                                      ║
echo  ╚══════════════════════════════════════════════════════╝
echo.
echo  This installer will set up everything automatically.
echo  이 설치 프로그램이 모든 것을 자동으로 설정합니다.
echo.
echo  ───────────────────────────────────────────────────────
echo   What will be installed / 설치 내용:
echo.
echo     • DrumSyncer v2.0 application files
echo     • Python 3.10 (if not already installed)
echo     • FFmpeg (audio/video processing)
echo     • yt-dlp (YouTube video downloader)
echo     • PyTorch, Demucs, librosa, Flask
echo.
echo   Install location / 설치 위치:
echo     C:\DrumSyncer
echo.
echo  ───────────────────────────────────────────────────────
echo.

:: ── License Agreement ──
echo  ╔══════════════════════════════════════════════════════╗
echo  ║              LICENSE AGREEMENT / 라이선스 계약         ║
echo  ╚══════════════════════════════════════════════════════╝
echo.
echo  Copyright (c) 2026 Kauzak Foundation, Inc.
echo  501(c)(3) Nonprofit - EIN: 41-3426116
echo.
echo  DrumSyncer is free for personal and non-commercial use.
echo  DrumSyncer는 개인 및 비상업적 사용에 무료입니다.
echo.
echo  You may use, copy, and modify this software freely.
echo  이 소프트웨어를 자유롭게 사용, 복사, 수정할 수 있습니다.
echo.
echo  You may NOT sell or commercially distribute the software.
echo  소프트웨어를 판매하거나 상업적으로 배포할 수 없습니다.
echo.
echo  THE SOFTWARE IS PROVIDED "AS IS" WITHOUT WARRANTY.
echo  소프트웨어는 보증 없이 "있는 그대로" 제공됩니다.
echo.
echo  Full license: https://kauzak.foundation/drumsyncer
echo.
echo  ───────────────────────────────────────────────────────
echo.

set /p ACCEPT="  Do you accept the license agreement? (Y/N): "
if /i not "!ACCEPT!"=="Y" (
    echo.
    echo  Installation cancelled. / 설치가 취소되었습니다.
    echo.
    pause
    exit /b 0
)

echo.
echo  License accepted. Starting installation...
echo  라이선스 동의. 설치를 시작합니다...
echo.

:: ── Set install directory ──
set "INSTALL_DIR=C:\DrumSyncer"
set "BIN_DIR=%INSTALL_DIR%\bin"

echo  ═══════════════════════════════════════════════════════
echo   [Step 1/6] Creating folders...
echo   [1/6단계] 폴더 생성 중...
echo  ═══════════════════════════════════════════════════════
echo.

mkdir "%INSTALL_DIR%" 2>nul
mkdir "%BIN_DIR%" 2>nul
mkdir "%INSTALL_DIR%\data\uploads" 2>nul
mkdir "%INSTALL_DIR%\data\output" 2>nul
mkdir "%INSTALL_DIR%\data\work" 2>nul

echo  [OK] C:\DrumSyncer created.
echo.

:: ── Download DrumSyncer files from GitHub ──
echo  ═══════════════════════════════════════════════════════
echo   [Step 2/6] Downloading DrumSyncer...
echo   [2/6단계] DrumSyncer 다운로드 중...
echo  ═══════════════════════════════════════════════════════
echo.

set "GITHUB_RAW=https://raw.githubusercontent.com/KauzAkAI/kauzak-foundation/main/DrumSyncer"

echo  Downloading drumsyncer_app.py...
powershell -Command "& {[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; try { Invoke-WebRequest -Uri '%GITHUB_RAW%/drumsyncer_app.py' -OutFile '%INSTALL_DIR%\drumsyncer_app.py' -ErrorAction Stop; Write-Host '  [OK] drumsyncer_app.py' } catch { Write-Host '  [FAIL] drumsyncer_app.py - will try backup' }}"

echo  Downloading drum_syncer.py...
powershell -Command "& {[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; try { Invoke-WebRequest -Uri '%GITHUB_RAW%/drum_syncer.py' -OutFile '%INSTALL_DIR%\drum_syncer.py' -ErrorAction Stop; Write-Host '  [OK] drum_syncer.py' } catch { Write-Host '  [FAIL] drum_syncer.py' }}"

:: If GitHub download failed, check if files were bundled alongside this bat
if not exist "%INSTALL_DIR%\drumsyncer_app.py" (
    echo.
    echo  GitHub download failed. Checking local files...
    echo  GitHub 다운로드 실패. 로컬 파일 확인 중...
    if exist "%~dp0drumsyncer_app.py" (
        copy "%~dp0drumsyncer_app.py" "%INSTALL_DIR%\" >nul
        copy "%~dp0drum_syncer.py" "%INSTALL_DIR%\" >nul
        echo  [OK] Copied from local folder.
    ) else (
        echo.
        echo  [ERROR] Cannot find DrumSyncer files.
        echo  [오류] DrumSyncer 파일을 찾을 수 없습니다.
        echo  Please download from https://kauzak.foundation/drumsyncer
        pause
        exit /b 1
    )
)

:: Create the start.bat launcher
(
echo @echo off
echo title DrumSyncer v2.0
echo color 0f
echo set "PATH=%%~dp0bin;%%PATH%%"
echo echo.
echo echo  Starting DrumSyncer v2.0...
echo echo  DrumSyncer v2.0 시작 중...
echo echo.
echo cd /d "%%~dp0"
echo python drumsyncer_app.py
echo pause
) > "%INSTALL_DIR%\start.bat"

echo  [OK] DrumSyncer files ready.
echo.

:: ── Install Python ──
echo  ═══════════════════════════════════════════════════════
echo   [Step 3/6] Checking Python...
echo   [3/6단계] Python 확인 중...
echo  ═══════════════════════════════════════════════════════
echo.

set "PYTHON="

:: Check common Python locations
where python >nul 2>&1
if %errorlevel% equ 0 (
    for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYVER=%%i
    echo  [OK] Python !PYVER! found.
    set "PYTHON=python"
    goto :have_python
)

where python3 >nul 2>&1
if %errorlevel% equ 0 (
    for /f "tokens=2" %%i in ('python3 --version 2^>^&1') do set PYVER=%%i
    echo  [OK] Python !PYVER! found.
    set "PYTHON=python3"
    goto :have_python
)

:: Python not found — install it
echo  Python not found. Installing Python 3.10...
echo  Python을 찾을 수 없습니다. Python 3.10을 설치합니다...
echo.
echo  This will take 1-2 minutes...
echo  1-2분 정도 걸립니다...
echo.

set "PY_URL=https://www.python.org/ftp/python/3.10.11/python-3.10.11-amd64.exe"
set "PY_INSTALLER=%TEMP%\python_installer.exe"

powershell -Command "& {[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%PY_URL%' -OutFile '%PY_INSTALLER%'}"

if not exist "%PY_INSTALLER%" (
    echo  [ERROR] Failed to download Python.
    echo  [오류] Python 다운로드에 실패했습니다.
    echo.
    echo  Please install Python 3.10+ manually from https://python.org
    echo  Make sure to check "Add Python to PATH" during install!
    echo.
    pause
    exit /b 1
)

echo  Installing Python silently...
echo  Python을 자동으로 설치 중...
"%PY_INSTALLER%" /quiet InstallAllUsers=0 PrependPath=1 Include_pip=1

:: Wait for install to finish
timeout /t 5 /nobreak >nul

:: Refresh PATH
set "PATH=%LOCALAPPDATA%\Programs\Python\Python310;%LOCALAPPDATA%\Programs\Python\Python310\Scripts;%PATH%"
set "PYTHON=python"

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo  [WARNING] Python may need a restart to be available.
    echo  [경고] Python을 사용하려면 재시작이 필요할 수 있습니다.
    echo.
    echo  After this installer finishes:
    echo    1. Close this window
    echo    2. Restart your computer
    echo    3. Double-click C:\DrumSyncer\start.bat
    echo.
) else (
    echo  [OK] Python installed successfully!
)

:have_python
echo.

:: ── Download FFmpeg ──
echo  ═══════════════════════════════════════════════════════
echo   [Step 4/6] Setting up FFmpeg and yt-dlp...
echo   [4/6단계] FFmpeg 및 yt-dlp 설정 중...
echo  ═══════════════════════════════════════════════════════
echo.

:: Check FFmpeg
ffmpeg -version >nul 2>&1
if %errorlevel% equ 0 (
    echo  [OK] FFmpeg already installed.
    goto :check_ytdlp
)

if exist "%BIN_DIR%\ffmpeg.exe" (
    echo  [OK] FFmpeg found in bin folder.
    goto :check_ytdlp
)

echo  Downloading FFmpeg (this may take a minute)...
echo  FFmpeg 다운로드 중 (1분 정도 걸릴 수 있습니다)...

set "FF_URL=https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
set "FF_ZIP=%TEMP%\ffmpeg_ds.zip"

powershell -Command "& {[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; try { Invoke-WebRequest -Uri '%FF_URL%' -OutFile '%FF_ZIP%' -ErrorAction Stop } catch { Write-Host 'Download failed' }}"

if exist "%FF_ZIP%" (
    echo  Extracting FFmpeg...
    powershell -Command "Expand-Archive -Path '%FF_ZIP%' -DestinationPath '%TEMP%\ffmpeg_ds_extract' -Force"

    for /r "%TEMP%\ffmpeg_ds_extract" %%f in (ffmpeg.exe) do (
        copy "%%f" "%BIN_DIR%\ffmpeg.exe" >nul
        echo  [OK] FFmpeg installed.
        goto :got_ffmpeg
    )
    echo  [WARNING] FFmpeg extraction failed.
) else (
    echo  [WARNING] FFmpeg download failed. You can install it manually later.
    echo  [경고] FFmpeg 다운로드 실패. 나중에 수동으로 설치할 수 있습니다.
)

:got_ffmpeg
:: Also grab ffprobe
for /r "%TEMP%\ffmpeg_ds_extract" %%f in (ffprobe.exe) do (
    copy "%%f" "%BIN_DIR%\ffprobe.exe" >nul 2>nul
)
rd /s /q "%TEMP%\ffmpeg_ds_extract" 2>nul

:check_ytdlp
:: Check yt-dlp
yt-dlp --version >nul 2>&1
if %errorlevel% equ 0 (
    echo  [OK] yt-dlp already installed.
    goto :install_deps
)

if exist "%BIN_DIR%\yt-dlp.exe" (
    echo  [OK] yt-dlp found in bin folder.
    goto :install_deps
)

echo  Downloading yt-dlp...
echo  yt-dlp 다운로드 중...

set "YT_URL=https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
powershell -Command "& {[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; try { Invoke-WebRequest -Uri '%YT_URL%' -OutFile '%BIN_DIR%\yt-dlp.exe' -ErrorAction Stop; Write-Host '  [OK] yt-dlp installed.' } catch { Write-Host '  [WARNING] yt-dlp download failed.' }}"

:install_deps
echo.

:: ── Install Python Packages ──
echo  ═══════════════════════════════════════════════════════
echo   [Step 5/6] Installing Python packages...
echo   [5/6단계] Python 패키지 설치 중...
echo  ═══════════════════════════════════════════════════════
echo.
echo  This is the longest step (5-10 minutes first time).
echo  이 단계가 가장 오래 걸립니다 (처음에는 5-10분).
echo.

if not defined PYTHON set "PYTHON=python"

:: Add bin to PATH
set "PATH=%BIN_DIR%;%PATH%"

echo  [1/4] Installing PyTorch (CPU)...
echo  [1/4] PyTorch (CPU) 설치 중...
%PYTHON% -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu --quiet 2>nul
if %errorlevel% equ 0 (echo  [OK] PyTorch) else (echo  [!] PyTorch may need manual install)

echo  [2/4] Installing Demucs (AI stem separation)...
echo  [2/4] Demucs (AI 스템 분리) 설치 중...
%PYTHON% -m pip install demucs --quiet 2>nul
if %errorlevel% equ 0 (echo  [OK] Demucs) else (echo  [!] Demucs may need manual install)

echo  [3/4] Installing audio libraries...
echo  [3/4] 오디오 라이브러리 설치 중...
%PYTHON% -m pip install flask librosa soundfile scipy numpy --quiet 2>nul
if %errorlevel% equ 0 (echo  [OK] Audio libraries) else (echo  [!] Some libraries may need manual install)

echo  [4/4] Installing yt-dlp Python module...
echo  [4/4] yt-dlp Python 모듈 설치 중...
%PYTHON% -m pip install yt-dlp --quiet 2>nul
if %errorlevel% equ 0 (echo  [OK] yt-dlp module) else (echo  [!] yt-dlp module may need manual install)

echo.

:: ── Create Desktop Shortcut ──
echo  ═══════════════════════════════════════════════════════
echo   [Step 6/6] Creating shortcuts...
echo   [6/6단계] 바로 가기 생성 중...
echo  ═══════════════════════════════════════════════════════
echo.

:: Create desktop shortcut using PowerShell
powershell -Command "& {$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\DrumSyncer.lnk'); $s.TargetPath = '%INSTALL_DIR%\start.bat'; $s.WorkingDirectory = '%INSTALL_DIR%'; $s.Description = 'DrumSyncer v2.0 - Kauzak Foundation'; $s.Save(); Write-Host '  [OK] Desktop shortcut created.'}"

:: Create Start Menu shortcut
set "STARTMENU=%APPDATA%\Microsoft\Windows\Start Menu\Programs\DrumSyncer"
mkdir "%STARTMENU%" 2>nul
powershell -Command "& {$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%STARTMENU%\DrumSyncer.lnk'); $s.TargetPath = '%INSTALL_DIR%\start.bat'; $s.WorkingDirectory = '%INSTALL_DIR%'; $s.Description = 'DrumSyncer v2.0 - Kauzak Foundation'; $s.Save(); Write-Host '  [OK] Start Menu shortcut created.'}"

echo.

:: ── Verification ──
echo  ═══════════════════════════════════════════════════════
echo   Verifying installation...
echo   설치 확인 중...
echo  ═══════════════════════════════════════════════════════
echo.

set PASS=0
set FAIL=0

if exist "%INSTALL_DIR%\drumsyncer_app.py" (echo  [OK] DrumSyncer app & set /a PASS+=1) else (echo  [FAIL] DrumSyncer app & set /a FAIL+=1)

%PYTHON% -c "import flask" >nul 2>&1
if %errorlevel% equ 0 (echo  [OK] Flask & set /a PASS+=1) else (echo  [FAIL] Flask & set /a FAIL+=1)

%PYTHON% -c "import demucs" >nul 2>&1
if %errorlevel% equ 0 (echo  [OK] Demucs & set /a PASS+=1) else (echo  [FAIL] Demucs & set /a FAIL+=1)

%PYTHON% -c "import librosa" >nul 2>&1
if %errorlevel% equ 0 (echo  [OK] librosa & set /a PASS+=1) else (echo  [FAIL] librosa & set /a FAIL+=1)

%PYTHON% -c "import torch" >nul 2>&1
if %errorlevel% equ 0 (echo  [OK] PyTorch & set /a PASS+=1) else (echo  [FAIL] PyTorch & set /a FAIL+=1)

%PYTHON% -c "import soundfile" >nul 2>&1
if %errorlevel% equ 0 (echo  [OK] SoundFile & set /a PASS+=1) else (echo  [FAIL] SoundFile & set /a FAIL+=1)

echo.

if !FAIL! gtr 0 (
    echo  ───────────────────────────────────────────────────────
    echo  !PASS! passed, !FAIL! failed.
    echo  Some packages may need manual installation.
    echo  Try restarting your computer and running this again.
    echo  ───────────────────────────────────────────────────────
) else (
    echo  ╔══════════════════════════════════════════════════════╗
    echo  ║                                                      ║
    echo  ║   INSTALLATION COMPLETE!                             ║
    echo  ║   설치 완료!                                         ║
    echo  ║                                                      ║
    echo  ║   !PASS!/6 components verified.                          ║
    echo  ║                                                      ║
    echo  ╚══════════════════════════════════════════════════════╝
)

echo.
echo  ───────────────────────────────────────────────────────
echo.
echo   To launch DrumSyncer / DrumSyncer를 실행하려면:
echo.
echo     • Double-click "DrumSyncer" on your Desktop
echo       바탕 화면의 "DrumSyncer"를 더블클릭하세요
echo.
echo     • Or open: C:\DrumSyncer\start.bat
echo.
echo     • Your browser will open to http://localhost:5151
echo       브라우저가 http://localhost:5151 에서 열립니다
echo.
echo  ───────────────────────────────────────────────────────
echo.

set /p LAUNCH="  Launch DrumSyncer now? / 지금 실행할까요? (Y/N): "
if /i "!LAUNCH!"=="Y" (
    echo.
    echo  Starting DrumSyncer...
    echo  DrumSyncer를 시작합니다...
    cd /d "%INSTALL_DIR%"
    start "" "%INSTALL_DIR%\start.bat"
)

echo.
echo  Thank you for installing DrumSyncer!
echo  DrumSyncer를 설치해 주셔서 감사합니다!
echo.
echo  Kauzak Foundation — kauzak.foundation
echo  카우작 재단 — kauzak.foundation
echo.
pause
