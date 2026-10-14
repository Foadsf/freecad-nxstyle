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
        return {"MenuText": self.app["title"], "ToolTip": f"Switch to the {self.app['title']} application"}

    def IsActive(self):
        return True

    def Activated(self):
        from . import shell
        shell.switch_application(self.app["id"])


class RotateMode:
    def GetResources(self):
        return {"MenuText": "Rotate", "ToolTip": "Drag with MB1 to rotate the view; Esc, MB2 or MB3 ends (NX: F7)",
                "Pixmap": _pixmap("Std_ViewRotateRight", "Std_ViewIsometric")}

    def IsActive(self):
        return _view3d() is not None

    def Activated(self):
        from . import shell
        sh = shell.instance()
        if sh is not None:
            nav = sh.navigation
            nav.set_mode(None if nav.mode == "rotate" else "rotate")


class Refresh:
    def GetResources(self):
        return {"MenuText": "Refresh", "ToolTip": "Redraw the graphics window (NX: F5)",
                "Pixmap": _pixmap("Std_Refresh")}

    def IsActive(self):
        return _view3d() is not None

    def Activated(self):
        Gui.Selection.clearPreselection()
        view = _view3d()
        if view is not None:
            view.redraw()


class ToggleSuppress:
    """NX's Suppress / Unsuppress for the selected features. FreeCAD 1.1 has a feature's Suppressed
    property but no command for it (Std_ToggleFreeze only stops an object's recompute)."""

    @staticmethod
    def _features():
        return [s.Object for s in Gui.Selection.getSelectionEx() if "Suppressed" in s.Object.PropertiesList]

    def GetResources(self):
        return {"MenuText": "Suppress", "ToolTip": "Suppress the selected features (again: unsuppress). "
                "A suppressed feature keeps its settings and can be switched back on",
                "Pixmap": config.resource("icons", "suppress.svg")}

    def IsActive(self):
        return bool(self._features())

    def Activated(self):
        feats = self._features()
        if not feats:
            return
        doc = feats[0].Document
        doc.openTransaction("Suppress")
        for f in feats:
            f.Suppressed = not f.Suppressed
        doc.commitTransaction()
        doc.recompute()


class ImmediateHideObserver:
    def __init__(self):
        self.active = False

    def addSelection(self, doc, obj, sub, _pnt=None):
        try:
            d = App.getDocument(doc)
            o = d.getObject(obj)
        except Exception:
            return
        target = o
        # a feature inside a Body is one step of the solid: hide the Body
        if o is not None and o.isDerivedFrom("PartDesign::Feature") and not o.isDerivedFrom("PartDesign::Body"):
            body = o.getParentGeoFeatureGroup()
            target = body or o
        if target is not None and getattr(target, "ViewObject", None) is not None:
            d.openTransaction("Immediate Hide")
            target.ViewObject.Visibility = False
            d.commitTransaction()
        from .qt import QtCore
        QtCore.QTimer.singleShot(0, Gui.Selection.clearSelection)


immediate_hide = ImmediateHideObserver()


def stop_immediate_hide():
    if immediate_hide.active:
        Gui.Selection.removeObserver(immediate_hide)
        immediate_hide.active = False


class ImmediateHide:
    def GetResources(self):
        return {"MenuText": "Immediate Hide", "ToolTip": "Pick objects to hide them at once; Esc finishes (NX: Ctrl+Shift+I)",
                "Pixmap": _pixmap("Std_HideSelection")}

    def IsActive(self):
        return _has_doc()

    def Activated(self):
        if immediate_hide.active:
            stop_immediate_hide()
            return
        sel = Gui.Selection.getSelectionEx("", 0)
        if sel:   # objects already selected: hide those and stay in the mode
            for s in sel:
                immediate_hide.addSelection(s.DocumentName, s.ObjectName, "")
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(immediate_hide)
        immediate_hide.active = True


def object_information():
    """Text for NX's Information window about the current selection."""
    lines = []
    for s in Gui.Selection.getSelectionEx("", 0):
        o = s.Object
        lines.append(f"{o.Label}  ({o.Name})")
        lines.append(f"  Type            {o.TypeId}")
        vo = getattr(o, "ViewObject", None)
        if vo is not None:
            lines.append(f"  Shown           {'yes' if vo.Visibility else 'no'}")
        pl = getattr(o, "Placement", None)
        if pl is not None:
            p, (yaw, pitch, roll) = pl.Base, pl.Rotation.toEuler()
            lines.append(f"  Position        {p.x:.4f}, {p.y:.4f}, {p.z:.4f} mm")
            lines.append(f"  Rotation (YPR)  {yaw:.3f}, {pitch:.3f}, {roll:.3f} deg")
        shape = getattr(o, "Shape", None)
        if shape is not None and not shape.isNull():
            bb = shape.BoundBox
            lines.append(f"  Shape           {shape.ShapeType}: {len(shape.Solids)} solids, {len(shape.Faces)} faces, "
                         f"{len(shape.Edges)} edges, {len(shape.Vertexes)} vertices")
            if shape.Solids:
                lines.append(f"  Volume          {shape.Volume:.4f} mm^3")
            if shape.Faces:
                lines.append(f"  Area            {shape.Area:.4f} mm^2")
            lines.append(f"  Bounding box    {bb.XLength:.4f} x {bb.YLength:.4f} x {bb.ZLength:.4f} mm")
        for name, sub in zip(s.SubElementNames, s.SubObjects):
            if sub.ShapeType == "Face":
                lines.append(f"  {name:<15} area {sub.Area:.4f} mm^2")
            elif sub.ShapeType == "Edge":
                lines.append(f"  {name:<15} length {sub.Length:.4f} mm")
            elif sub.ShapeType == "Vertex":
                pt = sub.Point
                lines.append(f"  {name:<15} at {pt.x:.4f}, {pt.y:.4f}, {pt.z:.4f} mm")
        lines.append("")
    return "\n".join(lines).rstrip()


class ObjectInfo:
    def GetResources(self):
        return {"MenuText": "Object Information", "ToolTip": "Information about the selected objects (NX: Ctrl+I)",
                "Pixmap": _pixmap("Std_WhatsThis", "Std_DlgParameter")}

    def IsActive(self):
        return bool(Gui.Selection.getSelection())

    def Activated(self):
        show_information(object_information())


def show_information(text):
    """NX's Information window: a non-modal text window (also echoed to the Report view)."""
    from .qt import QtCore, QtGui, QtWidgets
    global _info_dialog
    App.Console.PrintMessage("Information\n" + text + "\n")
    if _info_dialog is not None:
        try:
            _info_dialog.close()
        except RuntimeError:
            pass
    dlg = QtWidgets.QDialog(Gui.getMainWindow())
    # deleted when closed: closed-but-kept windows piled up, and the next lookup by name could find a stale
    # one while the live one stayed active and kept NX keys (Ctrl+Shift+D ...) from the main window
    dlg.setAttribute(QtCore.Qt.WA_DeleteOnClose)
    dlg.setObjectName("NXInformation")
    dlg.setWindowTitle("Information")
    dlg.resize(560, 360)
    lay = QtWidgets.QVBoxLayout(dlg)
    box = QtWidgets.QPlainTextEdit(text)
    box.setReadOnly(True)
    box.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont))
    lay.addWidget(box)
    dlg.show()
    _info_dialog = dlg
    return dlg


_info_dialog = None


def density_of(obj):
    """(material name, density in kg/m^3) assigned to obj or its Body, or (None, None)."""
    for o in [obj] + list(getattr(obj, "InList", [])):
        mat = getattr(o, "ShapeMaterial", None)
        if mat is None:
            continue
        rho = None
        try:
            rho = mat.getPhysicalValue("Density")
        except Exception:
            props = getattr(mat, "PhysicalProperties", {}) or {}
            rho = props.get("Density")
        if rho in (None, ""):
            continue
        try:
            q = App.Units.Quantity(rho) if isinstance(rho, str) else rho
            return getattr(mat, "Name", "?"), float(q.getValueAs("kg/m^3"))
        except Exception:
            continue
    return None, None


def measure_bodies(objs):
    """NX Measure Bodies: volume, area, mass (from the assigned material), centre of mass.

    Returns (text, rows); each row is a dict of the numbers for one solid object."""
    rows, lines = [], []
    U = App.Units
    from . import prefs
    names = prefs.unit_schemas()
    current = App.ParamGet(prefs.UNITS).GetInt("UserSchema", 0)
    metric = not (0 <= current < len(names) and prefs.is_imperial(names[current]))
    # values arrive in FreeCAD's internal units: mm³, mm², mm, kg
    kinds = {"volume": (U.Volume, "mm³", 1), "area": (U.Area, "mm²", 1), "length": (U.Length, "mm", 2),
             "mass": (U.Mass, "kg", 4)}

    def q(value, kind):
        unit, label, digits = kinds[kind]
        if metric:   # NX reports a millimetre part in mm³, mm² and kg; FreeCAD would pick ml, cm² or g by size
            return f"{value:,.{digits}f} {label}"
        return U.Quantity(value, unit).UserString

    for o in objs:
        shape = getattr(o, "Shape", None)
        if shape is None or shape.isNull() or not shape.Solids:
            continue
        name, rho = density_of(o)
        vol = shape.Volume                         # mm^3
        mass = vol * 1e-9 * rho if rho else None   # kg
        com = shape.Solids[0].CenterOfMass if len(shape.Solids) == 1 else shape.CenterOfMass
        rows.append({"object": o.Name, "volume_mm3": vol, "area_mm2": shape.Area, "material": name,
                     "density_kg_m3": rho, "mass_kg": mass, "com": (com.x, com.y, com.z)})
        lines += [f"{o.Label}  ({o.Name})",
                  f"  Volume          {q(vol, 'volume')}",
                  f"  Surface area    {q(shape.Area, 'area')}",
                  f"  Material        {name or 'none assigned (Tools > Assign Material)'}"]
        if rho:
            lines += [f"  Density         {rho:g} kg/m³",
                      f"  Mass            {q(mass, 'mass')}"]
        lines += [f"  Centre of mass  {q(com.x, 'length')}, {q(com.y, 'length')}, {q(com.z, 'length')}", ""]
    return "\n".join(lines).rstrip() or "Select a solid body to measure.", rows


last_measure = []


class MeasureBodies:
    def GetResources(self):
        return {"MenuText": "Measure Bodies",
                "ToolTip": "Volume, area, mass and centre of mass of the selected bodies (NX: Analysis > Measure)",
                "Pixmap": _pixmap("Part_CheckGeometry", "Std_MeasureDistance")}

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        global last_measure
        objs = Gui.Selection.getSelection()
        if not objs:
            body = None
            try:
                body = Gui.ActiveDocument.ActiveView.getActiveObject("pdbody")
            except Exception:
                pass
            objs = [body] if body is not None else [o for o in App.ActiveDocument.Objects
                                                    if o.isDerivedFrom("PartDesign::Body")]
        text, last_measure = measure_bodies(objs)
        show_information(text)


class TouchMode:
    def GetResources(self):
        return {"MenuText": "Touch Mode", "ToolTip": "Larger ribbon and bar icons for touch screens (NX: F4)",
                "Pixmap": _pixmap("Std_ViewFitAll")}

    def IsActive(self):
        return True

    def Activated(self):
        from . import shell
        sh = shell.instance()
        if sh is not None:
            sh.set_touch_mode(not sh.touch_mode)


# --------------------------------------------------------------------------
# NX feature workflow: Extrude / Revolve first, sketch inside the command
# --------------------------------------------------------------------------
pending_feature = {"command": None, "sketch": None}


def _selected_sketch():
    for s in Gui.Selection.getSelectionEx("", 0):
        o = s.Object
        if o.isDerivedFrom("Sketcher::SketchObject"):
            return o
        for name in s.SubElementNames:   # Body + "Sketch.Edge1"
            leaf = o.getSubObject(name, 1) if "." in name else None
            if leaf is not None and leaf.isDerivedFrom("Sketcher::SketchObject"):
                return leaf
    return None


class SketchFirstFeature:
    """NX Extrude/Revolve: with a sketch selected the FreeCAD feature starts at
    once; otherwise a sketch is started on the selected face or plane (or
    FreeCAD asks for one), and Finish Sketch carries straight on into the
    feature dialog, as in NX."""

    def __init__(self, target, title, tip, pixmap_from):
        self.target, self.title, self.tip, self.pixmap_from = target, title, tip, pixmap_from

    def GetResources(self):
        return {"MenuText": self.title, "ToolTip": self.tip, "Pixmap": _pixmap(self.pixmap_from)}

    def IsActive(self):
        return _has_doc() and not Gui.Control.activeDialog()

    def Activated(self):
        if _selected_sketch() is not None:
            Gui.runCommand(self.target)
            return
        pending_feature["command"] = self.target
        pending_feature["sketch"] = None
        Gui.runCommand("PartDesign_NewSketch")


def continue_pending_feature(sketch):
    """Called by the shell when a sketch leaves edit mode."""
    cmd = pending_feature["command"]
    pending_feature["command"] = None
    if not cmd or sketch is None or sketch.Document is None:
        return False
    if not sketch.Geometry:          # sketch cancelled or left empty
        return False
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(sketch)
    Gui.runCommand(cmd)
    return True


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
        "NXStyle_RotateMode": RotateMode(),
        "NXStyle_Refresh": Refresh(),
        "NXStyle_ToggleSuppress": ToggleSuppress(),
        "NXStyle_ImmediateHide": ImmediateHide(),
        "NXStyle_ObjectInfo": ObjectInfo(),
        "NXStyle_MeasureBodies": MeasureBodies(),
        "NXStyle_TouchMode": TouchMode(),
        "NXStyle_Extrude": SketchFirstFeature("PartDesign_Pad", "Extrude",
                                              "Extrude a sketch; with nothing selected, sketch first (NX: X)",
                                              "PartDesign_Pad"),
        "NXStyle_ExtrudeSubtract": SketchFirstFeature("PartDesign_Pocket", "Extrude (Subtract)",
                                                      "Extrude a sketch and subtract it", "PartDesign_Pocket"),
        "NXStyle_Revolve": SketchFirstFeature("PartDesign_Revolution", "Revolve",
                                              "Revolve a sketch; with nothing selected, sketch first",
                                              "PartDesign_Revolution"),
        "NXStyle_RevolveSubtract": SketchFirstFeature("PartDesign_Groove", "Revolve (Subtract)",
                                                      "Revolve a sketch and subtract it", "PartDesign_Groove"),
        "NXStyle_Hole": SketchFirstFeature("PartDesign_Hole", "Hole",
                                           "Hole: pick a face or plane, place the hole centres (circles), "
                                           "Finish Sketch continues into the Hole dialog", "PartDesign_Hole"),
    }
    from . import (alignment_ui, claims, clearance, gdt_ui, msa_ui, pmi_ui, package_ui, position_ui, sheetmetal_ui,
                   stackup_ui, titleblock_ui)
    table.update(alignment_ui.COMMANDS)
    table.update(position_ui.COMMANDS)
    table.update(msa_ui.COMMANDS)
    table.update(titleblock_ui.COMMANDS)
    table.update(claims.COMMANDS)
    table.update(clearance.COMMANDS)
    table.update(sheetmetal_ui.COMMANDS)
    table["NXStyle_FeatureControlFrame"] = gdt_ui.FeatureControlFrame()
    table["NXStyle_DatumFeatureSymbol"] = gdt_ui.DatumFeatureSymbol()
    table["NXStyle_ToleranceStackup"] = stackup_ui.ToleranceStackup()
    table.update(pmi_ui.COMMANDS)
    table["NXStyle_PublishPackage"] = package_ui.PublishPackage()
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
