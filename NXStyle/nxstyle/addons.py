# SPDX-License-Identifier: LGPL-2.1-or-later
"""Workbenches of the user's own add-ons as applications on the Application tab.

The user's add-ons are those in the NX profile's own Mod folder (installed there with the Addon Manager) and those
the launcher loads from the normal FreeCAD profile with --user-addons (NXSTYLE_USER_ADDONS). A workbench belongs to
one when its Python code (or its icon file) lives in that add-on's folder. A workbench that ribbons/apps.json
already places keeps its place there. Such an application has no hand-made ribbon, so NX-Style builds one from the
workbench's own toolbars (shell.Shell._auto_groups). The functions without FreeCAD in their name need no FreeCAD.
"""

import os

GROUP = "Add-ons"


def _within(path, folder):
    path, folder = os.path.normcase(os.path.abspath(path)), os.path.normcase(os.path.abspath(folder))
    return path == folder or path.startswith(folder.rstrip(os.sep) + os.sep)


def workbench_files(wb):
    """The files a workbench object's Python code comes from (its class's methods), and its icon if a file."""
    files = []
    for cls in type(wb).__mro__:
        for value in vars(cls).values():
            code = getattr(value, "__code__", None)
            if code is not None:
                files.append(code.co_filename)
    icon = getattr(wb, "Icon", "")
    if isinstance(icon, str) and os.path.isfile(icon):
        files.append(icon)
    return files


def addon_apps(workbenches, folders, placed):
    """Applications for the Add-ons group: ``workbenches`` is {name: (menu text, files)}, ``folders`` the add-on
    folders, ``placed`` the workbench names apps.json already has. Sorted by title."""
    apps = []
    for name, (title, files) in workbenches.items():
        if name in placed:
            continue
        if any(_within(f, d) for f in files for d in folders):
            apps.append({"id": f"addon_{name}", "title": title or name, "workbench": name})
    return sorted(apps, key=lambda a: a["title"].lower())


def user_folders_freecad():
    """The user's add-on folders in this FreeCAD: the launcher's NXSTYLE_USER_ADDONS and the NX profile's Mod."""
    import FreeCAD as App
    folders = [p for p in os.environ.get("NXSTYLE_USER_ADDONS", "").split(os.pathsep) if p]
    own = os.path.join(App.getUserAppDataDir(), "Mod")
    if os.path.isdir(own):
        folders += [os.path.join(own, d) for d in os.listdir(own) if os.path.isdir(os.path.join(own, d))]
    return folders


def apps_freecad(placed):
    """addon_apps for the workbenches FreeCAD has registered now."""
    import FreeCADGui as Gui
    benches = {}
    for name, wb in Gui.listWorkbenches().items():
        try:
            benches[name] = (getattr(wb, "MenuText", "") or "", workbench_files(wb))
        except Exception:
            continue
    return addon_apps(benches, user_folders_freecad(), placed)
