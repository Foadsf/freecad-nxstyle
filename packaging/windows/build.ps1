# SPDX-License-Identifier: LGPL-2.1-or-later
<#
.SYNOPSIS
Build NX-Style-<version>-windows-<arch>.zip: a portable folder with NX-Style.exe, FreeCAD's own portable release
(unmodified) and NX-Style.

.DESCRIPTION
Run from a Visual Studio developer prompt for the launcher's architecture (vcvarsall x64, or x64_arm64 to build
the arm64 launcher on an x64 machine). FreeCAD publishes no Windows arm64 build of the pinned release, so the
arm64 bundle carries the x86_64 FreeCAD, which Windows 11 on Arm runs through its x64 emulation; only
NX-Style.exe is native arm64.

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

$Bundle = Join-Path $Work $Name
if (Test-Path $Bundle) { Remove-Item -Recurse -Force $Bundle }
$Unpack = Join-Path $Work "unpack"
if (Test-Path $Unpack) { Remove-Item -Recurse -Force $Unpack }
Invoke-Native "7z x" { & $SevenZip x -y -bso0 -bsp0 "-o$Unpack" $Archive.FullName }
$Top = Get-ChildItem $Unpack -Directory | Select-Object -First 1      # FreeCAD_<ver>-Windows-x86_64-py311
if (-not (Test-Path (Join-Path $Top.FullName "bin/freecad.exe"))) { throw "no bin/freecad.exe in $($Archive.Name)" }
New-Item -ItemType Directory -Force $Bundle | Out-Null
Move-Item $Top.FullName (Join-Path $Bundle "FreeCAD")

Invoke-Native "launcher build" { cmd /c "`"$PSScriptRoot\build_launcher.cmd`" $Version `"$Work\launcher`"" }
Copy-Item (Join-Path $Work "launcher/NX-Style.exe") $Bundle
Copy-Item "$PSScriptRoot/nxstyle.cmd" $Bundle
Invoke-Native "stage" { python "$Root/packaging/bundle.py" stage (Join-Path $Bundle "nxstyle") }

$FreeCADVersion = (Get-Content "$Root/packaging/freecad.json" -Raw | ConvertFrom-Json).version
$Emulated = if ($Arch -eq "arm64") { "`r`nFreeCAD $FreeCADVersion has no Windows arm64 build: this bundle carries its x86_64 build, which Windows 11 on Arm runs through its built-in x64 emulation. NX-Style.exe itself is native arm64.`r`n" } else { "" }
@"
FreeCAD NX-Style $Version for Windows ($Arch), with FreeCAD $FreeCADVersion
https://github.com/Foadsf/freecad-nxstyle

Double-click NX-Style.exe. Nothing is installed: keep this folder anywhere you can write to, and delete it to
remove NX-Style. Your normal FreeCAD settings are never touched; NX-Style keeps its own profile in
%LOCALAPPDATA%\FreeCAD-NXStyle.

From a command prompt or PowerShell, nxstyle.cmd takes every option of launch_nx.py:
    nxstyle.cmd --help
    nxstyle.cmd --smoke-test C:\r\x
$Emulated
OpenGL: without a GPU driver that offers OpenGL 2 (a VM, a remote desktop), NX-Style.exe starts FreeCAD on the
Mesa software renderer FreeCAD ships. Set NXSTYLE_SOFTWARE_GL=1 to force it, 0 to forbid it.

FreeCAD folder: the official FreeCAD $FreeCADVersion portable release, unmodified (LGPL-2.1-or-later).
NX-Style is not affiliated with Siemens.
"@ | Set-Content -Encoding utf8 (Join-Path $Bundle "README.txt")

$Zip = Join-Path $Out "$Name.zip"
if (Test-Path $Zip) { Remove-Item -Force $Zip }
Push-Location $Work
try { Invoke-Native "7z a" { & $SevenZip a -tzip -mx=7 -mmt=on -bso0 -bsp0 $Zip $Name } } finally { Pop-Location }
Get-Item $Zip | Format-Table Name, Length
