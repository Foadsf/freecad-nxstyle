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
# FreeCAD's navigation styles (src/Gui/Navigation, FreeCAD 1.1.0), by the name its status-bar menu shows, written
# without spaces and in lower case: "navigation": "Touchpad" means Gui::TouchpadNavigationStyle. The launcher reads
# this table too (launch_nx.freecad_styles), so it is a plain literal.
FREECAD_STYLES = {
    "blender": "Gui::BlenderNavigationStyle",
    "cad": "Gui::CADNavigationStyle",
    "gesture": "Gui::GestureNavigationStyle",
    "mayagesture": "Gui::MayaGestureNavigationStyle",
    "opencascade": "Gui::OpenCascadeNavigationStyle",
    "openinventor": "Gui::InventorNavigationStyle",
    "openscad": "Gui::OpenSCADNavigationStyle",
    "revit": "Gui::RevitNavigationStyle",
    "siemensnx": "Gui::SiemensNXNavigationStyle",
    "solidworks": "Gui::SolidWorksNavigationStyle",
    "tinkercad": "Gui::TinkerCADNavigationStyle",
    "touchpad": "Gui::TouchpadNavigationStyle",
}


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


def style_class(name):
    """FreeCAD's class name for a navigation style written as its menu name ("Touchpad", "Siemens NX",
    "OpenInventor") or as the class name itself, in any case; None for a name that is no FreeCAD style."""
    key = "".join(c for c in str(name).lower() if c.isalnum() or c == ":")
    key = key.removeprefix("gui::").removesuffix("navigationstyle")
    if key == "inventor":
        key = "openinventor"
    return FREECAD_STYLES.get(key)


def navigation_style(cfg):
    choice = cfg.get("navigation", "nx")
    if choice == "native":
        return NATIVE_NX_STYLE if has_native_nx_style() else NX_BASE_STYLE
    if choice == "nx":
        # NXStyle's own event filter handles MB2; Blender style supplies the rest
        return NX_BASE_STYLE
    style = style_class(choice)
    if style == NATIVE_NX_STYLE and not has_native_nx_style():
        return NX_BASE_STYLE
    return style or choice       # an unknown name goes to FreeCAD as it is (the launcher warns about it)


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
    seed_orbit_style(cfg)
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


TRACKBALL_CLASSIC = 3          # FreeCAD 1.1's orbit style list: NX's rotation, about the screen's axes


def seed_orbit_style(cfg=None):
    """With NX-Style's own MB2 rotation, give a profile that has no orbit style FreeCAD 1.1's Trackball Classic.
    FreeCAD's Preferences write the orbit style each time they are saved, showing Rounded Arcball when there is
    none (DlgSettingsNavigation, FreeCAD 1.1.0), so pressing OK for any reason would turn MB2 into a trackball;
    seeded, the dialog shows the rotation MB2 has and saving it keeps it. A style already set (chosen, or imported
    from the normal profile) is left alone; FreeCAD 1.0 has no Trackball Classic. Returns the value written or
    None."""
    cfg = cfg or config.get()
    p = App.ParamGet(VIEW)
    if not uses_own_navigation(cfg) or freecad_version() < (1, 1) or p.GetInt("OrbitStyle", -1) >= 0:
        return None
    p.SetInt("OrbitStyle", TRACKBALL_CLASSIC)
    return TRACKBALL_CLASSIC


def apply_sketch_input(cfg=None):
    """NX's sketch curves and points take typed XC/YC coordinates (its on-screen input boxes, and the Point
    dialog): FreeCAD's on-view parameters show positions only with 'Position and dimensions'. Returns the
    index written, or None when the setting leaves FreeCAD's choice alone."""
    cfg = cfg or config.get()
    index = SKETCH_INPUT.get(cfg.get("sketch_input", "position"))
    if index is not None:
        App.ParamGet(SKETCHER_TOOLS).SetInt("OnViewParameterVisibility", index)
    return index


def view_cube_shown():
    """FreeCAD's own view cube (Preferences › Display › Navigation › Navigation Cube) is on."""
    return App.ParamGet(VIEW).GetBool("ShowNaviCube", True)


def show_view_cube(on):
    """Switch FreeCAD's view cube on or off. It is FreeCAD's own preference, so the choice is kept in the
    profile and Preferences shows it; FreeCAD's views follow the parameter, and the ones already open are
    set here as well. Returns the new state."""
    App.ParamGet(VIEW).SetBool("ShowNaviCube", bool(on))
    for gdoc in _gui_documents():
        for view in gdoc.mdiViewsOfType("Gui::View3DInventor"):
            try:
                viewer = view.getViewer()
                if viewer.isEnabledNaviCube() != bool(on):
                    viewer.setEnabledNaviCube(bool(on))
            except Exception:
                pass
    return view_cube_shown()


def apply_navigation_to_view(view, cfg=None):
    """Set the navigation style nxstyle.json names on one 3D view, if it runs another."""
    style = navigation_style(cfg or config.get())
    try:
        if view.getNavigationType() != style:
            view.setNavigationType(style)
    except Exception:
        pass


def apply_navigation_to_open_views(cfg=None):
    """Set the navigation style on views that already exist (at start-up)."""
    for gdoc in _gui_documents():
        for view in gdoc.mdiViewsOfType("Gui::View3DInventor"):
            apply_navigation_to_view(view, cfg)


def _gui_documents():
    for name in App.listDocuments():
        gdoc = Gui.getDocument(name)
        if gdoc:
            yield gdoc
