# SPDX-License-Identifier: LGPL-2.1-or-later
"""Settings for the NX-style shell.

Defaults live here. Override any key in ``nxstyle.json`` in the profile's
config folder (the launcher prints the profile location); every setting and its
default is written to ``nxstyle.defaults.json`` next to it for reference.
"""

import copy
import json
import os

import FreeCAD as App

RESOURCES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources")

# Colours are approximations: Siemens documents red pre-selection and orange
# selection, light-grey gradient backgrounds and a grey "Medium Steel" body
# colour, but publishes no RGB values for them.
DEFAULTS = {
    # "nx"     = NXStyle's own mouse handling (same on every FreeCAD version)
    # "native" = FreeCAD's Gui::SiemensNXNavigationStyle (FreeCAD 1.1+)
    # anything else is used verbatim as a FreeCAD navigation style class name
    "navigation": "nx",
    "units": "metric",                 # "metric": FreeCAD's Standard schema (mm, kg); "freecad": leave units alone
    "labels": "nx",                    # "nx" names (Extrude, Edge Blend) or "freecad" names (Pad, Fillet)
    "hide_menubar": True,              # menus stay reachable from the Menu button
    "hide_native_toolbars": True,      # FreeCAD's own toolbars stay hidden (Tools > FreeCAD Menus and Toolbars shows them)
    "floating_task_panel": False,      # True = feature dialogs float over the graphics window like NX
    "stylesheet": "auto",                # FreeCAD's light stylesheet for this version; or a file name
    "theme": "nx",                     # "nx" = NXStyle's light theme over that stylesheet; "none" = FreeCAD's look
    "background": "light_gray_gradient",  # white, light, light_gray_gradient, dark_gray_gradient or dark (View > Background)
    "colors": {                        # preselection, selection, body and edge colours of the graphics window
        "preselection": "#FF2020",
        "selection": "#FF8C00",
        "body": "#A7ADB4",
        "edges": "#1E1E1E",
    },
    "edge_width": 1,                   # line width of a body's edges, in pixels
    "view_triad": "nx",                # "nx" = lower-left (NXStyle), "freecad" = FreeCAD's lower-right one
    "zoom_at_cursor": True,            # the wheel zooms towards the point under the cursor
    "invert_wheel_zoom": True,         # FreeCAD default: wheel forward zooms in
    "rotate_degrees_per_pixel": 0.4,   # MB2 drag: how fast the view turns
    "zoom_drag_up_zooms_in": True,     # Ctrl+MB2 / MB1+MB2 drag: dragging up zooms in (false: down zooms in)
    "mb2_click_is_ok": True,           # middle click accepts the open feature dialog
    "mb2_hold_sets_rotation_point_ms": 450,  # press and hold MB2 this long on the model to rotate about that point
    "mb3_hold_radial_menu_ms": 350,    # hold MB3 this long for the radial menu; 0 switches the radial menu off
    "quickpick_hold_ms": 500,          # hold MB1 still this long for QuickPick; 0 switches QuickPick and select-through off
    "default_application": "modeling",  # the application NXStyle starts in (an id from ribbons/apps.json)
    "new_part_datum": True,            # a new empty part starts with a Body (NX Model template)
    "nx_shortcuts": True,              # bind the NX keys (see Keyboard shortcuts); false keeps FreeCAD's
    "plm": "strata",                   # data management (Teamcenter's role): "strata" add-on, or "none"
    "algorithmic_modeling": "katydid",  # node-based modelling (NX Algorithmic Modeling): "katydid" add-on, or "none"
    "sheet_metal": "sheetmetal",       # NX Sheet Metal: FreeCAD's "sheetmetal" add-on (bundled), or "none"
    "laser_cut": "lcinterlocking",     # Laser Cut: the "lcinterlocking" add-on (bundled), or "none"
}

BACKGROUNDS = {
    # name: (label, top, bottom); one colour means a plain background
    "white": ("White Background", "#FFFFFF", None),
    "light": ("Light Background", "#E6E9ED", None),
    "light_gray_gradient": ("Light Gray Gradient", "#B9C3CE", "#F2F4F6"),
    "dark_gray_gradient": ("Dark Gray Gradient", "#2C3138", "#6B737C"),
    "dark": ("Dark Background", "#25282C", None),
}

_cfg = None


def profile_dir():
    """The folder that holds nxstyle.json: the NX profile's config folder, where the launcher and the
    documentation look too (the launcher sets NXSTYLE_PROFILE to the profile's root)."""
    root = os.environ.get("NXSTYLE_PROFILE")
    return os.path.join(root, "config") if root else App.getUserConfigDir()


def user_file():
    path = os.path.join(profile_dir(), "nxstyle.json")
    root = os.environ.get("NXSTYLE_PROFILE")
    legacy = os.path.join(root, "nxstyle.json") if root else None
    # NXStyle before 2026-10-13 read nxstyle.json from the profile's root; keep honouring one there
    if not os.path.isfile(path) and legacy and os.path.isfile(legacy):
        return legacy
    return path


def _merge(base, over):
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def load():
    global _cfg
    cfg = copy.deepcopy(DEFAULTS)
    path = user_file()
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                _merge(cfg, json.load(f))
        except (OSError, ValueError) as e:
            App.Console.PrintWarning(f"NXStyle: ignoring unreadable {path}: {e}\n")
    # A reference copy of every setting; nxstyle.json holds only what you change,
    # so new defaults still reach existing profiles.
    try:
        with open(os.path.join(profile_dir(), "nxstyle.defaults.json"), "w", encoding="utf-8") as f:
            json.dump(DEFAULTS, f, indent=2)
    except OSError:
        pass
    _cfg = cfg
    return cfg


def get():
    return _cfg if _cfg is not None else load()


def resource(*parts):
    return os.path.join(RESOURCES, *parts)


def load_json(*parts):
    with open(resource(*parts), encoding="utf-8") as f:
        return json.load(f)
