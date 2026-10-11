# Fact check: two AI answers on making FreeCAD look like Siemens NX

Checked on 2026-10-11 against primary sources and the installed FreeCAD 1.0.2. The two answers are the Grok export (*FreeCAD UI UX to match Siemens NX.md*) and the Gemini export (*Making FreeCAD Look Like NX.md*). "Measured" means observed on this machine; the NX textbook facts come from the five books in the project's NotebookLM notebook.

## Verdicts

| Claim | Source | Verdict | Evidence |
|---|---|---|---|
| A Siemens NX navigation style exists in FreeCAD | both | **True, but only from 1.1** | PR [FreeCAD#21813](https://github.com/FreeCAD/FreeCAD/pull/21813), merged 9 Jun 2025, ships in 1.1.0 (released 2026-03-25; current 1.1.4). Class `Gui::SiemensNXNavigationStyle`. **Not in 1.0.2**: the installed 1.0.2 lists ten styles and none is NX (measured). |
| NX style mapping: MB2 rotate, Shift+MB2 / MB2+MB3 pan, wheel / MB1+MB2 zoom | Gemini | **Mostly true** | Matches FreeCAD's implementation and NX tutorials. Ctrl+MB2 zoom is in NX, but FreeCAD's NX style has none. |
| "Single-click MMB sets the rotation centre" | Gemini | **False for NX** | In NX you press and *hold* MB2 on the model. A quick MB2 click is OK in a dialog. FreeCAD's NX style does use a quick click for its rotation centre (`lookAtPoint`), which differs from NX. |
| FreeCAD 1.0 ships Behave-dark, Dark/Light-modern, ProDark themes | Grok | **False** | 1.0.2 ships only `FreeCAD Dark.qss` and `FreeCAD Light.qss`, plus preference packs Classic, Dark, Light and "Dark behave". The "Dark behave" pack points at a stylesheet that no longer exists (measured + source). |
| A Theme Editor exists | Grok | **Partly** | Not in 1.0.x. 1.1 has `DlgThemeEditor`. |
| Stylesheet folder `%APPDATA%\FreeCAD\Gui\Stylesheets` | Gemini | **True for 1.0** | 1.1 moves user data to versioned folders (`%APPDATA%\FreeCAD\v1-1\…`). |
| FreeCAD-Ribbon (APEbbers) is the most complete ribbon add-on | Grok | **True** | Actively maintained, GPL-3.0. Alt+P opens preferences and Alt+L the layout dialog, as stated. |
| OpenTheme add-on | Grok | **True** | obelisk79/OpenTheme, LGPL-2.1, maintained. |
| ProDark theme | Grok | **Partly** | The cited repo is stale (2022). The Addon Manager uses `turn211/ProDarkThemePreferencePack`. |
| PieMenu can be set to RMB-hold | Gemini | **True** | The maintained fork Grubuntu/PieMenu has a right-click hold trigger. The default trigger is Tab. |
| "View → Panels: uncheck Combo View, check Tree view and Property view" | Gemini | **Outdated** | In 1.0 the Combo View is split into separate **Model** and **Tasks** panels (measured dock names). |
| NX preselection orange `#FFA500`, selection magenta `#E6007E` or cyan | Gemini | **False** | Siemens documents **red preselection and orange selection**; the NX textbooks agree on orange selection. No RGB values are published. |
| NX background hex values (`#D9E2EC`, etc.) | Gemini | **Unverified** | NX offers five presets (white, light, light-grey gradient, dark-grey gradient, dark). Their RGB values are not published. |
| NX is built on "Block UI Styler" | Gemini | **False** | Block UI Styler is an NX Open tool for authoring custom dialogs (`.dlx`). NX's own GUI toolkit is not documented. |
| Theme-follows-system PR #32628 | Grok | **True, but open** | [FreeCAD#32628](https://github.com/FreeCAD/FreeCAD/pull/32628) is open, needs Qt ≥ 6.5, and is not in any release. |
| "Cannot make it identical" | both | **True** | Icons, dialogs and command semantics stay FreeCAD's. Siemens icons are proprietary and must not be copied. Layout, terminology, colours, mouse and keyboard behaviour can be matched; that is what this project does. |

## NX facts used by this project

The NX textbook facts come from the notebook's five sources (Shih, *Parametric Modeling with Siemens NX*; Tickoo, *NX 12.0 for Designers*; Wünsch et al., *NX für Einsteiger* / *für Fortgeschrittene*; KIT IMI course). Treat them as leads; they were checked against Siemens/tutorial sources where possible.

- **Ribbon (Modeling):** File, Home, Assemblies, Curve, Surface, Analysis, View, Render, Tools, Application. Home groups: Direct Sketch, Feature, Synchronous Modeling, Pattern, Edit Feature.
- **Above the graphics window:** the Top Border Bar with the Menu button, Type Filter ("No Selection Filter", Curve, Datums, Edge, Face, Feature, Point, Sketch, Solid Body, …), selection scope and snap points.
- **Left side:** the Resource Bar (Part / Assembly / Constraint Navigator, Reuse Library, History, Roles).
- **Bottom:** cue line and status line. **Top right:** Command Finder. **Lower left of the graphics window:** the view triad.
- **Mouse:** MB2 drag rotates. Press and hold MB2 to set the rotation point. Shift+MB2 or MB2+MB3 pans; Ctrl+MB2 or MB1+MB2 zooms. MB2 click = OK. Hold MB3 for the radial menu.
- **Keys:** Ctrl+F Fit, Home Trimetric, End Isometric, F8 Snap View, Ctrl+B Hide, Ctrl+Shift+B Invert, Ctrl+Shift+U Show All, Ctrl+W Show and Hide, Ctrl+J Object Display, Ctrl+T Move Object, X Extrude, Ctrl+E Expressions, Ctrl+M Modeling, Ctrl+Shift+D Drafting, F4 Repeat, Ctrl+Q Finish Sketch, Z Profile, D Rapid Dimension. Ctrl+Alt+F/T/R/L and F5/F6 were confirmed only by the textbooks.
