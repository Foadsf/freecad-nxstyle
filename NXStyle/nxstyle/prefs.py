# SPDX-License-Identifier: LGPL-2.1-or-later
"""Write NX-like values into FreeCAD's parameter tree.

The launcher points FreeCAD at a private profile, so these writes land in that
profile's user.cfg and never in the user's normal FreeCAD settings.
"""

import FreeCAD as App
import FreeCADGui as Gui

from . import config

VIEW = "User parameter:BaseApp/Preferences/View"
MAIN = "User parameter:BaseApp/Preferences/MainWindow"
GENERAL = "User parameter:BaseApp/Preferences/General"

NATIVE_NX_STYLE = "Gui::SiemensNXNavigationStyle"   # FreeCAD 1.1+ (PR #21813)
NX_BASE_STYLE = "Gui::BlenderNavigationStyle"       # MB2 rotate, Shift+MB2 pan, wheel zoom


def packed(hexstr):
    """'#RRGGBB' -> FreeCAD's packed 0xRRGGBBAA colour (AA = 0xFF opaque)."""
    h = hexstr.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (r << 24) | (g << 16) | (b << 8) | 0xFF


def freecad_version():
    v = App.Version()
    try:
        return int(v[0]), int(v[1])
    except (ValueError, IndexError):
        return 0, 0


def has_native_nx_style():
    return freecad_version() >= (1, 1)


def navigation_style(cfg):
    choice = cfg.get("navigation", "nx")
    if choice == "native":
        return NATIVE_NX_STYLE if has_native_nx_style() else NX_BASE_STYLE
    if choice == "nx":
        # NXStyle's own event filter handles MB2; Blender style supplies the rest
        return NX_BASE_STYLE
    return choice


def base_stylesheet(cfg):
    """FreeCAD's light stylesheet that the NX theme is layered on."""
    name = cfg.get("stylesheet", "auto")
    if name != "auto":
        return name
    # 1.0 ships one file per theme; 1.1 has one FreeCAD.qss plus a "Theme" parameter
    return "FreeCAD.qss" if freecad_version() >= (1, 1) else "FreeCAD Light.qss"


def uses_own_navigation(cfg=None):
    cfg = cfg or config.get()
    return cfg.get("navigation", "nx") == "nx"


def set_background(name):
    label, top, bottom = config.BACKGROUNDS.get(name, config.BACKGROUNDS["light_gray_gradient"])
    p = App.ParamGet(VIEW)
    if bottom:
        p.SetBool("Simple", False)
        p.SetBool("Gradient", True)
        p.SetBool("RadialGradient", False)
        p.SetBool("UseBackgroundColorMid", False)
        p.SetUnsigned("BackgroundColor2", packed(top))
        p.SetUnsigned("BackgroundColor3", packed(bottom))
    else:
        p.SetBool("Simple", True)
        p.SetBool("Gradient", False)
        p.SetBool("RadialGradient", False)
        p.SetUnsigned("BackgroundColor", packed(top))
    return label


def apply(cfg=None):
    cfg = cfg or config.get()
    v = App.ParamGet(VIEW)
    colors = cfg["colors"]
    set_background(cfg.get("background", "light_gray_gradient"))
    v.SetBool("EnablePreselection", True)
    v.SetBool("EnableSelection", True)
    v.SetUnsigned("HighlightColor", packed(colors["preselection"]))
    v.SetUnsigned("SelectionColor", packed(colors["selection"]))
    v.SetUnsigned("DefaultShapeColor", packed(colors["body"]))
    v.SetUnsigned("DefaultShapeLineColor", packed(colors["edges"]))
    v.SetInt("DefaultShapeLineWidth", int(cfg.get("edge_width", 1)))
    v.SetBool("RandomColor", False)
    # NX shows a view triad in the lower-left corner and no view cube. FreeCAD
    # 1.0 can only draw its triad lower-right, so NXStyle draws its own.
    v.SetBool("ShowNaviCube", False)
    v.SetBool("CornerCoordSystem", cfg.get("view_triad", "nx") == "freecad")
    v.SetBool("ZoomAtCursor", bool(cfg.get("zoom_at_cursor", True)))
    v.SetBool("InvertZoom", bool(cfg.get("invert_wheel_zoom", True)))
    v.SetString("NavigationStyle", navigation_style(cfg))
    # only write when different: FreeCAD 1.1 reloads its stylesheet on every
    # change of these parameters, which would drop the NX layer on top
    main = App.ParamGet(MAIN)
    if main.GetString("StyleSheet") != base_stylesheet(cfg):
        main.SetString("StyleSheet", base_stylesheet(cfg))
    if freecad_version() >= (1, 1) and main.GetString("Theme") != "FreeCAD Light":
        main.SetString("Theme", "FreeCAD Light")
    app = cfg.get("default_application", "modeling")
    wb = {"modeling": "PartDesignWorkbench", "drafting": "TechDrawWorkbench",
          "assemblies": "AssemblyWorkbench"}.get(app, "PartDesignWorkbench")
    App.ParamGet(GENERAL).SetString("AutoloadModule", wb)


def apply_navigation_to_open_views(cfg=None):
    """Set the navigation style on views that already exist."""
    cfg = cfg or config.get()
    style = navigation_style(cfg)
    for gdoc in _gui_documents():
        for view in gdoc.mdiViewsOfType("Gui::View3DInventor"):
            try:
                if view.getNavigationType() != style:
                    view.setNavigationType(style)
            except Exception:
                pass


def _gui_documents():
    for name in App.listDocuments():
        gdoc = Gui.getDocument(name)
        if gdoc:
            yield gdoc
