@echo off
rem SPDX-License-Identifier: LGPL-2.1-or-later
rem Build NX-Style.exe with MSVC from a developer prompt (vcvarsall x64 or arm64):
rem     set ZSTD_SRC=<zstd-1.5.7\lib>
rem     build_launcher.cmd <version such as 0.1.0> <output folder>
rem The C runtime is linked statically, so the .exe needs no Visual C++ redistributable.
setlocal
set VER=%~1
set OUT=%~2
if "%VER%"=="" set VER=0.0.0
if "%OUT%"=="" set OUT=%~dp0build
for /f "tokens=1-3 delims=." %%a in ("%VER%") do set NUM=%%a,%%b,%%c,0
if not exist "%OUT%" mkdir "%OUT%"
pushd "%~dp0"
rc /nologo /DNX_VERSION_STR=\"%VER%\" /DNX_VERSION_NUM=%NUM% /fo "%OUT%\launcher.res" launcher.rc || goto :fail
rem zstd's decoder, from its own sources (ZSTD_SRC: the lib folder of a zstd release), at zstd's warning level
if "%ZSTD_SRC%"=="" goto :nozstd
if not exist "%OUT%\zstd" mkdir "%OUT%\zstd"
cl /nologo /c /O2 /W3 /MT /DZSTD_DISABLE_ASM /DZSTD_MULTITHREAD=0 /I"%ZSTD_SRC%" "%ZSTD_SRC%\common\*.c" "%ZSTD_SRC%\decompress\*.c" /Fo"%OUT%\zstd\\" || goto :fail
cl /nologo /O2 /W4 /WX /MT /DUNICODE /D_UNICODE /I"%ZSTD_SRC%" launcher.c sfx.c "%OUT%\zstd\*.obj" "%OUT%\launcher.res" /Fo"%OUT%\\" /Fe"%OUT%\NX-Style.exe" /link /SUBSYSTEM:WINDOWS user32.lib gdi32.lib shell32.lib comctl32.lib || goto :fail
popd
echo built %OUT%\NX-Style.exe
exit /b 0
:nozstd
echo set ZSTD_SRC to the lib folder of zstd's sources (build.ps1 fetches them)
:fail
popd
exit /b 1
