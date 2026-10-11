# SPDX-License-Identifier: LGPL-2.1-or-later
"""Settings for the NX-style shell.

Defaults live here. A user can override any key in ``nxstyle.json`` inside the
profile folder (the launcher prints its location); the file is created with the
defaults on first start so it is easy to find and edit.
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
    "labels": "nx",                    # "nx" names (Extrude, Edge Blend) or "freecad" names (Pad, Fillet)
    "hide_menubar": True,              # menus stay reachable from the Menu button
    "hide_native_toolbars": True,
    "floating_task_panel": False,      # True = feature dialogs float over the graphics window like NX
    "stylesheet": "FreeCAD Light.qss",
    "background": "light_gray_gradient",
    "colors": {
        "preselection": "#FF2020",
        "selection": "#FF8C00",
        "body": "#A7ADB4",
        "edges": "#1E1E1E",
    },
    "edge_width": 1,
    "view_triad": "nx",                # "nx" = lower-left (NXStyle), "freecad" = FreeCAD's lower-right one
    "zoom_at_cursor": True,
    "invert_wheel_zoom": True,         # FreeCAD default: wheel forward zooms in
    "rotate_degrees_per_pixel": 0.4,
    "zoom_drag_up_zooms_in": True,
    "mb2_click_is_ok": True,           # middle click accepts the open feature dialog
    "mb2_hold_sets_rotation_point_ms": 450,
    "mb3_hold_radial_menu_ms": 350,
    "default_application": "modeling",
    "nx_shortcuts": True,
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
    return os.environ.get("NXSTYLE_PROFILE") or App.getUserConfigDir()


def user_file():
    return os.path.join(profile_dir(), "nxstyle.json")


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
    else:
        try:
            with open(path, "w", encoding="utf-8") as f:
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
