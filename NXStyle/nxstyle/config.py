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
    "icon_theme": "nx",                # "nx" = original NX-inspired Modeling/Sketch icons; "freecad" = native icons
    "background": "studio",               # studio, white, light, light_gray_gradient, dark_gray_gradient or dark (View > Background)
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
    # MB2 drag: "auto" = the axes of FreeCAD's orbit style (Preferences › Display › Navigation: Turntable, Free
    # Turntable, Trackball...) on FreeCAD 1.1 and later, where a profile without one gets Trackball Classic, NX's
    # own rotation; NX's own on FreeCAD 1.0, whose list has no such entry; "freecad" = FreeCAD's orbit style on
    # 1.0 too; "nx" = always NX's own
    "orbit_style": "auto",
    "zoom_drag_up_zooms_in": True,     # Ctrl+MB2 / MB1+MB2 drag: dragging up zooms in (false: down zooms in)
    "mb2_click_is_ok": True,           # middle click accepts the open feature dialog
    "mb2_hold_sets_rotation_point_ms": 450,  # press and hold MB2 this long on the model to rotate about that point
    "mb3_hold_radial_menu_ms": 350,    # hold MB3 this long for the radial menu; 0 switches the radial menu off
    "quickpick_hold_ms": 500,          # rest the pointer (then click) or hold MB1 this long for QuickPick; 0 = off, with select-through
    "default_application": "modeling",  # the application NXStyle starts in (an id from ribbons/apps.json)
    "new_part_datum": True,            # a new empty part starts with a Body (NX Model template)
    # sketch curves and points take typed coordinates, as NX's XC/YC input boxes: "position" = FreeCAD's on-view
    # parameters 'Position and dimensions'; "dimensions" (FreeCAD's default), "none", or "freecad" (leave alone)
    "sketch_input": "position",
    "nx_shortcuts": True,              # bind the NX keys (see Keyboard shortcuts); false keeps FreeCAD's
    # preferences the launcher copies from your normal FreeCAD at every start, which it only reads: "navigation"
    # (style, orbit style, zoom; the NX-Style settings navigation, zoom_at_cursor and invert_wheel_zoom you set
    # here still win), "view_cube", "macros" (macro commands, their files copied into this profile), "all"; [] =
    # none, true = navigation
    "import_preferences": [],
    # your normal FreeCAD's user folder (holds user.cfg, Mod and Macro), or {"config": ..., "data": ...} where they
    # are apart (Linux: ~/.config/FreeCAD and ~/.local/share/FreeCAD); "" = FreeCAD's usual folders
    "normal_profile": "",
    # also load the add-ons of your normal FreeCAD's Mod folder (not those NX-Style bundles or the NX profile has);
    # their workbenches join Application › Add-ons with a ribbon made from their toolbars
    "user_addons": False,
    "plm": "strata",                   # data management (Teamcenter's role): "strata" add-on, or "none"
    "algorithmic_modeling": "katydid",  # node-based modelling (NX Algorithmic Modeling): "katydid" add-on, or "none"
    "sheet_metal": "sheetmetal",       # NX Sheet Metal: FreeCAD's "sheetmetal" add-on (bundled), or "none"
    "laser_cut": "lcinterlocking",     # Laser Cut: the "lcinterlocking" add-on (bundled), or "none"
    "dfm": "dfm",                      # Molded Part Validation: the "dfm" add-on (bundled; needs OCP), or "none"
    "nxt": False,                      # the FreeCAD-Nxt add-on (model panel, Property Inspector), trial: off by default
    "manufacturing": "carbon",         # manufacturing ERP/MES/quality: "carbon" (a Carbon server), or "none"
    "carbon": {                        # The Carbon connection; PLM › Manufacturing Connection sets it, never the API key.
        "url": "",                     # url: https://app.carbon.ms (Carbon Cloud) or your own server.
        "api_key_file": "",            # api_key_file: "" = carbon.key in this config folder; CARBON_API_KEY wins.
        "location": "",                # location: the stock location for Manufacturing Status; "" = the first.
        "allow_unreleased": False,     # allow_unreleased: true also publishes a part with no Strata release.
        "new_part": {                  # new_part: what a part new to Carbon gets (Carbon's item fields).
            "replenishmentSystem": "Make",
            "defaultMethodType": "Make to Order",
            "itemTrackingType": "Inventory",
            "unitOfMeasureCode": "EA",
        },
    },
}

BACKGROUNDS = {
    # name: (label, top, bottom); one colour means a plain background
    "studio": ("Studio Background", "#DCE5ED", "#F8FAFC"),
    "white": ("White Background", "#FFFFFF", None),
    "light": ("Light Background", "#E6E9ED", None),
    "light_gray_gradient": ("Light Gray Gradient", "#B9C3CE", "#F2F4F6"),
    "dark_gray_gradient": ("Dark Gray Gradient", "#2C3138", "#6B737C"),
    "dark": ("Dark Background", "#25282C", None),
}

_cfg = None
IMPORTED_FILE = "nxstyle.imported.json"     # launch_nx.IMPORTED_FILE
DEFAULTS_FILE = "nxstyle.defaults.json"     # launch_nx.DEFAULTS_FILE
DEFAULTS_NOTE = ("For reference only: NX-Style rewrites this file at every start and never reads it. To change a "
                 "setting, put it in nxstyle.json in this folder, for example {\"navigation\": \"native\"}.")
# what load() read: {"path": nxstyle.json, "exists": bool, "error": why it was ignored or None,
# "defaults edited": {setting: value} that nxstyle.defaults.json held other than the defaults (it is not read)}
source = {}


def fingerprint(values):
    """The fingerprint written into nxstyle.defaults.json (launch_nx.settings_fingerprint: the same)."""
    import hashlib
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode("utf-8")).hexdigest()


def defaults_edits(path, defaults=None):
    """({setting: value}, certain): what an nxstyle.defaults.json, which is never read, holds other than the
    defaults. A file NX-Style wrote carries the fingerprint of what it wrote, so a difference there is a hand edit
    (certain); an older file without one is compared with today's defaults, where a default changed since then
    shows as well. ({}, False) when it is unchanged, missing or unreadable."""
    defaults = DEFAULTS if defaults is None else defaults
    try:
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}, False
    if not isinstance(data, dict):
        return {}, False
    stamp = data.pop("_fingerprint", None)
    data.pop("_note", None)
    if stamp is not None and stamp == fingerprint(data):
        return {}, False
    return {k: v for k, v in data.items() if k in defaults and v != defaults[k]}, stamp is not None


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


def imported_file():
    """What the launcher copied from the normal FreeCAD profile ("import_preferences"), written at each start."""
    return os.path.join(profile_dir(), IMPORTED_FILE)


def load():
    global _cfg
    cfg = copy.deepcopy(DEFAULTS)
    # imported preferences sit between the defaults and nxstyle.json: what you set in nxstyle.json still decides
    try:
        with open(imported_file(), encoding="utf-8-sig") as f:
            _merge(cfg, json.load(f).get("settings", {}))
    except FileNotFoundError:
        pass
    except (OSError, ValueError, AttributeError) as e:
        App.Console.PrintWarning(f"NXStyle: ignoring unreadable {imported_file()}: {e}\n")
    path = user_file()
    source.clear()
    source.update({"path": path, "exists": os.path.isfile(path), "error": None})
    if source["exists"]:
        try:
            # utf-8-sig: Windows editors may save UTF-8 with a byte order mark, which plain utf-8 refuses
            with open(path, encoding="utf-8-sig") as f:
                own = json.load(f)
            if not isinstance(own, dict):
                raise ValueError("not a JSON object ({...})")
            _merge(cfg, own)
        except (OSError, ValueError) as e:
            source["error"] = str(e)
            App.Console.PrintWarning(f"NXStyle: ignoring unreadable {path}: {e}\n")
    App.Console.PrintMessage(f"NXStyle: settings from {path}\n" if source["exists"] and not source["error"]
                             else f"NXStyle: no settings file read ({path}); defaults apply\n")
    # A reference copy of every setting; nxstyle.json holds only what you change,
    # so new defaults still reach existing profiles.
    reference = os.path.join(profile_dir(), DEFAULTS_FILE)
    edits, certain = defaults_edits(reference)
    if edits:
        source["defaults edited"] = edits
        what = f"was changed ({edits})" if certain else f"lists {edits}, not NX-Style's defaults"
        App.Console.PrintWarning(f"NXStyle: {reference} {what}; that file is only a reference, never read and "
                                 f"rewritten now: put the settings you change in {path}\n")
    try:
        with open(reference, "w", encoding="utf-8") as f:
            json.dump({"_note": DEFAULTS_NOTE, **DEFAULTS, "_fingerprint": fingerprint(DEFAULTS)}, f, indent=2)
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
