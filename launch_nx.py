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


def probe_version(gui_exe: Path) -> tuple[int, int, int] | None:
    target = _console_exe(gui_exe) or gui_exe
    try:
        out = subprocess.run(
            [str(target), "--version"], capture_output=True, text=True, timeout=60,
            env=_clean_env(),
        )
        m = VERSION_RE.search(out.stdout + out.stderr)
    except (OSError, subprocess.SubprocessError):
        m = None
    if not m:
        # Fall back to a version embedded in the folder name ("FreeCAD 1.0").
        m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", str(gui_exe.parent.parent.name))
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


def build_command(install: Install, files: list[str], passthrough: list[str]) -> list[str]:
    return [str(install.exe), "-M", str(MODULE_DIR), *passthrough, *files]


# --------------------------------------------------------------------------
# Hidden desktop (Windows): run the self-test without windows on the user's screen
# --------------------------------------------------------------------------
def run_on_hidden_desktop(cmd: list[str], env: dict, timeout_s: int) -> int | None:
    """Start cmd on a separate, never-shown Win32 desktop and wait for it.

    Returns the exit code, or None on timeout. The windows exist and paint, but
    on a desktop nobody is looking at, so they cannot steal focus or block input.
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.CreateDesktopW.restype = wintypes.HANDLE
    user32.CreateDesktopW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p,
                                      wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]

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

    name = f"NXStyleSmoke{os.getpid()}"
    desk = user32.CreateDesktopW(name, None, None, 0, 0x10000000, None)  # GENERIC_ALL
    if not desk:
        raise OSError(ctypes.get_last_error(), "CreateDesktopW failed")
    try:
        si = STARTUPINFOW()
        si.cb = ctypes.sizeof(si)
        si.lpDesktop = f"WinSta0\\{name}"
        pi = PROCESS_INFORMATION()
        block = "".join(f"{k}={v}\0" for k, v in env.items()) + "\0"
        cmdline = subprocess.list2cmdline(cmd)
        ok = kernel32.CreateProcessW(None, ctypes.create_unicode_buffer(cmdline), None, None, False,
                                     0x00000400,  # CREATE_UNICODE_ENVIRONMENT
                                     ctypes.create_unicode_buffer(block), None,
                                     ctypes.byref(si), ctypes.byref(pi))
        if not ok:
            raise OSError(ctypes.get_last_error(), "CreateProcessW failed")
        try:
            if kernel32.WaitForSingleObject(pi.hProcess, timeout_s * 1000) != 0:
                kernel32.TerminateProcess(pi.hProcess, 3)
                return None
            code = wintypes.DWORD()
            kernel32.GetExitCodeProcess(pi.hProcess, ctypes.byref(code))
            return code.value
        finally:
            kernel32.CloseHandle(pi.hThread)
            kernel32.CloseHandle(pi.hProcess)
    finally:
        user32.CloseDesktop(desk)


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
    ap.add_argument("--profile", type=Path, help=f"profile folder (default: {default_profile_root()}/profile-<ver>)")
    ap.add_argument("--reset-profile", action="store_true", help="delete the NX profile before starting")
    ap.add_argument("--list", action="store_true", help="list FreeCAD installs and exit")
    ap.add_argument("--dry-run", action="store_true", help="print what would run, start nothing")
    ap.add_argument("--wait", action="store_true", help="wait for FreeCAD to exit")
    ap.add_argument("--smoke-test", type=Path, metavar="OUTDIR",
                    help="run the built-in self-test in a fresh throwaway profile, write results to OUTDIR")
    ap.add_argument("--tutorial", type=Path, metavar="OUTDIR",
                    help="replay the NX textbook tutorials in a throwaway profile, write results to OUTDIR")
    ap.add_argument("--keep-open", action="store_true", help="with --smoke-test: leave FreeCAD open afterwards")
    ap.add_argument("--visible", action="store_true",
                    help="with --smoke-test on Windows: show FreeCAD on your desktop instead of a hidden one")
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

    extra = {}
    harness = "smoke" if args.smoke_test else "tutorial" if args.tutorial else None
    if harness:
        out = (args.smoke_test or args.tutorial).resolve()
        out.mkdir(parents=True, exist_ok=True)
        profile = args.profile or Path(tempfile.mkdtemp(prefix=f"nxstyle-{harness}-"))
        extra = {f"NXSTYLE_{harness.upper()}_OUT": out, "NXSTYLE_SMOKE_EXIT": "0" if args.keep_open else "1"}
        reset = True
    else:
        ver = f"{install.version[0]}.{install.version[1]}" if install.version else "unknown"
        profile = args.profile or default_profile_root() / f"profile-{ver}"
        reset = args.reset_profile

    cmd = build_command(install, args.files, passthrough)
    if args.dry_run:
        print(json.dumps({"freecad": str(install.exe), "version": install.version_str,
                          "profile": str(profile.resolve()), "command": cmd}, indent=2))
        return 0

    paths = prepare_profile(profile, reset=reset)
    seed_user_cfg(paths, install.version)
    env = build_env(paths, extra)
    print(f"FreeCAD {install.version_str}: {install.exe}")
    print(f"NX profile: {profile.resolve()}")

    if harness:
        if os.name == "nt" and not args.visible:
            code = run_on_hidden_desktop(cmd, env, timeout_s=600)
            if code is None:
                print(f"{harness} run timed out", file=sys.stderr)
                return 3
        else:
            proc = subprocess.Popen(cmd, env=env)
            try:
                proc.wait(timeout=600)
            except subprocess.TimeoutExpired:
                proc.kill()
                print(f"{harness} run timed out", file=sys.stderr)
                return 3
        result_file = out / ("smoke.json" if harness == "smoke" else "tutorial.json")
        if not result_file.is_file():
            print(f"{harness} run produced no result (FreeCAD crashed or NXStyle failed to load)", file=sys.stderr)
            return 2
        result = json.loads(result_file.read_text(encoding="utf-8"))
        if not args.profile:
            shutil.rmtree(profile, ignore_errors=True)
        if harness == "smoke":
            failed = [c for c in result.get("checks", []) if not c.get("ok")]
            for c in result.get("checks", []):
                print(f"{'PASS' if c['ok'] else 'FAIL'}  {c['name']}: {c.get('detail', '')}")
            return 1 if failed else 0
        for s in result.get("steps", []):
            print(f"{s['tutorial'][:1]}{s['n']:>3} {s['outcome']:<8} {s['nx']}  [{s['replay']}]  {s['detail']}")
        return 1 if any(s["outcome"] == "FAILED" for s in result.get("steps", [])) else 0

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
