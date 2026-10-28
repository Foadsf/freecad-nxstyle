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
UNITS = "User parameter:BaseApp/Preferences/Units"
SKETCHER_TOOLS = "User parameter:BaseApp/Preferences/Mod/Sketcher/Tools"
# FreeCAD's Sketcher > On-View-Parameters choice, by index (SketcherSettings.cpp): each tool reads it when it starts
SKETCH_INPUT = {"none": 0, "dimensions": 1, "position": 2}
IMPERIAL_WORDS = ("imperial", "us ", "us customary", "inch", "ft", "feet", "lb")

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


def unit_schemas():
    """FreeCAD's unit schemas by index, as their descriptions ("Standard (mm, kg, s, °)")."""
    try:
        names = App.Units.listSchemas()      # 1.1: internal names ("Internal", "Imperial", ...)
        count = names if isinstance(names, int) else len(names)
        out = []
        for i in range(count):
            try:
                out.append(str(App.Units.listSchemas(i)))
            except Exception:
                out.append(str(names[i]) if not isinstance(names, int) else str(i))
        return out
    except Exception:
        return []


def standard_schema(names):
    """Index of the Standard (mm, kg) schema: FreeCAD calls it 'Standard' or, internally, 'Internal'."""
    for word in ("standard", "internal"):
        for i, n in enumerate(names):
            if n.lower().startswith(word):
                return i
    return 0


def is_imperial(name):
    n = name.lower() + " "
    return any(w in n for w in IMPERIAL_WORDS)


def apply_units(cfg=None):
    """Metric by default: FreeCAD's Standard schema (mm, kg, s, °) unless the setting says otherwise.

    "metric" switches an imperial schema back to Standard and leaves other metric
    schemas (MKS, building, FEM, ...) alone; "freecad" leaves units untouched.
    Returns the schema name in use."""
    cfg = cfg or config.get()
    names = unit_schemas()
    p = App.ParamGet(UNITS)
    current = p.GetInt("UserSchema", 0)
    if cfg.get("units", "metric") == "metric" and names:
        if not (0 <= current < len(names)) or is_imperial(names[current]):
            standard = standard_schema(names)
            p.SetInt("UserSchema", standard)
            try:
                App.Units.setSchema(standard)
            except Exception:
                pass
            current = standard
    return names[current] if 0 <= current < len(names) else ""


def apply(cfg=None):
    cfg = cfg or config.get()
    apply_units(cfg)
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
    # 1.0 can only draw its triad lower-right, so NXStyle draws its own. The
    # launcher hides the view cube in a new profile only (seed_user_cfg): a cube
    # switched on in FreeCAD's Preferences stays on.
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
    apply_sketch_input(cfg)


def apply_sketch_input(cfg=None):
    """NX's sketch curves and points take typed XC/YC coordinates (its on-screen input boxes, and the Point
    dialog): FreeCAD's on-view parameters show positions only with 'Position and dimensions'. Returns the
    index written, or None when the setting leaves FreeCAD's choice alone."""
    cfg = cfg or config.get()
    index = SKETCH_INPUT.get(cfg.get("sketch_input", "position"))
    if index is not None:
        App.ParamGet(SKETCHER_TOOLS).SetInt("OnViewParameterVisibility", index)
    return index


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
