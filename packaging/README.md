# Release bundles

Each release carries one self-contained artifact per platform and architecture: an official FreeCAD release, unmodified, with NX-Style, its vendored add-ons and the launcher as the entry point. Nothing is installed and nothing is downloaded at start; NX-Style keeps its own profile and never touches the normal FreeCAD settings.

| Artifact | Entry point | FreeCAD inside |
|---|---|---|
| `NX-Style-<ver>-windows-x86_64.exe` | the file itself, one executable | FreeCAD's portable `.7z`, carried as the executable's payload |
| `NX-Style-<ver>-windows-arm64.exe` | the file itself, native arm64 | the x86_64 portable `.7z`, run by Windows 11 on Arm's x64 emulation (FreeCAD publishes no Windows arm64 build of the pinned release) |
| `NX-Style-<ver>-linux-x86_64.AppImage` | the AppImage | FreeCAD's x86_64 AppImage, unpacked and repacked |
| `NX-Style-<ver>-linux-aarch64.AppImage` | the AppImage | FreeCAD's aarch64 AppImage |
| `NX-Style-<ver>-macos-arm64.dmg` | `NX-Style.app` | FreeCAD's arm64 `FreeCAD.app`, inside `NX-Style.app/Contents/Resources` |
| `NX-Style-<ver>-macos-x86_64.dmg` | `NX-Style.app` | FreeCAD's x86_64 `FreeCAD.app` |
| `SHA256SUMS.txt` | | checksums of all of the above |

The FreeCAD version and the SHA-256 of each upstream file are pinned in [`freecad.json`](freecad.json); `bundle.py fetch` refuses a download that does not match.

## Entry points

Every entry point runs `launch_nx.py` with FreeCAD's own Python and `--freecad` set to the bundled FreeCAD, so every launcher option works (`--smoke-test`, `--headless-check`, `--profile`, files to open, ...).

- Windows: one `.exe`: [`windows/launcher.c`](windows/launcher.c), a small GUI program with NX-Style's icon and version resource, statically linked, with FreeCAD and NX-Style appended as a zstd-compressed payload ([`windows/sfx_pack.py`](windows/sfx_pack.py) writes it, [`windows/sfx.c`](windows/sfx.c) reads it with zstd's decoder, built in from zstd 1.5.7's sources, BSD licence, its notice unpacked as `licenses\zstd-LICENSE.txt`). The first start unpacks the payload once into `%LOCALAPPDATA%\FreeCAD-NXStyle\runtime\<version>-<hash>` (`NXSTYLE_RUNTIME_DIR` puts it elsewhere, such as beside the .exe on a USB stick), with a progress window; every later start goes straight to FreeCAD. Started from Explorer it shows a failure in a message box (log in `%TEMP%\NX-Style-launch.log`). From a terminal, pipe its output so the shell waits and gets the exit code: `& .\NX-Style-<ver>-windows-x86_64.exe --dry-run | Out-Host` in PowerShell, `start /wait` in cmd.
- Linux: [`linux/AppRun`](linux/AppRun) in front of FreeCAD's own AppRun (renamed `AppRun.freecad`). `NX-Style.AppImage freecadcmd ...` still reaches FreeCAD's tools.
- macOS: [`macos/NX-Style`](macos/NX-Style), the app's executable.

## OpenGL without a GPU vendor

FreeCAD needs OpenGL 2 or newer. No bundle carries a GPU vendor's driver:

- Windows: the launcher asks the system's OpenGL first. When it is below 2.0 or Windows' "GDI Generic" (a VM, a remote desktop, Windows on Arm without the OpenGL compatibility pack), FreeCAD starts on the Mesa software renderer it ships (`bin\opengl32sw.dll`, copied to `bin\opengl32.dll`, marked by `opengl32.dll.nxstyle` so only that copy is ever removed).
- Linux: FreeCAD's AppImage brings libglvnd, which hands OpenGL to the system's driver of whatever vendor. `AppRun` probes it with [`linux/glprobe.py`](linux/glprobe.py); when it gives no OpenGL 2+ context, FreeCAD runs on Mesa's llvmpipe (`LIBGL_ALWAYS_SOFTWARE=1`, Mesa's GLX vendor). Mesa itself comes from the system, as on every desktop Linux.
- macOS: Apple's OpenGL, with its own software fallback.

`NXSTYLE_SOFTWARE_GL=1` forces software rendering, `=0` forbids it.

## Building

[`.github/workflows/release.yml`](../.github/workflows/release.yml) builds and checks every bundle; a tag `v<version>` (the version in `NXStyle/nxstyle/__init__.py`) also makes a draft release with `release-notes/v<version>.md` as its text. Locally, on the target platform:

```
pwsh packaging/windows/build.ps1 -Arch x86_64 -Out dist     # from a VS developer prompt
packaging/linux/build.sh x86_64 dist
packaging/macos/build.sh arm64 dist
```

The icons in [`icons/`](icons/) are rendered from `docs/ui/img/logo.svg` by `python tools/make_icons.py`.

## Known limits

- The macOS apps are signed ad hoc, not notarized (that needs an Apple Developer ID). The first start of a downloaded copy is refused until it is allowed in System Settings > Privacy & Security > Open Anyway, or `xattr -dr com.apple.quarantine /Applications/NX-Style.app` is run.
- The Windows `.exe` is not code-signed, so SmartScreen may warn on first start ("More info" > "Run anyway").
- On Windows arm64, FreeCAD runs emulated: it works, but slower than a native build would.
- The Windows executable's first start unpacks about 2.2 GB (35,000 files); antivirus scanning makes this the slow part. Each version unpacks into its own folder under `%LOCALAPPDATA%\FreeCAD-NXStyle\runtime`; delete old ones by hand.
- A macOS `.dmg` is Apple's disk image, not an executable: inside it, `NX-Style.app` is the one item a user drags to Applications and double-clicks, as with every Mac application.
- The DFM add-on needs OCP, which no FreeCAD release ships; `--install-dfm-deps` downloads it on Windows.
