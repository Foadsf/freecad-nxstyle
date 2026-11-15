# SPDX-License-Identifier: LGPL-2.1-or-later
<#
.SYNOPSIS
Build NX-Style-<version>-windows-<arch>.exe: one executable file carrying FreeCAD's own portable release
(unmodified) and NX-Style.

.DESCRIPTION
Run from a Visual Studio developer prompt for the launcher's architecture (vcvarsall x64, or x64_arm64 to build
the arm64 launcher on an x64 machine). The launcher (launcher.c, sfx.c) gets the folder FreeCAD\ + nxstyle\
appended as an LZMS-compressed payload (sfx_pack.py), which it unpacks once, at its first start, into
%LOCALAPPDATA%\FreeCAD-NXStyle\runtime\<key>.

FreeCAD publishes no Windows arm64 build of the pinned release, so the arm64 executable carries the x86_64
FreeCAD, which Windows 11 on Arm runs through its x64 emulation; only the launcher is native arm64.

-Folder also leaves the unpacked folder layout (the launcher beside FreeCAD\ and nxstyle\) in the work folder,
for debugging.

.EXAMPLE
pwsh packaging/windows/build.ps1 -Arch x86_64 -Out dist
#>
param(
    [Parameter(Mandatory)][ValidateSet("x86_64", "arm64")][string]$Arch,
    [Parameter(Mandatory)][string]$Out
)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path "$PSScriptRoot/../..").Path
$Work = if ($env:WORK) { $env:WORK } else { Join-Path $Root "build/release-windows-$Arch" }
$Version = (python "$Root/packaging/bundle.py" version).Trim()
$Name = "NX-Style-$Version-windows-$Arch"
New-Item -ItemType Directory -Force $Out, $Work | Out-Null
$Out = (Resolve-Path $Out).Path

function Invoke-Native([string]$What, [scriptblock]$Block) {
    & $Block
    if ($LASTEXITCODE -ne 0) { throw "$What failed with exit code $LASTEXITCODE" }
}

$SevenZip = (Get-Command 7z -ErrorAction SilentlyContinue).Source
if (-not $SevenZip -and (Test-Path "$env:ProgramFiles\7-Zip\7z.exe")) { $SevenZip = "$env:ProgramFiles\7-Zip\7z.exe" }
if (-not $SevenZip) { throw "7-Zip is needed to unpack FreeCAD's .7z" }

Invoke-Native "download" { python "$Root/packaging/bundle.py" fetch "windows-$Arch" (Join-Path $Work "dl") }
$Archive = Get-ChildItem (Join-Path $Work "dl") -Filter "FreeCAD_*-Windows-*.7z" | Select-Object -First 1

# the payload: FreeCAD\ (unmodified) and nxstyle\
$Payload = Join-Path $Work "payload"
if (Test-Path $Payload) { Remove-Item -Recurse -Force $Payload }
$Unpack = Join-Path $Work "unpack"
if (Test-Path $Unpack) { Remove-Item -Recurse -Force $Unpack }
Invoke-Native "7z x" { & $SevenZip x -y -bso0 -bsp0 "-o$Unpack" $Archive.FullName }
$Top = Get-ChildItem $Unpack -Directory | Select-Object -First 1      # FreeCAD_<ver>-Windows-x86_64-py311
if (-not (Test-Path (Join-Path $Top.FullName "bin/freecad.exe"))) { throw "no bin/freecad.exe in $($Archive.Name)" }
New-Item -ItemType Directory -Force $Payload | Out-Null
Move-Item $Top.FullName (Join-Path $Payload "FreeCAD")
Invoke-Native "stage" { python "$Root/packaging/bundle.py" stage (Join-Path $Payload "nxstyle") }

# zstd's sources for the launcher's decoder, checked against the SHA-256 zstd's release publishes
$ZstdVersion = "1.5.7"
$ZstdSha = "eb33e51f49a15e023950cd7825ca74a4a2b43db8354825ac24fc1b7ee09e6fa3"
$ZstdTar = Join-Path $Work "zstd-$ZstdVersion.tar.gz"
if (-not (Test-Path $ZstdTar) -or (Get-FileHash $ZstdTar -Algorithm SHA256).Hash.ToLower() -ne $ZstdSha) {
    Invoke-WebRequest "https://github.com/facebook/zstd/releases/download/v$ZstdVersion/zstd-$ZstdVersion.tar.gz" -OutFile $ZstdTar
}
$got = (Get-FileHash $ZstdTar -Algorithm SHA256).Hash.ToLower()
if ($got -ne $ZstdSha) { throw "zstd-$ZstdVersion.tar.gz: SHA-256 $got is not the pinned $ZstdSha" }
Invoke-Native "zstd sources" { tar -xzf $ZstdTar -C $Work "zstd-$ZstdVersion/lib" "zstd-$ZstdVersion/LICENSE" }
$env:ZSTD_SRC = Join-Path $Work "zstd-$ZstdVersion\lib"
# the launcher carries zstd's decoder: its BSD licence travels in the payload
New-Item -ItemType Directory -Force (Join-Path $Payload "licenses") | Out-Null
Copy-Item (Join-Path $Work "zstd-$ZstdVersion\LICENSE") (Join-Path $Payload "licenses\zstd-LICENSE.txt")
Invoke-Native "zstandard" { python -m pip install --disable-pip-version-check --quiet "zstandard==0.24.0" }

# the launcher, then the launcher with the payload appended
Invoke-Native "launcher build" { cmd /c "`"$PSScriptRoot\build_launcher.cmd`" $Version `"$Work\launcher`"" }
$Exe = Join-Path $Out "$Name.exe"
Invoke-Native "pack" { python "$PSScriptRoot/sfx_pack.py" (Join-Path $Work "launcher/NX-Style.exe") $Payload $Exe --key $Version }
Invoke-Native "payload check" { python "$PSScriptRoot/sfx_pack.py" $Exe --verify }
Get-Item $Exe | Format-Table Name, Length
