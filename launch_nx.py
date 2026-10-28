#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Start an unmodified FreeCAD with an NX-style user interface.

The launcher never touches your normal FreeCAD settings. It gives FreeCAD a
private profile (user.cfg, Mod, Macro, temp) through FreeCAD's own
FREECAD_USER_HOME / FREECAD_USER_DATA / FREECAD_USER_TEMP environment
variables and loads the NXStyle module from this folder with ``-M``.

Usage:
    python launch_nx.py [files...]
    python launch_nx.py --list                 # show FreeCAD installs found
    python launch_nx.py --freecad PATH         # pick a specific FreeCAD
    python launch_nx.py --reset-profile        # start from a clean NX profile
    python launch_nx.py --smoke-test OUTDIR    # self-test in a throwaway profile

Only the Python standard library is used, so any Python 3.8+ (including the
one bundled with FreeCAD) can run it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODULE_DIR = HERE / "NXStyle"
APP_ID = "FreeCAD-NXStyle"
VERSION_RE = re.compile(r"FreeCAD\s+(\d+)\.(\d+)(?:\.(\d+))?")


# --------------------------------------------------------------------------
# FreeCAD discovery
# --------------------------------------------------------------------------
class Install:
    def __init__(self, exe: Path, version: tuple[int, int, int] | None):
        self.exe = exe
        self.version = version

    @property
    def version_str(self) -> str:
        return ".".join(map(str, self.version)) if self.version else "unknown"

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"Install({self.exe}, {self.version_str})"


def _exe_names() -> list[str]:
    if os.name == "nt":
        return ["freecad.exe", "FreeCAD.exe"]
    return ["FreeCAD", "freecad"]


def _console_exe(gui_exe: Path) -> Path | None:
    """freecadcmd sits next to the GUI binary; it prints --version reliably."""
    for name in ("freecadcmd.exe", "FreeCADCmd.exe", "freecadcmd", "FreeCADCmd"):
        cand = gui_exe.with_name(name)
        if cand.is_file():
            return cand
    return None


def _version_command(gui_exe: Path) -> list[str] | None:
    """The command that prints the version, or None when only the GUI binary is at hand.

    On Linux the GUI binary answers --version with a message box and waits for
    OK, so it is never asked. An AppImage runs its bundled freecadcmd when that
    is the first argument (AppRun starts usr/bin/<arg1> if it exists).
    """
    if gui_exe.suffix.lower() == ".appimage":
        return [str(gui_exe), "freecadcmd", "--version"]
    console = _console_exe(gui_exe)
    if console:
        return [str(console), "--version"]
    if os.name == "nt":
        return [str(gui_exe), "--version"]
    return None


def probe_version(gui_exe: Path) -> tuple[int, int, int] | None:
    cmd = _version_command(gui_exe)
    m = None
    if cmd:
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=_clean_env())
            m = VERSION_RE.search(out.stdout + out.stderr)
        except (OSError, subprocess.SubprocessError):
            m = None
    if not m:
        # Fall back to a version embedded in the file name ("FreeCAD_1.1.4-Linux-x86_64.AppImage")
        # or the folder name ("FreeCAD 1.0").
        m = (re.search(r"[Ff]ree[Cc][Aa][Dd][ _-]?(\d+)\.(\d+)(?:\.(\d+))?", gui_exe.name)
             or re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", str(gui_exe.parent.parent.name)))
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)


def _clean_env() -> dict:
    env = dict(os.environ)
    for key in ("FREECAD_USER_HOME", "FREECAD_USER_DATA", "FREECAD_USER_TEMP"):
        env.pop(key, None)
    return env


def _windows_registry_dirs() -> list[Path]:
    dirs: list[Path] = []
    try:
        import winreg
    except ImportError:
        return dirs
    roots = [
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    for hive, path in roots:
        try:
            key = winreg.OpenKey(hive, path)
        except OSError:
            continue
        with key:
            for i in range(winreg.QueryInfoKey(key)[0]):
                try:
                    sub = winreg.OpenKey(key, winreg.EnumKey(key, i))
                    with sub:
                        name = winreg.QueryValueEx(sub, "DisplayName")[0]
                        if "freecad" not in str(name).lower():
                            continue
                        loc = winreg.QueryValueEx(sub, "InstallLocation")[0]
                        if loc:
                            dirs.append(Path(loc))
                except OSError:
                    continue
    return dirs


def candidate_executables() -> list[Path]:
    found: list[Path] = []

    def add(p: Path) -> None:
        try:
            p = p.resolve()
        except OSError:
            return
        if p.is_file() and p not in found:
            found.append(p)

    env_exe = os.environ.get("FREECAD_EXE")
    if env_exe:
        add(Path(env_exe))

    for name in _exe_names():
        hit = shutil.which(name)
        if hit:
            add(Path(hit))

    if os.name == "nt":
        roots = [
            os.environ.get("LOCALAPPDATA", "") + r"\Programs",
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
            os.path.expanduser(r"~\scoop\apps"),
            r"C:\ProgramData\chocolatey\lib",
        ]
        bases = [Path(r) for r in roots if r]
        bases += _windows_registry_dirs()
        for base in bases:
            if not base.is_dir():
                continue
            for d in [base, *base.glob("[Ff]ree[Cc][Aa][Dd]*")]:
                for sub in ("bin", "current/bin", "tools/bin", ""):
                    for exe in _exe_names():
                        add(d / sub / exe)
                # chocolatey portable keeps FreeCAD one folder deeper
                for exe in d.glob("tools/*/bin/freecad.exe"):
                    add(exe)
    elif sys.platform == "darwin":
        for app in Path("/Applications").glob("FreeCAD*.app"):
            add(app / "Contents/MacOS/FreeCAD")
        for app in Path.home().joinpath("Applications").glob("FreeCAD*.app"):
            add(app / "Contents/MacOS/FreeCAD")
    else:
        for p in ("/usr/bin/freecad", "/usr/local/bin/freecad", "/usr/bin/FreeCAD",
                  "/snap/bin/freecad"):
            add(Path(p))
        for img in Path.home().glob("*/FreeCAD*.AppImage"):
            add(img)
    return found


def discover() -> list[Install]:
    installs = [Install(exe, probe_version(exe)) for exe in candidate_executables()]
    installs.sort(key=lambda i: i.version or (0, 0, 0), reverse=True)
    return installs


# --------------------------------------------------------------------------
# Private profile
# --------------------------------------------------------------------------
def default_profile_root() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / APP_ID
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support" / APP_ID
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / APP_ID.lower()


def vanilla_dirs() -> list[Path]:
    """Directories a normal FreeCAD uses; the NX profile must stay out of them."""
    dirs = []
    if os.name == "nt":
        dirs.append(Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming")) / "FreeCAD")
    elif sys.platform == "darwin":
        dirs.append(Path.home() / "Library/Application Support/FreeCAD")
        dirs.append(Path.home() / "Library/Preferences/FreeCAD")
    else:
        dirs += [Path.home() / ".FreeCAD", Path.home() / ".config/FreeCAD",
                 Path.home() / ".local/share/FreeCAD"]
    return [d.resolve() for d in dirs]


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent)
        return True
    except ValueError:
        return False


def prepare_profile(profile: Path, reset: bool = False) -> dict[str, Path]:
    profile = profile.resolve()
    for vd in vanilla_dirs():
        if _is_within(profile, vd) or _is_within(vd, profile):
            raise SystemExit(f"Refusing to use {profile}: it overlaps the normal FreeCAD folder {vd}")
    if reset and profile.exists():
        shutil.rmtree(profile)
    paths = {
        "home": profile / "config",   # user.cfg / system.cfg
        "data": profile / "data",     # Mod, Macro, preference packs, ...
        "temp": profile / "temp",
    }
    # FreeCAD ignores these variables unless the directories already exist.
    for p in paths.values():
        p.mkdir(parents=True, exist_ok=True)
    (paths["data"] / "Mod").mkdir(exist_ok=True)
    return paths


def seed_user_cfg(paths: dict[str, Path], version: tuple[int, int, int] | None) -> bool:
    """Give a brand-new NX profile the few settings FreeCAD reads before any
    add-on runs: the light stylesheet, no first-run wizard, and no panels in
    overlays (FreeCAD 1.1 puts the Tasks panel in one). Never touches an
    existing user.cfg. Returns True if it wrote one."""
    cfg = paths["home"] / "user.cfg"
    if cfg.exists():
        return False
    import xml.etree.ElementTree as ET

    root = ET.Element("FCParameters")
    top = ET.SubElement(root, "FCParamGroup", Name="Root")

    def group(parent, *names):
        for n in names:
            found = next((g for g in parent.findall("FCParamGroup") if g.get("Name") == n), None)
            parent = found if found is not None else ET.SubElement(parent, "FCParamGroup", Name=n)
        return parent

    v11 = bool(version and version >= (1, 1, 0))
    main = group(top, "BaseApp", "Preferences", "MainWindow")
    ET.SubElement(main, "FCText", Name="StyleSheet").text = "FreeCAD.qss" if v11 else "FreeCAD Light.qss"
    if v11:
        ET.SubElement(main, "FCText", Name="Theme").text = "FreeCAD Light"
    start = group(top, "BaseApp", "Preferences", "Mod", "Start")
    ET.SubElement(start, "FCBool", Name="FirstStart2024", Value="0")
    general = group(top, "BaseApp", "Preferences", "General")
    ET.SubElement(general, "FCText", Name="AutoloadModule").text = "PartDesignWorkbench"
    for side in ("OverlayLeft", "OverlayRight", "OverlayTop", "OverlayBottom"):
        ET.SubElement(group(top, "BaseApp", "MainWindow", "DockWindows", side), "FCText", Name="Widgets")
    ET.ElementTree(root).write(cfg, encoding="UTF-8", xml_declaration=True)
    return True


def build_env(paths: dict[str, Path], extra: dict | None = None) -> dict:
    env = _clean_env()
    env["FREECAD_USER_HOME"] = str(paths["home"])
    env["FREECAD_USER_DATA"] = str(paths["data"])
    env["FREECAD_USER_TEMP"] = str(paths["temp"])
    env["NXSTYLE_PROFILE"] = str(paths["home"].parent)
    if extra:
        env.update({k: str(v) for k, v in extra.items()})
    return env


def build_command(install: Install, files: list[str], passthrough: list[str],
                  modules: tuple[Path, ...] = ()) -> list[str]:
    extra = [arg for m in modules for arg in ("-M", str(m))]
    return [str(install.exe), "-M", str(MODULE_DIR), *extra, *passthrough, *files]


# --------------------------------------------------------------------------
# Strata: data management next to NXStyle (the role Teamcenter plays next to NX)
# --------------------------------------------------------------------------
STRATA_DIR = HERE / "vendor" / "freecad-strata"     # git submodule of github.com/Foadsf/freecad-strata


def read_settings(profile: Path) -> dict:
    """The profile's nxstyle.json, as NXStyle reads it: config/nxstyle.json, or an older one in the
    profile's root when config/ has none (NXStyle before 2026-10-13 kept it there)."""
    for path in (profile / "config" / "nxstyle.json", profile / "nxstyle.json"):
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return {}
    return {}


def find_strata(profile: Path, disabled: bool = False) -> tuple[Path | None, str]:
    """The Strata folder to load with -M, or None, and why. One copy only: a Strata the user installed
    into the NX profile (Addon Manager) is loaded by FreeCAD itself, so the bundled one stays out."""
    if disabled:
        return None, "off (--no-strata)"
    cfg = read_settings(profile)
    if cfg.get("plm", "strata") != "strata":
        return None, f"off (nxstyle.json: plm = {cfg.get('plm')!r})"
    mods = profile / "data" / "Mod"
    if mods.is_dir():
        for mod in sorted(mods.iterdir()):
            if (mod / "strata" / "__init__.py").is_file():
                return None, f"installed in the NX profile ({mod})"
    if (STRATA_DIR / "InitGui.py").is_file():
        return STRATA_DIR, f"bundled ({STRATA_DIR})"
    return None, "not found: run 'git submodule update --init' in the freecad-nxstyle folder"


# --------------------------------------------------------------------------
# Katydid: node-based algorithmic modelling (the role of NX's Algorithmic Modeling)
# --------------------------------------------------------------------------
KATYDID_DIR = HERE / "vendor" / "Katydid"            # git submodule of github.com/Foadsf/Katydid


def find_katydid(profile: Path, disabled: bool = False) -> tuple[Path | None, str]:
    """The Katydid folder to load with -M, or None, and why; one copy only, as for Strata."""
    if disabled:
        return None, "off (--no-katydid)"
    cfg = read_settings(profile)
    if cfg.get("algorithmic_modeling", "katydid") != "katydid":
        return None, f"off (nxstyle.json: algorithmic_modeling = {cfg.get('algorithmic_modeling')!r})"
    mods = profile / "data" / "Mod"
    if mods.is_dir():
        for mod in sorted(mods.iterdir()):
            if (mod / "katydid" / "__init__.py").is_file():
                return None, f"installed in the NX profile ({mod})"
    if (KATYDID_DIR / "InitGui.py").is_file():
        return KATYDID_DIR, f"bundled ({KATYDID_DIR})"
    return None, "not found: run 'git submodule update --init' in the freecad-nxstyle folder"


# --------------------------------------------------------------------------
# SheetMetal: FreeCAD's sheet metal add-on (shaise/FreeCAD_SheetMetal, LGPL-2.1) behind NX Sheet Metal
# --------------------------------------------------------------------------
SHEETMETAL_DIR = HERE / "vendor" / "FreeCAD_SheetMetal"   # git submodule of github.com/shaise/FreeCAD_SheetMetal


def find_sheetmetal(profile: Path, disabled: bool = False) -> tuple[Path | None, str]:
    """The SheetMetal folder to load with -M, or None, and why; one copy only, as for Strata. A copy the
    Addon Manager installed into the NX profile is loaded by FreeCAD itself."""
    if disabled:
        return None, "off (--no-sheetmetal)"
    cfg = read_settings(profile)
    if cfg.get("sheet_metal", "sheetmetal") != "sheetmetal":
        return None, f"off (nxstyle.json: sheet_metal = {cfg.get('sheet_metal')!r})"
    mods = profile / "data" / "Mod"
    if mods.is_dir():
        for mod in sorted(mods.iterdir()):
            if (mod / "SheetMetalCmd.py").is_file():
                return None, f"installed in the NX profile ({mod})"
    if (SHEETMETAL_DIR / "InitGui.py").is_file():
        return SHEETMETAL_DIR, f"bundled ({SHEETMETAL_DIR})"
    return None, "not found: run 'git submodule update --init' in the freecad-nxstyle folder"


# --------------------------------------------------------------------------
# LCInterlocking: laser-cut panels with tabs and slots (execuc/LCInterlocking, LGPL-2.1) behind Laser Cut;
# bundled as a fork with two Qt 6 fixes, and NXStyle patches an upstream copy the same way (nxstyle/lcinterlocking.py)
# --------------------------------------------------------------------------
LCINTERLOCKING_DIR = HERE / "vendor" / "LCInterlocking"   # git submodule of github.com/Foadsf/LCInterlocking


def find_lcinterlocking(profile: Path, disabled: bool = False) -> tuple[Path | None, str]:
    """The LCInterlocking folder to load with -M, or None, and why; one copy only, as for Strata. A copy
    the Addon Manager installed into the NX profile is loaded by FreeCAD itself."""
    if disabled:
        return None, "off (--no-lcinterlocking)"
    cfg = read_settings(profile)
    if cfg.get("laser_cut", "lcinterlocking") != "lcinterlocking":
        return None, f"off (nxstyle.json: laser_cut = {cfg.get('laser_cut')!r})"
    mods = profile / "data" / "Mod"
    if mods.is_dir():
        for mod in sorted(mods.iterdir()):
            if (mod / "lasercut" / "join.py").is_file():
                return None, f"installed in the NX profile ({mod})"
    if (LCINTERLOCKING_DIR / "InitGui.py").is_file():
        return LCINTERLOCKING_DIR, f"bundled ({LCINTERLOCKING_DIR})"
    return None, "not found: run 'git submodule update --init' in the freecad-nxstyle folder"


# --------------------------------------------------------------------------
# DFM: design-for-manufacturing checks (ryankembrey/FreeCAD-DFM-Workbench, LGPL-2.1-or-later) behind
# Analysis > Molded Part Validation. It imports OCP (cadquery-ocp) on load, which FreeCAD does not ship, so
# --install-dfm-deps puts a pinned copy in a folder of NXStyle's own; the launcher never downloads by itself.
# --------------------------------------------------------------------------
DFM_DIR = HERE / "vendor" / "FreeCAD-DFM-Workbench"   # git submodule of github.com/ryankembrey/FreeCAD-DFM-Workbench
# OCCT 7.8.1, the one FreeCAD 1.1 is built on; OCP loads vtk's DLLs on import; gmsh meshes the part for
# Draft Analysis and Check Wall Thickness. --no-deps: vtk's own requirements (numpy 2, matplotlib) would
# shadow FreeCAD's.
DFM_DEPS = ("cadquery-ocp==7.8.1.1.post1", "vtk==9.3.1", "gmsh==4.15.2")
DFM_VTK_SHADOWS = ("vtkmodules", "vtk.py")     # the vtk wheel's Python side, removed after installing


def freecad_python(install: Install) -> tuple[Path | None, str]:
    """FreeCAD's own python.exe and its tag ('py311'), from the pythonXY.dll beside the binary; (None, '')
    where FreeCAD has no separate interpreter (AppImage, macOS bundle)."""
    bindir = install.exe.parent
    # python3.dll, the stable-ABI forwarder, sits beside python311.dll
    dll = next((d for d in sorted(bindir.glob("python3*.dll")) if re.fullmatch(r"python3\d+", d.stem)), None)
    exe = bindir / "python.exe"
    if dll is None or not exe.is_file():
        return None, ""
    return exe, "py" + dll.stem[len("python"):]


def dfm_deps_dir(install: Install) -> Path | None:
    """Where --install-dfm-deps puts OCP for this FreeCAD's Python, outside any profile so that throwaway
    test profiles share it."""
    _exe, tag = freecad_python(install)
    return default_profile_root() / "pydeps" / tag if tag else None


def has_ocp(folder: Path | None) -> bool:
    return bool(folder) and (folder / "OCP" / "__init__.py").is_file()


def find_dfm(profile: Path, install: Install, disabled: bool = False) -> tuple[tuple[Path, ...], str]:
    """The folders to load with -M for the DFM add-on (its OCP folder first), or (), and why; one copy only,
    as for Strata. Without OCP the add-on fails on load, so it stays out and the reason says how to get it."""
    if disabled:
        return (), "off (--no-dfm)"
    cfg = read_settings(profile)
    if cfg.get("dfm", "dfm") != "dfm":
        return (), f"off (nxstyle.json: dfm = {cfg.get('dfm')!r})"
    deps = dfm_deps_dir(install)
    site = install.exe.parent / "Lib" / "site-packages"
    ocp = (deps,) if has_ocp(deps) else ()
    mods = profile / "data" / "Mod"
    if mods.is_dir():
        for mod in sorted(mods.iterdir()):
            if (mod / "freecad" / "DFM" / "init_gui.py").is_file():   # its OCP is the Addon Manager's job
                return ocp, f"installed in the NX profile ({mod})"
    if not ocp and not has_ocp(site):
        return (), ("off: it needs OCP (cadquery-ocp), which FreeCAD does not ship; "
                    "run 'python launch_nx.py --install-dfm-deps' once")
    if (DFM_DIR / "freecad" / "DFM" / "init_gui.py").is_file():
        return (*ocp, DFM_DIR), f"bundled ({DFM_DIR})" + (f", OCP from {deps}" if ocp else "")
    return (), "not found: run 'git submodule update --init' in the freecad-nxstyle folder"


def install_dfm_deps(install: Install) -> int:
    """pip-install DFM_DEPS with FreeCAD's own Python into dfm_deps_dir; the one step that downloads."""
    exe, _tag = freecad_python(install)
    target = dfm_deps_dir(install)
    if exe is None or target is None:
        print("This FreeCAD has no separate python.exe; install cadquery-ocp into its Python yourself "
              "(the Addon Manager does it when it installs DFM).", file=sys.stderr)
        return 2
    target.mkdir(parents=True, exist_ok=True)
    cmd = [str(exe), "-m", "pip", "install", "--disable-pip-version-check", "--no-deps", "--upgrade",
           "--target", str(target), *DFM_DEPS]
    print(" ".join(cmd))
    code = subprocess.call(cmd)
    if code == 0:
        # FreeCAD ships VTK 9.3.1's Python package itself, and FEM uses it: a second copy on the path shadows
        # it and Pre/Post hangs (measured, smoke run 2026-10-27). OCP needs only the wheel's DLLs, vtk.libs.
        for name in DFM_VTK_SHADOWS:
            p = target / name
            if p.is_dir():
                shutil.rmtree(p)
            elif p.exists():
                p.unlink()
    return code


# --------------------------------------------------------------------------
# Hidden desktop (Windows): run the self-test without windows on the user's screen
# --------------------------------------------------------------------------
# A test run gets a hard memory ceiling. On 2026-10-12 a tutorial replay grew
# FreeCAD past the whole commit limit (RAM + page file, ~59 GB) within a minute,
# twice; Windows then could not start dwm, explorer or even WerFault
# (0xc000012d) and the machine had to be powered off. The 600 s timeout never
# got a chance. Inside a job object the kernel refuses FreeCAD's allocations
# beyond the ceiling and the launcher ends the run, so the rest of the machine
# keeps working.
HARNESS_MEMORY_GB = 4.0
STATUS_NO_MEMORY = 0xC0000017      # exit code of a run ended at the memory ceiling

# The result a harness run must leave (written by NXStyle/nxstyle/harness_result.py, same schema)
HARNESS_SCHEMA = "nxstyle-harness/1"
RESULT_FILES = {"smoke": "smoke.json", "tutorial": "tutorial.json"}
EXIT_INVALID_RESULT = 6            # stale, empty, truncated, unfinished or another run's result
EXIT_CHILD_FAILED = 7              # FreeCAD exited with an error code


def judge_result(path: Path, harness: str, run_id: str, child_code: int | None,
                 require_all: bool = False) -> int:
    """The exit code of a harness run, from its result file and FreeCAD's exit code. Prints the checks or
    steps. Only a result that names this run, says it is complete and lists every planned step as run is
    believed: an old file left in the output folder, '{}', empty lists or a truncated file fail
    (EXIT_INVALID_RESULT), and so does a FreeCAD that exited with an error (EXIT_CHILD_FAILED), even when an
    earlier, passing result is still in the folder."""
    def bad(why: str, code: int = EXIT_INVALID_RESULT) -> int:
        print(f"{harness} run not accepted: {why}", file=sys.stderr)
        return code

    if not path.is_file():
        if child_code:
            return bad(f"FreeCAD exited with code {child_code} and left no result", 2)
        return bad("no result (FreeCAD crashed or NXStyle failed to load)", 2)
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        return bad(f"{path.name} cannot be read ({e}): a truncated or corrupted file")
    if not isinstance(result, dict):
        return bad(f"{path.name} is not a result object")
    if result.get("schema") != HARNESS_SCHEMA or result.get("harness") != harness:
        return bad(f"{path.name} is not a {harness} result of schema {HARNESS_SCHEMA} "
                   f"(schema {result.get('schema')!r}, harness {result.get('harness')!r}): left by an older run?")
    if result.get("run_id") != run_id:
        return bad(f"{path.name} is from another run ({result.get('run_id')!r}), not this one ({run_id}): "
                   "this run left no result of its own")
    if result.get("status") != "complete":
        return bad(f"the run did not finish (status {result.get('status')!r})")
    planned, ran = result.get("planned"), result.get("ran")
    if not isinstance(planned, list) or not planned:
        return bad("the result lists no planned steps")
    if not isinstance(ran, list) or sorted(ran) != sorted(planned):
        missing = sorted(set(planned) - set(ran or []))
        return bad(f"not every planned step ran: {missing[:10]}{' …' if len(missing) > 10 else ''}")
    key = "checks" if harness == "smoke" else "steps"
    rows = result.get(key)
    if not isinstance(rows, list) or not rows:
        return bad(f"the result has no {key}")
    if harness == "smoke":
        counts = {"pass": 0, "fail": 0, "skipped": 0}
        for c in rows:
            status = c.get("status") or ("pass" if c.get("ok") else "fail")
            status = status if status in counts else "fail"
            counts[status] += 1
            label = {"pass": "PASS", "fail": "FAIL", "skipped": "SKIP"}[status]
            print(f"{label}  {c.get('name')}: {c.get('detail', '')}")
        print(f"{len(rows)} checks: {counts['pass']} passed, {counts['fail']} failed, {counts['skipped']} skipped")
        failed = counts["fail"] or (require_all and counts["skipped"])
    else:
        for s in rows:
            print(f"{s['tutorial'].split(':', 1)[0]}{s['n']:>3} {s['outcome']:<8} {s['nx']}  [{s['replay']}]  "
                  f"{s['detail']}")
        dropped = result.get("dropped") or []
        if dropped:
            print(f"{len(dropped)} steps not run after a failure in their tutorial: {dropped}")
        failed = any(s.get("outcome") == "FAILED" for s in rows)
    if child_code:
        return bad(f"FreeCAD exited with code {child_code} after writing its result", EXIT_CHILD_FAILED)
    return 1 if failed else 0
HARNESS_MUTEX = "Local\\FreeCAD-NXStyle-harness"


class HarnessBusy(RuntimeError):
    """Another smoke/tutorial run is active; runs never overlap."""


def run_on_hidden_desktop(cmd: list[str], env: dict, timeout_s: int,
                          max_memory_gb: float = HARNESS_MEMORY_GB, hidden: bool = True,
                          stats: dict | None = None) -> int | None:
    """Start cmd on a separate, never-shown Win32 desktop and wait for it.

    Returns the exit code, None on timeout, or STATUS_NO_MEMORY when the run hit
    max_memory_gb. The windows exist and paint, but on a desktop nobody is
    looking at, so they cannot steal focus or block input. The process tree runs
    in a job object: memory ceiling, killed when the launcher exits for any
    reason, and no crash dialogs. hidden=False runs on the normal desktop with
    the same limits. stats, if given, receives the peak memory in MB; Windows
    counts a refused request in that peak, so after a stop it can exceed the limit
    (measured: an 8 GB commit refused under a 4 GB ceiling reads 8217 MB).
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.CreateDesktopW.restype = wintypes.HANDLE
    user32.CreateDesktopW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p,
                                      wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel32.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                                   wintypes.DWORD, ctypes.c_void_p]
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    class BASIC_LIMIT(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class EXTENDED_LIMIT(ctypes.Structure):
        _fields_ = [("Basic", BASIC_LIMIT), ("IoInfo", ctypes.c_uint64 * 6),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    class STARTUPINFOW(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR), ("lpDesktop", wintypes.LPWSTR),
                    ("lpTitle", wintypes.LPWSTR), ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
                    ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD), ("dwXCountChars", wintypes.DWORD),
                    ("dwYCountChars", wintypes.DWORD), ("dwFillAttribute", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
                    ("lpReserved2", ctypes.c_void_p), ("hStdInput", wintypes.HANDLE),
                    ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE)]

    class PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                    ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]

    # One run at a time: three FreeCADs started side by side were the first of
    # the two machine-wide memory exhaustions.
    mutex = kernel32.CreateMutexW(None, False, HARNESS_MUTEX)
    if not mutex:
        raise OSError(ctypes.get_last_error(), "CreateMutexW failed")
    if kernel32.WaitForSingleObject(mutex, 0) not in (0, 0x80):   # WAIT_OBJECT_0, WAIT_ABANDONED
        kernel32.CloseHandle(mutex)
        raise HarnessBusy("another NX-style smoke/tutorial run is active; wait for it to finish")

    limit = int(max_memory_gb * 1024 ** 3)
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        kernel32.ReleaseMutex(mutex)
        kernel32.CloseHandle(mutex)
        raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
    info = EXTENDED_LIMIT()
    # JOB_MEMORY | DIE_ON_UNHANDLED_EXCEPTION (no WerFault dialog) | KILL_ON_JOB_CLOSE
    info.Basic.LimitFlags = 0x0200 | 0x0400 | 0x2000
    info.JobMemoryLimit = limit
    if not kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
        raise OSError(ctypes.get_last_error(), "SetInformationJobObject failed")

    def peak() -> int:
        q = EXTENDED_LIMIT()
        kernel32.QueryInformationJobObject(job, 9, ctypes.byref(q), ctypes.sizeof(q), None)
        return q.PeakJobMemoryUsed

    name = f"NXStyleSmoke{os.getpid()}"
    desk = user32.CreateDesktopW(name, None, None, 0, 0x10000000, None) if hidden else None  # GENERIC_ALL
    if hidden and not desk:
        raise OSError(ctypes.get_last_error(), "CreateDesktopW failed")
    try:
        si = STARTUPINFOW()
        si.cb = ctypes.sizeof(si)
        si.lpDesktop = f"WinSta0\\{name}" if hidden else None
        pi = PROCESS_INFORMATION()
        block = "".join(f"{k}={v}\0" for k, v in env.items()) + "\0"
        cmdline = subprocess.list2cmdline(cmd)
        # Hard-error and GP-fault boxes are inherited settings: none reach the screen.
        kernel32.SetErrorMode(0x0001 | 0x0002)   # SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX
        ok = kernel32.CreateProcessW(None, ctypes.create_unicode_buffer(cmdline), None, None, False,
                                     0x00000400 | 0x00000004,  # CREATE_UNICODE_ENVIRONMENT | CREATE_SUSPENDED
                                     ctypes.create_unicode_buffer(block), None,
                                     ctypes.byref(si), ctypes.byref(pi))
        if not ok:
            raise OSError(ctypes.get_last_error(), "CreateProcessW failed")
        try:
            # In the job before its first instruction, so every child is in it too.
            if not kernel32.AssignProcessToJobObject(job, pi.hProcess):
                err = ctypes.get_last_error()
                kernel32.TerminateProcess(pi.hProcess, 3)
                raise OSError(err, "AssignProcessToJobObject failed")
            kernel32.ResumeThread(pi.hThread)
            deadline = time.monotonic() + timeout_s
            while kernel32.WaitForSingleObject(pi.hProcess, 250) != 0:
                if peak() >= limit - 64 * 1024 ** 2:
                    kernel32.TerminateJobObject(job, STATUS_NO_MEMORY)
                    kernel32.WaitForSingleObject(pi.hProcess, 10_000)
                    break
                if time.monotonic() > deadline:
                    kernel32.TerminateJobObject(job, 3)
                    return None
            code = wintypes.DWORD()
            kernel32.GetExitCodeProcess(pi.hProcess, ctypes.byref(code))
            return STATUS_NO_MEMORY if peak() >= limit - 64 * 1024 ** 2 else code.value
        finally:
            if stats is not None:
                stats["peak_mb"] = peak() // 1024 ** 2
                stats["limit_mb"] = limit // 1024 ** 2
            kernel32.CloseHandle(pi.hThread)
            kernel32.CloseHandle(pi.hProcess)
    finally:
        if desk:
            user32.CloseDesktop(desk)
        kernel32.CloseHandle(job)          # KILL_ON_JOB_CLOSE: nothing of the run survives
        kernel32.ReleaseMutex(mutex)
        kernel32.CloseHandle(mutex)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def pick_install(path: str | None) -> Install:
    if path:
        exe = Path(path)
        if exe.is_dir():
            for sub in ("bin", ""):
                for name in _exe_names():
                    if (exe / sub / name).is_file():
                        exe = exe / sub / name
                        break
        if not exe.is_file():
            raise SystemExit(f"FreeCAD executable not found: {path}")
        return Install(exe.resolve(), probe_version(exe))
    installs = discover()
    if not installs:
        raise SystemExit("No FreeCAD found. Install FreeCAD 1.0 or newer, or pass --freecad PATH.")
    return installs[0]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("files", nargs="*", help="documents to open")
    ap.add_argument("--freecad", help="FreeCAD executable or install folder (default: newest found)")
    ap.add_argument("--profile", type=Path, help=f"profile folder (default: {default_profile_root()}/profile-<ver>; "
                    "with --smoke-test/--tutorial a fresh temporary one, or this folder kept between runs)")
    ap.add_argument("--reset-profile", action="store_true", help="delete the NX profile before starting")
    ap.add_argument("--list", action="store_true", help="list FreeCAD installs and exit")
    ap.add_argument("--dry-run", action="store_true", help="print what would run, start nothing")
    ap.add_argument("--wait", action="store_true", help="wait for FreeCAD to exit")
    ap.add_argument("--smoke-test", type=Path, metavar="OUTDIR",
                    help="run the built-in self-test in a fresh throwaway profile, write results to OUTDIR")
    ap.add_argument("--tutorial", type=Path, metavar="OUTDIR",
                    help="replay the NX textbook tutorials in a throwaway profile, write results to OUTDIR")
    ap.add_argument("--tutorials", default="A,B,C,D,E,F,G,H,I,J,K,L,M,N,O,P,Q,R,S,T,U,V,W,X,Y,Z,AA,AB,AC,AD,AE,AF,AG,AH,AJ,AK,AN,AO,AP,AQ,AR,AS,AT,AU,AX,AY",
                    help="with --tutorial: which exercises to replay (A Adjuster, B cylinder+cone, "
                         "C Rod-Guide, D Pulley with drawing, E Saddle Bracket, F Dryer Housing, "
                         "G Shaft Support assembly, H GD&T plate drawing, I Gasket (trim, fillet, "
                         "offset), J parametric constraints, K spreadsheet-driven plate, L Locator (CSG), "
                         "M U-Bracket (parent/child, suppress), N U-Bracket drawing (runs M first), "
                         "O Grasshopper basics, P waffle canopy, Q faceted planter, R masterclass tube, all on the Katydid canvas, "
                         "S tolerance stack-up of a pin, T guide bush documented to ISO GPS with 3D PMI and its drawing, "
                         "U volume claims and assembly clearance, V release and engineering change (runs T first), "
                         "W sheet metal bracket, X pin location of a laser module, Y PMI model views, "
                         "Z MBD exchange through STEP AP242, AA composite position evaluated from CMM data, "
                         "AB measurement capability (TUR, guard bands, gauge studies), "
                         "AC title block and revision block from the release (runs T and V first), "
                         "AD a laser-cut tray with tabs and slots, AE one Extrude through the command controller: "
                         "None (new body), Unite, Subtract, edit, cancel, undo, reopen, "
                         "AF Arbor Press Base: a sketch constrained to size, extruded, AG Impeller Lower Casing: a sketch built with Move Curve copies, AH Impeller: tangent arcs by centre and by 3 points, AJ Circular Base: a disc with four slots, AK Holder: a sketch with Quick Trim and Rotate Curve copies, "
                         "AN Arbor Press Plate: Block, Datum Plane, Datum Axis and six holes, "
                         "AO Impeller Lower Casing: AG's sketch revolved, extruded and mirrored (runs AG first), "
                         "AP Impeller Shaft: Cylinder, Cone and Cylinder united, each at the centre of the last edge, "
                         "AQ Hexagonal Screw: cylinders, a hexagon head, a Sphere Intersect, "
                         "AR Hexagonal Nut: a hexagon, Sphere Intersect, Mirror, hole, Chamfer, "
                         "AS Arbor Press L-Bar: Blocks, Move Object, Combine, Edge Blend, "
                         "AT Arbor Press Rack: a tapered pocket patterned 19 times, a hole, "
                         "AU Impeller: AH's blade with a Cone, Extrude, Circular Pattern and two holes (runs AH first), "
                         "AX Impeller Upper Casing: AO's casing edited to the other side, a manhole (runs AO first), "
                         "AY Die Cavity: Blocks, a spline section revolved to cut, a cavity with posts, Edge Blends)")
    ap.add_argument("--keep-open", action="store_true", help="with --smoke-test: leave FreeCAD open afterwards")
    ap.add_argument("--require-all", action="store_true",
                    help="with --smoke-test: a check skipped because this FreeCAD lacks what it needs (no pythonocc, "
                         "no FEM, no QtTest) fails the run instead of being reported apart")
    ap.add_argument("--visible", action="store_true",
                    help="with --smoke-test on Windows: show FreeCAD on your desktop instead of a hidden one")
    ap.add_argument("--max-memory-gb", type=float, default=HARNESS_MEMORY_GB,
                    help=f"with --smoke-test/--tutorial on Windows: end the run when FreeCAD uses more "
                         f"(default {HARNESS_MEMORY_GB:g})")
    ap.add_argument("--no-strata", action="store_true",
                    help="start without Strata (versions, releases and sync; on by default)")
    ap.add_argument("--no-katydid", action="store_true",
                    help="start without Katydid (the node-based Algorithmic Modeling canvas; on by default)")
    ap.add_argument("--no-sheetmetal", action="store_true",
                    help="start without the SheetMetal add-on (NX Sheet Metal; on by default)")
    ap.add_argument("--no-lcinterlocking", action="store_true",
                    help="start without the LCInterlocking add-on (Laser Cut; on by default)")
    ap.add_argument("--no-dfm", action="store_true",
                    help="start without the DFM add-on (Analysis > Molded Part Validation; on by default once "
                         "--install-dfm-deps has run)")
    ap.add_argument("--install-dfm-deps", action="store_true",
                    help=f"install what the DFM add-on needs ({', '.join(DFM_DEPS)}) with FreeCAD's own Python "
                         f"into {default_profile_root()}/pydeps, then exit (downloads about 165 MB)")
    ap.add_argument("passthrough", nargs=argparse.REMAINDER,
                    help="arguments after -- go to FreeCAD unchanged")
    args = ap.parse_args(argv)
    passthrough = args.passthrough[1:] if args.passthrough[:1] == ["--"] else args.passthrough

    if args.list:
        for inst in discover():
            print(f"{inst.version_str:>10}  {inst.exe}")
        return 0

    install = pick_install(args.freecad)
    if install.version and install.version < (1, 0, 0):
        print(f"warning: FreeCAD {install.version_str} is older than 1.0 and is not supported", file=sys.stderr)
    if args.install_dfm_deps:
        return install_dfm_deps(install)

    extra = {}
    harness = "smoke" if args.smoke_test else "tutorial" if args.tutorial else None
    if harness:
        out = (args.smoke_test or args.tutorial).resolve()
        out.mkdir(parents=True, exist_ok=True)
        profile = args.profile or Path(tempfile.mkdtemp(prefix=f"nxstyle-{harness}-"))
        run_id = uuid.uuid4().hex             # the result must carry it: a file from another run is rejected
        extra = {f"NXSTYLE_{harness.upper()}_OUT": out, "NXSTYLE_SMOKE_EXIT": "0" if args.keep_open else "1",
                 "NXSTYLE_TUTORIALS": args.tutorials, "NXSTYLE_RUN_ID": run_id}
        # a throwaway profile by default; a --profile given is kept between runs (a second start sees
        # what the first one saved), unless --reset-profile is given too
        reset = args.reset_profile if args.profile else True
    else:
        ver = f"{install.version[0]}.{install.version[1]}" if install.version else "unknown"
        profile = args.profile or default_profile_root() / f"profile-{ver}"
        reset = args.reset_profile

    strata, strata_why = find_strata(profile.resolve(), disabled=args.no_strata)
    extra["NXSTYLE_STRATA_EXPECTED"] = "1" if strata or "NX profile" in strata_why else "0"
    katydid, katydid_why = find_katydid(profile.resolve(), disabled=args.no_katydid)
    extra["NXSTYLE_KATYDID_EXPECTED"] = "1" if katydid or "NX profile" in katydid_why else "0"
    sheetmetal, sheetmetal_why = find_sheetmetal(profile.resolve(), disabled=args.no_sheetmetal)
    extra["NXSTYLE_SHEETMETAL_EXPECTED"] = "1" if sheetmetal or "NX profile" in sheetmetal_why else "0"
    lcinterlocking, lcinterlocking_why = find_lcinterlocking(profile.resolve(), disabled=args.no_lcinterlocking)
    extra["NXSTYLE_LCINTERLOCKING_EXPECTED"] = "1" if lcinterlocking or "NX profile" in lcinterlocking_why else "0"
    dfm, dfm_why = find_dfm(profile.resolve(), install, disabled=args.no_dfm)
    extra["NXSTYLE_DFM_EXPECTED"] = "1" if dfm_why.startswith(("bundled", "installed")) else "0"
    cmd = build_command(install, args.files, passthrough,
                        tuple(m for m in (strata, katydid, sheetmetal, lcinterlocking) if m) + dfm)
    if args.dry_run:
        print(json.dumps({"freecad": str(install.exe), "version": install.version_str,
                          "profile": str(profile.resolve()), "strata": strata_why, "katydid": katydid_why,
                          "sheetmetal": sheetmetal_why, "lcinterlocking": lcinterlocking_why, "dfm": dfm_why,
                          "command": cmd},
                         indent=2))
        return 0

    paths = prepare_profile(profile, reset=reset)
    seed_user_cfg(paths, install.version)
    env = build_env(paths, extra)
    print(f"FreeCAD {install.version_str}: {install.exe}")
    print(f"NX profile: {profile.resolve()}")
    print(f"Strata: {strata_why}")
    print(f"Katydid: {katydid_why}")
    print(f"SheetMetal: {sheetmetal_why}")
    print(f"LCInterlocking: {lcinterlocking_why}")
    print(f"DFM: {dfm_why}")

    if harness:
        if os.name == "nt":
            stats = {}
            # the self-test takes about 2 minutes; a textbook tutorial about a minute, a canvas (Katydid) one
            # up to about 8 (measured 2026-10-14: O-R together ~20 min)
            timeout_s = 300 + 300 * len(args.tutorials.split(",")) if harness == "tutorial" else 600
            try:
                code = run_on_hidden_desktop(cmd, env, timeout_s=timeout_s, max_memory_gb=args.max_memory_gb,
                                             hidden=not args.visible, stats=stats)
            except HarnessBusy as e:
                print(f"{harness} run refused: {e}", file=sys.stderr)
                return 5
            if code == STATUS_NO_MEMORY:
                # the job's peak counter includes the request it refused
                print(f"{harness} run stopped: FreeCAD asked for {stats.get('peak_mb', 0)} MB in total, over the "
                      f"{args.max_memory_gb:g} GB ceiling; the request was refused and the run ended, "
                      f"the rest of the machine was not affected", file=sys.stderr)
                return 4
            print(f"peak memory: {stats.get('peak_mb', 0)} MB of {stats.get('limit_mb', 0)} MB allowed")
            if code is None:
                print(f"{harness} run timed out", file=sys.stderr)
                return 3
        else:
            proc = subprocess.Popen(cmd, env=env)
            try:
                code = proc.wait(timeout=600)
            except subprocess.TimeoutExpired:
                proc.kill()
                print(f"{harness} run timed out", file=sys.stderr)
                return 3
        if not args.profile:
            shutil.rmtree(profile, ignore_errors=True)
        return judge_result(out / RESULT_FILES[harness], harness, run_id, code, require_all=args.require_all)

    kwargs = {}
    if os.name == "nt" and not args.wait:
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    elif not args.wait:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, env=env, **kwargs)
    if args.wait:
        return proc.wait()
    time.sleep(0.2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
