# SPDX-License-Identifier: LGPL-2.1-or-later
"""FreeCAD commands that NX has and FreeCAD does not: Snap View, Invert Shown
and Hidden, Show and Hide, Expressions, Repeat Command, background presets."""

import FreeCAD as App
import FreeCADGui as Gui

from . import config, prefs

last_command = {"name": None}

# Commands that should not become the "Repeat Command" target
NOT_REPEATABLE_PREFIXES = (
    "Std_View", "Std_DrawStyle", "Std_Undo", "Std_Redo", "Std_Workbench", "Std_Toggle",
    "Std_Show", "Std_Hide", "Std_Select", "Std_Sel", "Std_Tree", "Std_Save", "Std_Open",
    "Std_New", "Std_Close", "Std_Quit", "Std_Cut", "Std_Copy", "Std_Paste", "Std_Delete",
    "Std_Activate", "Std_Main", "Std_Tile", "Std_Cascade", "Std_Refresh", "Std_Recent",
    "Std_Dlg", "Std_Python", "Std_Report", "NXStyle_", "Sketcher_LeaveSketch",
    "Std_Measure", "Std_Window", "Std_Edit", "Std_Panel", "Std_Dock", "Std_Bookmark",
)


def remember(name):
    if name and not name.startswith(NOT_REPEATABLE_PREFIXES):
        last_command["name"] = name


def _pixmap(*candidates):
    for c in candidates:
        try:
            pix = Gui.Command.get(c).getInfo().get("pixmap")
            if pix:
                return pix
        except Exception:
            continue
    return ""


def _has_doc():
    return App.ActiveDocument is not None


def _view3d():
    try:
        v = Gui.ActiveDocument.ActiveView
        return v if hasattr(v, "getCameraOrientation") else None
    except Exception:
        return None


# --------------------------------------------------------------------------
# Snap View (NX: F8) - rotate to the closest standard view, or look normal to a
# selected planar face.
# --------------------------------------------------------------------------
AXES = [App.Vector(1, 0, 0), App.Vector(-1, 0, 0), App.Vector(0, 1, 0),
        App.Vector(0, -1, 0), App.Vector(0, 0, 1), App.Vector(0, 0, -1)]


def nearest_standard_rotation(rot):
    """Camera rotation -> rotation of the nearest axis-aligned view."""
    d = rot.multVec(App.Vector(0, 0, -1))
    u = rot.multVec(App.Vector(0, 1, 0))
    dn = max(AXES, key=lambda a: a.dot(d))
    un = max((a for a in AXES if abs(a.dot(dn)) < 1e-9), key=lambda a: a.dot(u))
    z = dn * -1
    y = un
    x = y.cross(z)
    m = App.Matrix(x.x, y.x, z.x, 0,
                   x.y, y.y, z.y, 0,
                   x.z, y.z, z.z, 0,
                   0, 0, 0, 1)
    return App.Placement(m).Rotation


def _selected_planar_face():
    for sel in Gui.Selection.getSelectionEx("", 0):
        for sub in sel.SubObjects:
            try:
                if sub.ShapeType == "Face" and sub.Surface.__class__.__name__ == "Plane":
                    return True
            except Exception:
                continue
    return False


class SnapView:
    def GetResources(self):
        return {"MenuText": "Snap View",
                "ToolTip": "Rotate to the nearest standard view, or normal to a selected planar face (NX: F8)",
                "Pixmap": _pixmap("Std_ViewIsometric")}

    def IsActive(self):
        return _view3d() is not None

    def Activated(self):
        view = _view3d()
        if view is None:
            return
        if _selected_planar_face() and "Std_AlignToSelection" in Gui.listCommands():
            Gui.runCommand("Std_AlignToSelection")
            return
        target = nearest_standard_rotation(view.getCameraOrientation())
        view.setCameraOrientation(target.Q)


# --------------------------------------------------------------------------
# Visibility helpers shared by Invert and the Show and Hide dialog
# --------------------------------------------------------------------------
def _is_origin_child(o):
    return any(p.TypeId == "App::Origin" for p in getattr(o, "InList", []))


def display_objects(doc):
    """Objects the user thinks of as separate things in the graphics window."""
    out = []
    for o in doc.Objects:
        vo = getattr(o, "ViewObject", None)
        if vo is None or _is_origin_child(o):
            continue
        if not (o.isDerivedFrom("App::GeoFeature") or o.TypeId == "App::Origin"):
            continue
        # Features inside a PartDesign Body are steps of one solid, not objects
        if o.isDerivedFrom("PartDesign::Feature") and not o.isDerivedFrom("PartDesign::Body"):
            continue
        out.append(o)
    return out


def category(o):
    tid = o.TypeId
    if o.isDerivedFrom("Sketcher::SketchObject"):
        return "Sketches"
    if tid == "App::Origin" or o.isDerivedFrom("Part::Datum") or tid in ("App::Plane", "App::Line", "App::Point"):
        return "Datums"
    if o.isDerivedFrom("PartDesign::Body"):
        return "Solid Bodies"
    if o.isDerivedFrom("App::Part") or tid == "App::Link":
        return "Components"
    shape = getattr(o, "Shape", None)
    if shape is not None and not shape.isNull():
        if shape.Solids:
            return "Solid Bodies"
        if shape.Faces:
            return "Sheet Bodies"
        if shape.Edges:
            return "Curves"
        if shape.Vertexes:
            return "Points"
    return "Other"


CATEGORIES = ["Solid Bodies", "Sheet Bodies", "Curves", "Points", "Sketches", "Datums", "Components", "Other"]


class InvertVisibility:
    def GetResources(self):
        return {"MenuText": "Invert Shown and Hidden",
                "ToolTip": "Hide what is shown and show what is hidden (NX: Ctrl+Shift+B)",
                "Pixmap": _pixmap("Std_ToggleVisibility")}

    def IsActive(self):
        return _has_doc()

    def Activated(self):
        doc = App.ActiveDocument
        doc.openTransaction("Invert Shown and Hidden")
        for o in display_objects(doc):
            o.ViewObject.Visibility = not o.ViewObject.Visibility
        doc.commitTransaction()


class ShowHide:
    def GetResources(self):
        return {"MenuText": "Show and Hide",
                "ToolTip": "Show or hide objects by type (NX: Ctrl+W)",
                "Pixmap": _pixmap("Std_ShowObjects", "Std_ToggleVisibility")}

    def IsActive(self):
        return _has_doc()

    def Activated(self):
        from . import showhide
        showhide.show_dialog()


class Expressions:
    def GetResources(self):
        return {"MenuText": "Expressions",
                "ToolTip": "Open this part's expression sheet; create it if needed (NX: Ctrl+E)",
                "Pixmap": _pixmap("Spreadsheet_CreateSheet")}

    def IsActive(self):
        return _has_doc()

    def Activated(self):
        doc = App.ActiveDocument
        sheet = doc.getObject("Expressions")
        if sheet is None:
            import Spreadsheet  # noqa: F401  (registers the type)
            doc.openTransaction("Create expression sheet")
            sheet = doc.addObject("Spreadsheet::Sheet", "Expressions")
            sheet.set("A1", "Name")
            sheet.set("B1", "Value")
            doc.commitTransaction()
            doc.recompute()
        try:
            import SpreadsheetGui  # noqa: F401
        except ImportError:
            pass
        sheet.ViewObject.doubleClicked()


class RepeatCommand:
    def GetResources(self):
        return {"MenuText": "Repeat Command",
                "ToolTip": "Run the last modelling command again (NX: F4)",
                "Pixmap": _pixmap("Std_Redo")}

    def IsActive(self):
        name = last_command["name"]
        if not name:
            return False
        try:
            return Gui.Command.get(name).isActive()
        except Exception:
            return False

    def Activated(self):
        if last_command["name"]:
            Gui.runCommand(last_command["name"])


class Background:
    def __init__(self, key):
        self.key = key

    def GetResources(self):
        label = config.BACKGROUNDS[self.key][0]
        return {"MenuText": label, "ToolTip": f"Set the graphics window to {label}"}

    def IsActive(self):
        return True

    def Activated(self):
        prefs.set_background(self.key)
        cfg = config.get()
        cfg["background"] = self.key


class ToggleNativeUI:
    def GetResources(self):
        return {"MenuText": "FreeCAD Menus and Toolbars",
                "ToolTip": "Show or hide FreeCAD's own menu bar and toolbars",
                "Pixmap": _pixmap("Std_DlgCustomize")}

    def IsActive(self):
        return True

    def Activated(self):
        from . import shell
        shell.toggle_native_ui()


class SwitchApplication:
    def __init__(self, app):
        self.app = app

    def GetResources(self):
        res = {"MenuText": self.app["title"],
               "ToolTip": f"Switch to the {self.app['title']} application"}
        if self.app.get("shortcut"):
            res["Accel"] = self.app["shortcut"]
        return res

    def IsActive(self):
        return True

    def Activated(self):
        from . import shell
        shell.switch_application(self.app["id"])


GLOBAL_TOOLBAR = "User parameter:BaseApp/Workbench/Global/Toolbar/Custom_NXStyle"


def register(apps):
    """Register the commands; returns their names."""
    table = {
        "NXStyle_SnapView": SnapView(),
        "NXStyle_InvertVisibility": InvertVisibility(),
        "NXStyle_ShowHide": ShowHide(),
        "NXStyle_Expressions": Expressions(),
        "NXStyle_RepeatCommand": RepeatCommand(),
        "NXStyle_ToggleNativeUI": ToggleNativeUI(),
    }
    for key in config.BACKGROUNDS:
        table[f"NXStyle_Background_{key}"] = Background(key)
    for app in apps:
        table[f"NXStyle_App_{app['id']}"] = SwitchApplication(app)
    for name, cmd in table.items():
        Gui.addCommand(name, cmd)
    # FreeCAD 1.0 creates a Python command's QAction only when the command is
    # placed in a toolbar or menu. A global custom toolbar (hidden by the shell)
    # makes FreeCAD create the actions, so shortcuts and ribbon buttons work.
    p = App.ParamGet(GLOBAL_TOOLBAR)
    p.SetString("Name", "NXStyle Commands")
    p.SetBool("Active", True)
    for name in table:
        p.SetString(name, "FreeCAD")
    return list(table)
