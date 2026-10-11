# FreeCAD NX-Style

Run your normal, unmodified FreeCAD with a user interface laid out and behaving like Siemens NX: ribbon, Top Border Bar, Resource Bar, NX mouse buttons, NX shortcuts, NX names. There is no fork, no patch, and your usual FreeCAD settings are never touched.

```bash
python launch_nx.py
```

## How it stays out of your normal FreeCAD

FreeCAD reads its user folders from `FREECAD_USER_HOME`, `FREECAD_USER_DATA` and `FREECAD_USER_TEMP` (the folders must already exist; FreeCAD ignores the variables otherwise). The launcher points them at a private profile: `%LOCALAPPDATA%\FreeCAD-NXStyle\profile-<version>` on Windows, `~/.local/share/freecad-nxstyle/…` on Linux, `~/Library/Application Support/FreeCAD-NXStyle/…` on macOS. It loads the `NXStyle` module from this folder with FreeCAD's `-M` switch. Nothing is installed into FreeCAD or into your normal `%APPDATA%\FreeCAD`. The launcher refuses any profile path that overlaps that folder. Your normal add-ons do not load in the NX profile, by design.

Delete the profile folder (or run `--reset-profile`) and it is gone.

## What you get

| NX | Here |
|---|---|
| Ribbon: File, Home, Assemblies, Curve, Surface, Analysis, View, Render, Tools, Application | Same tabs and groups, with NX command names (Extrude, Edge Blend, Pattern Feature, WAVE Linker, …) driving FreeCAD's real commands. Tooltips also show the FreeCAD name. |
| Quick Access Toolbar, Command Finder | Left and right of the tab row. The finder searches NX and FreeCAD names and shows where each command lives. |
| Top Border Bar | Menu button (all FreeCAD menus), Type Filter that really restricts picking, selection tools |
| Resource Bar | Part Navigator, History (recent parts), Information, Journal (Python console), Selection |
| Applications | Modeling (PartDesign), Drafting (TechDraw), Assemblies, Shape Studio, Pre/Post (FEM), Manufacturing (CAM), … Applications without a hand-made ribbon get one generated from their workbench toolbars. |
| Sketch task environment | Contextual **Sketch** tab with Finish Sketch, Profile, Rapid Dimension, constraints |
| Mouse | MB2 rotate; hold MB2 to rotate about the point under the cursor; Shift+MB2 / MB2+MB3 pan; Ctrl+MB2 / MB1+MB2 zoom; wheel zoom; **MB2 click = OK**; **hold MB3 = radial menu** (view menu, or object menu over a part) |
| Keys | All 65 bindings from [NXtips](https://github.com/Foadsf/NXtips): file, edit, view (Home, End, Ctrl+Alt+F/T/R/L, F5–F8, W, Ctrl+H), selection (Ctrl+B, Ctrl+Shift+I/K/U/B, Ctrl+J, Ctrl+I), sketch (Z, R, L, A, O, P, S, T, E, F, D, C, Ctrl+Q), applications (Ctrl+M, Ctrl+Shift+D/M/Y, Ctrl+Alt+S), Ctrl+1/2/E/L, F4 Touch Mode. Each one is pressed by the self-test; see [docs/SHORTCUTS.md](docs/SHORTCUTS.md) |
| Graphics window | Light-grey gradient background (five NX presets on View › Background), red preselection, orange selection, grey bodies with dark edges, view triad bottom-left (drawn by NXStyle; FreeCAD 1.0 can only put its own bottom-right), no view cube |
| Cue line | NX-style prompt at the bottom left |

**Look:** one NX-light theme layered on FreeCAD's own *FreeCAD Light* stylesheet, with a single accent colour and its tints, original line icons on the Resource Bar, the left panels as one tab strip, and document tabs above the graphics window. The colour tokens are listed at the top of `NXStyle/nxstyle/resources/nx_theme.qss`. Set `"theme": "none"` to keep FreeCAD's look.

**Tools › FreeCAD Menus and Toolbars** brings back FreeCAD's own menu bar and toolbars at any time.

## What it is not

It is not identical to NX, and cannot be. Icons, feature dialogs and modelling semantics are FreeCAD's: Pocket is not an Extrude with a Boolean option, and there is no synchronous modelling beyond Defeaturing. No Siemens assets are used. See [docs/FACT-CHECK.md](docs/FACT-CHECK.md) for what is and is not achievable and why.

## Options

```bash
python launch_nx.py --list
```

```bash
python launch_nx.py --freecad "C:\Program Files\FreeCAD 1.1\bin\freecad.exe" part.FCStd
```

```bash
python launch_nx.py --reset-profile
```

Settings live in `nxstyle.json` inside the profile's `config` folder, which is created on first start. You can change the navigation (`"nx"` = this project's mouse handling on any FreeCAD version, `"native"` = FreeCAD 1.1's own Siemens NX style), labels (`"nx"` or `"freecad"`), colours, background, hold delays, and whether the feature dialog floats over the graphics window.

Ribbons are plain JSON in `NXStyle/nxstyle/resources/ribbons/`. A command entry can list several candidate names (the first one that exists wins), so one file serves FreeCAD 1.0 and 1.1. Entries marked `"optional": true` exist only in newer FreeCAD versions.

## Self-test

```bash
python launch_nx.py --smoke-test out
```

This starts FreeCAD in a throwaway profile, on a hidden Windows desktop so nothing appears on your screen (`--visible` to watch). The test drives the real UI with synthetic mouse and key events and checks 48 behaviours. It writes `out/smoke.json` plus screenshots, and exits non-zero on any failure.

```bash
python -m unittest discover -s tests
```

Launcher unit tests; FreeCAD is not needed.

## Requirements

FreeCAD 1.0 or newer. Tested on Windows 11 with FreeCAD 1.0.2 (Qt 5.15) and 1.1.4 (Qt 6). Any Python 3.8+ runs the launcher, including FreeCAD's own.

## Licence and trademarks

LGPL-2.1-or-later, matching FreeCAD; the full licence text still needs adding before publication. Siemens and NX are trademarks of Siemens; this project is not affiliated with or endorsed by Siemens and uses no Siemens software, icons or documentation text.
